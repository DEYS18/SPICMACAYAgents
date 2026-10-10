"""Wires the APR Assistant v2 into a Flask app: the production app (via init_assistant, called
from create_app) or a standalone/test app (create_assistant_app)."""
import os
import threading

from flask import url_for, Flask, jsonify, redirect, render_template

APP_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(APP_DIR)
LANGUAGES = [('auto', 'Auto'), ('en', 'English'), ('hi', 'हिन्दी'), ('hinglish', 'Hinglish'), ('mr', 'मराठी'),
             ('bn', 'বাংলা'), ('ta', 'தமிழ்'), ('te', 'తెలుగు'), ('kn', 'ಕನ್ನಡ'), ('ml', 'മലയാളം'), ('gu', 'ગુજરાતી'),
             ('pa', 'ਪੰਜਾਬੀ'), ('or', 'ଓଡ଼ିଆ'), ('as', 'অসমীয়া'), ('ur', 'اردو')]


def _install_urls(app):
    from app.core import urls
    urls.install(app)


def register_assistant(app, services):
    _install_urls(app)
    from app.core.auth import auth_mode, bp as auth_bp, current_user, is_admin, require_assistant
    from app.routes.admin import bp as admin_bp
    from app.routes.assistant_api import bp as api_bp
    app.extensions['spicmacay'] = services
    app.register_blueprint(auth_bp)
    app.register_blueprint(api_bp, url_prefix='/api/assistant')
    app.register_blueprint(admin_bp)

    @app.route('/assistant/new')          # the earlier preview address still works
    @app.route('/assistant')
    @require_assistant
    def assistant_page():
        u = current_user() or {}
        return render_template('assistant.html', user=u, is_admin=is_admin(u), auth_mode=auth_mode(), languages=LANGUAGES)

    @app.route('/manifest.webmanifest')
    def webmanifest():
        resp = jsonify({'name': 'SPIC MACAY APR Assistant', 'short_name': 'APR Assistant', 'start_url': './assistant',
                        'display': 'standalone', 'background_color': '#FFFFFF', 'theme_color': '#A3161E',
                        'icons': [{'src': 'static/img/spicmacay-logo.svg', 'sizes': 'any', 'type': 'image/svg+xml'}]})
        resp.mimetype = 'application/manifest+json'
        return resp
    return app


def _legacy_report_hook(app, services):
    def hook(result):
        if not services.setting('reports.send_on_apr_create', False):
            return
        notif = getattr(app, 'notification_service', None)
        if not notif or not services.event_service:
            return
        from app.services.report_service import send_weekly_reports
        ev, ar = list(app.config.get('WEEKLY_EVENTS_REPORT_RECIPIENTS', [])), list(app.config.get('WEEKLY_ARTIST_REPORT_RECIPIENTS', []))
        threading.Thread(target=lambda: send_weekly_reports(services.event_service, notif, ev, ar), daemon=True).start()
    services.hooks['apr_created'].append(hook)


_UNAVAILABLE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>APR Assistant could not start</title><style>body{font:16px/1.55 system-ui,sans-serif;max-width:720px;margin:40px auto;padding:0 18px;color:#2b1d14}
h1{color:#8B0000;font-weight:500}code,pre{background:#f6efe4;border-radius:6px;padding:2px 6px}pre{padding:10px;white-space:pre-wrap}</style></head><body>
<h1>The new APR Assistant could not start</h1><p>The server is running version {version}, but the new assistant failed while starting:</p>
<pre>{reason}</pre><p><strong>Usual fix:</strong> install the packages this version needs, in the same Python environment the server uses, then restart the app:</p>
<pre>pip install -r requirements.txt</pre><p>On a Lilly-managed machine, install through Artifactory. The server log has the full details.</p>
<p>Meanwhile the previous assistant still works: <a href="{classic}">open the previous assistant</a>.</p></body></html>"""


def register_unavailable(app, reason):
    """When the new assistant cannot start, /assistant and /admin say why, instead of "Not Found"."""
    from html import escape
    from app.core.version import APR_VERSION
    taken = {r.rule for r in app.url_map.iter_rules()}

    def page():
        from app.core.urls import relative
        html = (_UNAVAILABLE.replace('{version}', escape(APR_VERSION)).replace('{reason}', escape(reason))   # the page's CSS has braces
                .replace('{classic}', escape(relative('/assistant/classic'))))
        return html, 503, {'Content-Type': 'text/html; charset=utf-8'}
    for rule, endpoint in (('/assistant/new', 'assistant_unavailable'), ('/admin', 'admin_unavailable')):
        if rule not in taken:
            app.add_url_rule(rule, endpoint, page)
    if '/assistant' not in taken:                        # coordinators carry on with the original assistant meanwhile
        from flask import redirect
        from app.core.urls import relative
        app.add_url_rule('/assistant', 'assistant_fallback', lambda: redirect(relative('/assistant/classic')))


def _knowledge_answerer(app):
    """The original assistant's information agent (WorkflowAgent), created on first use."""
    holder = {}

    def answer(question):
        agent = getattr(getattr(app, 'agent', None), 'workflow_agent', None) or holder.get('agent')
        if agent is None:
            from app.models.workflow_agent import WorkflowAgent
            agent = holder['agent'] = WorkflowAgent(api_key=app.config.get('OPENAI_API_KEY') or '')
        return agent.run_workflow(question)
    return answer if app.config.get('OPENAI_API_KEY') else None


def init_assistant(app):
    from app.agents.services import build_services
    services = build_services(db=getattr(app, 'db_manager', None), event_service=getattr(app, 'event_service', None),
                              db_validator=getattr(app, 'db_validator', None),
                              instance_dir=os.getenv('INSTANCE_DIR') or os.path.join(PROJECT_DIR, 'instance'),
                              smtp=app.config.get('SMTP_CONFIG') or {}, openai_key=app.config.get('OPENAI_API_KEY') or '',
                              google_key=os.getenv('GOOGLE_API_KEY', ''), config=app.config)
    _legacy_report_hook(app, services)
    register_assistant(app, services)
    from app.services import classic_bridge
    classic_bridge.install(app, services)
    services.knowledge = _knowledge_answerer(app)      # the original information agent, for questions about SPIC MACAY     # the original assistant gets the improved search and portal records
    return services


def create_assistant_app(services, config=None):
    app = Flask('app', root_path=APP_DIR)
    from app.core.urls import SubPathMiddleware
    app.wsgi_app = SubPathMiddleware(app.wsgi_app, os.getenv('URL_PREFIX', ''))
    app.config.update(SECRET_KEY=os.getenv('SECRET_KEY', 'test-secret'), TESTING=True)
    app.config.update(config or {})
    register_assistant(app, services)

    @app.route('/')
    def root():
        from app.core.urls import relative
        return redirect(relative(url_for('assistant_page')))
    return app
