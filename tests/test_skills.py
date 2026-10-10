"""Every skill against a copy of the portal schema: circuits, Virasat, the reviewer's comments,
confirmations, emails, posters, poster and cheque reading, governance switches, and the agent loop."""
import base64
import io
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import FakeLLM, build_test_services  # noqa: E402

from app.agents.state import ConversationState  # noqa: E402
from app.services import pdf_service, poster_service  # noqa: E402
from app.skills.base import SkillContext  # noqa: E402
from app.skills.output_skills import confirm_bank_proposal, extract_poster, read_cheque  # noqa: E402

CIRCUIT_STOPS = [{'date': '14-02-2027', 'institution': 'APS Ahmednagar', 'start_time': '8am-10am', 'contribution': '23,000'},
                 {'date': '16/02/2027', 'institution': 'DPS Nashik', 'start_time': '10am-12pm', 'contribution': '10000'},
                 {'date': '17 Feb 2027', 'institution': 'BITS Pilani', 'contribution': 'NIL'}]


def jpeg():
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (600, 800), (180, 120, 60)).save(buf, 'JPEG')
    return buf.getvalue()


class SkillTestCase(unittest.TestCase):
    llm = None

    def setUp(self):
        self.s, self.db, self.tmp = build_test_services(self.llm)
        self._dirs = poster_service._ARTIST_PHOTO_DIR, pdf_service.EVENT_PHOTOS_DIR
        poster_service._ARTIST_PHOTO_DIR = os.path.join(self.tmp, 'artist_photos')
        pdf_service.EVENT_PHOTOS_DIR = os.path.join(self.tmp, 'event_photos')
        self.st = ConversationState()
        self.ctx = SkillContext(self.s, self.st, actor={'email': 'sabyasachi@spicmacay.com'}, via='button')

    def tearDown(self):
        poster_service._ARTIST_PHOTO_DIR, pdf_service.EVENT_PHOTOS_DIR = self._dirs

    def run_tool(self, tool_name, /, **args):
        return self.s.registry.execute(tool_name, args, self.ctx)

    def circuit(self):
        self.run_tool('update_program', program_type='circuit', module='lec dem', title='Maharashtra Circuit')
        self.run_tool('find_artist', name='Pt Ronu Mazumdar', role='main')
        self.run_tool('find_artist', name='Ajeet Pathak', role='accompanying')
        r = self.run_tool('add_events', events=CIRCUIT_STOPS)
        self.run_tool('select_institution', institution_id=5, event_index=2)
        self.run_tool('add_coordinator', email='sabyasachi@spicmacay.com', role='filer')
        return r

    def file(self):
        rv = self.run_tool('review_program')
        self.assertTrue(rv['ready'], rv)
        return self.run_tool('create_apr', confirmation_id=rv['confirmation_id'])


class CircuitTests(SkillTestCase):
    def test_every_stop_resolved_in_one_call(self):
        r = self.circuit()
        self.assertEqual([e['status'] for e in r['events']], ['matched', 'matched', 'choose_campus'])
        self.assertEqual(self.ctx.ui.candidates[0]['kind'], 'institution')

    def test_filing_writes_portal_rows_correctly(self):
        self.circuit()
        c = self.file()
        self.assertTrue(c['ok'], c)
        self.assertEqual(c['apr_number'], '208')                        # the portal's own APR numbering (custom_apr)
        rows = self.db.fetch_all('SELECT event_category, institution, artist, accompanying_artist, budget, fy FROM event_list ORDER BY id')
        self.assertEqual([r['event_category'] for r in rows], ['4', '4', '4'])    # module id, not the name
        self.assertEqual([r['institution'] for r in rows], ['APS Ahmednagar', 'Delhi Public School', 'BITS Pilani Goa Campus'])  # by name, as the portal does
        self.assertEqual({(r['artist'], r['accompanying_artist']) for r in rows}, {('1', '2')})
        self.assertEqual([r['budget'] for r in rows], [23000, 10000, 0])
        self.assertEqual(rows[0]['fy'], '2026-2027')
        self.assertEqual(self.db.count('apr_payment_request'), 3)
        series = self.db.fetch_one('SELECT id, event_id, event_type FROM event_series')
        self.assertEqual((series['event_id'], series['event_type']), ('1,2,3', '288'))
        self.assertEqual({r['added_from'] for r in self.db.fetch_all('SELECT added_from FROM event_list')}, {series['id']})
        apr = self.db.fetch_one('SELECT * FROM custom_apr WHERE id = 208')
        self.assertEqual((apr['event_id'], apr['event_series'], apr['eventgroup'], apr['coordinators_id'], apr['final_submit'], apr['added_by']),
                         ('1,2,3', '288', str(series['id']), '15', 1, 'event_list'))
        self.assertTrue(os.path.exists(self.s.files.path('apr', 'APR_208.pdf')))
        self.assertTrue(any(a['action'] == 'email.dry_run' for a in self.s.gov.list_audit(50)))
        self.assertEqual(len(self.s.gov.get_program_coordinators(self.st.draft.d['outputs']['apr']['request_id'])), 1)

    def test_a_failure_leaves_nothing_behind(self):
        self.circuit()
        self.db.fail_on = 'INSERT INTO apr_payment_request'
        with self.assertRaises(RuntimeError):
            self.s.writer.create(self.st.draft.to_dict(), uid=15)
        self.assertEqual((self.db.count('event_list'), self.db.count('event_series'), self.db.count('custom_apr')), (0, 0, 1))

    def test_different_accompanist_at_one_stop_dc13(self):
        self.circuit()
        r = self.run_tool('set_event_artists', event_index=1, artists=[{'name': 'Ronu Majumdar', 'role': 'main'},
                                                                       {'name': 'Kalpesh Sachala', 'role': 'accompanying'}])
        self.assertEqual(r['not_in_directory'], [])
        self.assertTrue(self.file()['ok'])
        acc = [r['accompanying_artist'] for r in self.db.fetch_all('SELECT accompanying_artist FROM event_list ORDER BY id')]
        self.assertEqual(acc, ['2', '8', '2'])

    def test_stale_or_wrong_confirmation_is_refused(self):
        self.circuit()
        self.assertFalse(self.run_tool('create_apr', confirmation_id='nope')['ok'])
        rv = self.run_tool('review_program')
        self.run_tool('update_program', notes='changed after the review')
        r = self.run_tool('create_apr', confirmation_id=rv['confirmation_id'])
        self.assertFalse(r['ok'])
        self.assertIn('changed', r['error'])
        self.assertEqual(self.db.count('event_list'), 0)


class VirasatTests(SkillTestCase):
    def test_one_institution_several_artists(self):
        self.run_tool('update_program', program_type='virasat', module='Concert')
        self.run_tool('add_events', events=[{'date': '20-01-2027', 'start_time': '10am'},
                                            {'date': '21-01-2027', 'start_time': '10am', 'module': 'Workshop'}])
        self.run_tool('select_institution', institution_id=1)
        self.run_tool('set_event_artists', event_index=0, artists=[{'name': 'Uma Dogra', 'role': 'main'}])
        self.run_tool('set_event_artists', event_index=1, artists=[{'name': 'Shahid Parvez', 'role': 'main'}])
        self.run_tool('add_coordinator', email='sabyasachi@spicmacay.com', role='filer')
        self.assertTrue(self.file()['ok'])
        rows = self.db.fetch_all('SELECT artist, institution, event_category FROM event_list ORDER BY id')
        iitb = 'Indian Institute of Technology Bombay'
        self.assertEqual([(r['artist'], r['institution'], r['event_category']) for r in rows], [('9', iitb, '13'), ('3', iitb, '9')])
        self.assertEqual(self.db.fetch_one('SELECT event_type FROM event_series')['event_type'], '291')
        self.assertEqual(self.db.count('event_series'), 1)


class DirectoryTests(SkillTestCase):
    def test_deceased_artist_needs_confirmation_dc3(self):
        self.assertEqual(self.run_tool('select_artist', artist_id=4, role='main').get('blocked'), 'deceased')
        self.assertTrue(self.run_tool('select_artist', artist_id=4, role='main', acknowledge_flags=True)['ok'])

    def test_new_artist_is_provisional_dc7_dc8(self):
        r = self.run_tool('add_artist', name='Meera Iyer', art_form='Veena', role='accompanying', city='Chennai', state='Tamil Nadu')
        self.assertTrue(r['ok'] and r['provisional'] and r['acg_notified'], r)
        self.assertEqual(self.db.fetch_one('SELECT added_by FROM artists_list WHERE tid = %s', (r['artist_id'],))['added_by'], 'AI-PROV')
        self.assertEqual(self.s.gov.list_approvals()[0]['kind'], 'artist')
        self.assertIn('provisional', self.s.index.search_artists('Meera Iyer')['best']['flags'])
        self.assertEqual(self.st.draft.d['accompanying'][0]['name'], 'Meera Iyer')

    def test_duplicate_artist_is_caught(self):
        r = self.run_tool('add_artist', name='Ronu Mazumdar', art_form='Flute', role='main')
        self.assertFalse(r['ok'])
        self.assertTrue(r['possible_duplicates'])

    def test_coordinators_dc6(self):
        r = self.run_tool('add_coordinator', name='Someone New', email='someone@example.org')
        self.assertTrue(r['not_in_directory'])
        self.assertEqual(self.s.gov.list_approvals()[0]['kind'], 'coordinator_request')
        self.assertTrue(self.run_tool('add_coordinator', email='banashree.roy@spicmacay.com')['ok'])

    def test_several_art_forms_dc10(self):
        self.assertEqual(self.run_tool('select_artist', artist_id=7, role='main')['art_form_options'], ['Vocal', 'Harmonium'])

    def test_switched_off_skill_disappears(self):
        self.s.gov.set_setting('skills.posters.enabled', False, 'test')
        names = [t['function']['name'] for t in self.s.registry.tool_specs(self.s)]
        self.assertNotIn('generate_poster', names)
        self.assertIn('create_apr', names)
        self.assertFalse(self.run_tool('generate_poster')['ok'])


class EmailTests(SkillTestCase):
    def test_payment_requests_one_per_institution(self):
        self.circuit()
        self.file()
        r = self.run_tool('prepare_payment_requests')
        status = {i['institution']: i['status'] for i in r['items']}
        self.assertEqual(status, {'APS Ahmednagar': 'needs_email', 'Delhi Public School': 'ready', 'BITS Pilani Goa Campus': 'skipped'})
        r2 = self.run_tool('prepare_payment_requests', emails=[{'institution': 'APS Ahmednagar', 'email': 'aps@example.org'}])
        self.assertEqual(r2['ready'], 2)
        sent = self.run_tool('send_prepared_emails', confirmation_id=r2['confirmation_id'])
        self.assertEqual((sent['sent'], sent['dry_run']), (2, True))

    def test_admin_can_require_the_send_button(self):
        self.circuit()
        self.file()
        self.s.gov.set_setting('email.require_button_confirmation', True, 'test')
        r = self.run_tool('prepare_payment_requests')
        by_ai = self.s.registry.execute('send_prepared_emails', {'confirmation_id': r['confirmation_id']}, SkillContext(self.s, self.st, via='llm'))
        self.assertTrue(by_ai.get('needs_button'))
        self.assertEqual(self.run_tool('send_prepared_emails', confirmation_id=r['confirmation_id'])['sent'], 1)

    def test_guidelines_only_for_upcoming_events(self):
        self.circuit()
        self.run_tool('update_event', event_index=0, date='01-01-2020')
        names = [i['institution'] for i in self.run_tool('prepare_guidelines')['items']]
        self.assertNotIn('APS Ahmednagar', names)
        self.assertIn('Delhi Public School', names)


class PosterTests(SkillTestCase):
    def test_main_artist_photo_is_required_dc11(self):
        self.circuit()
        r = self.run_tool('generate_poster', event_index=1)
        self.assertTrue(r['needs_artist_photo'])
        self.assertEqual(self.ctx.ui.cards[-1]['type'], 'upload')
        self.assertTrue(poster_service.save_artist_photo(jpeg(), 1))
        r = self.run_tool('generate_poster', event_index=1)
        self.assertTrue(r['ok'], r)
        self.assertEqual(self.s.files.read('poster', r['poster_url'].rsplit('/', 1)[-1])[:3], b'\xff\xd8\xff')


class ImageReadingTests(SkillTestCase):
    llm = FakeLLM()

    def test_poster_fills_the_draft(self):
        self.llm.push({'content': json.dumps({
            'program_type': 'circuit', 'module': 'Lecture Demonstration', 'main_artist': {'name': 'Pt. Ronu Majumdar', 'art_form': 'Flute'},
            'accompanying': [{'name': 'Ajeet Pathak', 'art_form': 'Tabla'}],
            'events': [{'date': '2027-02-14', 'institution': 'APS Ahmednagar', 'start_time': '08:00'},
                       {'date': '2027-02-16', 'institution': 'DPS', 'city': 'Nashik', 'start_time': '10:00'}]})})
        r = extract_poster(self.ctx, base64.b64encode(jpeg()).decode(), 'image/jpeg')
        self.assertTrue(r['ok'], r)
        d = self.st.draft.d
        self.assertEqual((d['program_type'], d['main_artist']['artist_id'], d['accompanying'][0]['artist_id']), ('circuit', 1, 2))
        self.assertEqual([e['institution_id'] for e in d['events']], [3, 2])
        self.assertEqual(self.llm.calls[-1]['response_format'], {'type': 'json_object'})

    def test_cheque_details_are_confirmed_before_saving_dc12(self):
        self.s.gov.set_setting('bank.ifsc_lookup', False, 'test')
        self.llm.push({'content': json.dumps({'account_holder': 'Ajeet Pathak', 'bank_name': 'State Bank of India',
                                              'account_number': '1234 5678 9012', 'ifsc': 'sbin0011781'})})
        r = read_cheque(self.ctx, base64.b64encode(jpeg()).decode(), 'image/jpeg', {'entity': 'artist', 'id': 2, 'name': 'Ajeet Pathak'})
        self.assertEqual(r['problems'], [])
        self.assertEqual(self.ctx.ui.cards[-1]['fields']['Account number'], 'XXXXXXXX9012')
        self.assertIsNone(self.db.fetch_one('SELECT account_number FROM artists_list WHERE tid = 2')['account_number'] or None)
        self.assertTrue(confirm_bank_proposal(self.ctx, r['confirmation_id'])['ok'])
        row = self.db.fetch_one('SELECT account_number, ifsc_code, cancelled_cheque FROM artists_list WHERE tid = 2')
        self.assertEqual((row['account_number'], row['ifsc_code']), ('123456789012', 'SBIN0011781'))
        self.assertTrue(row['cancelled_cheque'].startswith('ai_private/cheques/'))


class OrchestratorTests(unittest.TestCase):
    def test_several_tool_rounds_in_one_message(self):
        llm = FakeLLM([
            {'tool_calls': [('update_program', {'program_type': 'circuit', 'module': 'Lecture Demonstration'}),
                            ('find_artist', {'name': 'Pt Ronu Mazumdar', 'role': 'main'})]},
            {'tool_calls': [('add_events', {'events': CIRCUIT_STOPS[:2]}),
                            ('add_coordinator', {'email': 'sabyasachi@spicmacay.com', 'role': 'filer'})]},
            {'content': 'Done.'}])
        s, _, _ = build_test_services(llm)
        st = ConversationState()
        r = s.orchestrator.run_turn(st, 'Circuit lec dem by Ronu Mazumdar at APS Ahmednagar and DPS Nashik')
        self.assertEqual(len(llm.calls), 3)
        self.assertTrue(all(len(c['tools']) > 30 for c in llm.calls))   # tools offered on every round
        self.assertEqual(r['progress']['done'], 6)
        ids = [c['id'] for m in st.history if m.get('tool_calls') for c in m['tool_calls']]
        self.assertEqual(ids, [m['tool_call_id'] for m in st.history if m.get('role') == 'tool'])

    def test_without_ai_it_degrades_gracefully(self):
        s, _, _ = build_test_services()
        self.assertIn('AI service', s.orchestrator.run_turn(ConversationState(), 'hello')['reply'])


if __name__ == '__main__':
    unittest.main()
