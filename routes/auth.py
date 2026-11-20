import re, secrets, time
from urllib.parse import urlparse
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, current_app
from flask_login import login_user, logout_user, current_user
from extensions import db
from models.user import User
from services import auth_service as A

bp = Blueprint('auth', __name__)
EMAIL = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')

def home_for(u):
    return url_for('admin.dashboard') if u.role == 'admin' else url_for('citizen.dashboard')

def safe_next(default, admin=False):
    nxt = request.args.get('next', '')
    ok = nxt.startswith('/') and not nxt.startswith('//') and '\\' not in nxt and not urlparse(nxt).netloc
    if ok and nxt.startswith('/admin') == admin:
        return nxt
    return default

def digits(s):
    return re.sub(r'\D', '', s or '')[-10:]

def public_stats():
    """Read-only counters for the public homepage (real database values; None = unavailable, shown as a dash)."""
    try:
        from models.complaint import Complaint
        total = Complaint.query.count()
        solved = Complaint.query.filter_by(status='Resolved').count()
        citizens = User.query.filter_by(role='citizen').count()
        return dict(total=total, solved=solved, citizens=citizens, rate=round(solved * 100 / total) if total else 0)
    except Exception:
        return dict(total=None, solved=None, citizens=None, rate=None)

@bp.route('/')
def landing():
    if current_user.is_authenticated:
        return redirect(home_for(current_user))
    return render_template('landing.html', stats=public_stats())

@bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('auth.landing'))
    if request.method == 'POST':
        f = request.form
        name, email, pw, phone = f.get('name', '').strip()[:60], f.get('email', '').strip().lower(), f.get('password', ''), digits(f.get('phone'))
        err = ('Please enter your name.' if not name else 'Please enter a valid email.' if not EMAIL.match(email)
               else 'Password must be at least 8 characters.' if len(pw) < 8 else 'Passwords do not match.' if pw != f.get('confirm')
               else 'Enter a valid 10-digit phone number or leave it empty.' if f.get('phone', '').strip() and len(phone) != 10
               else 'An account with this email already exists.' if User.query.filter_by(email=email).first()
               else 'This phone number is already registered.' if phone and User.query.filter_by(phone=phone).first() else None)
        if not err:
            u = User(name=name, email=email, phone=phone or None, role='citizen')      # role is never taken from the form
            u.set_password(pw)
            db.session.add(u); db.session.commit()
            session.clear(); login_user(u)
            flash('Welcome! Your account is ready.', 'success')
            return redirect(url_for('citizen.dashboard'))
        flash(err, 'danger')
    return render_template('auth/register.html')

@bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        if current_user.role == 'admin' and request.args.get('switch'):          # footer "Citizen Login" while signed in as an admin
            logout_user(); session.clear()
            flash('You were signed out of the administrator account. Please sign in as a citizen.', 'success')
        else:
            return redirect(url_for('auth.landing'))
    if request.method == 'POST':
        email, pw, ip = request.form.get('email', '').strip().lower(), request.form.get('password', ''), request.remote_addr or ''
        if A.locked_minutes(email, ip):
            flash(f"Too many failed attempts. Please wait {current_app.config['LOCKOUT_MINUTES']} minutes or use OTP login.", 'danger')
        else:
            u = User.query.filter_by(email=email).first() if email else None
            if u and u.check_password(pw):
                if u.role == 'admin':
                    flash('Administrator accounts sign in through the Admin Portal (link in the page footer).', 'warning')
                elif not u.active:
                    flash('This account has been deactivated. Please contact support.', 'danger')
                else:
                    A.record(email, ip, True); session.clear(); login_user(u)
                    return redirect(safe_next(home_for(u)))
            else:
                A.record(email, ip, False); flash('Incorrect email or password.', 'danger')
    return render_template('auth/login.html')

# OTP login (kept from version 1.0; the code is shown on screen because no SMS gateway is connected)
@bp.route('/login/otp', methods=['GET', 'POST'])
def otp_login():
    if current_user.is_authenticated:
        return redirect(url_for('auth.landing'))
    if request.method == 'POST':
        phone = digits(request.form.get('phone'))
        if len(phone) != 10:
            flash('Please enter a valid 10-digit phone number.', 'danger')
        else:
            u = User.query.filter_by(phone=phone).first()
            if u and (u.role != 'citizen' or not u.active):
                flash('This number cannot use OTP login.', 'danger')
            else:
                session['otp'] = {'phone': phone, 'name': request.form.get('name', '').strip()[:60], 'tries': 0,
                                  'code': str(secrets.randbelow(900000) + 100000), 'exp': time.time() + current_app.config['OTP_SECONDS']}
                return redirect(url_for('auth.otp_verify'))
    return render_template('auth/otp_login.html')

@bp.route('/login/otp/verify', methods=['GET', 'POST'])
def otp_verify():
    o = session.get('otp')
    if not o:
        return redirect(url_for('auth.otp_login'))
    if request.method == 'POST':
        if time.time() > o['exp']:
            session.pop('otp', None); flash('Code expired. Please request a new one.', 'danger'); return redirect(url_for('auth.otp_login'))
        o['tries'] += 1; session['otp'] = o
        if o['tries'] > current_app.config['OTP_MAX_TRIES']:
            session.pop('otp', None); flash('Too many wrong codes. Please request a new one.', 'danger'); return redirect(url_for('auth.otp_login'))
        if request.form.get('otp', '').strip() == o['code']:
            u = User.query.filter_by(phone=o['phone']).first()
            if not u:                                                     # first OTP login = quick registration (phone-only account)
                u = User(name=o['name'] or f"Citizen {o['phone'][-4:]}", phone=o['phone'], role='citizen')
                u.set_password(secrets.token_urlsafe(24))               # unusable random password; they can use OTP every time
                db.session.add(u); db.session.commit()
            session.clear(); login_user(u)
            return redirect(url_for('citizen.dashboard'))
        flash('Wrong code. Try again.', 'danger')
    return render_template('auth/otp_verify.html', code=o['code'], phone=o['phone'], seconds=max(0, int(o['exp'] - time.time())))

@bp.route('/forgot-password')
def forgot():
    return render_template('auth/forgot.html')

@bp.route('/logout')
def logout():
    logout_user(); session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('auth.landing'))
