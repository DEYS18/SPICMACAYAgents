"""
Governance store: versioned templates, settings, audit log, approvals, directory flags,
per-program coordinators, a lookup cache and saved conversations.

It lives in the assistant's own SQLite file (instance/governance.db), so administrators can
change wording, layouts and behaviour from the Admin console without code changes and
without altering the portal's MySQL schema. Every change is versioned and audited, and any
earlier version can be re-activated.
"""
import hashlib
import hmac
import json
import os
import sqlite3
import threading
import time
from datetime import datetime

LANGS = ['auto', 'en', 'hi', 'hinglish', 'mr', 'bn', 'ta', 'te', 'kn', 'ml', 'gu', 'pa', 'or', 'as', 'ur']

SETTINGS_SCHEMA = [
    # Organisation
    ('Organisation', 'org.name', 'Organisation name', 'str', 'SPIC MACAY', ''),
    ('Organisation', 'org.tagline', 'Tagline', 'str', 'Society for the Promotion of Indian Classical Music And Culture Amongst Youth', ''),
    ('Organisation', 'org.website', 'Website', 'str', 'https://www.spicmacay.org', ''),
    ('Organisation', 'org.info_email', 'Public contact email', 'str', 'info@spicmacay.com', ''),
    ('Organisation', 'org.registered_office', 'Registered office', 'str', '41/42 Lucknow Road, New Delhi – 110054', 'Printed on the Request for Payment.'),
    ('Organisation', 'org.pan', 'PAN', 'str', 'AABTS8382A', ''),
    ('Organisation', 'org.tan', 'TAN', 'str', 'DELS27706A', ''),
    # Payments
    ('Payments', 'bank.bank_name', 'Bank name', 'str', 'State Bank of India', 'Account institutions pay their contribution into.'),
    ('Payments', 'bank.branch', 'Branch', 'str', 'Modern School, Barakhamba Road, New Delhi', ''),
    ('Payments', 'bank.account_name', 'Account name', 'str', 'SPIC MACAY', ''),
    ('Payments', 'bank.account_number', 'Account number', 'str', '10773571902', ''),
    ('Payments', 'bank.ifsc', 'IFSC', 'str', 'SBIN0011781', ''),
    ('Payments', 'rfp.signatory_name', 'Signatory name', 'str', 'Sabyasachi Dey', ''),
    ('Payments', 'rfp.signatory_title', 'Signatory title', 'str', 'National Coordinator', ''),
    ('Payments', 'rfp.feedback_form_url', 'Feedback form link', 'str', '', 'Shown in Request for Payment and thank-you emails when set.'),
    ('Payments', 'bank.ifsc_lookup', 'Check IFSC codes online (public Razorpay IFSC directory)', 'bool', True, ''),
    # APR
    ('APR', 'apr.default_audience', 'Default student audience per event', 'int', 300, 'Shown at review, never asked.'),
    ('APR', 'apr.payment_required_default', '"Payment required by Delhi A/c" starts as Yes', 'bool', True, ''),
    ('APR', 'apr.finance_cc', 'Always copy these addresses on APR emails', 'email_list', ['smhighereducation@spicmacay.com'], ''),
    ('APR', 'apr.send_artist_acknowledgement', 'Email the artist a thank-you when an APR is filed', 'bool', True, ''),
    ('APR', 'apr.attach_poster', 'Attach the program poster to the APR email', 'bool', True,
     'The poster the coordinator uploaded, or one the assistant made in the conversation. It is also kept with the program, '
     'so Requests for Payment sent later carry it too.'),
    ('APR', 'apr.auto_poster', 'No poster yet? Make one when filing (single programs, when the main artist\'s photo is on file)', 'bool', True,
     'The review card says so before the coordinator taps File APR.'),
    ('APR', 'apr.calendar_invite', 'Attach a calendar invite (.ics) for upcoming events to the APR email', 'bool', True, ''),
    ('APR', 'apr.write_portal_records', 'Write the portal\'s APR records (custom_apr, and event_series for programs)', 'bool', True,
     'Keep on: this is how the APR appears in the portal and its approval workflow.'),
    ('APR', 'apr.write_ai_request_rows', 'Also write apr_payment_request rows, exactly as the previous version did', 'bool', True,
     'Keep on: the previous version\'s dashboard, payment reminders, resend and reports read these rows.'),
    ('APR', 'apr.number_scheme', 'APR number', 'select', 'portal', 'portal = the custom_apr id, the number the portal shows (recommended); '
     'legacy = APR-<event>-<date> as the previous version wrote; sequence = the previous AI assistant\'s numbering. '
     'The number is also written into apr_payment_request.custom_apr.', ['portal', 'legacy', 'sequence']),
    ('APR', 'apr.program_type_ids', 'Program-type ids (JSON), if not read from taxonomy', 'str', '', 'Normally read from taxonomy_term_field_data (Circuit 288, Single Event 289, Viraasat Series 291 in production).'),
    ('APR', 'apr.write_event_series', 'Also create a Program (event_series) record for Virasat and circuits', 'bool', True, 'Matches the portal hierarchy: one Program holding several events.'),
    ('APR', 'db.ensure_modules', 'Modules to add to the portal if missing', 'list', ['Workshops', 'Yoga & Meditation'],
     'Each is added to event_module once, only when no module of that name exists (singular or plural, and "&" or "and", count as the same). '
     'A module switched off in the portal is left alone. Example to add: Baithak.'),
    ('APR', 'db.store_institution_as', 'Store the institution in event_list.institution as', 'select', 'name',
     'name = as the portal stores and shows it (recommended). id = as the previous version did; choose it only while that version still runs '
     'alongside this one, since its lookups find institutions by id (the portal then shows a number).', ['name', 'id']),
    ('APR', 'db.store_module_as', 'Store the module in event_list.event_category as', 'select', 'tid', 'The portal stores the event_module id (tid).', ['tid', 'name']),
    ('APR', 'reports.send_on_apr_create', 'Send both weekly reports every time an APR is created (testing only)', 'bool', False, ''),
    # Directory
    ('Directory', 'artists.acg_email', 'Artist Care Group email for new provisional artists', 'email_list', [], ''),
    ('Directory', 'coordinators.directory_only', 'Only coordinators in the directory can be added to a program', 'bool', True, 'Others become a request to the admin team.'),
    ('Directory', 'coordinators.admin_email', 'Send coordinator-addition requests to', 'email_list', [], ''),
    ('Directory', 'search.web_enrichment', 'Search the web when an artist or institution is not in the directory', 'bool', True, 'Wikipedia/Wikidata and OpenStreetMap work without keys.'),
    ('Directory', 'search.google_places', 'Use Google Places for institutions (needs GOOGLE_API_KEY)', 'bool', True, ''),
    ('Directory', 'search.google_kg', 'Use Google Knowledge Graph for artists (needs GOOGLE_API_KEY)', 'bool', True, ''),
    # Posters
    ('Posters', 'poster.require_main_artist_photo', "Require the main artist's photo before making a poster", 'bool', True, 'Reviewer comment DC11.'),
    ('Posters', 'poster.time_format', 'Time format on posters', 'select', '12h', '', ['12h', '24h']),
    # Emails
    ('Emails', 'email.require_button_confirmation', 'Emails can only be sent by tapping Send (not by a typed or spoken yes)', 'bool', False, ''),
    ('Emails', 'email.dry_run', "Dry run: prepare and log emails but don't send them", 'bool', False, 'Saved copies appear in instance/outbox.'),
    # Assistant
    ('Assistant', 'assistant.model', 'AI model for the conversation', 'str', 'gpt-4o', 'Defaults to OPENAI_MODEL from the server environment.'),
    ('Assistant', 'assistant.reasoning_effort', 'Reasoning effort for the conversation (GPT-5 and later)', 'select', 'low',
     'Lower is faster and cheaper. "auto" uses the model default (medium for GPT-5.5).', ['auto', 'none', 'low', 'medium', 'high']),
    ('Assistant', 'assistant.vision_model', 'Model for reading posters and cheques', 'str', 'gpt-4o', 'Defaults to OPENAI_VISION_MODEL, else OPENAI_MODEL.'),
    ('Assistant', 'assistant.vision_reasoning_effort', 'Reasoning effort for reading posters and cheques', 'select', 'medium',
     'Accuracy matters most here.', ['auto', 'none', 'low', 'medium', 'high']),
    ('Assistant', 'assistant.api', 'OpenAI API', 'select', 'auto',
     'auto uses the Responses API for GPT-6 models (needed for tool calling there) and Chat Completions otherwise.', ['auto', 'chat', 'responses']),
    ('Assistant', 'assistant.temperature', 'Creativity (0 to 1; GPT-4o family only)', 'float', 0.3, 'Reasoning models ignore it.'),
    ('Assistant', 'assistant.max_tool_rounds', 'Steps the assistant may take per message', 'int', 8, ''),
    ('Assistant', 'assistant.show_face', "Show the assistant's face: she greets with folded hands and her lips move while replies are read aloud", 'bool', True,
     'On a laptop she stands at the left of the conversation, with the program at a glance on the right. In Hindi and Marathi she '
     'speaks of herself in the feminine, to match the face and the default voice.'),
    # Voice
    ('Voice', 'voice.stt_model', 'Speech recognition model', 'str', 'gpt-4o-mini-transcribe', 'Falls back to whisper-1.'),
    ('Voice', 'voice.tts_model', 'Speech model for spoken replies', 'str', 'gpt-4o-mini-tts', 'Falls back to tts-1.'),
    ('Voice', 'voice.tts_voice', 'Voice', 'select', 'coral', '', ['alloy', 'ash', 'ballad', 'coral', 'echo', 'fable', 'nova', 'onyx', 'sage', 'shimmer']),
    ('Voice', 'voice.server_tts', 'Use the server voice for spoken replies (clearer Hindi)', 'bool', True, 'Otherwise the browser voice is used.'),
    ('Voice', 'voice.default_language', 'Default conversation language', 'select', 'auto', '', LANGS),
    # Access
    ('Access', 'admin.emails', 'Administrator emails (in addition to ADMIN_EMAILS)', 'email_list', [], ''),
]


def schema_dicts():
    out = []
    for row in SETTINGS_SCHEMA:
        group, key, label, typ, default, help_ = row[:6]
        out.append({'group': group, 'key': key, 'label': label, 'type': typ, 'default': default,
                    'help': help_, 'options': row[6] if len(row) > 6 else None})
    return out


_DEFAULTS = {r[1]: r[4] for r in SETTINGS_SCHEMA}
# Server environment variables that act as defaults until an administrator saves a value
_ENV_DEFAULTS = {'assistant.model': ('OPENAI_MODEL',), 'assistant.vision_model': ('OPENAI_VISION_MODEL', 'OPENAI_MODEL'),
                 'voice.stt_model': ('OPENAI_STT_MODEL',), 'voice.tts_model': ('OPENAI_TTS_MODEL',)}


def _env_default(key):
    for var in _ENV_DEFAULTS.get(key, ()):
        v = (os.getenv(var) or '').strip()
        if v:
            return v
    return None
_TYPES = {r[1]: r[3] for r in SETTINGS_SCHEMA}


def coerce(key, value):
    typ = _TYPES.get(key)
    if typ == 'bool':
        return value if isinstance(value, bool) else str(value).strip().lower() in ('1', 'true', 'yes', 'on')
    if typ == 'int':
        return int(float(value))
    if typ == 'float':
        return float(value)
    if typ == 'list':
        if isinstance(value, str):
            value = value.replace(';', ',').split(',')
        return [str(v).strip() for v in (value or []) if str(v).strip()]
    if typ == 'email_list':
        if isinstance(value, str):
            value = [v.strip() for v in value.replace(';', ',').split(',')]
        return [v for v in (value or []) if v and '@' in v]
    return value


def _now():
    return datetime.now().isoformat(timespec='seconds')


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_by TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS templates (key TEXT NOT NULL, version INTEGER NOT NULL, kind TEXT NOT NULL, title TEXT,
    subject TEXT, body TEXT NOT NULL, meta TEXT, created_by TEXT, created_at TEXT, note TEXT, PRIMARY KEY (key, version));
CREATE TABLE IF NOT EXISTS template_active (key TEXT PRIMARY KEY, version INTEGER NOT NULL, updated_by TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, actor TEXT, action TEXT, target TEXT, details TEXT);
CREATE TABLE IF NOT EXISTS approvals (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, ref_id TEXT, payload TEXT,
    status TEXT DEFAULT 'pending', requested_by TEXT, requested_at TEXT, decided_by TEXT, decided_at TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS program_coordinators (id INTEGER PRIMARY KEY AUTOINCREMENT, apr_request_id TEXT, event_ids TEXT,
    uid TEXT, name TEXT, email TEXT, phone TEXT, chapter TEXT, role TEXT, added_by TEXT, added_at TEXT);
CREATE TABLE IF NOT EXISTS directory_flags (id INTEGER PRIMARY KEY AUTOINCREMENT, entity TEXT, ref_id TEXT, name TEXT,
    art_form TEXT, flag TEXT, note TEXT, source TEXT, updated_by TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT, fetched_at REAL);
CREATE TABLE IF NOT EXISTS conversations (id TEXT PRIMARY KEY, user_email TEXT, state TEXT, updated_at REAL);
CREATE TABLE IF NOT EXISTS login_codes (email TEXT PRIMARY KEY, code_hash TEXT, expires REAL, attempts INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS idx_conv_user ON conversations(user_email, updated_at);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts);
"""


class Governance:
    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)) or '.', exist_ok=True)
        self._lock = threading.RLock()
        self._settings = None
        with self._conn() as c:
            c.executescript(SCHEMA_SQL)

    def _conn(self):
        c = sqlite3.connect(self.path, timeout=15)
        c.row_factory = sqlite3.Row
        try:
            c.execute('PRAGMA journal_mode=WAL')
        except sqlite3.DatabaseError:
            pass
        return c

    def _q(self, sql, params=(), one=False):
        with self._conn() as c:
            cur = c.execute(sql, params)
            rows = [dict(r) for r in cur.fetchall()]
        return (rows[0] if rows else None) if one else rows

    def _x(self, sql, params=()):
        with self._lock, self._conn() as c:
            cur = c.execute(sql, params)
            return cur.lastrowid

    # ── settings ─────────────────────────────────────────────────────────────
    def _load_settings(self):
        if self._settings is None:
            self._settings = {r['key']: json.loads(r['value']) for r in self._q('SELECT key, value FROM settings')}
        return self._settings

    def get_setting(self, key, default=None):
        vals = self._load_settings()
        if key in vals:
            return vals[key]
        env = _env_default(key)
        if env:
            return env
        if key in _DEFAULTS:
            return _DEFAULTS[key]
        return default

    def all_settings(self) -> dict:
        vals = dict(_DEFAULTS)
        vals.update({k: _env_default(k) for k in _ENV_DEFAULTS if _env_default(k)})
        vals.update(self._load_settings())
        return vals

    # ── AI usage, per day and model (for cost oversight in the admin console) ─
    def add_usage(self, model, inp, out, cached=0):
        key = f"usage:{datetime.now():%Y-%m-%d}:{model}"
        with self._lock:
            cur = self.cache_get(key, max_age_days=400) or {'calls': 0, 'input': 0, 'output': 0, 'cached': 0}
            cur = {'calls': cur['calls'] + 1, 'input': cur['input'] + int(inp or 0), 'output': cur['output'] + int(out or 0),
                   'cached': cur['cached'] + int(cached or 0)}
            self.cache_set(key, cur)

    def list_usage(self, days=7):
        rows = self._q("SELECT key, value FROM cache WHERE key LIKE 'usage:%' ORDER BY key DESC LIMIT 200")
        out = []
        for r in rows:
            _, day, model = r['key'].split(':', 2)
            out.append(dict(json.loads(r['value']), day=day, model=model))
        keep = sorted({o['day'] for o in out}, reverse=True)[:days]
        return [o for o in out if o['day'] in keep]

    def set_setting(self, key, value, actor='admin'):
        value = coerce(key, value)
        old = self.get_setting(key)
        self._x('INSERT INTO settings(key, value, updated_by, updated_at) VALUES(?,?,?,?) '
                'ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_by=excluded.updated_by, updated_at=excluded.updated_at',
                (key, json.dumps(value), actor, _now()))
        self._settings = None
        if old != value:
            self.audit(actor, 'setting.changed', key, {'from': old, 'to': value})
        return value

    # ── templates ────────────────────────────────────────────────────────────
    def get_template(self, key, version=None):
        if version is None:
            act = self._q('SELECT version FROM template_active WHERE key=?', (key,), one=True)
            if not act:
                return None
            version = act['version']
        row = self._q('SELECT * FROM templates WHERE key=? AND version=?', (key, version), one=True)
        if row:
            row['meta'] = json.loads(row['meta'] or '{}')
        return row

    def list_templates(self):
        rows = self._q('SELECT t.key, t.kind, t.title, t.subject, t.version, t.created_by, t.created_at, '
                       '(SELECT COUNT(*) FROM templates x WHERE x.key=t.key) AS versions '
                       'FROM templates t JOIN template_active a ON a.key=t.key AND a.version=t.version ORDER BY t.kind, t.key')
        return rows

    def template_history(self, key):
        act = self._q('SELECT version FROM template_active WHERE key=?', (key,), one=True)
        rows = self._q('SELECT version, created_by, created_at, note FROM templates WHERE key=? ORDER BY version DESC', (key,))
        for r in rows:
            r['active'] = bool(act and act['version'] == r['version'])
        return rows

    def save_template(self, key, body, *, kind=None, title=None, subject=None, meta=None,
                      actor='admin', note='', activate=True) -> int:
        with self._lock:
            cur = self.get_template(key)
            last = self._q('SELECT MAX(version) AS v FROM templates WHERE key=?', (key,), one=True)
            version = int((last or {}).get('v') or 0) + 1
            kind = kind or (cur or {}).get('kind') or 'email'
            title = title if title is not None else (cur or {}).get('title')
            meta = meta if meta is not None else (cur or {}).get('meta') or {}
            self._x('INSERT INTO templates(key, version, kind, title, subject, body, meta, created_by, created_at, note) '
                    'VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (key, version, kind, title, subject, body, json.dumps(meta), actor, _now(), note))
            if activate:
                self.activate_template(key, version, actor, audit=False)
            self.audit(actor, 'template.saved', key, {'version': version, 'activated': activate, 'note': note})
            return version

    def activate_template(self, key, version, actor='admin', audit=True):
        if not self._q('SELECT 1 FROM templates WHERE key=? AND version=?', (key, version), one=True):
            raise ValueError(f'{key} has no version {version}')
        self._x('INSERT INTO template_active(key, version, updated_by, updated_at) VALUES(?,?,?,?) '
                'ON CONFLICT(key) DO UPDATE SET version=excluded.version, updated_by=excluded.updated_by, updated_at=excluded.updated_at',
                (key, int(version), actor, _now()))
        if audit:
            self.audit(actor, 'template.activated', key, {'version': version})

    def seed_templates(self, defaults: dict):
        for key, t in defaults.items():
            if not self._q('SELECT 1 FROM template_active WHERE key=?', (key,), one=True):
                self.save_template(key, t['body'], kind=t['kind'], title=t.get('title'), subject=t.get('subject'),
                                   meta=t.get('meta') or {}, actor='system', note='Default', activate=True)
        try:                                        # earlier default wordings nobody edited move to the current default
            from app.core.default_templates import SUPERSEDED_DEFAULTS
        except ImportError:
            SUPERSEDED_DEFAULTS = {}
        for key, olds in SUPERSEDED_DEFAULTS.items():
            cur, new = self.get_template(key), defaults.get(key)
            if cur and new and cur.get('body', '').strip() in [o.strip() for o in olds] and cur['body'].strip() != new['body'].strip():
                self.save_template(key, new['body'], kind=new['kind'], title=new.get('title'), subject=new.get('subject'),
                                   meta=new.get('meta') or {}, actor='system', note='Updated default', activate=True)

    # ── audit ────────────────────────────────────────────────────────────────
    def audit(self, actor, action, target='', details=None):
        self._x('INSERT INTO audit_log(ts, actor, action, target, details) VALUES(?,?,?,?,?)',
                (_now(), str(actor or 'system'), action, str(target or ''), json.dumps(details or {}, default=str)))

    def list_audit(self, limit=200, prefix=None):
        if prefix:
            rows = self._q('SELECT * FROM audit_log WHERE action LIKE ? ORDER BY id DESC LIMIT ?', (prefix + '%', limit))
        else:
            rows = self._q('SELECT * FROM audit_log ORDER BY id DESC LIMIT ?', (limit,))
        for r in rows:
            r['details'] = json.loads(r['details'] or '{}')
        return rows

    # ── approvals (DC8 provisional artists, DC6 coordinator requests) ────────
    def add_approval(self, kind, ref_id, payload, requested_by):
        aid = self._x('INSERT INTO approvals(kind, ref_id, payload, requested_by, requested_at) VALUES(?,?,?,?,?)',
                      (kind, str(ref_id or ''), json.dumps(payload or {}, default=str), str(requested_by or ''), _now()))
        self.audit(requested_by, f'approval.requested', f'{kind}:{ref_id}', payload)
        return aid

    def list_approvals(self, status='pending'):
        rows = self._q('SELECT * FROM approvals WHERE (?="all" OR status=?) ORDER BY id DESC LIMIT 300', (status, status))
        for r in rows:
            r['payload'] = json.loads(r['payload'] or '{}')
        return rows

    def get_approval(self, aid):
        r = self._q('SELECT * FROM approvals WHERE id=?', (aid,), one=True)
        if r:
            r['payload'] = json.loads(r['payload'] or '{}')
        return r

    def decide_approval(self, aid, status, actor, note=''):
        self._x('UPDATE approvals SET status=?, decided_by=?, decided_at=?, note=? WHERE id=?', (status, actor, _now(), note, aid))
        self.audit(actor, f'approval.{status}', str(aid), {'note': note})

    # ── program coordinators (DC6, DC14) ─────────────────────────────────────
    def add_program_coordinators(self, request_id, event_ids, coordinators, actor):
        for c in coordinators or []:
            self._x('INSERT INTO program_coordinators(apr_request_id, event_ids, uid, name, email, phone, chapter, role, added_by, added_at) '
                    'VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (request_id, ','.join(str(e) for e in event_ids), str(c.get('uid') or ''), c.get('name'), c.get('email'),
                     c.get('phone'), c.get('chapter'), c.get('role'), actor, _now()))

    def get_program_coordinators(self, request_id):
        return self._q('SELECT * FROM program_coordinators WHERE apr_request_id=? ORDER BY id', (request_id,))

    # ── directory flags (DC3) ────────────────────────────────────────────────
    def list_flags(self, entity=None):
        if entity:
            return self._q('SELECT * FROM directory_flags WHERE entity=? ORDER BY name', (entity,))
        return self._q('SELECT * FROM directory_flags ORDER BY entity, name')

    def add_flag(self, entity, name, flag, ref_id=None, art_form=None, note='', source='admin', actor='admin'):
        fid = self._x('INSERT INTO directory_flags(entity, ref_id, name, art_form, flag, note, source, updated_by, updated_at) '
                      'VALUES(?,?,?,?,?,?,?,?,?)', (entity, str(ref_id or ''), name, art_form, flag, note, source, actor, _now()))
        self.audit(actor, 'flag.added', f'{entity}:{name}', {'flag': flag, 'note': note})
        return fid

    def remove_flag(self, fid, actor='admin'):
        self._x('DELETE FROM directory_flags WHERE id=?', (fid,))
        self.audit(actor, 'flag.removed', str(fid))

    def seed_flags(self, flags):
        if self.get_setting('seed.flags_done', False):
            return
        for f in flags:
            self.add_flag('artist', f['name'], f.get('flag', 'deceased'), art_form=f.get('art_form'),
                          note=f.get('note', ''), source='seed', actor='system')
        self.set_setting('seed.flags_done', True, 'system')

    # ── cache ────────────────────────────────────────────────────────────────
    def cache_get(self, key, max_age_days=30):
        r = self._q('SELECT value, fetched_at FROM cache WHERE key=?', (key,), one=True)
        if r and time.time() - (r['fetched_at'] or 0) < max_age_days * 86400:
            return json.loads(r['value'])
        return None

    def cache_set(self, key, value):
        self._x('INSERT INTO cache(key, value, fetched_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET '
                'value=excluded.value, fetched_at=excluded.fetched_at', (key, json.dumps(value, default=str), time.time()))

    # ── conversations ────────────────────────────────────────────────────────
    def load_conversation(self, cid):
        r = self._q('SELECT state FROM conversations WHERE id=?', (cid,), one=True)
        return json.loads(r['state']) if r else None

    def save_conversation(self, cid, user_email, state: dict):
        self._x('INSERT INTO conversations(id, user_email, state, updated_at) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET '
                'user_email=excluded.user_email, state=excluded.state, updated_at=excluded.updated_at',
                (cid, user_email or '', json.dumps(state, default=str), time.time()))

    def recent_conversations(self, user_email, limit=8):
        rows = self._q('SELECT id, state, updated_at FROM conversations WHERE user_email=? ORDER BY updated_at DESC LIMIT ?',
                       (user_email or '', limit))
        out = []
        for r in rows:
            st = json.loads(r['state'])
            d = st.get('draft') or {}
            out.append({'id': r['id'], 'updated_at': r['updated_at'], 'title': d.get('title') or
                        ((d.get('main_artist') or {}).get('name')) or 'Untitled program',
                        'program_type': d.get('program_type'), 'events': len(d.get('events') or []),
                        'apr': (d.get('outputs') or {}).get('apr', {}).get('number')})
        return out

    def purge_conversations(self, older_than_days=21):
        self._x('DELETE FROM conversations WHERE updated_at < ?', (time.time() - older_than_days * 86400,))

    # ── one-time login codes ─────────────────────────────────────────────────
    @staticmethod
    def _hash(code, email):
        return hashlib.sha256(f'{email.lower()}:{code}'.encode()).hexdigest()

    def set_login_code(self, email, code, ttl=600):
        self._x('INSERT INTO login_codes(email, code_hash, expires, attempts) VALUES(?,?,?,0) ON CONFLICT(email) DO UPDATE SET '
                'code_hash=excluded.code_hash, expires=excluded.expires, attempts=0',
                (email.lower(), self._hash(code, email), time.time() + ttl))

    def check_login_code(self, email, code) -> bool:
        r = self._q('SELECT * FROM login_codes WHERE email=?', (email.lower(),), one=True)
        if not r or r['expires'] < time.time() or r['attempts'] >= 5:
            return False
        ok = hmac.compare_digest(r['code_hash'], self._hash(str(code).strip(), email))
        if ok:
            self._x('DELETE FROM login_codes WHERE email=?', (email.lower(),))
        else:
            self._x('UPDATE login_codes SET attempts=attempts+1 WHERE email=?', (email.lower(),))
        return ok
