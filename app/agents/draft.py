"""
The program draft: the single source of truth while a coordinator builds a program.

Every skill reads and writes this structure, the interface renders it live, and the
assistant receives a compact copy on every turn, so nothing has to be remembered from chat
history and nothing is asked twice. A program holds one or more events (reviewer comments
DC2 and DC5):
  single  = one event
  virasat = several events at one institution, often different artists (incl. Mini Virasat)
  circuit = the same main artist visiting several institutions
"""
import copy
from datetime import timedelta

from app.core import dates as dt
from app.core import text_utils as tu

PROGRAM_TYPES = {'single': 'Single Event', 'virasat': 'Virasat', 'circuit': 'Circuit'}
PROGRAM_FIELDS = ('program_type', 'title', 'module', 'start_time', 'end_time', 'chapter', 'notes',
                  'payment_required', 'audience_default')
EVENT_FIELDS = ('date', 'end_date', 'start_time', 'end_time', 'module', 'institution_id', 'institution_name', 'city', 'state',
                'contact_name', 'contact_phone', 'institution_email', 'audience_students', 'audience_other',
                'contribution', 'venue', 'notes')
OUTPUT_KEYS = ('apr', 'poster', 'payment_request', 'guidelines')
MAX_DAYS = 14     # longest date range expanded into daily rows; longer is almost certainly a typo
_MODULE_ALIASES = {
    'lec dem': 'Lecture Demonstration', 'lecdem': 'Lecture Demonstration', 'lecture demo': 'Lecture Demonstration',
    'lecture demonstration': 'Lecture Demonstration', 'ld': 'Lecture Demonstration', 'concert': 'Concert',
    'recital': 'Concert', 'workshop': 'Workshop', 'baithak': 'Baithak', 'intensive': 'Intensive',
    'heritage walk': 'Heritage Walk', 'cinema classic': 'Cinema Classic', 'yoga': 'Yoga',
    'talk': 'Talk', 'convention': 'Convention', 'online session': 'Online Session',
}
_TYPE_ALIASES = {'single program': 'single', 'single event': 'single', 'one': 'single', 'mini virasat': 'virasat',
                 'mini-virasat': 'virasat', 'festival': 'virasat', 'tour': 'circuit', 'series': 'circuit'}


_MODULE_KEYWORDS = (     # how posters word it -> the portal's module; first match wins
    (('lecture demonstration', 'lec dem', 'lecdem', 'lecture demo'), 'Lecture Demonstration'),
    (('screening', 'movie', 'film', 'cinema'), 'Cinema Classic'),
    (('workshop', 'intensive'), 'Workshop'),
    (('baithak',), 'Baithak'), (('heritage walk',), 'Heritage Walk'), (('yoga',), 'Yoga'),
    (('concert', 'recital', 'performance', 'jugalbandi'), 'Concert'),
    (('talk', 'lecture'), 'Talk'),
)


def normalize_module(v):
    s = ' '.join(str(v or '').replace('-', ' ').split()).strip()
    if not s:
        return None
    key = s.lower()
    hit = _MODULE_ALIASES.get(key) or _MODULE_ALIASES.get(key.replace(' ', ''))
    if hit:
        return hit
    for words, name in _MODULE_KEYWORDS:
        if any(w in key for w in words):
            return name
    return s.title()


def span_days(e):
    start, end = dt._as_date(e.get('date')), dt._as_date(e.get('end_date'))
    return (end - start).days + 1 if start and end and end > start else 1


def expand_days(draft):
    """One portal row per day: an event running several days becomes one event per date (same times,
    module, institution and artists). Returns the expanded draft and {original index: [new indices]}."""
    src = draft.to_dict()
    events, mapping = [], {}
    for i, e in enumerate(src['events']):
        n = span_days(e)
        if n < 2 or n > MAX_DAYS:
            mapping[i] = [len(events)]
            events.append(e)
            continue
        start, mapping[i] = dt._as_date(e['date']), []
        for k in range(n):
            day = start + timedelta(days=k)
            ev = copy.deepcopy(e)
            ev.update(date=day.isoformat(), date_display=dt.display_date(day), end_date=None)
            mapping[i].append(len(events))
            events.append(ev)
    src['events'] = events
    return ProgramDraft(src), mapping


def _blank_event():
    ev = {k: None for k in EVENT_FIELDS}
    ev.update({'date_display': None, 'artists': None})
    return ev


def _issue(field, message, severity='required', event_index=None):
    return {'field': field, 'message': message, 'severity': severity, 'event_index': event_index}


def _same_artist(a, b):
    if a.get('artist_id') and b.get('artist_id'):
        return str(a['artist_id']) == str(b['artist_id'])
    return tu.normalize(a.get('name')) == tu.normalize(b.get('name'))


def artists_text(arts) -> str:
    main = [a['name'] for a in arts if a.get('role') == 'main' and a.get('name')]
    acc = [a['name'] for a in arts if a.get('role') != 'main' and a.get('name')]
    s = ', '.join(main)
    return f"{s} with {', '.join(acc)}" if acc and s else (s or ', '.join(acc))


class ProgramDraft:
    def __init__(self, data=None, audience_default=300, payment_required=True):
        self.d = {'program_type': None, 'title': None, 'module': None, 'start_time': None, 'end_time': None,
                  'chapter': None, 'notes': None, 'payment_required': payment_required,
                  'audience_default': audience_default, 'main_artist': None, 'accompanying': [], 'events': [],
                  'coordinators': [], 'recipe': {'apr': True, 'poster': False, 'payment_request': False, 'guidelines': False},
                  'outputs': {}, 'rev': 0}
        if data:
            self.d.update(copy.deepcopy(data))

    def to_dict(self):
        return copy.deepcopy(self.d)

    def bump(self):
        self.d['rev'] = int(self.d.get('rev') or 0) + 1

    # ── program level ────────────────────────────────────────────────────────
    def set_program(self, fields: dict) -> dict:
        notes = []
        for k, v in (fields or {}).items():
            if k not in PROGRAM_FIELDS or v is None:
                continue
            if k == 'program_type':
                v = str(v).strip().lower()
                v = _TYPE_ALIASES.get(v, v)
                if v not in PROGRAM_TYPES:
                    notes.append(f'Unknown program type {v!r}: use single, virasat or circuit.')
                    continue
            elif k in ('start_time', 'end_time'):
                t = dt.parse_time(v)
                if not t:
                    notes.append(f'Could not read the time {v!r}.')
                    continue
                if k == 'start_time' and t.get('end') and not fields.get('end_time'):
                    self.d['end_time'] = t['end']
                if t['ambiguous']:
                    notes.append(f'Read {v!r} as {dt.format_time(t["start"])}; correct me if that is wrong.')
                v = t['start']
            elif k == 'payment_required':
                v = v if isinstance(v, bool) else str(v).strip().lower() in ('yes', 'true', '1', 'y', 'haan')
            elif k == 'audience_default':
                try:
                    v = int(str(v).replace(',', ''))
                except ValueError:
                    continue
            elif k == 'module':
                v = normalize_module(v)
            self.d[k] = v
        self.bump()
        if self.d['program_type'] == 'single' and len(self.d['events']) > 1:
            notes.append('A single program has one event; with several, Virasat or circuit fits better.')
        return {'notes': notes}

    def set_recipe(self, recipe: dict):
        for k in OUTPUT_KEYS:
            if k in (recipe or {}):
                self.d['recipe'][k] = bool(recipe[k])
        self.bump()

    # ── events ───────────────────────────────────────────────────────────────
    def _apply_event(self, ev, fields):
        notes = []
        for k, v in (fields or {}).items():
            if v is None or v == '':
                continue
            k = {'institution': 'institution_name', 'time': 'start_time'}.get(k, k)
            if k not in EVENT_FIELDS:
                continue
            if k == 'date':
                p = dt.parse_date(v)
                if not p:
                    notes.append(f'Could not read the date {v!r}.')
                    continue
                ev['date'], ev['date_display'] = p.iso, p.display
                if p.ambiguous:
                    notes.append(f'{v!r} read as {p.display}. {p.note}'.strip())
                continue
            if k == 'end_date':
                p = dt.parse_date(v)
                if p:
                    ev['end_date'] = p.iso
                continue
            if k in ('start_time', 'end_time'):
                t = dt.parse_time(v)
                if not t:
                    notes.append(f'Could not read the time {v!r}.')
                    continue
                ev[k] = t['start']
                if k == 'start_time' and t.get('end') and not fields.get('end_time'):
                    ev['end_time'] = t['end']
                if t['ambiguous']:
                    notes.append(f'{v!r} read as {dt.format_time(t["start"])}.')
                continue
            if k in ('audience_students', 'audience_other'):
                try:
                    v = int(str(v).replace(',', ''))
                except ValueError:
                    continue
            elif k == 'contribution':
                s = str(v).strip()
                if s.upper() in ('NIL', 'NONE', 'NO', '0', 'FREE'):
                    v = 'NIL'
                else:
                    n = tu.to_number(s)
                    if n is None:
                        notes.append(f'Could not read the amount {v!r}.')
                        continue
                    v = int(round(n))
            elif k == 'module':
                v = normalize_module(v)
            ev[k] = v
        return notes

    def event(self, i):
        try:
            i = int(i)
        except (TypeError, ValueError):
            raise IndexError('event_index must be a number')
        if not 0 <= i < len(self.d['events']):
            raise IndexError(f'There is no event {i + 1}; the draft has {len(self.d["events"])}.')
        return self.d['events'][i]

    def add_event(self, fields=None):
        ev = _blank_event()
        notes = self._apply_event(ev, fields or {})
        self.d['events'].append(ev)
        self.bump()
        return len(self.d['events']) - 1, notes

    def update_event(self, i, fields):
        notes = self._apply_event(self.event(i), fields)
        self.bump()
        return notes

    def remove_event(self, i):
        self.event(i)
        removed = self.d['events'].pop(int(i))
        self.bump()
        return removed

    def apply_to_all(self, fields):
        notes = []
        for ev in self.d['events']:
            notes += self._apply_event(ev, fields)
        self.bump()
        return sorted(set(notes))

    def default_event_index(self, create=False):
        """The event an unqualified detail belongs to: the only one, or a new first one."""
        evs = self.d['events']
        if len(evs) == 1:
            return 0
        if not evs and create:
            return self.add_event()[0]
        return None

    # ── artists ──────────────────────────────────────────────────────────────
    @staticmethod
    def make_artist(a, role):
        return {'artist_id': a.get('artist_id') or a.get('tid'), 'name': a.get('name'), 'art_form': a.get('art_form'),
                'role': 'main' if role in (None, '', 'main', 'lead', 'performer') else 'accompanying',
                'phone': a.get('phone'), 'email': a.get('email'), 'flags': list(a.get('flags') or []),
                'provisional': bool(a.get('provisional')), 'has_photo': bool(a.get('has_photo'))}

    def program_artists(self):
        return ([self.d['main_artist']] if self.d['main_artist'] else []) + list(self.d['accompanying'])

    def effective_artists(self, ev):
        return ev['artists'] if ev.get('artists') is not None else self.program_artists()

    def all_artists(self):
        out = []
        for a in self.program_artists() + [a for e in self.d['events'] for a in (e.get('artists') or [])]:
            if a and not any(_same_artist(a, b) for b in out):
                out.append(a)
        return out

    def set_artist(self, a, role='main', event_index=None):
        art = self.make_artist(a, role)
        if event_index is not None:
            ev = self.event(event_index)
            if ev['artists'] is None:
                ev['artists'] = copy.deepcopy(self.program_artists())
            if art['role'] == 'main':
                ev['artists'] = [x for x in ev['artists'] if x['role'] != 'main']
                ev['artists'].insert(0, art)
            elif not any(_same_artist(art, x) for x in ev['artists']):
                ev['artists'].append(art)
        elif art['role'] == 'main':
            self.d['main_artist'] = art
            self.d['accompanying'] = [x for x in self.d['accompanying'] if not _same_artist(x, art)]
        elif not any(_same_artist(art, x) for x in self.d['accompanying']):
            self.d['accompanying'].append(art)
        self.bump()
        return art

    def remove_artist(self, ref, event_index=None) -> bool:
        probe = {'artist_id': ref if str(ref).isdigit() else None, 'name': ref}
        hit = False
        if event_index is not None:
            ev = self.event(event_index)
            before = len(ev['artists'] or [])
            ev['artists'] = [a for a in (ev['artists'] or []) if not _same_artist(a, probe)]
            hit = len(ev['artists']) < before
        else:
            if self.d['main_artist'] and _same_artist(self.d['main_artist'], probe):
                self.d['main_artist'], hit = None, True
            before = len(self.d['accompanying'])
            self.d['accompanying'] = [a for a in self.d['accompanying'] if not _same_artist(a, probe)]
            hit = hit or len(self.d['accompanying']) < before
        self.bump()
        return hit

    def mark_photo(self, artist_id):
        for a in self.all_artists() + [a for e in self.d['events'] for a in (e.get('artists') or [])]:
            if str(a.get('artist_id')) == str(artist_id):
                a['has_photo'] = True
        if self.d['main_artist'] and str(self.d['main_artist'].get('artist_id')) == str(artist_id):
            self.d['main_artist']['has_photo'] = True
        self.bump()

    # ── coordinators (DC6, DC14) ─────────────────────────────────────────────
    def add_coordinator(self, c):
        email = (c.get('email') or '').strip().lower()
        for x in self.d['coordinators']:
            if (email and (x.get('email') or '').lower() == email) or (not email and x.get('name') == c.get('name')):
                x.update({k: v for k, v in c.items() if v})
                self.bump()
                return x
        entry = {'uid': c.get('uid'), 'name': c.get('name'), 'email': c.get('email'), 'phone': c.get('phone'),
                 'chapter': c.get('chapter'), 'role': c.get('role') or ('filer' if not self.d['coordinators'] else 'co-coordinator')}
        if entry['role'] == 'filer':
            for x in self.d['coordinators']:
                if x.get('role') == 'filer':
                    x['role'] = 'co-coordinator'
            self.d['coordinators'].insert(0, entry)
        else:
            self.d['coordinators'].append(entry)
        self.bump()
        return entry

    def remove_coordinator(self, ref) -> bool:
        ref = (ref or '').strip().lower()
        before = len(self.d['coordinators'])
        self.d['coordinators'] = [c for c in self.d['coordinators']
                                  if (c.get('email') or '').lower() != ref and (c.get('name') or '').lower() != ref]
        self.bump()
        return len(self.d['coordinators']) < before

    def filer(self):
        cs = self.d['coordinators']
        return next((c for c in cs if c.get('role') == 'filer'), cs[0] if cs else None)

    # ── validation ───────────────────────────────────────────────────────────
    def issues(self):
        out, t, evs = [], self.d['program_type'], self.d['events']
        if not t:
            out.append(_issue('program_type', 'Program type: single, Virasat (one institution) or circuit (several institutions)'))
        if not evs:
            out.append(_issue('events', 'Circuit stops: date and institution for each' if t == 'circuit' else 'Date and institution'))
            if not self.d['main_artist'] and t != 'virasat':
                out.append(_issue('main_artist', 'Main artist'))
        if t == 'circuit' and len(evs) == 1:
            out.append(_issue('events', 'A circuit usually has two or more stops', 'warning'))
        if t == 'single' and len(evs) > 1:
            out.append(_issue('program_type', 'Several events: Virasat or circuit may fit better', 'warning'))
        if not self.d['module'] and (not evs or any(not e.get('module') for e in evs)):
            out.append(_issue('module', 'Module (for example Full Concert, Lecture Demonstration or Workshops)'))
        for i, e in enumerate(evs):
            n = i + 1
            if not e.get('date'):
                out.append(_issue(f'events.{i}.date', f'Date for event {n}', event_index=i))
            if not e.get('institution_name'):
                out.append(_issue(f'events.{i}.institution', f'Institution for event {n}', event_index=i))
            elif not e.get('institution_id'):
                out.append(_issue(f'events.{i}.institution', f'Event {n}: pick the matching institution for "{e["institution_name"]}" or add it to the directory', 'required', i))
            if not any(a.get('role') == 'main' for a in self.effective_artists(e)):
                if t == 'virasat':
                    out.append(_issue(f'events.{i}.artists', f'Artist for event {n}', event_index=i))
                else:
                    out.append(_issue('main_artist', 'Main artist'))
            end = dt._as_date(e.get('end_date'))
            if end and e.get('date') and end < dt._as_date(e['date']):
                out.append(_issue(f'events.{i}.date', f'Event {n} ends before it starts: check the dates', event_index=i))
            elif span_days(e) > MAX_DAYS:
                out.append(_issue(f'events.{i}.date', f'Event {n} runs {span_days(e)} days: check the dates (up to {MAX_DAYS} are filed day by day)', event_index=i))
            if e.get('date') and not (e.get('start_time') or self.d['start_time']):
                out.append(_issue(f'events.{i}.time', f'Time for event {n}', 'warning', i))
        if t == 'virasat' and len({e.get('institution_id') or e.get('institution_name') for e in evs if e.get('institution_name')}) > 1:
            out.append(_issue('events', 'A Virasat is held at one institution, but these events name different ones', 'warning'))
        for a in self.all_artists():
            if not a.get('artist_id'):
                out.append(_issue('artists', f"{a['name']} isn't matched to the artist directory: pick a match or add them",
                                  'required' if a.get('role') == 'main' else 'warning'))
            if 'deceased' in (a.get('flags') or []):
                out.append(_issue('artists', f"{a['name']} is recorded as deceased: please confirm the artist"))
            elif a.get('provisional'):
                out.append(_issue('artists', f"{a['name']} is provisional, awaiting Artist Care Group approval", 'warning'))
        if not any(c.get('email') for c in self.d['coordinators']):
            out.append(_issue('coordinators', 'Coordinator email (the APR is sent there)'))
        seen, res = set(), []
        for x in out:
            if (x['field'], x['message']) not in seen:
                seen.add((x['field'], x['message']))
                res.append(x)
        return res

    def is_ready(self):
        return not any(i['severity'] == 'required' for i in self.issues())

    def progress(self):
        evs = self.d['events']
        checks = [bool(self.d['program_type']),
                  bool(self.d['module']) or (bool(evs) and all(e.get('module') for e in evs)),
                  all(any(a.get('role') == 'main' for a in self.effective_artists(e)) for e in evs) if evs else bool(self.d['main_artist']),
                  bool(evs) and all(e.get('date') for e in evs),
                  bool(evs) and all(e.get('institution_id') for e in evs),
                  any(c.get('email') for c in self.d['coordinators'])]
        return {'done': sum(1 for c in checks if c), 'total': len(checks), 'ready': self.is_ready()}

    # ── presentation ─────────────────────────────────────────────────────────
    def summary_markdown(self) -> str:
        d = self.d
        lines = [f"**Program:** {PROGRAM_TYPES.get(d['program_type'], 'Not set')}" + (f" ({d['title']})" if d['title'] else '')]
        if d['module']:
            lines.append(f"**Module:** {d['module']}")
        if d['program_type'] != 'virasat' and self.program_artists():
            lines.append('**Artists:** ' + artists_text([dict(a, name=f"{a['name']} ({a['art_form']})" if a.get('art_form') else a['name'])
                                                        for a in self.program_artists()]))
        lines.append('**Events:**')
        for i, e in enumerate(d['events'], 1):
            time = dt.time_range_display(e.get('start_time') or d['start_time'], e.get('end_time') or d['end_time'])
            place = ', '.join(x for x in (e.get('institution_name'), e.get('city')) if x)
            extra = []
            if e.get('module') and e.get('module') != d['module']:
                extra.append(e['module'])
            if e.get('artists') is not None:
                extra.append(artists_text(e['artists']))
            c = e.get('contribution')
            if c:
                extra.append('contribution NIL' if c == 'NIL' else f'contribution Rs {tu.inr(c)}')
            when = e.get('date_display') or 'date?'
            if e.get('end_date') and e.get('end_date') != e.get('date'):
                when += ' to ' + dt.display_date(e['end_date']) + f' ({span_days(e)} days, one row each)'
            lines.append(f"{i}. {when}{', ' + time if time else ''}: {place or 'institution?'}"
                         + (f" ({'; '.join(extra)})" if extra else ''))
        if d['coordinators']:
            lines.append('**Coordinators:** ' + ', '.join(c.get('name') or c.get('email') or '?' for c in d['coordinators']))
        lines.append(f"**Expected students:** {d['audience_default']} per event (default)")
        lines.append(f"**Payment required by Delhi A/c:** {'Yes' if d['payment_required'] else 'No'}")
        if d['notes']:
            lines.append(f"**Notes:** {d['notes']}")
        return '\n'.join(lines)

    def compact(self) -> dict:
        def clean(x):
            if isinstance(x, dict):
                return {k: clean(v) for k, v in x.items() if v not in (None, [], {}, '') and k not in ('flags',) or (k == 'flags' and v)}
            if isinstance(x, list):
                return [clean(v) for v in x]
            return x
        c = clean(self.to_dict())
        for i, e in enumerate(c.get('events', [])):
            e['event_index'] = i
        return c

    def patch(self, path, value):
        parts = str(path).split('.')
        if parts[0] == 'recipe' and len(parts) == 2:
            self.set_recipe({parts[1]: value})
            return []
        if parts[0] == 'events' and len(parts) == 3:
            if parts[2] == 'institution_name':
                ev = self.event(parts[1])
                ev['institution_id'] = None            # retyped by hand: no longer the matched record
            return self.update_event(parts[1], {parts[2]: value})
        if len(parts) == 1 and parts[0] in PROGRAM_FIELDS:
            return self.set_program({parts[0]: value})['notes']
        raise KeyError(f'Cannot edit {path}')
