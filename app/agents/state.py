"""Per-conversation state (history, draft, pending confirmations), persisted in the
governance store so a coordinator can start on a phone and finish on a laptop, and so the
app works with several server worker processes."""
import time
import uuid

from app.agents.draft import ProgramDraft

CONFIRM_TTL = 30 * 60


class ConversationState:
    def __init__(self, cid=None, data=None, audience_default=300, payment_required=True):
        data = data or {}
        self.id = cid or data.get('id') or uuid.uuid4().hex
        self.history = data.get('history') or []
        self.draft = ProgramDraft(data.get('draft'), audience_default, payment_required)
        self.language = data.get('language') or 'auto'
        self.pending = data.get('pending') or {}
        self.awaiting = data.get('awaiting')
        self.uploads = data.get('uploads') or {'program_photos': [], 'poster': None}
        self.user = data.get('user') or {}
        self.batch = data.get('batch')
        self.created_at = data.get('created_at') or time.time()

    def to_dict(self):
        return {'id': self.id, 'history': self.history[-120:], 'draft': self.draft.to_dict(), 'language': self.language,
                'pending': self.pending, 'awaiting': self.awaiting, 'uploads': self.uploads, 'user': self.user, 'batch': self.batch,
                'created_at': self.created_at}

    def _expire(self):
        now = time.time()
        for k in [k for k, v in self.pending.items() if now - v.get('created', 0) > CONFIRM_TTL]:
            self.pending.pop(k, None)

    def new_confirmation(self, kind, **data) -> str:
        self._expire()
        cid = uuid.uuid4().hex[:12]
        self.pending[cid] = dict(data, kind=kind, created=time.time())
        return cid

    def get_confirmation(self, cid, kind):
        self._expire()
        p = self.pending.get(cid or '')
        return p if p and p.get('kind') == kind else None

    def take_confirmation(self, cid, kind):
        p = self.get_confirmation(cid, kind)
        if p:
            self.pending.pop(cid, None)
        return p


class StateStore:
    def __init__(self, governance, setting):
        self.gov, self.setting = governance, setting

    def _defaults(self):
        return {'audience_default': int(self.setting('apr.default_audience', 300) or 300),
                'payment_required': bool(self.setting('apr.payment_required_default', True))}

    def load(self, cid):
        data = self.gov.load_conversation(cid) if cid else None
        return ConversationState(cid, data, **self._defaults()) if data else None

    def new(self, user=None):
        st = ConversationState(**self._defaults())
        st.language = self.setting('voice.default_language', 'auto') or 'auto'
        st.user = user or {}
        if st.user.get('email'):
            st.draft.add_coordinator({'uid': st.user.get('uid'), 'name': st.user.get('name'), 'email': st.user['email'],
                                      'phone': st.user.get('phone'), 'chapter': st.user.get('chapter'), 'role': 'filer'})
        return st

    def save(self, st):
        self.gov.save_conversation(st.id, (st.user or {}).get('email'), st.to_dict())
