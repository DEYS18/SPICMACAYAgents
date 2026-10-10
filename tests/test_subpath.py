"""The app under a sub-path nobody configured, as on spicmacay.in: a proxy strips the prefix and says nothing.
Before the fix every script and style pointed at the site root ("Refused to execute script ... MIME type
('text/html')", then "startWithMessage is not defined")."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import build_test_services  # noqa: E402

from app.assistant_setup import create_assistant_app  # noqa: E402
from app.core.urls import prefix_from_headers  # noqa: E402

P = '/spicmacay_ai_agent/New_AI_Portal'


class SubPathTests(unittest.TestCase):
    def setUp(self):
        for k in ('URL_PREFIX', 'AUTH_MODE'):
            os.environ.pop(k, None)
        self.s, _, _ = build_test_services()
        self.app = create_assistant_app(self.s)
        self.c = self.app.test_client()

    def tearDown(self):
        for k in ('URL_PREFIX', 'AUTH_MODE'):
            os.environ.pop(k, None)

    def page(self, path, **headers):
        return self.c.get(path, headers=headers).get_data(as_text=True)

    def test_unknown_subpath_gives_relative_addresses(self):
        html = self.page('/assistant')
        self.assertRegex(html, r'src="static/js/assistant\.js\?v=\d+"')
        self.assertIn('href="static/css/assistant.css?v=', html)
        self.assertIn('window.APP_ROOT = (function(r,k)', html)       # the scripts' base, worked out in the browser
        self.assertNotIn('src="/static/', html)

    def test_deeper_pages_step_up(self):
        from flask import render_template
        import re
        src = open(os.path.join(self.app.root_path, 'templates', 'assistant_classic.html')).read()
        for ep in set(re.findall(r"url_for\(['\"]([a-z_.]+)['\"]", src)) - {'static'} - set(self.app.view_functions):
            self.app.add_url_rule(f'/_stand_in/{ep}', ep, lambda: '')     # legacy pages exist only in the full app
        with self.app.test_request_context('/assistant/classic'):
            html = render_template('assistant_classic.html')
        self.assertIn('src="../static/js/unified-chat.js?v=', html)
        self.assertIn('window.startWithMessage = window.startWithMessage ||', html)

    def test_the_iis_header_reveals_the_subpath(self):
        html = self.page('/assistant', **{'X-Original-URL': P + '/assistant'})
        self.assertIn(f'src="{P}/static/js/assistant.js?v=', html)
        self.assertEqual(prefix_from_headers({'PATH_INFO': '/assistant', 'HTTP_X_ORIGINAL_URL': P + '/assistant?x=1'}), P)
        self.assertEqual(prefix_from_headers({'PATH_INFO': '/assistant', 'HTTP_X_ORIGINAL_URL': '/assistant'}), '')

    def test_url_prefix_setting(self):
        os.environ['URL_PREFIX'] = P
        html = create_assistant_app(self.s).test_client().get('/assistant').get_data(as_text=True)
        self.assertIn(f'src="{P}/static/js/assistant.js?v=', html)

    def test_a_proxy_that_keeps_the_prefix(self):
        os.environ['URL_PREFIX'] = P
        self.assertEqual(create_assistant_app(self.s).test_client().get(P + '/assistant').status_code, 200)

    def test_redirects_stay_relative(self):
        os.environ['AUTH_MODE'] = 'email_otp'
        r = self.c.get('/assistant')
        self.assertEqual((r.status_code, r.headers['Location']), (302, 'login?next=/assistant'))
        self.assertEqual(self.c.get('/').headers['Location'], 'assistant')


if __name__ == '__main__':
    unittest.main()
