/* Admin console: templates with live preview and version history, settings and skill switches,
   approvals, directory flags and the activity log. */
(() => {
  'use strict';
  const BASE = window.APP_ROOT != null ? window.APP_ROOT : (document.body.dataset.base || '');
  const $ = (s, r = document) => r.querySelector(s);
  const el = (tag, attrs, ...kids) => {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === 'class') n.className = v;
      else if (k.startsWith('on') && typeof v === 'function') n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v === true ? '' : v);
    }
    for (const c of kids.flat(3)) if (c !== null && c !== undefined && c !== false) n.append(c.nodeType ? c : document.createTextNode(String(c)));
    return n;
  };
  async function api(path, body, method) {
    const res = await fetch(BASE + '/admin/api' + path, { method: method || (body === undefined ? 'GET' : 'POST'), credentials: 'same-origin',
      headers: body === undefined ? {} : { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) });
    const data = await res.json().catch(() => ({}));
    if (res.status === 403) { location.href = BASE + '/admin'; }
    if (!res.ok) throw new Error((data.error || 'Request failed (' + res.status + ')') + (data.line ? ' (line ' + data.line + ')' : ''));
    return data;
  }
  let toastTimer = 0;
  const toast = t => { const n = $('#toast'); n.textContent = t; n.hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => { n.hidden = true; }, 4500); };
  const main = $('#admin-main');
  const when = s => s ? String(s).replace('T', ' ').slice(0, 16) : '';
  const guard = fn => async (...a) => { try { await fn(...a); } catch (e) { toast(e.message); } };

  // ── Overview ────────────────────────────────────────────────────────────
  async function overview() {
    const r = await api('/overview'), st = r.status, h = r.ai_health;
    const failing = h && h.ok === false;
    const rows = [
      ['AI assistant', st.ai && !failing, !st.ai ? 'OPENAI_API_KEY is not set: chat, voice and image reading are off'
        : failing ? 'Last AI call failed (' + when(h.at) + '): ' + h.message : 'Key set' + (h && h.ok ? '; it worked at ' + when(h.at) : '')],
      ['Email', st.email && !st.email_dry_run, st.email ? (st.email_dry_run ? 'Configured, but dry run is on: emails are saved, not sent' : 'Sending') : 'SMTP is not configured: emails are saved under instance/outbox'],
      ['Voice', st.voice, st.voice ? 'Server speech recognition and voice are on' : 'Browser speech only'],
      ['Google lookups', st.google, st.google ? 'GOOGLE_API_KEY is set' : 'Using Wikipedia, Wikidata and OpenStreetMap only'],
      ['Portal database', st.database, st.database ? 'Connected' : 'Not connected: filing is disabled'],
      ['Sign-in', st.auth_mode === 'email_otp', st.auth_mode === 'email_otp' ? 'Coordinators sign in with an emailed code' : 'Open: anyone with the link can use the assistant']];
    main.append(el('h2', {}, 'Overview'), el('p', { class: 'muted' }, 'APR Assistant ' + (r.version || '')),
      el('ul', { class: 'status-list' }, rows.map(([k, ok, v]) => el('li', {}, el('span', { class: 'dot' + (ok ? '' : ' off') }), el('strong', {}, k), el('span', {}, v)))),
      el('p', {}, el('button', { class: 'btn ghost small', type: 'button', onclick: guard(async () => {
        const res = await api('/ai-check', {}); toast(res.message); main.innerHTML = ''; overview();
      }) }, 'Check the AI key now')),
      el('h3', {}, 'Waiting for approval'),
      el('p', {}, el('span', { class: 'count' }, String(r.pending_approvals)), ' ', el('a', { href: '#approvals', onclick: () => go('approvals') }, 'Review approvals')),
      el('h3', {}, 'Skills'),
      el('p', { class: 'lead' }, r.skills.map(s => s.title + (s.core ? '' : s.enabled ? '' : ' (off)')).join(', ')),
      el('h3', {}, 'AI models'), el('p', { class: 'lead' }, 'Conversation: ' + r.models.conversation + '. Posters and cheques: ' + r.models.vision + '. Speech: ' + r.models.speech + '.'),
      el('h3', {}, 'AI usage, last 7 days'), r.usage.length ? el('table', { class: 'data' }, el('tr', {}, el('th', {}, 'Day'), el('th', {}, 'Model'), el('th', {}, 'Calls'), el('th', {}, 'Input tokens'), el('th', {}, 'of which cached'), el('th', {}, 'Output tokens')),
        r.usage.map(u => el('tr', {}, el('td', {}, u.day), el('td', {}, u.model), el('td', {}, String(u.calls)), el('td', {}, u.input.toLocaleString('en-IN')), el('td', {}, u.cached.toLocaleString('en-IN')), el('td', {}, u.output.toLocaleString('en-IN'))))) : el('p', { class: 'muted' }, 'No AI calls yet.'),
      el('h3', {}, 'Recent activity'), auditTable(r.audit));
  }

  // ── Templates ───────────────────────────────────────────────────────────
  const GROUP_ORDER = ['APR', 'Request for Payment', 'Event guidelines', 'Posters', 'Other emails', 'Assistant'];
  function groupOf(t) {                       // grouped by what they are for, as coordinators think of them
    const k = t.key;
    if (k === 'email.apr_confirmation' || k === 'email.apr_poster' || k === 'email.apr_batch_summary' || k.startsWith('layout.apr')) return 'APR';
    if (k === 'email.payment_request' || k === 'layout.rfp') return 'Request for Payment';
    if (k === 'email.pre_event_guidelines' || k === 'doc.event_guidelines') return 'Event guidelines';
    if (k === 'layout.poster') return 'Posters';
    if (t.kind === 'prompt') return 'Assistant';
    return 'Other emails';
  }
  let current = null;
  async function templates() {
    const { templates: list } = await api('/templates');
    const nav = el('div', { class: 'tpl-list' });
    const editor = el('div', { id: 'tpl-editor' }, el('p', { class: 'lead' }, 'Choose a template. Every save is a new version, and any earlier version can be switched back on.'));
    let lastGroup = null;
    list.sort((a, b) => GROUP_ORDER.indexOf(groupOf(a)) - GROUP_ORDER.indexOf(groupOf(b)));
    list.forEach(t => {
      const g = groupOf(t);
      if (g !== lastGroup) { nav.append(el('h4', {}, g)); lastGroup = g; }
      nav.append(el('button', { type: 'button', 'data-key': t.key, onclick: () => openTemplate(t.key) }, t.title || t.key, el('small', {}, 'Version ' + t.version + (t.versions > 1 ? ' of ' + t.versions : ''))));
    });
    main.append(el('h2', {}, 'Templates'), el('div', { class: 'two' }, nav, editor));
    const want = decodeURIComponent((location.hash.split(':')[1] || ''));
    if (want) openTemplate(want);
  }
  async function openTemplate(key) {
    const r = await api('/templates/' + encodeURIComponent(key));
    const t = r.template;
    history.replaceState(null, '', '#templates:' + encodeURIComponent(key));
    document.querySelectorAll('.tpl-list button').forEach(b => b.setAttribute('aria-current', String(b.dataset.key === key)));
    if (t.kind === 'document') { renderDocument(key, r); return; }
    current = { key, kind: t.kind, obj: null };
    const box = $('#tpl-editor');
    box.innerHTML = '';
    const pv = el('div', { class: 'preview' }, el('div', { class: 'bar' }, 'Preview'), el('div', { class: 'pv-body' }, el('p', { class: 'muted', style: 'padding:12px' }, 'Press Preview to see it with sample data.')));
    const note = el('input', { type: 'text', placeholder: 'What changed? (optional)', 'aria-label': 'Change note' });
    let getBody = () => t.body, getSubject = () => t.subject, getText = () => undefined;
    const form = el('div', { class: 'stack' });
    if (t.kind === 'email' || t.kind === 'email_layout' || t.kind === 'prompt') {
      const body = el('textarea', { class: 'code', spellcheck: 'false', 'aria-label': 'Template body' }); body.value = t.body || '';
      getBody = () => body.value;
      if (t.kind === 'email') {
        const subj = el('input', { type: 'text', 'aria-label': 'Subject' }); subj.value = t.subject || '';
        getSubject = () => subj.value;
        const text = el('textarea', { class: 'code short', spellcheck: 'false', 'aria-label': 'Plain-text version' }); text.value = (t.meta && t.meta.text) || '';
        getText = () => text.value;
        const ph = el('div', { class: 'placeholders' }, ((t.meta && t.meta.placeholders) || []).map(p => el('button', { type: 'button', title: 'Insert', onclick: () => insertAt(body, '{{ ' + p + ' }}') }, '{{ ' + p + ' }}')));
        form.append(el('label', {}, 'Subject', subj), el('label', {}, 'Email body (HTML; inherits the email frame)', ph, body),
          el('details', {}, el('summary', {}, 'Plain-text version (optional; generated from the HTML when empty)'), text));
      } else {
        form.append(el('p', { class: 'lead' }, t.kind === 'prompt' ? (t.meta && t.meta.help) || '' : 'The frame wraps every email: header, colours and footer.'), body);
      }
    } else {
      current.obj = JSON.parse(t.body || '{}');
      const json = el('textarea', { class: 'code', spellcheck: 'false', 'aria-label': 'Layout JSON' });
      const sync = () => { json.value = JSON.stringify(current.obj, null, 2); };
      const widgets = el('div');
      const rebuild = () => { widgets.innerHTML = ''; widgets.append(t.kind === 'apr_layout' ? aprEditor(current.obj, sync, rebuild) : t.kind === 'rfp_layout' ? rfpEditor(current.obj, sync, rebuild) : posterEditor(current.obj, sync)); };
      json.addEventListener('change', () => { try { current.obj = JSON.parse(json.value); rebuild(); } catch (e) { toast('That JSON is not valid: ' + e.message); } });
      rebuild(); sync();
      getBody = () => json.value;
      form.append(widgets, el('details', {}, el('summary', {}, 'Advanced: edit the JSON directly'), json));
    }
    const doPreview = guard(async () => { await preview(key, { body: getBody(), subject: getSubject(), text: getText() }, pv); });
    const save = guard(async () => {
      const payload = { body: getBody(), subject: getSubject(), text: getText(), note: note.value };
      let res = await saveTemplate(key, payload);
      if (res.missing) {                       // the major parts: never lost by accident
        const ok = confirm('This version leaves out parts the original template relies on:\n\n' +
          res.missing.map(m => '  \u2022 {{ ' + m + ' }}').join('\n') + '\n\nPress Cancel to put them back, or OK to save anyway.');
        if (!ok) return;
        res = await saveTemplate(key, Object.assign(payload, { confirm_missing: true }));
      }
      toast('Saved as version ' + res.version + (res.undeclared && res.undeclared.length ? '. Placeholders used: ' + res.undeclared.join(', ') : ''));
      openTemplate(key);
    });
    const testTo = el('input', { type: 'email', placeholder: 'you@spicmacay.com', 'aria-label': 'Test email address' });
    const actions = el('div', { class: 'row' },
      el('button', { class: 'btn ghost', type: 'button', onclick: doPreview }, 'Preview'),
      el('div', { class: 'grow' }, note), el('button', { class: 'btn primary', type: 'button', onclick: save }, 'Save as new version'));
    const extras = el('div', { class: 'row' },
      t.kind === 'email' ? [el('div', { class: 'grow' }, testTo), el('button', { class: 'btn ghost small', type: 'button', onclick: guard(async () => {
        const res = await api('/templates/' + encodeURIComponent(key) + '/test', { to: testTo.value });
        toast(res.ok ? (res.dry_run ? 'Test saved as a dry run (SMTP is off).' : 'Test email sent.') : (res.error || 'Could not send.'));
      }) }, 'Send me a test (saved version)')] : null,
      r.has_default ? el('button', { class: 'btn ghost small', type: 'button', onclick: guard(async () => {
        if (!confirm('Replace this template with the original default? The current version stays in the history.')) return;
        await api('/templates/' + encodeURIComponent(key) + '/reset', {}); toast('Default restored as a new version.'); openTemplate(key);
      }) }, 'Reset to default') : null);
    const versions = el('ul', { class: 'versions' }, r.history.map(h => el('li', {}, el('strong', {}, 'Version ' + h.version),
      el('span', {}, [h.created_by, when(h.created_at), h.note].filter(Boolean).join(', ')),
      h.active ? el('em', {}, 'Active') : el('button', { class: 'btn ghost small', type: 'button', onclick: guard(async () => {
        await api('/templates/' + encodeURIComponent(key) + '/activate', { version: h.version }); toast('Version ' + h.version + ' is active again.'); openTemplate(key);
      }) }, 'Switch back to this'))));
    box.append(el('h3', { style: 'margin-top:0' }, t.title || key), el('p', { class: 'muted' }, key + ', version ' + t.version),
      el('div', { class: 'split' }, el('div', {}, form, actions, extras), pv), el('h3', {}, 'History'), versions);
    doPreview();
  }
  async function saveTemplate(key, payload) {
    const res = await fetch(BASE + '/admin/api/templates/' + encodeURIComponent(key), { method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    const data = await res.json().catch(() => ({}));
    if (res.status === 409 && data.missing) return { missing: data.missing };
    if (!res.ok) throw new Error((data.error || 'Save failed (' + res.status + ')') + (data.line ? ' (line ' + data.line + ')' : ''));
    return data;
  }
  function renderDocument(key, r) {
    const t = r.template, m = t.meta || {}, box = $('#tpl-editor');
    box.innerHTML = '';
    const fileUrl = (v, dl) => BASE + '/admin/api/documents/' + encodeURIComponent(key) + '/file?' + (v ? 'version=' + v + '&' : '') + (dl ? 'download=1' : '');
    const input = el('input', { type: 'file', accept: 'application/pdf,.pdf', 'aria-label': 'Revised version (PDF)' });
    const note = el('input', { type: 'text', placeholder: 'What changed? (optional)', 'aria-label': 'Change note' });
    const upload = guard(async () => {
      if (!input.files.length) { toast('Choose a PDF first.'); return; }
      const fd = new FormData(); fd.append('file', input.files[0]); fd.append('note', note.value);
      const res = await fetch(BASE + '/admin/api/documents/' + encodeURIComponent(key), { method: 'POST', body: fd, credentials: 'same-origin' });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || 'Upload failed');
      toast('Uploaded as version ' + data.version + '. It is attached from now on.'); openTemplate(key);
    });
    const pv = el('div', { class: 'preview' }, el('div', { class: 'bar' }, 'The active version'),
      el('iframe', { src: fileUrl(), title: 'The active document', style: 'width:100%;height:540px;border:0;background:#fff' }));
    const versions = el('ul', { class: 'versions' }, r.history.map(h => el('li', {}, el('strong', {}, 'Version ' + h.version),
      el('span', {}, [h.created_by, when(h.created_at), h.note].filter(Boolean).join(', ')),
      el('a', { class: 'btn ghost small', href: fileUrl(h.version), target: '_blank', rel: 'noopener' }, 'Open'),
      h.active ? el('em', {}, 'Active') : el('button', { class: 'btn ghost small', type: 'button', onclick: guard(async () => {
        await api('/templates/' + encodeURIComponent(key) + '/activate', { version: h.version }); toast('Version ' + h.version + ' is attached again.'); openTemplate(key);
      }) }, 'Switch back to this'))));
    const current = m.file ? (m.original_name || 'Uploaded PDF') + (m.size ? ', ' + Math.round(m.size / 1024) + ' KB' : '') : 'The original document that ships with the app';
    box.append(el('h3', { style: 'margin-top:0' }, t.title || key), el('p', { class: 'muted' }, (m.help || '') + ' Version ' + t.version + '.'),
      el('div', { class: 'split' }, el('div', { class: 'stack' },
        el('p', {}, el('strong', {}, 'Attached now: '), current),
        el('a', { class: 'btn ghost', href: fileUrl(null, true) }, 'Download the active version'),
        el('label', {}, 'Upload a revised version (PDF, up to 15 MB)', input), note,
        el('div', { class: 'row' }, el('button', { class: 'btn primary', type: 'button', onclick: upload }, 'Upload as new version'),
          r.has_default ? el('button', { class: 'btn ghost small', type: 'button', onclick: guard(async () => {
            if (!confirm('Go back to the original document? The current version stays in the history.')) return;
            await api('/templates/' + encodeURIComponent(key) + '/reset', {}); toast('The original document is attached again.'); openTemplate(key);
          }) }, 'Back to the original') : null)),
        pv), el('h3', {}, 'History'), versions);
  }
  function insertAt(ta, text) {
    const s = ta.selectionStart ?? ta.value.length, e = ta.selectionEnd ?? ta.value.length;
    ta.value = ta.value.slice(0, s) + text + ta.value.slice(e);
    ta.focus(); ta.selectionStart = ta.selectionEnd = s + text.length;
  }
  async function preview(key, payload, pv) {
    const r = await api('/preview', Object.assign({ key }, payload));
    const body = pv.querySelector('.pv-body'), bar = pv.querySelector('.bar');
    body.innerHTML = '';
    if (r.type === 'html') {
      bar.textContent = 'Subject: ' + (r.subject || '');
      const f = el('iframe', { sandbox: '', title: 'Email preview' }); f.srcdoc = r.html; body.append(f);
    } else if (r.type === 'pdf') {
      bar.textContent = 'PDF preview with sample data';
      const bin = atob(r.data), bytes = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
      const url = URL.createObjectURL(new Blob([bytes], { type: 'application/pdf' }));
      body.append(el('a', { class: 'pv-open', href: url, target: '_blank', rel: 'noopener' }, 'Open the preview in a new tab'), el('iframe', { src: url, title: 'Document preview' }));
    } else if (r.type === 'image') {
      bar.textContent = 'Poster preview with sample data';
      body.append(el('img', { src: 'data:image/jpeg;base64,' + r.data, alt: 'Poster preview' }));
    } else {
      bar.textContent = 'Text';
      body.append(el('pre', { style: 'white-space:pre-wrap;padding:12px;margin:0' }, r.text || ''));
    }
  }

  // layout widgets, bound to the JSON object
  const txt = (o, k, label, sync, wide) => { const i = el('input', { type: 'text' }); i.value = o[k] ?? ''; i.addEventListener('input', () => { o[k] = i.value; sync(); }); return el('label', { class: wide ? 'grow' : null }, label, i); };
  const num = (o, k, label, sync, step) => { const i = el('input', { type: 'number', step: step || '1' }); i.value = o[k] ?? ''; i.addEventListener('input', () => { o[k] = i.value === '' ? null : Number(i.value); sync(); }); return el('label', {}, label, i); };
  const chk = (o, k, label, sync) => { const i = el('input', { type: 'checkbox' }); i.checked = o[k] !== false; i.addEventListener('change', () => { o[k] = i.checked; sync(); }); return el('label', { class: 'check' }, i, label); };
  const sel = (o, k, opts, label, sync) => { const s = el('select', {}, opts.map(v => el('option', { value: v }, v))); s.value = o[k] ?? opts[0]; s.addEventListener('change', () => { o[k] = s.value; sync(); }); return el('label', {}, label, s); };
  const col = (o, k, label, sync) => { const i = el('input', { type: 'color' }); i.value = o[k] || '#8B0000'; i.addEventListener('input', () => { o[k] = i.value; sync(); }); return el('label', {}, label, i); };
  const lines = (o, k, label, sync) => { const t = el('textarea', { class: 'code short', spellcheck: 'false' }); t.value = (o[k] || []).join('\n'); t.addEventListener('input', () => { o[k] = t.value.split('\n').filter(x => x.trim()); sync(); }); return el('label', { class: 'grow' }, label + ' (one per line)', t); };
  function columns(cols, sync, rebuild) {
    return el('table', { class: 'data cols' }, el('tr', {}, el('th', {}, 'Show'), el('th', {}, 'Column heading'), el('th', {}, 'Width'), el('th', {}, 'Order')),
      cols.map((c, i) => {
        const on = el('input', { type: 'checkbox', 'aria-label': 'Show ' + c.label }); on.checked = c.enabled !== false;
        on.addEventListener('change', () => { c.enabled = on.checked; sync(); });
        const lab = el('input', { type: 'text', 'aria-label': 'Heading for ' + c.key }); lab.value = c.label;
        lab.addEventListener('input', () => { c.label = lab.value; sync(); });
        const w = el('input', { type: 'number', min: '1', 'aria-label': 'Width of ' + c.label }); w.value = c.width;
        w.addEventListener('input', () => { c.width = Number(w.value) || 1; sync(); });
        const move = d => () => { const j = i + d; if (j < 0 || j >= cols.length) return; [cols[i], cols[j]] = [cols[j], cols[i]]; sync(); rebuild(); };
        return el('tr', {}, el('td', {}, on), el('td', {}, lab), el('td', {}, w),
          el('td', {}, el('button', { class: 'btn ghost small', type: 'button', 'aria-label': 'Move up', onclick: move(-1) }, '↑'), ' ',
            el('button', { class: 'btn ghost small', type: 'button', 'aria-label': 'Move down', onclick: move(1) }, '↓')));
      }));
  }
  function aprEditor(o, sync, rebuild) {
    o.page = o.page || {}; o.style = o.style || {}; o.header = o.header || {}; o.footer = o.footer || {};
    const wrap = el('div');
    wrap.append(el('fieldset', {}, el('legend', {}, 'Page and style'), el('div', { class: 'row' },
      sel(o.page, 'orientation', ['landscape', 'portrait'], 'Orientation', sync), num(o.page, 'margin_mm', 'Margin (mm)', sync),
      col(o.style, 'accent', 'Accent colour', sync), num(o.style, 'font_size', 'Text size', sync, '0.1'),
      sel(o, 'date_format', ['%d-%b-%Y', '%d-%m-%Y', '%d %b %Y', '%d/%m/%Y'], 'Date format', sync))));
    wrap.append(el('fieldset', {}, el('legend', {}, 'Header'), el('div', { class: 'row' }, chk(o.header, 'show_logo', 'Show the logo', sync)),
      el('div', { class: 'row' }, txt(o.header, 'title', 'Title', sync, true)), el('div', { class: 'row' }, txt(o.header, 'subtitle', 'Subtitle', sync, true))));
    (o.sections || []).forEach(sec => {
      const fs = el('fieldset', {}, el('legend', {}, chk(sec, 'enabled', sec.title || sec.id, sync)));
      if (sec.type === 'table') fs.append(el('div', { class: 'row' }, txt(sec, 'title', 'Section heading', sync, true)), columns(sec.columns || [], sync, rebuild));
      else if (sec.type === 'lines') fs.append(el('div', { class: 'row' }, lines(sec, 'lines', 'Summary lines', sync)));
      else fs.append(el('div', { class: 'row' }, txt(sec, 'title', 'Heading', sync, true)));
      wrap.append(fs);
    });
    wrap.append(el('fieldset', {}, el('legend', {}, 'Footer'), el('div', { class: 'row' },
      txt(o.footer, 'left', 'Left', sync, true), txt(o.footer, 'center', 'Centre', sync, true), txt(o.footer, 'right', 'Right', sync, true))));
    return wrap;
  }
  function rfpEditor(o, sync, rebuild) {
    o.header = o.header || {}; o.footer = o.footer || {}; o.page = o.page || {}; o.style = o.style || {};
    return el('div',
      el('fieldset', {}, el('legend', {}, 'Header'), el('div', { class: 'row' }, chk(o.header, 'show_logo', 'Show the logo', sync), col(o.style, 'accent', 'Accent colour', sync), num(o.style, 'font_size', 'Text size', sync, '0.1')),
        el('div', { class: 'row' }, txt(o.header, 'title', 'Title', sync, true), txt(o.header, 'invoice_label', 'Date label', sync), txt(o, 'to_label', 'Addressee label', sync))),
      el('fieldset', {}, el('legend', {}, 'Line items'), el('div', { class: 'row' }, txt(o, 'description', 'Description of each event', sync, true)), columns(o.columns || [], sync, rebuild)),
      el('fieldset', {}, el('legend', {}, 'Text'), el('div', { class: 'row' }, lines(o, 'after_table', 'After the table', sync)),
        el('div', { class: 'row' }, lines(o, 'bank_block', 'Bank details', sync)), el('div', { class: 'row' }, lines(o, 'signature', 'Signature', sync))),
      el('fieldset', {}, el('legend', {}, 'Footer'), el('div', { class: 'row' }, txt(o.footer, 'center', 'Footer', sync, true))),
      el('p', { class: 'muted' }, 'Bank account, PAN, TAN and the signatory come from Settings > Payments and Organisation.'));
  }
  function posterEditor(o, sync) {
    return el('div', el('fieldset', {}, el('legend', {}, 'Poster wording'), el('div', { class: 'stack' },
      txt(o, 'tagline', 'Top tagline', sync), txt(o, 'presenter_template', 'Presenter line ({chapter_or_institution}, {chapter} or {institution})', sync),
      txt(o, 'info_line', 'Information line in the footer band', sync), txt(o, 'footer_tagline', 'Bottom tagline', sync),
      chk(o, 'show_coordinator', "Print the coordinator's name", sync), chk(o, 'show_accompanying', 'Print accompanying artists', sync))));
  }

  // ── Settings ────────────────────────────────────────────────────────────
  async function settings() {
    const r = await api('/settings'), vals = r.values, inputs = {};
    const groups = {};
    r.schema.forEach(s => { (groups[s.group] = groups[s.group] || []).push(s); });
    const form = el('div');
    Object.entries(groups).forEach(([g, items]) => {
      const fs = el('fieldset', {}, el('legend', {}, g));
      items.forEach(s => {
        let inp;
        const v = vals[s.key];
        if (s.type === 'bool') { inp = el('input', { type: 'checkbox' }); inp.checked = !!v; fs.append(el('div', { class: 'row' }, el('label', { class: 'check' }, inp, s.label))); }
        else {
          if (s.type === 'select') { inp = el('select', {}, (s.options || []).map(o => el('option', { value: o }, o))); inp.value = v; }
          else { inp = el('input', { type: s.type === 'int' || s.type === 'float' ? 'number' : 'text', step: s.type === 'float' ? '0.1' : null });
                 inp.value = Array.isArray(v) ? v.join(', ') : (v ?? ''); }
          fs.append(el('div', { class: 'stack', style: 'margin:8px 0' }, el('label', {}, s.label + (s.type === 'email_list' || s.type === 'list' ? ' (comma separated)' : ''), inp)));
        }
        if (s.help) fs.append(el('p', { class: 'muted', style: 'margin:-2px 0 8px;font-size:14px' }, s.help));
        inputs[s.key] = [inp, s.type];
      });
      form.append(fs);
    });
    const sk = el('fieldset', {}, el('legend', {}, 'Skills'), el('p', { class: 'muted' }, 'Switch off anything your chapter does not use. Core skills stay on.'));
    r.skills.filter(s => !s.core).forEach(s => {
      const cb = el('input', { type: 'checkbox' }); cb.checked = s.enabled;
      inputs['skills.' + s.key + '.enabled'] = [cb, 'bool'];
      sk.append(el('div', { class: 'row' }, el('label', { class: 'check' }, cb, s.title + ': ' + s.description)));
    });
    form.append(sk);
    const save = guard(async () => {
      const values = {};
      for (const [k, [inp, type]] of Object.entries(inputs)) values[k] = type === 'bool' ? inp.checked : (type === 'int' || type === 'float') ? Number(inp.value) : inp.value;
      const res = await api('/settings', { values });
      toast('Saved ' + res.saved.length + ' settings.');
    });
    main.append(el('h2', {}, 'Settings'), el('p', { class: 'lead' }, 'Changes apply immediately and are recorded in Activity. Passwords and API keys stay in the server environment, not here.'),
      form, el('div', { class: 'row' }, el('button', { class: 'btn primary', type: 'button', onclick: save }, 'Save settings')));
  }

  // ── Approvals ───────────────────────────────────────────────────────────
  async function approvals(status) {
    status = status || 'pending';
    const r = await api('/approvals?status=' + status);
    const filter = el('select', { 'aria-label': 'Show' }, ['pending', 'approved', 'rejected', 'all'].map(s => el('option', { value: s }, s)));
    filter.value = status;
    filter.addEventListener('change', () => { main.innerHTML = ''; guard(approvals)(filter.value); });
    const KIND = { artist: 'New artist (provisional)', institution: 'New institution', coordinator_request: 'Coordinator to add' };
    const decide = (a, decision) => guard(async () => {
      const note = decision === 'reject' ? prompt('Reason (optional)') : '';
      if (note === null) return;
      await api('/approvals/' + a.id, { decision, note }); toast(decision === 'approve' ? 'Approved.' : 'Rejected.');
      main.innerHTML = ''; approvals(status);
    });
    main.append(el('h2', {}, 'Approvals'),
      el('p', { class: 'lead' }, 'Artists and institutions added by coordinators are used straight away and marked provisional until approved here. Rejecting an artist or institution hides it from the directory.'),
      el('div', { class: 'row' }, el('label', {}, 'Show', filter)),
      r.approvals.length ? el('table', { class: 'data' }, el('tr', {}, el('th', {}, 'What'), el('th', {}, 'Details'), el('th', {}, 'Requested'), el('th', {}, '')),
        r.approvals.map(a => { const p = a.payload || {};
          return el('tr', {}, el('td', {}, KIND[a.kind] || a.kind, a.ref_id ? el('div', { class: 'muted' }, 'ID ' + a.ref_id) : null),
            el('td', {}, el('strong', {}, p.name || p.email || ''), el('div', { class: 'muted' }, [p.art_form, p.role, [p.city, p.state].filter(Boolean).join(', '), p.email, p.program].filter(Boolean).join(' | '))),
            el('td', {}, a.requested_by, el('div', { class: 'muted' }, when(a.requested_at))),
            el('td', {}, a.status === 'pending' ? [el('button', { class: 'btn primary small', type: 'button', onclick: decide(a, 'approve') }, 'Approve'), ' ',
              el('button', { class: 'btn ghost small', type: 'button', onclick: decide(a, 'reject') }, 'Reject')] : el('em', {}, a.status + (a.note ? ': ' + a.note : ''))));
        })) : el('p', { class: 'muted' }, 'Nothing here.'));
  }

  // ── Directory flags ─────────────────────────────────────────────────────
  async function flags() {
    const r = await api('/flags');
    const f = { entity: 'artist', name: '', art_form: '', flag: 'deceased', note: '' };
    const add = guard(async () => { if (!f.name.trim()) { toast('Enter a name.'); return; } await api('/flags', f); toast('Flag added.'); main.innerHTML = ''; flags(); });
    const noop = () => {};
    main.append(el('h2', {}, 'Directory flags'),
      el('p', { class: 'lead' }, 'Flags warn coordinators before an artist is booked, for example an artist who has passed away (reviewer comment DC3). Matching also checks the art form, so a living namesake in another art form is not flagged.'),
      el('fieldset', {}, el('legend', {}, 'Add a flag'), el('div', { class: 'row' }, sel(f, 'entity', ['artist', 'institution'], 'For', noop),
        txt(f, 'name', 'Name', noop, true), txt(f, 'art_form', 'Art form (optional)', noop), sel(f, 'flag', ['deceased', 'inactive', 'do_not_book'], 'Flag', noop),
        txt(f, 'note', 'Note', noop, true), el('button', { class: 'btn primary', type: 'button', onclick: add }, 'Add flag'))),
      el('table', { class: 'data' }, el('tr', {}, el('th', {}, 'Name'), el('th', {}, 'Art form'), el('th', {}, 'Flag'), el('th', {}, 'Note'), el('th', {}, 'Source'), el('th', {}, '')),
        r.flags.map(x => el('tr', {}, el('td', {}, x.name || 'ID ' + x.ref_id), el('td', {}, x.art_form || ''), el('td', {}, x.flag), el('td', {}, x.note || ''), el('td', {}, x.source || ''),
          el('td', {}, el('button', { class: 'btn ghost small', type: 'button', onclick: guard(async () => { if (!confirm('Remove this flag?')) return; await api('/flags/' + x.id, undefined, 'DELETE'); main.innerHTML = ''; flags(); }) }, 'Remove'))))));
  }

  // ── Activity ────────────────────────────────────────────────────────────
  function auditTable(rows) {
    return el('table', { class: 'data' }, el('tr', {}, el('th', {}, 'When'), el('th', {}, 'Who'), el('th', {}, 'What'), el('th', {}, 'Details')),
      rows.map(a => el('tr', {}, el('td', {}, when(a.ts)), el('td', {}, a.actor), el('td', {}, a.action, a.target ? el('div', { class: 'muted' }, a.target) : null),
        el('td', { class: 'muted' }, JSON.stringify(a.details || {}).slice(0, 160)))));
  }
  async function activity() {
    const r = await api('/audit?limit=300');
    main.append(el('h2', {}, 'Activity'), el('p', { class: 'lead' }, 'Every APR filed, email sent or saved, template change, setting change and approval.'), auditTable(r.audit));
  }

  const TABS = { overview, templates, settings, approvals, flags, activity };
  async function go(tab) {
    if (!TABS[tab]) tab = 'overview';
    document.querySelectorAll('.tabs button').forEach(b => b.setAttribute('aria-selected', String(b.dataset.tab === tab)));
    main.innerHTML = '';
    if (!location.hash.startsWith('#' + tab)) history.replaceState(null, '', '#' + tab);
    try { await TABS[tab](); } catch (e) { main.append(el('p', { class: 'err' }, e.message)); }
  }
  document.querySelectorAll('.tabs button').forEach(b => b.addEventListener('click', () => go(b.dataset.tab)));
  go((location.hash.slice(1).split(':')[0]) || 'overview');
})();
