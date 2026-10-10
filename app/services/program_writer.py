"""
Writes a confirmed program into the portal database the way the portal itself records it, in ONE transaction:

- event_series: the program record for a circuit or Virasat. event_type is the portal's program-type term
  (production: Circuit 288, Single Event 289, Viraasat Series 291), read from taxonomy_term_field_data.
- event_list: one row per event. As the portal does: institution by NAME, artist and accompanying artists by id,
  the module as its event_module id, and added_from pointing at the program.
- custom_apr: the APR itself. Its id is the APR number the portal shows. It holds the comma-separated event ids,
  the coordinators' user ids and the program type and group, and is submitted (final_submit = 1) to await the
  portal's approval (apr_status stays empty until someone accepts or rejects it there).
- apr_payment_request: ALSO, exactly the per-event rows the previous version wrote (same request_id format, shared
  reference, start time in time_duration), so its dashboard, payment reminders, resend and reports keep working.
  Both record types are written by default; each has its own switch in Admin > Settings > APR.

Every id comes from AUTO_INCREMENT, so the portal's own inserts and the assistant's never collide. Text for the
portal's latin1 tables is made latin1-safe first: under MariaDB strict mode one unrepresentable character
(Devanagari, the rupee sign) would otherwise reject the whole filing. Either everything is written or nothing is.
"""
import json
import logging
import re
import threading
import uuid
from datetime import date, datetime

from app.core import text_utils as tu

logger = logging.getLogger(__name__)
L = tu.latin1_safe
PROGRAM_TYPE_FALLBACK = {'single': '289', 'circuit': '288', 'virasat': '291'}
_TYPE_NAMES = {'single': ('single event', 'single'), 'circuit': ('circuit',),
               'virasat': ('viraasat series', 'virasat series', 'viraasat', 'virasat')}
# how coordinators and posters word a module -> the portal's module names, tried in order
MODULE_ALIASES = {'concert': ('full concert', 'concert'), 'workshop': ('workshops', 'workshop'),
                  'yoga': ('yoga & meditation', 'yoga and meditation', 'yoga')}


def module_key(name):
    """Names that mean the same module: case, punctuation, '&' or 'and', and singular or plural don't matter."""
    s = re.sub(r'[^a-z0-9 ]', ' ', str(name or '').lower().replace('&', ' and '))
    return ' '.join(w[:-1] if len(w) > 3 and w.endswith('s') else w for w in s.split())


def _first(cur):
    rows = cur.fetchall()
    return rows[0] if rows else {}


class ProgramWriter:
    LOCK = 'spicmacay_ai_writer'

    def __init__(self, db, governance):
        self.db, self.gov = db, governance
        self._modules = self._types = None
        self._lock, self._added = threading.Lock(), set()

    def reset_cache(self):
        self._modules = self._types = None

    def _module_rows(self):
        try:
            return self.db.fetch_all('SELECT tid, name, status FROM event_module') or []
        except Exception:
            return []

    def modules(self):
        if self._modules is None:
            with self._lock:
                rows = self._module_rows()
                if rows and self._add_missing_modules(rows):
                    rows = self._module_rows()
                self._modules = [(str(r['tid']), r['name']) for r in rows if r.get('name') and str(r.get('status', 1)) == '1']
        return self._modules

    def _add_missing_modules(self, rows):
        """Add the modules listed in Admin > Settings > APR that the portal lacks (agreed with SPIC MACAY, October 2026).
        Only rows in event_module are added; nothing in the database structure changes."""
        wanted = self.gov.get_setting('db.ensure_modules', ['Workshops', 'Yoga & Meditation']) or []
        if isinstance(wanted, str):
            wanted = [w.strip() for w in wanted.split(',') if w.strip()]
        have = {module_key(r.get('name')) for r in rows if r.get('name')}      # includes switched-off modules
        added = False
        for name in wanted:
            key = module_key(name)
            if not key or key in have or key in self._added:
                continue
            self._added.add(key)
            res = self.db.execute_query('INSERT INTO event_module (name, status) VALUES (%s, 1)', (tu.latin1_safe(name, 255),), commit=True)
            if isinstance(res, dict) and res.get('success') is False:
                logger.warning('Could not add module %r to event_module: %s', name, res.get('error'))
                continue
            added = True
            logger.info('Added module %r to event_module', name)
            try:
                self.gov.audit('system', 'portal.module_added', name, {'tid': (res or {}).get('lastrowid') if isinstance(res, dict) else None})
            except Exception:
                pass
        return added

    def module_lookup(self, name):
        """(tid, portal name) for a module however it is worded, or (None, None) when the portal has no such module."""
        if not name:
            return None, None
        mods = self.modules()
        if not mods:
            return None, None
        key = ' '.join(str(name).lower().replace('-', ' ').split())
        by_name = {m.lower(): (t, m) for t, m in mods}
        if key in by_name:
            return by_name[key]
        for alias in MODULE_ALIASES.get(key, ()):
            if alias in by_name:
                return by_name[alias]
        nt, best, score = tu.plain_tokens(name), (None, None), 0.0
        for t, m in mods:
            s = tu.name_similarity(nt, tu.plain_tokens(m))
            if s > score:
                best, score = (t, m), s
        return best if score >= 0.85 else (None, None)

    def module_value(self, name, store_as='tid'):
        if not name or store_as == 'name':
            return name or ''
        tid, _ = self.module_lookup(name)
        return tid or name

    def program_type_id(self, ptype, setting=None):
        ptype = ptype if ptype in PROGRAM_TYPE_FALLBACK else 'single'
        override = (setting or self.gov.get_setting)('apr.program_type_ids', '')
        if override:
            try:
                v = (json.loads(override) if isinstance(override, str) else override).get(ptype)
                if v:
                    return str(v)
            except Exception:
                logger.warning('apr.program_type_ids is not valid JSON')
        if self._types is None:
            self._types = {}
            try:
                rows = self.db.fetch_all("SELECT tid, name FROM taxonomy_term_field_data WHERE vid = 'events'") or []
                for p, names in _TYPE_NAMES.items():
                    hit = next((str(r['tid']) for n in names for r in rows if (r.get('name') or '').strip().lower() == n), None)
                    if hit:
                        self._types[p] = hit
            except Exception as e:
                logger.info('Program types not readable (%s); using the production ids', e)
        return self._types.get(ptype) or PROGRAM_TYPE_FALLBACK[ptype]

    @staticmethod
    def fy(d):
        return f'{d.year}-{d.year + 1}' if d.month >= 4 else f'{d.year - 1}-{d.year}'

    def _sequence_number(self, cur):
        best = 0
        for table in ('apr_payment_request', 'apr_payment_request2'):
            try:
                cur.execute(f'SELECT custom_apr FROM {table} WHERE custom_apr IS NOT NULL')
                for r in cur.fetchall():
                    v = str(r.get('custom_apr') or '').strip()
                    if v.isdigit():
                        best = max(best, int(v))
            except Exception as e:
                logger.info('APR numbering: %s unavailable (%s)', table, e)
        return max(best + 1, int(self.gov.get_setting('apr.number_start', 1) or 1))

    def find_existing(self, date_iso, artist_id, institution_id=None, institution_name=None):
        """Event ids already in the portal for this artist, date and institution (so a batch never files twice)."""
        if not (date_iso and artist_id):
            return []
        rows = self.db.fetch_all('SELECT id, institution FROM event_list WHERE start_date = %s AND artist = %s AND status = 1',
                                 (date_iso, str(artist_id))) or []
        keys = {str(institution_id or '').strip(), (L(institution_name) or '').strip().lower()} - {''}
        return [r['id'] for r in rows if not keys or str(r.get('institution') or '').strip().lower() in keys]

    def create(self, draft: dict, uid=None, settings=None) -> dict:
        setting = settings or self.gov.get_setting
        scheme = setting('apr.number_scheme', 'portal')
        store_as = setting('db.store_module_as', 'tid')
        today, now_s = date.today(), date.today().isoformat()
        coords = draft['coordinators']
        filer = next((c for c in coords if c.get('role') == 'filer'), (coords or [{}])[0])
        uid = uid or filer.get('uid')
        added_by = str(uid) if uid else L(filer.get('name') or filer.get('email') or 'AI', 50)
        coord_ids = ','.join(dict.fromkeys(str(c['uid']) for c in [filer] + list(coords) if c.get('uid')))
        ptype = draft.get('program_type') or 'single'
        prog_main, evs = draft.get('main_artist'), draft['events']
        audience_default = draft.get('audience_default') or 300
        notes = draft.get('notes') or ''
        rows = []
        for e in evs:
            arts = e['artists'] if e.get('artists') is not None else ([prog_main] if prog_main else []) + list(draft.get('accompanying') or [])
            main = next((a for a in arts if a.get('role') == 'main'), {}) or {}
            asked = e.get('module') or draft.get('module') or ''
            tid, portal_name = self.module_lookup(asked)
            contrib = e.get('contribution')
            rows.append({'e': e, 'd': datetime.strptime(e['date'], '%Y-%m-%d').date(), 'main': main, 'label': portal_name or asked,
                         'category': str((tid if (tid and store_as != 'name') else (portal_name or asked)) or '')[:50],
                         'acc': ','.join(str(a['artist_id']) for a in arts if a.get('role') != 'main' and str(a.get('artist_id') or '').isdigit())[:255],
                         'start': e.get('start_time') or draft.get('start_time') or '', 'end': e.get('end_time') or draft.get('end_time') or '',
                         'budget': contrib if isinstance(contrib, (int, float)) else 0,
                         'audience': str(e.get('audience_students') or audience_default)})
        portal = bool(setting('apr.write_portal_records', True))
        legacy_rows = bool(setting('apr.write_ai_request_rows', True))
        if not (portal or legacy_rows):
            raise ValueError('Both APR record types are switched off (Admin > Settings > APR), so nothing would record this APR.')
        if scheme == 'portal' and not portal:
            scheme = 'sequence'                      # the portal number exists only with the portal record
        inst_as = setting('db.store_institution_as', 'name')
        multi = portal and ptype in ('circuit', 'virasat') and setting('apr.write_event_series', True)
        type_id = self.program_type_id(ptype, setting)
        institutions = list(dict.fromkeys(L(r['e'].get('institution_name') or '') for r in rows))
        with self.db.transaction() as cur:
            cur.execute('SELECT GET_LOCK(%s, 15) AS got', (self.LOCK,))
            _first(cur)
            try:
                series_id = None
                if multi:
                    dates = sorted(r['e']['date'] for r in rows)
                    main = prog_main or rows[0]['main'] or {}
                    stitle = draft.get('title') or (f"Circuit by {main.get('name') or ''}" if ptype == 'circuit'
                                                    else f"Viraasat Series at {institutions[0] if institutions else ''}")
                    cur.execute('INSERT INTO event_series (event_type, title, start_date, end_date, event_time, end_time, state, city, summary, '
                                'added_date, added_by, status, institution, event_id, event_status, budget, poww, amount_paid, partially_amt) '
                                'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,%s,%s,%s,%s,0,%s,0)',
                                (type_id, L(stitle), dates[0], dates[-1], (draft.get('start_time') or rows[0]['start'])[:50],
                                 (draft.get('end_time') or rows[0]['end'])[:50], L(rows[0]['e'].get('state') or '', 50),
                                 L(', '.join(dict.fromkeys(r['e'].get('city') for r in rows if r['e'].get('city')))),
                                 L(notes or f'{len(rows)} events filed through the APR Assistant'), now_s, added_by[:50], L(', '.join(institutions)),
                                 '', 'Completed' if all(r['d'] <= today for r in rows) else 'Pending', sum(r['budget'] for r in rows), ''))
                    series_id = cur.lastrowid
                event_ids = []
                for r in rows:
                    e, main = r['e'], r['main']
                    title = draft.get('title') or f"{r['label'] or 'Programme'} by {main.get('name') or ''}".strip()
                    cur.execute('INSERT INTO event_list (title, start_date, end_date, event_time, end_time, event_category, state, city, summary, '
                                'institution, artist, accompanying_artist, venue, attendees, budget, added_by, added_date, event_status, status, '
                                'poww, added_from, fy) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,0,%s,%s)',
                                (L(title, 255), e['date'], e.get('end_date') or e['date'], r['start'][:50], r['end'][:20], r['category'],
                                 L(e.get('state') or '', 50), L(e.get('city') or '', 255), L(notes) or None,
                                 (str(e.get('institution_id')) if inst_as == 'id' and e.get('institution_id') else L(e.get('institution_name') or '', 255)),
                                 str(main.get('artist_id') or '')[:255], r['acc'], L(e.get('venue') or '') or None, r['audience'][:50], r['budget'],
                                 added_by[:50], now_s, 'Completed' if r['d'] <= today else 'Pending', series_id or 0, self.fy(r['d'])))
                    event_ids.append(cur.lastrowid)
                ids = ','.join(str(i) for i in event_ids)
                if len(ids) > 255:
                    raise ValueError('Too many events for one APR: the portal keeps up to 255 characters of event ids. Split the program into two APRs.')
                if series_id:
                    cur.execute('UPDATE event_series SET event_id = %s WHERE id = %s', (ids, series_id))
                portal_id = None
                if portal:
                    cur.execute('INSERT INTO custom_apr (coordinators_id, event_series, eventgroup, event_id, additional_message, created_by, '
                                "dt_created, del, final_submit, added_by) VALUES (%s,%s,%s,%s,%s,%s,%s,0,1,'event_list')",
                                (coord_ids or None, type_id, str(series_id or event_ids[0]), ids, notes or None, str(uid) if uid else None, now_s))
                    portal_id = str(cur.lastrowid)
                if scheme == 'portal':
                    number = portal_id
                elif scheme == 'legacy':
                    number = f'APR-{event_ids[0]}-{today:%Y%m%d}'
                else:
                    number = str(self._sequence_number(cur))
                # The same request_id format as the previous version (EventService._generate_request_id)
                request_id = f"REQ-{datetime.now():%Y%m%d%H%M%S}-{uuid.uuid4().hex[:6].upper()}"
                if legacy_rows:
                    # Exactly the rows the previous version wrote (EventService.create_apr / create_apr_for_group):
                    # one per event, sharing request_id and custom_apr; time_duration holds the start time.
                    for eid, r in zip(event_ids, rows):
                        e = r['e']
                        cur.execute('INSERT INTO apr_payment_request (request_id, artist_id, event_id, custom_apr, event_date, time_duration, '
                                    'institution, chapter, students, fc, created_by, dt_created, del, updated_by) '
                                    'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0,%s)',
                                    (request_id, str(r['main'].get('artist_id') or '')[:50], str(eid), number[:50], e['date'],
                                     r['start'][:50], L(e.get('institution_name') or ''), L(draft.get('chapter') or '', 255),
                                     r['audience'][:255], '', added_by[:50], now_s, added_by[:50]))
            finally:
                try:
                    cur.execute('SELECT RELEASE_LOCK(%s) AS rel', (self.LOCK,))
                    _first(cur)
                except Exception:
                    pass
        return {'event_ids': event_ids, 'request_id': request_id, 'custom_apr': number, 'apr_number': number,
                'portal_apr_id': portal_id, 'series_id': series_id, 'program_type_id': type_id,
                'wrote': {'custom_apr': bool(portal_id), 'event_series': bool(series_id), 'apr_payment_request': legacy_rows}}
