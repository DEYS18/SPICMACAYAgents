"""Admin > Templates governs every template family: emails, APR layouts, the Request for Payment document, the
event guidelines document, posters and the assistant's house rules. Minor edits save straight away; an edit that
drops a part the original relies on asks first; the guidelines PDF is versioned and attached by both assistants."""
import io
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import build_test_services  # noqa: E402

from app.assistant_setup import create_assistant_app  # noqa: E402
from app.core.documents import DOCUMENTS, document_path  # noqa: E402

KEY = 'doc.event_guidelines'
REVISED = b'%PDF-1.4\n% revised guidelines 2027\n'


class GovernanceScreensTests(unittest.TestCase):
    def setUp(self):
        os.environ['ADMIN_PASSWORD'] = 'k'
        self.s, self.db, _ = build_test_services()
        self.c = create_assistant_app(self.s).test_client()
        self.c.post('/admin/login', json={'password': 'k'})

    def tearDown(self):
        os.environ.pop('ADMIN_PASSWORD', None)

    def test_every_template_family_is_governed(self):
        keys = {t['key'] for t in self.c.get('/admin/api/templates').get_json()['templates']}
        for k in ('email.apr_confirmation', 'email.payment_request', 'email.pre_event_guidelines', 'layout.apr.single',
                  'layout.apr.circuit', 'layout.apr.virasat', 'layout.rfp', 'layout.poster', KEY, 'prompt.house_rules'):
            self.assertIn(k, keys)

    def test_minor_edits_save_and_major_parts_are_not_lost_by_accident(self):
        t = self.c.get('/admin/api/templates/email.payment_request').get_json()['template']
        ok = self.c.post('/admin/api/templates/email.payment_request', json={'body': t['body'] + '<p>With warm regards from the chapter.</p>',
                                                                             'subject': t['subject']})
        self.assertEqual(ok.status_code, 200, ok.get_json())
        expr = next(e for e in re.findall(r'\{\{\s*(.+?)\s*\}\}', t['body']) if e not in (t['subject'] or ''))
        cut = re.sub(r'\{\{\s*' + re.escape(expr) + r'\s*\}\}', '', t['body'])
        r = self.c.post('/admin/api/templates/email.payment_request', json={'body': cut, 'subject': t['subject']})
        self.assertEqual(r.status_code, 409)
        self.assertIn(re.sub(r'\s+', '', expr), r.get_json()['missing'])
        forced = self.c.post('/admin/api/templates/email.payment_request', json={'body': cut, 'subject': t['subject'], 'confirm_missing': True})
        self.assertEqual(forced.status_code, 200)

    def upload(self, data, name='Guidelines 2027.pdf'):
        return self.c.post(f'/admin/api/documents/{KEY}', data={'file': (io.BytesIO(data), name), 'note': '2027 edition'},
                           content_type='multipart/form-data')

    def test_the_guidelines_document_is_versioned_and_attached_by_both_assistants(self):
        original = DOCUMENTS[KEY]['default']
        self.assertTrue(os.path.exists(original))
        self.assertEqual(document_path(self.s, KEY)[0], original)                 # version 1 is the original PDF
        r = self.upload(REVISED)
        self.assertEqual(r.status_code, 200, r.get_json())
        uploaded = r.get_json()['version']
        self.assertEqual(open(document_path(self.s, KEY)[0], 'rb').read(), REVISED)
        self.assertEqual(self.c.get(f'/admin/api/documents/{KEY}/file').data, REVISED)
        es = self.s.event_service
        es.portal = self.s
        self.assertEqual(es._load_guidelines_pdf(), REVISED)                     # the original screen attaches it too
        self.assertEqual(self.upload(b'hello', 'notes.pdf').status_code, 400)    # only real PDFs
        self.c.post(f'/admin/api/templates/{KEY}/reset', json={})
        self.assertEqual(document_path(self.s, KEY)[0], original)
        self.c.post(f'/admin/api/templates/{KEY}/activate', json={'version': uploaded})
        self.assertEqual(open(document_path(self.s, KEY)[0], 'rb').read(), REVISED)

    def test_the_new_assistant_attaches_the_active_version(self):
        src = open(os.path.join(os.path.dirname(__file__), '..', 'app', 'skills', 'output_skills.py'), encoding='utf-8').read()
        self.assertIn("document_path(ctx.s, 'doc.event_guidelines')", src)
        self.assertNotIn("{'path': GUIDELINES_PDF", src)


if __name__ == '__main__':
    unittest.main()


class HomePageTests(unittest.TestCase):
    def test_the_home_page_leads_to_the_admin_console(self):
        from flask import Blueprint, render_template
        s, _, _ = build_test_services()
        app = create_assistant_app(s)
        src = open(os.path.join(app.root_path, 'templates', 'index.html'), encoding='utf-8').read()
        knowledge = Blueprint('knowledge', __name__)
        knowledge.add_url_rule('/_stand_in/agents', 'list_agents', lambda: '')
        app.register_blueprint(knowledge)
        for ep in set(re.findall(r"url_for\(['\"]([a-z_]+)['\"]", src)) - {'static'} - set(app.view_functions):
            app.add_url_rule(f'/_stand_in/{ep}', ep, lambda: '')
        with app.test_request_context('/'):
            html = render_template('index.html')
        self.assertIn('href="./admin"', html)                               # relative, so it works under a sub-path too
        self.assertIn('Admin Console', html)
        self.assertIn('href="./assistant"', html)
        self.assertEqual(html.count('href="https://spicmacay.in"'), 1)
