"""HTTP API behind the new assistant: chat, taps on the interface (actions), uploads, voice
and authenticated file downloads. Taps call exactly the same skill tools the AI uses."""
import base64
import csv
import io
import json
import logging
import time

from flask import Blueprint, Response, abort, current_app, jsonify, request, send_file, session

from app.agents import prompts
from app.core.auth import assistant_user, current_user, is_admin, require_assistant
from app.core.text_utils import clean_for_speech
from app.services.voice_service import BROWSER_LOCALES, build_vocabulary_prompt
from app.skills.base import SkillContext

logger = logging.getLogger(__name__)
bp = Blueprint('assistant_api', __name__)
MAX_UPLOAD = 12 * 1024 * 1024
# Buttons may run these directly; none of them sends an email or files anything without a
# further confirmation step.
SAFE_TOOLS = {'review_program', 'preview_apr_pdf', 'payment_request_pdf', 'prepare_payment_requests', 'prepare_guidelines',
              'generate_poster', 'request_artist_photo', 'request_cheque_upload', 'find_institution', 'find_artist', 'get_draft'}


def svc():
    return current_app.extensions['spicmacay']


def _actor():
    u = assistant_user() or {}
    return {'email': u.get('email'), 'name': u.get('name'), 'role': u.get('role')}


def _state(create=True):
    s, cid = svc(), session.get('conv_id')
    st = s.store.load(cid) if cid else None
    u = current_user() or {}
    if st and st.user.get('email') and (u.get('email') or '').lower() != st.user['email'].lower():
        st = None                                       # never continue someone else's conversation
    if st is None and create:
        st = s.store.new(user=u if u.get('email') else None)
        session['conv_id'] = st.id
        session.permanent = True
    return st


def _remember_files(ui):
    """Files shown to this session (documents, previews, poster thumbnails) may be downloaded by it."""
    names = []

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k == 'filename' and isinstance(v, str):
                    names.append(v)
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, str) and '/api/assistant/files/' in x:
            names.append(x.rsplit('/', 1)[-1].split('?')[0])
    walk(ui or {})
    if names:
        known = session.get('files', [])
        session['files'] = (known + [n for n in names if n not in known])[-80:]


def _payload(st, ui=None, reply=None):
    d = st.draft
    return {'reply': reply, 'draft': d.to_dict(), 'issues': d.issues(), 'progress': d.progress(),
            'ui': ui or {'candidates': [], 'cards': [], 'artifacts': [], 'notices': []},
            'suggestions': prompts.suggestions(svc(), st), 'language': st.language, 'conversation_id': st.id}


def _finish(st, result):
    svc().store.save(st)
    _remember_files(result.get('ui'))
    return jsonify(result)


def _visible_history(st):
    out = [{'role': m['role'], 'text': m['content']} for m in st.history[-80:]
           if m.get('role') in ('user', 'assistant') and m.get('content') and not m.get('tool_calls')
           and not str(m['content']).startswith('[')]
    return out[-30:]


def _action_reply(res):
    if not res:
        return None
    if res.get('ok') is False:
        return res.get('error') or res.get('message') or res.get('advice') or 'That did not work.'
    if res.get('apr_number'):
        dry = 'dry run' in str(res.get('email'))
        return f"APR **{res['apr_number']}** is filed. The PDF is below" + ('; the email was saved as a dry run.' if dry else ' and has been emailed.')
    if 'sent' in res:
        return (f"Sent {res['sent']} email{'s' if res['sent'] != 1 else ''}" + (' (dry run: saved, not sent)' if res.get('dry_run') else '')
                + (f", {res['failed']} failed" if res.get('failed') else '') + '.')
    if res.get('saved'):
        sv = res['saved']
        return f"Saved bank details: {sv.get('bank_name') or ''} {sv.get('account')} ({sv.get('ifsc')})."
    return None


@bp.post('/start')
@require_assistant
def start():
    s, body = svc(), request.get_json(silent=True) or {}
    if body.get('new'):
        session.pop('conv_id', None)
    rid, u = body.get('resume_id'), current_user() or {}
    if rid and u.get('email'):
        data = s.gov.load_conversation(rid)
        if data and ((data.get('user') or {}).get('email') or '').lower() == u['email'].lower():
            session['conv_id'] = rid
    st = _state()
    if body.get('language'):
        st.language = body['language']
    history = _visible_history(st)
    payload = _payload(st, reply=None if history else prompts.greeting(st.language, s))
    if not history:
        st.history.append({'role': 'assistant', 'content': payload['reply']})
    au = assistant_user() or {}
    payload.update({'resumed': bool(history), 'history': history, 'recipes': prompts.recipes(st.language, s),
                    'user': {k: au.get(k) for k in ('name', 'email', 'role')}, 'is_admin': is_admin(u),
                    'recent': s.gov.recent_conversations(u['email']) if u.get('email') else [],
                    'ai_ready': s.llm_factory is not None,
                    'voice': {'server_stt': bool(s.voice and s.voice.available),
                              'server_tts': bool(s.voice and s.voice.available and s.setting('voice.server_tts', True)),
                              'locales': BROWSER_LOCALES}})
    return _finish(st, payload)


@bp.post('/chat')
@require_assistant
def chat():
    body = request.get_json(silent=True) or {}
    text = (body.get('message') or '').strip()[:4000]
    if not text:
        return jsonify({'error': 'Type or say something first.'}), 400
    st = _state()
    if body.get('language'):
        st.language = body['language']
    return _finish(st, svc().orchestrator.run_turn(st, text, actor=_actor()))


@bp.get('/draft')
@require_assistant
def get_draft():
    st = _state()
    return _finish(st, _payload(st))


@bp.get('/conversations')
@require_assistant
def conversations():
    u = current_user() or {}
    return jsonify({'recent': svc().gov.recent_conversations(u['email']) if u.get('email') else []})


@bp.post('/action')
@require_assistant
def action():
    s, body = svc(), request.get_json(silent=True) or {}
    typ, p = body.get('type'), body.get('payload') or {}
    st = _state()
    ctx = SkillContext(s, st, actor=_actor(), via='button')
    note = res = None
    try:
        if typ == 'select_candidate':
            kind = p.get('kind')
            if kind == 'artist':
                res = s.registry.execute('select_artist', {'artist_id': p.get('id'), 'role': p.get('role') or 'main',
                                                           'event_index': p.get('event_index'),
                                                           'acknowledge_flags': p.get('acknowledge_flags')}, ctx)
                note = f"[Tapped artist: {p.get('label')} as {p.get('role') or 'main'} artist]"
            elif kind == 'institution':
                res = s.registry.execute('select_institution', {'institution_id': p.get('id'), 'event_index': p.get('event_index')}, ctx)
                note = f"[Tapped institution: {p.get('label')}]"
            elif kind == 'coordinator':
                res = s.registry.execute('add_coordinator', {'email': p.get('email') or p.get('id'), 'name': p.get('label'),
                                                             'role': p.get('role') or 'co-coordinator'}, ctx)
                note = f"[Tapped coordinator: {p.get('label')}]"
            else:
                return jsonify({'error': 'Unknown choice'}), 400
        elif typ == 'update_field':
            res = {'ok': True, 'notes': st.draft.patch(p.get('path'), p.get('value'))}
            note = f"[Edited {p.get('path')} in the draft to {p.get('value')!r}]"
        elif typ == 'add_event':
            st.draft.add_event({})
            res, note = {'ok': True}, '[Added an empty event row to the draft]'
        elif typ == 'remove_event':
            st.draft.remove_event(int(p.get('index')))
            res, note = {'ok': True}, f"[Removed event {int(p.get('index')) + 1} from the draft]"
        elif typ == 'remove_artist':
            res, note = {'ok': st.draft.remove_artist(p.get('ref'), p.get('event_index'))}, f"[Removed artist {p.get('ref')}]"
        elif typ == 'remove_coordinator':
            res, note = {'ok': st.draft.remove_coordinator(p.get('ref'))}, f"[Removed coordinator {p.get('ref')}]"
        elif typ == 'set_recipe':
            st.draft.set_recipe(p)
            res = {'ok': True}
            note = f"[Outputs wanted: {', '.join(k.replace('_', ' ') for k, v in st.draft.d['recipe'].items() if v) or 'none'}]"
        elif typ == 'start_recipe':
            rec = prompts.recipe_by_key(p.get('key'))
            if not rec:
                return jsonify({'error': 'Unknown option'}), 400
            st.draft.set_recipe(rec['recipe'])
            if rec.get('program_type'):
                st.draft.set_program({'program_type': rec['program_type']})
            return _finish(st, s.orchestrator.run_turn(st, prompts.recipe_message(rec, st.language), actor=_actor()))
        elif typ == 'confirm':
            cid = p.get('confirmation_id')
            kind = (st.pending.get(cid) or {}).get('kind')
            if kind == 'create_apr':
                res, note = s.registry.execute('create_apr', {'confirmation_id': cid}, ctx), '[Tapped "File APR"]'
            elif kind == 'send_emails':
                res = s.registry.execute('send_prepared_emails', {'confirmation_id': cid, 'item_ids': p.get('item_ids')}, ctx)
                note = '[Tapped "Send"]'
            elif kind == 'bank_details':
                from app.skills.output_skills import confirm_bank_proposal
                res, note = confirm_bank_proposal(ctx, cid), '[Tapped "Save bank details"]'
            elif kind == 'file_batch':
                res = s.registry.execute('batch_file', {'confirmation_id': cid, 'email_mode': p.get('email_mode')}, ctx)
                note = '[Tapped "File" on the batch plan]'
                if res.get('ok'):
                    filed = res['filed']
                    st.history.append({'role': 'user', 'content': f"{note} Result: {json.dumps({'filed': [r['apr_number'] for r in filed], 'failed': [r['title'] for r in res['failed']]})}"})
                    reply = (f"Filed **{len(filed)} APR{'s' if len(filed) != 1 else ''}**: " + ', '.join(f"{r['apr_number']} ({r['title']})" for r in filed) + '.'
                             if filed else 'Nothing was filed.')
                    if res['failed']:
                        reply += ' Could not file: ' + '; '.join(f"{r['title']} ({r['error']})" for r in res['failed']) + '.'
                    if res['still_open']:
                        reply += ' Still needing your input: ' + ', '.join(res['still_open']) + '.'
                    reply += ('\n\nEach APR has been emailed to the coordinators. Which institutions should get a **Request for Payment**? '
                              'Tick them below and enter the contribution amounts.') if filed else ''
                    st.history.append({'role': 'assistant', 'content': reply})
                    return _finish(st, _payload(st, ctx.ui.to_dict(), reply))
            else:
                res = {'ok': False, 'error': 'That confirmation has expired. Ask me to review it again.'}
        elif typ == 'run_tool':
            name = p.get('name')
            if name not in SAFE_TOOLS:
                return jsonify({'error': 'That action is not available from a button.'}), 400
            res = s.registry.execute(name, p.get('args') or {}, ctx)
            note = f"[Tapped \"{p.get('label') or name}\"]"
        elif typ.startswith('batch_'):
            return _batch_action(s, st, ctx, typ, p)
        elif typ == 'reset':
            s.registry.execute('reset_draft', {'keep_coordinators': True}, ctx)
            res, note = {'ok': True}, '[Started a new program draft]'
        elif typ == 'set_language':
            st.language = p.get('language') or 'auto'
            res = {'ok': True}
        else:
            return jsonify({'error': f'Unknown action {typ}'}), 400
    except (IndexError, KeyError, ValueError, TypeError) as e:
        res = {'ok': False, 'error': str(e).strip("'")}
    if note:
        brief = {k: v for k, v in (res or {}).items() if k in ('ok', 'error', 'selected', 'apr_number', 'sent', 'failed',
                                                                 'dry_run', 'saved', 'message', 'advice', 'blocked', 'notes')}
        st.history.append({'role': 'user', 'content': f"{note} Result: {json.dumps(brief, default=str, ensure_ascii=False)[:700]}"})
    if body.get('continue') and s.llm_factory and typ not in ('update_field', 'set_language', 'set_recipe'):
        return _finish(st, s.orchestrator.run_turn(st, None, actor=_actor(), ui=ctx.ui))
    reply = _action_reply(res)
    if reply:
        st.history.append({'role': 'assistant', 'content': reply})
    return _finish(st, _payload(st, ctx.ui.to_dict(), reply))


def _batch_action(s, st, ctx, typ, p):
    """Taps on the batch plan card. Each one updates the plan and re-renders the card in place."""
    from app.agents.state import ConversationState
    from app.skills.batch import BatchPlanner, batch_coordinators, plan_card, prepare_rfp
    plan = st.batch
    if not plan:
        return jsonify({'error': 'There is no batch plan yet. Attach several posters first.'}), 400
    planner, reply = BatchPlanner(s), None
    prog = next((x for x in plan['programs'] if x['pid'] == p.get('pid')), None)
    if typ == 'batch_toggle':
        if prog and p.get('eid'):
            ev = next((e for e in prog['events'] if e['eid'] == p['eid']), None)
            if ev:
                ev['include'] = bool(p.get('include'))
        elif prog:
            prog['include'] = bool(p.get('include'))
    elif typ == 'batch_type' and prog and p.get('program_type') in ('single', 'virasat', 'circuit'):
        prog['type'] = p['program_type']
    elif typ == 'batch_pick':
        ok = planner.pick_artist(plan, p.get('said'), p.get('role') or 'main', p.get('id')) if p.get('kind') == 'artist' \
            else planner.pick_institution(plan, p.get('said'), p.get('id'))
        reply = None if ok else 'That choice could not be applied; please try again.'
    elif typ == 'batch_add':
        tmp = ConversationState()
        tmp.draft.d['coordinators'] = [dict(c) for c in st.draft.d['coordinators']]
        tctx = SkillContext(s, tmp, actor=ctx.actor, via='button', ui=ctx.ui)
        if p.get('kind') == 'artist':
            r = s.registry.execute('add_artist', {'name': p.get('said'), 'art_form': p.get('art_form') or 'Not specified',
                                                  'role': p.get('role') or 'main', 'force': True}, tctx)
            if r.get('ok'):
                planner.pick_artist(plan, p.get('said'), p.get('role') or 'main', r['artist_id'])
                reply = f"Added **{p.get('said')}** as a provisional artist; the Artist Care Group has been asked to approve it."
        else:
            r = s.registry.execute('add_institution', {'name': p.get('name') or p.get('said'), 'city': p.get('city') or '',
                                                       'state': p.get('state') or '', 'email': p.get('email'), 'force': True}, tctx)
            if r.get('ok'):
                planner.pick_institution(plan, p.get('said'), r['institution_id'])
                reply = f"Added **{p.get('name') or p.get('said')}** to the directory (pending approval)."
        if not r.get('ok'):
            reply = r.get('error') or 'Could not add it.'
    elif typ == 'batch_coordinator':
        r = s.registry.execute('add_coordinator', {'email': (p.get('email') or '').strip(), 'role': 'filer'}, ctx)
        reply = None if r.get('ok') else (r.get('advice') or r.get('error') or 'That email is not in the coordinator directory.')
    elif typ == 'batch_email_mode':
        plan['email_mode'] = 'combined' if p.get('mode') == 'combined' else 'each'
        return _finish(st, _payload(st, ctx.ui.to_dict(), None))
    elif typ == 'batch_rfp':
        r = prepare_rfp(ctx, p.get('rows') or [])
        reply = (r.get('error') if not r.get('ok') else
                 f"Prepared {len(r['items'])} Request{'s' if len(r['items']) != 1 else ''} for Payment. Check the recipients and amounts, then tap **Send**.")
        st.history.append({'role': 'user', 'content': '[Chose Requests for Payment from the batch]'})
        st.history.append({'role': 'assistant', 'content': reply})
        return _finish(st, _payload(st, ctx.ui.to_dict(), reply))
    elif typ != 'batch_show':
        return jsonify({'error': 'Unknown batch action'}), 400
    planner.refresh(plan, batch_coordinators(ctx))
    ctx.ui.cards.append(plan_card(ctx, plan))
    if reply:
        st.history.append({'role': 'assistant', 'content': reply})
    return _finish(st, _payload(st, ctx.ui.to_dict(), reply))


@bp.post('/batch')
@require_assistant
def batch_upload():
    """Several posters at once: read them all, merge duplicates, group into programs, show the plan."""
    import uuid
    from app.skills.batch import BatchPlanner, batch_coordinators, plan_card, plan_reply, read_posters
    s, body = svc(), request.get_json(silent=True) or {}
    files = (body.get('files') or [])[:20]
    if not files:
        return jsonify({'error': 'Attach the posters first.'}), 400
    if not s.llm_factory:
        return jsonify({'error': 'Reading posters needs the AI service (OPENAI_API_KEY is not set).'}), 400
    st = _state()
    ctx = SkillContext(s, st, actor=_actor(), via='button')
    posters = []
    for f in files:
        try:
            raw = base64.b64decode((f.get('data') or '').split(',', 1)[-1])
        except Exception:
            raw = b''
        pid = uuid.uuid4().hex[:6]
        if not raw or len(raw) > MAX_UPLOAD:
            posters.append({'pid': pid, 'filename': f.get('filename'), 'error': 'The file could not be read', 'b64': ''})
            continue
        fname = s.files.save('docs', f'poster_{st.id[:6]}_{pid}.jpg', raw)
        posters.append({'pid': pid, 'filename': f.get('filename') or fname, 'file': fname, 'thumb': s.file_url('docs', fname),
                        'b64': base64.b64encode(raw).decode(), 'mime': f.get('mime') or 'image/jpeg'})
    readable = [p for p in posters if p.get('b64')]
    read_posters(ctx, readable)
    for p in posters:
        p.pop('b64', None)
    plan = BatchPlanner(s).build(posters, batch_coordinators(ctx))
    st.batch = plan
    ctx.ui.cards.append(plan_card(ctx, plan))
    reply = plan_reply(plan)
    st.history.append({'role': 'user', 'content': f'[Uploaded {len(posters)} posters to file their APRs together]'})
    st.history.append({'role': 'assistant', 'content': reply})
    s.gov.audit(ctx.actor_label, 'batch.read', plan['id'], {'posters': len(posters), 'programs': len(plan['programs'])})
    return _finish(st, _payload(st, ctx.ui.to_dict(), reply))


_STOP_COLS = {'date': 'date', 'event date': 'date', 'institution': 'institution', 'school': 'institution',
              'college': 'institution', 'venue': 'institution', 'city': 'city', 'state': 'state', 'time': 'start_time',
              'start time': 'start_time', 'end time': 'end_time', 'contribution': 'contribution', 'amount': 'contribution',
              'module': 'module', 'audience': 'audience_students', 'students': 'audience_students'}


def parse_stops_file(raw, filename):
    rows = []
    if filename.lower().endswith(('.xlsx', '.xlsm')):
        try:
            from openpyxl import load_workbook
            ws = load_workbook(io.BytesIO(raw), read_only=True, data_only=True).active
            it = ws.iter_rows(values_only=True)
            header = [str(h or '').strip().lower() for h in next(it)]
            rows = [{header[i]: v for i, v in enumerate(r) if i < len(header)} for r in it]
        except Exception as e:
            logger.warning('Could not read spreadsheet: %s', e)
            return []
    else:
        text = raw.decode('utf-8-sig', errors='replace')
        rows = [{(k or '').strip().lower(): v for k, v in r.items()} for r in csv.DictReader(io.StringIO(text))]
    out = []
    for r in rows:
        m = {}
        for k, v in r.items():
            key = _STOP_COLS.get(k)
            if key and v not in (None, ''):
                m[key] = v.isoformat() if hasattr(v, 'isoformat') else str(v).strip()
        if m.get('date') or m.get('institution'):
            out.append(m)
    return out[:40]


@bp.post('/upload')
@require_assistant
def upload():
    s, body = svc(), request.get_json(silent=True) or {}
    kind, mime = body.get('kind'), body.get('mime') or 'image/jpeg'
    try:
        raw = base64.b64decode((body.get('data') or '').split(',', 1)[-1])
    except Exception:
        return jsonify({'error': 'The file could not be read.'}), 400
    if not raw or len(raw) > MAX_UPLOAD:
        return jsonify({'error': 'Files must be under 12 MB.'}), 400
    st = _state()
    ctx = SkillContext(s, st, actor=_actor(), via='button')
    target, note, res = body.get('target') or {}, None, None
    if kind == 'auto':
        kind = (st.awaiting or {}).get('kind') or 'poster'
    if kind == 'artist_photo':
        tgt = dict(st.awaiting or {}) if (st.awaiting or {}).get('kind') == 'artist_photo' else {}
        tgt.update({k: v for k, v in target.items() if v})
        key = tgt.get('artist_id') or (st.draft.d.get('main_artist') or {}).get('artist_id')
        if not key or not s.poster:
            res = {'ok': False, 'error': 'Choose the artist first, then upload their photo.'}
        elif s.poster.save_artist_photo(raw, key):
            st.draft.mark_photo(key)
            st.awaiting, res = None, {'ok': True}
            note = f"[Uploaded a photo of {tgt.get('name') or 'the artist'} ({tgt.get('role') or 'main'} artist); saved for posters]"
        else:
            res = {'ok': False, 'error': 'The photo could not be saved; please try another image.'}
    elif kind == 'cheque':
        from app.skills.output_skills import read_cheque
        tgt = target or {k: (st.awaiting or {}).get(k) for k in ('entity', 'id', 'name')}
        res = read_cheque(ctx, base64.b64encode(raw).decode(), mime, tgt)
        st.awaiting = None
        note = '[Uploaded a cancelled cheque; the details were read for confirmation]'
    elif kind == 'poster':
        from app.skills.output_skills import extract_poster
        st.uploads['poster'] = s.files.save('uploads', f'poster_{st.id[:8]}_{int(time.time())}.jpg', raw)
        res = extract_poster(ctx, base64.b64encode(raw).decode(), mime)
        note = ('[Uploaded a program poster. Read into the draft: '
                + json.dumps(res.get('summary') if res.get('ok') else res, default=str, ensure_ascii=False)[:1500] + ']')
    elif kind == 'program_photo':
        fname = s.files.save('uploads', f'photo_{st.id[:8]}_{int(time.time() * 1000)}.jpg', raw)
        st.uploads.setdefault('program_photos', []).append(fname)
        res, note = {'ok': True}, '[Attached a program photo; it will go with the APR email]'
    elif kind == 'stops':
        from app.skills.core_skills import add_events_impl
        rows = parse_stops_file(raw, body.get('filename') or '')
        if not rows:
            res = {'ok': False, 'error': 'No rows found. Use columns such as Date, Institution, City, Time, Contribution.'}
        else:
            out = add_events_impl(ctx, rows)
            res = {'ok': True, 'added': len(out)}
            note = f"[Imported {len(out)} events from a file: {json.dumps(out, default=str, ensure_ascii=False)[:1500]}]"
    else:
        return jsonify({'error': 'Unknown upload type'}), 400
    if note:
        st.history.append({'role': 'user', 'content': note})
    if s.llm_factory and res and res.get('ok', True) and kind in ('poster', 'stops', 'artist_photo', 'cheque'):
        return _finish(st, s.orchestrator.run_turn(st, None, actor=_actor(), ui=ctx.ui))
    reply = (res or {}).get('error') or {
        'artist_photo': 'Photo saved; it will be used on posters for this artist.', 'program_photo': 'Photo attached; it will go with the APR email.',
        'poster': 'I read the poster into the draft; please check the details.', 'stops': 'Events imported into the draft.',
        'cheque': 'Please check the bank details read from the cheque.'}.get(kind)
    st.history.append({'role': 'assistant', 'content': reply})
    return _finish(st, _payload(st, ctx.ui.to_dict(), reply))


@bp.post('/voice/transcribe')
@require_assistant
def voice_transcribe():
    s, f = svc(), request.files.get('audio')
    if not f:
        return jsonify({'success': False, 'error': 'No audio received.'}), 400
    st = _state()
    lang = (request.form.get('language') or st.language or 'auto').lower()
    names = [a.get('name') for a in st.draft.all_artists() if a.get('name')] + s.index.popular_artist_names(15)
    insts = [e.get('institution_name') for e in st.draft.d['events'] if e.get('institution_name')]
    prompt = build_vocabulary_prompt(lang if lang in ('hi', 'hinglish') else 'en', list(dict.fromkeys(names)), insts)
    r = s.voice.transcribe(f.read(), f.filename or 'speech.webm', None if lang in ('auto', 'hinglish') else lang, prompt)
    return jsonify(r), (200 if r.get('success') else 502)


@bp.post('/voice/speak')
@require_assistant
def voice_speak():
    s, body = svc(), request.get_json(silent=True) or {}
    if not (s.voice and s.voice.available and s.setting('voice.server_tts', True)):
        return '', 204
    text = clean_for_speech(body.get('text') or '')
    audio = s.voice.synthesize(text, language=body.get('language')) if text else b''
    return Response(audio, mimetype='audio/mpeg') if audio else ('', 204)


@bp.get('/files/<kind>/<path:filename>')
@require_assistant
def download_file(kind, filename):
    from app.core.files import PUBLIC_KINDS
    s = svc()
    if kind not in PUBLIC_KINDS:
        abort(404)
    name = s.files.safe_name(filename)
    allowed = name in session.get('files', []) or is_admin(current_user())
    if not allowed:
        st = _state(create=False)
        allowed = bool(st) and (name in json.dumps(st.draft.d.get('outputs', {})) or name in json.dumps(st.batch or {}))
    if not allowed:
        abort(403)
    if not s.files.exists(kind, name):
        abort(404)
    return send_file(s.files.path(kind, name), as_attachment=request.args.get('dl') == '1', download_name=name)
