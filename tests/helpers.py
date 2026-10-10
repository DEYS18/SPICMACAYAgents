"""Test doubles: a SQLite database with the portal's schema (only the tables the assistant
touches) seeded with realistic rows, and a scripted stand-in for the OpenAI client."""
import json
import sqlite3
import sys
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SCHEMA = """
CREATE TABLE artists_list (tid INTEGER PRIMARY KEY, name TEXT, art_form TEXT, `On` TEXT, artist_type TEXT, artist_grade TEXT,
  select_award TEXT, city TEXT, enter_state TEXT, pincode TEXT, country_id INTEGER DEFAULT 1, phone TEXT, address TEXT, email TEXT,
  create_password TEXT, bank_name TEXT, account_number TEXT, ifsc_code TEXT, added_by TEXT, added_date TEXT, updated_by TEXT,
  dt_updated TEXT, status INTEGER NOT NULL DEFAULT 1, cancelled_cheque TEXT);
CREATE TABLE institution_list (sid INTEGER PRIMARY KEY, institution_name TEXT NOT NULL, state TEXT NOT NULL DEFAULT '',
  country_id INTEGER NOT NULL DEFAULT 1, pincode TEXT, phone TEXT, email TEXT, address TEXT, bank_name TEXT, account_number TEXT,
  enter_ifsc_code TEXT, name_of_the_coordinator TEXT, institution_coordinator_designation TEXT, added_by INTEGER, added_date TEXT,
  updated_by INTEGER, dt_updated TEXT, status INTEGER NOT NULL DEFAULT 1, create_password TEXT NOT NULL DEFAULT '', city TEXT,
  cancelled_cheque TEXT);
CREATE TABLE event_list (id INTEGER PRIMARY KEY, title TEXT, image TEXT, start_date TEXT, end_date TEXT, event_time TEXT,
  end_time TEXT, event_category TEXT, state TEXT, address TEXT, summary TEXT, added_date TEXT, updated_date TEXT, added_by TEXT,
  updated_by TEXT, status INTEGER NOT NULL, city TEXT, institution TEXT, artist TEXT, accompanying_artist TEXT,
  event_status TEXT NOT NULL, venue TEXT, budget REAL, poww INTEGER NOT NULL DEFAULT 0, attendees TEXT, amount_paid TEXT,
  partially_amt REAL, expenses_incurred TEXT, added_from INTEGER NOT NULL DEFAULT 0, fy TEXT);
CREATE TABLE event_module (tid INTEGER PRIMARY KEY, name TEXT, status INTEGER NOT NULL DEFAULT 1);
CREATE TABLE event_series (id INTEGER PRIMARY KEY, event_type TEXT, title TEXT, image TEXT, start_date TEXT, end_date TEXT,
  event_time TEXT, event_series TEXT, state TEXT, city TEXT, address TEXT, summary TEXT, added_date TEXT, updated_date TEXT,
  added_by TEXT, updated_by TEXT, status INTEGER NOT NULL, institution TEXT, event_id TEXT, event_status TEXT NOT NULL,
  end_time TEXT, budget REAL, poww INTEGER NOT NULL, amount_paid TEXT, partially_amt REAL);
CREATE TABLE apr_payment_request (id INTEGER PRIMARY KEY, request_id TEXT NOT NULL, artist_id TEXT NOT NULL, artist_type TEXT,
  event_id TEXT NOT NULL, custom_apr TEXT NOT NULL, event_date TEXT NOT NULL, time_duration TEXT NOT NULL, institution TEXT NOT NULL,
  chapter TEXT NOT NULL, students TEXT NOT NULL, fc TEXT NOT NULL, created_by TEXT NOT NULL, dt_created TEXT NOT NULL,
  del INTEGER NOT NULL, updated_by TEXT NOT NULL, dt_updated TEXT);
CREATE TABLE apr_payment_request2 (id INTEGER PRIMARY KEY, event_id TEXT, type_of_artist TEXT, artist TEXT, custom_apr TEXT,
  created_by TEXT, dt_created TEXT);
CREATE TABLE apr_event_receipt (id INTEGER PRIMARY KEY, apr_id INTEGER, event_id INTEGER, upload_receipt TEXT, added_by TEXT,
  updated_by TEXT, added_date TEXT, updated_date TEXT, upload_receipt_expenses TEXT, type_of_receipt TEXT NOT NULL, event_status TEXT);
CREATE TABLE users_field_data (uid INTEGER PRIMARY KEY, name TEXT, mail TEXT, status INTEGER);
CREATE TABLE custom_apr (id INTEGER PRIMARY KEY AUTOINCREMENT, coordinators_id TEXT, event_series TEXT, eventgroup TEXT, event_id TEXT,
  donation_type TEXT, amount_paid TEXT, additional_message TEXT, school_additional_message TEXT, created_by TEXT, updated_by TEXT,
  dt_created TEXT, dt_updated TEXT, del INTEGER NOT NULL DEFAULT 0, final_submit INTEGER NOT NULL DEFAULT 0,
  added_by TEXT NOT NULL DEFAULT 'apr', event_status TEXT, apr_pdf_name TEXT, apr_status TEXT, apr_remarks TEXT, apr_updated_by TEXT,
  apr_dt_updated TEXT, apr_finance_status TEXT, apr_finance_remarks TEXT, apr_finance_updated_by TEXT, apr_finance_dt_updated TEXT);
CREATE TABLE taxonomy_term_field_data (tid INTEGER PRIMARY KEY, vid TEXT, name TEXT, langcode TEXT DEFAULT 'en');
"""
# Like production (MariaDB 10.11, strict mode): these tables are latin1 (Windows-1252), so a write of anything
# outside it fails with error 1366 instead of being stored.
LATIN1_TABLES = {'event_list', 'event_series', 'artists_list', 'institution_list', 'apr_payment_request', 'apr_payment_request2',
                 'event_module', 'payment_artist_detail'}
PORTAL_MODULES = [(1, 'Cinema Classic'), (2, 'Heritage Walk'), (3, 'Holistic Food'), (4, 'Lecture Demonstration'), (5, 'Nature Walk'),
                  (6, 'Talk'), (7, 'Virtual Interactions'), (8, 'Workshop Demonstration'), (9, 'Workshops'), (11, 'Yoga & Meditation'),
                  (12, 'Virtual Demonstrations'), (13, 'Full Concert')]
PROGRAM_TYPES = [(288, 'Circuit'), (289, 'Single Event'), (290, 'Convention'), (291, 'Viraasat Series')]


def strict_latin1(sql, params):
    import re
    m = re.match(r"\s*(?:INSERT|UPDATE|REPLACE)\s+(?:INTO\s+)?`?(\w+)", sql or '', re.I)
    if m and m.group(1).lower() in LATIN1_TABLES:
        for v in params or ():
            if isinstance(v, str):
                try:
                    v.encode('cp1252')
                except UnicodeEncodeError:
                    raise RuntimeError(f"1366 (22007): Incorrect string value {v[:20]!r} for a latin1 column of {m.group(1)}")

ARTISTS = [
    (1, 'Ronu Majumdar', 'Flute', 'Mumbai', 'Maharashtra', 'ronu@example.com', '9820320131', '', '', ''),
    (2, 'Ajeet Pathak', 'Tabla', 'Mumbai', 'Maharashtra', '', '', '', '', ''),
    (3, 'Ustad Shahid Parvez Khan', 'Sitar', 'Pune', 'Maharashtra', '', '', 'SBI', '12345678901', 'SBIN0011781'),
    (4, 'Pt. Ravi Shankar', 'Sitar', 'New Delhi', 'Delhi', '', '', '', '', ''),
    (5, 'Ravi Shankar Mishra', 'Tabla', 'Varanasi', 'Uttar Pradesh', '', '', '', '', ''),
    (6, 'Padma Shri Ustad Faiyaz Wasifuddin Dagar', 'Dhrupad', 'New Delhi', 'Delhi', '', '', '', '', ''),
    (7, 'Vidushi Ashwini Bhide Deshpande', 'Vocal, Harmonium', 'Mumbai', 'Maharashtra', '', '', '', '', ''),
    (8, 'Kalpesh Sachala', 'Flute', 'Mumbai', 'Maharashtra', '', '', '', '', ''),
    (9, 'Uma Dogra', 'Kathak', 'Mumbai', 'Maharashtra', 'uma@example.com', '', '', '', ''),
]
INSTITUTIONS = [
    (1, 'Indian Institute of Technology Bombay', 'Mumbai', 'Maharashtra', 'spicmacay@iitb.ac.in', 'Prof. Rao', '022-2576'),
    (2, 'Delhi Public School', 'Nashik', 'Maharashtra', 'principal@dpsnashik.in', 'Mrs. Kulkarni', '0253-2222'),
    (3, 'APS Ahmednagar', 'Ahmednagar', 'Maharashtra', '', 'Principal', '0241-111'),
    (4, 'Birla Institute of Technology and Science, Pilani', 'Pilani', 'Rajasthan', 'bits@pilani.in', '', ''),
    (5, 'BITS Pilani Goa Campus', 'Goa', 'Goa', 'bits@goa.in', '', ''),
    (6, 'BITS Pilani Hyderabad Campus', 'Hyderabad', 'Telangana', 'bits@hyd.in', '', ''),
    (7, 'Kendriya Vidyalaya No. 1', 'Colaba', 'Maharashtra', 'kv1@colaba.in', '', ''),
    (8, 'Kendriya Vidyalaya No. 2', 'Colaba', 'Maharashtra', 'kv2@colaba.in', '', ''),
    (9, "St Xavier's College", 'Mumbai', 'Maharashtra', 'xaviers@example.com', 'Fr. DSouza', ''),
]


def _tr(sql):
    return sql.replace('%s', '?')


class _Cur:
    def __init__(self, cur, fail_on):
        self.c, self.fail_on = cur, fail_on

    def execute(self, sql, params=()):
        if self.fail_on and self.fail_on in sql:
            raise RuntimeError('simulated database failure')
        strict_latin1(sql, params)
        self.c.execute(_tr(sql), tuple(params or ()))

    @property
    def lastrowid(self):
        return self.c.lastrowid

    def fetchall(self):
        return [dict(r) for r in self.c.fetchall()]

    def fetchone(self):
        r = self.c.fetchone()
        return dict(r) if r else None


class FakeDB:
    def __init__(self):
        self.conn = sqlite3.connect(':memory:', check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.create_function('GET_LOCK', 2, lambda n, t: 1)
        self.conn.create_function('RELEASE_LOCK', 1, lambda n: 1)
        import re as _re
        self.conn.create_function('REGEXP', 2, lambda pat, val: 1 if val is not None and _re.search(pat, str(val)) else 0)
        self.conn.executescript(SCHEMA)
        self.lock = threading.RLock()
        self.fail_on = None

    def fetch_all(self, sql, params=None):
        with self.lock:
            return [dict(r) for r in self.conn.execute(_tr(sql), tuple(params or ())).fetchall()]

    def fetch_one(self, sql, params=None):
        rows = self.fetch_all(sql, params)
        return rows[0] if rows else None

    def execute_query(self, sql, params=None, commit=False):
        try:
            strict_latin1(sql, params)
            with self.lock:
                cur = self.conn.execute(_tr(sql), tuple(params or ()))
                if commit:
                    return {'success': True, 'lastrowid': cur.lastrowid, 'rowcount': cur.rowcount}
                return {'success': True, 'results': [dict(r) for r in cur.fetchall()], 'rowcount': cur.rowcount}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @contextmanager
    def transaction(self):
        with self.lock:
            self.conn.execute('BEGIN')
            try:
                yield _Cur(self.conn.cursor(), self.fail_on)
                self.conn.execute('COMMIT')
            except Exception:
                self.conn.execute('ROLLBACK')
                raise

    def count(self, table):
        return self.fetch_one(f'SELECT COUNT(*) AS n FROM {table}')['n']


def seed(db):
    for t in ARTISTS:
        db.execute_query('INSERT INTO artists_list (tid, name, art_form, city, enter_state, email, phone, bank_name, account_number, '
                         'ifsc_code, status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1)', t, commit=True)
    for sid, name, city, state, email, coord, phone in INSTITUTIONS:
        db.execute_query('INSERT INTO institution_list (sid, institution_name, city, state, email, name_of_the_coordinator, phone, status) '
                         'VALUES (%s,%s,%s,%s,%s,%s,%s,1)', (sid, name, city, state, email, coord, phone), commit=True)
    for tid, name in PORTAL_MODULES:
        db.execute_query('INSERT INTO event_module (tid, name, status) VALUES (%s,%s,1)', (tid, name), commit=True)
    for tid, name in PROGRAM_TYPES:
        db.execute_query("INSERT INTO taxonomy_term_field_data (tid, vid, name) VALUES (%s,'events',%s)", (tid, name), commit=True)
    db.execute_query("INSERT INTO custom_apr (id, coordinators_id, event_series, eventgroup, event_id, created_by, dt_created, final_submit, "
                     "added_by) VALUES (207, '51', '288', '116', '9583,9584', '51', '2026-03-05', 1, 'event_list')", commit=True)
    for uid, name, mail in [(15, 'sabyasachi', 'sabyasachi@spicmacay.com'), (22, 'banashree', 'banashree.roy@spicmacay.com')]:
        db.execute_query('INSERT INTO users_field_data (uid, name, mail, status) VALUES (%s,%s,%s,1)', (uid, name, mail), commit=True)
    db.execute_query("INSERT INTO apr_payment_request2 (id, event_id, custom_apr) VALUES (1, '159', '171')", commit=True)
    return db


class FakeLLM:
    """Replays scripted turns. Each step is {'tool_calls': [(name, args), ...]} or {'content': '...'};
    every request is recorded so tests can check what the model was offered."""
    def __init__(self, script=None):
        self.script, self.calls = list(script or []), []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def push(self, *steps):
        self.script.extend(steps)

    def _create(self, **kw):
        self.calls.append(kw)
        step = self.script.pop(0) if self.script else {'content': 'OK.'}
        if callable(step):
            step = step(kw)
        tcs = [SimpleNamespace(id=f'call_{len(self.calls)}_{i}', type='function',
                               function=SimpleNamespace(name=n, arguments=json.dumps(a)))
               for i, (n, a) in enumerate(step.get('tool_calls', []))]
        msg = SimpleNamespace(content=step.get('content'), tool_calls=tcs or None)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def build_test_services(llm=None, tmp=None):
    from app.agents.services import build_services
    from app.services.event_service import EventService
    tmp = tmp or tempfile.mkdtemp(prefix='smtest-')
    db = seed(FakeDB())
    s = build_services(db=db, event_service=EventService(db), instance_dir=tmp, smtp={}, openai_key='')
    if llm is not None:
        s.llm_factory = lambda: llm
    s.gov.set_setting('artists.acg_email', ['acg@spicmacay.com'], 'test')
    return s, db, tmp
