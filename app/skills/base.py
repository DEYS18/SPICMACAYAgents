"""
Skill framework. A skill is a small, independent capability (find an artist, file an APR,
send a Request for Payment, make a poster...). Each exposes tools the assistant can call,
and the same tools are invoked directly when the coordinator taps a button, so behaviour is
identical whether something is spoken, typed or tapped. Administrators can switch any
non-core skill off in Admin > Settings.
"""
import inspect
import logging

logger = logging.getLogger(__name__)


def tool(name, description, properties=None, required=()):
    def deco(fn):
        fn._tool = {'name': name, 'description': description, 'properties': properties or {}, 'required': list(required)}
        return fn
    return deco


def portal_issues(services, draft):
    """Checks only the portal can answer: every module must be one of its modules (event_module)."""
    w = getattr(services, 'writer', None)
    mods = w.modules() if w else []
    if not mods:
        return []
    out, seen = [], set()
    for e in draft.d['events']:
        name = e.get('module') or draft.d.get('module')
        if name and name not in seen:
            seen.add(name)
            if w.module_lookup(name)[0] is None:
                out.append(f'Module "{name}" is not one of the portal\'s modules ({", ".join(m for _, m in mods)}): choose one, or ask an '
                           f'administrator to add it under Admin > Settings > APR > "Modules to add to the portal if missing"')
    return out


class Skill:
    key = ''
    title = ''
    description = ''
    core = False

    def tools(self):
        for _, m in inspect.getmembers(self, predicate=inspect.ismethod):
            meta = getattr(m, '_tool', None)
            if meta:
                yield meta, m


class UICollector:
    """Things the interface should show alongside the reply: tappable candidates, cards
    (review, outbox preview, upload request...) and produced files."""
    def __init__(self):
        self.candidates, self.cards, self.artifacts, self.notices = [], [], [], []

    def to_dict(self):
        return {'candidates': self.candidates, 'cards': self.cards, 'artifacts': self.artifacts, 'notices': self.notices}


class SkillContext:
    def __init__(self, services, state, actor=None, via='llm', ui=None):
        self.s, self.state, self.actor, self.via = services, state, actor or {}, via
        self.ui = ui or UICollector()

    @property
    def draft(self):
        return self.state.draft

    def setting(self, key, default=None):
        return self.s.setting(key, default)

    @property
    def actor_label(self):
        return self.actor.get('email') or self.actor.get('name') or 'coordinator'


class SkillRegistry:
    def __init__(self):
        self.skills = {}
        self._tools = {}

    def register(self, skill):
        self.skills[skill.key] = skill
        for meta, fn in skill.tools():
            self._tools[meta['name']] = (skill, meta, fn)
        return skill

    def enabled(self, key, services) -> bool:
        sk = self.skills.get(key)
        return bool(sk) and (sk.core or bool(services.setting(f'skills.{key}.enabled', True)))

    def tool_specs(self, services):
        return [{'type': 'function', 'function': {'name': meta['name'], 'description': meta['description'],
                                                  'parameters': {'type': 'object', 'properties': meta['properties'],
                                                                 'required': meta['required']}}}
                for sk, meta, _ in self._tools.values() if self.enabled(sk.key, services)]

    def execute(self, name, args, ctx):
        entry = self._tools.get(name)
        if not entry:
            return {'ok': False, 'error': f'Unknown tool {name}'}
        sk, meta, fn = entry
        if not self.enabled(sk.key, ctx.s):
            return {'ok': False, 'error': f'"{sk.title}" is switched off by an administrator.'}
        clean = {k: v for k, v in (args or {}).items() if k in meta['properties'] and v is not None}
        missing = [r for r in meta['required'] if clean.get(r) in (None, '', [])]
        if missing:
            return {'ok': False, 'error': f"Missing: {', '.join(missing)}"}
        try:
            return fn(ctx, **clean)
        except (IndexError, KeyError, ValueError) as e:
            return {'ok': False, 'error': str(e).strip("'")}
        except Exception as e:
            logger.exception('Tool %s failed', name)
            return {'ok': False, 'error': f'{type(e).__name__}: {e}'}

    def describe(self, services):
        return [{'key': sk.key, 'title': sk.title, 'description': sk.description, 'core': sk.core,
                 'enabled': self.enabled(sk.key, services), 'tools': [m['name'] for m, _ in sk.tools()]}
                for sk in self.skills.values()]


# ── shared helpers ───────────────────────────────────────────────────────────
def email_context(ctx, extra=None) -> dict:
    base = {'org': ctx.s.org(), 'coordinator': ctx.draft.filer() or {}, 'admin_url': ctx.s.admin_url()}
    base.update(extra or {})
    return base


def notify(ctx, template_key, to, extra=None, attachments=None) -> bool:
    to = [t for t in (to or []) if t]
    if not to:
        return False
    try:
        msg = ctx.s.renderer.render_email(template_key, email_context(ctx, extra))
    except Exception as e:
        logger.error('Could not render %s: %s', template_key, e)
        return False
    r = ctx.s.mailer.send(to=to, subject=msg['subject'], html=msg['html'], text=msg['text'],
                          attachments=attachments, actor=ctx.actor_label, category=template_key)
    return bool(r.get('ok'))


def program_summary(draft) -> str:
    from app.agents.draft import PROGRAM_TYPES
    d = draft.d
    main = d.get('main_artist') or {}
    parts = [PROGRAM_TYPES.get(d.get('program_type'), 'Program'), f"{len(d['events'])} event(s)"]
    if main.get('name'):
        parts.append(main['name'] + (f" ({main['art_form']})" if main.get('art_form') else ''))
    return ', '.join(parts)
