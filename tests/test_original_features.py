"""The original assistant's outputs, each on its own or together: printable documents for any name, the
program's own artist on a poster, guidelines reachable on their own, and the "What do you need today?" picker."""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import build_test_services  # noqa: E402

from app.core.pdf_text import pdf_text  # noqa: E402

try:
    import fpdf  # noqa: F401
    HAVE_FPDF = True
except ImportError:
    HAVE_FPDF = False

TRICKY = {'id': 9586, 'title': 'Lec dem', 'start_date': '2026-11-15', 'institution_name': 'St. Xavier’s College – Mumbai', 'city': 'Mumbai',
          'state': 'Maharashtra', 'module_name': 'Lecture Demonstration', 'artist_name': 'Pt. Rāmesh Kumar', 'custom_apr': '208', 'budget': 15000}


class DocumentTests(unittest.TestCase):
    def test_text_any_name_can_be_printed(self):
        self.assertEqual(pdf_text('St. Xavier’s College – “Mumbai” ₹5,000…'), 'St. Xavier\'s College - "Mumbai" Rs.5,000...')
        self.assertEqual(pdf_text('Pt. Rāmesh'), 'Pt. Ramesh')
        self.assertTrue(all(ord(c) < 256 for c in pdf_text('केन्द्रीय विद्यालय')))

    @unittest.skipUnless(HAVE_FPDF, 'fpdf2 is not installed here (it is in requirements.txt)')
    def test_invoice_and_apr_pdf_never_come_out_empty(self):
        from app.services import pdf_service as P
        inv = P.generate_payment_request_pdf({'amount': 15000, 'institute_coordinator_name': 'Fr. D’Souza', 'coordinator_name': 'Sabyasachi'}, TRICKY)
        apr = P.generate_apr_pdf({'custom_apr': '208', 'request_id': 'REQ-1'}, TRICKY, {'name': 'Sabyasachi', 'email': 'x@y.z'})
        self.assertTrue(inv.startswith(b'%PDF') and len(inv) > 1000)
        self.assertTrue(apr.startswith(b'%PDF') and len(apr) > 1000)


class OriginalAgentFeatureTests(unittest.TestCase):
    def test_the_program_lookup_gives_the_artist_id(self):
        s, db, _ = build_test_services()
        es = s.event_service
        es.portal = s
        r = es.create_event({'event_date': '2026-11-15', 'title': 'Lec dem', 'module_name': 'Lecture Demonstration', 'institution_id': 1,
                             'institution_name': 'Indian Institute of Technology Bombay', 'artist_id': 1, 'city': 'Mumbai', 'state': 'Maharashtra'})
        ev = es.get_event_for_resend(r['event_id'])
        self.assertEqual((str(ev['artist_id']), ev['artist_name']), ('1', 'Ronu Majumdar'))

    def test_guidelines_can_be_asked_for_on_their_own(self):
        src = open(os.path.join(os.path.dirname(__file__), '..', 'app', 'models', 'agent_router.py'), encoding='utf-8').read()
        for word in ("'guideline'", "'pre-event'", "'invoice'"):
            self.assertIn(word, src)

    def test_the_agent_is_told_outputs_go_alone_or_together(self):
        from app.services.classic_bridge import prompt_addendum
        self.assertIn('on its own or together', prompt_addendum())

    def test_the_original_screen_asks_nothing_up_front(self):
        from flask import render_template
        from app.assistant_setup import create_assistant_app
        s, _, _ = build_test_services()
        app = create_assistant_app(s)
        src = open(os.path.join(app.root_path, 'templates', 'assistant_classic.html'), encoding='utf-8').read()
        for ep in set(re.findall(r"url_for\(['\"]([a-z_.]+)['\"]", src)) - {'static'} - set(app.view_functions):
            app.add_url_rule(f'/_stand_in/{ep}', ep, lambda: '')
        with app.test_request_context('/assistant'):
            html = render_template('assistant_classic.html')
        self.assertNotIn('need-picker', html)                              # nothing is asked up front
        self.assertIn("I want to send the pre-event guidelines for a program", html)
        self.assertIn('href="./assistant"', html)


if __name__ == '__main__':
    unittest.main()
