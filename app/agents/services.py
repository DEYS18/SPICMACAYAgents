"""Everything a skill may need, gathered in one place and built once per process."""
import logging
import os
from collections import defaultdict

from app.core.rendering import org_context

logger = logging.getLogger(__name__)


class Services:
    def __init__(self, *, governance, index, renderer, pdf, mailer, files, writer=None, event_service=None,
                 db_validator=None, db=None, enricher=None, llm_factory=None, voice=None, poster=None, config=None):
        self.gov, self.index, self.renderer, self.pdf, self.mailer, self.files = governance, index, renderer, pdf, mailer, files
        self.writer, self.event_service, self.db_validator, self.db = writer, event_service, db_validator, db
        self.enricher, self.llm_factory, self.voice, self.poster = enricher, llm_factory, voice, poster
        self.config = config or {}
        self.hooks = defaultdict(list)
        self.registry = self.orchestrator = self.store = None

    def setting(self, key, default=None):
        return self.gov.get_setting(key, default)

    def llm(self):
        if not self.llm_factory:
            return None
        try:
            return self.llm_factory()
        except Exception as e:
            logger.error('AI client unavailable: %s', e)
            return None

    def org(self):
        return org_context(self.setting)

    def file_url(self, kind, filename):
        try:
            from flask import url_for
            return url_for('assistant_api.download_file', kind=kind, filename=filename)
        except Exception:
            return f'/api/assistant/files/{kind}/{filename}'

    def admin_url(self):
        try:
            from flask import url_for
            return url_for('admin.admin_home', _external=True)
        except Exception:
            return '/admin'


def _openai_factory(key):
    holder = {}

    def factory():
        if 'client' not in holder:
            from openai import OpenAI
            holder['client'] = OpenAI(api_key=key, timeout=90)
        return holder['client']
    return factory


def build_services(*, db=None, event_service=None, db_validator=None, instance_dir='instance', smtp=None,
                   openai_key='', google_key='', config=None) -> Services:
    from app.core.default_templates import DEFAULT_FLAGS, DEFAULT_TEMPLATES
    from app.core.files import OutputStore
    from app.core.governance import Governance
    from app.core.mailer import Mailer
    from app.core.rendering import PdfRenderer, TemplateRenderer
    from app.search.resolver import DirectoryIndex, make_db_loaders
    from app.search.web_enrichment import WebEnricher
    from app.services.program_writer import ProgramWriter
    from app.services.voice_service import VoiceService
    os.makedirs(instance_dir, exist_ok=True)
    gov = Governance(os.path.join(instance_dir, 'governance.db'))
    gov.seed_templates(DEFAULT_TEMPLATES)
    gov.seed_flags(DEFAULT_FLAGS)
    loaders = make_db_loaders(db) if db else {'load_artists': list, 'load_institutions': list}
    renderer = TemplateRenderer(gov)
    try:
        from app.services import poster_service
    except Exception as e:
        logger.warning('Posters unavailable: %s', e)
        poster_service = None
    s = Services(governance=gov, index=DirectoryIndex(**loaders, flags_provider=gov.list_flags), renderer=renderer,
                 pdf=PdfRenderer(renderer.text), mailer=Mailer(smtp or {}, gov, os.path.join(instance_dir, 'outbox')),
                 files=OutputStore(os.path.join(instance_dir, 'outputs')), writer=ProgramWriter(db, gov) if db else None,
                 event_service=event_service, db_validator=db_validator, db=db,
                 enricher=WebEnricher(gov, gov.get_setting, google_key),
                 llm_factory=_openai_factory(openai_key) if openai_key else None,
                 voice=VoiceService(openai_key, gov.get_setting), poster=poster_service, config=config)
    return finish(s)


def finish(s):
    from app.agents.orchestrator import Orchestrator
    from app.agents.state import StateStore
    from app.skills import build_registry
    s.registry = build_registry()
    s.orchestrator = Orchestrator(s, s.registry)
    s.store = StateStore(s.gov, s.setting)
    return s
