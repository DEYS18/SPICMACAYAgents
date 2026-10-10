"""
Addresses that work wherever the app is mounted, even when nobody told it where (no URL_PREFIX in .env and no
X-Forwarded-Prefix from the proxy).

On spicmacay.in the app sits under a sub-path behind a proxy that strips it. Flask then believes it lives at
the site root, so every address it generates (scripts, styles, API calls, redirects) points at the main
website, which answers with an HTML page: "Refused to execute script ... MIME type ('text/html')", and then
"startWithMessage is not defined" because the script never ran.

Three layers, each enough on its own:
1. Server: the original address is read from headers IIS URL Rewrite and common proxies send (X-Original-URL
   and similar), so the app learns its sub-path and absolute addresses come out right.
2. Pages: while the sub-path is unknown, url_for() in templates produces addresses relative to the current
   page ("static/js/chat.js", "../static/js/chat.js"), which the browser resolves under the sub-path it used.
   Static files also carry a version, so browsers never keep a stale script after an upgrade.
3. Scripts: window.APP_ROOT is worked out in the browser from its own address and the page's route.
"""
import json
import os
from urllib.parse import urlsplit

from flask import has_request_context, request
from flask import url_for as _flask_url_for
from markupsafe import Markup

ORIGINAL_URL_HEADERS = ('HTTP_X_ORIGINAL_URL', 'HTTP_X_ORIGINAL_URI', 'HTTP_X_FORWARDED_URI', 'HTTP_X_REWRITE_URL')


def prefix_from_headers(environ):
    """The sub-path the browser used, from the original address a proxy passes on (IIS: X-Original-URL)."""
    path = environ.get('PATH_INFO') or '/'
    for header in ORIGINAL_URL_HEADERS:
        value = environ.get(header)
        if not value:
            continue
        original = urlsplit(value).path or ''
        if original != path and original.endswith(path):
            prefix = original[:len(original) - len(path)].rstrip('/')
            if prefix.startswith('/'):
                return prefix
    return ''


class SubPathMiddleware:
    """Sets SCRIPT_NAME from URL_PREFIX, or else from the original-address headers. A prefix sent by the proxy
    (X-Forwarded-Prefix, applied by ProxyFix) always wins. Also copes with proxies that do NOT strip it."""

    def __init__(self, wsgi_app, fallback_prefix=''):
        self.wsgi_app = wsgi_app
        self.fallback_prefix = (fallback_prefix or '').rstrip('/')

    def __call__(self, environ, start_response):
        if not environ.get('SCRIPT_NAME'):
            prefix = self.fallback_prefix or prefix_from_headers(environ)
            if prefix:
                environ['SCRIPT_NAME'] = prefix
                path = environ.get('PATH_INFO') or ''
                if path == prefix or path.startswith(prefix + '/'):
                    environ['PATH_INFO'] = path[len(prefix):] or '/'
        return self.wsgi_app(environ, start_response)


def _steps():
    return '../' * max(request.path.count('/') - 1, 0)


def relative(url):
    """An app-absolute address ('/assistant') made relative to the current page while the mount point is unknown."""
    if (not has_request_context() or request.script_root or not isinstance(url, str)
            or not url.startswith('/') or url.startswith('//')):
        return url
    return (_steps() + url.lstrip('/')) or './'


def app_url_for(endpoint, **values):
    """url_for for templates: a version on static files, and relative while the mount point is unknown."""
    from flask import current_app
    if endpoint == 'static' and values.get('filename') and 'v' not in values:
        try:
            values['v'] = int(os.path.getmtime(os.path.join(current_app.static_folder, values['filename'])))
        except OSError:
            pass
    url = _flask_url_for(endpoint, **values)
    return url if values.get('_external') else relative(url)


def app_root():
    """The app's root for href attributes, with a trailing slash: absolute when known, else './' or '../'."""
    if not has_request_context():
        return '/'
    return request.script_root + '/' if request.script_root else (_steps() or './')


def app_root_js():
    """A JavaScript expression giving the app's root ('/spicmacay_ai_agent/New_AI_Portal' or ''), worked out in
    the browser from its own address when the server does not know it."""
    route = request.path if has_request_context() else '/'
    known = request.script_root if has_request_context() else ''
    return Markup("(function(r,k){if(k)return k;var p=location.pathname;try{p=decodeURI(p)}catch(e){}"
                  "if(r==='/')return p.replace(/\\/+$/,'');"
                  "return p.slice(-r.length)===r?p.slice(0,p.length-r.length):'';})(%s,%s)" % (json.dumps(route), json.dumps(known)))


ASSET_GUARD = Markup(
    "<script>(function(){window.addEventListener('error',function(e){var t=e.target;"
    "if(!t||!(t.tagName==='SCRIPT'||(t.tagName==='LINK'&&/stylesheet/.test(t.rel))))return;"
    "var u=t.src||t.href||'';if(!u||/fonts\\.g|cdn\\.|cdnjs\\./.test(u))return;"
    "var d=document.getElementById('asset-guard');if(!d){d=document.createElement('div');d.id='asset-guard';"
    "d.setAttribute('role','alert');d.style.cssText='position:fixed;left:0;right:0;bottom:0;z-index:99999;background:#7a1010;"
    "color:#fff;padding:10px 14px;font:14px/1.45 system-ui,sans-serif';(document.body||document.documentElement).appendChild(d);}"
    "d.textContent='Part of this page could not be loaded ('+u+'). If the app runs under a sub-path of the website, set URL_PREFIX "
    "in .env to that path (for example /spicmacay_ai_agent/New_AI_Portal), or have the web server send X-Forwarded-Prefix.';},true);})();"
    "</script>")


def install(app):
    """Use these in every template of the app, classic and new."""
    from app.core.version import APR_VERSION
    app.jinja_env.globals.update(url_for=app_url_for, app_root=app_root, app_root_js=app_root_js, asset_guard=ASSET_GUARD,
                                 apr_version=APR_VERSION)
