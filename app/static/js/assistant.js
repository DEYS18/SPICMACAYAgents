/* SPIC MACAY APR Assistant: conversation, live program draft, tap-to-confirm cards, uploads and voice. */
(() => {
  'use strict';
  const BASE = window.APP_ROOT != null ? window.APP_ROOT : (document.body.dataset.base || '');
  const $ = (s, root = document) => root.querySelector(s);
  const el = (tag, attrs, ...kids) => {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === 'class') n.className = v;
      else if (k === 'html') n.innerHTML = v;
      else if (k.startsWith('on') && typeof v === 'function') n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v === true ? '' : v);
    }
    for (const c of kids.flat(3)) if (c !== null && c !== undefined && c !== false) n.append(c.nodeType ? c : document.createTextNode(String(c)));
    return n;
  };
  const PREFS_KEY = 'sm-apr-prefs';
  const prefs = Object.assign({ lang: 'auto', tts: false, handsFree: false, review: false },
    (() => { try { return JSON.parse(localStorage.getItem(PREFS_KEY) || '{}'); } catch (e) { return {}; } })());
  const savePrefs = () => { try { localStorage.setItem(PREFS_KEY, JSON.stringify(prefs)); } catch (e) { /* private mode */ } };
  const S = { draft: null, issues: [], progress: null, busy: false, aiReady: true, voiceCaps: {}, recipes: [], voice: null };
  const msgs = $('#messages'), input = $('#composer-input'), sendBtn = $('#btn-send'), fileInput = $('#file-input');
  const TYPE_LABEL = { single: 'Single program', virasat: 'Virasat', circuit: 'Circuit' };
  const ROLE_LABEL = { main: 'Main', accompanying: 'Accompanying', filer: 'Filing', 'co-coordinator': 'Co-coordinator' };
  const STATUS = { ready: 'Ready', needs_email: 'Needs email', needs_amount: 'Needs amount', skipped: 'Not needed' };
  const UPLOAD_LABEL = { poster: 'Program poster', artist_photo: 'Artist photo', cheque: 'Cancelled cheque', program_photo: 'Program photo', stops: 'Circuit list', auto: 'File' };

  // ── server ──────────────────────────────────────────────────────────────
  async function api(path, body) {
    const res = await fetch(BASE + '/api/assistant' + path, {
      method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin',
      headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body) });
    if (res.status === 401) { location.href = BASE + '/login?next=' + encodeURIComponent(location.pathname); throw new Error('Please sign in.'); }
    const data = res.status === 204 ? null : await res.json().catch(() => ({}));
    if (!res.ok) throw new Error((data && data.error) || 'Something went wrong (' + res.status + ').');
    return data;
  }

  // ── text ────────────────────────────────────────────────────────────────
  function md(text) {
    const esc = s => s.replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const inline = s => s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\[([^\]]+)\]\(((?:https?:\/\/|\/)[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
    let html = '', list = null;
    for (const raw of esc(String(text || '')).split('\n')) {
      const m = raw.match(/^\s*(?:[-•*]|(\d+)[.)])\s+(.*)$/);
      if (m) {
        const type = m[1] ? 'ol' : 'ul';
        if (list !== type) { if (list) html += '</' + list + '>'; html += '<' + type + '>'; list = type; }
        html += '<li>' + inline(m[2]) + '</li>';
        continue;
      }
      if (list) { html += '</' + list + '>'; list = null; }
      if (raw.trim()) html += '<p>' + inline(raw) + '</p>';
    }
    return html + (list ? '</' + list + '>' : '');
  }
  const inr = n => Number(n).toLocaleString('en-IN');
  const listText = xs => xs.length < 2 ? (xs[0] || '') : xs.slice(0, -1).join(', ') + ' and ' + xs[xs.length - 1];
  const t12 = hhmm => { if (!hhmm) return ''; const [h, m] = hhmm.split(':').map(Number); return ((h % 12) || 12) + ':' + String(m).padStart(2, '0') + (h < 12 ? ' am' : ' pm'); };
  const timeText = (a, b) => a ? t12(a) + (b ? ' - ' + t12(b) : '') : '';

  let scrollQueued = false;
  function scrollEnd(force) {
    const near = msgs.scrollHeight - msgs.scrollTop - msgs.clientHeight < 160;
    if ((!force && !near && !S.follow) || scrollQueued) return;
    scrollQueued = true;
    requestAnimationFrame(() => { scrollQueued = false; msgs.scrollTo({ top: msgs.scrollHeight, behavior: 'auto' }); });
  }
  function leaveWelcome() {
    if (!document.body.classList.contains('is-empty')) return;
    document.body.classList.remove('is-empty');
    const w = $('#welcome');
    if (w) w.remove();
  }
  function addMsg(role, text) {
    if (!text) return null;
    if (role === 'user') leaveWelcome();
    const n = el('div', { class: 'msg ' + role });
    if (role === 'assistant') n.innerHTML = md(text); else n.textContent = text;
    msgs.append(n);
    scrollEnd(role === 'user');
    return n;
  }
  // A steady, fixed-height indicator (see assistant.css): the conversation above it never moves while it runs.
  let typingNode = null;
  function typing(on) {
    if (on && !typingNode) {
      typingNode = el('div', { class: 'msg assistant typing', role: 'status' },
        el('span', { class: 'typing-dots', 'aria-hidden': 'true' }, el('i'), el('i'), el('i')), el('span', { class: 'typing-text' }, 'Working on it'));
      msgs.append(typingNode); S.follow = true; scrollEnd(true);
    }
    if (!on && typingNode) { typingNode.remove(); typingNode = null; }
    face(on ? 'thinking' : 'idle');
  }
  let toastTimer = 0;
  function toast(text) {
    const t = $('#toast');
    t.textContent = text; t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.hidden = true; }, 4200);
  }
  function setBusy(v) { S.busy = v; sendBtn.disabled = v; }

  // ── turns ───────────────────────────────────────────────────────────────
  function renderTurn(r, opts) {
    typing(false);
    if (!r) return;
    if (r.reply) addMsg('assistant', r.reply);
    renderUI(r.ui || {});
    // A card with its own buttons (review, emails, batch plan) is the next step: no extra chips repeating it.
    const actionable = ((r.ui || {}).cards || []).some(c => ['review', 'outbox', 'batch_plan', 'rfp_picker', 'bank_proposal', 'upload'].includes(c.type));
    renderChips(actionable ? [] : (r.suggestions || []).slice(0, 3));
    if (r.draft) { S.draft = r.draft; S.issues = r.issues || []; S.progress = r.progress; renderDraft(); }
    S.follow = false;
    if ((!opts || opts.speak !== false) && r.reply) speakReply(r.reply);
  }
  async function send(text) {
    text = (text || '').trim();
    if (!text || S.busy) return;
    addMsg('user', text);
    input.value = ''; autosize();
    setBusy(true); typing(true);
    try { renderTurn(await api('/chat', { message: text, language: prefs.lang })); }
    catch (e) { typing(false); toast(e.message); }
    finally { setBusy(false); }
  }
  async function action(type, payload, cont) {
    if (cont || type === 'start_recipe') typing(true);
    try { renderTurn(await api('/action', { type, payload, continue: !!cont }), { speak: !!cont }); }
    catch (e) { typing(false); toast(e.message); }
  }
  const runTool = (name, args, label) => action('run_tool', { name, args: args || {}, label }, S.aiReady);
  async function speakReply(text) {
    if (prefs.tts && S.voice) await S.voice.speak(text, prefs.lang);
    if (prefs.handsFree && S.voice && S.voice.state === 'idle' && !S.busy) setTimeout(() => S.voice.start('toggle'), 350);
  }

  // ── cards in the conversation ───────────────────────────────────────────
  function renderUI(ui) {
    S.keepScroll = false;
    (ui.candidates || []).forEach(renderCandidates);
    (ui.cards || []).forEach(renderCard);
    (ui.artifacts || []).forEach(renderArtifact);
    if (!S.keepScroll || (ui.artifacts || []).length || (ui.candidates || []).length) scrollEnd(S.follow);
  }
  function renderCandidates(g) {
    const row = el('div', { class: 'cand-row' });
    g.items.forEach(it => {
      const flags = it.flags || [], deceased = flags.includes('deceased');
      const b = el('button', { class: 'cand ' + (it.band || ''), type: 'button' }, el('strong', {}, it.label), it.meta ? el('span', {}, it.meta) : null,
        deceased ? el('em', { class: 'flag' }, 'Recorded as deceased') : null, flags.includes('provisional') ? el('em', { class: 'flag' }, 'Provisional') : null);
      b.addEventListener('click', () => {
        const payload = { kind: it.kind || g.kind, id: it.id, label: it.label, role: it.role || g.role,
          event_index: it.event_index ?? g.event_index, email: it.email };
        if (deceased) {
          if (!confirm(it.label + ' is recorded as deceased. Is this a different person with the same name?')) return;
          payload.acknowledge_flags = true;
        }
        row.querySelectorAll('button').forEach(x => { x.disabled = true; });
        b.classList.add('strong');
        action('select_candidate', payload, S.aiReady);
      });
      row.append(b);
    });
    if (g.allow_add && g.query) {
      const what = g.kind === 'institution' ? 'institution' : 'artist';
      row.append(el('button', { class: 'cand add', type: 'button', onclick: () => send('"' + g.query + '" is a new ' + what + '; please add it.') },
        el('strong', {}, '+ Add as new'), el('span', {}, 'Not in this list')));
    }
    msgs.append(el('div', { class: 'cands' }, el('h3', {}, g.title), row));
  }
  function card(title, body, footer) {
    const n = el('section', { class: 'card' }, el('header', {}, title), el('div', { class: 'body' }, body));
    if (footer && footer.length) n.append(el('footer', {}, footer));
    msgs.append(n);
    return n;
  }
  const once = fn => e => { e.currentTarget.disabled = true; fn(); };
  function renderCard(c) {
    if (c.type === 'batch_plan') return renderBatchPlan(c);
    if (c.type === 'batch_results') return renderBatchResults(c);
    if (c.type === 'rfp_picker') return renderRfpPicker(c);
    if (c.type === 'review') {
      const sends = (c.sends || []).length ? el('p', { class: 'muted sends' }, 'The APR email will carry ' + listText(c.sends) + '.') : null;
      card(c.title, [el('div', { html: md(c.summary) }), (c.warnings || []).length ? el('ul', { class: 'warnings' }, c.warnings.map(w => el('li', {}, w))) : null, sends],
        [el('button', { class: 'btn ghost small', type: 'button', onclick: () => runTool('preview_apr_pdf', {}, 'Preview PDF') }, 'Preview PDF'),
         el('button', { class: 'btn primary', type: 'button', onclick: once(() => action('confirm', { confirmation_id: c.confirmation_id }, S.aiReady)) }, c.button || 'File APR')]);
    } else if (c.type === 'outbox') {
      const boxes = [];
      const rows = c.items.map(it => {
        const cb = el('input', { type: 'checkbox', 'aria-label': 'Send to ' + it.institution });
        cb.checked = it.status === 'ready'; cb.disabled = it.status !== 'ready';
        boxes.push([cb, it.item_id]);
        return el('div', { class: 'ob-item' }, cb,
          el('div', {}, el('strong', {}, it.institution),
            el('small', {}, it.to ? 'To ' + it.to + ((it.cc || []).length ? ', copy to ' + it.cc.join(', ') : '') : 'No email address yet'),
            it.amount_inr ? el('small', {}, 'Contribution Rs ' + it.amount_inr) : null,
            it.problem ? el('small', {}, it.problem) : null,
            it.pdf_url ? el('small', {}, el('a', { href: it.pdf_url, target: '_blank', rel: 'noopener' }, 'View the PDF')) : null),
          el('span', { class: 'badge ' + it.status }, STATUS[it.status] || it.status));
      });
      const chosen = () => boxes.filter(([cb]) => cb.checked).map(([, id]) => id);
      const btn = el('button', { class: 'btn primary', type: 'button', disabled: !chosen().length }, c.button);
      boxes.forEach(([cb]) => cb.addEventListener('change', () => {
        const n = chosen().length; btn.disabled = !n; btn.textContent = 'Send ' + n + ' email' + (n === 1 ? '' : 's');
      }));
      btn.addEventListener('click', () => { btn.disabled = true; action('confirm', { confirmation_id: c.confirmation_id, item_ids: chosen() }, S.aiReady); });
      card(c.title, rows, [btn]);
    } else if (c.type === 'upload') {
      card(c.title, el('div', { class: 'drop' }, el('p', {}, c.subtitle || ''),
        el('button', { class: 'btn primary', type: 'button', onclick: () => pickFile(c.kind, 'image/*', c.target) }, c.kind === 'cheque' ? 'Take or choose a photo' : 'Choose a photo')));
    } else if (c.type === 'web_result') {
      card(c.title || 'From the web', [el('p', {}, el('em', {}, 'Found on ' + (c.source || 'the web') + '. Please check before using it.')),
        c.description ? el('p', {}, c.description) : null, c.extract ? el('p', {}, c.extract) : null,
        c.deceased ? el('p', {}, el('strong', {}, 'Recorded as deceased')) : null,
        (c.awards || []).length ? el('p', {}, 'Awards: ' + c.awards.join(', ')) : null,
        (c.instruments || []).length ? el('p', {}, 'Instruments: ' + c.instruments.join(', ')) : null,
        (c.city || c.state) ? el('p', {}, [c.city, c.state].filter(Boolean).join(', ')) : null,
        c.url ? el('p', {}, el('a', { href: c.url, target: '_blank', rel: 'noopener' }, 'Open the source')) : null]);
    } else if (c.type === 'bank_proposal') {
      const dl = el('dl', { class: 'facts' });
      Object.entries(c.fields || {}).forEach(([k, v]) => dl.append(el('dt', {}, k), el('dd', {}, v || '-')));
      card(c.title, [dl, (c.problems || []).length ? el('ul', { class: 'warnings' }, c.problems.map(p => el('li', {}, p))) : null],
        [el('button', { class: 'btn primary', type: 'button', onclick: once(() => action('confirm', { confirmation_id: c.confirmation_id }, S.aiReady)) }, c.button)]);
    }
  }
  // ── batch: several posters at once ─────────────────────────────────────
  const PTYPE = { single: 'Single', virasat: 'Virasat', circuit: 'Circuit' };
  function renderBatchPlan(c) {
    const n = c.programs.length, np = c.posters.length;
    const body = [];
    if (c.needs_coordinator) {
      const em = el('input', { type: 'email', placeholder: 'you@spicmacay.com', 'aria-label': 'Your coordinator email' });
      body.push(el('div', { class: 'bp-fix' }, el('strong', {}, 'Your coordinator email'), ' ', el('small', {}, 'Every APR is emailed here.'),
        el('div', { class: 'bp-row' }, em, el('button', { class: 'btn primary small', type: 'button', 'data-action': 'save-coordinator',
          onclick: () => action('batch_coordinator', { email: em.value }, false) }, 'Save'))));
    }
    c.programs.forEach(p => body.push(batchProgram(p)));
    if (c.skipped.length) body.push(el('div', { class: 'bp-note' }, el('strong', {}, 'No APR needed'),
      el('ul', {}, c.skipped.map(x => el('li', {}, x.what + ': ' + x.reason)))));
    if (c.merged.length) body.push(el('div', { class: 'bp-note' }, el('strong', {}, 'On two posters, merged into one event'),
      el('ul', {}, c.merged.map(x => el('li', {}, x.what + (x.note ? '. ' + x.note : ''))))));
    const unread = c.posters.filter(x => x.error);
    if (unread.length) body.push(el('div', { class: 'bp-note' }, el('strong', {}, 'Could not read'),
      el('ul', {}, unread.map(x => el('li', {}, (x.filename || 'poster') + ': ' + x.error)))));
    const mode = el('select', { 'aria-label': 'How to email the APRs' }, el('option', { value: 'each' }, 'Email each APR to the coordinators'),
      el('option', { value: 'combined' }, 'One email with all the APRs'));
    mode.value = c.email_mode || 'each';
    mode.addEventListener('change', () => api('/action', { type: 'batch_email_mode', payload: { mode: mode.value } }).catch(e => toast(e.message)));
    const file = el('button', { class: 'btn primary', type: 'button', 'data-action': 'file-batch', disabled: !c.ready || !!c.needs_coordinator,
      onclick: once(() => action('confirm', { confirmation_id: c.confirmation_id, email_mode: mode.value }, false)) }, c.button);
    const node = el('section', { class: 'card batch', 'data-plan-id': c.plan_id },
      el('header', {}, 'Batch plan: ' + n + ' program' + (n === 1 ? '' : 's') + ' from ' + np + ' poster' + (np === 1 ? '' : 's')),
      el('div', { class: 'body' }, body), el('footer', {}, mode, file));
    const old = msgs.querySelector('[data-plan-id="' + c.plan_id + '"]');
    if (old) { old.replaceWith(node); S.keepScroll = true; } else msgs.append(node);
  }
  function batchProgram(p) {
    const live = p.status === 'ready' || p.status === 'needs_attention' || p.status === 'excluded';
    const cb = el('input', { type: 'checkbox', 'aria-label': 'Include ' + p.title, disabled: !live });
    cb.checked = p.include && p.status !== 'already_filed' && p.status !== 'filed';
    cb.addEventListener('change', () => action('batch_toggle', { pid: p.pid, include: cb.checked }, false));
    const typeSel = el('select', { class: 'bp-type', 'aria-label': 'Program type', disabled: !live }, Object.entries(PTYPE).map(([v, l]) => el('option', { value: v }, l)));
    typeSel.value = p.type;
    typeSel.addEventListener('change', () => action('batch_type', { pid: p.pid, program_type: typeSel.value }, false));
    const evs = el('ul', { class: 'bp-events' }, p.events.map(e => {
      const ecb = el('input', { type: 'checkbox', 'aria-label': 'Include ' + e.when + ' ' + e.place, disabled: !live || e.existing.length > 0 });
      ecb.checked = e.include;
      ecb.addEventListener('change', () => action('batch_toggle', { pid: p.pid, eid: e.eid, include: ecb.checked }, false));
      return el('li', { class: e.include ? '' : 'off' }, ecb, el('div', {}, el('span', {}, e.when + (e.days > 1 ? ' (' + e.days + ' days, one row each)' : '') + (e.time ? ', ' + e.time : '') + ': ' + e.place),
        el('small', {}, [e.artist, e.module].filter(Boolean).join(' | ') + (e.existing.length ? ' (already in the portal)' : ''))));
    }));
    return el('div', { class: 'bp-prog' + (p.include ? '' : ' off'), 'data-pid': p.pid },
      el('div', { class: 'bp-head' }, cb, typeSel, el('strong', { class: 'bp-title' }, p.title), el('span', { class: 'badge ' + p.status }, p.status_text)),
      p.thumbs.length ? el('div', { class: 'bp-thumbs' }, p.thumbs.map(u => el('a', { href: u, target: '_blank', rel: 'noopener' },
        el('img', { class: 'bp-thumb', src: u, alt: 'Poster', loading: 'lazy' })))) : null,
      evs, p.issues.length ? el('ul', { class: 'warnings' }, p.issues.map(x => el('li', {}, x))) : null,
      p.unresolved.map(u => batchFix(p, u)),
      p.warnings.length ? el('ul', { class: 'bp-notes' }, p.warnings.map(x => el('li', {}, x))) : null,
      p.apr ? el('p', { class: 'bp-filed' }, 'APR ' + p.apr.number + ': ', el('a', { href: p.apr.pdf_url, target: '_blank', rel: 'noopener' }, 'open the PDF')) : null);
  }
  function batchFix(p, u) {
    if (u.kind === 'artist') {
      return el('div', { class: 'bp-fix', 'data-said': u.said },
        el('div', {}, el('strong', {}, u.said), ' ', el('small', {}, (u.art_form ? u.art_form + ', ' : '') + (u.role === 'main' ? 'artist' : 'accompanying artist') + ' not found in the directory')),
        el('div', { class: 'bp-row' }, u.options.map(o => el('button', { class: 'chip small', type: 'button',
          onclick: () => action('batch_pick', { pid: p.pid, kind: 'artist', said: u.said, role: u.role, id: o.id }, false) }, 'Use ' + o.label + (o.meta ? ' (' + o.meta + ')' : ''))),
          el('button', { class: 'btn ghost small', type: 'button', 'data-action': 'add-artist',
            onclick: once(() => action('batch_add', { pid: p.pid, kind: 'artist', said: u.said, role: u.role, art_form: u.art_form }, false)) }, 'Add as new artist (provisional)')));
    }
    const name = el('input', { type: 'text', 'aria-label': 'Institution name' }); name.value = u.said || '';
    const city = el('input', { type: 'text', placeholder: 'City', 'aria-label': 'City' }); city.value = u.city || '';
    const state = el('input', { type: 'text', placeholder: 'State', 'aria-label': 'State', 'data-field': 'state' }); state.value = u.state || '';
    const email = el('input', { type: 'email', placeholder: 'Email (optional)', 'aria-label': 'Institution email' });
    return el('div', { class: 'bp-fix', 'data-said': u.said },
      el('div', {}, el('strong', {}, u.said), ' ', el('small', {}, u.city_mismatch && u.city ? 'no match in the directory for ' + u.city : 'not matched in the directory')),
      u.options.length ? el('div', { class: 'bp-row' }, u.options.map(o => el('button', { class: 'chip small', type: 'button',
        onclick: () => action('batch_pick', { pid: p.pid, kind: 'institution', said: u.said, id: o.sid }, false) }, 'Use ' + o.label + (o.meta ? ' (' + o.meta + ')' : '')))) : null,
      el('details', {}, el('summary', {}, 'Add it as a new institution'), el('div', { class: 'bp-form' }, name, city, state, email,
        el('button', { class: 'btn ghost small', type: 'button', 'data-action': 'add-institution',
          onclick: () => action('batch_add', { pid: p.pid, kind: 'institution', said: u.said, name: name.value, city: city.value, state: state.value, email: email.value }, false) }, 'Add institution'))));
  }
  function renderBatchResults(c) {
    card(c.title || 'Filed', el('ul', { class: 'bp-results' }, c.results.map(r => el('li', {}, r.ok
      ? [el('strong', {}, 'APR ' + r.apr_number), ' ', r.title, ' ', el('small', {}, '(' + r.email + ')')]
      : [el('strong', {}, 'Not filed: '), r.title, ' ', el('small', {}, r.error)]))));
  }
  function renderRfpPicker(c) {
    const rows = c.rows.map(r => {
      const cb = el('input', { type: 'checkbox', 'aria-label': 'Request payment from ' + r.institution });
      const amt = el('input', { type: 'number', min: '0', step: '500', placeholder: 'Amount (Rs)', 'aria-label': 'Contribution from ' + r.institution });
      const em = el('input', { type: 'email', placeholder: 'Institution email', 'aria-label': 'Email for ' + r.institution });
      em.value = r.email || '';
      return { r, cb, amt, em, node: el('div', { class: 'rfp-row', 'data-institution': r.institution }, cb,
        el('div', {}, el('strong', {}, r.institution), el('small', {}, r.dates + ', ' + r.artist + ', APR ' + r.apr), el('div', { class: 'bp-row' }, amt, em))) };
    });
    const btn = el('button', { class: 'btn primary', type: 'button', 'data-action': 'prepare-rfp' }, c.button);
    btn.addEventListener('click', () => {
      const chosen = rows.filter(x => x.cb.checked).map(x => ({ event_ids: x.r.event_ids, amount: x.amt.value, email: x.em.value, institution: x.r.institution }));
      if (!chosen.length) { toast('Tick at least one institution.'); return; }
      action('batch_rfp', { rows: chosen }, false);
    });
    card(c.title, [el('p', { class: 'muted' }, 'Nothing is sent yet: you will see every email before it goes.'), rows.map(x => x.node)], [btn]);
  }
  async function batchUpload(files) {
    const imgs = files.filter(f => (f.type || '').startsWith('image/')).slice(0, 20);
    if (!imgs.length) { toast('Choose poster images (JPEG or PNG).'); return; }
    addMsg('user', imgs.length + ' poster' + (imgs.length === 1 ? '' : 's') + ': ' + imgs.map(f => f.name).join(', '));
    setBusy(true); typing(true);
    try {
      const data = [];
      for (const f of imgs) data.push({ data: await downscale(f, 1600), mime: 'image/jpeg', filename: f.name });
      renderTurn(await api('/batch', { files: data }));
    } catch (e) { typing(false); toast(e.message); }
    finally { setBusy(false); }
  }

  function renderArtifact(a) {
    const sep = a.url.includes('?') ? '&' : '?';
    msgs.append(el('div', { class: 'artifact' },
      a.type === 'image' ? el('img', { class: 'thumb', src: a.url, alt: a.label }) : el('div', { class: 'doc', 'aria-hidden': 'true' }, 'PDF'),
      el('div', { class: 'label' }, a.label),
      el('div', { class: 'actions' },
        el('a', { class: 'btn ghost small', href: a.url, target: '_blank', rel: 'noopener' }, 'Open'),
        el('a', { class: 'btn ghost small', href: a.url + sep + 'dl=1', download: a.filename }, 'Download'),
        navigator.share ? el('button', { class: 'btn primary small', type: 'button', onclick: () => shareFile(a) }, 'Share') : null)));
  }
  async function shareFile(a) {
    try {
      const blob = await (await fetch(a.url, { credentials: 'same-origin' })).blob();
      const file = new File([blob], a.filename, { type: blob.type });
      if (navigator.canShare && navigator.canShare({ files: [file] })) await navigator.share({ files: [file], title: a.label });
      else await navigator.share({ title: a.label, url: new URL(a.url, location.href).href });
    } catch (e) { if (e.name !== 'AbortError') toast('Sharing is not available here; use Download.'); }
  }
  function renderChips(list) {
    const box = $('#chips');
    box.innerHTML = '';
    list.forEach(c => box.append(el('button', { class: 'chip', type: 'button', onclick: () => send(c.value) }, c.label)));
  }

  // ── the live draft ──────────────────────────────────────────────────────
  const sec = (title, content) => el('div', { class: 'd-sec' }, el('h3', {}, title), content);
  const kv = rows => el('dl', { class: 'kv' }, rows.map(([k, v]) => [el('dt', {}, k), el('dd', {}, v)]));
  function field(path, value, opts) {
    opts = opts || {};
    const shown = opts.display || value;
    const b = el('button', { class: 'field' + (shown ? '' : ' empty'), type: 'button', title: 'Tap to edit' }, shown || opts.placeholder || 'Add');
    b.addEventListener('click', () => {
      const inp = el(opts.multiline ? 'textarea' : 'input', { class: 'field-input', 'aria-label': opts.label || path });
      inp.value = opts.raw !== undefined ? (opts.raw || '') : (value || '');
      b.replaceWith(inp);
      inp.focus();
      let done = false;
      const commit = save => {
        if (done) return; done = true;
        const v = inp.value.trim();
        if (!save || v === (opts.raw !== undefined ? (opts.raw || '') : (value || ''))) { renderDraft(); return; }
        const m = path.match(/^events\.(\d+)\.institution_name$/);
        if (m && v) runTool('find_institution', { name: v, event_index: Number(m[1]) }, 'Institution ' + v);
        else action('update_field', { path, value: v }, false);
      };
      inp.addEventListener('keydown', e => {
        if (e.key === 'Enter' && !opts.multiline) { e.preventDefault(); commit(true); }
        if (e.key === 'Escape') commit(false);
      });
      inp.addEventListener('blur', () => commit(true));
    });
    return b;
  }
  function personRow(name, meta, role, extra, onRemove) {
    return el('div', { class: 'person' }, el('div', { class: 'who' }, el('strong', {}, name || '?'), meta ? el('small', {}, meta) : null),
      role ? el('span', { class: 'role' }, role) : null, extra || null,
      onRemove ? el('button', { class: 'x', type: 'button', 'aria-label': 'Remove ' + (name || ''), onclick: onRemove }, '×') : null);
  }
  function photoBtn(a) {
    if (a.has_photo) return el('span', { class: 'photo-btn has' }, 'Photo on file');
    if (a.role !== 'main') return null;
    return el('button', { class: 'photo-btn', type: 'button', onclick: () => pickFile('artist_photo', 'image/*', { artist_id: a.artist_id, role: a.role, name: a.name }) }, 'Add photo');
  }
  function renderDraft() {
    const d = S.draft;
    if (!d) return;
    renderGlance();
    const p = S.progress || { done: 0, total: 6, ready: false };
    const pct = Math.round(100 * p.done / (p.total || 1));
    const o = d.outputs || {};
    $('#pill-ring').style.setProperty('--p', pct);
    $('#draft-pill').hidden = !(d.program_type || d.main_artist || (d.events || []).length || (d.accompanying || []).length);
    $('#pill-ring b').textContent = p.done + '/' + p.total;
    $('#pill-text').textContent = [TYPE_LABEL[d.program_type] || 'New program', d.events.length ? d.events.length + ' event' + (d.events.length > 1 ? 's' : '') : '',
      o.apr ? 'APR ' + o.apr.number : ''].filter(Boolean).join(', ');
    const body = $('#draft-body');
    body.innerHTML = '';
    body.append(el('div', { class: 'd-head' }, el('h2', {}, d.title || TYPE_LABEL[d.program_type] || 'New program'),
      el('span', { class: 'ring', style: '--p:' + pct, title: p.done + ' of ' + p.total + ' essentials done' }, el('b', {}, p.done + '/' + p.total))));

    const toggles = el('div', { class: 'toggles' });
    [['apr', 'APR'], ['poster', 'Poster'], ['payment_request', 'Request for Payment'], ['guidelines', 'Guidelines']].forEach(([k, label]) => {
      const cb = el('input', { type: 'checkbox' });
      cb.checked = !!(d.recipe || {})[k];
      const t = el('label', { class: 'toggle' + (cb.checked ? ' on' : '') }, cb, label);
      cb.addEventListener('change', () => { t.classList.toggle('on', cb.checked); action('set_recipe', { [k]: cb.checked }, false); });
      toggles.append(t);
    });
    body.append(sec('What do you need?', toggles));

    const typeSel = el('select', { class: 'field-input', 'aria-label': 'Program type' }, el('option', { value: '' }, 'Choose'),
      Object.entries(TYPE_LABEL).map(([v, l]) => el('option', { value: v }, l)));
    typeSel.value = d.program_type || '';
    typeSel.addEventListener('change', () => action('update_field', { path: 'program_type', value: typeSel.value }, false));
    const pay = el('input', { type: 'checkbox', 'aria-label': 'Payment required by Delhi account' });
    pay.checked = !!d.payment_required;
    pay.addEventListener('change', () => action('update_field', { path: 'payment_required', value: pay.checked }, false));
    body.append(sec('Program', kv([
      ['Type', typeSel], ['Title', field('title', d.title, { placeholder: 'Optional' })],
      ['Module', field('module', d.module, { placeholder: 'Concert, Lecture Demonstration...' })],
      ['Time', field('start_time', timeText(d.start_time, d.end_time), { placeholder: 'e.g. 10am-12pm', raw: d.start_time ? timeText(d.start_time, d.end_time) : '' })],
      ['Chapter', field('chapter', d.chapter, { placeholder: 'Optional' })],
      ['Notes', field('notes', d.notes, { placeholder: 'Printed on the APR', multiline: true })],
      ['Delhi A/c', el('label', { class: 'toggle' + (pay.checked ? ' on' : '') }, pay, 'Payment required')]])));

    const arts = el('div');
    const people = [d.main_artist].concat(d.accompanying || []).filter(Boolean);
    people.forEach(a => arts.append(personRow(a.name, [a.art_form, a.provisional ? 'provisional' : '', a.artist_id ? '' : 'not in the directory yet'].filter(Boolean).join(', '),
      ROLE_LABEL[a.role], photoBtn(a), () => action('remove_artist', { ref: a.artist_id ? String(a.artist_id) : a.name }, false))));
    if (!people.length) arts.append(el('p', { class: 'muted' }, d.program_type === 'virasat' ? 'Each event below has its own artist.' : "Say or type the artist's name."));
    body.append(sec('Artists', arts));

    const evs = el('div');
    d.events.forEach((e, i) => {
      const place = [e.institution_name, [e.city, e.state].filter(Boolean).join(', ')].filter(Boolean).join(', ');
      const rows = [
        ['Time', field('events.' + i + '.start_time', timeText(e.start_time, e.end_time), { placeholder: d.start_time ? timeText(d.start_time, d.end_time) + ' (program)' : 'Add time' })],
        ['Institution', field('events.' + i + '.institution_name', e.institution_name, { placeholder: 'Add institution', display: place })],
        ['Module', field('events.' + i + '.module', e.module, { placeholder: d.module ? d.module + ' (program)' : 'Add module' })],
        ['Students', field('events.' + i + '.audience_students', e.audience_students != null ? String(e.audience_students) : '', { placeholder: d.audience_default + ' (default)' })],
        ['Contribution', field('events.' + i + '.contribution', e.contribution != null ? (e.contribution === 'NIL' ? 'NIL' : 'Rs ' + inr(e.contribution)) : '',
          { placeholder: 'Amount or NIL', raw: e.contribution != null ? String(e.contribution) : '' })]];
      if (e.artists) rows.push(['Artists', el('span', {}, e.artists.map(a => a.name + (a.role === 'main' ? '' : ' (acc.)')).join(', '))]);
      const box = el('div', { class: 'event' },
        el('div', { class: 'ev-head' }, el('span', { class: 'ev-num' }, String(i + 1)), field('events.' + i + '.date', e.date_display, { placeholder: 'Add date', raw: e.date_display || '' }),
          el('button', { class: 'x', type: 'button', 'aria-label': 'Remove event ' + (i + 1), onclick: () => action('remove_event', { index: i }, false) }, '×')),
        kv(rows));
      S.issues.filter(x => x.event_index === i && /institution$/.test(x.field) && e.institution_name).forEach(x => box.append(el('p', { class: 'ev-note' }, x.message)));
      evs.append(box);
    });
    evs.append(el('button', { class: 'btn ghost small add-row', type: 'button', onclick: () => action('add_event', {}, false) }, '+ Add event'));
    body.append(sec(d.program_type === 'circuit' ? 'Circuit stops' : 'Events', evs));

    const co = el('div');
    (d.coordinators || []).forEach(c => co.append(personRow(c.name || c.email, c.email || '', ROLE_LABEL[c.role] || '', null,
      () => action('remove_coordinator', { ref: c.email || c.name }, false))));
    if (!(d.coordinators || []).length) co.append(el('p', { class: 'muted' }, 'Tell me who is filing, and anyone else coordinating.'));
    body.append(sec('Coordinators', co));

    const req = S.issues.filter(x => x.severity === 'required'), warn = S.issues.filter(x => x.severity === 'warning');
    if (req.length || warn.length) body.append(sec('Still needed', [req.length ? el('ul', { class: 'issues req' }, req.map(x => el('li', {}, x.message))) : null,
      warn.length ? el('ul', { class: 'issues warn' }, warn.map(x => el('li', {}, x.message))) : null]));

    if (o.apr || (o.posters || []).length || (o.emails || []).length) {
      const list = el('div', { class: 'outputs' });
      if (o.apr) list.append(el('a', { href: o.apr.pdf_url, target: '_blank', rel: 'noopener' }, 'APR ' + o.apr.number + ' (PDF)'));
      (o.posters || []).forEach((x, k) => list.append(el('a', { href: x.url, target: '_blank', rel: 'noopener' }, 'Poster ' + (k + 1))));
      if ((o.emails || []).length) list.append(el('span', {}, o.emails.filter(x => x.ok).length + ' email(s) sent or saved'));
      body.append(sec('Done', list));
    }
    const acts = el('div', { class: 'd-actions' });
    const r = d.recipe || {};
    if (r.apr && !o.apr) acts.append(el('button', { class: 'btn primary', type: 'button', disabled: !p.ready, onclick: () => runTool('review_program', {}, 'Review and file') }, 'Review and file APR'));
    if (r.poster || o.apr) acts.append(el('button', { class: 'btn ghost', type: 'button', disabled: !d.events.length, onclick: () => runTool('generate_poster', { event_index: 0 }, 'Make the poster') }, 'Poster'));
    if (r.payment_request || o.apr) acts.append(el('button', { class: 'btn ghost', type: 'button', disabled: !d.events.length, onclick: () => runTool('prepare_payment_requests', {}, 'Prepare Request for Payment') }, 'Request for Payment'));
    if (acts.children.length) body.append(acts);
  }

  // ── files ───────────────────────────────────────────────────────────────
  const readDataURL = file => new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(r.result); r.onerror = rej; r.readAsDataURL(file); });
  async function downscale(file, max) {
    try {
      const bmp = await createImageBitmap(file);
      const k = Math.min(1, max / Math.max(bmp.width, bmp.height));
      const c = document.createElement('canvas');
      c.width = Math.round(bmp.width * k); c.height = Math.round(bmp.height * k);
      c.getContext('2d').drawImage(bmp, 0, 0, c.width, c.height);
      return c.toDataURL('image/jpeg', 0.88);
    } catch (e) { return readDataURL(file); }
  }
  function pickFile(kind, accept, target, multiple) {
    fileInput.accept = accept || ''; fileInput.multiple = !!multiple;
    fileInput._ctx = { kind, target: target || {} };
    fileInput.click();
  }
  async function upload(kind, file, target) {
    if (!file) return;
    const isImage = (file.type || '').startsWith('image/');
    addMsg('user', (UPLOAD_LABEL[kind] || 'File') + ': ' + file.name);
    setBusy(true); typing(true);
    try {
      const data = isImage ? await downscale(file, 1800) : await readDataURL(file);
      renderTurn(await api('/upload', { kind, data, mime: isImage ? 'image/jpeg' : file.type, filename: file.name, target: target || {} }));
    } catch (e) { typing(false); toast(e.message); }
    finally { setBusy(false); }
  }

  // ── setup ───────────────────────────────────────────────────────────────
  function autosize() { input.style.height = 'auto'; input.style.height = Math.min(input.scrollHeight, 150) + 'px'; sendBtn.hidden = !input.value.trim(); }
  function show(menuSel, btnSel, v) { $(menuSel).hidden = !v; $(btnSel).setAttribute('aria-expanded', String(v)); }
  function setupComposer() {
    $('#composer').addEventListener('submit', e => { e.preventDefault(); send(input.value); });
    input.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(input.value); } });
    input.addEventListener('input', autosize);
    $('#btn-attach').addEventListener('click', () => show('#attach-menu', '#btn-attach', $('#attach-menu').hidden));
    $('#attach-menu').addEventListener('click', e => {
      const b = e.target.closest('button[data-kind]');
      if (!b) return;
      show('#attach-menu', '#btn-attach', false);
      const main = S.draft && S.draft.main_artist;
      const target = b.dataset.kind === 'artist_photo' && main ? { artist_id: main.artist_id, role: 'main', name: main.name } : {};
      pickFile(b.dataset.kind, b.dataset.accept, target, !!b.dataset.multiple);
    });
    fileInput.addEventListener('change', async () => {
      const files = Array.from(fileInput.files), ctx = fileInput._ctx || {};
      fileInput.value = '';
      if (ctx.kind === 'posters_batch') { await batchUpload(files); return; }
      for (const f of files) await upload(ctx.kind, f, ctx.target);
    });
    $('#menu-new').addEventListener('click', () => { show('#menu', '#btn-menu', false); $('#btn-new').click(); });
    $('#btn-new').addEventListener('click', async () => {
      const d = S.draft;
      if (d && (d.events.length || d.main_artist) && !(d.outputs || {}).apr && !confirm('Start a new program? This draft is kept under "Pick up where you left off" when you are signed in.')) return;
      try { boot(await api('/start', { new: true, language: prefs.lang })); } catch (e) { toast(e.message); }
    });
    document.addEventListener('click', e => {
      if (!e.target.closest('#menu, #btn-menu')) show('#menu', '#btn-menu', false);
      if (!e.target.closest('#attach-menu, #btn-attach')) show('#attach-menu', '#btn-attach', false);
    });
  }
  function setupMenu() {
    $('#btn-menu').addEventListener('click', () => show('#menu', '#btn-menu', $('#menu').hidden));
    [['#pref-tts', 'tts'], ['#pref-handsfree', 'handsFree'], ['#pref-review', 'review']].forEach(([sel, key]) => {
      const cb = $(sel);
      cb.checked = !!prefs[key];
      cb.addEventListener('change', () => { prefs[key] = cb.checked; savePrefs(); });
    });
    const ls = $('#lang-select');
    ls.value = prefs.lang;
    ls.addEventListener('change', () => {
      prefs.lang = ls.value; savePrefs();
      api('/action', { type: 'set_language', payload: { language: ls.value } }).catch(() => {});
      toast('Language: ' + ls.options[ls.selectedIndex].text);
    });
  }
  function setupSheet() {
    const pill = $('#draft-pill'), sheet = $('#draft'), bd = $('#backdrop');
    const open = v => { sheet.classList.toggle('open', v); bd.hidden = !v; pill.setAttribute('aria-expanded', String(v)); };
    pill.addEventListener('click', () => open(true));
    $('#draft-close').addEventListener('click', () => open(false));
    bd.addEventListener('click', () => open(false));
    document.addEventListener('keydown', e => { if (e.key === 'Escape') open(false); });
  }
  function setupDrop() {
    const hint = $('#drop-hint');
    let depth = 0;
    window.addEventListener('dragenter', e => { if (e.dataTransfer && Array.from(e.dataTransfer.types || []).includes('Files')) { depth++; hint.hidden = false; } });
    window.addEventListener('dragleave', () => { depth = Math.max(0, depth - 1); if (!depth) hint.hidden = true; });
    window.addEventListener('dragover', e => e.preventDefault());
    window.addEventListener('drop', async e => {
      e.preventDefault(); depth = 0; hint.hidden = true;
      const dropped = Array.from(e.dataTransfer.files || []);
      if (dropped.filter(f => (f.type || '').startsWith('image/')).length > 1) { await batchUpload(dropped); return; }
      for (const f of dropped) await upload(/\.(csv|xlsx)$/i.test(f.name) ? 'stops' : 'auto', f, {});
    });
  }
  function setupVoice() {
    const mic = $('#btn-mic'), taal = mic.querySelector('.taal'), vs = $('#voice-status'), vsText = $('#vs-text'), vsTimer = $('#vs-timer');
    for (let i = 0; i < 16; i++) taal.append(el('i', { class: i === 0 ? 'sam' : i === 8 ? 'khali' : '', style: '--i:' + i }));
    const dots = Array.from(taal.children);
    let beat = 0, beatTimer = 0, clock = 0;
    S.voice = new window.SMVoice({
      base: BASE, language: () => prefs.lang,
      serverSTT: () => !!S.voiceCaps.server_stt, serverTTS: () => !!S.voiceCaps.server_tts,
      onLevel: lv => mic.style.setProperty('--level', lv.toFixed(3)),
      onSpeakStart: info => { if (AV) { AV.startSpeaking(info); showFaceState('speaking'); } },
      onSpeakEnd: () => { if (AV && AV.state === 'speaking') { AV.stopSpeaking(); showFaceState(S.busy ? 'thinking' : 'idle'); if (S.busy) AV.setState('thinking'); } },
      onState: st => {
        face(st === 'recording' ? 'listening' : st === 'processing' ? 'thinking' : (S.busy ? 'thinking' : 'idle'));
        mic.classList.toggle('recording', st === 'recording');
        mic.classList.toggle('busy', st === 'processing');
        vs.hidden = st === 'idle';
        clearInterval(beatTimer); clearInterval(clock);
        dots.forEach(d => d.classList.remove('on'));
        if (st === 'recording') {
          const ls = $('#lang-select');
          vsText.textContent = 'Listening (' + ls.options[ls.selectedIndex].text + ')';
          const t0 = Date.now();
          vsTimer.textContent = '0:00';
          clock = setInterval(() => { const s = Math.floor((Date.now() - t0) / 1000); vsTimer.textContent = Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0'); }, 500);
          beatTimer = setInterval(() => { dots.forEach(d => d.classList.remove('on')); dots[beat % 16].classList.add('on'); beat++; }, 250);
        } else if (st === 'processing') { vsText.textContent = 'Writing down what you said'; vsTimer.textContent = ''; }
      },
      onInterim: t => { input.value = t; autosize(); },
      onResult: t => { if (prefs.review) { input.value = t; autosize(); input.focus(); toast('Check the text, then send it.'); } else send(t); },
      onError: m => toast(m),
      onStopWord: () => { prefs.handsFree = false; savePrefs(); $('#pref-handsfree').checked = false; toast('Hands-free is off.'); }
    });
    $('#vs-cancel').addEventListener('click', () => S.voice.cancel());
    let downAt = 0, holdTimer = 0, holding = false;
    mic.addEventListener('pointerdown', e => {
      e.preventDefault();
      S.voice.stopSpeaking();
      if (S.voice.state === 'recording') { S.voice.stop(); downAt = 0; return; }
      downAt = Date.now(); holding = false;
      holdTimer = setTimeout(() => { holding = true; S.voice.start('hold'); }, 280);
    });
    mic.addEventListener('pointerup', () => {
      clearTimeout(holdTimer);
      if (holding) { holding = false; S.voice.stop(); }
      else if (downAt && Date.now() - downAt < 280 && S.voice.state === 'idle') S.voice.start('toggle');
    });
    mic.addEventListener('pointerleave', () => { clearTimeout(holdTimer); if (holding) { holding = false; S.voice.stop(); } });
    mic.addEventListener('contextmenu', e => e.preventDefault());
    document.addEventListener('keydown', e => {
      if (e.altKey && (e.key === 'v' || e.key === 'V')) { e.preventDefault(); if (S.voice.state === 'recording') S.voice.stop(); else S.voice.start('toggle'); }
      if (e.key === 'Escape' && S.voice.state !== 'idle') S.voice.cancel();
    });
  }

  // ── the assistant's face ────────────────────────────────────────────────
  const AV = window.SMAvatar;
  const FACE_TEXT = { idle: 'Ready when you are', listening: 'Listening', thinking: 'Working on it', speaking: 'Speaking' };
  function face(st) {
    if (!AV) return;
    if (AV.state === 'speaking' && st !== 'speaking') return;      // a reply being read aloud keeps the face speaking
    AV.setState(st);
    showFaceState(st);
  }
  function showFaceState(st) {
    const rail = $('#host-rail');
    if (rail) rail.dataset.state = st;
    const t = $('#host-status-text');
    if (t) t.textContent = FACE_TEXT[st] + (st === 'idle' ? '' : '…');
    const stop = $('#host-stop');
    if (stop) stop.hidden = st !== 'speaking';
    const chip = $('#speak-chip');
    if (chip) chip.hidden = st !== 'speaking';
  }
  function setupFace() {
    if (!AV) return;
    AV.mount($('#host-face'), { bow: true });
    AV.mount($('#speak-face'));
    const stop = () => { if (S.voice) S.voice.stopSpeaking(); };
    $('#host-stop').addEventListener('click', stop);
    $('#speak-stop').addEventListener('click', stop);
    const say = $('#say-list');
    SAY.forEach(t => say.append(el('li', {}, el('button', { type: 'button', onclick: () => { input.value = t; autosize(); input.focus(); } }, t))));
  }
  const SAY = ['Concert by Pt. Ronu Majumdar at IIT Bombay on 15 November, 6 pm, contribution Rs 25,000',
    'सर्किट: विदुषी उमा डोगरा, पुणे के तीन स्कूल, 4 से 6 दिसंबर', 'Send the Request for Payment for APR 208',
    'Which programs still have payments pending?'];

  // ── this program at a glance (laptop): what the coordinator has said so far, read-only ──
  function renderGlance() {
    const box = $('#program-glance');
    if (!box) return;
    const d = S.draft, p = S.progress || { done: 0, total: 6 };
    box.innerHTML = '';
    const started = d && (d.program_type || d.main_artist || (d.events || []).length || (d.accompanying || []).length || (d.outputs || {}).apr);
    const pct = Math.round(100 * p.done / (p.total || 1));
    box.append(el('div', { class: 'glance-head' }, el('h2', {}, 'This program'),
      started ? el('span', { class: 'ring', style: '--p:' + pct, title: p.done + ' of ' + p.total + ' essentials done' }, el('b', {}, p.done + '/' + p.total)) : null));
    if (!started) {
      box.append(el('p', { class: 'glance-empty' }, 'As we talk, the program comes together here: the artists, the dates and institutions, and anything still missing. Nothing is filed until you say so.'));
      return;
    }
    const o = d.outputs || {};
    box.append(el('p', { class: 'glance-type' }, [TYPE_LABEL[d.program_type] || 'Program type not chosen yet', d.title].filter(Boolean).join(': ')));
    const sec = (title, ...kids) => el('div', { class: 'glance-sec' }, el('h3', {}, title), kids);
    const people = [d.main_artist].concat(d.accompanying || []).filter(Boolean);
    if (people.length) box.append(sec('Artists', people.map(a => el('p', {}, a.name,
      el('small', {}, [a.art_form, a.role === 'main' ? 'main artist' : 'accompanying', a.provisional ? 'provisional' : ''].filter(Boolean).join(', '),
        a.role === 'main' && a.has_photo ? el('span', { class: 'ok' }, ', photo on file') : null)))));
    if ((d.events || []).length) box.append(sec(d.events.length > 1 ? (d.program_type === 'circuit' ? 'Circuit stops' : 'Events') : 'Event', d.events.map(e => el('div', { class: 'glance-ev' },
      el('p', {}, [e.date_display || 'Date to come', timeText(e.start_time || d.start_time, e.end_time || d.end_time)].filter(Boolean).join(', ')),
      el('small', {}, [[e.institution_name, e.city].filter(Boolean).join(', ') || 'Institution to come',
        e.contribution === 'NIL' ? 'no contribution' : e.contribution != null ? 'Rs ' + inr(e.contribution) : ''].filter(Boolean).join('; '))))));
    if ((d.coordinators || []).length) box.append(sec('Coordinators', el('p', {}, d.coordinators.map(c => c.name || c.email).join(', '))));
    const req = (S.issues || []).filter(x => x.severity === 'required');
    if (req.length && !o.apr) box.append(sec('Still needed', el('ul', { class: 'glance-need' }, req.slice(0, 4).map(x => el('li', {}, x.message)))));
    if (o.apr || (o.posters || []).length) {
      const out = el('div', { class: 'glance-out' });
      if (o.apr) out.append(el('a', { class: 'doc-link', href: o.apr.pdf_url, target: '_blank', rel: 'noopener' }, 'APR ' + o.apr.number + ' (PDF)'));
      (o.posters || []).slice(-3).forEach((x, k) => out.append(el('a', { href: x.url, target: '_blank', rel: 'noopener', title: 'Poster ' + (k + 1) },
        el('img', { src: x.url, alt: 'Poster ' + (k + 1), loading: 'lazy' }))));
      const sent = (o.emails || []).filter(x => x.ok).length;
      box.append(sec('Done', out, sent ? el('small', {}, sent + ' email' + (sent > 1 ? 's' : '') + ' sent or saved') : null,
        o.apr && o.apr.has_poster ? el('small', {}, 'The poster went with the APR email.') : null));
    }
    box.append(el('button', { class: 'btn ghost glance-edit', type: 'button', onclick: () => $('#draft-pill').click() }, 'Check or change the details'));
  }

  // ── boot ────────────────────────────────────────────────────────────────
  function renderWelcome(w) {
    const wf = el('div', { class: 'welcome-face' });
    msgs.append(el('section', { class: 'welcome', id: 'welcome' }, wf, el('h2', {}, w.title || 'Namaste'), w.text ? el('p', {}, w.text) : null));
    if (AV && getComputedStyle(wf).display !== 'none') AV.mount(wf, { bow: true });
  }
  // The original assistant greeted coordinators aloud as the screen opened. Browsers may keep a page silent until the
  // first tap: then a small "Tap to hear the welcome" button appears, so the spoken welcome is never lost.
  function speakWelcome(w) {
    const text = w && (w.spoken || w.text);
    if (!text || !S.voice || S.welcomeSpoken) return;
    S.welcomeSpoken = true;
    const lang = prefs.lang === 'auto' ? 'hi' : prefs.lang;
    S.voice.speak(text, lang).catch(() => {});
    setTimeout(() => {
      const a = S.voice.audio, playing = (a && !a.paused && !a.ended) || ('speechSynthesis' in window && speechSynthesis.speaking);
      if (playing || !document.body.classList.contains('is-empty')) return;
      const b = el('button', { class: 'chip hear', type: 'button', id: 'hear-welcome', onclick: () => { b.remove(); S.voice.speak(text, lang).catch(() => {}); } },
        '🔊 सुनिए · Tap to hear the welcome');
      $('#chips').prepend(b);
    }, 2200);
  }
  function setupSpeaker() {
    const b = $('#btn-speaker'), box = $('#pref-tts');
    if (!b || !box) return;
    const sync = () => { b.setAttribute('aria-pressed', String(box.checked)); b.title = box.checked ? 'Replies are read aloud' : 'Read replies aloud'; };
    b.addEventListener('click', () => { box.checked = !box.checked; box.dispatchEvent(new Event('change', { bubbles: true })); sync(); if (!box.checked && S.voice) S.voice.stopSpeaking(); });
    box.addEventListener('change', sync);
    sync();
  }
  function renderStarters() {
    const box = $('#chips');
    box.innerHTML = '';
    (S.recipes || []).forEach(rc => box.append(el('button', { class: 'chip', type: 'button', onclick: () => {
      if (rc.kind === 'attach') {
        const b = document.querySelector('#attach-menu button[data-kind="' + (rc.attach || '') + '"]');
        if (b) b.click();
        return;
      }
      if (rc.kind === 'message' && rc.message) { send(rc.message); return; }
      startRecipe(rc);
    } }, rc.label)));
  }
  function renderRecent(list) {
    $('#recent-wrap').hidden = !list.length;
    const rw = $('#rail-recent-wrap');
    if (rw) rw.hidden = !list.length;
    [$('#recent'), $('#rail-recent')].filter(Boolean).forEach(ul => {
      ul.innerHTML = '';
      list.slice(0, ul.id === 'rail-recent' ? 5 : 20).forEach(c => ul.append(el('li', {}, el('button', { type: 'button', onclick: async () => { try { boot(await api('/start', { resume_id: c.id, language: prefs.lang })); } catch (e) { toast(e.message); } } },
        el('strong', {}, c.title), el('span', {}, [TYPE_LABEL[c.program_type], c.events ? c.events + ' event(s)' : '', c.apr ? 'APR ' + c.apr : ''].filter(Boolean).join(', '))))));
    });
  }
  function startRecipe(rc) { addMsg('user', rc.label); action('start_recipe', { key: rc.key }, true); }
  function boot(r) {
    S.aiReady = !!r.ai_ready; S.voiceCaps = r.voice || {}; S.recipes = r.recipes || [];
    $('#ai-status').hidden = S.aiReady;
    msgs.innerHTML = '';
    const fresh = !(r.history && r.history.length);
    document.body.classList.toggle('is-empty', fresh);
    if (!fresh) r.history.forEach(m => addMsg(m.role, m.text));
    else { renderWelcome(r.welcome || { title: 'Namaste', text: r.reply || '' }); speakWelcome(r.welcome); }
    renderRecent(r.recent || []);
    renderTurn(Object.assign({}, r, { reply: null }), { speak: false });
    renderGlance();
    if (fresh) renderStarters();
  }
  async function init() {
    setupComposer(); setupMenu(); setupSheet(); setupDrop(); setupFace(); setupVoice(); setupSpeaker();
    try { boot(await api('/start', { language: prefs.lang })); } catch (e) { toast(e.message); }
  }
  init();
})();
