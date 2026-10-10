"""Admin console API: templates (versioned, with live preview), settings and skill switches,
approvals (provisional artists and institutions, coordinator requests), directory flags and the
activity log. Every change is audited."""
import base64
import json
from datetime import date

from flask import Blueprint, current_app, jsonify, render_template, request

from app.core.auth import auth_mode, current_user, require_admin
from app.core.default_templates import DEFAULT_TEMPLATES, sample_context
from app.core.governance import schema_dicts
from app.core.rendering import bank_context

bp = Blueprint('admin', __name__)
POSTER_SAMPLE = {'institution_name': 'Delhi Public School', 'artist_name': 'Pt. Ronu Majumdar', 'art_form': 'Flute',
                 'module_name': 'Lecture Demonstration', 'start_date': '2026-02-16', 'event_time': '10:00 AM',
                 'venue': 'DPS Nashik', 'city': 'Nashik', 'state': 'Maharashtra', 'chapter': 'SPIC MACAY Mumbai',
                 'coordinator_name': 'Sabyasachi', 'accompanying_artists': ['Ajeet Pathak']}


def svc():
    return current_app.extensions['spicmacay']


def _actor():
    u = current_user() or {}
    return u.get('email') or u.get('name') or 'admin'


def _sample(s, key):
    kind = 'virasat' if key.endswith('virasat') else 'single' if key.endswith('single') else 'circuit'
    return sample_context(s.org(), kind)


def _preview(s, key, kind, body, subject=None, text=None):
    if kind == 'email':
        msg = s.renderer.render_email(key, _sample(s, key), override={'body': body, 'subject': subject or '',
                                                                       'meta': {'text': text} if text else {}})
        return {'type': 'html', 'subject': msg['subject'], 'html': msg['html'], 'text': msg['text']}
    if kind == 'email_layout':
        return {'type': 'html', 'subject': '(email frame)', 'html': s.renderer.env.from_string(body).render(**_sample(s, key))}
    if kind == 'apr_layout':
        return {'type': 'pdf', 'data': base64.b64encode(s.pdf.render_apr(json.loads(body), _sample(s, key))).decode()}
    if kind == 'rfp_layout':
        layout, ctx = json.loads(body), _sample(s, key)
        desc = s.renderer.text(layout.get('description', ''), {'program': {'title': 'Maharashtra Circuit'},
                                                               'e': {'module': 'Lecture Demonstration', 'art_form': 'Flute',
                                                                     'artists_text': 'Pt. Ronu Majumdar with Ajeet Pathak'}})
        ctx.update(invoice_date=date.today().strftime('%d %b %Y'), bank=bank_context(s.setting),
                   signatory={'name': s.setting('rfp.signatory_name', ''), 'title': s.setting('rfp.signatory_title', '')},
                   line_items=[{'sl': 1, 'description': desc, 'date': '16 Feb 2026', 'amount': 'Rs 10,000'}])
        return {'type': 'pdf', 'data': base64.b64encode(s.pdf.render_rfp(layout, ctx)).decode()}
    if kind == 'poster_style':
        jpg = s.poster.generate_with_style(POSTER_SAMPLE, json.loads(body)) if s.poster else b''
        return {'type': 'image', 'data': base64.b64encode(jpg or b'').decode()}
    return {'type': 'text', 'text': body}


def _validate(s, key, kind, body, subject, text):
    if kind == 'email':
        v = s.renderer.validate(body, subject, ctx=_sample(s, key))
        if v['ok'] and text:
            v2 = s.renderer.validate(text, ctx=_sample(s, key), autoescape=False)
            v = v if v2['ok'] else v2
        return v
    if kind == 'email_layout':
        return s.renderer.validate(body, ctx=_sample(s, key))
    if kind in ('apr_layout', 'rfp_layout', 'poster_style'):
        try:
            obj = json.loads(body)
        except ValueError as e:
            return {'ok': False, 'error': f'Not valid JSON: {e}'}
        if not isinstance(obj, dict):
            return {'ok': False, 'error': 'The layout must be a JSON object.'}
        if kind == 'apr_layout' and not isinstance(obj.get('sections'), list):
            return {'ok': False, 'error': 'An APR layout needs a "sections" list.'}
        try:
            _preview(s, key, kind, body)
        except Exception as e:
            return {'ok': False, 'error': f'The layout does not render: {e}'}
        return {'ok': True}
    if kind == 'prompt' and len(body or '') > 4000:
        return {'ok': False, 'error': 'Keep house rules under 4,000 characters.'}
    return {'ok': True}


@bp.get('/admin')
@require_admin
def admin_home():
    return render_template('admin.html', user=current_user())


@bp.get('/admin/api/overview')
@require_admin
def overview():
    s = svc()
    return jsonify({'status': {'ai': s.llm_factory is not None, 'email': s.mailer.configured,
                               'email_dry_run': bool(s.setting('email.dry_run', False)),
                               'google': bool(getattr(s.enricher, 'key', '')), 'database': s.writer is not None,
                               'auth_mode': auth_mode(), 'voice': bool(s.voice and s.voice.available)},
                    'pending_approvals': len(s.gov.list_approvals('pending')), 'audit': s.gov.list_audit(15),
                    'usage': s.gov.list_usage(7), 'models': {'conversation': s.setting('assistant.model'),
                                                             'vision': s.setting('assistant.vision_model'),
                                                             'speech': s.setting('voice.stt_model')},
                    'skills': s.registry.describe(s)})


@bp.get('/admin/api/templates')
@require_admin
def templates():
    return jsonify({'templates': svc().gov.list_templates()})


@bp.get('/admin/api/templates/<key>')
@require_admin
def template_get(key):
    s = svc()
    t = s.gov.get_template(key)
    if not t:
        return jsonify({'error': 'Unknown template'}), 404
    return jsonify({'template': t, 'history': s.gov.template_history(key), 'has_default': key in DEFAULT_TEMPLATES})


@bp.get('/admin/api/templates/<key>/version/<int:version>')
@require_admin
def template_version(key, version):
    t = svc().gov.get_template(key, version)
    return (jsonify({'template': t}) if t else (jsonify({'error': 'Unknown version'}), 404))


@bp.post('/admin/api/templates/<key>')
@require_admin
def template_save(key):
    s = svc()
    cur = s.gov.get_template(key)
    if not cur:
        return jsonify({'error': 'Unknown template'}), 404
    body = request.get_json(silent=True) or {}
    new_body, subject, text = body.get('body', cur['body']), body.get('subject', cur.get('subject')), body.get('text')
    v = _validate(s, key, cur['kind'], new_body, subject, text)
    if not v.get('ok'):
        return jsonify({'error': v.get('error'), 'line': v.get('line')}), 400
    meta = dict(cur.get('meta') or {})
    if text is not None:
        if text.strip():
            meta['text'] = text
        else:
            meta.pop('text', None)
    ver = s.gov.save_template(key, new_body, subject=subject, meta=meta, actor=_actor(), note=body.get('note') or '',
                              activate=body.get('activate', True))
    return jsonify({'ok': True, 'version': ver, 'undeclared': v.get('undeclared', [])})


@bp.post('/admin/api/templates/<key>/activate')
@require_admin
def template_activate(key):
    try:
        svc().gov.activate_template(key, int((request.get_json(silent=True) or {}).get('version')), _actor())
    except (TypeError, ValueError) as e:
        return jsonify({'error': str(e)}), 400
    return jsonify({'ok': True})


@bp.post('/admin/api/templates/<key>/reset')
@require_admin
def template_reset(key):
    d = DEFAULT_TEMPLATES.get(key)
    if not d:
        return jsonify({'error': 'No default for this template'}), 404
    ver = svc().gov.save_template(key, d['body'], subject=d.get('subject'), meta=d.get('meta') or {}, actor=_actor(),
                                  note='Reset to default')
    return jsonify({'ok': True, 'version': ver})


@bp.post('/admin/api/preview')
@require_admin
def preview():
    s, body = svc(), request.get_json(silent=True) or {}
    t = s.gov.get_template(body.get('key') or '')
    if not t:
        return jsonify({'error': 'Unknown template'}), 404
    try:
        return jsonify(_preview(s, t['key'], t['kind'], body.get('body', t['body']), body.get('subject', t.get('subject')), body.get('text')))
    except Exception as e:
        return jsonify({'error': f'{type(e).__name__}: {e}'}), 400


@bp.post('/admin/api/templates/<key>/test')
@require_admin
def template_test(key):
    s, body = svc(), request.get_json(silent=True) or {}
    to = (body.get('to') or '').strip()
    if '@' not in to:
        return jsonify({'error': 'Enter an email address.'}), 400
    msg = s.renderer.render_email(key, _sample(s, key))
    r = s.mailer.send(to=[to], subject='[TEST] ' + msg['subject'], html=msg['html'], text=msg['text'], actor=_actor(), category='template_test')
    return jsonify(r)


@bp.get('/admin/api/settings')
@require_admin
def settings_get():
    s = svc()
    return jsonify({'schema': schema_dicts(), 'values': s.gov.all_settings(), 'skills': s.registry.describe(s)})


@bp.post('/admin/api/settings')
@require_admin
def settings_save():
    s = svc()
    keys = {d['key'] for d in schema_dicts()}
    saved = []
    for k, v in ((request.get_json(silent=True) or {}).get('values') or {}).items():
        if k in keys or (k.startswith('skills.') and k.endswith('.enabled')):
            try:
                s.gov.set_setting(k, bool(v) if k.startswith('skills.') else v, _actor())
                saved.append(k)
            except (TypeError, ValueError) as e:
                return jsonify({'error': f'{k}: {e}'}), 400
    if getattr(s, 'writer', None):
        s.writer.reset_cache()                      # e.g. a module added to "Modules to add to the portal" applies at once
    return jsonify({'ok': True, 'saved': saved})


@bp.get('/admin/api/approvals')
@require_admin
def approvals():
    return jsonify({'approvals': svc().gov.list_approvals(request.args.get('status', 'pending'))})


@bp.post('/admin/api/approvals/<int:aid>')
@require_admin
def approval_decide(aid):
    s, body = svc(), request.get_json(silent=True) or {}
    a = s.gov.get_approval(aid)
    if not a:
        return jsonify({'error': 'Unknown approval'}), 404
    approve = body.get('decision') == 'approve'
    es = s.event_service
    if es and a['kind'] == 'artist' and str(a['ref_id']).isdigit():
        es.set_artist_status(int(a['ref_id']), 1 if approve else 0, added_by='AI' if approve else None)
    elif es and a['kind'] == 'institution' and str(a['ref_id']).isdigit() and not approve:
        es.db.execute_query('UPDATE institution_list SET status = 0 WHERE sid = %s', (int(a['ref_id']),), commit=True)
    s.gov.decide_approval(aid, 'approved' if approve else 'rejected', _actor(), body.get('note') or '')
    s.index.invalidate()
    return jsonify({'ok': True})


@bp.get('/admin/api/flags')
@require_admin
def flags():
    return jsonify({'flags': svc().gov.list_flags()})


@bp.post('/admin/api/flags')
@require_admin
def flag_add():
    s, b = svc(), request.get_json(silent=True) or {}
    if not (b.get('name') or b.get('ref_id')):
        return jsonify({'error': 'Give a name or a directory ID.'}), 400
    fid = s.gov.add_flag(b.get('entity') or 'artist', b.get('name'), b.get('flag') or 'deceased', ref_id=b.get('ref_id'),
                         art_form=b.get('art_form'), note=b.get('note') or '', actor=_actor())
    s.index.invalidate()
    return jsonify({'ok': True, 'id': fid})


@bp.delete('/admin/api/flags/<int:fid>')
@require_admin
def flag_delete(fid):
    s = svc()
    s.gov.remove_flag(fid, _actor())
    s.index.invalidate()
    return jsonify({'ok': True})


@bp.get('/admin/api/audit')
@require_admin
def audit():
    return jsonify({'audit': svc().gov.list_audit(int(request.args.get('limit', 200)), request.args.get('prefix') or None)})
