#!/usr/bin/env python3
"""
End-to-end check of the APR Assistant against your real services, safely. Run it on the machine that
hosts the app, from the project folder, with the same .env:

  python e2e_check.py                          configuration, OpenAI, database (read-only), email login
  python e2e_check.py --posters a.jpg b.jpg    also read real posters with the vision model and build the batch plan
  python e2e_check.py --posters ... --file     also file them into an in-memory COPY of the portal and write the APR PDFs
  python e2e_check.py --voice                  Hindi speech round trip: text to speech to text
  python e2e_check.py --compare-models gpt-5.5,gpt-5.4-mini   the same short conversation on each model
  python e2e_check.py --send-test-email you@spicmacay.com     one real email through your SMTP relay

It never writes to your database (the session is READ ONLY and filing uses an in-memory copy), never emails
anyone unless --send-test-email is given, and never prints secrets. Results: e2e_output/e2e_report.json.
"""
import argparse
import base64
import json
import os
import re
import shutil
import smtplib
import sys
import time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
OUT = ROOT / 'e2e_output'
REPORT = {'checks': []}
PLACEHOLDERS = ('your-secret-key', 'change-in-production', 'your_secure_password', 'yourdomain.com', 'your_email', 'your_app_password')
SCRIPT = ['I want to file a circuit APR: lecture demonstrations by Pt Ronu Mazumdar, with Ajeet Pathak on tabla.',
          'The stops are APS Ahmednagar on 14 Feb and DPS Nashik on 16 Feb, both 10 am to 12 pm.',
          "That's everything. Please review it."]


def short(e):
    s = re.sub(r'sk-[A-Za-z0-9_\-]{6,}', 'sk-...', str(e))
    for var in ('DB_PASSWORD', 'SMTP_PASSWORD', 'OPENAI_API_KEY'):
        if os.getenv(var):
            s = s.replace(os.getenv(var), '***')
    return s[:300]


def record(area, ok, detail, data=None):
    mark = {True: 'PASS', False: 'FAIL', None: 'NOTE'}[ok]
    print(f'[{mark}] {area}: {detail}')
    REPORT['checks'].append(dict({'area': area, 'result': mark, 'detail': detail}, **({'data': data} if data is not None else {})))


# ── 1. configuration ─────────────────────────────────────────────────────────
def review_env(text, env):
    findings, seen = [], {}
    for n, line in enumerate(text.splitlines(), 1):
        m = re.match(r'\s*([A-Z0-9_]+)\s*=', line)
        if m:
            seen.setdefault(m.group(1), []).append(n)
    dups = {k: v for k, v in seen.items() if len(v) > 1}
    if dups:
        findings.append(('warn', 'Defined more than once, so the last one wins: ' +
                         ', '.join(f"{k} (lines {', '.join(map(str, v))})" for k, v in dups.items())))
    sk = env.get('SECRET_KEY') or ''
    if len(sk) < 32 or any(p in sk for p in PLACEHOLDERS):
        findings.append(('fail', 'SECRET_KEY is a placeholder or too short, so sessions and the admin console are not safe. '
                                 'Generate one: python -c "import secrets; print(secrets.token_hex(32))"'))
    if env.get('DB_USER') == 'root':
        findings.append(('warn', 'The app connects to MySQL as root. Use a dedicated user with SELECT, INSERT and UPDATE on the portal tables.'))
    if env.get('DB_PASSWORD') in ('', 'root', 'password', 'your_secure_password'):
        findings.append(('warn', 'The database password is weak or a placeholder.'))
    unused = [k for k in seen if k.startswith('MYSQL_')]
    if unused:
        findings.append(('warn', f"{', '.join(unused)} are not read by the app (it uses DB_*) but hold credentials: remove them."))
    if (env.get('SEND_WEEKLY_REPORTS_ON_APR_CREATE') or '').lower() == 'true':
        findings.append(('warn', 'SEND_WEEKLY_REPORTS_ON_APR_CREATE=true makes the classic assistant email both weekly reports on every APR. Set it to false.'))
    if any(p in (env.get('ALLOWED_ORIGINS') or '') for p in PLACEHOLDERS):
        findings.append(('warn', 'ALLOWED_ORIGINS still contains a placeholder domain.'))
    if (env.get('AUTH_MODE') or 'open') == 'open':
        findings.append(('warn', 'AUTH_MODE is open: anyone with the link can use the assistant. Use AUTH_MODE=email_otp in production.'))
    if not env.get('ADMIN_PASSWORD') and not env.get('ADMIN_EMAILS'):
        findings.append(('warn', 'Neither ADMIN_PASSWORD nor ADMIN_EMAILS is set, so the admin console is locked.'))
    if not (env.get('SMTP_HOST') and env.get('SMTP_USER') and env.get('SMTP_PASSWORD')):
        findings.append(('warn', 'SMTP is incomplete, so emails are saved as files instead of being sent.'))
    if env.get('FLASK_ENV'):
        findings.append(('note', 'FLASK_ENV is ignored by current Flask versions; DEBUG controls debug mode.'))
    return findings


def check_config(env_path):
    if not env_path.exists():
        record('Configuration', False, f'No .env found at {env_path}')
        return {}
    from dotenv import dotenv_values
    env = {k: (v or '') for k, v in dotenv_values(env_path).items()}
    for level, msg in review_env(env_path.read_text(encoding='utf-8', errors='replace'), env):
        record('Configuration', {'fail': False, 'warn': None, 'note': None}[level], msg)
    record('Configuration', None, f"Effective database: {env.get('DB_USER')}@{env.get('DB_HOST')}:{env.get('DB_PORT') or 3306}/{env.get('DB_NAME')}")
    return env


# ── 2. OpenAI ────────────────────────────────────────────────────────────────
def check_openai(client, gov):
    from app.agents import llm
    models = {'conversation': gov.get_setting('assistant.model'), 'posters and cheques': gov.get_setting('assistant.vision_model'),
              'speech to text': gov.get_setting('voice.stt_model'), 'text to speech': gov.get_setting('voice.tts_model')}
    for role, m in models.items():
        try:
            client.models.retrieve(m)
            record('OpenAI model', True, f'{role}: {m} is available to this key')
        except Exception as e:
            record('OpenAI model', False, f'{role}: {m}: {short(e)}')
    m, t0 = models['conversation'], time.time()
    tools = [{'type': 'function', 'function': {'name': 'find_artist', 'description': 'Search the artist directory.',
                                               'parameters': {'type': 'object', 'properties': {'name': {'type': 'string'},
                                                              'role': {'type': 'string', 'enum': ['main', 'accompanying']}},
                                                              'required': ['name']}}}]
    try:
        r = llm.complete(client, model=m, system='You register SPIC MACAY programs. Always look artists up with find_artist.',
                         messages=[{'role': 'user', 'content': 'Concert by Pt Ronu Mazumdar next Friday'}], tools=tools,
                         effort=gov.get_setting('assistant.reasoning_effort', 'low'), api=gov.get_setting('assistant.api', 'auto'))
        ok = any(c['name'] == 'find_artist' for c in r.tool_calls)
        dropped = llm.dropped_params(m)
        record('OpenAI tool calling', ok, f"{m} {'called find_artist' if ok else 'did not call the tool'} in {time.time() - t0:.1f}s, "
                                          f"tokens in/out {llm.usage_numbers(r.usage)[:2]}" +
               (f'; parameters it rejected (now dropped automatically): {dropped}' if dropped else ''))
    except Exception as e:
        record('OpenAI tool calling', False, f'{m}: {short(e)}')


# ── 3. database, read-only ───────────────────────────────────────────────────
def q(cur, sql, params=()):
    if not sql.lstrip().upper().startswith('SELECT'):
        raise ValueError('this check only runs SELECT statements')
    cur.execute(sql, params)
    return cur.fetchall()


def check_db():
    try:
        import mysql.connector
        conn = mysql.connector.connect(host=os.getenv('DB_HOST'), port=int(os.getenv('DB_PORT') or 3306), user=os.getenv('DB_USER'),
                                       password=os.getenv('DB_PASSWORD'), database=os.getenv('DB_NAME'), connection_timeout=10)
        cur = conn.cursor(dictionary=True, buffered=True)
        cur.execute('SET SESSION TRANSACTION READ ONLY')
    except Exception as e:
        record('Database', False, f'Could not connect: {short(e)}')
        return None, None
    try:
        counts = {t: q(cur, f'SELECT COUNT(*) AS n FROM {t}')[0]['n'] for t in
                  ('artists_list', 'institution_list', 'event_list', 'apr_payment_request', 'event_series', 'users_field_data', 'event_module')}
        record('Database', True, 'Connected read-only. Rows: ' + ', '.join(f'{k} {v}' for k, v in counts.items()))
        mods = q(cur, 'SELECT tid, name FROM event_module ORDER BY tid')
        record('Assumption: modules', None, 'event_module: ' + ', '.join(f"{m['tid']}={m['name']}" for m in mods), mods)
        cats = q(cur, 'SELECT event_category AS v, COUNT(*) AS n FROM event_list GROUP BY event_category ORDER BY n DESC LIMIT 12')
        ids, total = sum(c['n'] for c in cats if str(c['v'] or '').isdigit()), sum(c['n'] for c in cats) or 1
        record('Assumption: module stored as its id', ids / total > 0.5, f'{ids * 100 // total}% of the commonest event_category values are ids', cats)
        newest = q(cur, 'SELECT institution FROM event_list ORDER BY id DESC LIMIT 50')
        share = sum(1 for r in newest if not str(r['institution'] or '').isdigit()) * 100 // max(len(newest), 1)
        record('Portal convention: institution stored by name', share > 50, f'{share}% of the 50 newest events store the institution name, as the assistant does')
        mx = q(cur, 'SELECT MAX(id) AS m, COUNT(*) AS n FROM custom_apr')[0]
        record('Portal convention: APRs in custom_apr', True, f"{mx['n']} APRs; the newest is {mx['m']}, so the next APR the assistant files is {int(mx['m'] or 0) + 1}")
        types = q(cur, "SELECT tid, name FROM taxonomy_term_field_data WHERE vid = 'events' ORDER BY tid")
        record('Portal convention: program types', bool(types), 'taxonomy terms: ' + (', '.join(f"{t['tid']}={t['name']}" for t in types) or 'none found'))
        collations = q(cur, "SELECT table_name AS t, table_collation AS c FROM information_schema.tables WHERE table_schema = DATABASE() "
                            "AND table_name IN ('event_list', 'event_series', 'artists_list', 'institution_list', 'custom_apr')")
        record('Character sets', None, ', '.join(f"{c['t']}={c['c']}" for c in collations) + ' (text for latin1 tables is made latin1-safe)')
        twins = q(cur, 'SELECT institution_name AS n, COUNT(DISTINCT city) AS c FROM institution_list WHERE status = 1 '
                       'GROUP BY institution_name HAVING c > 1 ORDER BY c DESC LIMIT 5')
        record('Directory', None, 'Institution names found in several cities (matched by city, address or campus): ' +
               (', '.join(f"{t['n']} ({t['c']})" for t in twins) or 'none'))
    except Exception as e:
        record('Database', False, f'Check failed: {short(e)}')
    return conn, cur


def memory_copy(cur):
    """The portal's directory and recent events copied into an in-memory database, so filing can be tested for real."""
    from helpers import FakeDB, seed
    db = FakeDB()
    if cur is None:
        from real_world import seed_real_world
        seed_real_world(seed(db))
        record('Directory copy', None, 'No database connection, so the sample directory from the tests is used')
        return db
    ins = lambda sql, rows: [db.execute_query(sql, tuple('' if v is None else str(v) if isinstance(v, date) else v for v in r.values()), commit=True) for r in rows]
    ins('INSERT INTO artists_list (tid, name, art_form, city, enter_state, email, phone, added_by, status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,1)',
        q(cur, 'SELECT tid, name, art_form, city, enter_state, email, phone, added_by FROM artists_list WHERE status = 1'))
    ins('INSERT INTO institution_list (sid, institution_name, city, state, email, phone, address, name_of_the_coordinator, status) '
        'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,1)',
        q(cur, 'SELECT sid, institution_name, city, state, email, phone, address, name_of_the_coordinator FROM institution_list WHERE status = 1'))
    ins('INSERT INTO users_field_data (uid, name, mail, status) VALUES (%s,%s,%s,1)',
        q(cur, "SELECT uid, name, mail FROM users_field_data WHERE status = 1 AND mail IS NOT NULL AND mail <> ''"))
    ins('INSERT INTO event_module (tid, name, status) VALUES (%s,%s,1)', q(cur, 'SELECT tid, name FROM event_module'))
    ins("INSERT INTO event_list (id, start_date, end_date, artist, institution, event_category, status, event_status) VALUES (%s,%s,%s,%s,%s,%s,1,'Completed')",
        q(cur, 'SELECT id, start_date, end_date, artist, institution, event_category FROM event_list WHERE status = 1 AND start_date >= %s',
          ((date.today() - timedelta(days=540)).isoformat(),)))
    digits = [int(r['custom_apr']) for r in q(cur, 'SELECT custom_apr FROM apr_payment_request') if str(r['custom_apr'] or '').isdigit()]
    db.execute_query("INSERT INTO apr_payment_request2 (id, custom_apr) VALUES (1, %s)", (str(max(digits) if digits else 0),), commit=True)
    record('Directory copy', True, f"In-memory copy: {db.count('artists_list')} artists, {db.count('institution_list')} institutions, "
                                   f"{db.count('event_list')} events from the last 18 months")
    return db


def services_on_copy(db, client):
    from app.agents.services import build_services
    from app.core.governance import Governance
    from app.services import pdf_service, poster_service
    from app.services.event_service import EventService
    s = build_services(db=db, event_service=EventService(db), instance_dir=str(OUT / 'instance'), smtp={}, openai_key='')
    s.llm_factory = lambda: client
    real = ROOT / 'instance' / 'governance.db'
    if real.exists():                                   # use the administrators' settings (models, rules)
        for k, v in Governance(str(real)).all_settings().items():
            try:
                s.gov.set_setting(k, v, 'e2e')
            except Exception:
                pass
    s.gov.set_setting('email.dry_run', True, 'e2e')
    pdf_service.EVENT_PHOTOS_DIR = str(OUT / 'event_photos')
    poster_service._ARTIST_PHOTO_DIR = str(OUT / 'artist_photos')
    return s


def _ctx(s):
    from app.agents.state import ConversationState
    from app.skills.base import SkillContext
    st = ConversationState()
    st.draft.add_coordinator({'name': 'E2E check', 'email': 'e2e-check@example.org', 'role': 'filer'})
    return st, SkillContext(s, st, actor={'email': 'e2e-check@example.org'}, via='button')


# ── 4. posters, filing into the copy ────────────────────────────────────────
def check_posters(s, paths, do_file=False):
    from app.skills.batch import BatchPlanner, file_programs, plan_reply, read_posters
    st, ctx = _ctx(s)
    posters = [{'pid': f'p{i}', 'filename': Path(p).name, 'mime': 'image/png' if str(p).lower().endswith('.png') else 'image/jpeg',
                'b64': base64.b64encode(Path(p).read_bytes()).decode()} for i, p in enumerate(paths, 1)]
    t0 = time.time()
    read_posters(ctx, posters)
    secs = time.time() - t0
    for p in posters:
        d = p.get('data') or {}
        record('Poster reading', not p.get('error'), f"{p['filename']}: " + (p['error'] or
               f"{len(d.get('events') or [])} event(s); {(d.get('main_artist') or {}).get('name') or 'several artists'}"))
    (OUT / 'posters_as_read.json').write_text(json.dumps([{'file': p['filename'], 'read': p.get('data')} for p in posters],
                                                         indent=2, ensure_ascii=False), encoding='utf-8')
    plan = BatchPlanner(s).build(posters, [dict(c) for c in st.draft.d['coordinators']])
    st.batch = plan
    record('Batch plan', True, f'{len(posters)} posters read in {secs:.0f}s. ' + plan_reply(plan).replace('**', '').replace('\n\n', ' '))
    for p in plan['programs']:
        record('Batch plan', None, f"{p['title'] or p['type']}: {p['status']}" + (f" (needs: {'; '.join(p['issues'][:3])})" if p['issues'] else ''))
    (OUT / 'batch_plan.json').write_text(json.dumps(plan, indent=2, default=str, ensure_ascii=False), encoding='utf-8')
    if do_file:
        for r in file_programs(ctx, plan, 'each'):
            record('Filing into the copy', r.get('ok'), f"{r['title']}: " + (f"APR {r['apr_number']}" if r.get('ok') else r.get('error', '')))
        (OUT / 'apr_pdfs').mkdir(exist_ok=True)
        for f in (OUT / 'instance' / 'outputs' / 'apr').glob('*.pdf'):
            shutil.copy(f, OUT / 'apr_pdfs' / f.name)
    return plan


# ── 5. models side by side ──────────────────────────────────────────────────
def compare_models(s, models):
    rows = []
    for m in models:
        s.gov.set_setting('assistant.model', m, 'e2e')
        st, _ = _ctx(s)
        before = {(u['day'], u['model']): (u['input'], u['output']) for u in s.gov.list_usage(1)}
        t0, err, reply = time.time(), None, ''
        try:
            for msg in SCRIPT:
                reply = s.orchestrator.run_turn(st, msg, actor={'email': 'e2e-check@example.org'})['reply']
        except Exception as e:
            err = short(e)
        used = [tc['function']['name'] for h in st.history if h.get('tool_calls') for tc in h['tool_calls']]
        after = {(u['day'], u['model']): (u['input'], u['output']) for u in s.gov.list_usage(1)}
        tin = sum(v[0] - before.get(k, (0, 0))[0] for k, v in after.items() if k[1] == m)
        tout = sum(v[1] - before.get(k, (0, 0))[1] for k, v in after.items() if k[1] == m)
        pr = st.draft.progress()
        rows.append({'model': m, 'seconds': round(time.time() - t0, 1), 'draft': f"{pr['done']}/{pr['total']}", 'tool_calls': len(used),
                     'tools': sorted(set(used)), 'input_tokens': tin, 'output_tokens': tout, 'error': err, 'last_reply': reply[:300]})
        record('Model comparison', not err and pr['done'] >= 5, f"{m}: {rows[-1]['seconds']}s for {len(SCRIPT)} messages, draft {rows[-1]['draft']}, "
                                                              f"{len(used)} tool calls, tokens in/out {tin}/{tout}" + (f', error: {err}' if err else ''))
    REPORT['model_comparison'] = rows
    return rows


# ── 6. voice and email ──────────────────────────────────────────────────────
def check_voice(s, key):
    from app.services.voice_service import VoiceService, build_vocabulary_prompt
    v = VoiceService(key, s.setting)
    sentence = 'पंडित रोनू मजूमदार का लेक्चर डेमोंस्ट्रेशन चौदह फरवरी को ए पी एस अहमदनगर में है, तबले पर अजीत पाठक।'
    audio = v.synthesize(sentence, language='hi')
    if not audio:
        record('Voice', False, 'Speech synthesis returned nothing')
        return
    prompt = build_vocabulary_prompt('hi', ['Ronu Majumdar', 'Ajeet Pathak'], ['APS Ahmednagar'])
    for model in dict.fromkeys([s.setting('voice.stt_model'), 'gpt-4o-transcribe']):
        t0 = time.time()
        r = v.transcribe(audio, 'speech.mp3', 'hi', prompt, model=model)
        text = r.get('text') or r.get('error') or ''
        found = [n for n, dev in (('Ronu Majumdar', 'रोनू'), ('Ajeet Pathak', 'अजीत')) if n.lower() in text.lower() or dev in text]
        record('Voice', bool(r.get('success')) and len(found) == 2, f'{model} in {time.time() - t0:.1f}s heard: "{text[:160]}"; names recognised: {found}')


def check_smtp(send_to=None):
    host, user, pw = os.getenv('SMTP_HOST'), os.getenv('SMTP_USER'), os.getenv('SMTP_PASSWORD')
    port = int(os.getenv('SMTP_PORT') or 587)
    if not (host and user and pw):
        record('Email', None, 'SMTP is not configured')
        return
    try:
        server = smtplib.SMTP_SSL(host, port, timeout=20) if port == 465 else smtplib.SMTP(host, port, timeout=20)
        with server:
            if port != 465:
                server.starttls()
            server.login(user, pw)
            record('Email', True, f'Logged in to {host}:{port} (nothing sent)')
            if send_to:
                from email.message import EmailMessage
                msg = EmailMessage()
                msg['Subject'], msg['From'], msg['To'] = 'SPIC MACAY APR Assistant: test email', os.getenv('FROM_EMAIL') or user, send_to
                msg.set_content('This is a test from e2e_check.py. If you can read it, outgoing email works.')
                server.send_message(msg)
                record('Email', True, f'Test email sent to {send_to}')
    except Exception as e:
        record('Email', False, f'{host}:{port}: {short(e)}')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--posters', nargs='*', default=[])
    ap.add_argument('--file', action='store_true', help='file the posters into an in-memory copy and write the APR PDFs')
    ap.add_argument('--voice', action='store_true')
    ap.add_argument('--compare-models', default='')
    ap.add_argument('--send-test-email', default=None)
    a = ap.parse_args(argv)
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    OUT.mkdir(exist_ok=True)
    check_config(ROOT / '.env')
    from app.core.governance import Governance
    real = ROOT / 'instance' / 'governance.db'
    gov = Governance(str(real if real.exists() else OUT / 'settings_probe.db'))
    key = os.getenv('OPENAI_API_KEY') or ''
    client = None
    if key:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=key, timeout=180)
        except ImportError:
            record('OpenAI', False, 'The openai package is not installed (pip install -r requirements.txt)')
        else:
            check_openai(client, gov)
    else:
        record('OpenAI', False, 'OPENAI_API_KEY is not set')
    conn, cur = check_db()
    check_smtp(a.send_test_email)
    if client and (a.posters or a.compare_models or a.voice):
        s = services_on_copy(memory_copy(cur), client)
        if a.posters:
            check_posters(s, a.posters, a.file)
        if a.compare_models:
            compare_models(s, [m.strip() for m in a.compare_models.split(',') if m.strip()])
        if a.voice:
            check_voice(s, key)
    if conn:
        conn.close()
    (OUT / 'e2e_report.json').write_text(json.dumps(REPORT, indent=2, default=str, ensure_ascii=False), encoding='utf-8')
    res = [c['result'] for c in REPORT['checks']]
    print(f"\n{res.count('PASS')} passed, {res.count('FAIL')} failed, {res.count('NOTE')} notes. Full report: {OUT / 'e2e_report.json'}")
    return 1 if 'FAIL' in res else 0


if __name__ == '__main__':
    sys.exit(main())
