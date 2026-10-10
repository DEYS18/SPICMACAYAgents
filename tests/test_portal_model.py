"""How the portal itself stores APRs, found in the production dump (MariaDB 10.11), and the fixes for it:
custom_apr is the APR, event_series the program, institutions by name, latin1 tables in strict mode."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import build_test_services  # noqa: E402

from app.agents.state import ConversationState  # noqa: E402
from app.models.database import latin1_params  # noqa: E402
from app.search.resolver import DirectoryIndex  # noqa: E402
from app.services.event_service import EventService  # noqa: E402
from app.skills.base import SkillContext  # noqa: E402


class PortalModelTests(unittest.TestCase):
    def setUp(self):
        self.s, self.db, _ = build_test_services()
        self.st = ConversationState()
        self.ctx = SkillContext(self.s, self.st, actor={'email': 'sabyasachi@spicmacay.com'}, via='button')

    def run_tool(self, tool_name, /, **a):
        return self.s.registry.execute(tool_name, a, self.ctx)

    def single(self, module='Concert', title=None, notes=None):
        self.run_tool('update_program', program_type='single', module=module, **({'title': title} if title else {}), **({'notes': notes} if notes else {}))
        self.run_tool('select_artist', artist_id=3, role='main')
        self.run_tool('add_events', events=[{'date': '20-01-2027', 'institution': 'IIT Bombay', 'start_time': '6 pm - 8 pm'}])
        self.run_tool('add_coordinator', email='sabyasachi@spicmacay.com', role='filer')
        return self.run_tool('review_program')

    def test_the_apr_is_a_custom_apr_record(self):
        rv = self.single()
        c = self.run_tool('create_apr', confirmation_id=rv['confirmation_id'])
        self.assertTrue(c['ok'], c)
        ev = self.db.fetch_one('SELECT * FROM event_list')
        apr = self.db.fetch_one('SELECT * FROM custom_apr WHERE id = %s', (int(c['apr_number']),))
        self.assertEqual(c['apr_number'], '208')
        self.assertEqual((apr['event_series'], apr['eventgroup'], apr['event_id'], apr['created_by'], apr['del'], apr['final_submit']),
                         ('289', str(ev['id']), str(ev['id']), '15', 0, 1))
        self.assertIsNone(apr['apr_status'])                         # awaits approval in the portal
        self.assertEqual((ev['institution'], ev['event_category'], ev['added_from'], ev['added_by'], ev['event_time'], ev['end_time']),
                         ('Indian Institute of Technology Bombay', '13', 0, '15', '18:00', '20:00'))
        self.assertEqual(self.db.count('event_series'), 0)

    def test_text_is_stored_latin1_safe(self):
        rv = self.single(title='विरासत कार्यक्रम ₹', notes='Pt. Rāmesh’s visit')
        c = self.run_tool('create_apr', confirmation_id=rv['confirmation_id'])
        self.assertTrue(c['ok'], c)                                  # strict latin1 would have rejected the original text
        ev = self.db.fetch_one('SELECT title, summary FROM event_list')
        self.assertEqual(ev['title'], 'Viraasat Kaaryakram Rs')
        self.assertEqual(ev['summary'], 'Pt. Ramesh’s visit')        # curly apostrophe is valid in latin1 (Windows-1252)

    def test_unknown_module_is_caught_at_review(self):
        rv = self.single(module='Baithak')
        self.assertFalse(rv['ready'])
        self.assertTrue(any('not one of the portal' in m for m in rv['missing']))

    def test_classic_lookups_find_institutions_by_name(self):
        self.db.execute_query("INSERT INTO event_list (id, title, start_date, end_date, institution, city, artist, status, event_status) "
                              "VALUES (9582, 'Concert', '2026-03-08', '2026-03-08', 'Delhi Public School', 'Nashik', '1', 1, 'Completed')", commit=True)
        ev = EventService(self.db).get_event_for_payment(9582)
        self.assertEqual((ev or {}).get('institution_email') or (ev or {}).get('email'), 'principal@dpsnashik.in')

    def test_an_exact_name_beats_dirty_city_data(self):
        insts = [{'sid': 598, 'institution_name': 'AIIMS Delhi', 'city': 'Delhi', 'state': 'Delhi'},
                 {'sid': 797, 'institution_name': 'AIIMS', 'city': 'AIIMS', 'state': 'Jharkhand'},
                 {'sid': 3166, 'institution_name': 'AIIMS', 'city': 'AIIMS', 'state': 'Uttarakhand'}]
        idx = DirectoryIndex(lambda: [], lambda: insts)
        self.assertEqual(idx.search_institutions('AIIMS Delhi')['best']['sid'], 598)
        self.assertIsNone(idx.search_institutions('AIIMS')['best'])  # two records with that very name: ask

    def test_generic_words_alone_never_pick_an_institution(self):
        insts = [{'sid': 1, 'institution_name': 'TIFR Mumbai', 'city': 'Mumbai', 'state': 'Maharashtra'},
                 {'sid': 2, 'institution_name': 'VNIT Nagpur', 'city': 'Nagpur', 'state': 'Maharashtra'},
                 {'sid': 3, 'institution_name': 'B.V.M. CIVIL LINES NAGPUR', 'city': 'NAGPUR', 'state': 'Maharashtra'}]
        idx = DirectoryIndex(lambda: [], lambda: insts)
        r = idx.search_institutions('Tata Institute of Social Science', city='Mumbai')
        self.assertIsNone(r['best'])                                 # TISS is not TIFR...
        self.assertEqual(r['matches'][0]['institution_name'], 'TIFR Mumbai')   # ...but stays visible as a candidate
        self.assertEqual(idx.search_institutions('Tata Institute of Fundamental Research', city='Mumbai')['best']['sid'], 1)
        self.assertEqual(idx.search_institutions('VNIT Nagpur', city='Nagpur')['best']['sid'], 2)
        idx2 = DirectoryIndex(lambda: [], lambda: [x for x in insts if x['sid'] != 2])           # VNIT not in the directory
        self.assertIsNone(idx2.search_institutions('VNIT Nagpur', city='Nagpur')['best'])         # never "B.V.M." by its initials

    def test_the_classic_write_guard(self):
        self.assertEqual(latin1_params('INSERT INTO event_list (title) VALUES (%s)', ('विरासत',)), ('Viraasat',))
        self.assertEqual(latin1_params('INSERT INTO custom_apr (additional_message) VALUES (%s)', ('विरासत',)), ('विरासत',))   # utf8mb4 table


if __name__ == '__main__':
    unittest.main()


class EnsureModulesTests(unittest.TestCase):
    """Workshops and Yoga & Meditation are added to event_module when missing (agreed with SPIC MACAY)."""

    def setUp(self):
        self.s, self.db, _ = build_test_services()

    def names(self):
        return [r['name'] for r in self.db.fetch_all('SELECT name FROM event_module ORDER BY tid')]

    def test_nothing_is_added_when_they_exist(self):
        before = self.names()
        self.s.writer.reset_cache()
        self.s.writer.modules()
        self.assertEqual(self.names(), before)                          # production already has tids 9 and 11

    def test_missing_ones_are_added_once(self):
        self.db.execute_query("DELETE FROM event_module WHERE name IN ('Workshops', 'Yoga & Meditation')", commit=True)
        self.s.writer.reset_cache()
        self.assertEqual(self.s.writer.module_lookup('Workshop')[1], 'Workshops')
        self.assertEqual(self.s.writer.module_lookup('Yoga')[1], 'Yoga & Meditation')
        self.s.writer.reset_cache()
        self.s.writer.modules()
        self.assertEqual(self.names().count('Workshops') + self.names().count('Yoga & Meditation'), 2)   # not twice
        self.assertEqual(sum(1 for a in self.s.gov.list_audit(50) if a['action'] == 'portal.module_added'), 2)

    def test_close_names_and_switched_off_modules_count_as_present(self):
        self.db.execute_query("UPDATE event_module SET name = 'Workshop' WHERE name = 'Workshops'", commit=True)
        self.db.execute_query("UPDATE event_module SET name = 'Yoga and Meditation', status = 0 WHERE name = 'Yoga & Meditation'", commit=True)
        before = len(self.names())
        self.s.writer.reset_cache()
        self.s.writer.modules()
        self.assertEqual(len(self.names()), before)

    def test_an_administrator_can_add_another(self):
        self.s.gov.set_setting('db.ensure_modules', 'Workshops, Yoga & Meditation, Baithak', 'admin')
        self.assertEqual(self.s.setting('db.ensure_modules'), ['Workshops', 'Yoga & Meditation', 'Baithak'])
        self.s.writer.reset_cache()
        self.assertIsNotNone(self.s.writer.module_lookup('Baithak')[0])


class BothRecordTypesTests(unittest.TestCase):
    """Every APR is written for the portal (custom_apr) AND as the previous version wrote it (apr_payment_request)."""

    def setUp(self):
        self.s, self.db, _ = build_test_services()
        self.ctx = SkillContext(self.s, ConversationState(), actor={'email': 'sabyasachi@spicmacay.com'}, via='button')

    def file(self, **settings):
        for k, v in settings.items():
            self.s.gov.set_setting(k, v, 'test')
        R = lambda n, **a: self.s.registry.execute(n, a, self.ctx)
        R('update_program', program_type='circuit', module='Lecture Demonstration')
        R('select_artist', artist_id=1, role='main')
        R('add_events', events=[{'date': '14-02-2027', 'institution': 'APS Ahmednagar', 'start_time': '10:00 - 12:00'},
                                {'date': '16-02-2027', 'institution': 'DPS Nashik', 'start_time': '18:00'}])
        R('add_coordinator', email='sabyasachi@spicmacay.com', role='filer')
        return R('create_apr', confirmation_id=R('review_program')['confirmation_id'])

    def test_both_by_default_in_the_previous_format(self):
        import re
        c = self.file()
        self.assertTrue(c['ok'], c)
        portal = self.db.fetch_one('SELECT * FROM custom_apr WHERE id = 208')
        old = self.db.fetch_all('SELECT * FROM apr_payment_request ORDER BY id')
        self.assertEqual(portal['event_id'], '1,2')
        self.assertEqual([r['event_id'] for r in old], ['1', '2'])                       # one row per event
        self.assertEqual({r['request_id'] for r in old}.__len__(), 1)                     # sharing one request_id...
        self.assertRegex(old[0]['request_id'], r'^REQ-\d{14}-[0-9A-F]{6}$')               # ...in the previous format
        self.assertEqual({r['custom_apr'] for r in old}, {'208'})                         # and the portal's APR number
        self.assertEqual([r['time_duration'] for r in old], ['10:00', '18:00'])           # start time, as before
        self.assertEqual([r['institution'] for r in old], ['APS Ahmednagar', 'Delhi Public School'])
        self.assertEqual({(r['created_by'], r['updated_by'], r['del']) for r in old}, {('15', '15', 0)})

    def test_legacy_reference_still_creates_the_portal_record(self):
        c = self.file(**{'apr.number_scheme': 'legacy'})
        self.assertTrue(c['apr_number'].startswith('APR-1-'))
        self.assertEqual({r['custom_apr'] for r in self.db.fetch_all('SELECT custom_apr FROM apr_payment_request')}, {c['apr_number']})
        self.assertEqual(self.db.count('custom_apr'), 2)                                  # 207 from the seed + this one

    def test_institution_by_id_for_the_previous_version(self):
        self.file(**{'db.store_institution_as': 'id'})
        self.assertEqual([r['institution'] for r in self.db.fetch_all('SELECT institution FROM event_list ORDER BY id')], ['3', '2'])

    def test_one_switch_at_a_time(self):
        self.file(**{'apr.write_ai_request_rows': False})
        self.assertEqual((self.db.count('apr_payment_request'), self.db.count('custom_apr')), (0, 2))

    def test_never_both_off(self):
        c = self.file(**{'apr.write_ai_request_rows': False, 'apr.write_portal_records': False})
        self.assertFalse(c.get('ok'))
        self.assertEqual(self.db.count('event_list'), 0)
