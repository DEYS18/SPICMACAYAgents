"""The original conversational agent stays the main assistant. Underneath, its two services are improved:
better directory search with the same result fields, any date format, the portal's own APR records, and
provisional new artists. With the bridge off, everything behaves exactly as the original did."""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import build_test_services  # noqa: E402

from app.models.database import DatabaseValidator  # noqa: E402
from app.services import classic_bridge as bridge  # noqa: E402

LEGACY_ARTIST_FIELDS = {'tid', 'name', 'art_form', 'artist_type', 'artist_grade', 'city', 'enter_state', 'email', 'phone', 'relevance'}
LEGACY_INSTITUTION_FIELDS = {'sid', 'institution_name', 'city', 'state', 'pincode', 'email', 'phone', 'address'}


class BridgeSearchTests(unittest.TestCase):
    def setUp(self):
        self.s, self.db, _ = build_test_services()
        self.v = DatabaseValidator.__new__(DatabaseValidator)          # the original validator, with the improved engine attached
        self.v.directory = self.s.index

    def test_artists_keep_the_original_fields(self):
        rows = self.v.search_artists('Pt Ronu Mazumdar')
        self.assertTrue(LEGACY_ARTIST_FIELDS <= set(rows[0]))
        self.assertEqual((rows[0]['name'], rows[0]['tid'], rows[0].get('best_match')), ('Ronu Majumdar', 1, True))

    def test_notes_for_the_reviewers_points(self):
        notes = ' '.join(r.get('note', '') for r in self.v.search_artists('Pandit Ravi Shankar'))
        self.assertIn('passed away', notes)                              # DC3
        self.assertIn('similar name', notes)
        self.assertIn('several art forms', self.v.search_artists('Ashwini Bhide')[0]['note'])   # DC10
        inst = self.v.search_institutions('BITS Pilani')
        self.assertTrue(LEGACY_INSTITUTION_FIELDS <= set(inst[0]))
        self.assertIn('several campuses', inst[0]['note'])                # DC4
        self.assertTrue(self.v.search_institutions('IIT Bombay')[0].get('best_match'))
        self.assertEqual(self.v.search_coordinators('Sabyasachi')[0]['email'], 'sabyasachi@spicmacay.com')

    def test_any_date_format(self):
        self.assertEqual([bridge.iso_date(d) for d in ('15 Oct 2026', '15-10-2026', '2026-10-15')], ['2026-10-15'] * 3)


class BridgeFilingTests(unittest.TestCase):
    def setUp(self):
        self.s, self.db, _ = build_test_services()
        self.es = self.s.event_service
        self.es.portal = self.s

    def event(self, inst_id, inst_name, day='15 Oct 2026', module='Lecture Demonstration'):
        r = self.es.create_event({'event_date': day, 'title': 'Lec dem', 'module_name': module, 'institution_id': inst_id,
                                  'institution_name': inst_name, 'artist_id': 1, 'city': 'Mumbai', 'state': 'Maharashtra',
                                  'created_by_uid': 15})
        self.assertTrue(r['success'], r)
        return r['event_id']

    def test_single_event_gets_the_portal_record(self):
        eid = self.event(1, 'Indian Institute of Technology Bombay')
        row = self.db.fetch_one('SELECT start_date, institution, event_category FROM event_list WHERE id = %s', (eid,))
        self.assertEqual((row['start_date'], row['institution'], row['event_category']), ('2026-10-15', 'Indian Institute of Technology Bombay', '4'))
        apr = self.es.create_apr(eid, {'event_date': '2026-10-15', 'artist_id': 1, 'institution_name': 'IIT Bombay',
                                       'coordinator_email': 'sabyasachi@spicmacay.com', 'created_by_uid': 15})
        self.assertEqual(apr['custom_apr'], '208')                       # the portal's own numbering
        portal = self.db.fetch_one('SELECT * FROM custom_apr WHERE id = 208')
        self.assertEqual((portal['event_series'], portal['eventgroup'], portal['event_id'], portal['coordinators_id'], portal['final_submit']),
                         ('289', str(eid), str(eid), '15', 1))
        self.assertEqual(self.db.fetch_one('SELECT custom_apr FROM apr_payment_request')['custom_apr'], '208')   # old rows too

    def test_circuit_and_virasat_get_program_records(self):
        ids = [self.event(3, 'APS Ahmednagar', '14 Feb 2027'), self.event(2, 'Delhi Public School', '16 Feb 2027')]
        apr = self.es.create_apr_for_group(ids, {'event_date': '2027-02-14', 'artist_id': 1, 'created_by_uid': 15})
        series = self.db.fetch_one('SELECT id, event_type, event_id FROM event_series')
        self.assertEqual((series['event_type'], series['event_id'], apr['custom_apr']), ('288', f'{ids[0]},{ids[1]}', '208'))
        self.assertEqual({r['added_from'] for r in self.db.fetch_all('SELECT added_from FROM event_list')}, {series['id']})
        vir = [self.event(1, 'Indian Institute of Technology Bombay', d) for d in ('20 Jan 2027', '21 Jan 2027')]
        self.es.create_apr_for_group(vir, {'event_date': '2027-01-20', 'artist_id': 1, 'created_by_uid': 15})
        self.assertEqual(self.db.fetch_one('SELECT event_type FROM event_series ORDER BY id DESC')['event_type'], '291')

    def test_without_the_bridge_the_original_behaviour_is_unchanged(self):
        self.es.portal = None
        eid = self.event(1, 'Indian Institute of Technology Bombay')
        self.assertEqual(self.db.fetch_one('SELECT institution FROM event_list WHERE id = %s', (eid,))['institution'], '1')
        apr = self.es.create_apr(eid, {'event_date': '2026-10-15', 'artist_id': 1, 'institution_name': 'IIT Bombay'})
        self.assertTrue(apr['custom_apr'].startswith(f'APR-{eid}-'))
        self.assertEqual(self.db.count('custom_apr'), 1)                  # only the seed row

    def test_a_new_artist_is_provisional(self):
        r = self.es.add_new_artist({'name': 'Smt. Rubi Devi', 'art_form': 'Sikki Grass Weaving', 'city': 'Madhubani', 'state': 'Bihar'})
        self.assertTrue(r['success'], r)
        self.assertEqual(self.db.fetch_one('SELECT added_by FROM artists_list WHERE tid = %s', (r['artist_id'],))['added_by'], 'AI-PROV')
        self.assertEqual(self.s.gov.list_approvals()[0]['kind'], 'artist')


class OriginalAgentTests(unittest.TestCase):
    def test_the_original_instructions_stay_and_gain_the_addendum(self):
        src = open(os.path.join(os.path.dirname(__file__), '..', 'app', 'models', 'agent.py'), encoding='utf-8').read()
        self.assertIn('LANGUAGE — SPEAK THE COORDINATOR\'S LANGUAGE, STORE IN ENGLISH', src)      # the original text, unchanged
        self.assertIn('self.system_prompt += prompt_addendum()', src)
        add = bridge.prompt_addendum()
        for point in ('passed away', 'any format', 'main or an accompanying', 'provisional', 'more than one coordinator'.capitalize()):
            self.assertIn(point.lower(), add.lower())

    def test_the_original_screen_with_the_theme(self):
        from flask import render_template
        from app.assistant_setup import create_assistant_app
        s, _, _ = build_test_services()
        app = create_assistant_app(s)
        src = open(os.path.join(app.root_path, 'templates', 'assistant_classic.html'), encoding='utf-8').read()
        for ep in set(re.findall(r"url_for\(['\"]([a-z_.]+)['\"]", src)) - {'static'} - set(app.view_functions):
            app.add_url_rule(f'/_stand_in/{ep}', ep, lambda: '')
        with app.test_request_context('/assistant'):
            html = render_template('assistant_classic.html')
        self.assertIn('css/classic-theme.css', html)
        self.assertIn('Several Posters at Once', html)
        self.assertIn('href="./assistant"', html)
        for feature in ('Create APR', 'Upload a Poster', 'Generate a Poster', 'Voice Assistant Mode', 'speaker-btn', 'mic-btn'):
            self.assertIn(feature, html)                                   # every original feature is still there


if __name__ == '__main__':
    unittest.main()
