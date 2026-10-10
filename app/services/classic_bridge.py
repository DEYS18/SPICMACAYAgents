"""
The original conversational agent (app/models/agent.py) is the main assistant: its conversation flow, its
instructions (word for word), its Hindi welcome and its screen are kept. This bridge improves what happens
underneath, at the two services it calls, without changing what it says or how it asks:

- directory searches (DatabaseValidator.search_artists / search_institutions / search_coordinators) use the
  stronger search engine (spelling variants, Indian scripts, abbreviations, campuses, deceased flags) and
  return the same fields as before, plus a "note" when the coordinator needs to choose (DC3, DC4, DC10);
- create_event accepts any date format (DC1) and stores the module and the institution as the portal does;
- create_apr / create_apr_for_group also write the portal's own records (custom_apr, and event_series for a
  circuit or Virasat), so the APR appears in the portal; the old apr_payment_request rows are still written
  and carry the portal's APR number;
- an artist added in conversation is provisional until the Artist Care Group approves it (DC8).
Everything falls back to the original behaviour if anything goes wrong, so filing never breaks because of it.
"""
import logging
from datetime import date

logger = logging.getLogger(__name__)


def install(app, services):
    """Connect the original agent's services to the improved engine (called once at startup)."""
    if getattr(app, 'db_validator', None) is not None:
        app.db_validator.directory = services.index
    if getattr(app, 'event_service', None) is not None:
        app.event_service.portal = services
    logger.info('Original assistant connected to the improved search and portal records')


def _services(obj):
    return getattr(obj, 'portal', None)


# ── searches: same fields as the original, better matches, a note when a choice is needed ─────────────
def artists(index, term):
    try:
        r = index.search_artists(term or '')
    except Exception as e:
        logger.warning('Improved artist search failed (%s); using the original search', e)
        return None
    if not r.get('matches'):
        return None                                   # let the original search have its say
    rows = []
    for m in r['matches'][:10]:
        row = {'tid': m['tid'], 'name': m['name'], 'art_form': m.get('art_form'), 'artist_type': m.get('artist_type'),
               'artist_grade': m.get('grade'), 'city': m.get('city'), 'enter_state': m.get('state'), 'email': m.get('email'),
               'phone': m.get('phone'), 'relevance': m.get('score')}
        notes = []
        if 'deceased' in (m.get('flags') or []):
            notes.append('marked in the directory as having passed away: tell the coordinator gently and ask whether they mean someone else')
        if len(m.get('art_forms') or []) > 1:
            row['art_forms'] = m['art_forms']
            notes.append('has several art forms: ask which one applies to this program')
        if m.get('provisional'):
            notes.append('provisional record, awaiting Artist Care Group approval')
        if notes:
            row['note'] = '; '.join(notes)
        rows.append(row)
    if r.get('ambiguous') and len(rows) > 1:
        for row in rows[:3]:
            row['note'] = '; '.join(x for x in (row.get('note'), 'several artists have a similar name: ask the coordinator which one '
                                                                 '(art form or city)') if x)
    elif r.get('best'):
        rows[0]['best_match'] = True
    return rows


def institutions(index, term, state=None):
    try:
        r = index.search_institutions(term or '', state=state)
    except Exception as e:
        logger.warning('Improved institution search failed (%s); using the original search', e)
        return None
    pool = r.get('campus_choices') or r.get('matches') or []
    if not pool:
        return None
    rows = []
    for m in pool[:10]:
        row = {'sid': m['sid'], 'institution_name': m['institution_name'], 'city': m.get('city'), 'state': m.get('state'),
               'pincode': m.get('pincode'), 'email': m.get('email'), 'phone': m.get('phone'), 'address': m.get('address'),
               'relevance': m.get('score')}
        if r.get('campus_choices'):
            row['note'] = 'one of several campuses or branches with this name: ask the coordinator which one'
        elif r.get('ambiguous'):
            row['note'] = 'several institutions have a similar name: ask the coordinator which one (city)'
        rows.append(row)
    if r.get('best') and not r.get('campus_choices'):
        rows[0]['best_match'] = True
    return rows


def coordinators(index, name):
    try:
        r = index.search_coordinators(name or '')
    except Exception as e:
        logger.warning('Improved coordinator search failed (%s); using the original search', e)
        return None
    matches = r.get('matches') if isinstance(r, dict) else r
    if not matches:
        return None
    return [{'source': m.get('source', 'user'), 'uid': m.get('uid'), 'name': m.get('name'), 'email': m.get('email'),
             'institution_name': m.get('institution_name'), 'relevance': m.get('score')} for m in matches[:8]]


# ── events: any date format; module and institution as the portal stores them ──────────────────────
def iso_date(value):
    if not value:
        return value
    try:
        from app.core import dates as dt
        p = dt.parse_date(str(value))
        return p.iso if p else value
    except Exception:
        return value


def institution_value(es, event_data):
    s = _services(es)
    name = (event_data.get('institution_name') or '').strip()
    if s and s.setting('db.store_institution_as', 'name') == 'name' and name:
        return name
    return str(event_data.get('institution_id', ''))


# ── APRs: the portal's own records as well ──────────────────────────────────────────────────────────
def use_portal_number(es):
    s = _services(es)
    return bool(s) and s.setting('apr.number_scheme', 'portal') == 'portal' and bool(s.setting('apr.write_portal_records', True))


def _coordinator_ids(es, event_data, uid):
    ids = [str(uid)] if str(uid or '').isdigit() else []
    emails = [event_data.get('coordinator_email')] + [c.get('email') for c in (event_data.get('coordinators') or []) if isinstance(c, dict)]
    for email in [e for e in emails if e]:
        try:
            row = es.db.fetch_one('SELECT uid FROM users_field_data WHERE mail = %s AND status = 1', (email.strip(),))
            if row and str(row['uid']) not in ids:
                ids.append(str(row['uid']))
        except Exception:
            pass
    return ','.join(ids) or None


def _custom_apr(es, s, type_id, group, ids, event_data, uid):
    res = es.db.execute_query(
        'INSERT INTO custom_apr (coordinators_id, event_series, eventgroup, event_id, additional_message, created_by, dt_created, '
        "del, final_submit, added_by) VALUES (%s,%s,%s,%s,%s,%s,%s,0,1,'event_list')",
        (_coordinator_ids(es, event_data, uid), type_id, str(group), ids, event_data.get('notes') or event_data.get('additional_message') or None,
         str(uid) if str(uid or '').isdigit() else None, date.today().isoformat()), commit=True)
    if isinstance(res, dict) and res.get('success') and res.get('lastrowid'):
        return str(res['lastrowid'])
    logger.warning('Portal APR record not written: %s', (res or {}).get('error') if isinstance(res, dict) else res)
    return None


def portal_single(es, event_id, event_data):
    s = _services(es)
    if not s or not s.setting('apr.write_portal_records', True):
        return None
    try:
        type_id = s.writer.program_type_id('single') if s.writer else '289'
        return _custom_apr(es, s, type_id, event_id, str(event_id), event_data, es._added_by_value(event_data))
    except Exception as e:
        logger.warning('Portal APR record for event %s failed: %s', event_id, e)
        return None


def portal_group(es, event_ids, event_data):
    s = _services(es)
    if not s or not s.setting('apr.write_portal_records', True) or not event_ids:
        return None
    try:
        marks = ','.join(['%s'] * len(event_ids))
        rows = es.db.fetch_all(f'SELECT id, title, start_date, event_time, end_time, institution, city, state, budget '
                               f'FROM event_list WHERE id IN ({marks}) ORDER BY start_date, id', tuple(event_ids)) or []
        places = list(dict.fromkeys(str(r.get('institution') or '') for r in rows))
        ptype = event_data.get('program_type') if event_data.get('program_type') in ('circuit', 'virasat') else \
            ('virasat' if len(places) <= 1 else 'circuit')
        type_id = s.writer.program_type_id(ptype) if s.writer else {'circuit': '288', 'virasat': '291'}[ptype]
        days = sorted(str(r['start_date'])[:10] for r in rows if r.get('start_date'))
        uid = es._added_by_value(event_data)
        ids = ','.join(str(i) for i in event_ids)
        first = rows[0] if rows else {}
        title = event_data.get('program_title') or event_data.get('title') or first.get('title') or ptype.title()
        done = bool(days) and all(d <= date.today().isoformat() for d in days)
        res = es.db.execute_query(
            'INSERT INTO event_series (event_type, title, start_date, end_date, event_time, end_time, state, city, summary, added_date, '
            'added_by, status, institution, event_id, event_status, budget, poww, amount_paid, partially_amt) '
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,%s,%s,%s,%s,0,'',0)",
            (type_id, title, days[0] if days else None, days[-1] if days else None, first.get('event_time') or '', first.get('end_time') or '',
             first.get('state') or '', ', '.join(dict.fromkeys(r.get('city') for r in rows if r.get('city'))),
             f'{len(event_ids)} events filed through the APR Assistant', date.today().isoformat(), str(uid or '')[:50],
             ', '.join(p for p in places if p), ids, 'Completed' if done else 'Pending', sum(float(r.get('budget') or 0) for r in rows)),
            commit=True)
        series_id = res.get('lastrowid') if isinstance(res, dict) and res.get('success') else None
        if series_id:
            es.db.execute_query(f'UPDATE event_list SET added_from = %s WHERE id IN ({marks})', (series_id, *event_ids), commit=True)
        return _custom_apr(es, s, type_id, series_id or event_ids[0], ids, event_data, uid)
    except Exception as e:
        logger.warning('Portal records for events %s failed: %s', event_ids, e)
        return None


# ── new artists: provisional until approved (DC8) ──────────────────────────────────────────────────
def artist_added(es, artist_id, artist_data):
    s = _services(es)
    if not s or not artist_id:
        return
    try:
        es.db.execute_query("UPDATE artists_list SET added_by = 'AI-PROV' WHERE tid = %s", (artist_id,), commit=True)
        payload = {k: artist_data.get(k) for k in ('name', 'art_form', 'city', 'state', 'email', 'phone')}
        payload['role'] = artist_data.get('role') or 'not stated'
        payload['program'] = 'added in the conversational assistant'
        s.gov.add_approval('artist', artist_id, payload, 'assistant')
        from app.agents.state import ConversationState
        from app.skills.base import SkillContext, notify
        ctx = SkillContext(s, ConversationState(), actor={'email': artist_data.get('coordinator_email') or ''}, via='classic')
        notify(ctx, 'email.acg_new_artist', s.setting('artists.acg_email', []),
               {'artist': dict(payload, role=str(payload['role']).title()), 'program_summary': ''})
        s.index.invalidate()
    except Exception as e:
        logger.warning('Provisional marking for artist %s failed: %s', artist_id, e)


# ── the reviewer's points, added after the original instructions (which stay word for word) ─────────
def prompt_addendum():
    return """

ADDITIONS (October 2026, from the review of this assistant; follow them together with everything above):
- Search results may carry a "note". Act on it: if an artist is marked as having passed away, say so gently and ask whether
  the coordinator means someone else; if several artists, institutions or campuses fit, ask which one (art form, city or
  campus) before using it; if an artist has several art forms, ask which one applies. A result marked best_match is the one
  the directory is confident about: confirm it in passing.
- Coordinators may give dates in any format (15-10-2026, 15 Oct, next Friday, कल). Convert them to YYYY-MM-DD yourself
  (other formats are also accepted), and when confirming, read the date back with the weekday, e.g. "15 Oct 2026 (Thu)".
- When adding a new artist, always ask whether they are the main or an accompanying artist, and mention that the record stays
  provisional until the Artist Care Group approves it; the program can go ahead meanwhile.
- More than one coordinator may be associated with a program: ask once whether anyone else should be on the APR.
- In a circuit, once all the stops are known, ask once whether any stop has a different accompanying artist, time or
  contribution.
- Use the portal's module names as get_event_modules returns them (for example Full Concert, Lecture Demonstration, Workshops).
- Each output can be asked for on its own or together, for a new program or one already filed: the APR (create_event), the
  Request for Payment (send_payment_reminder), the pre-event guidelines (send_pre_event_guidelines), a poster (generate_poster).
  Do exactly what they ask, in one conversation, never making them start again. For the APR and the Request for Payment
  together, file the APR first, then confirm the institute's email and amount and send it for the new program's event_id.
  For a program already filed, find it first (list_programs or list_pending_payments) instead of collecting its details again.
"""
