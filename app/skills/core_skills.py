"""
Core skills: the program draft, events (including circuit planning), artists,
institutions and coordinators. These are always on; output skills (APR, posters, emails...)
live in output_skills.py and can be switched off individually.
"""
import logging
import re

from app.agents.draft import PROGRAM_FIELDS, PROGRAM_TYPES, ProgramDraft
from app.core import text_utils as tu
from app.skills.base import Skill, notify, program_summary, tool

logger = logging.getLogger(__name__)
S, I, B = {'type': 'string'}, {'type': 'integer'}, {'type': 'boolean'}
EVENT_PROPS = {
    'date': {'type': 'string', 'description': 'As said: 15-10-2026, 15 Oct, next Friday, कल'},
    'end_date': {'type': 'string', 'description': 'Last day, only for a workshop or intensive running several consecutive days (filed as one row per day)'},
    'institution': {'type': 'string', 'description': 'Institution as said, e.g. "KV 2 Colaba", "IIT Bombay"'},
    'city': S, 'state': S,
    'start_time': {'type': 'string', 'description': 'e.g. 6:30 pm, or a range such as 10am-12pm'},
    'end_time': S, 'module': S,
    'contribution': {'type': 'string', 'description': "Institution's contribution, e.g. 23000 or NIL"},
    'audience_students': I, 'audience_other': I, 'venue': S, 'notes': S,
}
EDIT_EVENT_PROPS = {k: v for k, v in EVENT_PROPS.items() if k not in ('institution', 'city', 'state')}


def artist_chip(m, role, event_index=None):
    meta = ', '.join(x for x in (m.get('art_form'), m.get('city')) if x)
    return {'kind': 'artist', 'id': m['tid'], 'label': m['name'], 'meta': meta, 'band': m['band'],
            'flags': m.get('flags', []), 'role': role, 'event_index': event_index}


def inst_chip(m, event_index=None):
    meta = ', '.join(x for x in (m.get('city'), m.get('state')) if x)
    return {'kind': 'institution', 'id': m['sid'], 'label': m['institution_name'], 'meta': meta, 'band': m['band'],
            'event_index': event_index}


def apply_institution(ctx, idx, rec, apply_all=False):
    fields = {'institution_id': rec['sid'], 'institution_name': rec['institution_name'], 'city': rec.get('city') or None,
              'state': rec.get('state') or None, 'contact_name': rec.get('name_of_the_coordinator') or None,
              'contact_phone': rec.get('phone') or None, 'institution_email': rec.get('email') or None}
    if apply_all:
        ctx.draft.apply_to_all(fields)
    else:
        ctx.draft.update_event(idx, fields)
    return fields


def _wants_outputs(draft):
    return any(draft.d['recipe'].values())


def add_events_impl(ctx, events, replace_existing=False):
    """Bulk-add events and resolve every institution in one go (the circuit planner)."""
    if replace_existing:
        ctx.draft.d['events'] = []
        ctx.draft.bump()
    rows = []
    for item in (events or [])[:40]:
        fields = {k: v for k, v in item.items() if k in EVENT_PROPS and k not in ('institution', 'city', 'state')}
        idx, notes = ctx.draft.add_event(fields)
        row = {'event_index': idx, 'date': ctx.draft.d['events'][idx]['date_display'], 'notes': notes}
        inst = (item.get('institution') or '').strip()
        if inst:
            res = ctx.s.index.search_institutions(inst, city=item.get('city'), state=item.get('state'))
            if res['best']:
                apply_institution(ctx, idx, res['best'])
                row.update(status='matched', institution=f"{res['best']['institution_name']}, {res['best']['city']}".strip(', '))
            else:
                ctx.draft.update_event(idx, {'institution_name': inst, 'city': item.get('city'), 'state': item.get('state')})
                choices = res['campus_choices'] or res['matches'][:4]
                if choices:
                    ctx.ui.candidates.append({'kind': 'institution', 'event_index': idx, 'query': inst, 'allow_add': True,
                                              'title': f'Event {idx + 1}: which campus?' if res['campus_choices'] else f'Event {idx + 1}: which "{inst}"?',
                                              'items': [inst_chip(m, idx) for m in choices]})
                    row.update(status='choose_campus' if res['campus_choices'] else 'choose',
                               options=[f"{m['institution_name']} ({m['city']})" for m in choices])
                else:
                    row['status'] = 'not_found'
        rows.append(row)
    return rows


def _missing(draft, n=6):
    return [i['message'] for i in draft.issues() if i['severity'] == 'required'][:n]


def _apr_email_contents(ctx):
    """What the APR email will carry, said on the review card before the coordinator taps File APR."""
    from datetime import date as _date
    from app.core import dates as dtm
    from app.skills.output_skills import auto_poster_planned, poster_sources
    d, out = ctx.draft, ['the APR PDF']
    if ctx.setting('apr.attach_poster', True):
        src = poster_sources(ctx, d)
        if any(k == 'uploads' for k, _, _ in src):
            out.append('the poster you uploaded')
        elif src:
            out.append('the poster made here')
        elif auto_poster_planned(ctx, d):
            out.append("a poster made from the main artist's photo")
    photos = len((ctx.state.uploads or {}).get('program_photos') or [])
    if photos:
        out.append(f"{photos} program photo{'s' if photos > 1 else ''}")
    if ctx.setting('apr.calendar_invite', True) and any((dtm._as_date(e.get('date')) or _date.min) >= _date.today() for e in d.d['events']):
        out.append('a calendar invite')
    return out


class ProgramSkill(Skill):
    key, title, core = 'program', 'Program details', True
    description = 'Program type, title, module, timing, notes and the review before filing.'

    @tool('get_draft', 'Return the current program draft and what is still missing.')
    def get_draft(self, ctx):
        return {'draft': ctx.draft.compact(), 'issues': ctx.draft.issues()}

    @tool('update_program', 'Set program-level details. Module, times and artists set here apply to every event '
          'unless an event overrides them. Pass dates/times exactly as said.',
          {'program_type': {'type': 'string', 'enum': ['single', 'virasat', 'circuit']}, 'title': S,
           'module': {'type': 'string', 'description': "One of the portal's modules listed in the instructions (e.g. Full Concert, Lecture Demonstration, Workshops)"},
           'start_time': S, 'end_time': S, 'chapter': S, 'notes': {'type': 'string', 'description': 'Additional notes printed on the APR'},
           'payment_required': {'type': 'boolean', 'description': 'Payment required by Delhi A/c'}, 'audience_default': I})
    def update_program(self, ctx, **fields):
        r = ctx.draft.set_program(fields)
        return {'ok': True, 'program': {k: ctx.draft.d[k] for k in PROGRAM_FIELDS}, 'notes': r['notes'],
                'missing': _missing(ctx.draft)}

    @tool('set_outputs', "Record which outputs the coordinator wants; each is optional and independent.",
          {'apr': B, 'poster': B, 'payment_request': B, 'guidelines': B})
    def set_outputs(self, ctx, **recipe):
        ctx.draft.set_recipe(recipe)
        return {'ok': True, 'outputs': ctx.draft.d['recipe']}

    @tool('update_event', 'Change details of one event (0-based event_index). To change its institution use '
          'find_institution with event_index.', dict({'event_index': I}, **EDIT_EVENT_PROPS), required=('event_index',))
    def update_event(self, ctx, event_index, **fields):
        notes = ctx.draft.update_event(event_index, fields)
        return {'ok': True, 'event': ctx.draft.compact()['events'][event_index], 'notes': notes}

    @tool('remove_event', 'Remove one event from the draft (0-based event_index).', {'event_index': I}, required=('event_index',))
    def remove_event(self, ctx, event_index):
        ev = ctx.draft.remove_event(event_index)
        return {'ok': True, 'removed': ev.get('institution_name') or ev.get('date_display'), 'events_left': len(ctx.draft.d['events'])}

    @tool('list_modules', 'List the module types defined in the directory.')
    def list_modules(self, ctx):
        mods = []
        if ctx.s.writer:
            try:
                mods = [n for _, n in ctx.s.writer.modules()]
            except Exception as e:
                logger.warning('Module list unavailable: %s', e)
        return {'modules': mods or ['Concert', 'Lecture Demonstration', 'Workshop', 'Baithak', 'Intensive', 'Heritage Walk']}

    @tool('review_program', 'Check the draft is complete. Returns the summary to show and a confirmation_id for '
          'create_apr. Always call this before filing.')
    def review_program(self, ctx):
        from app.skills.base import portal_issues
        issues = ctx.draft.issues()
        req = [i['message'] for i in issues if i['severity'] == 'required'] + portal_issues(ctx.s, ctx.draft)
        warn = [i['message'] for i in issues if i['severity'] == 'warning']
        if req:
            return {'ready': False, 'missing': req, 'warnings': warn}
        cid = ctx.state.new_confirmation('create_apr', rev=ctx.draft.d['rev'])
        summary = ctx.draft.summary_markdown()
        sends = _apr_email_contents(ctx)
        ctx.ui.cards.append({'type': 'review', 'confirmation_id': cid, 'title': 'Ready to file the APR',
                             'summary': summary, 'warnings': warn, 'button': 'File APR', 'sends': sends})
        return {'ready': True, 'confirmation_id': cid, 'summary': summary, 'warnings': warn, 'apr_email_will_carry': sends,
                'next': 'Show the summary; on a clear yes call create_apr with this confirmation_id.'}

    @tool('reset_draft', 'Start a fresh program draft (keeps the coordinators).', {'keep_coordinators': B})
    def reset_draft(self, ctx, keep_coordinators=True):
        old = ctx.draft
        ctx.state.draft = ProgramDraft(audience_default=old.d['audience_default'], payment_required=old.d['payment_required'])
        if keep_coordinators:
            for c in old.d['coordinators']:
                ctx.state.draft.add_coordinator(c)
        ctx.state.pending = {}
        return {'ok': True}


class EventsSkill(Skill):
    key, title, core = 'events', 'Dates, institutions and circuit stops', True
    description = 'Adds one or many events at once and resolves every institution against the directory.'

    @tool('add_events', 'Add one or more events in ONE call (use for every circuit stop at once). Each institution '
          'is matched automatically; city and state come from the directory.',
          {'events': {'type': 'array', 'items': {'type': 'object', 'properties': EVENT_PROPS}},
           'replace_existing': {'type': 'boolean', 'description': 'Replace the events already in the draft'}},
          required=('events',))
    def add_events(self, ctx, events, replace_existing=False):
        rows = add_events_impl(ctx, events, replace_existing)
        return {'ok': True, 'events': rows, 'total_events': len(ctx.draft.d['events']), 'missing': _missing(ctx.draft)}

    @tool('set_event_artists', "Give one event its own artists (a different accompanist at one circuit stop, or each "
          "Virasat performance's artist). Replaces that event's artist list.",
          {'event_index': I, 'artists': {'type': 'array', 'items': {'type': 'object', 'properties': {
              'name': S, 'art_form': S, 'artist_id': I, 'role': {'type': 'string', 'enum': ['main', 'accompanying']}}}}},
          required=('event_index', 'artists'))
    def set_event_artists(self, ctx, event_index, artists):
        ev = ctx.draft.event(event_index)
        resolved, unmatched = [], []
        for a in artists:
            rec = ctx.s.index.get_artist(a['artist_id']) if a.get('artist_id') else None
            if not rec and a.get('name'):
                rec = ctx.s.index.search_artists(a['name'], a.get('art_form'))['best']
            entry = dict(rec, artist_id=rec['tid']) if rec else {'name': a.get('name'), 'art_form': a.get('art_form')}
            if a.get('art_form'):
                entry['art_form'] = a['art_form']
            resolved.append(ProgramDraft.make_artist(entry, a.get('role') or 'accompanying'))
            if not rec:
                unmatched.append(a.get('name'))
        if resolved and not any(x['role'] == 'main' for x in resolved):
            resolved[0]['role'] = 'main'
        ev['artists'] = resolved
        ctx.draft.bump()
        return {'ok': True, 'event_index': event_index, 'artists': [f"{x['name']} ({x['role']})" for x in resolved],
                'not_in_directory': unmatched}

    @tool('apply_to_all_events', 'Apply the same values to every event (time, module, contribution, audience).',
          {k: EDIT_EVENT_PROPS[k] for k in ('start_time', 'end_time', 'module', 'contribution', 'audience_students', 'audience_other')})
    def apply_to_all_events(self, ctx, **fields):
        return {'ok': True, 'notes': ctx.draft.apply_to_all(fields), 'events': len(ctx.draft.d['events'])}


class ArtistsSkill(Skill):
    key, title, core = 'artists', 'Artists', True
    description = 'Finds artists despite spelling variants, honorifics and Indian scripts; adds new ones provisionally.'

    @tool('find_artist', 'Search the artist directory. Pass role ("main" or "accompanying") when known: a single '
          'strong match is then selected automatically.',
          {'name': S, 'art_form': {'type': 'string', 'description': 'Helps tell similar names apart'},
           'role': {'type': 'string', 'enum': ['main', 'accompanying']}, 'event_index': I}, required=('name',))
    def find_artist(self, ctx, name, art_form=None, role=None, event_index=None):
        res = ctx.s.index.search_artists(name, art_form=art_form)
        matches = res['matches'][:6]
        out = {'query': name, 'ambiguous': res['ambiguous'],
               'matches': [{k: m.get(k) for k in ('tid', 'name', 'art_form', 'city', 'state', 'band', 'flags')} for m in matches]}
        best = res['best']
        if best and role and not best['flags']:
            sel = self.select_artist(ctx, artist_id=best['tid'], role=role, event_index=event_index)
            out.update({k: v for k, v in sel.items() if k != 'ok'})
            out['advice'] = 'Selected automatically (one strong match). Confirm it in one line and continue.'
            return out
        chips = [m for m in matches if m['score'] >= 0.7] or matches[:2]
        if chips:
            ctx.ui.candidates.append({'kind': 'artist', 'title': f'Which artist is "{name}"?', 'role': role or 'main',
                                      'event_index': event_index, 'query': name, 'allow_add': True,
                                      'items': [artist_chip(m, role or 'main', event_index) for m in chips[:5]]})
        web = ctx.s.enricher is not None and ctx.setting('search.web_enrichment', True)
        if not matches:
            out['advice'] = ('Not in the directory. ' + ('Offer web_lookup_artist, then ' if web else 'Offer ')
                             + 'add_artist, asking whether they are the main or an accompanying artist.')
        elif 'deceased' in matches[0]['flags']:
            out['advice'] = ('The closest match is recorded as deceased. Say so gently and ask whether they mean '
                             'someone else, such as a namesake or a disciple.')
        elif res['ambiguous'] or sum(1 for m in matches if m['score'] >= 0.8) > 1:
            out['advice'] = 'Several similar names: ask which one (cards are shown) or ask the art form.'
        elif best:
            out['advice'] = f"One strong match: {best['name']}. Select it with select_artist (ask main or accompanying if unclear)."
        else:
            out['advice'] = 'Only weak matches: show them and ask the coordinator to confirm or spell the name.'
        return out

    @tool('select_artist', 'Put a directory artist on the program (or on one event with event_index).',
          {'artist_id': I, 'role': {'type': 'string', 'enum': ['main', 'accompanying']}, 'event_index': I,
           'art_form': {'type': 'string', 'description': 'Which art form applies, when the artist has several'},
           'acknowledge_flags': {'type': 'boolean', 'description': 'True only if the user confirmed a flagged record is right'}},
          required=('artist_id',))
    def select_artist(self, ctx, artist_id, role='main', event_index=None, art_form=None, acknowledge_flags=False):
        rec = ctx.s.index.get_artist(artist_id)
        if not rec:
            return {'ok': False, 'error': f'No artist with ID {artist_id} in the directory.'}
        if 'deceased' in rec['flags'] and not acknowledge_flags:
            return {'ok': False, 'blocked': 'deceased',
                    'message': f"{rec['name']} is recorded as deceased. If this is a different person with the same "
                               f"name, call select_artist again with acknowledge_flags=true."}
        form = art_form or (rec['art_forms'][0] if len(rec['art_forms']) == 1 else rec['art_form'])
        has_photo = bool(ctx.s.poster and ctx.s.poster.stored_artist_photo_path(rec['tid']))
        flags = [f for f in rec['flags'] if f != 'deceased'] if acknowledge_flags else rec['flags']
        art = ctx.draft.set_artist(dict(rec, artist_id=rec['tid'], art_form=form, has_photo=has_photo, flags=flags),
                                   role or 'main', event_index)
        out = {'ok': True, 'selected': {'artist_id': rec['tid'], 'name': rec['name'], 'art_form': form, 'role': art['role'],
                                        'city': rec['city']},
               'has_photo': has_photo, 'bank_details_on_file': rec['has_bank']}
        if len(rec['art_forms']) > 1 and not art_form:
            out['art_form_options'] = rec['art_forms']
            out['advice'] = 'Listed for several art forms: ask which applies here and call select_artist again with art_form.'
        if rec['provisional']:
            out['note'] = 'Provisional artist, awaiting Artist Care Group approval.'
        return out

    @tool('remove_artist', 'Remove an artist from the program (or from one event).', {'name': S, 'event_index': I}, required=('name',))
    def remove_artist(self, ctx, name, event_index=None):
        return {'ok': ctx.draft.remove_artist(name, event_index)}

    @tool('add_artist', 'Add an artist who is not in the directory. Ask first whether they are the main or an '
          'accompanying artist. The record is provisional until the Artist Care Group approves it.',
          {'name': S, 'art_form': S, 'role': {'type': 'string', 'enum': ['main', 'accompanying']}, 'city': S, 'state': S,
           'email': S, 'phone': S, 'artist_grade': S, 'bank_name': S, 'account_number': S, 'ifsc_code': S,
           'event_index': I, 'force': {'type': 'boolean', 'description': 'Add even though a similar name exists'}},
          required=('name', 'art_form', 'role'))
    def add_artist(self, ctx, name, art_form, role, city=None, state=None, email=None, phone=None, artist_grade=None,
                   bank_name=None, account_number=None, ifsc_code=None, event_index=None, force=False):
        if not force:
            dup = ctx.s.index.search_artists(name, art_form)
            if dup['matches'] and dup['matches'][0]['score'] >= 0.9:
                return {'ok': False, 'possible_duplicates': [{'tid': m['tid'], 'name': m['name'], 'art_form': m['art_form']}
                                                              for m in dup['matches'][:3]],
                        'advice': 'Ask whether it is one of these; use force=true only for a genuinely new artist.'}
        if ifsc_code and not re.fullmatch(r'[A-Z]{4}0[A-Z0-9]{6}', ifsc_code.strip().upper()):
            return {'ok': False, 'error': 'That IFSC looks wrong: 4 letters, a zero, then 6 letters or digits.'}
        if not ctx.s.event_service:
            return {'ok': False, 'error': 'The directory is read-only on this server (no database connection).'}
        res = ctx.s.event_service.add_new_artist({
            'name': name, 'art_form': art_form, 'art_form_category': '', 'city': city or '', 'state': state or '',
            'email': email or '', 'phone': phone or '', 'artist_grade': artist_grade or '', 'bank_name': bank_name,
            'account_number': account_number, 'ifsc_code': (ifsc_code or '').upper() or None, 'added_by': 'AI-PROV'})
        if not res.get('success'):
            return {'ok': False, 'error': res.get('error') or 'Could not add the artist'}
        aid = res['artist_id']
        payload = {'name': name, 'art_form': art_form, 'role': role, 'city': city, 'state': state, 'email': email,
                   'phone': phone, 'program': program_summary(ctx.draft)}
        ctx.s.gov.add_approval('artist', aid, payload, ctx.actor_label)
        notified = notify(ctx, 'email.acg_new_artist', ctx.setting('artists.acg_email', []),
                          {'artist': dict(payload, role=role.title()), 'program_summary': program_summary(ctx.draft)})
        ctx.s.index.invalidate()
        ctx.draft.set_artist({'artist_id': aid, 'name': name, 'art_form': art_form, 'provisional': True,
                              'flags': ['provisional'], 'phone': phone, 'email': email}, role, event_index)
        return {'ok': True, 'artist_id': aid, 'provisional': True, 'role': role, 'acg_notified': notified,
                'message': 'Added provisionally. The Artist Care Group will review it; the program can go ahead meanwhile.'}

    @tool('web_lookup_artist', 'Look an artist up on the web (Wikipedia/Wikidata, Google) when they are not in the '
          'directory. Results are suggestions to confirm.', {'name': S, 'art_form': S}, required=('name',))
    def web_lookup_artist(self, ctx, name, art_form=None):
        if not ctx.s.enricher or not ctx.setting('search.web_enrichment', True):
            return {'ok': False, 'error': 'Web lookups are switched off by an administrator.'}
        results = (ctx.s.enricher.lookup_artist(name, art_form) or {}).get('results') or []
        for x in results[:2]:
            ctx.ui.cards.append({'type': 'web_result', 'entity': 'artist', 'title': x.get('name'), 'source': x.get('source'),
                                 'description': x.get('description'), 'extract': (x.get('extract') or '')[:300],
                                 'url': x.get('url'), 'deceased': x.get('deceased'), 'awards': x.get('awards'),
                                 'instruments': x.get('instruments')})
        return {'ok': True, 'results': results,
                'advice': ('Share the key facts (art form, awards, deceased or not) and ask before add_artist.' if results
                           else 'Nothing reliable on the web either; ask the coordinator for the details.')}

    @tool('request_artist_photo', "Ask for an artist's photo (posters need the MAIN artist's photo; it is kept for "
          'future posters).', {'role': {'type': 'string', 'enum': ['main', 'accompanying']}, 'artist_id': I, 'event_index': I})
    def request_artist_photo(self, ctx, role='main', artist_id=None, event_index=None):
        pool = ctx.draft.effective_artists(ctx.draft.event(event_index)) if event_index is not None else ctx.draft.all_artists()
        art = next((a for a in pool if artist_id and str(a.get('artist_id')) == str(artist_id)), None) or \
            next((a for a in pool if a.get('role') == role), None)
        if not art:
            return {'ok': False, 'error': 'Choose the artist first.'}
        key = art.get('artist_id') or 'n-' + '-'.join(tu.normalize(art['name']).split())
        ctx.state.awaiting = {'kind': 'artist_photo', 'artist_id': key, 'name': art['name'], 'role': art['role']}
        ctx.ui.cards.append({'type': 'upload', 'kind': 'artist_photo', 'title': f"Photo of {art['name']}",
                             'subtitle': f"{art['role'].title()} artist. Kept for their future posters.",
                             'target': {'artist_id': key, 'role': art['role'], 'name': art['name']}})
        return {'ok': True, 'awaiting': 'artist_photo', 'artist': art['name'], 'role': art['role']}


class InstitutionsSkill(Skill):
    key, title, core = 'institutions', 'Institutions', True
    description = 'Finds institutions despite abbreviations (KV, JNV, DPS, IIT) and tells campuses apart.'

    @tool('find_institution', 'Search the institution directory. With one strong match it is set on the event '
          '(event_index, or the only event) including city, state and contact from the directory.',
          {'name': S, 'city': S, 'state': S, 'event_index': I}, required=('name',))
    def find_institution(self, ctx, name, city=None, state=None, event_index=None):
        res = ctx.s.index.search_institutions(name, city=city, state=state)
        idx = event_index if event_index is not None else ctx.draft.default_event_index(create=_wants_outputs(ctx.draft))
        out = {'query': name, 'matches': [{k: m.get(k) for k in ('sid', 'institution_name', 'city', 'state', 'band')}
                                          for m in res['matches'][:6]]}
        if res['campus_choices']:
            out['campus_choices'] = [f"{m['institution_name']} ({m['city']})" for m in res['campus_choices']]
        best = res['best']
        if best and idx is not None:
            apply_institution(ctx, idx, best)
            out.update(selected={'institution_id': best['sid'], 'name': best['institution_name'], 'city': best['city'],
                                 'state': best['state']}, event_index=idx,
                       advice='Matched and set from the directory (city and state included). Mention it in one line.')
            if not best.get('email'):
                out['note'] = 'No email on file; ask for it only when an email has to be sent.'
            return out
        choices = res['campus_choices'] or res['matches'][:5]
        if choices:
            ctx.ui.candidates.append({'kind': 'institution', 'event_index': idx, 'query': name, 'allow_add': True,
                                      'title': 'Which campus?' if res['campus_choices'] else f'Which institution is "{name}"?',
                                      'items': [inst_chip(m, idx) for m in choices]})
        if best and idx is None:
            out['advice'] = 'Strong match, but the draft has several events: call select_institution with event_index.'
        elif res['campus_choices']:
            out['advice'] = 'Several campuses: ask which campus.'
        elif res['matches']:
            out['advice'] = 'Several similar institutions: ask which one, or ask the city.'
        else:
            out['advice'] = 'Not in the directory: offer web_lookup_institution, or add_institution (name, city, state).'
        return out

    @tool('select_institution', 'Set a directory institution on an event (or on all events, e.g. for a Virasat).',
          {'institution_id': I, 'event_index': I, 'apply_to_all': B}, required=('institution_id',))
    def select_institution(self, ctx, institution_id, event_index=None, apply_to_all=False):
        rec = ctx.s.index.get_institution(institution_id)
        if not rec:
            return {'ok': False, 'error': f'No institution with ID {institution_id}.'}
        if apply_to_all or (ctx.draft.d['program_type'] == 'virasat' and event_index is None):
            if not ctx.draft.d['events']:
                ctx.draft.add_event()
            apply_institution(ctx, None, rec, apply_all=True)
            where = 'all events'
        else:
            idx = event_index if event_index is not None else ctx.draft.default_event_index(create=True)
            if idx is None:
                return {'ok': False, 'error': 'Which event is this for? Pass event_index.'}
            apply_institution(ctx, idx, rec)
            where = f'event {idx + 1}'
        return {'ok': True, 'selected': {'institution_id': rec['sid'], 'name': rec['institution_name'],
                                         'city': rec['city'], 'state': rec['state']}, 'applied_to': where,
                'email_on_file': bool(rec.get('email'))}

    @tool('add_institution', 'Add an institution that is not in the directory (after confirming with the coordinator).',
          {'name': S, 'city': S, 'state': S, 'email': S, 'phone': S, 'event_index': I, 'force': B},
          required=('name', 'city', 'state'))
    def add_institution(self, ctx, name, city, state, email=None, phone=None, event_index=None, force=False):
        if not force:
            dup = ctx.s.index.search_institutions(name, city=city)
            if dup['best'] or (dup['matches'] and dup['matches'][0]['score'] >= 0.92):
                m = dup['best'] or dup['matches'][0]
                return {'ok': False, 'possible_duplicate': {'sid': m['sid'], 'name': m['institution_name'], 'city': m['city']},
                        'advice': 'Ask whether it is this one; use force=true only for a genuinely new institution.'}
        if not ctx.s.event_service:
            return {'ok': False, 'error': 'The directory is read-only on this server (no database connection).'}
        res = ctx.s.event_service.add_new_institution({'name': name, 'city': city, 'state': state, 'email': email or '',
                                                       'phone': phone or ''})
        if not res.get('success'):
            return {'ok': False, 'error': res.get('error') or 'Could not add the institution'}
        sid = res['institution_id']
        ctx.s.gov.add_approval('institution', sid, {'name': name, 'city': city, 'state': state, 'email': email,
                                                    'program': program_summary(ctx.draft)}, ctx.actor_label)
        ctx.s.index.invalidate()
        rec = {'sid': sid, 'institution_name': name, 'city': city, 'state': state, 'email': email, 'phone': phone}
        idx = event_index if event_index is not None else ctx.draft.default_event_index(create=True)
        if idx is not None:
            apply_institution(ctx, idx, rec)
        return {'ok': True, 'institution_id': sid, 'applied_to_event': idx}

    @tool('web_lookup_institution', 'Look an institution up on the web (Google Places or OpenStreetMap) to get its '
          'city, state and address. Results are suggestions to confirm.', {'name': S, 'city': S}, required=('name',))
    def web_lookup_institution(self, ctx, name, city=None):
        if not ctx.s.enricher or not ctx.setting('search.web_enrichment', True):
            return {'ok': False, 'error': 'Web lookups are switched off by an administrator.'}
        results = (ctx.s.enricher.lookup_institution(name, city) or {}).get('results') or []
        for x in results[:3]:
            ctx.ui.cards.append({'type': 'web_result', 'entity': 'institution', 'title': x.get('name'), 'source': x.get('source'),
                                 'description': x.get('address') or '', 'url': x.get('maps_url') or x.get('website') or x.get('url'),
                                 'city': x.get('city'), 'state': x.get('state')})
        return {'ok': True, 'results': results}


class CoordinatorsSkill(Skill):
    key, title, core = 'coordinators', 'Coordinators', True
    description = 'The filing coordinator plus any co-coordinators, checked against the coordinator directory.'

    @tool('find_coordinator', 'Search coordinators by name or email.', {'query': S}, required=('query',))
    def find_coordinator(self, ctx, query):
        r = ctx.s.index.search_coordinators(query)['matches']
        if len(r) > 1:
            ctx.ui.candidates.append({'kind': 'coordinator', 'title': f'Which coordinator is "{query}"?', 'query': query,
                                      'items': [{'kind': 'coordinator', 'id': m['email'], 'label': m['name'] or m['email'],
                                                 'meta': m['email'] + (f", {m['institution_name']}" if m.get('institution_name') else ''),
                                                 'email': m['email'], 'band': 'strong'} for m in r]})
        return {'matches': r}

    @tool('add_coordinator', 'Associate a coordinator with the program. role "filer" is the person filing; others are '
          '"co-coordinator". Only directory coordinators can be added (others become a request to admins).',
          {'name': S, 'email': S, 'phone': S, 'chapter': S, 'role': {'type': 'string', 'enum': ['filer', 'co-coordinator']}})
    def add_coordinator(self, ctx, name=None, email=None, phone=None, chapter=None, role='co-coordinator'):
        if not (name or email):
            return {'ok': False, 'error': 'Give a name or an email.'}
        rec = ctx.s.index.find_coordinator_by_email(email) if email else None
        if not rec and name and not email:
            r = ctx.s.index.search_coordinators(name)['matches']
            if r and r[0]['score'] >= 0.9 and (len(r) == 1 or r[1]['score'] < r[0]['score'] - 0.05):
                rec = r[0]
            elif r:
                return dict(self.find_coordinator(ctx, name), ok=False, advice='Ask which coordinator this is (cards are shown).')
        if not rec:
            if ctx.setting('coordinators.directory_only', True):
                requested = {'name': name, 'email': email, 'phone': phone, 'chapter': chapter}
                aid = ctx.s.gov.add_approval('coordinator_request', email or name, dict(requested, program=program_summary(ctx.draft)),
                                             ctx.actor_label)
                notified = notify(ctx, 'email.coordinator_request', ctx.setting('coordinators.admin_email', []),
                                  {'requested': requested, 'program_summary': program_summary(ctx.draft)})
                return {'ok': False, 'not_in_directory': True, 'request_id': aid, 'admins_notified': notified,
                        'advice': 'Not in the coordinator directory. A request went to the admin team; continue without them for now.'}
            rec = {'name': name, 'email': email}
        c = ctx.draft.add_coordinator({'uid': rec.get('uid'), 'name': rec.get('name') or name, 'email': rec.get('email') or email,
                                       'phone': phone, 'chapter': chapter, 'role': role})
        return {'ok': True, 'coordinator': c, 'coordinators': [x.get('name') or x.get('email') for x in ctx.draft.d['coordinators']]}

    @tool('remove_coordinator', 'Remove a coordinator from the program.', {'name_or_email': S}, required=('name_or_email',))
    def remove_coordinator(self, ctx, name_or_email):
        return {'ok': ctx.draft.remove_coordinator(name_or_email)}
