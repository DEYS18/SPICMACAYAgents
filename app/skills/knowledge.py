"""Questions about SPIC MACAY itself, answered from the movement's own documents by the original assistant's
information agent (WorkflowAgent), so the merged assistant keeps that expertise."""
from app.skills.base import Skill, tool

S = {'type': 'string'}


class KnowledgeSkill(Skill):
    key, title = 'knowledge', 'SPIC MACAY knowledge'
    description = "Answers questions about SPIC MACAY from the movement's own documents."

    @tool('ask_spicmacay_guide', "Answer a question about SPIC MACAY itself (its history, the movement, conventions, chapters, "
          "guidelines, how things are done) from the movement's own documents. Use it for such questions instead of answering "
          "from memory.", {'question': S}, required=('question',))
    def ask_spicmacay_guide(self, ctx, question):
        fn = getattr(ctx.s, 'knowledge', None)
        if not fn:
            return {'ok': False, 'error': 'The SPIC MACAY knowledge guide is not available on this server: answer briefly from '
                                          'general knowledge and say so.'}
        try:
            r = fn(question)
        except Exception as e:
            return {'ok': False, 'error': f'The knowledge guide could not answer just now ({e}).'}
        text = r if isinstance(r, str) else ((r or {}).get('response') or (r or {}).get('answer') or (r or {}).get('output') or '')
        return {'ok': bool(text), 'answer': str(text)[:6000]} if text else {'ok': False, 'error': 'The guide had no answer.'}
