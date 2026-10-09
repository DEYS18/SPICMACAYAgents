"""
Per-conversation agent sessions.

Every conversation's state — the message history, the APR being assembled, the pending
poster and photos — lives on the agent instance itself. A single shared instance therefore
puts all users into one conversation: one person's reset wipes another's half-finished
APR, and a poster uploaded in one tab surfaces in someone else's chat.

Each browser tab gets its own agent instead. The key is a per-tab id (held in the client's
sessionStorage, so tabs don't share it) scoped under a server-issued id in Flask's signed
cookie — a guessed or forged tab id can therefore only ever reach the same browser's own
conversations, never another user's.
"""
import logging
import re
import threading
import time
import uuid
from collections import OrderedDict
from contextlib import contextmanager

from flask import current_app, request, session

logger = logging.getLogger(__name__)

# An abandoned tab shouldn't hold its agent — and the base64 photos attached to it —
# in memory forever. Idle conversations are dropped; the cap bounds a traffic spike.
SESSION_TTL_SECONDS = 8 * 60 * 60
MAX_SESSIONS = 400

_TAB_ID_RE = re.compile(r'[^A-Za-z0-9_-]')


class _Session:
    """One conversation: its agent, a lock, and the timestamps used for eviction."""

    __slots__ = ('agent', 'lock', 'created_at', 'last_used')

    def __init__(self, agent):
        self.agent = agent
        # Serialises concurrent requests from the same tab, so two messages in flight
        # can't interleave their mutations of a single conversation
        self.lock = threading.RLock()
        self.created_at = time.time()
        self.last_used = self.created_at


class ConversationRegistry:
    """Thread-safe map of conversation key -> agent, with idle and capacity eviction."""

    def __init__(self, factory, ttl=SESSION_TTL_SECONDS, max_sessions=MAX_SESSIONS):
        self._factory = factory
        self._ttl = ttl
        self._max = max_sessions
        self._sessions = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> _Session:
        now = time.time()
        with self._lock:
            self._evict_idle(now)

            entry = self._sessions.get(key)
            if entry is None:
                entry = _Session(self._factory())
                self._sessions[key] = entry
                logger.info(
                    f"New conversation session {key[:14]}… "
                    f"({len(self._sessions)} active)"
                )

            entry.last_used = now
            self._sessions.move_to_end(key)

            while len(self._sessions) > self._max:
                stale_key, _ = self._sessions.popitem(last=False)
                logger.warning(
                    f"Session cap reached — evicted least recently used {stale_key[:14]}…"
                )
            return entry

    def drop(self, key: str) -> bool:
        with self._lock:
            return self._sessions.pop(key, None) is not None

    def _evict_idle(self, now: float):
        expired = [k for k, s in self._sessions.items() if now - s.last_used > self._ttl]
        for key in expired:
            self._sessions.pop(key, None)
            logger.info(f"Expired idle conversation session {key[:14]}…")

    def stats(self) -> dict:
        with self._lock:
            now = time.time()
            return {
                'active_sessions': len(self._sessions),
                'oldest_idle_seconds': int(
                    max((now - s.last_used for s in self._sessions.values()), default=0)
                ),
            }


def _browser_id() -> str:
    """Server-issued id in the signed session cookie — one per browser."""
    sid = session.get('sid')
    if not sid:
        sid = uuid.uuid4().hex
        session['sid'] = sid
        session.permanent = True
    return sid


def _tab_id() -> str:
    """Client-supplied per-tab id. Sanitised — it is used to build a registry key."""
    raw = request.headers.get('X-Conversation-Id') or ''
    clean = _TAB_ID_RE.sub('', raw)[:64]
    # Older clients that don't send the header still work; they just share one
    # conversation per browser, which is the previous behaviour minus the cross-user bleed
    return clean or 'default'


def conversation_key() -> str:
    return f"{_browser_id()}:{_tab_id()}"


def _registry() -> ConversationRegistry:
    registry = getattr(current_app, 'conversation_registry', None)
    if registry is None:
        raise RuntimeError('Conversation registry not initialised')
    return registry


@contextmanager
def session_agent():
    """
    Yield this tab's agent, holding its lock for the duration of the request.

    Use for anything that reads or mutates conversation state, so a second request
    from the same tab waits rather than corrupting the first one's state.
    """
    entry = _registry().get(conversation_key())
    with entry.lock:
        yield entry.agent


def reset_session() -> None:
    """Drop this tab's conversation entirely; the next request builds a fresh agent."""
    _registry().drop(conversation_key())


def registry_stats() -> dict:
    return _registry().stats()
