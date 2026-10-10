"""
Batch mode: many posters at once, for coordinators who file APRs after a season of programs.

1. Every poster is read (the vision model, a few at a time).
2. The events become one list. The same artist on the same date at the same institution on two
   posters (a festival poster and that concert's own poster, or two versions of one poster) is
   one event, keeping the details from both and noting any disagreement.
3. Events are grouped into programs: a Virasat when the poster says so; a circuit when one artist
   visits several institutions within a week; several days at one institution as one program;
   otherwise a single program. A screening or talk without a performing artist needs no APR.
4. Each program is checked like a normal draft, and against the portal (already filed?).
5. The coordinator ticks programs and files them together: one transaction each, every APR
   emailed to the coordinators (one email each, or a single email with all of them).
6. Then the coordinator chooses which institutions get a Request for Payment, and how much.
"""
import logging
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from app.agents.draft import PROGRAM_TYPES, ProgramDraft, normalize_module
from app.core import dates as dt
from app.core import text_utils as tu
from app.skills.base import Skill, SkillContext, email_context, tool

logger = logging.getLogger(__name__)
CIRCUIT_WINDOW_DAYS = 7
VIRASAT_WINDOW_DAYS = 10
S, B = {'type': 'string'}, {'type': 'boolean'}
STATUS_TEXT = {'ready': 'Ready', 'needs_attention': 'Needs your input', 'filed': 'Filed', 'already_filed': 'Already in the portal',
               'excluded': 'Left out'}


def _id():
    return uuid.uuid4().hex[:8]


def _person(name):
    return tu.person_tokens(name or '')[0]


def _same_person(a, b):
    if not a or not b:
        return False
    if a.get('artist_id') and b.get('artist_id'):
        return str(a['artist_id']) == str(b['artist_id'])
    pa, pb = _person(a.get('said') or a.get('name')), _person(b.get('said') or b.get('name'))
    return bool(pa and pb) and min(tu.name_similarity(pa, pb), tu.name_similarity(pb, pa)) >= 0.9


def _inst_key(ev):
    inst = ev.get('institution')
    return f"sid:{inst['sid']}" if inst else 'txt:' + ' '.join(tu.institution_tokens(ev.get('institution_text') or ''))


def _same_place(a, b):
    ia, ib = a.get('institution'), b.get('institution')
    if ia and ib:
        return str(ia['sid']) == str(ib['sid'])
    ta = tu.institution_tokens(f"{a.get('institution_text') or ''} {a.get('city') or ''}")
    tb = tu.institution_tokens(f"{b.get('institution_text') or ''} {b.get('city') or ''}")
    return bool(ta and tb) and max(tu.name_similarity(ta, tb), tu.name_similarity(tb, ta)) >= 0.85


def _sort_key(e):
    return (e.get('date') or '9999-12-31', e.get('start_time') or '')


def _gap(a, b):
    end, start = dt._as_date(a.get('end_date') or a.get('date')), dt._as_date(b.get('date'))
    return (start - end).days if end and start else 999


def _when(e):
    s = dt.display_date(e.get('date')) if e.get('date') else 'date not read'
    if e.get('end_date') and e.get('end_date') != e.get('date'):
        s += ' to ' + dt.display_date(e['end_date'])
    return s


def _days(e):
    from app.agents.draft import span_days
    return span_days(e)


def _place(e):
    inst = e.get('institution')
    return inst['institution_name'] if inst else (e.get('institution_text') or 'institution not read')


def _inst(m):
    return {k: m.get(k) for k in ('sid', 'institution_name', 'city', 'state', 'email', 'phone', 'name_of_the_coordinator')}


def _key_set(arts):
    return {str(a.get('artist_id')) if a.get('artist_id') else ' '.join(_person(a.get('name'))) for a in arts if a}


def program_label(p):
    return p.get('title') or (f"{p['events'][0]['artist']['name']} at {_place(p['events'][0])}" if p['events'] and p['events'][0].get('artist') else 'Program')


class BatchPlanner:
    def __init__(self, services):
        self.s = services

    # 1. poster -> events
    def events_from_poster(self, poster):
        data = poster.get('data') or {}
        title = (data.get('title') or '').strip() or None
        virasat = (data.get('program_type') or '').lower() == 'virasat' or 'virasat' in (title or '').lower()
        main = data.get('main_artist') or {}
        acc = [a for a in data.get('accompanying') or [] if a.get('name')]
        host = data.get('host_institution') or {}
        out = []
        for e in data.get('events') or []:
            artist = e['artist'] if 'artist' in e else main.get('name')
            is_main = bool(artist) and _person(artist) == _person(main.get('name'))
            own_acc = [a for a in e.get('accompanying') or [] if a.get('name')] or (acc if is_main else [])
            pd, pe = dt.parse_date(e.get('date')), dt.parse_date(e.get('end_date')) if e.get('end_date') else None
            st = dt.parse_time(e.get('start_time')) if e.get('start_time') else None
            en = dt.parse_time(e.get('end_time')) if e.get('end_time') else None
            out.append({'eid': _id(), 'sources': [poster['pid']], 'date': pd.iso if pd else None,
                        'end_date': pe.iso if pe and pd and pe.iso > pd.iso else None,
                        'start_time': st['start'] if st else None, 'end_time': en['start'] if en else (st or {}).get('end'),
                        'module': normalize_module(e.get('module') or data.get('module')),
                        'institution_text': (e.get('institution') or host.get('name') or '').strip(),
                        'city': e.get('city') or host.get('city'), 'state': e.get('state') or host.get('state'), 'venue': e.get('venue'),
                        'artist_name': (artist or '').strip() or None,
                        'art_form': e.get('art_form') or (main.get('art_form') if is_main else None),
                        'accompanying_said': own_acc, 'virasat': virasat, 'title': title, 'chapter': data.get('chapter'),
                        'contacts': [c for c in data.get('contacts') or [] if c.get('phone') or c.get('name')], 'include': True})
        return out

    # 2. directory matching
    def _artist(self, name, art_form, role):
        r = self.s.index.search_artists(name, art_form)
        best = r['best']
        if best and 'deceased' not in best['flags']:
            return {'artist_id': best['tid'], 'name': best['name'], 'art_form': art_form or best['art_form'], 'role': role,
                    'flags': best['flags'], 'provisional': best['provisional'], 'said': name}
        return {'artist_id': None, 'name': name, 'art_form': art_form, 'role': role, 'flags': [], 'said': name,
                'options': [{'id': m['tid'], 'label': m['name'], 'meta': ', '.join(x for x in (m['art_form'], m['city']) if x),
                             'flags': m['flags']} for m in r['matches'][:4]
                            if m['score'] >= 0.78 and ('deceased' not in m['flags'] or m['score'] >= 0.9)]}   # no far-fetched suggestions

    def resolve(self, ev):
        ev.update(institution=None, institution_options=[], city_mismatch=False, existing=[])
        if ev['institution_text']:
            r = self.s.index.search_institutions(ev['institution_text'], city=ev.get('city'), state=ev.get('state'))
            if r['best']:
                ev['institution'] = _inst(r['best'])
                if r.get('city_mismatch') and ev.get('city'):
                    ev['place_note'] = (f"{r['best']['institution_name']} was matched, but its city in the directory is "
                                        f"{r['best'].get('city') or 'empty'}, not {ev['city']}: check it is the right one.")
            else:
                ev['institution_options'] = [dict(_inst(m), label=m['institution_name'], meta=', '.join(x for x in (m['city'], m['state']) if x))
                                             for m in (r['campus_choices'] or r['matches'])[:4]]
                ev['city_mismatch'] = bool(r.get('city_mismatch'))
        ev['artist'] = self._artist(ev['artist_name'], ev.get('art_form'), 'main') if ev['artist_name'] else None
        ev['accompanying'] = [self._artist(a['name'], a.get('art_form'), 'accompanying') for a in ev.pop('accompanying_said', [])]
        self._check_portal(ev)
        return ev

    def _check_portal(self, ev):
        ev['existing'] = []
        if not (self.s.writer and ev.get('artist') and ev['artist'].get('artist_id') and ev.get('date')):
            return
        inst = ev.get('institution') or {}
        try:
            ev['existing'] = self.s.writer.find_existing(ev['date'], ev['artist']['artist_id'], inst.get('sid'),
                                                         inst.get('institution_name') or ev.get('institution_text'))
        except Exception as e:
            logger.warning('Portal check failed: %s', e)
        if ev['existing']:
            ev['include'] = False

    # 3. duplicates
    def merge_duplicates(self, events):
        kept, merged = [], []
        for ev in sorted(events, key=_sort_key):
            twin = next((k for k in kept if ev.get('artist') and k['date'] and k['date'] == ev['date']
                         and _same_person(k.get('artist'), ev['artist']) and _same_place(k, ev)
                         and (not k['module'] or not ev['module'] or k['module'] == ev['module'])), None)
            if not twin:
                kept.append(ev)
                continue
            note = ''
            if twin.get('start_time') and ev.get('start_time') and twin['start_time'] != ev['start_time']:
                note = f"The posters give different start times ({dt.format_time(twin['start_time'])} and {dt.format_time(ev['start_time'])}); using {dt.format_time(twin['start_time'])}."
            twin['sources'] = sorted(set(twin['sources'] + ev['sources']))
            for a in ev['accompanying']:
                if not any(_same_person(a, b) for b in twin['accompanying']):
                    twin['accompanying'].append(a)
            for k in ('start_time', 'end_time', 'end_date', 'venue', 'module', 'city', 'state', 'chapter', 'title', 'contacts'):
                if not twin.get(k) and ev.get(k):
                    twin[k] = ev[k]
            if not twin.get('institution') and ev.get('institution'):
                twin['institution'], twin['institution_options'] = ev['institution'], []
            twin['virasat'] = twin['virasat'] or ev['virasat']
            merged.append({'eid': twin['eid'], 'what': f"{twin['artist']['name']}, {_when(twin)}, {_place(twin)}",
                           'sources': twin['sources'], 'note': note})
        return kept, merged

    # 4. programs
    def _program(self, ptype, evs):
        evs = sorted(evs, key=_sort_key)
        first = evs[0]
        if ptype == 'virasat':
            title = f"{first['title']}: {_place(first)}" if first.get('title') else f"{first['artist']['name']} at {_place(first)}"
        elif ptype == 'circuit':
            title = f"Circuit: {first['artist']['name']}"
        else:
            title = first.get('title')
        return {'pid': _id(), 'type': ptype, 'title': title, 'chapter': first.get('chapter'), 'events': evs, 'include': True,
                'status': None, 'issues': [], 'warnings': [], 'notes': [], 'apr': None,
                'sources': sorted({s for e in evs for s in e['sources']})}

    def group(self, events):
        programs, skipped, with_artist = [], [], []
        for ev in events:
            if ev.get('artist'):
                with_artist.append(ev)
            else:
                skipped.append({'eid': ev['eid'], 'sources': ev['sources'], 'reason': 'No performing artist on the poster, so no APR is needed',
                                'what': f"{ev.get('module') or 'Event'}, {_when(ev)}, {_place(ev)}"})
        used = set()
        vir = [e for e in with_artist if e['virasat']]
        for key in dict.fromkeys(_inst_key(e) for e in vir):
            cluster = []
            for ev in sorted((e for e in vir if _inst_key(e) == key), key=_sort_key):
                if cluster and _gap(cluster[-1], ev) > VIRASAT_WINDOW_DAYS:
                    programs.append(self._program('virasat' if len(cluster) > 1 else 'single', cluster))
                    cluster = []
                cluster.append(ev)
                used.add(ev['eid'])
            if cluster:
                programs.append(self._program('virasat' if len(cluster) > 1 else 'single', cluster))
        rest = [e for e in with_artist if e['eid'] not in used]
        while rest:
            same = sorted((e for e in rest if _same_person(e['artist'], rest[0]['artist'])), key=_sort_key)
            cluster = []
            for ev in same:
                if cluster and _gap(cluster[-1], ev) > CIRCUIT_WINDOW_DAYS:
                    programs.append(self._grouped(cluster))
                    cluster = []
                cluster.append(ev)
            if cluster:
                programs.append(self._grouped(cluster))
            ids = {e['eid'] for e in same}
            rest = [e for e in rest if e['eid'] not in ids]
        programs.sort(key=lambda p: _sort_key(p['events'][0]))
        for p in programs:                              # an artist in a circuit and also at a Virasat
            if p['type'] == 'virasat':
                continue
            main = p['events'][0]['artist']
            for v in programs:
                if v['type'] == 'virasat':
                    for e in v['events']:
                        if _same_person(main, e['artist']):
                            p['notes'].append(f"{main['name']} also performs at {v['title']} on {_when(e)}; that event is filed with the Virasat.")
        return programs, skipped

    def _grouped(self, cluster):
        if len(cluster) == 1:
            return self._program('single', cluster)
        return self._program('circuit' if len({_inst_key(e) for e in cluster}) > 1 else 'virasat', cluster)

    # 5. a program as a normal draft, so it is checked and filed exactly like one
    def to_draft(self, prog, coordinators):
        d = ProgramDraft(audience_default=int(self.s.setting('apr.default_audience', 300) or 300),
                         payment_required=bool(self.s.setting('apr.payment_required_default', True)))
        d.set_program({'program_type': prog['type'], 'title': prog.get('title'), 'chapter': prog.get('chapter')})
        d.d['batch_ref'] = prog['pid']
        evs = [e for e in prog['events'] if e.get('include', True)]
        if prog['type'] != 'virasat' and evs:
            d.set_artist(evs[0]['artist'], 'main')
            for e in evs:
                for a in e['accompanying']:
                    d.set_artist(a, 'accompanying')
        for e in evs:
            idx, _ = d.add_event({'date': e.get('date'), 'end_date': e.get('end_date'), 'start_time': e.get('start_time'),
                                  'end_time': e.get('end_time'), 'module': e.get('module'), 'venue': e.get('venue')})
            inst = e.get('institution')
            fields = ({'institution_id': inst['sid'], 'institution_name': inst['institution_name'], 'city': inst.get('city'),
                       'state': inst.get('state'), 'contact_name': inst.get('name_of_the_coordinator'), 'contact_phone': inst.get('phone'),
                       'institution_email': inst.get('email')} if inst else
                      {'institution_name': e.get('institution_text'), 'city': e.get('city'), 'state': e.get('state')})
            if e.get('contacts') and not fields.get('contact_name'):
                fields.update(contact_name=e['contacts'][0].get('name'), contact_phone=e['contacts'][0].get('phone'))
            d.update_event(idx, fields)
            own = [e['artist']] + e['accompanying']
            if prog['type'] == 'virasat' or _key_set(own) != _key_set(d.program_artists()):
                d.d['events'][idx]['artists'] = [ProgramDraft.make_artist(a, a['role']) for a in own]
        for c in coordinators:
            d.add_coordinator(dict(c))
        return d

    def refresh(self, plan, coordinators):
        plan['needs_coordinator'] = not any(c.get('email') for c in coordinators)
        for p in plan['programs']:
            p['warnings'] = list(p.get('notes') or [])
            for e in p['events']:
                if e.get('existing'):
                    p['warnings'].append(f"{_when(e)} at {_place(e)} is already in the portal (event {', '.join(map(str, e['existing']))}), so it is left out.")
            if p.get('apr'):
                p['status'], p['issues'] = 'filed', []
                continue
            inc = [e for e in p['events'] if e.get('include', True)]
            if not inc:
                p['status'] = 'already_filed' if any(e.get('existing') for e in p['events']) else 'excluded'
                p['issues'] = []
                continue
            if not p.get('include', True):
                p['status'], p['issues'] = 'excluded', []
                continue
            for e in inc:
                if e.get('place_note') and e['place_note'] not in p['warnings']:
                    p['warnings'].append(e['place_note'])
            d = self.to_draft(p, coordinators)
            from app.skills.base import portal_issues
            p['issues'] = [i['message'] for i in d.issues() if i['severity'] == 'required' and i['field'] != 'coordinators'] + portal_issues(self.s, d)
            p['status'] = 'needs_attention' if p['issues'] else 'ready'
        plan['rev'] = int(plan.get('rev') or 0) + 1
        return plan

    def build(self, posters, coordinators):
        events = []
        for p in posters:
            if p.get('data'):
                events += self.events_from_poster(p)
        for ev in events:
            self.resolve(ev)
        events, merged = self.merge_duplicates(events)
        programs, skipped = self.group(events)
        plan = {'id': _id(), 'programs': programs, 'skipped': skipped, 'merged': merged, 'rev': 0, 'email_mode': 'each',
                'posters': [{k: p.get(k) for k in ('pid', 'filename', 'file', 'thumb', 'error')} for p in posters]}
        return self.refresh(plan, coordinators)

    # 6. fixes from the card
    def pick_artist(self, plan, said, role, artist_id):
        rec = self.s.index.get_artist(artist_id)
        if not rec:
            return False
        hit = False
        for p in plan['programs']:
            for e in p['events']:
                slots = ([('artist', None)] if role == 'main' else []) + [('accompanying', i) for i in range(len(e['accompanying']))]
                for field, i in slots:
                    a = e[field] if i is None else e['accompanying'][i]
                    if a and not a.get('artist_id') and _person(a['said']) == _person(said):
                        new = {'artist_id': rec['tid'], 'name': rec['name'], 'art_form': a.get('art_form') or rec['art_form'],
                               'role': a['role'], 'flags': rec['flags'], 'provisional': rec['provisional'], 'said': a['said']}
                        if i is None:
                            e['artist'] = new
                        else:
                            e['accompanying'][i] = new
                        hit = True
                if hit:
                    self._check_portal(e)
        return hit

    def pick_institution(self, plan, text, sid):
        rec = self.s.index.get_institution(sid)
        if not rec:
            return False
        key = ' '.join(tu.institution_tokens(text or ''))
        hit = False
        for p in plan['programs']:
            for e in p['events']:
                if not e.get('institution') and ' '.join(tu.institution_tokens(e.get('institution_text') or '')) == key:
                    e['institution'], e['institution_options'], hit = _inst(rec), [], True
                    self._check_portal(e)
        return hit


def batch_coordinators(ctx):
    coords = [dict(c) for c in ctx.draft.d['coordinators']]
    u = ctx.state.user or {}
    if not coords and u.get('email'):
        coords = [{'uid': u.get('uid'), 'name': u.get('name'), 'email': u['email'], 'role': 'filer'}]
    return coords


def read_posters(ctx, posters):
    """Read every poster with the vision model, a few at a time."""
    from app.skills.output_skills import POSTER_PROMPT, vision_json

    def one(p):
        p['data'], p['error'] = vision_json(ctx, p.pop('b64'), p.get('mime') or 'image/jpeg', POSTER_PROMPT)
        if not p['error'] and not (p['data'] or {}).get('events'):
            p['error'] = 'No events could be read from this poster'
    workers = max(1, int(ctx.setting('batch.parallel_reads', 3) or 1))
    if workers == 1 or len(posters) == 1:
        for p in posters:
            one(p)
    else:
        with ThreadPoolExecutor(max_workers=min(workers, len(posters))) as ex:
            list(ex.map(one, posters))


def mark_filed(plan, pid, out):
    for p in plan['programs']:
        if p['pid'] == pid:
            p['apr'] = {'number': out['apr']['number'], 'request_id': out['apr']['request_id'], 'pdf_url': out['pdf_url'],
                        'pdf_file': out['pdf_file'], 'event_ids': out['event_ids']}
            p['status'], p['issues'] = 'filed', []
            emap = out.get('event_map') or {i: [x] for i, x in enumerate(out['event_ids'])}
            for i, e in enumerate([e for e in p['events'] if e.get('include', True)]):
                e['event_ids'] = emap.get(i) or emap.get(str(i)) or []
                e['event_id'] = e['event_ids'][0] if e['event_ids'] else None
            return True
    return False


def plan_card(ctx, plan):
    posters = {p['pid']: p for p in plan['posters']}
    progs = []
    for p in plan['programs']:
        unresolved, seen = [], set()
        for e in p['events']:
            if not e.get('include', True):
                continue
            for a in [e.get('artist')] + list(e.get('accompanying') or []):
                if a and not a.get('artist_id') and ('artist', a['role'], ' '.join(_person(a['said']))) not in seen:
                    seen.add(('artist', a['role'], ' '.join(_person(a['said']))))
                    unresolved.append({'kind': 'artist', 'role': a['role'], 'said': a['said'], 'art_form': a.get('art_form'),
                                       'options': a.get('options') or []})
            if e.get('institution_text') and not e.get('institution') and ('inst', e['institution_text']) not in seen:
                seen.add(('inst', e['institution_text']))
                unresolved.append({'kind': 'institution', 'said': e['institution_text'], 'city': e.get('city'), 'state': e.get('state'),
                                   'options': e.get('institution_options') or [], 'city_mismatch': e.get('city_mismatch')})
        names = [u['said'] for u in unresolved]
        issues = [i for i in p.get('issues', []) if not any(n and n in i for n in names)]   # the fix boxes already say it
        progs.append({'pid': p['pid'], 'type': p['type'], 'type_label': PROGRAM_TYPES.get(p['type'], p['type']), 'title': program_label(p),
                      'status': p['status'], 'status_text': STATUS_TEXT.get(p['status'], p['status']), 'include': p.get('include', True),
                      'issues': issues, 'warnings': p.get('warnings', []), 'unresolved': unresolved, 'apr': p.get('apr'),
                      'thumbs': [posters[s]['thumb'] for s in p['sources'] if posters.get(s, {}).get('thumb')],
                      'events': [{'eid': e['eid'], 'when': _when(e), 'days': _days(e), 'time': dt.time_range_display(e.get('start_time'), e.get('end_time')),
                                  'place': _place(e), 'module': e.get('module') or '', 'include': e.get('include', True),
                                  'existing': e.get('existing') or [],
                                  'artist': ', '.join(x for x in [(e.get('artist') or {}).get('name')] +
                                                      [a['name'] for a in e.get('accompanying') or []] if x)} for e in p['events']]})
    ready = [p for p in plan['programs'] if p['status'] == 'ready' and p.get('include', True)]
    cid = ctx.state.new_confirmation('file_batch', rev=plan['rev'], plan_id=plan['id'])
    counts = {k: sum(1 for p in plan['programs'] if p['status'] == k) for k in STATUS_TEXT}
    return {'type': 'batch_plan', 'plan_id': plan['id'], 'confirmation_id': cid, 'programs': progs, 'skipped': plan['skipped'],
            'merged': plan['merged'], 'needs_coordinator': plan.get('needs_coordinator'), 'email_mode': plan.get('email_mode', 'each'),
            'posters': [{'pid': p['pid'], 'filename': p.get('filename'), 'thumb': p.get('thumb'), 'error': p.get('error')} for p in plan['posters']],
            'counts': counts, 'ready': len(ready), 'button': f"File {len(ready)} APR{'s' if len(ready) != 1 else ''}"}


def plan_reply(plan):
    unread = [p for p in plan['posters'] if p.get('error')]
    progs = plan['programs']
    c = {k: sum(1 for p in progs if p['status'] == k) for k in STATUS_TEXT}
    lines = [f"I read **{len(plan['posters']) - len(unread)} of {len(plan['posters'])} posters** and found **{len(progs)} programs**."]
    extra = []
    if plan['merged']:
        extra.append(f"{len(plan['merged'])} event{'s were' if len(plan['merged']) != 1 else ' was'} on two posters and merged")
    if plan['skipped']:
        extra.append(f"{len(plan['skipped'])} need{'s' if len(plan['skipped']) == 1 else ''} no APR (no performing artist)")
    if extra:
        lines.append('; '.join(extra).capitalize() + '.')
    status = [f"**{c['ready']} ready to file**"]
    if c['needs_attention']:
        status.append(f"**{c['needs_attention']} need your input**")
    if c['already_filed']:
        status.append(f"{c['already_filed']} already in the portal")
    if c['filed']:
        status.append(f"{c['filed']} filed")
    lines.append(', '.join(status) + '.')
    if unread:
        lines.append('Could not read: ' + ', '.join(p.get('filename') or p['pid'] for p in unread) + '.')
    if plan.get('needs_coordinator'):
        lines.append('First, your coordinator email: every APR is sent there.')
    lines.append('Check the plan, fix anything marked, untick what you do not want, then tap **File**.')
    return '\n\n'.join(lines)


def file_programs(ctx, plan, email_mode='each'):
    from app.skills.output_skills import _email_status, file_draft
    planner, coords = BatchPlanner(ctx.s), batch_coordinators(ctx)
    results, done = [], []
    for p in plan['programs']:
        if not p.get('include', True) or p['status'] != 'ready':
            continue
        d = planner.to_draft(p, coords)
        posters = {x['pid']: x for x in plan['posters']}
        media = [('docs', posters[s]['file'], 'poster') for s in p['sources'] if posters.get(s, {}).get('file')]
        try:
            out = file_draft(ctx, d, media_files=media, send_email=(email_mode == 'each'))
        except Exception as e:
            logger.exception('Batch filing failed for %s', program_label(p))
            results.append({'pid': p['pid'], 'title': program_label(p), 'ok': False, 'error': f'{type(e).__name__}: {e}'})
            continue
        mark_filed(plan, p['pid'], out)
        done.append((p, out, d))
        results.append({'pid': p['pid'], 'title': program_label(p), 'ok': True, 'apr_number': out['apr']['number'],
                        'pdf_url': out['pdf_url'], 'pdf_file': out['pdf_file'], 'email': _email_status(out['sent'])})
    if email_mode == 'combined' and done:
        aprs = [{'number': out['apr']['number'], 'program': program_label(p),
                 'dates': ', '.join(dict.fromkeys(_when(e) for e in p['events'] if e.get('include', True))),
                 'institutions': ', '.join(dict.fromkeys(_place(e) for e in p['events'] if e.get('include', True)))} for p, out, _ in done]
        pending = ', '.join(program_label(p) for p in plan['programs'] if p['status'] == 'needs_attention')
        msg = ctx.s.renderer.render_email('email.apr_batch_summary', email_context(ctx, {'aprs': aprs, 'pending': pending,
                                                                                      'coordinator': (coords or [{}])[0]}))
        sent = ctx.s.mailer.send(to=[c['email'] for c in coords if c.get('email')], cc=ctx.setting('apr.finance_cc', []),
                                 subject=msg['subject'], html=msg['html'], text=msg['text'],
                                 attachments=[(f"APR_{out['apr']['number']}.pdf", out['pdf'], 'application/pdf') for _, out, _ in done],
                                 actor=ctx.actor_label, category='apr_batch_summary')
        for r in results:
            if r.get('ok'):
                r['email'] = 'in the combined email' + (' (dry run)' if sent.get('dry_run') else '' if sent.get('ok') else f" (failed: {sent.get('error')})")
    planner.refresh(plan, coords)
    ctx.s.gov.audit(ctx.actor_label, 'batch.filed', plan['id'], {'filed': [r.get('apr_number') for r in results if r.get('ok')],
                                                                'failed': [r['title'] for r in results if not r.get('ok')]})
    return results


def rfp_rows(plan):
    rows = []
    for p in plan['programs']:
        if not p.get('apr'):
            continue
        groups = OrderedDict()
        for e in p['events']:
            if not e.get('event_id'):
                continue
            inst = e.get('institution') or {}
            key = str(inst.get('sid') or e.get('institution_text'))
            g = groups.setdefault(key, {'key': f"{p['pid']}:{key}", 'institution': _place(e), 'email': inst.get('email') or '',
                                        'program': program_label(p), 'apr': p['apr']['number'], 'event_ids': [], 'first': None,
                                        'last': None, 'artists': []})
            g['event_ids'].extend(e.get('event_ids') or [e['event_id']])
            g['first'] = min(filter(None, [g['first'], e.get('date')]))
            g['last'] = max(filter(None, [g['last'], e.get('end_date') or e.get('date')]))
            name = (e.get('artist') or {}).get('name')
            if name and name not in g['artists']:
                g['artists'].append(name)
        rows += list(groups.values())
    for r in rows:
        r['dates'] = _when({'date': r.pop('first'), 'end_date': r.pop('last')})
        n, arts = len(r['event_ids']), r.pop('artists')
        r['artist'] = arts[0] if len(arts) == 1 else f"{n} events, {len(arts)} artists"
    return rows


def rfp_picker_card(plan):
    rows = rfp_rows(plan)
    return {'type': 'rfp_picker', 'title': 'Requests for Payment: choose which to send', 'rows': rows,
            'button': 'Prepare Request for Payment'} if rows else None


def prepare_rfp(ctx, choices):
    """choices: [{event_ids, amount, email}] -> the usual outbox preview, nothing sent yet."""
    ids, amounts, emails = [], [], []
    for c in choices or []:
        evs = [int(x) for x in c.get('event_ids') or []]
        if not evs:
            continue
        ids += evs
        amounts.append({'event_id': evs[0], 'amount': tu.to_number(c.get('amount')) if c.get('amount') not in (None, '') else None})
        amounts += [{'event_id': x, 'amount': 0} for x in evs[1:]]
        if c.get('email'):
            emails.append({'event_id': evs[0], 'email': c['email'].strip()})
    amounts = [a for a in amounts if a['amount'] is not None]
    if not ids:
        return {'ok': False, 'error': 'Tick at least one institution.'}
    return ctx.s.registry.execute('prepare_payment_requests', {'event_ids': ids, 'amounts': amounts, 'emails': emails}, ctx)


class BatchSkill(Skill):
    key, title = 'batch', 'Several posters at once'
    description = 'Reads many posters together, merges duplicates, groups events into programs and files all their APRs at once.'

    @tool('batch_summary', 'The batch plan from posters uploaded together: each program, its status and what it still needs. '
          'Also returns the confirmation_id for batch_file.')
    def batch_summary(self, ctx):
        plan = ctx.state.batch
        if not plan:
            return {'ok': False, 'error': 'No posters have been uploaded together yet.'}
        card = plan_card(ctx, plan)
        ctx.ui.cards.append(card)
        return {'ok': True, 'confirmation_id': card['confirmation_id'], 'ready': card['ready'],
                'programs': [{'program_id': p['pid'], 'title': p['title'], 'type': p['type'], 'status': p['status'],
                              'needs': p['issues'], 'apr': (p['apr'] or {}).get('number')} for p in card['programs']]}

    @tool('batch_update', 'Change a program in the batch plan: include or leave it out, or change its type.',
          {'program_id': S, 'include': B, 'program_type': {'type': 'string', 'enum': ['single', 'virasat', 'circuit']}, 'title': S},
          required=('program_id',))
    def batch_update(self, ctx, program_id, include=None, program_type=None, title=None):
        plan = ctx.state.batch
        p = next((x for x in (plan or {}).get('programs', []) if x['pid'] == program_id), None)
        if not p:
            return {'ok': False, 'error': 'No such program in the batch plan.'}
        if include is not None:
            p['include'] = bool(include)
        if program_type:
            p['type'] = program_type
        if title:
            p['title'] = title
        BatchPlanner(ctx.s).refresh(plan, batch_coordinators(ctx))
        ctx.ui.cards.append(plan_card(ctx, plan))
        return {'ok': True, 'status': p['status'], 'needs': p['issues']}

    @tool('batch_file', 'File every ticked, ready program of the batch plan after a clear yes. Each APR is emailed to the '
          'coordinators (email_mode "each"), or all of them in one email ("combined").',
          {'confirmation_id': S, 'email_mode': {'type': 'string', 'enum': ['each', 'combined']}}, required=('confirmation_id',))
    def batch_file(self, ctx, confirmation_id, email_mode=None):
        plan = ctx.state.batch
        pend = ctx.state.get_confirmation(confirmation_id, 'file_batch')
        if not plan or not pend:
            return {'ok': False, 'error': 'This confirmation has expired. Call batch_summary again.'}
        if pend.get('rev') != plan['rev'] or pend.get('plan_id') != plan['id']:
            return {'ok': False, 'error': 'The plan changed after it was shown. Show it again (batch_summary) and get a fresh yes.'}
        if not ctx.s.writer:
            return {'ok': False, 'error': 'Filing is unavailable on this server (no database connection).'}
        if plan.get('needs_coordinator'):
            return {'ok': False, 'error': 'A coordinator email is needed first: every APR is sent there.'}
        ctx.state.take_confirmation(confirmation_id, 'file_batch')
        results = file_programs(ctx, plan, email_mode or plan.get('email_mode', 'each'))
        ctx.ui.cards.append({'type': 'batch_results', 'title': 'Filed', 'results': results})
        for r in results:
            if r.get('ok'):
                ctx.ui.artifacts.append({'type': 'pdf', 'label': f"APR {r['apr_number']}: {r['title']}", 'url': r['pdf_url'], 'filename': r['pdf_file']})
        picker = rfp_picker_card(plan)
        if picker:
            ctx.ui.cards.append(picker)
        return {'ok': True, 'filed': [r for r in results if r.get('ok')], 'failed': [r for r in results if not r.get('ok')],
                'still_open': [program_label(p) for p in plan['programs'] if p['status'] == 'needs_attention'],
                'advice': 'Tell them which APRs were filed and emailed, then ask which institutions should get a Request for Payment.'}

    @tool('batch_payment_requests', 'Prepare Requests for Payment for institutions of the filed batch programs (nothing is sent yet).',
          {'choices': {'type': 'array', 'items': {'type': 'object', 'properties': {'institution': S, 'amount': {'type': 'number'}, 'email': S}}}},
          required=('choices',))
    def batch_payment_requests(self, ctx, choices):
        rows = rfp_rows(ctx.state.batch or {'programs': []})
        picked = []
        for c in choices:
            q = tu.institution_tokens(c.get('institution') or '')
            row = max(rows, key=lambda r: tu.name_similarity(q, tu.institution_tokens(r['institution'])), default=None) if q else None
            if row and tu.name_similarity(q, tu.institution_tokens(row['institution'])) >= 0.8:
                picked.append({'event_ids': row['event_ids'], 'amount': c.get('amount'), 'email': c.get('email') or row['email']})
        if not picked:
            return {'ok': False, 'error': 'None of those institutions is in the filed batch programs.', 'institutions': [r['institution'] for r in rows]}
        return prepare_rfp(ctx, picked)
