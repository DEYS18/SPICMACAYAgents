"""The merged assistant: the calm screen, the original assistant's playbook (word for word) driving this version's
tools, intent read from the first input, follow-up buttons only when they apply, the original information agent for
questions about SPIC MACAY, and the welcome spoken as the screen opens."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import build_test_services  # noqa: E402

from app.agents import prompts  # noqa: E402
from app.agents.state import ConversationState  # noqa: E402
from app.skills.base import SkillContext  # noqa: E402

AGENT_PY = os.path.join(os.path.dirname(__file__), '..', 'app', 'models', 'agent.py')


class MergedAssistantTests(unittest.TestCase):
    def setUp(self):
        self.s, _, _ = build_test_services()

    def test_the_original_playbook_drives_this_version(self):
        play = prompts.original_playbook()
        src = open(AGENT_PY, encoding='utf-8').read()
        for section in ('TERMINOLOGY — IMPORTANT:', 'COORDINATOR EMAIL — LOOK IT UP BEFORE ASKING:', 'AFTER THE APR IS CREATED — UPCOMING PROGRAMMES ONLY:',
                        'PAYMENT REMINDERS TO HOST INSTITUTIONS', 'EVENT CATEGORIES — IMPORTANT:'):
            self.assertIn(section, play)
            self.assertIn(section, src)
        text = prompts.system_prompt(self.s, ConversationState(), self.s.registry)
        self.assertTrue(text.startswith(play[:200]))
        for note in ('INTENT FIRST', 'create_event: there is no single call', 'send_payment_reminder: prepare_payment_requests',
                     'ask_spicmacay_guide', 'Nothing is filed or sent without a yes', 'DRAFT:'):
            self.assertIn(note, text)

    def test_the_welcome_asks_nothing(self):
        for lang in ('auto', 'hi', 'en', 'hinglish'):
            w, g = prompts.welcome(lang), prompts.greeting(lang)
            self.assertNotIn('?', w['text'] + g)
            self.assertTrue(w['spoken'])
        self.assertTrue(prompts.greeting('auto').startswith('नमस्कार! 🙏'))      # the original's Hindi-first welcome

    def test_follow_up_buttons_only_when_they_apply(self):
        st = ConversationState()
        self.assertEqual(prompts.suggestions(self.s, st), [])                     # nothing offered before anything is said
        st.draft.add_events([{'date': '15-11-2026', 'institution': 'IIT Bombay'}]) if hasattr(st.draft, 'add_events') else \
            st.draft.d['events'].append({'date': '2026-11-15', 'institution': {'sid': 1, 'institution_name': 'IIT Bombay'}})
        labels = ' '.join(c['label'] for c in prompts.suggestions(self.s, st))
        self.assertIn('Circuit', labels)

    def test_questions_about_spic_macay_go_to_the_original_information_agent(self):
        asked = []
        self.s.knowledge = lambda q: asked.append(q) or {'response': 'SPIC MACAY was founded in 1977 by Dr Kiran Seth.'}
        ctx = SkillContext(self.s, ConversationState(), via='llm')
        r = self.s.registry.execute('ask_spicmacay_guide', {'question': 'When was SPIC MACAY founded?'}, ctx)
        self.assertEqual((r['ok'], asked), (True, ['When was SPIC MACAY founded?']))
        self.assertIn('1977', r['answer'])
        self.s.knowledge = None
        self.assertFalse(self.s.registry.execute('ask_spicmacay_guide', {'question': 'x'}, ctx)['ok'])

    def test_the_screen_speaks_and_has_a_speaker(self):
        from app.assistant_setup import create_assistant_app
        c = create_assistant_app(self.s).test_client()
        html = c.get('/assistant').get_data(as_text=True)
        self.assertIn('id="btn-speaker"', html)
        self.assertIn('Original screen', html)
        js = c.get('/static/js/assistant.js').get_data(as_text=True)
        self.assertIn('function speakWelcome', js)
        self.assertIn('Tap to hear the welcome', js)
        self.assertTrue(c.post('/api/assistant/start', json={}).get_json()['welcome']['spoken'])


if __name__ == '__main__':
    unittest.main()
