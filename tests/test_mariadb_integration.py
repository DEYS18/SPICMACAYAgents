"""
Integration test against a real MariaDB/MySQL COPY of the portal database (never production).

    SPICMACAY_TEST_DB="user:password@127.0.0.1:3306/drupal" SPICMACAY_TEST_DB_IS_A_COPY=yes \
        python -m unittest tests.test_mariadb_integration -v

Skipped unless both variables are set. Every record it creates is deleted again at the end.
"""
import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import helpers  # noqa: E402,F401  (puts the project on the path)

DSN = os.getenv('SPICMACAY_TEST_DB', '')
COPY = os.getenv('SPICMACAY_TEST_DB_IS_A_COPY', '').lower() == 'yes'
NEEDED = {'event_list': {'title', 'start_date', 'end_date', 'event_time', 'end_time', 'event_category', 'institution', 'artist',
                         'accompanying_artist', 'event_status', 'status', 'added_by', 'added_from', 'poww', 'fy', 'attendees', 'budget'},
          'event_series': {'event_type', 'title', 'start_date', 'end_date', 'event_id', 'event_status', 'status', 'added_by', 'institution'},
          'custom_apr': {'coordinators_id', 'event_series', 'eventgroup', 'event_id', 'created_by', 'dt_created', 'del', 'final_submit',
                         'added_by', 'apr_status'},
          'apr_payment_request': {'request_id', 'artist_id', 'event_id', 'custom_apr', 'event_date', 'time_duration', 'institution',
                                  'chapter', 'students', 'fc', 'created_by', 'dt_created', 'updated_by'},
          'artists_list': {'tid', 'name', 'art_form', 'status', 'added_by'},
          'institution_list': {'sid', 'institution_name', 'city', 'state', 'status'},
          'event_module': {'tid', 'name', 'status'}, 'users_field_data': {'uid', 'name', 'mail', 'status'}}


@unittest.skipUnless(DSN and COPY, 'set SPICMACAY_TEST_DB and SPICMACAY_TEST_DB_IS_A_COPY=yes to run against a database copy')
class MariaDBIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        m = re.match(r'(?P<user>[^:]+):(?P<pw>.*)@(?P<host>[^:/]+):(?P<port>\d+)/(?P<db>\w+)$', DSN)
        assert m, 'SPICMACAY_TEST_DB must look like user:password@host:port/dbname'
        os.environ.update(DB_HOST=m['host'], DB_PORT=m['port'], DB_USER=m['user'], DB_PASSWORD=m['pw'], DB_NAME=m['db'],
                          INSTANCE_DIR=tempfile.mkdtemp(), SECRET_KEY='integration-test-' + 'x' * 24)
        os.environ.pop('OPENAI_API_KEY', None)
        from app import create_app
        cls.app = create_app()
        cls.s = cls.app.extensions['spicmacay']
        cls.db = cls.s.writer.db
        cls.created = {'custom_apr': [], 'event_list': [], 'event_series': [], 'apr_payment_request': []}

    @classmethod
    def tearDownClass(cls):
        for table, ids in cls.created.items():
            for i in ids:
                col = 'request_id' if table == 'apr_payment_request' else 'id'
                cls.db.execute_query(f'DELETE FROM {table} WHERE {col} = %s', (i,), commit=True)

    def q(self, sql, params=()):
        return self.db.fetch_all(sql, params) or []

    def test_schema_has_what_the_assistant_writes(self):
        for table, cols in NEEDED.items():
            have = {r['COLUMN_NAME'] for r in self.q('SELECT COLUMN_NAME FROM information_schema.columns WHERE table_schema = DATABASE() '
                                                    'AND table_name = %s', (table,))}
            self.assertFalse(cols - have, f'{table} is missing {sorted(cols - have)}')

    def test_directory_types_and_modules(self):
        self.assertGreater(len(self.s.index.search_artists('a')['matches']) + self.q('SELECT COUNT(*) n FROM artists_list')[0]['n'], 0)
        for p in ('single', 'circuit', 'virasat'):
            self.assertTrue(self.s.writer.program_type_id(p).isdigit())
        if self.s.writer.modules():
            self.assertIsNotNone(self.s.writer.module_lookup('Lecture Demonstration')[0])

    def test_filing_matches_the_portal_and_survives_any_text(self):
        from app.agents.draft import ProgramDraft
        artist = self.q('SELECT tid, name, art_form FROM artists_list WHERE status = 1 ORDER BY tid LIMIT 1')[0]
        insts = self.q('SELECT MIN(sid) sid, institution_name, MIN(city) city, MIN(state) state FROM institution_list WHERE status = 1 '
                       'GROUP BY institution_name HAVING COUNT(*) = 1 ORDER BY MIN(sid) LIMIT 2')
        user = self.q("SELECT uid, name, mail FROM users_field_data WHERE status = 1 AND mail <> '' ORDER BY uid LIMIT 1")[0]
        module = (self.s.writer.modules() or [('', 'Lecture Demonstration')])[0][1]
        d = ProgramDraft()
        d.set_program({'program_type': 'circuit', 'module': module, 'title': 'विरासत संगीत ₹ Rāga’s test', 'notes': 'Integration test'})
        d.set_artist({'artist_id': artist['tid'], 'name': artist['name'], 'art_form': artist['art_form']}, 'main')
        for k, inst in enumerate(insts):
            i, _ = d.add_event({'date': f'2099-01-0{k + 1}', 'start_time': '10:00 - 12:00'})
            d.update_event(i, {'institution_id': inst['sid'], 'institution_name': inst['institution_name'], 'city': inst['city'], 'state': inst['state']})
        d.add_coordinator({'uid': user['uid'], 'name': user['name'], 'email': user['mail'], 'role': 'filer'})
        res = self.s.writer.create(d.to_dict(), uid=user['uid'])
        self.created['custom_apr'].append(int(res['apr_number']))
        self.created['event_list'].extend(res['event_ids'])
        self.created['event_series'].append(res['series_id'])
        self.created['apr_payment_request'].append(res['request_id'])
        apr = self.q('SELECT * FROM custom_apr WHERE id = %s', (int(res['apr_number']),))[0]
        self.assertEqual((apr['event_series'], apr['eventgroup'], apr['event_id'], apr['final_submit'], apr['del']),
                         (res['program_type_id'], str(res['series_id']), ','.join(map(str, res['event_ids'])), 1, 0))
        rows = self.q('SELECT * FROM event_list WHERE id IN (%s, %s) ORDER BY id' % tuple(res['event_ids']))
        self.assertEqual([r['institution'] for r in rows], [i['institution_name'] for i in insts])
        self.assertEqual({int(r['added_from']) for r in rows}, {int(res['series_id'])})
        self.assertTrue(rows[0]['title'].startswith('Viraasat Sangeet Rs'))
        old = self.q('SELECT event_id, custom_apr, request_id FROM apr_payment_request WHERE request_id = %s ORDER BY id', (res['request_id'],))
        self.assertEqual([r['event_id'] for r in old], [str(i) for i in res['event_ids']])     # the previous version's rows too
        self.assertEqual({r['custom_apr'] for r in old}, {res['apr_number']})

    def test_classic_lookup_by_institution_name(self):
        ev = self.q('SELECT e.id FROM event_list e JOIN institution_list i ON i.institution_name = e.institution '
                    'WHERE e.status = 1 ORDER BY e.id DESC LIMIT 1')
        if not ev:
            self.skipTest('no event stores an institution name found in the directory')
        self.assertTrue((self.s.event_service.get_event_for_payment(ev[0]['id']) or {}).get('institution_name'))


if __name__ == '__main__':
    unittest.main()
