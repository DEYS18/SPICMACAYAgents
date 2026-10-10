"""What people see when the AI service fails: what is wrong and who can fix it, never the raw error text.
Reported case: "Error code: 401 - ... 'Your API key has been invalidated.' ... 'token_invalidated'", shown with
"Could you please try rephrasing your message?", which no rephrasing could fix."""
import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import FakeLLM, build_test_services  # noqa: E402

from app.agents import llm  # noqa: E402
from app.agents.state import ConversationState  # noqa: E402
from app.assistant_setup import create_assistant_app  # noqa: E402

REPORTED = ("Error code: 401 - {'error': {'message': 'Your API key has been invalidated.', 'type': None, "
            "'code': 'token_invalidated', 'param': None}, 'status': 401}")


class APIError(Exception):
    def __init__(self, status, code, msg='x'):
        super().__init__(f"Error code: {status} - {{'error': {{'message': '{msg}', 'code': '{code}'}}}}")
        self.status_code, self.body = status, {'error': {'message': msg, 'code': code}}


class Failing:
    def __init__(self, exc):
        self.exc = exc
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.fail))
        self.models = SimpleNamespace(retrieve=self.fail)

    def fail(self, *a, **k):
        raise self.exc


class AIErrorTests(unittest.TestCase):
    def test_each_kind(self):
        for e, kind in [(Exception(REPORTED), 'auth'), (APIError(401, 'invalid_api_key'), 'auth'),
                        (APIError(429, 'insufficient_quota'), 'quota'), (APIError(429, 'rate_limit_exceeded'), 'rate'),
                        (APIError(404, 'model_not_found'), 'model'), (ConnectionError('Connection refused'), 'network'),
                        (ValueError('odd'), 'other')]:
            self.assertEqual(llm.describe_ai_error(e)[0], kind, str(e))
        msg = llm.describe_ai_error(Exception(REPORTED))[1]
        self.assertIn('token_invalidated', msg)
        self.assertIn('OPENAI_API_KEY', msg)
        self.assertNotIn('rephras', msg)

    def test_the_assistant_says_what_is_wrong(self):
        s, _, _ = build_test_services(Failing(Exception(REPORTED)))
        r = s.orchestrator.run_turn(ConversationState(), 'hello')
        self.assertIn('new OPENAI_API_KEY', r['reply'])
        self.assertIn('draft is saved', r['reply'])
        self.assertNotIn('Error code', r['reply'])
        self.assertEqual(s.gov.cache_get('ai:health', max_age_days=1)['kind'], 'auth')
        s.llm_factory = lambda: FakeLLM([{'content': 'Namaste'}])
        s.orchestrator.run_turn(ConversationState(), 'hello again')
        self.assertTrue(s.gov.cache_get('ai:health', max_age_days=1)['ok'])

    def test_an_administrator_can_check_the_key(self):
        os.environ['ADMIN_PASSWORD'] = 'k'
        try:
            s, _, _ = build_test_services(Failing(Exception(REPORTED)))
            c = create_assistant_app(s).test_client()
            c.post('/admin/login', json={'password': 'k'})
            j = c.post('/admin/api/ai-check', json={}).get_json()
            self.assertFalse(j['ok'])
            self.assertIn('OPENAI_API_KEY', j['message'])
            self.assertEqual(c.get('/admin/api/overview').get_json()['ai_health']['kind'], 'auth')
            s.llm_factory = lambda: SimpleNamespace(models=SimpleNamespace(retrieve=lambda m: {'id': m}))
            self.assertTrue(c.post('/admin/api/ai-check', json={}).get_json()['ok'])
        finally:
            os.environ.pop('ADMIN_PASSWORD', None)


if __name__ == '__main__':
    unittest.main()
