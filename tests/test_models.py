"""The OpenAI layer across model families, environment defaults, and one-row-per-day filing."""
import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import FakeLLM, build_test_services  # noqa: E402

from app.agents import llm  # noqa: E402
from app.agents.draft import ProgramDraft, expand_days  # noqa: E402
from app.agents.state import ConversationState  # noqa: E402
from app.skills.base import SkillContext  # noqa: E402

TOOL = [{'type': 'function', 'function': {'name': 'get_draft', 'description': 'd', 'parameters': {'type': 'object', 'properties': {}}}}]


class Rejecting:
    """A Chat Completions client that rejects named parameters the way the API does."""
    def __init__(self, reject):
        self.reject, self.calls = set(reject), []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.calls.append(dict(kw))
        for p in self.reject:
            if p in kw:
                raise RuntimeError(f"Error code: 400 - Unsupported parameter: '{p}' is not supported with this model.")
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='hi', tool_calls=None))], usage=None)


class FakeResponses:
    """Responses API stand-in: first a function call, then a final answer."""
    def __init__(self):
        self.calls = []
        self.responses = SimpleNamespace(create=self.create)

    def create(self, **kw):
        self.calls.append(kw)
        if len(self.calls) == 1:
            return SimpleNamespace(output=[{'type': 'reasoning', 'id': 'rs_1', 'encrypted_content': 'x'},
                                           {'type': 'function_call', 'call_id': 'call_1', 'name': 'update_program',
                                            'arguments': '{"program_type": "circuit"}'}],
                                   output_text='', usage={'input_tokens': 100, 'output_tokens': 20})
        return SimpleNamespace(output=[{'type': 'message', 'content': [{'type': 'output_text', 'text': 'Circuit noted.'}]}],
                               output_text='Circuit noted.', usage={'input_tokens': 120, 'output_tokens': 10})


class ModelLayerTests(unittest.TestCase):
    def test_reasoning_models_get_effort_not_temperature(self):
        f = FakeLLM([{'content': 'ok'}])
        llm.complete(f, model='gpt-5.5', messages=[{'role': 'user', 'content': 'hi'}], tools=TOOL, temperature=0.3, effort='low')
        kw = f.calls[0]
        self.assertNotIn('temperature', kw)
        self.assertEqual(kw['reasoning_effort'], 'low')
        f2 = FakeLLM([{'content': 'ok'}])
        llm.complete(f2, model='gpt-4o', messages=[{'role': 'user', 'content': 'hi'}], temperature=0.3, effort='low')
        self.assertEqual(f2.calls[0]['temperature'], 0.3)
        self.assertNotIn('reasoning_effort', f2.calls[0])

    def test_rejected_parameters_are_dropped_and_remembered(self):
        c = Rejecting({'safety_identifier'})
        r = llm.complete(c, model='test-model-a', messages=[{'role': 'user', 'content': 'hi'}], user_key='abc')
        self.assertEqual(r.content, 'hi')
        self.assertEqual(len(c.calls), 2)
        llm.complete(c, model='test-model-a', messages=[{'role': 'user', 'content': 'again'}], user_key='abc')
        self.assertNotIn('safety_identifier', c.calls[-1])            # learned: no failed call this time
        self.assertEqual(len(c.calls), 3)

    def test_gpt6_uses_responses_with_tools_in_one_turn(self):
        fake = FakeResponses()
        s, _, _ = build_test_services(fake)
        s.gov.set_setting('assistant.model', 'gpt-6-luna', 'test')
        st = ConversationState()
        r = s.orchestrator.run_turn(st, 'It is a circuit')
        self.assertEqual(r['reply'], 'Circuit noted.')
        self.assertEqual(st.draft.d['program_type'], 'circuit')
        second = fake.calls[1]
        self.assertTrue(any(i.get('type') == 'function_call_output' and i['call_id'] == 'call_1' for i in second['input']))
        self.assertTrue(any(i.get('type') == 'reasoning' for i in second['input']))     # reasoning carried within the turn
        self.assertEqual(second['tools'][0]['type'], 'function')
        self.assertIn('name', second['tools'][0])                      # flat Responses tool shape
        self.assertEqual(second['reasoning'], {'effort': 'low'})
        self.assertEqual(sum(u['calls'] for u in s.gov.list_usage()), 2)

    def test_env_model_is_the_default(self):
        s, _, _ = build_test_services()
        os.environ['OPENAI_MODEL'] = 'gpt-5.5'
        try:
            self.assertEqual(s.setting('assistant.model'), 'gpt-5.5')
            self.assertEqual(s.setting('assistant.vision_model'), 'gpt-5.5')
            s.gov.set_setting('assistant.model', 'gpt-5.4-mini', 'test')
            self.assertEqual(s.setting('assistant.model'), 'gpt-5.4-mini')   # an admin choice wins
        finally:
            os.environ.pop('OPENAI_MODEL', None)


class OneRowPerDayTests(unittest.TestCase):
    def test_expansion_and_filing(self):
        d = ProgramDraft()
        d.set_program({'program_type': 'single', 'module': 'Workshop'})
        d.add_event({'date': '09-09-2026', 'end_date': '11-09-2026', 'start_time': '9:30 am - 12:30 pm'})
        expanded, mapping = expand_days(d)
        self.assertEqual([e['date'] for e in expanded.d['events']], ['2026-09-09', '2026-09-10', '2026-09-11'])
        self.assertEqual(mapping, {0: [0, 1, 2]})
        s, db, _ = build_test_services()
        st = ConversationState()
        ctx = SkillContext(s, st, actor={'email': 'sabyasachi@spicmacay.com'}, via='button')
        R = lambda n, **a: s.registry.execute(n, a, ctx)
        R('update_program', program_type='single', module='Workshop')
        R('find_artist', name='Uma Dogra', role='main')
        R('add_events', events=[{'date': '09-09-2026', 'institution': 'DPS Nashik', 'start_time': '9:30 am'}])
        R('update_event', event_index=0, end_date='11-09-2026')
        R('add_coordinator', email='sabyasachi@spicmacay.com', role='filer')
        self.assertIn('3 days, one row each', R('review_program')['summary'])
        c = R('create_apr', confirmation_id=R('review_program')['confirmation_id'])
        self.assertTrue(c['ok'], c)
        self.assertEqual(len(c['event_ids']), 3)
        self.assertEqual(db.count('apr_payment_request'), 3)

    def test_a_typo_range_is_stopped(self):
        d = ProgramDraft()
        d.add_event({'date': '01-09-2026', 'end_date': '30-11-2026'})
        self.assertTrue(any('runs 91 days' in i['message'] for i in d.issues()))


if __name__ == '__main__':
    unittest.main()
