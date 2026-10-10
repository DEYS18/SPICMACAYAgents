"""
Every call to the OpenAI API goes through here, so the assistant works across model families.

- GPT-4o and GPT-4.1 take `temperature`.
- GPT-5.x and GPT-6 are reasoning models: they take a reasoning effort, and accept `temperature` /
  `top_p` only when the effort is "none" (OpenAI model guidance, 2026).
- GPT-6 Astra and GPT-6.1 Sol need the Responses API for tool calling; GPT-5.5 and earlier support
  tools in Chat Completions. With assistant.api = "auto" the right one is picked from the model name.
If a model still rejects an optional parameter, it is dropped, the call retried, and the model
remembered so the error is not repeated.
"""
import logging
import re
import threading

logger = logging.getLogger(__name__)
REASONING_PREFIXES = ('gpt-5', 'gpt-6', 'o1', 'o3', 'o4')
OPTIONAL = ('temperature', 'top_p', 'reasoning_effort', 'reasoning', 'safety_identifier', 'response_format', 'text',
            'include', 'store', 'parallel_tool_calls', 'max_tokens', 'tool_choice')
_unsupported, _lock = {}, threading.Lock()


def is_reasoning(model):
    return (model or '').strip().lower().startswith(REASONING_PREFIXES)


def use_responses(model, api='auto'):
    if api in ('chat', 'responses'):
        return api == 'responses'
    return (model or '').strip().lower().startswith('gpt-6')


def _offending(err, kwargs):
    msg = str(err)
    low = msg.lower()
    for name in re.findall(r"['\"`]([a-z_][a-z0-9_.]*)['\"`]", low):
        base = name.split('.')[0]
        if base in kwargs and base in OPTIONAL:
            return base
    if any(w in low for w in ('unsupported', 'not supported', 'unrecognized', 'unknown parameter', 'does not support')):
        for p in OPTIONAL:
            if p in kwargs and p in low:
                return p
    return None


def call_with_fallback(fn, model, kwargs, attempts=4):
    with _lock:
        for p in _unsupported.get(model, ()):
            kwargs.pop(p, None)
    for _ in range(attempts):
        try:
            return fn(**kwargs)
        except Exception as e:
            p = _offending(e, kwargs)
            if not p:
                raise
            logger.warning('Model %s rejected %r; retrying without it', model, p)
            if p == 'max_tokens':
                kwargs['max_completion_tokens'] = kwargs.pop('max_tokens')
            else:
                kwargs.pop(p, None)
            with _lock:
                _unsupported.setdefault(model, set()).add(p)
    return fn(**kwargs)


def dropped_params(model):
    return sorted(_unsupported.get(model, ()))


class Result:
    def __init__(self, content, tool_calls, usage, raw, items=None):
        self.content, self.tool_calls, self.usage, self.raw, self.items = content or '', tool_calls, usage, raw, items or []


def usage_numbers(usage):
    """(input, output, cached) tokens from either API's usage object."""
    if not usage:
        return 0, 0, 0
    g = (lambda o, k: getattr(o, k, None) if not isinstance(o, dict) else o.get(k))
    inp = g(usage, 'prompt_tokens') or g(usage, 'input_tokens') or 0
    out = g(usage, 'completion_tokens') or g(usage, 'output_tokens') or 0
    det = g(usage, 'prompt_tokens_details') or g(usage, 'input_tokens_details')
    cached = (g(det, 'cached_tokens') or 0) if det else 0
    return int(inp or 0), int(out or 0), int(cached or 0)


def _part(p):
    if p.get('type') == 'image_url':
        img = p.get('image_url') or {}
        return {'type': 'input_image', 'image_url': img.get('url'), 'detail': img.get('detail', 'auto')}
    if p.get('type') == 'text':
        return {'type': 'input_text', 'text': p.get('text', '')}
    return p


def to_response_items(messages):
    items = []
    for m in messages:
        role = m.get('role')
        if role == 'tool':
            items.append({'type': 'function_call_output', 'call_id': m['tool_call_id'], 'output': m.get('content') or ''})
        elif role == 'assistant' and m.get('tool_calls'):
            if m.get('content'):
                items.append({'role': 'assistant', 'content': m['content']})
            for tc in m['tool_calls']:
                items.append({'type': 'function_call', 'call_id': tc['id'], 'name': tc['function']['name'],
                              'arguments': tc['function'].get('arguments') or '{}'})
        else:
            content = m.get('content')
            items.append({'role': role, 'content': [_part(p) for p in content] if isinstance(content, list) else (content or '')})
    return items


def _dump(item):
    if isinstance(item, dict):
        return item
    for attr in ('model_dump', 'to_dict', 'dict'):
        if hasattr(item, attr):
            try:
                return getattr(item, attr)(exclude_none=True) if attr == 'model_dump' else getattr(item, attr)()
            except TypeError:
                return getattr(item, attr)()
    return dict(vars(item))


def complete(client, *, model, messages, system=None, tools=None, temperature=0.3, effort='low', json_mode=False,
             user_key=None, api='auto', extra_items=None):
    """One model call, whichever API and model family. `tools` use the Chat Completions shape."""
    reasoning = is_reasoning(model)
    if use_responses(model, api):
        kwargs = {'model': model, 'input': to_response_items(messages) + list(extra_items or []), 'store': False}
        if system:
            kwargs['instructions'] = system
        if tools:
            kwargs['tools'] = [{'type': 'function', 'name': t['function']['name'], 'description': t['function'].get('description', ''),
                                'parameters': t['function']['parameters']} for t in tools]
        if reasoning:
            if effort and effort != 'auto':
                kwargs['reasoning'] = {'effort': effort}
            kwargs['include'] = ['reasoning.encrypted_content']
        if temperature is not None and (not reasoning or effort == 'none'):
            kwargs['temperature'] = temperature
        if json_mode:
            kwargs['text'] = {'format': {'type': 'json_object'}}
        if user_key:
            kwargs['safety_identifier'] = user_key
        resp = call_with_fallback(client.responses.create, model, kwargs)
        items = [_dump(i) for i in (getattr(resp, 'output', None) or [])]
        calls = [{'id': i.get('call_id'), 'name': i.get('name'), 'arguments': i.get('arguments') or '{}'}
                 for i in items if i.get('type') == 'function_call']
        text = getattr(resp, 'output_text', None) or ''.join(
            c.get('text', '') for i in items if i.get('type') == 'message' for c in (i.get('content') or []) if isinstance(c, dict))
        return Result(text, calls, getattr(resp, 'usage', None), resp, items)
    kwargs = {'model': model, 'messages': ([{'role': 'system', 'content': system}] if system else []) + list(messages)}
    if tools:
        kwargs.update(tools=tools, tool_choice='auto')
    if reasoning and effort and effort != 'auto':
        kwargs['reasoning_effort'] = effort
    if temperature is not None and (not reasoning or effort == 'none'):
        kwargs['temperature'] = temperature
    if json_mode:
        kwargs['response_format'] = {'type': 'json_object'}
    if user_key:
        kwargs['safety_identifier'] = user_key
    resp = call_with_fallback(client.chat.completions.create, model, kwargs)
    msg = resp.choices[0].message
    calls = [{'id': c.id, 'name': c.function.name, 'arguments': c.function.arguments or '{}'} for c in (getattr(msg, 'tool_calls', None) or [])]
    return Result(msg.content, calls, getattr(resp, 'usage', None), resp)


def install_compat_shim():
    """Make the classic assistant and guides work with GPT-5.x / GPT-6 too: drop temperature/top_p for
    reasoning models, rename max_tokens, and retry without any optional parameter a model rejects."""
    try:
        from openai.resources.chat.completions import Completions
    except Exception:
        return False
    if getattr(Completions.create, '_sm_compat', False):
        return True
    original = Completions.create

    def create(self, *args, **kwargs):
        model = kwargs.get('model', '')
        if is_reasoning(model):
            if kwargs.get('reasoning_effort') != 'none':
                kwargs.pop('temperature', None)
                kwargs.pop('top_p', None)
            if 'max_tokens' in kwargs and 'max_completion_tokens' not in kwargs:
                kwargs['max_completion_tokens'] = kwargs.pop('max_tokens')
        return call_with_fallback(lambda **kw: original(self, *args, **kw), model, kwargs)
    create._sm_compat = True
    Completions.create = create
    return True
