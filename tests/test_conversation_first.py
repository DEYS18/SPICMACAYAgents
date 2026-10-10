"""The assistant is a conversation first: warm instructions, a personal welcome, a few quiet starters,
house rules that move to the new default only if nobody edited them; and deployment diagnostics."""
import http.server
import json
import os
import sys
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import build_test_services  # noqa: E402

from app.agents import prompts  # noqa: E402
from app.agents.state import ConversationState  # noqa: E402
from app.core.default_templates import DEFAULT_TEMPLATES, SUPERSEDED_DEFAULTS  # noqa: E402
from app.core.governance import Governance  # noqa: E402


class ConversationFirstTests(unittest.TestCase):
    def test_the_instructions_are_conversational(self):
        s, _, _ = build_test_services()
        s.gov.set_setting('assistant.original_playbook', False, 'test')         # the fallback when agent.py is absent
        text = prompts.system_prompt(s, ConversationState(), s.registry)
        self.assertIn('Have a real conversation', text)
        self.assertIn('never make it feel like filling in a form', text)
        self.assertIn('Nothing is filed or sent without a yes', text)          # the safety rules stay
        self.assertNotIn('Ask ONE short question per reply', text)
        self.assertIn('OUTPUTS WANTED: apr', text)                            # a new conversation assumes an APR
        self.assertNotIn('Baithak', text)

    def test_a_personal_welcome(self):
        w = prompts.welcome('en', 'sabyasachi', now=datetime(2026, 10, 10, 18, 5))
        self.assertEqual(w['title'], 'Namaste, Sabyasachi ji')
        self.assertTrue(w['text'].startswith('Good evening!'))
        self.assertEqual(prompts.welcome('hi', 'Banashree Roy')['title'], 'नमस्कार, Banashree जी')
        self.assertEqual(prompts.welcome('en', 'someone@example.org')['title'], 'Namaste')     # never an email as a name
        self.assertIn('Speak', prompts.greeting('en', None, 'Sabyasachi'))

    def test_five_quiet_starters(self):
        s, _, _ = build_test_services()
        st = prompts.recipes('en', s)
        self.assertEqual([x['label'] for x in st], ['Upload a poster', 'Several posters at once', 'Pending payments', 'Upcoming programs', 'About SPIC MACAY'])
        self.assertEqual({x['kind'] for x in st}, {'attach', 'message'})                 # inputs, never a question
        s.gov.set_setting('skills.batch.enabled', False, 'test')
        self.assertNotIn('Several posters at once', [x['label'] for x in prompts.recipes('en', s)])

    def test_house_rules_move_to_the_new_default_only_if_untouched(self):
        old = SUPERSEDED_DEFAULTS['prompt.house_rules'][0]
        g = Governance(os.path.join(tempfile.mkdtemp(), 'g.db'))
        g.save_template('prompt.house_rules', old, kind='prompt', actor='system', note='Default', activate=True)
        g.seed_templates(DEFAULT_TEMPLATES)
        self.assertIn('be warm, respectful and patient', g.get_template('prompt.house_rules')['body'])
        g2 = Governance(os.path.join(tempfile.mkdtemp(), 'g.db'))
        g2.save_template('prompt.house_rules', 'Our own rules.', kind='prompt', actor='admin', activate=True)
        g2.seed_templates(DEFAULT_TEMPLATES)
        self.assertEqual(g2.get_template('prompt.house_rules')['body'], 'Our own rules.')

    def test_the_page_has_no_side_panels(self):
        from app.assistant_setup import create_assistant_app
        s, _, _ = build_test_services()
        html = create_assistant_app(s).test_client().get('/assistant').get_data(as_text=True)
        self.assertNotIn('class="rail"', html)
        self.assertIn('class="is-empty"', html)
        self.assertIn('id="draft-pill"', html)
        self.assertIn('Nothing is filed or sent until you say yes.', html)


class DeploymentDiagnosticsTests(unittest.TestCase):
    def test_a_failed_start_explains_itself(self):
        from flask import Flask
        from app.assistant_setup import register_unavailable
        from app.core import urls
        app = Flask('x')
        urls.install(app)
        register_unavailable(app, "ModuleNotFoundError: No module named 'reportlab'")
        r = app.test_client().get('/assistant/new')
        self.assertEqual(r.status_code, 503)
        body = r.get_data(as_text=True)
        self.assertIn('reportlab', body)
        self.assertIn('pip install -r requirements.txt', body)
        self.assertEqual(app.test_client().get('/admin').status_code, 503)

    def test_installation_check_spots_a_nested_copy(self):
        import e2e_check
        root = Path(tempfile.mkdtemp())
        (root / 'spicmacay_ai_app' / 'app').mkdir(parents=True)
        (root / 'VERSION').write_text('2.0.0 (test)')
        e2e_check.REPORT = {'checks': []}
        e2e_check.check_installation(root)
        self.assertTrue(any(c['result'] == 'FAIL' and 'nested' in c['detail'] for c in e2e_check.REPORT['checks']))

    def test_the_live_site_reports_its_version(self):
        import e2e_check
        replies = {'new': {'apr_assistant': {'version': '2.0.0', 'active': True}}, 'old': {'status': 'healthy'}}
        state = {'which': 'new'}

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                body = json.dumps(replies[state['which']]).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(body)
        srv = http.server.HTTPServer(('127.0.0.1', 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        url = f'http://127.0.0.1:{srv.server_port}'
        try:
            for which, want in (('new', 'PASS'), ('old', 'FAIL')):
                state['which'] = which
                e2e_check.REPORT = {'checks': []}
                e2e_check.check_live(url)
                self.assertEqual(e2e_check.REPORT['checks'][-1]['result'], want)
            self.assertIn('PREVIOUS version', e2e_check.REPORT['checks'][-1]['detail'])
        finally:
            srv.shutdown()


if __name__ == '__main__':
    unittest.main()
