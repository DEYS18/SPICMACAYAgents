"""
Output skills. Each produces one optional deliverable and can be switched off on its own:
  apr               file the program and its APR (database, PDF, emails)
  documents         PDFs only (APR preview, Request for Payment) without filing or emailing
  payment_requests  Request for Payment emails with the invoice PDF, one per institution
  guidelines        pre-event SOP email for upcoming events
  posters           SPIC MACAY poster from the draft or an existing program
  bank              bank details, IFSC checks and cancelled-cheque reading (DC12, DC15)
  lookups           existing programs
Emails always go through a prepared preview (the outbox) and are sent only on confirmation.
"""
import base64
import json
import logging
import os
import re
import threading
import urllib.error
import urllib.request
from collections import OrderedDict
from datetime import date, datetime

from app.agents.draft import PROGRAM_TYPES, artists_text
from app.core import dates as dt
from app.core import text_utils as tu
from app.core.rendering import bank_context
from app.skills.base import Skill, email_context, notify, program_summary, tool
from app.skills.core_skills import add_events_impl, artist_chip

logger = logging.getLogger(__name__)
S, I, B = {'type': 'string'}, {'type': 'integer'}, {'type': 'boolean'}
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUIDELINES_PDF = os.path.join(APP_DIR, 'static', 'guidelines', 'event_institution_guidelines.pdf')
IFSC_RE = re.compile(r'[A-Z]{4}0[A-Z0-9]{6}')


def _stamp():
    return datetime.now().strftime('%Y%m%d-%H%M%S')


def _slug(text):
    return '-'.join(tu.normalize(text).split())[:40] or 'x'


# ── APR context (what the PDF and the confirmation email show) ───────────────
def _portal_module(ctx, name):
    w = getattr(ctx.s, 'writer', None)
    return ((w.module_lookup(name)[1] if w and name else None) or name)


def apr_context(ctx, apr, draft=None) -> dict:
    draft = draft or ctx.draft
    d = draft.d
    coords = [{'name': c.get('name') or '', 'chapter': c.get('chapter') or ('' if d.get('batch_ref') else d.get('chapter')) or '',
               'phone': c.get('phone') or '', 'email': c.get('email') or ''} for c in d['coordinators']]
    events, total = [], 0
    for i, e in enumerate(d['events'], 1):
        arts = draft.effective_artists(e)
        place = ', '.join(x for x in (e.get('institution_name'), e.get('city'), e.get('state')) if x)
        contact = ' - '.join(x for x in (e.get('contact_name'), e.get('contact_phone')) if x)
        c = e.get('contribution')
        if isinstance(c, (int, float)):
            total += c
        main = next((a for a in arts if a.get('role') == 'main'), {})
        span = f" to {dt.format_date(e['end_date'], '%d-%b-%Y')}" if e.get('end_date') and e.get('end_date') != e.get('date') else ''
        events.append({'sl': i, 'date': dt.format_date(e.get('date'), '%d-%b-%Y') + span,
                       'time': dt.time_range_display(e.get('start_time') or d.get('start_time'), e.get('end_time') or d.get('end_time')),
                       'module': _portal_module(ctx, e.get('module') or d.get('module') or ''), 'artists': artists_text(arts),
                       'institution': place + (f'\nContact Details: {contact}' if contact else ''),
                       'institution_line': ', '.join(x for x in (e.get('institution_name'), e.get('city')) if x),
                       'audience_students': str(e.get('audience_students') or d.get('audience_default') or ''),
                       'audience_other': str(e.get('audience_other') or ''),
                       'contribution': 'NIL' if c == 'NIL' else (tu.inr(c) if c else ''),
                       'artists_text': artists_text(arts), 'art_form': main.get('art_form') or '', 'city': e.get('city') or ''})
    artists = []

    def add(a, role, details=''):
        if not any(x['name'] == a.get('name') for x in artists):
            artists.append({'role': role, 'name': a.get('name') or '', 'art_form': a.get('art_form') or '',
                            'phone': a.get('phone') or '', 'details': details})
    if d['program_type'] == 'virasat':
        seen = OrderedDict()                            # one row per artist, listing every event they appear in
        for i, e in enumerate(d['events'], 1):
            for a in draft.effective_artists(e):
                row = seen.setdefault(a.get('name'), [a, 'Performer' if a['role'] == 'main' else 'Accompanying', []])
                row[2].append(str(i))
        for a, role, nums in seen.values():
            add(a, role, ('Event ' if len(nums) == 1 else 'Events ') + ', '.join(nums))
    else:
        for a in draft.program_artists():
            add(a, 'Main' if a['role'] == 'main' else 'Accompanying', 'Provisional' if a.get('provisional') else '')
        for i, e in enumerate(d['events'], 1):
            for a in e.get('artists') or []:
                add(a, 'Main' if a['role'] == 'main' else 'Accompanying', f'Event {i} only')
    now = datetime.now()
    return {'apr': apr, 'program': {'type': d['program_type'], 'type_label': PROGRAM_TYPES.get(d['program_type'], 'Program'),
                                    'title': d.get('title') or '', 'notes': d.get('notes') or '',
                                    'payment_required': bool(d.get('payment_required', True))},
            'coordinators': coords, 'artists': artists, 'events': events,
            'totals': {'events': len(events), 'contribution': total, 'contribution_inr': tu.inr(total) if total else ''},
            'org': ctx.s.org(), 'generated_at': now.strftime('%d-%b-%Y %I:%M') + now.strftime('%p').lower()}


def _program_media(ctx, first_event_id, files=None):
    """Poster and program photos: attached to the APR email and linked to the event the way the
    portal expects (event_list.image), so later reminders can re-attach the poster."""
    up = ctx.state.uploads or {}
    if files is None:
        files = ([('uploads', up.get('poster'), 'poster')] if up.get('poster') else []) + \
                [('uploads', f, 'photo') for f in (up.get('program_photos') or [])[:6]]
    atts, legacy = [], []
    for kind, fname, label in files:
        try:
            data = ctx.s.files.read(kind, fname)
        except (OSError, ValueError, TypeError):
            continue
        name = ('event_poster.jpg' if not any(a[0] == 'event_poster.jpg' for a in atts) else f'event_poster_{len(atts) + 1}.jpg') \
            if label == 'poster' else f'program_photo_{len(atts) + 1}.jpg'
        atts.append((name, data, 'image/jpeg'))
        legacy.append({'bytes': data, 'filename': name, 'mime_type': 'image/jpeg'})
    if legacy and ctx.s.event_service and first_event_id:
        try:
            from app.services.pdf_service import save_event_photos
            paths = save_event_photos(legacy, first_event_id)
            if paths:
                ctx.s.event_service.update_event_photos(first_event_id, paths)
        except Exception as e:
            logger.warning('Could not link program photos to event %s: %s', first_event_id, e)
    return atts


def next_steps(ctx):
    d, reg, steps = ctx.draft.d, ctx.s.registry, []
    future = any((dt._as_date(e.get('date')) or date.min) > date.today() for e in d['events'])
    if reg.enabled('posters', ctx.s) and not d['outputs'].get('posters'):
        steps.append('poster')
    if reg.enabled('payment_requests', ctx.s) and any(isinstance(e.get('contribution'), (int, float)) for e in d['events']):
        steps.append('payment_request')
    if future and reg.enabled('guidelines', ctx.s):
        steps.append('guidelines')
    return steps


def file_draft(ctx, draft, media_files=None, send_email=True):
    """File one program: portal rows (one transaction), the APR PDF, coordinators, the APR email
    and the artist's thank-you. Shared by create_apr and batch filing."""
    filer = draft.filer() or {}
    uid = filer.get('uid')
    if not uid and ctx.s.db_validator:
        try:
            uid = ctx.s.db_validator.resolve_user_uid(email=filer.get('email') or '', name=filer.get('name') or '')
        except Exception:
            uid = None
    from app.agents.draft import expand_days
    filing, day_map = expand_days(draft)            # one portal row and one APR line per day
    result = ctx.s.writer.create(filing.to_dict(), uid=uid, settings=ctx.setting)
    apr = {'number': result['apr_number'], 'request_id': result['request_id'], 'custom_apr': result['custom_apr']}
    event_map = {i: [result['event_ids'][j] for j in js] for i, js in day_map.items()}
    pctx = apr_context(ctx, apr, filing)
    pdf = ctx.s.pdf.render_apr(ctx.s.renderer.layout(f"layout.apr.{draft.d['program_type'] or 'single'}"), pctx)
    fname = ctx.s.files.save('apr', f"APR_{_slug(apr['number'])}.pdf", pdf)
    url = ctx.s.file_url('apr', fname)
    ctx.s.gov.add_program_coordinators(apr['request_id'], result['event_ids'], draft.d['coordinators'], ctx.actor_label)
    media = _program_media(ctx, result['event_ids'][0], media_files)
    to = [c['email'] for c in draft.d['coordinators'] if c.get('email')]
    sent = {'ok': False, 'skipped': True}
    if send_email:
        msg = ctx.s.renderer.render_email('email.apr_confirmation', email_context(ctx, dict(pctx, has_poster=bool(media), coordinator=filer)))
        sent = ctx.s.mailer.send(to=to, cc=ctx.setting('apr.finance_cc', []), subject=msg['subject'], html=msg['html'], text=msg['text'],
                                 attachments=[(f"APR_{apr['number']}.pdf", pdf, 'application/pdf')] + media,
                                 actor=ctx.actor_label, category='apr_confirmation')
    acks = []
    if ctx.setting('apr.send_artist_acknowledgement', True) and draft.d['events']:
        first = draft.d['events'][0]
        for a in draft.all_artists():
            if a.get('role') != 'main' or not a.get('artist_id'):
                continue
            rec = ctx.s.index.get_artist(a['artist_id']) or {}
            if rec.get('email') and notify(ctx, 'email.artist_acknowledgement', [rec['email']], {
                    'artist': {'name': a['name']}, 'reference': f"APR {apr['number']}", 'coordinator': filer,
                    'feedback_url': ctx.setting('rfp.feedback_form_url', ''),
                    'event': {'module': first.get('module') or draft.d.get('module') or 'Programme',
                              'institution': first.get('institution_name'), 'date': first.get('date_display')}}):
                acks.append(a['name'])
    ctx.s.gov.audit(ctx.actor_label, 'apr.created', apr['request_id'],
                    {'apr_number': apr['number'], 'event_ids': result['event_ids'], 'program': program_summary(draft)})
    for hook in (ctx.s.hooks or {}).get('apr_created', []):
        try:
            hook(result)
        except Exception as e:
            logger.warning('apr_created hook failed: %s', e)
    return {'apr': apr, 'event_ids': result['event_ids'], 'event_map': event_map, 'series_id': result.get('series_id'), 'pdf': pdf, 'pdf_file': fname,
            'pdf_url': url, 'to': to, 'sent': sent, 'acks': acks}


def _email_status(sent):
    if sent.get('skipped'):
        return 'not emailed separately'
    return 'saved as a dry run (not sent)' if sent.get('dry_run') else ('sent' if sent.get('ok') else f"failed: {sent.get('error')}")


class AprSkill(Skill):
    key, title = 'apr', 'Artist Payment Request (APR)'
    description = 'Files the program in the portal database, generates the APR PDF and emails it.'

    @tool('create_apr', 'File the program and its APR. Needs the confirmation_id from review_program and a clear '
          'yes from the coordinator.', {'confirmation_id': S}, required=('confirmation_id',))
    def create_apr(self, ctx, confirmation_id):
        draft = ctx.draft
        pend = ctx.state.get_confirmation(confirmation_id, 'create_apr')
        if not pend:
            return {'ok': False, 'error': 'This confirmation has expired or was already used. Call review_program again.'}
        if pend.get('rev') != draft.d['rev']:
            return {'ok': False, 'error': 'The draft changed after the review. Call review_program again and get a fresh yes.'}
        if draft.d['outputs'].get('apr'):
            return {'ok': False, 'error': 'An APR has already been filed from this draft.', 'apr': draft.d['outputs']['apr']}
        from app.skills.base import portal_issues
        missing = [i['message'] for i in draft.issues() if i['severity'] == 'required'] + portal_issues(ctx.s, draft)
        if missing:
            return {'ok': False, 'missing': missing}
        if not ctx.s.writer:
            return {'ok': False, 'error': 'Filing is unavailable on this server (no database connection).'}
        ctx.state.take_confirmation(confirmation_id, 'create_apr')
        out = file_draft(ctx, draft)
        apr = out['apr']
        draft.d['outputs']['apr'] = {'number': apr['number'], 'request_id': apr['request_id'], 'event_ids': out['event_ids'],
                                     'series_id': out['series_id'], 'pdf_file': out['pdf_file'], 'pdf_url': out['pdf_url'],
                                     'emailed_to': out['to'], 'email_ok': bool(out['sent'].get('ok')), 'dry_run': bool(out['sent'].get('dry_run'))}
        draft.bump()
        ctx.ui.artifacts.append({'type': 'pdf', 'label': f"APR {apr['number']}", 'url': out['pdf_url'], 'filename': out['pdf_file']})
        if draft.d.get('batch_ref') and getattr(ctx.state, 'batch', None):
            from app.skills.batch import mark_filed
            mark_filed(ctx.state.batch, draft.d['batch_ref'], out)
        return {'ok': True, 'apr_number': apr['number'], 'event_ids': out['event_ids'], 'pdf_url': out['pdf_url'],
                'email': _email_status(out['sent']), 'emailed_to': out['to'], 'artist_thanked': out['acks'],
                'next_steps': next_steps(ctx),
                'advice': 'Tell the coordinator the APR number, that the PDF is below, and offer the next steps once.'}


class DocumentsSkill(Skill):
    key, title = 'documents', 'Documents only'
    description = 'Makes PDFs (APR preview, Request for Payment) without filing or emailing anything.'

    @tool('preview_apr_pdf', 'Make a DRAFT APR PDF from the current draft without filing it.')
    def preview_apr_pdf(self, ctx):
        layout = ctx.s.renderer.layout(f"layout.apr.{ctx.draft.d['program_type'] or 'single'}")
        pdf = ctx.s.pdf.render_apr(layout, apr_context(ctx, {'number': 'DRAFT', 'request_id': ''}))
        fname = ctx.s.files.save('preview', f'APR_draft_{_stamp()}.pdf', pdf)
        url = ctx.s.file_url('preview', fname)
        ctx.ui.artifacts.append({'type': 'pdf', 'label': 'APR preview (draft)', 'url': url, 'filename': fname})
        return {'ok': True, 'pdf_url': url}

    @tool('payment_request_pdf', 'Make Request for Payment PDFs only (no email), from the draft or for existing '
          'programs by event_ids.', {'event_ids': {'type': 'array', 'items': I},
                                     'amounts': {'type': 'array', 'items': {'type': 'object', 'properties': {'event': I, 'event_id': I, 'amount': {'type': 'number'}}}}})
    def payment_request_pdf(self, ctx, event_ids=None, amounts=None):
        items, problems = _rfp_items(ctx, event_ids, amounts, None)
        made = []
        for it in items:
            if it['status'] in ('skipped',):
                continue
            fname = _render_rfp(ctx, it)
            url = ctx.s.file_url('rfp', fname)
            ctx.ui.artifacts.append({'type': 'pdf', 'label': f"Request for Payment: {it['institution']['name']}", 'url': url, 'filename': fname})
            made.append({'institution': it['institution']['name'], 'amount_inr': it['amount_inr'], 'pdf_url': url, 'problem': it['problem']})
        return {'ok': bool(made), 'documents': made, 'problems': problems}


# ── Request for Payment ─────────────────────────────────────────────────────
def _groups_from_db(ctx, event_ids, amounts, guidelines=False):
    groups, problems = OrderedDict(), []
    es = ctx.s.event_service
    for eid in event_ids:
        ev = (es.get_event_for_guidelines(eid) if guidelines else es.get_event_for_payment(eid)) if es else None
        if not ev:
            problems.append(f'No program with ID {eid}')
            continue
        if guidelines and (dt._as_date(ev.get('start_date')) or date.min) <= date.today():
            problems.append(f'Program {eid} is not in the future; guidelines are only for upcoming programs')
            continue
        key = str(ev.get('institution_id') or ev.get('institution_name'))
        g = groups.setdefault(key, {'institution': {'name': ev.get('institution_name') or '', 'email': ev.get('institution_email') or '',
                                                    'contact_name': ev.get('institution_coordinator') or '',
                                                    'city': ev.get('institution_city') or ev.get('city') or ''},
                                    'events': [], 'event_ids': [], 'reference': ev.get('custom_apr') or ev.get('request_id') or '',
                                    'poster_image': ev.get('image'), 'amount_missing': False, 'nil': 0})
        acc = es.get_accompanying_artists(ev.get('accompanying_artist'))
        arts = ([{'name': ev.get('artist_name'), 'role': 'main'}] if ev.get('artist_name') else []) + \
               [{'name': a['name'], 'role': 'accompanying'} for a in acc]
        n = tu.to_number(amounts.get(str(eid), ev.get('budget')))
        if n is None:
            g['amount_missing'] = True                # an explicit 0 is fine; the group total is checked later
        g['events'].append({'date': dt.format_date(ev.get('start_date'), '%d %b %Y'), 'time': ev.get('event_time') or '',
                            'module': ev.get('module_name') or 'Programme', 'artists_text': artists_text(arts),
                            'art_form': ev.get('art_form') or '', 'title': ev.get('title') or '', 'amount': n or 0})
        g['event_ids'].append(eid)
    return groups, problems


def _groups_from_draft(ctx, amounts, guidelines=False):
    d, groups, problems = ctx.draft.d, OrderedDict(), []
    apr = d['outputs'].get('apr') or {}
    ids = apr.get('event_ids') or []
    for i, e in enumerate(d['events']):
        if not e.get('institution_name'):
            problems.append(f'Event {i + 1} has no institution yet')
            continue
        if guidelines and (dt._as_date(e.get('date')) or date.min) <= date.today():
            continue
        key = str(e.get('institution_id') or e.get('institution_name'))
        g = groups.setdefault(key, {'institution': {'name': e['institution_name'], 'email': e.get('institution_email') or '',
                                                    'contact_name': e.get('contact_name') or '', 'city': e.get('city') or ''},
                                    'events': [], 'event_ids': [], 'reference': f"APR {apr['number']}" if apr.get('number') else '',
                                    'poster_image': None, 'amount_missing': False, 'nil': 0})
        arts = ctx.draft.effective_artists(e)
        main = next((a for a in arts if a.get('role') == 'main'), {})
        raw = amounts.get(str(i + 1), e.get('contribution'))
        n = 0 if raw == 'NIL' else (tu.to_number(raw) or 0)
        if raw == 'NIL':
            g['nil'] += 1
        elif not n:
            g['amount_missing'] = True
        g['events'].append({'date': dt.format_date(e.get('date'), '%d %b %Y'),
                            'time': dt.time_range_display(e.get('start_time') or d.get('start_time'), e.get('end_time') or d.get('end_time')),
                            'module': e.get('module') or d.get('module') or 'Programme', 'artists_text': artists_text(arts),
                            'art_form': main.get('art_form') or '', 'title': d.get('title') or '', 'amount': n})
        if i < len(ids):
            g['event_ids'].append(ids[i])
    return groups, problems


def _override_email(g, emails):
    for x in emails or []:
        if not x.get('email'):
            continue
        if x.get('institution') and tu.normalize(x['institution']) in tu.normalize(g['institution']['name']):
            return x['email']
        if x.get('event_id') and x['event_id'] in g['event_ids']:
            return x['email']
    return None


def _items(ctx, groups, emails, category):
    cc = [c['email'] for c in ctx.draft.d['coordinators'] if c.get('email')]
    items = []
    for n, g in enumerate(groups.values(), 1):
        email = _override_email(g, emails) or g['institution']['email']
        total = sum(e['amount'] for e in g['events'])
        status, problem = 'ready', ''
        if category == 'payment_request':
            if g['nil'] and not total:
                status, problem = 'skipped', 'Contribution is NIL'
            elif g['amount_missing'] or not total:
                status, problem = 'needs_amount', 'Contribution amount missing'
        if status == 'ready' and not email:
            status, problem = 'needs_email', 'No email on file for this institution'
        items.append({'item_id': f'i{n}', 'institution': g['institution'], 'to': email or '', 'cc': cc, 'events': g['events'],
                      'event_ids': g['event_ids'], 'amount': total, 'amount_inr': tu.inr(total) if total else '',
                      'reference': g['reference'], 'poster_image': g.get('poster_image'), 'status': status, 'problem': problem})
    return items


def _rfp_items(ctx, event_ids, amounts, emails):
    amap = {str(a.get('event_id') or a.get('event')): a.get('amount') for a in (amounts or []) if a.get('amount') is not None}
    groups, problems = _groups_from_db(ctx, event_ids, amap) if event_ids else _groups_from_draft(ctx, amap)
    return _items(ctx, groups, emails, 'payment_request'), problems


def _render_rfp(ctx, item):
    layout = ctx.s.renderer.layout('layout.rfp')
    program = {'title': ctx.draft.d.get('title') or ''}
    lines = []
    for i, e in enumerate(item['events'], 1):
        desc = ctx.s.renderer.text(layout.get('description', ''), {'program': program, 'e': e}).strip()
        lines.append({'sl': i, 'description': re.sub(r'\s+', ' ', desc or f"{e['module']} by {e['artists_text']}"),
                      'date': e['date'], 'amount': f"Rs {tu.inr(e['amount'])}" if e['amount'] else '-'})
    rctx = {'org': ctx.s.org(), 'bank': bank_context(ctx.setting), 'institution': item['institution'], 'program': program,
            'signatory': {'name': ctx.setting('rfp.signatory_name', ''), 'title': ctx.setting('rfp.signatory_title', '')},
            'invoice_date': date.today().strftime('%d %b %Y'), 'line_items': lines, 'amount_inr': item['amount_inr'] or '0',
            'amount_words': tu.amount_in_words(item['amount']) if item['amount'] else ''}
    return ctx.s.files.save('rfp', f"RFP_{_slug(item['institution']['name'])}_{_stamp()}.pdf", ctx.s.pdf.render_rfp(layout, rctx))


def _poster_attachment(ctx, item):
    if item.get('poster_image'):
        return [{'legacy_image': item['poster_image'], 'name': 'program_poster.jpg'}]
    up = (ctx.state.uploads or {}).get('poster')
    return [{'kind': 'uploads', 'file': up, 'name': 'program_poster.jpg'}] if up else []


def _outbox(ctx, category, title, items, problems):
    cid = ctx.state.new_confirmation('send_emails', category=category, items=items)
    ready = [i for i in items if i['status'] == 'ready']
    ctx.ui.cards.append({'type': 'outbox', 'category': category, 'title': title, 'confirmation_id': cid,
                         'button': f"Send {len(ready)} email{'s' if len(ready) != 1 else ''}",
                         'items': [{'item_id': i['item_id'], 'institution': i['institution']['name'], 'to': i['to'], 'cc': i['cc'],
                                    'subject': i.get('subject'), 'amount_inr': i['amount_inr'], 'status': i['status'],
                                    'problem': i['problem'], 'pdf_url': i.get('pdf_url')} for i in items]})
    return {'ok': True, 'confirmation_id': cid, 'ready': len(ready), 'problems': problems,
            'items': [{'item_id': i['item_id'], 'institution': i['institution']['name'], 'to': i['to'],
                       'amount_inr': i['amount_inr'], 'status': i['status'], 'problem': i['problem']} for i in items],
            'advice': 'Show each recipient (and amount). For missing emails or amounts call prepare again with emails/amounts. '
                      'Send only after a clear yes, with send_prepared_emails.'}


class PaymentsSkill(Skill):
    key, title = 'payment_requests', 'Request for Payment'
    description = 'Invoice emails to host institutions, one per institution, with the Request for Payment PDF.'

    @tool('list_pending_payments', 'List programs in the database with no contribution receipt yet.',
          {'search': S, 'city': S, 'date_from': S, 'date_to': S})
    def list_pending_payments(self, ctx, **filters):
        if not ctx.s.event_service:
            return {'ok': False, 'error': 'No database connection.'}
        rows = ctx.s.event_service.get_pending_payment_events({k: v for k, v in filters.items() if v}) or []
        return {'ok': True, 'count': len(rows), 'programs': [
            {'event_id': r.get('id'), 'date': str(r.get('start_date') or ''), 'artist': r.get('artist_name'),
             'institution': r.get('institution_name'), 'institution_email': r.get('institution_email'),
             'budget': r.get('budget'), 'apr': r.get('custom_apr') or r.get('request_id')} for r in rows[:20]]}

    @tool('prepare_payment_requests', 'Prepare Request for Payment emails (one per institution, invoice PDF attached) '
          'for the draft, or for existing programs by event_ids. Returns a preview and a confirmation_id; nothing is sent.',
          {'event_ids': {'type': 'array', 'items': I},
           'amounts': {'type': 'array', 'items': {'type': 'object', 'properties': {
               'event': {'type': 'integer', 'description': '1-based event number in the draft'}, 'event_id': I, 'amount': {'type': 'number'}}}},
           'emails': {'type': 'array', 'items': {'type': 'object', 'properties': {'institution': S, 'event_id': I, 'email': S}}}})
    def prepare_payment_requests(self, ctx, event_ids=None, amounts=None, emails=None):
        items, problems = _rfp_items(ctx, event_ids, amounts, emails)
        if not items:
            return {'ok': False, 'error': '; '.join(problems) or 'Nothing to invoice yet: add events with institutions first.'}
        for it in items:
            if it['status'] == 'skipped':
                continue
            fname = _render_rfp(ctx, it)
            it.update(pdf_file=fname, pdf_url=ctx.s.file_url('rfp', fname),
                      attachments=[{'kind': 'rfp', 'file': fname, 'name': 'Request_for_Payment.pdf'}] + _poster_attachment(ctx, it))
            msg = ctx.s.renderer.render_email('email.payment_request', email_context(ctx, {
                'institution': it['institution'], 'events': it['events'], 'amount_inr': it['amount_inr'] or '0',
                'amount_words': tu.amount_in_words(it['amount']) if it['amount'] else '', 'reference': it['reference'],
                'feedback_url': ctx.setting('rfp.feedback_form_url', '')}))
            it.update(subject=msg['subject'], html=msg['html'], text=msg['text'])
        return _outbox(ctx, 'payment_request', 'Request for Payment', items, problems)


class GuidelinesSkill(Skill):
    key, title = 'guidelines', 'Pre-event guidelines'
    description = 'Sends host institutions the SOP and pre-programme checklist, for upcoming events only.'

    @tool('prepare_guidelines', 'Prepare the pre-event guidelines email for upcoming events (from the draft, or existing '
          'programs by event_ids). Returns a preview and a confirmation_id; nothing is sent.',
          {'event_ids': {'type': 'array', 'items': I},
           'emails': {'type': 'array', 'items': {'type': 'object', 'properties': {'institution': S, 'event_id': I, 'email': S}}}})
    def prepare_guidelines(self, ctx, event_ids=None, emails=None):
        groups, problems = _groups_from_db(ctx, event_ids, {}, guidelines=True) if event_ids else _groups_from_draft(ctx, {}, guidelines=True)
        items = _items(ctx, groups, emails, 'guidelines')
        if not items:
            return {'ok': False, 'error': '; '.join(problems) or 'There are no upcoming events to send guidelines for.'}
        has_pdf = os.path.exists(GUIDELINES_PDF)
        for it in items:
            msg = ctx.s.renderer.render_email('email.pre_event_guidelines', email_context(ctx, {
                'institution': it['institution'], 'events': it['events'], 'has_attachment': has_pdf}))
            it.update(subject=msg['subject'], html=msg['html'], text=msg['text'],
                      attachments=[{'path': GUIDELINES_PDF, 'name': 'SPIC_MACAY_Event_Guidelines.pdf'}] if has_pdf else [])
        return _outbox(ctx, 'guidelines', 'Pre-event guidelines', items, problems)


class OutboxSkill(Skill):
    key, title, core = 'outbox', 'Sending prepared emails', True
    description = 'Sends emails that were prepared and previewed.'

    @tool('send_prepared_emails', 'Send emails prepared by prepare_payment_requests or prepare_guidelines, after the '
          'coordinator clearly confirmed.', {'confirmation_id': S, 'item_ids': {'type': 'array', 'items': S}},
          required=('confirmation_id',))
    def send_prepared_emails(self, ctx, confirmation_id, item_ids=None):
        if ctx.via == 'llm' and ctx.setting('email.require_button_confirmation', False):
            return {'ok': False, 'needs_button': True,
                    'advice': 'An administrator requires the Send button: ask the coordinator to tap Send on the preview.'}
        pend = ctx.state.get_confirmation(confirmation_id, 'send_emails')
        if not pend:
            return {'ok': False, 'error': 'This preview has expired or was already sent. Prepare it again.'}
        results = []
        for it in pend['items']:
            if (item_ids and it['item_id'] not in item_ids) or it.get('sent') or it['status'] != 'ready':
                continue
            atts = []
            for a in it.get('attachments') or []:
                try:
                    if a.get('kind'):
                        atts.append((a['name'], ctx.s.files.read(a['kind'], a['file']), 'application/pdf' if a['name'].endswith('.pdf') else 'image/jpeg'))
                    elif a.get('path'):
                        with open(a['path'], 'rb') as fh:
                            atts.append((a['name'], fh.read(), 'application/pdf'))
                    elif a.get('legacy_image'):
                        from app.services.pdf_service import load_poster_bytes
                        data = load_poster_bytes(a['legacy_image'])
                        if data:
                            atts.append((a['name'], data, 'image/jpeg'))
                except (OSError, ValueError) as e:
                    logger.warning('Attachment %s unavailable: %s', a.get('name'), e)
            r = ctx.s.mailer.send(to=[it['to']], cc=it['cc'], subject=it['subject'], html=it['html'], text=it['text'],
                                  attachments=atts, actor=ctx.actor_label, category=pend['category'])
            it['sent'] = bool(r.get('ok'))
            results.append({'institution': it['institution']['name'], 'to': it['to'], 'ok': bool(r.get('ok')),
                            'dry_run': bool(r.get('dry_run')), 'error': r.get('error')})
        if all(i.get('sent') or i['status'] != 'ready' for i in pend['items']):
            ctx.state.take_confirmation(confirmation_id, 'send_emails')
        ctx.draft.d['outputs'].setdefault('emails', []).extend(
            {'category': pend['category'], 'to': r['to'], 'ok': r['ok'], 'dry_run': r['dry_run']} for r in results)
        ctx.draft.bump()
        ok = sum(1 for r in results if r['ok'])
        return {'ok': ok > 0 or not results, 'sent': ok, 'failed': len(results) - ok,
                'dry_run': any(r['dry_run'] for r in results), 'results': results}


# ── Posters ─────────────────────────────────────────────────────────────────
_POSTER_LOCK = threading.Lock()


class PostersSkill(Skill):
    key, title = 'posters', 'Posters'
    description = "SPIC MACAY poster from the draft or an existing program, using the main artist's photo."

    @tool('generate_poster', "Make a poster for one event of the draft (event_index) or an existing program (event_id). "
          "Needs the MAIN artist's photo on file (request_artist_photo).",
          {'event_index': I, 'event_id': I, 'proceed_without_photo': {'type': 'boolean', 'description': 'Only if the user has no photo and the admin allows it'}})
    def generate_poster(self, ctx, event_index=0, event_id=None, proceed_without_photo=False):
        poster = ctx.s.poster
        if not poster:
            return {'ok': False, 'error': 'Poster generation is unavailable on this server.'}
        style = ctx.s.renderer.layout('layout.poster')
        tfmt = ctx.setting('poster.time_format', '12h')
        if event_id:
            ev = ctx.s.event_service.get_event_for_resend(event_id) if ctx.s.event_service else None
            if not ev:
                return {'ok': False, 'error': f'No program with ID {event_id}.'}
            best = ctx.s.index.search_artists(ev.get('artist_name') or '')['best'] or {}
            main = {'name': ev.get('artist_name'), 'art_form': ev.get('art_form'), 'artist_id': best.get('tid')}
            data = {'institution_name': ev.get('institution_name'), 'module_name': ev.get('module_name'), 'start_date': str(ev.get('start_date') or ''),
                    'event_time': ev.get('event_time') or '', 'venue': ev.get('venue'), 'city': ev.get('city'), 'state': ev.get('state'),
                    'chapter': ev.get('chapter') or ''}
            acc = [a['name'] for a in ctx.s.event_service.get_accompanying_artists(ev.get('accompanying_artist'))]
        else:
            if not ctx.draft.d['events']:
                return {'ok': False, 'error': 'Add the date and institution first.'}
            e = ctx.draft.event(event_index or 0)
            arts = ctx.draft.effective_artists(e)
            main = next((a for a in arts if a.get('role') == 'main'), None)
            if not main:
                return {'ok': False, 'error': 'Choose the main artist first.'}
            d = ctx.draft.d
            data = {'institution_name': e.get('institution_name'), 'module_name': e.get('module') or d.get('module'),
                    'start_date': e.get('date') or '', 'event_time': dt.format_time(e.get('start_time') or d.get('start_time'), tfmt).upper(),
                    'venue': e.get('venue') or e.get('institution_name'), 'city': e.get('city'), 'state': e.get('state'),
                    'chapter': d.get('chapter') or ''}
            acc = [a['name'] for a in arts if a.get('role') != 'main']
        key = main.get('artist_id') or 'n-' + _slug(main.get('name') or '')
        has_photo = bool(poster.stored_artist_photo_path(key))
        require = ctx.setting('poster.require_main_artist_photo', True)
        if not has_photo and (require or not proceed_without_photo):
            ctx.state.awaiting = {'kind': 'artist_photo', 'artist_id': key, 'name': main.get('name'), 'role': 'main'}
            ctx.ui.cards.append({'type': 'upload', 'kind': 'artist_photo', 'title': f"Photo of {main.get('name')}",
                                 'subtitle': 'Main artist. Needed for the poster and kept for future posters.',
                                 'target': {'artist_id': key, 'role': 'main', 'name': main.get('name')}})
            return {'ok': False, 'needs_artist_photo': True, 'artist': main.get('name'), 'required_by_policy': require,
                    'advice': "Ask for a photo of the MAIN artist (kept for future posters)." +
                              ('' if require else ' If they have none, call generate_poster with proceed_without_photo=true.')}
        filer = ctx.draft.filer() or {}
        data.update({'artist_name': main.get('name'), 'art_form': main.get('art_form'), 'artist_id': key,
                     'coordinator_name': filer.get('name') if style.get('show_coordinator', True) else '',
                     'accompanying_artists': acc if style.get('show_accompanying', True) else []})
        with _POSTER_LOCK:
            jpg = poster.generate_with_style(data, style)
        if not jpg:
            return {'ok': False, 'error': 'The poster could not be drawn (image library unavailable).'}
        fname = ctx.s.files.save('poster', f"poster_{_slug(main.get('name') or 'artist')}_{_stamp()}.jpg", jpg)
        url = ctx.s.file_url('poster', fname)
        ctx.draft.d['outputs'].setdefault('posters', []).append({'file': fname, 'url': url})
        ctx.draft.bump()
        ctx.ui.artifacts.append({'type': 'image', 'label': f"Poster: {main.get('name')}", 'url': url, 'filename': fname})
        ctx.s.gov.audit(ctx.actor_label, 'poster.created', fname, {'artist': main.get('name')})
        return {'ok': True, 'poster_url': url, 'artist_photo_used': has_photo}


POSTER_PROMPT = """You are reading a SPIC MACAY program poster to pre-fill program records. Return ONLY a JSON object:
{"program_type": "single" (one artist, one venue, one date) | "circuit" (one artist, several institutions or dates) | "virasat" (one institution, several sessions or artists; also when the poster says Virasat or Mini Virasat),
 "title": "series or festival name as printed, e.g. Virasat 2026", "module": "the main programme type as printed",
 "chapter": "the SPIC MACAY chapter or heritage club that hosts it",
 "host_institution": {"name": "...", "city": "...", "state": "..."},
 "main_artist": {"name": "full name with honorific as printed", "art_form": "..."},
 "accompanying": [{"name": "...", "art_form": "Tabla, Harmonium, ..."}],
 "events": [{"date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD only for a workshop or intensive running on consecutive days",
             "start_time": "HH:MM", "end_time": "HH:MM", "institution": "...", "city": "...", "state": "...", "venue": "hall or room",
             "module": "Concert | Lecture Demonstration | Workshop | Baithak | Yoga | Cinema Classic | ...",
             "artist": "who performs or teaches in this session (needed when sessions have different artists)", "art_form": "...",
             "accompanying": [{"name": "...", "art_form": "..."}]}],
 "contacts": [{"name": "...", "phone": "..."}], "notes": "anything else useful"}
Rules: one event per concert or session; a workshop running on several consecutive days is ONE event with date and end_date.
A screening or talk without a performing artist has "artist": null. Never invent entries; use empty lists when the poster names none.
Do not list the main artist among the accompanying artists. Dates on the poster are in 2026 unless printed otherwise."""

CHEQUE_PROMPT = """Read this Indian cancelled cheque (or passbook front page). Return ONLY JSON:
{"account_holder": "...", "bank_name": "...", "branch": "...", "account_number": "digits only", "ifsc": "11 characters", "micr": "9 digits"}
Use null for anything not clearly readable. Never guess digits."""


def vision_json(ctx, image_b64, mime, prompt):
    client = ctx.s.llm()
    if not client:
        return None, 'The AI service is not configured (OPENAI_API_KEY), so images cannot be read.'
    from app.agents import llm
    model = ctx.setting('assistant.vision_model', 'gpt-4o')
    try:
        res = llm.complete(client, model=model, temperature=0, json_mode=True, api=ctx.setting('assistant.api', 'auto'),
                           effort=ctx.setting('assistant.vision_reasoning_effort', 'medium'),
                           messages=[{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': f'data:{mime};base64,{image_b64}', 'detail': 'high'}},
                                                                  {'type': 'text', 'text': prompt}]}])
        try:
            ctx.s.gov.add_usage(model, *llm.usage_numbers(res.usage))
        except Exception:
            pass
        text = (res.content or '{}').strip()
        if text.startswith('```'):
            text = text.strip('`').split('\n', 1)[-1].rsplit('```', 1)[0]
        return json.loads(text or '{}'), None
    except Exception as e:
        logger.exception('Vision read failed')
        return None, f'Could not read the image: {e}'


def _resolve_artist(ctx, name, art_form, role, event_index=None):
    r = ctx.s.index.search_artists(name, art_form)
    best = r['best']
    if best and not best['flags']:
        ctx.draft.set_artist(dict(best, artist_id=best['tid'], art_form=art_form or best['art_form'],
                                  has_photo=bool(ctx.s.poster and ctx.s.poster.stored_artist_photo_path(best['tid']))), role, event_index)
        return {'name': best['name'], 'role': role, 'status': 'matched'}
    ctx.draft.set_artist({'name': name, 'art_form': art_form}, role, event_index)
    if r['matches']:
        ctx.ui.candidates.append({'kind': 'artist', 'title': f'Poster says "{name}": which artist?', 'role': role,
                                  'event_index': event_index, 'query': name, 'allow_add': True,
                                  'items': [artist_chip(m, role, event_index) for m in r['matches'][:4]]})
    return {'name': name, 'role': role, 'status': 'choose' if r['matches'] else 'not_found'}


def apply_poster_extraction(ctx, data):
    d = ctx.draft
    ptype = (data.get('program_type') or '').lower()
    d.set_program({k: v for k, v in {'program_type': ptype if ptype in PROGRAM_TYPES else None, 'title': data.get('title'),
                                      'module': data.get('module'), 'chapter': data.get('chapter')}.items() if v})
    summary = {'program_type': d.d['program_type'], 'artists': [], 'events': []}
    main = data.get('main_artist') or {}
    if main.get('name') and ptype != 'virasat':
        summary['artists'].append(_resolve_artist(ctx, main['name'], main.get('art_form'), 'main'))
    for acc in (data.get('accompanying') or [])[:6]:
        if acc.get('name'):
            summary['artists'].append(_resolve_artist(ctx, acc['name'], acc.get('art_form'), 'accompanying'))
    events = data.get('events') or []
    rows = add_events_impl(ctx, [{k: e.get(k) for k in ('date', 'institution', 'city', 'state', 'start_time', 'end_time', 'module') if e.get(k)}
                                 for e in events], replace_existing=bool(events))
    if ptype == 'virasat':
        for row, e in zip(rows, events):
            if e.get('artist'):
                summary['artists'].append(_resolve_artist(ctx, e['artist'], e.get('art_form'), 'main', row['event_index']))
    summary['events'] = rows
    return {'ok': True, 'summary': summary, 'notes': data.get('notes')}


def extract_poster(ctx, image_b64, mime):
    data, err = vision_json(ctx, image_b64, mime, POSTER_PROMPT)
    return {'ok': False, 'error': err} if err else apply_poster_extraction(ctx, data or {})


# ── Bank details (DC12, DC15) ────────────────────────────────────────────────
def lookup_ifsc(ctx, code):
    if not ctx.setting('bank.ifsc_lookup', True):
        return None
    hit = ctx.s.gov.cache_get('ifsc:' + code, max_age_days=180)
    if hit is not None:
        return hit
    try:
        req = urllib.request.Request(f'https://ifsc.razorpay.com/{code}', headers={'User-Agent': 'SPICMACAY-APR-Assistant'})
        with urllib.request.urlopen(req, timeout=4) as r:
            info = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        info = {'valid': False} if e.code == 404 else None
    except Exception:
        info = None
    if info is not None:
        ctx.s.gov.cache_set('ifsc:' + code, info)
    return info


def _save_bank(ctx, entity, entity_id, bank_name, account_number, ifsc_code, cheque_file=None):
    acc = re.sub(r'\s', '', str(account_number or ''))
    code = re.sub(r'\s', '', str(ifsc_code or '')).upper()
    if not re.fullmatch(r'\d{9,18}', acc):
        return {'ok': False, 'error': 'Account numbers have 9 to 18 digits.'}
    if not IFSC_RE.fullmatch(code):
        return {'ok': False, 'error': 'An IFSC has 11 characters: 4 letters, a zero, then 6 letters or digits.'}
    es = ctx.s.event_service
    if not es:
        return {'ok': False, 'error': 'No database connection.'}
    data = {'bank_name': bank_name, 'account_number': acc, 'ifsc_code': code}
    res = es.update_artist_bank_details(entity_id, data) if entity == 'artist' else es.update_institution_bank_details(entity_id, data)
    if cheque_file and res.get('success'):
        es.set_cancelled_cheque(entity, entity_id, f'ai_private/cheques/{cheque_file}')
    ctx.s.gov.audit(ctx.actor_label, 'bank.saved', f'{entity}:{entity_id}', {'account': tu.mask_account(acc), 'ifsc': code})
    return {'ok': bool(res.get('success')), 'saved': {'bank_name': bank_name, 'account': tu.mask_account(acc), 'ifsc': code},
            'error': res.get('error')}


def read_cheque(ctx, image_b64, mime, target):
    data, err = vision_json(ctx, image_b64, mime, CHEQUE_PROMPT)
    if err:
        return {'ok': False, 'error': err}
    data = data or {}
    acc = re.sub(r'\D', '', str(data.get('account_number') or ''))
    code = re.sub(r'\s', '', str(data.get('ifsc') or '')).upper()
    problems = []
    if not 9 <= len(acc) <= 18:
        problems.append('Account number is not clear')
    info = None
    if IFSC_RE.fullmatch(code):
        info = lookup_ifsc(ctx, code)
        if info and info.get('valid') is False:
            problems.append('This IFSC was not found in the bank directory')
    else:
        problems.append('IFSC is not clear')
    bank = data.get('bank_name') or (info or {}).get('BANK')
    branch = data.get('branch') or (info or {}).get('BRANCH')
    fname = ctx.s.files.save('cheques', f"cheque_{target.get('entity', 'artist')}_{target.get('id', 'x')}_{_stamp()}.jpg",
                             base64.b64decode(image_b64))
    cid = ctx.state.new_confirmation('bank_details', entity=target.get('entity', 'artist'), entity_id=target.get('id'),
                                     name=target.get('name'), bank_name=bank, account_number=acc, ifsc=code, cheque_file=fname)
    ctx.ui.cards.append({'type': 'bank_proposal', 'confirmation_id': cid, 'title': f"Bank details for {target.get('name') or 'this record'}",
                         'fields': {'Account holder': data.get('account_holder') or '', 'Bank': bank or '', 'Branch': branch or '',
                                    'Account number': tu.mask_account(acc), 'IFSC': code},
                         'problems': problems, 'button': 'Save bank details'})
    return {'ok': True, 'problems': problems, 'confirmation_id': cid,
            'read': {'bank': bank, 'branch': branch, 'account': tu.mask_account(acc), 'ifsc': code}}


def confirm_bank_proposal(ctx, cid):
    p = ctx.state.take_confirmation(cid, 'bank_details')
    if not p:
        return {'ok': False, 'error': 'This proposal has expired; please upload the cheque again.'}
    if not p.get('entity_id'):
        return {'ok': False, 'error': 'Which artist or institution are these details for? Select them first.'}
    return _save_bank(ctx, p['entity'], p['entity_id'], p.get('bank_name'), p.get('account_number'), p.get('ifsc'), p.get('cheque_file'))


class BankSkill(Skill):
    key, title = 'bank', 'Bank details'
    description = 'Optional bank details for artists and institutions, read from a cancelled cheque photo and checked.'

    @tool('validate_ifsc', 'Check an IFSC code and look up its bank and branch.', {'ifsc': S}, required=('ifsc',))
    def validate_ifsc(self, ctx, ifsc):
        code = re.sub(r'\s', '', ifsc).upper()
        if not IFSC_RE.fullmatch(code):
            return {'ok': False, 'valid_format': False, 'error': 'An IFSC has 11 characters: 4 letters, a zero, then 6 letters or digits.'}
        info = lookup_ifsc(ctx, code)
        if info and info.get('valid') is False:
            return {'ok': False, 'valid_format': True, 'error': 'This IFSC was not found in the bank directory.'}
        return {'ok': True, 'ifsc': code, 'bank': (info or {}).get('BANK'), 'branch': (info or {}).get('BRANCH'),
                'city': (info or {}).get('CITY'), 'checked_online': info is not None}

    @tool('save_bank_details', 'Save bank details for an artist or institution (optional; only when the coordinator gives them).',
          {'entity': {'type': 'string', 'enum': ['artist', 'institution']}, 'entity_id': I, 'bank_name': S,
           'account_number': S, 'ifsc_code': S}, required=('entity', 'entity_id', 'account_number', 'ifsc_code'))
    def save_bank_details(self, ctx, entity, entity_id, account_number, ifsc_code, bank_name=None):
        return _save_bank(ctx, entity, entity_id, bank_name, account_number, ifsc_code)

    @tool('request_cheque_upload', 'Ask for a photo of a cancelled cheque; bank details are read from it and shown for confirmation.',
          {'entity': {'type': 'string', 'enum': ['artist', 'institution']}, 'entity_id': I,
           'role': {'type': 'string', 'enum': ['main', 'accompanying']}})
    def request_cheque_upload(self, ctx, entity='artist', entity_id=None, role='main'):
        name = None
        if entity == 'artist' and not entity_id:
            a = next((x for x in ctx.draft.all_artists() if x.get('role') == role and x.get('artist_id')), None)
            entity_id, name = (a or {}).get('artist_id'), (a or {}).get('name')
        elif entity == 'institution' and not entity_id and ctx.draft.d['events']:
            e = ctx.draft.d['events'][0]
            entity_id, name = e.get('institution_id'), e.get('institution_name')
        if not entity_id:
            return {'ok': False, 'error': 'Select the artist or institution first.'}
        ctx.state.awaiting = {'kind': 'cheque', 'entity': entity, 'id': entity_id, 'name': name}
        ctx.ui.cards.append({'type': 'upload', 'kind': 'cheque', 'title': f'Cancelled cheque for {name or entity}',
                             'subtitle': 'Bank details are read from the photo and shown to you before anything is saved.',
                             'target': {'entity': entity, 'id': entity_id, 'name': name}})
        return {'ok': True, 'awaiting': 'cheque'}


class LookupsSkill(Skill):
    key, title = 'lookups', 'Program lookups'
    description = 'Finds existing programs and APRs in the database.'

    @tool('list_programs', 'Look up existing programs in the database (never answer from memory).',
          {'search': S, 'status': S, 'state': S, 'date_from': S, 'date_to': S})
    def list_programs(self, ctx, **filters):
        if not ctx.s.event_service:
            return {'ok': False, 'error': 'No database connection.'}
        rows = ctx.s.event_service.search_events({k: v for k, v in filters.items() if v}) or []
        return {'ok': True, 'count': len(rows), 'programs': [
            {'event_id': r.get('id'), 'date': str(r.get('start_date') or ''), 'title': r.get('title'), 'artist': r.get('artist_name'),
             'institution': r.get('institution_name'), 'city': r.get('city'), 'status': r.get('event_status'),
             'apr': r.get('apr_request_id')} for r in rows[:15]]}

    @tool('get_program', 'Details of one existing program by event_id.', {'event_id': I}, required=('event_id',))
    def get_program(self, ctx, event_id):
        ev = ctx.s.event_service.get_event_for_payment(event_id) if ctx.s.event_service else None
        if not ev:
            return {'ok': False, 'error': f'No program with ID {event_id}.'}
        return {'ok': True, 'program': {k: (str(v) if isinstance(v, (date, datetime)) else v) for k, v in ev.items() if k != 'image'}}
