"""The HTTP API and pages: chat, taps, uploads, voice, downloads, sign-in and the admin console."""
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import FakeLLM, build_test_services  # noqa: E402

from app.assistant_setup import create_assistant_app  # noqa: E402
from app.services import pdf_service, poster_service  # noqa: E402


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.llm = FakeLLM()
        self.s, self.db, self.tmp = build_test_services(self.llm)
        self._dirs = poster_service._ARTIST_PHOTO_DIR, pdf_service.EVENT_PHOTOS_DIR
        poster_service._ARTIST_PHOTO_DIR = os.path.join(self.tmp, 'artist_photos')
        pdf_service.EVENT_PHOTOS_DIR = os.path.join(self.tmp, 'event_photos')
        os.environ['ADMIN_PASSWORD'] = 'test-admin'
        os.environ.pop('AUTH_MODE', None)
        self.app = create_assistant_app(self.s)
        self.c = self.app.test_client()

    def tearDown(self):
        poster_service._ARTIST_PHOTO_DIR, pdf_service.EVENT_PHOTOS_DIR = self._dirs
        os.environ.pop('ADMIN_PASSWORD', None)

    def act(self, type_, payload=None, cont=False):
        return self.c.post('/api/assistant/action', json={'type': type_, 'payload': payload or {}, 'continue': cont})

    def test_pages(self):
        for path in ('/assistant', '/login', '/manifest.webmanifest'):
            self.assertEqual(self.c.get(path).status_code, 200, path)
        page = self.c.get('/assistant').data
        self.assertIn(b'assistant.js', page)
        self.assertIn('हिन्दी'.encode(), page)
        self.assertIn(b'Admin console', self.c.get('/admin').data)      # the admin sign-in form

    def test_start_in_hindi(self):
        j = self.c.post('/api/assistant/start', json={'language': 'hi'}).get_json()
        self.assertIn('नमस्कार', j['reply'])
        self.assertEqual([r['key'] for r in j['recipes']], ['poster', 'batch', 'pending', 'upcoming', 'about'])
        self.assertTrue(j['welcome']['title'].startswith('नमस्कार'))

    def test_chat_to_filed_apr_and_private_download(self):
        self.llm.push(
            {'tool_calls': [('update_program', {'program_type': 'single', 'module': 'Concert'}),
                            ('find_artist', {'name': 'Shahid Pervez', 'role': 'main'}), ('find_institution', {'name': 'IIT Bombay'})]},
            {'tool_calls': [('update_event', {'event_index': 0, 'date': '15-01-2027', 'start_time': '6:30 pm', 'contribution': '50000'}),
                            ('add_coordinator', {'email': 'sabyasachi@spicmacay.com', 'role': 'filer'}), ('review_program', {})]},
            {'content': 'Shall I file it?'})
        self.c.post('/api/assistant/start', json={})
        j = self.c.post('/api/assistant/chat', json={'message': 'Concert by Shahid Pervez at IIT Bombay on 15 Jan, 6:30 pm, Rs 50,000'}).get_json()
        self.assertEqual(j['progress']['done'], 6)
        card = j['ui']['cards'][0]
        self.assertEqual(card['type'], 'review')
        j = self.act('confirm', {'confirmation_id': card['confirmation_id']}).get_json()
        self.assertIn('208', j['reply'])
        url = j['ui']['artifacts'][0]['url']
        self.assertEqual(self.c.get(url).data[:4], b'%PDF')
        self.assertEqual(self.app.test_client().get(url).status_code, 403)

    def test_taps_and_inline_edits(self):
        self.llm.push({'tool_calls': [('find_artist', {'name': 'Ravi Shankar'})]}, {'content': 'Which one?'})
        j = self.c.post('/api/assistant/chat', json={'message': 'Ravi Shankar'}).get_json()
        self.assertIn(5, [c['id'] for c in j['ui']['candidates'][0]['items']])
        j = self.act('select_candidate', {'kind': 'artist', 'id': 5, 'role': 'main', 'label': 'Ravi Shankar Mishra'}).get_json()
        self.assertEqual(j['draft']['main_artist']['name'], 'Ravi Shankar Mishra')
        self.act('add_event')
        self.assertEqual(self.act('update_field', {'path': 'events.0.date', 'value': '15 Oct 2026'}).get_json()['draft']['events'][0]['date'], '2026-10-15')
        self.assertEqual(self.act('update_field', {'path': 'program_type', 'value': 'circuit'}).get_json()['draft']['program_type'], 'circuit')
        self.assertEqual(self.act('run_tool', {'name': 'create_apr', 'args': {}}).status_code, 400)

    def test_circuit_list_upload(self):
        import base64
        csv = b'Date,Institution,City,Contribution\n14-02-2027,APS Ahmednagar,Ahmednagar,23000\n16-02-2027,DPS,Nashik,10000\n'
        j = self.c.post('/api/assistant/upload', json={'kind': 'stops', 'filename': 'circuit.csv', 'mime': 'text/csv',
                                                       'data': base64.b64encode(csv).decode()}).get_json()
        self.assertEqual([e['institution_id'] for e in j['draft']['events']], [3, 2])
        self.assertEqual([e['contribution'] for e in j['draft']['events']], [23000, 10000])

    def test_voice_without_a_key(self):
        self.assertEqual(self.c.post('/api/assistant/voice/speak', json={'text': 'hello'}).status_code, 204)
        self.assertEqual(self.c.post('/api/assistant/voice/transcribe').status_code, 400)
        r = self.c.post('/api/assistant/voice/transcribe', data={'audio': (io.BytesIO(b'x' * 3000), 'speech.webm'), 'language': 'hi'},
                        content_type='multipart/form-data')
        self.assertEqual(r.status_code, 502)
        self.assertIn('not configured', r.get_json()['error'])

    def test_email_sign_in_dc6(self):
        os.environ.update(AUTH_MODE='email_otp', AUTH_DEV_CODES='1')
        try:
            self.assertEqual(self.c.get('/assistant').status_code, 302)
            self.assertEqual(self.c.post('/api/assistant/start', json={}).status_code, 401)
            self.assertEqual(self.c.post('/api/auth/request-code', json={'email': 'stranger@example.org'}).status_code, 403)
            code = self.c.post('/api/auth/request-code', json={'email': 'sabyasachi@spicmacay.com'}).get_json()['dev_code']
            self.assertEqual(self.c.post('/api/auth/verify', json={'email': 'sabyasachi@spicmacay.com', 'code': '000000'}).status_code, 401)
            self.assertEqual(self.c.post('/api/auth/verify', json={'email': 'sabyasachi@spicmacay.com', 'code': code}).status_code, 200)
            j = self.c.post('/api/assistant/start', json={}).get_json()
            self.assertEqual(j['draft']['coordinators'][0]['email'], 'sabyasachi@spicmacay.com')   # the filer is known
        finally:
            os.environ.pop('AUTH_MODE', None)
            os.environ.pop('AUTH_DEV_CODES', None)

    def test_admin_console(self):
        self.assertEqual(self.c.get('/admin/api/templates').status_code, 403)
        self.assertEqual(self.c.post('/admin/login', json={'password': 'wrong'}).status_code, 401)
        self.assertEqual(self.c.post('/admin/login', json={'password': 'test-admin'}).status_code, 200)
        self.assertIn(b'admin.js', self.c.get('/admin').data)
        self.assertEqual(len(self.c.get('/admin/api/templates').get_json()['templates']), 17)
        p = self.c.post('/admin/api/preview', json={'key': 'email.payment_request'}).get_json()
        self.assertEqual(p['type'], 'html')
        self.assertIn('DPS Nashik', p['html'])
        self.assertEqual(self.c.post('/admin/api/preview', json={'key': 'layout.apr.circuit'}).get_json()['type'], 'pdf')
        self.assertTrue(self.c.post('/admin/api/preview', json={'key': 'layout.poster'}).get_json()['data'])
        self.assertEqual(self.c.post('/admin/api/templates/email.payment_request', json={'body': '{% if %}'}).status_code, 400)
        self.assertEqual(self.c.post('/admin/api/templates/layout.apr.single', json={'body': '{"page": {}}'}).status_code, 400)
        short = {'body': '{% extends "email.shell" %}{% block content %}<p>Hello {{ institution.name }}</p>{% endblock %}', 'note': 'shorter'}
        warned = self.c.post('/admin/api/templates/email.payment_request', json=short)
        self.assertEqual(warned.status_code, 409)                      # it drops the amount and the APR number: ask first
        self.assertTrue(warned.get_json()['missing'])
        ok = self.c.post('/admin/api/templates/email.payment_request', json=dict(short, confirm_missing=True)).get_json()
        self.assertEqual(ok['version'], 2)
        self.c.post('/admin/api/templates/email.payment_request/activate', json={'version': 1})
        self.assertEqual(self.s.gov.get_template('email.payment_request')['version'], 1)
        saved = self.c.post('/admin/api/settings', json={'values': {'apr.default_audience': '450', 'skills.posters.enabled': False}}).get_json()
        self.assertEqual(len(saved['saved']), 2)
        self.assertEqual(self.s.setting('apr.default_audience'), 450)
        self.assertEqual(self.c.post('/admin/api/flags', json={'name': 'Test Artist', 'flag': 'inactive'}).status_code, 200)
        for path in ('/admin/api/overview', '/admin/api/approvals', '/admin/api/audit', '/admin/api/flags', '/admin/api/settings'):
            self.assertEqual(self.c.get(path).status_code, 200, path)


if __name__ == '__main__':
    unittest.main()
