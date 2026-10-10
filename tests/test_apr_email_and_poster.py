"""October 2026 feedback: the earlier app's email designs, the poster travelling with the APR, and the calendar invite."""
import base64
import email
import glob
import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import FakeLLM, build_test_services  # noqa: E402

from app.assistant_setup import create_assistant_app  # noqa: E402
from app.core.default_templates import DEFAULT_TEMPLATES, sample_context  # noqa: E402
from app.core.governance import Governance  # noqa: E402
from app.core.invites import build_ics  # noqa: E402
from app.core.template_history import V23  # noqa: E402
from app.services import pdf_service, poster_service  # noqa: E402


def jpeg():
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (600, 800), (180, 120, 60)).save(buf, 'JPEG')
    return buf.getvalue()


class AprEmailFlowTests(unittest.TestCase):
    def setUp(self):
        self.llm = FakeLLM()
        self.s, self.db, self.tmp = build_test_services(self.llm)
        self._dirs = poster_service._ARTIST_PHOTO_DIR, pdf_service.EVENT_PHOTOS_DIR
        poster_service._ARTIST_PHOTO_DIR = os.path.join(self.tmp, 'artist_photos')
        pdf_service.EVENT_PHOTOS_DIR = os.path.join(self.tmp, 'event_photos')
        self.c = create_assistant_app(self.s).test_client()
        self.c.post('/api/assistant/start', json={})

    def tearDown(self):
        poster_service._ARTIST_PHOTO_DIR, pdf_service.EVENT_PHOTOS_DIR = self._dirs

    def act(self, type_, payload=None):
        return self.c.post('/api/assistant/action', json={'type': type_, 'payload': payload or {}}).get_json()

    def details(self):
        self.llm.push({'tool_calls': [('update_program', {'program_type': 'single', 'module': 'Concert'}),
                                      ('find_artist', {'name': 'Shahid Pervez', 'role': 'main'}), ('find_institution', {'name': 'IIT Bombay'})]},
                      {'tool_calls': [('update_event', {'event_index': 0, 'date': '15-01-2027', 'start_time': '6:30 pm', 'contribution': '50000'}),
                                      ('add_coordinator', {'email': 'sabyasachi@spicmacay.com', 'role': 'filer'})]}, {'content': 'ok'})
        self.c.post('/api/assistant/chat', json={'message': 'Concert by Shahid Pervez at IIT Bombay on 15 Jan 2027, 6:30 pm, Rs 50,000'})

    def file(self):
        self.llm.push({'tool_calls': [('review_program', {})]}, {'content': 'File it?'})
        j = self.c.post('/api/assistant/chat', json={'message': 'review'}).get_json()
        card = next(x for x in j['ui']['cards'] if x['type'] == 'review')
        return card, self.act('confirm', {'confirmation_id': card['confirmation_id']})

    def mails(self, category):
        out = []
        for f in sorted(glob.glob(os.path.join(self.tmp, 'outbox', f'*-{category}-*.eml'))):
            m = email.message_from_bytes(open(f, 'rb').read())
            html = next(p for p in m.walk() if p.get_content_type() == 'text/html').get_payload(decode=True).decode()
            out.append((m, [p.get_filename() for p in m.walk() if p.get_filename()], html))
        return out

    def test_uploaded_poster_and_calendar_go_with_the_apr(self):
        self.llm.push({'content': json.dumps({'program_type': 'single', 'main_artist': {'name': 'Ustad Shahid Parvez Khan', 'art_form': 'Sitar'},
                                              'events': [{'date': '2027-01-15', 'institution': 'IIT Bombay', 'start_time': '18:30'}]})},
                      {'content': 'Read.'})
        self.c.post('/api/assistant/upload', json={'kind': 'poster', 'data': base64.b64encode(jpeg()).decode(), 'mime': 'image/jpeg'})
        self.details()
        card, _ = self.file()
        self.assertIn('the poster you uploaded', card['sends'])
        (m, files, html), = self.mails('apr_confirmation')
        self.assertEqual(files, ['APR_208.pdf', 'event_poster.jpg', 'SPIC_MACAY_program.ics'])
        self.assertNotIn('\n', m['Subject'].replace('\n ', ' '))           # no contact details leaking into the subject
        self.assertIn('Artist Payment Request (APR) Confirmation', html)
        self.assertIn('along with the program poster', html)

    def test_a_poster_made_before_filing_is_attached(self):
        self.details()
        poster_service.save_artist_photo(jpeg(), 3)
        self.act('run_tool', {'name': 'generate_poster', 'args': {}})
        _, j = self.file()
        (_, files, _), = self.mails('apr_confirmation')
        self.assertIn('event_poster.jpg', files)
        self.assertEqual([a['type'] for a in j['ui']['artifacts']], ['pdf'])     # the poster was already shown when it was made

    def test_filing_makes_the_poster_when_the_photo_is_on_file(self):
        poster_service.save_artist_photo(jpeg(), 3)
        self.details()
        card, j = self.file()
        self.assertIn("a poster made from the main artist's photo", card['sends'])
        self.assertEqual([a['type'] for a in j['ui']['artifacts']], ['pdf', 'image'])
        (_, files, _), = self.mails('apr_confirmation')
        self.assertIn('event_poster.jpg', files)
        self.assertNotIn('Make a poster', [x['label'] for x in j['suggestions']])
        # ...and the Request for Payment sent later carries it too
        r = self.act('run_tool', {'name': 'prepare_payment_requests', 'args': {}})
        ob = next(x for x in r['ui']['cards'] if x['type'] == 'outbox')
        self.act('confirm', {'confirmation_id': ob['confirmation_id'], 'item_ids': ['i1']})
        (_, files, html), = self.mails('payment_request')
        self.assertEqual(files, ['Request_for_Payment.pdf', 'program_poster.jpg'])
        self.assertIn('With Our Thanks', html)
        self.assertIn('SBIN0011781', html)                                        # bank particulars in the email itself

    def test_auto_poster_can_be_switched_off(self):
        self.s.gov.set_setting('apr.auto_poster', False, 'test')
        poster_service.save_artist_photo(jpeg(), 3)
        self.details()
        self.file()
        (_, files, _), = self.mails('apr_confirmation')
        self.assertEqual(files, ['APR_208.pdf', 'SPIC_MACAY_program.ics'])

    def test_a_poster_made_after_filing_is_kept_and_offered_by_email(self):
        self.details()
        self.file()
        poster_service.save_artist_photo(jpeg(), 3)
        j = self.act('run_tool', {'name': 'generate_poster', 'args': {}})
        ob = next(x for x in j['ui']['cards'] if x['type'] == 'outbox')
        self.assertEqual(ob['category'], 'apr_poster')
        self.assertEqual(self.mails('apr_poster'), [])                         # nothing sent before the tap
        self.act('confirm', {'confirmation_id': ob['confirmation_id'], 'item_ids': ['i1']})
        (m, files, html), = self.mails('apr_poster')
        self.assertEqual(files, ['program_poster.jpg', 'APR_208.pdf'])
        self.assertIn('smhighereducation@spicmacay.com', m['Cc'])
        ev = self.db.fetch_one('SELECT image FROM event_list ORDER BY id DESC LIMIT 1')
        self.assertIn('event_poster', ev['image'])                              # kept with the program for later reminders


class TemplateTests(unittest.TestCase):
    def test_every_email_renders_with_sample_data(self):
        s, _, _ = build_test_services()
        for key, t in DEFAULT_TEMPLATES.items():
            if t['kind'] == 'email':
                msg = s.renderer.render_email(key, sample_context(s.org()))
                self.assertIn('Supatra Platform', msg['html'], key)
                self.assertNotIn('\n', msg['subject'], key)

    def test_untouched_v23_emails_move_to_the_restored_design(self):
        g = Governance(os.path.join(tempfile.mkdtemp(), 'g.db'))
        for key, body in V23.items():
            t = DEFAULT_TEMPLATES[key]
            g.save_template(key, body, kind=t['kind'], subject=t.get('subject'), actor='system', note='Default', activate=True)
        g.save_template('email.payment_request', V23['email.payment_request'] + '<p>Our own line.</p>', kind='email', actor='admin', activate=True)
        g.seed_templates(DEFAULT_TEMPLATES)
        self.assertIn('linear-gradient(135deg,#FDEFB8', g.get_template('email.shell')['body'])
        self.assertIn('APR Filed', g.get_template('email.apr_confirmation')['body'])
        self.assertIn('Our own line.', g.get_template('email.payment_request')['body'])     # an administrator's edit is kept
        self.assertIsNotNone(g.get_template('email.apr_poster'))


class CalendarTests(unittest.TestCase):
    def test_ist_times_and_past_events(self):
        from datetime import date
        ics, n = build_ics([{'date': '2027-01-15', 'start_time': '18:30', 'summary': 'Concert; Sitar', 'location': 'IIT Bombay, Mumbai'},
                            {'date': '2020-01-01', 'summary': 'Past'}, {'date': '2027-01-16', 'summary': 'All day'}], 'apr208', date(2026, 10, 10))
        text = ics.decode()
        self.assertEqual(n, 2)
        self.assertIn('DTSTART:20270115T130000Z', text)            # 6:30 pm IST
        self.assertIn('DTSTART;VALUE=DATE:20270116', text)
        self.assertIn('SUMMARY:Concert\\; Sitar', text)
        self.assertNotIn('Past', text)
        self.assertEqual(build_ics([{'date': '2020-01-01'}], 'x', date(2026, 10, 10)), (b'', 0))


if __name__ == '__main__':
    unittest.main()


class ScreenTests(unittest.TestCase):
    """The sides of a laptop screen and the assistant's face (October 2026 feedback)."""
    def page(self, **settings):
        s, _, _ = build_test_services()
        for k, v in settings.items():
            s.gov.set_setting(k, v, 'test')
        return create_assistant_app(s).test_client().get('/assistant').get_data(as_text=True)

    def test_the_sides_hold_the_face_and_the_program_never_a_form(self):
        import re
        html = self.page()
        self.assertIn('id="host-rail"', html)
        self.assertIn('id="program-rail"', html)
        self.assertIn('js/avatar.js', html)
        self.assertNotIn('no-face', html)
        for rail in re.findall(r'<aside class="side.*?</aside>', html, re.S):
            self.assertNotRegex(rail, r'<(input|select|textarea)\b')        # read-only: editing stays in the conversation and the drawer

    def test_the_face_can_be_switched_off(self):
        self.assertIn('class="is-empty no-face"', self.page(**{'assistant.show_face': False}))

    def test_she_speaks_of_herself_in_the_feminine_when_shown(self):
        from app.agents import prompts
        s, _, _ = build_test_services()
        from app.agents.state import ConversationState
        st = ConversationState()
        self.assertIn('in the feminine', prompts.system_prompt(s, st, s.registry))
        self.assertIn('लूँगी', prompts.greeting('hi'))
        s.gov.set_setting('assistant.show_face', False, 'test')
        self.assertNotIn('in the feminine', prompts.system_prompt(s, st, s.registry))
