"""Wires the APR Assistant v2 into a Flask app: the production app (via init_assistant, called
from create_app) or a standalone/test app (create_assistant_app)."""
import os
import threading

from flask import Flask, jsonify, redirect, render_template

APP_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(APP_DIR)
LANGUAGES = [('auto', 'Auto'), ('en', 'English'), ('hi', 'हिन्दी'), ('hinglish', 'Hinglish'), ('mr', 'मराठी'),
             ('bn', 'বাংলা'), ('ta', 'தமிழ்'), ('te', 'తెలుగు'), ('kn', 'ಕನ್ನಡ'), ('ml', 'മലയാളം'), ('gu', 'ગુજરાતી'),
             ('pa', 'ਪੰਜਾਬੀ'), ('or', 'ଓଡ଼ିଆ'), ('as', 'অসমীয়া'), ('ur', 'اردو')]


def register_assistant(app, services):
    from app.core.auth import auth_mode, bp as auth_bp, current_user, is_admin, require_assistant
    from app.routes.admin import bp as admin_bp
    from app.routes.assistant_api import bp as api_bp
    app.extensions['spicmacay'] = services
    app.register_blueprint(auth_bp)
    app.register_blueprint(api_bp, url_prefix='/api/assistant')
    app.register_blueprint(admin_bp)

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


def init_assistant(app):
    from app.agents.services import build_services
    services = build_services(db=getattr(app, 'db_manager', None), event_service=getattr(app, 'event_service', None),
                              db_validator=getattr(app, 'db_validator', None),
                              instance_dir=os.getenv('INSTANCE_DIR') or os.path.join(PROJECT_DIR, 'instance'),
                              smtp=app.config.get('SMTP_CONFIG') or {}, openai_key=app.config.get('OPENAI_API_KEY') or '',
                              google_key=os.getenv('GOOGLE_API_KEY', ''), config=app.config)
    _legacy_report_hook(app, services)
    register_assistant(app, services)
    return services


def create_assistant_app(services, config=None):
    app = Flask('app', root_path=APP_DIR)
    app.config.update(SECRET_KEY=os.getenv('SECRET_KEY', 'test-secret'), TESTING=True)
    app.config.update(config or {})
    register_assistant(app, services)

    @app.route('/')
    def root():
        return redirect('/assistant')
    return app
