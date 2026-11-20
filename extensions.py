"""Shared objects: SQLAlchemy db, Flask-Login manager, role decorators, CSRF helpers."""
import secrets
from datetime import datetime, timezone
from functools import wraps
from flask import session, request, abort, redirect, url_for
from flask_login import LoginManager, current_user
from flask_sqlalchemy import SQLAlchemy
from markupsafe import Markup

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_message = 'Please log in to continue.'
login_manager.login_message_category = 'warning'

def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)

@login_manager.user_loader
def load_user(uid):
    from models.user import User
    u = db.session.get(User, int(uid))
    return u if u and u.active else None          # deactivated accounts are logged out immediately

@login_manager.unauthorized_handler
def unauthorized():
    admin_area = request.path.startswith('/admin')
    nxt = request.full_path.rstrip('?')
    return redirect(url_for('admin.login' if admin_area else 'auth.login', next=nxt))

def role_required(role):
    def deco(f):
        @wraps(f)
        def w(*a, **k):
            if not current_user.is_authenticated:
                return login_manager.unauthorized()
            if current_user.role != role:
                if role == 'citizen':
                    return redirect(url_for('admin.dashboard'))
                abort(403)
            return f(*a, **k)
        return w
    return deco

citizen_required = role_required('citizen')
admin_required = role_required('admin')

def csrf_token():
    if 'csrf' not in session:
        session['csrf'] = secrets.token_hex(16)
    return session['csrf']

def csrf_input():
    return Markup(f'<input type="hidden" name="csrf_token" value="{csrf_token()}">')

def check_csrf():
    if request.method == 'POST':
        tok = request.form.get('csrf_token') or request.headers.get('X-CSRFToken')
        if not tok or tok != session.get('csrf'):
            abort(400, 'Security token missing or expired. Please go back, refresh the page and try again.')
