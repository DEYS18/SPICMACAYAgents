"""
The agent loop. The previous assistant asked the model a follow-up question *without* its
tools after the first round, so it could only take one step per message (search an artist,
then stop). Here the model may chain several tool rounds per message (search the artist,
match the institutions, record the dates, review) until it has something worth saying.
"""
import hashlib
import json
import logging

from app.agents import llm, prompts
from app.skills.base import SkillContext

logger = logging.getLogger(__name__)


def window(history, limit=40):
    """Recent history for the model, always starting at a user turn so every tool call
    stays paired with its result."""
    start = max(0, len(history) - limit)
    idx = next((i for i in range(start, len(history)) if history[i].get('role') == 'user'), None)
    if idx is None:
        idx = next((i for i in range(len(history) - 1, -1, -1) if history[i].get('role') == 'user'), len(history))
    return [{k: v for k, v in m.items() if k in ('role', 'content', 'tool_calls', 'tool_call_id')} for m in history[idx:]]


def _clip(s, n=6000):
    return s if len(s) <= n else s[:n] + '... (truncated)'


class Orchestrator:
    def __init__(self, services, registry):
        self.s, self.registry = services, registry

    def result(self, state, ctx, reply):
        d = state.draft
        return {'reply': reply, 'draft': d.to_dict(), 'issues': d.issues(), 'progress': d.progress(),
                'ui': ctx.ui.to_dict(), 'suggestions': prompts.suggestions(self.s, state),
                'conversation_id': state.id, 'language': state.language}

    def run_turn(self, state, user_text=None, actor=None, ui=None):
        ctx = SkillContext(self.s, state, actor=actor, via='llm', ui=ui)
        if user_text:
            state.history.append({'role': 'user', 'content': user_text})
        client = self.s.llm()
        if client is None:
            reply = ('The AI service is not set up on this server yet (OPENAI_API_KEY). You can still fill in the draft '
                     'by tapping its fields, and file or send from the buttons.')
            state.history.append({'role': 'assistant', 'content': reply})
            return self.result(state, ctx, reply)
        tools = self.registry.tool_specs(self.s)
        model = self.s.setting('assistant.model', 'gpt-4o')
        api = self.s.setting('assistant.api', 'auto')
        effort = self.s.setting('assistant.reasoning_effort', 'low')
        temperature = float(self.s.setting('assistant.temperature', 0.3))
        rounds = max(1, int(self.s.setting('assistant.max_tool_rounds', 8)))
        responses = llm.use_responses(model, api)
        user_key = hashlib.sha256(((actor or {}).get('email') or state.id).encode()).hexdigest()[:32]
        turn_start, extra, reply = len(state.history), [], None
        for _ in range(rounds):
            system = prompts.system_prompt(self.s, state, self.registry)
            messages = window(state.history[:turn_start] if responses else state.history)
            try:
                res = llm.complete(client, model=model, system=system, messages=messages, tools=tools, temperature=temperature,
                                   effort=effort, user_key=user_key, api=api, extra_items=extra if responses else None)
            except Exception as e:
                kind, msg = llm.describe_ai_error(e)
                logger.exception('AI call failed (%s)', kind)
                llm.record_ai_result(self.s.gov, False, kind, msg)
                reply = msg + (' Your draft is saved.' if kind in ('rate', 'network', 'other') else
                               ' Your draft is saved, and tapping and editing it still work.')
                break
            llm.record_ai_result(self.s.gov, True)
            try:
                self.s.gov.add_usage(model, *llm.usage_numbers(res.usage))
            except Exception:
                pass
            if not res.tool_calls:
                reply = (res.content or '').strip() or 'Done.'
                break
            state.history.append({'role': 'assistant', 'content': res.content or None,
                                  'tool_calls': [{'id': c['id'], 'type': 'function',
                                                  'function': {'name': c['name'], 'arguments': c['arguments']}} for c in res.tool_calls]})
            if responses:
                extra.extend(res.items)
            for c in res.tool_calls:
                try:
                    args = json.loads(c['arguments'] or '{}')
                except json.JSONDecodeError:
                    result = {'ok': False, 'error': 'The arguments were not valid JSON.'}
                else:
                    result = self.registry.execute(c['name'], args, ctx)
                logger.info('tool %s -> %s', c['name'], 'ok' if result.get('ok', True) else result.get('error'))
                out = _clip(json.dumps(result, default=str, ensure_ascii=False))
                state.history.append({'role': 'tool', 'tool_call_id': c['id'], 'content': out})
                if responses:
                    extra.append({'type': 'function_call_output', 'call_id': c['id'], 'output': out})
        if reply is None:
            reply = "I've updated the draft. What would you like to do next?"
        state.history.append({'role': 'assistant', 'content': reply})
        return self.result(state, ctx, reply)
