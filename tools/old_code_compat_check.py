#!/usr/bin/env python3
"""
Proves that the PREVIOUS version of this app still works with APRs filed by this version.

    python tools/old_code_compat_check.py --old-app /path/to/previous/spicmacay_ai_app \
        --db "user:password@127.0.0.1:3306/drupal" --this-is-a-copy

1. This version files four programs on the database (single, circuit, 3-day Virasat, and one with institutions by id).
2. The previous version's own event_service.py and database.py, loaded on their own in a separate process, read them
   through every lookup it has: details, payment reminder, guidelines, resend, listings, dashboards. It then files an
   APR of its own, to show its writes still work.
3. Everything both versions created is deleted again.
Run it on a COPY of the database: it refuses without --this-is-a-copy.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
READER = r'''
import sys, json, logging
sys.path[:0] = [sys.argv[1]]
errors = []
class Catch(logging.Handler):
    def emit(self, rec):
        if rec.levelno >= logging.ERROR: errors.append(rec.getMessage()[:200])
logging.getLogger().addHandler(Catch()); logging.getLogger().setLevel(logging.ERROR)
from app.models.database import DatabaseManager
from app.services.event_service import EventService
cfg, rows = json.loads(sys.argv[2]), json.loads(sys.argv[3])
es = EventService(DatabaseManager(cfg))
out = {'events': [], 'errors': errors}
for p in rows:
    for eid in p['event_ids']:
        pay = es.get_event_for_payment(eid) or {}
        out['events'].append({'program': p['label'], 'event': eid, 'details': bool(es.get_event_details(eid)), 'payment': bool(pay),
                              'guidelines': bool(es.get_event_for_guidelines(eid)), 'resend': bool(es.get_event_for_resend(eid)),
                              'apr_ref': pay.get('custom_apr'), 'institution_found_by_old_lookup': pay.get('institution_name')})
out['listings'] = {'search_events': len(es.search_events({}) or []), 'pending_payments': len(es.get_pending_payment_events({}) or []),
                   'dashboard_stats': bool(es.get_dashboard_stats()), 'year_to_date': bool(es.get_academic_year_to_date_stats())}
ev = es.create_event({'event_date': '2099-12-01', 'title': 'Compatibility check (previous version)', 'module_name': 'Talk',
                      'institution_id': rows[0]['inst_sid'], 'institution_name': rows[0]['inst_name'], 'artist_id': rows[0]['artist_id']})
apr = es.create_apr(ev.get('event_id'), {'event_date': '2099-12-01', 'artist_id': rows[0]['artist_id'], 'institution_name': rows[0]['inst_name']}) if ev.get('success') else None
out['old_writes'] = {'event_id': ev.get('event_id'), 'ok': bool(ev.get('success')), 'apr_ref': (apr or {}).get('custom_apr'), 'request_id': (apr or {}).get('request_id')}
print('RESULT ' + json.dumps(out, default=str))
'''


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--old-app', required=True, help='folder of the previous version (containing app/services/event_service.py)')
    ap.add_argument('--db', required=True, help='user:password@host:port/dbname of a database COPY')
    ap.add_argument('--this-is-a-copy', action='store_true')
    a = ap.parse_args()
    if not a.this_is_a_copy:
        sys.exit('Refusing to run without --this-is-a-copy: it writes and then deletes test records.')
    m = re.match(r'(?P<user>[^:]+):(?P<pw>.*)@(?P<host>[^:/]+):(?P<port>\d+)/(?P<db>\w+)$', a.db)
    if not m:
        sys.exit('--db must look like user:password@host:port/dbname')
    old = Path(a.old_app)
    pkg = Path(tempfile.mkdtemp()) / 'oldpkg'                   # only the two old files, nothing else of either version
    for sub in ('app/models', 'app/services'):
        (pkg / sub).mkdir(parents=True)
    for init in ('app', 'app/models', 'app/services'):
        (pkg / init / '__init__.py').write_text('')
    shutil.copy(old / 'app' / 'models' / 'database.py', pkg / 'app' / 'models' / 'database.py')
    shutil.copy(old / 'app' / 'services' / 'event_service.py', pkg / 'app' / 'services' / 'event_service.py')

    os.environ.update(DB_HOST=m['host'], DB_PORT=m['port'], DB_USER=m['user'], DB_PASSWORD=m['pw'], DB_NAME=m['db'],
                      INSTANCE_DIR=tempfile.mkdtemp(), SECRET_KEY='compat-check-' + 'x' * 30)
    os.environ.pop('OPENAI_API_KEY', None)
    sys.path[:0] = [str(ROOT)]
    import logging
    logging.disable(logging.WARNING)
    from app import create_app
    from app.agents.draft import ProgramDraft, expand_days
    s = create_app().extensions['spicmacay']
    db = s.writer.db
    user = db.fetch_one("SELECT uid, name, mail FROM users_field_data WHERE status = 1 AND mail <> '' ORDER BY uid LIMIT 1")
    artist = db.fetch_one('SELECT tid, name FROM artists_list WHERE status = 1 ORDER BY tid LIMIT 1')
    insts = db.fetch_all('SELECT MIN(sid) sid, institution_name, MIN(city) city, MIN(state) state FROM institution_list WHERE status = 1 '
                         'GROUP BY institution_name HAVING COUNT(*) = 1 ORDER BY MIN(sid) LIMIT 2')
    module = (s.writer.modules() or [('', 'Talk')])[0][1]
    created = {'custom_apr': [], 'event_series': [], 'event_list': [], 'request_ids': []}
    rows = []
    previous_inst_setting = s.gov.get_setting('db.store_institution_as')
    try:
        for label, ptype, stops, mode in [('single', 'single', [('2099-11-02', 0, None)], 'name'),
                                          ('circuit', 'circuit', [('2099-11-03', 0, None), ('2099-11-04', 1, None)], 'name'),
                                          ('virasat, 3-day workshop', 'virasat', [('2099-11-05', 0, '2099-11-07')], 'name'),
                                          ('single, institution by id', 'single', [('2099-11-09', 0, None)], 'id')]:
            s.gov.set_setting('db.store_institution_as', mode, 'compat-check')
            d = ProgramDraft()
            d.set_program({'program_type': ptype, 'module': module})
            if ptype != 'virasat':
                d.set_artist({'artist_id': artist['tid'], 'name': artist['name']}, 'main')
            for date, k, end in stops:
                inst = insts[k % len(insts)]
                i, _ = d.add_event({'date': date, 'start_time': '10:00 - 12:00', **({'end_date': end} if end else {})})
                d.update_event(i, {'institution_id': inst['sid'], 'institution_name': inst['institution_name'], 'city': inst['city'], 'state': inst['state']})
                if ptype == 'virasat':
                    d.d['events'][i]['artists'] = [ProgramDraft.make_artist({'artist_id': artist['tid'], 'name': artist['name']}, 'main')]
            d.add_coordinator({'uid': user['uid'], 'name': user['name'], 'email': user['mail'], 'role': 'filer'})
            r = s.writer.create(expand_days(d)[0].to_dict(), uid=user['uid'])
            created['event_list'] += r['event_ids']
            created['request_ids'].append(r['request_id'])
            if r.get('portal_apr_id'):
                created['custom_apr'].append(int(r['portal_apr_id']))
            if r.get('series_id'):
                created['event_series'].append(int(r['series_id']))
            rows.append({'label': label, 'event_ids': r['event_ids'], 'apr': r['apr_number'], 'inst_sid': insts[0]['sid'],
                         'inst_name': insts[0]['institution_name'], 'artist_id': artist['tid']})
        cfg = {'host': m['host'], 'port': int(m['port']), 'user': m['user'], 'password': m['pw'], 'database': m['db']}
        proc = subprocess.run([sys.executable, '-c', READER, str(pkg), json.dumps(cfg), json.dumps(rows)], capture_output=True, text=True, timeout=300)
        line = next((ln for ln in proc.stdout.splitlines() if ln.startswith('RESULT ')), None)
        if not line:
            print(proc.stdout[-2000:], proc.stderr[-2000:])
            sys.exit('The previous version could not be run (see above).')
        res = json.loads(line[7:])
        if res['old_writes'].get('event_id'):
            created['event_list'].append(res['old_writes']['event_id'])
            if res['old_writes'].get('request_id'):
                created['request_ids'].append(res['old_writes']['request_id'])
        print('The previous version reading APRs filed by this version:')
        for e in res['events']:
            ok = all(e[k] for k in ('details', 'payment', 'guidelines', 'resend')) and e['apr_ref']
            print(f"  [{'PASS' if ok else 'FAIL'}] {e['program']:<27} event {e['event']}: lookups "
                  f"{'all found' if ok else e}, APR reference {e['apr_ref']}, institution by its id lookup: {e['institution_found_by_old_lookup'] or '(stored by name)'}")
        print(f"  [{'PASS' if all(res['listings'].values()) else 'FAIL'}] listings and dashboards: {res['listings']}")
        print(f"  [{'PASS' if res['old_writes']['ok'] else 'FAIL'}] the previous version files its own APR afterwards: {res['old_writes']['apr_ref']}")
        print(f"  [{'PASS' if not res['errors'] else 'FAIL'}] errors logged by the previous version: {res['errors'] or 'none'}")
    finally:
        s.gov.set_setting('db.store_institution_as', previous_inst_setting or 'name', 'compat-check')
        for i in created['custom_apr']:
            db.execute_query('DELETE FROM custom_apr WHERE id = %s', (i,), commit=True)
        for i in created['event_series']:
            db.execute_query('DELETE FROM event_series WHERE id = %s', (i,), commit=True)
        for i in created['event_list']:
            db.execute_query('DELETE FROM event_list WHERE id = %s', (i,), commit=True)
        for rid in created['request_ids']:
            db.execute_query('DELETE FROM apr_payment_request WHERE request_id = %s', (rid,), commit=True)
        print(f"Cleaned up: {len(created['event_list'])} events, {len(created['custom_apr'])} APRs, {len(created['event_series'])} programs.")


if __name__ == '__main__':
    main()
