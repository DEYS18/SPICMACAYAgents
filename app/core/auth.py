"""
Sign-in and roles (reviewer comment DC6: controlled access).

AUTH_MODE=open       the assistant is open (as before); the admin console needs ADMIN_PASSWORD
                     or an administrator account.
AUTH_MODE=email_otp  coordinators sign in with a one-time code emailed to an address that is in
                     the coordinator directory; the filer is then known automatically and never
                     asked for a name or email.
Administrators: ADMIN_EMAILS (comma separated) or Admin > Settings > Access, or ADMIN_PASSWORD.
"""
import hmac
import os
import secrets
import time
from functools import wraps

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, session, url_for

bp = Blueprint('auth', __name__)
_LAST_CODE = {}


def auth_mode():
    return (os.getenv('AUTH_MODE') or current_app.config.get('AUTH_MODE') or 'open').lower()


def current_user():
    return session.get('user')


def is_admin(user):
    return bool(user and user.get('role') == 'admin')


def admin_emails():
    s = current_app.extensions.get('spicmacay')
    env = [e.strip().lower() for e in (os.getenv('ADMIN_EMAILS') or '').split(',') if e.strip()]
    return set(env + [e.lower() for e in (s.setting('admin.emails', []) if s else [])])


def assistant_user():
    u = current_user()
    if u:
        return u
    return {'role': 'guest'} if auth_mode() == 'open' else None


def require_assistant(f):
    @wraps(f)
    def wrapper(*a, **k):
        if assistant_user() is None:
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Please sign in first.', 'login_url': url_for('auth.login')}), 401
            from app.core.urls import relative
            return redirect(relative(url_for('auth.login', next=request.path)))
        return f(*a, **k)
    return wrapper


def require_admin(f):
    @wraps(f)
    def wrapper(*a, **k):
        if not is_admin(current_user()):
            if request.path.startswith('/admin/api/'):
                return jsonify({'error': 'Administrators only.'}), 403
            return render_template('login.html', mode='admin', auth_mode=auth_mode(), next=request.path,
                                   admin_password=bool(os.getenv('ADMIN_PASSWORD')))
        return f(*a, **k)
    return wrapper


@bp.get('/login')
def login():
    return render_template('login.html', mode='coordinator', auth_mode=auth_mode(),
                           next=request.args.get('next') or url_for('assistant_page'),
                           admin_password=bool(os.getenv('ADMIN_PASSWORD')))


@bp.post('/api/auth/request-code')
def request_code():
    s = current_app.extensions['spicmacay']
    email = ((request.get_json(silent=True) or {}).get('email') or '').strip().lower()
    if '@' not in email:
        return jsonify({'error': 'Enter your email address.'}), 400
    if time.time() - _LAST_CODE.get(email, 0) < 30:
        return jsonify({'error': 'A code was just sent. Please wait half a minute before asking again.'}), 429
    if not s.index.find_coordinator_by_email(email) and email not in admin_emails():
        return jsonify({'error': "This email isn't in the coordinator directory. Ask your chapter's admin to add you."}), 403
    code = f'{secrets.randbelow(10 ** 6):06d}'
    s.gov.set_login_code(email, code, ttl=600)
    _LAST_CODE[email] = time.time()
    msg = s.renderer.render_email('email.login_code', {'org': s.org(), 'code': code, 'minutes': 10, 'coordinator': {}})
    r = s.mailer.send(to=[email], subject=msg['subject'], html=msg['html'], text=msg['text'], actor=email, category='login_code')
    out = {'ok': bool(r.get('ok')), 'dry_run': bool(r.get('dry_run'))}
    if r.get('dry_run') and (current_app.debug or os.getenv('AUTH_DEV_CODES') == '1'):
        out['dev_code'] = code
    if not r.get('ok'):
        out['error'] = 'The sign-in email could not be sent. Please try again later.'
    return jsonify(out)


@bp.post('/api/auth/verify')
def verify():
    s = current_app.extensions['spicmacay']
    body = request.get_json(silent=True) or {}
    email, code = (body.get('email') or '').strip().lower(), (body.get('code') or '').strip()
    if not s.gov.check_login_code(email, code):
        return jsonify({'error': 'That code is wrong or has expired.'}), 401
    rec = s.index.find_coordinator_by_email(email) or {}
    session.clear()
    session.permanent = True
    session['user'] = {'email': email, 'name': rec.get('name') or email.split('@')[0], 'uid': rec.get('uid'),
                       'role': 'admin' if email in admin_emails() else 'coordinator'}
    s.gov.audit(email, 'auth.login', email)
    return jsonify({'ok': True, 'user': session['user']})


@bp.post('/admin/login')
def admin_login():
    expected = os.getenv('ADMIN_PASSWORD') or ''
    given = (request.get_json(silent=True) or {}).get('password') or request.form.get('password') or ''
    if not expected or not hmac.compare_digest(expected.encode(), given.encode()):
        time.sleep(0.5)
        return jsonify({'error': 'Incorrect password.'}), 401
    u = current_user() or {}
    session['user'] = {'email': u.get('email') or '', 'name': u.get('name') or 'Administrator', 'uid': u.get('uid'), 'role': 'admin'}
    current_app.extensions['spicmacay'].gov.audit('admin', 'auth.admin_login', '')
    return jsonify({'ok': True})


@bp.get('/logout')
def logout():
    session.clear()
    from app.core.urls import relative
    return redirect(relative(url_for('auth.login')))
