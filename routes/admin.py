import re, secrets
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, current_app, Response, session
from flask_login import login_user, logout_user, current_user
from extensions import db, admin_required, utcnow
from models.user import User
from models.complaint import Complaint, Department, AIDetection, AIPrediction, Notification, AuditLog, STATUSES, PRIORITIES
from services import complaint_service as S, auth_service as A
from services.helpers import save_image

bp = Blueprint('admin', __name__, url_prefix='/admin')
EMAIL = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')

# separate admin authentication
@bp.route('/login', methods=['GET', 'POST'])
def login():
    from routes.auth import safe_next
    if current_user.is_authenticated:
        if current_user.role != 'admin' and request.args.get('switch'):          # footer "Admin Login" while signed in as a citizen
            logout_user(); session.clear()
            flash('You were signed out of your citizen account. Please sign in as an administrator.', 'success')
        else:
            return redirect(url_for('admin.dashboard') if current_user.role == 'admin' else url_for('citizen.dashboard'))
    if request.method == 'POST':
        email, pw, ip = request.form.get('email', '').strip().lower(), request.form.get('password', ''), request.remote_addr or ''
        if A.locked_minutes(email, ip):
            flash(f"Too many failed attempts. Try again in {current_app.config['LOCKOUT_MINUTES']} minutes.", 'danger')
        else:
            u = User.query.filter_by(email=email).first() if email else None
            if u and u.role == 'admin' and u.active and u.check_password(pw):          # citizens can never pass this check
                A.record(email, ip, True); session.clear(); login_user(u)
                S.audit(u.id, 'login'); db.session.commit()
                return redirect(safe_next(url_for('admin.dashboard'), admin=True))
            A.record(email, ip, False); flash('Incorrect email or password.', 'danger')
    return render_template('admin/login.html')

@bp.route('/forgot')
def forgot():
    return render_template('admin/forgot.html')

@bp.route('/logout')
def logout():
    if current_user.is_authenticated and current_user.role == 'admin':
        S.audit(current_user.id, 'logout'); db.session.commit()
    logout_user(); session.clear()
    flash('You have been logged out of the Admin Portal.', 'success')
    return redirect(url_for('admin.login'))

# overview
@bp.route('/')
@admin_required
def dashboard():
    return render_template('admin/dashboard.html', **S.admin_dashboard(request.args.get('days', 14, type=int)))

# complaints
def _filters():
    a = request.args
    return dict(group=a.get('group', ''), status=a.get('status', ''), category=a.get('category', ''), priority=a.get('priority', ''),
                department_id=a.get('department_id', type=int), q=a.get('q', '').strip(), place=a.get('place', '').strip(),
                date_from=a.get('from', ''), date_to=a.get('to', ''), ai=a.get('ai', ''))

@bp.route('/complaints')
@admin_required
def complaints():
    return render_template('admin/complaints.html', rows=S.listing(**_filters()), depts=Department.query.order_by(Department.name).all())

@bp.route('/complaints/export.csv')
@admin_required
def export():
    S.audit(current_user.id, 'export_csv', details=request.query_string.decode()[:200]); db.session.commit()
    return Response(S.export_csv(S.listing(**_filters())), mimetype='text/csv',
                    headers={'Content-Disposition': 'attachment; filename=complaints.csv'})

@bp.route('/complaint/<tid>', methods=['GET', 'POST'])
@admin_required
def detail(tid):
    c = S.get_by_tid(tid)
    if not c:
        abort(404)
    if request.method == 'POST':
        evidence = None
        fs = request.files.get('evidence')
        if fs and fs.filename:
            try:
                evidence = save_image(fs)
            except ValueError as e:
                flash(str(e), 'danger'); return redirect(url_for('admin.detail', tid=c.tracking_id))
        err = S.admin_update(c, current_user, request.form, evidence)
        flash(err or 'Complaint updated and the citizen has been notified.', 'danger' if err else 'success')
        return redirect(url_for('admin.detail', tid=c.tracking_id))
    logs = AuditLog.query.filter_by(complaint_id=c.id).order_by(AuditLog.id.desc()).limit(20).all()
    return render_template('admin/detail.html', c=c, sibs=S.siblings(c), det=c.detection, hist=c.history, stages=STATUSES, priorities=PRIORITIES, logs=logs,
                           depts=Department.query.order_by(Department.name).all())

# AI review
@bp.route('/ai-review')
@admin_required
def ai_review():
    v = request.args.get('v', '')
    q = AIDetection.query
    q = {'pending': q.filter(AIDetection.prediction_verified.is_(None)), 'correct': q.filter(AIDetection.prediction_verified.is_(True)),
         'incorrect': q.filter(AIDetection.prediction_verified.is_(False))}.get(v, q)
    from ai import manager as AIM
    return render_template('admin/ai_review.html', rows=q.order_by(AIDetection.id.desc()).all(), perf=S.admin_dashboard()['ai'], mstats=S.model_stats(), mstatus=AIM.availability(current_app.config), fam=current_app.config.get('AI_FAMILY_BY_FILE') or {})

@bp.route('/ai-review/<int:det_id>', methods=['POST'])
@admin_required
def ai_verdict(det_id):
    d = db.session.get(AIDetection, det_id) or abort(404)
    d.prediction_verified = {'1': True, '0': False}.get(request.form.get('verdict', ''))
    S.audit(current_user.id, 'ai_review', d.complaint, f'verdict={d.prediction_verified}')
    db.session.commit(); flash('AI prediction review saved.', 'success')
    return redirect(url_for('admin.ai_review', v=request.form.get('back', '')))

@bp.route('/ai-prediction/<int:pid>', methods=['POST'])
@admin_required
def ai_prediction_verdict(pid):
    """Admin verdict on one model's prediction (correct / incorrect / reset). Does not change the complaint's category."""
    p = db.session.get(AIPrediction, pid) or abort(404)
    p.verified = {'1': True, '0': False}.get(request.form.get('verdict', ''))
    p.verified_by, p.verified_at = (current_user.id, utcnow()) if p.verified is not None else (None, None)
    S.audit(current_user.id, 'ai_prediction_review', p.complaint, f'{p.model_name}:{p.model_label} verdict={p.verified}')
    db.session.commit(); flash('Prediction review saved.', 'success')
    return redirect(url_for('admin.detail', tid=p.complaint.tracking_id) + '#ai-details')

# map
@bp.route('/map')
@admin_required
def map_view():
    a = request.args
    rows = [c for c in S.listing(status=a.get('status', ''), category=a.get('category', ''), priority=a.get('priority', ''), department_id=a.get('department_id', type=int)) if c.latitude is not None]
    pts = [dict(tracking_id=c.tracking_id, category=c.category, status=c.status, priority=c.priority, votes=c.vote_count, latitude=c.latitude, longitude=c.longitude,
                acc=c.geo.accuracy_m if c.geo else None, src=S.SOURCE_LABEL.get(c.geo.source, '') if c.geo else '', video=bool(c.video_issue)) for c in rows]
    return render_template('admin/map.html', points=pts, depts=Department.query.order_by(Department.name).all())

# departments
@bp.route('/departments', methods=['GET', 'POST'])
@admin_required
def departments():
    if request.method == 'POST':
        act, name = request.form.get('action'), request.form.get('name', '').strip()[:80]
        d = db.session.get(Department, request.form.get('id', type=int)) if request.form.get('id') else None
        if act == 'add' and name:
            if Department.query.filter_by(name=name).first():
                flash('That department already exists.', 'warning')
            else:
                db.session.add(Department(name=name)); S.audit(current_user.id, 'department_add', details=name); flash('Department added.', 'success')
        elif act == 'rename' and d and name:
            S.audit(current_user.id, 'department_rename', details=f'{d.name} -> {name}'); d.name = name; flash('Department renamed.', 'success')
        elif act == 'delete' and d:
            if d.complaints:
                flash('This department still has complaints. Reassign them first.', 'warning')
            else:
                S.audit(current_user.id, 'department_delete', details=d.name); db.session.delete(d); flash('Department deleted.', 'success')
        db.session.commit()
        return redirect(url_for('admin.departments'))
    rows = []
    for d in Department.query.order_by(Department.name).all():
        rows.append({'d': d, 'total': len(d.complaints), 'open': sum(1 for c in d.complaints if c.status != 'Resolved')})
    return render_template('admin/departments.html', rows=rows, unassigned=Complaint.query.filter(Complaint.department_id.is_(None)).count())

# community votes
@bp.route('/votes')
@admin_required
def votes():
    return render_template('admin/votes.html', groups=S.vote_groups())

# admin alerts
@bp.route('/notifications')
@admin_required
def notifications():
    rows = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.id.desc()).limit(100).all()
    return render_template('admin/notifications.html', rows=rows)

@bp.route('/notifications/read-all', methods=['POST'])
@admin_required
def read_all():
    S.mark_read(current_user.id)
    return redirect(url_for('admin.notifications'))

@bp.route('/notifications/<int:nid>/open')
@admin_required
def open_notification(nid):
    n = Notification.query.filter_by(id=nid, user_id=current_user.id).first_or_404()
    S.mark_read(current_user.id, nid)
    return redirect(url_for('admin.detail', tid=n.complaint.tracking_id) if n.complaint else url_for('admin.notifications'))

# reports
@bp.route('/reports')
@admin_required
def reports():
    return render_template('admin/reports.html', **S.analytics(request.args.get('days', 30, type=int)))

# users
@bp.route('/users')
@admin_required
def users():
    rows = (db.session.query(User, db.func.count(Complaint.id)).outerjoin(Complaint, Complaint.user_id == User.id)
            .filter(User.role == 'citizen').group_by(User.id).order_by(User.id.desc()).all())
    return render_template('admin/users.html', rows=rows)

@bp.route('/users/<int:uid>/<action>', methods=['POST'])
@admin_required
def user_action(uid, action):
    u = db.session.get(User, uid)
    if not u or u.role != 'citizen' or action not in ('toggle', 'reset'):
        abort(404)
    if action == 'toggle':
        u.active = not u.active
        S.audit(current_user.id, 'user_toggle', details=f'{u.contact} active={u.active}'); flash(f"{u.name} is now {'active' if u.active else 'deactivated'}.", 'success')
    else:
        temp = secrets.token_urlsafe(8)
        u.set_password(temp)
        S.audit(current_user.id, 'user_password_reset', details=u.contact)
        flash(f'Temporary password for {u.name}: {temp}  (share it privately; ask them to change it in Profile)', 'warning')
    db.session.commit()
    return redirect(url_for('admin.users'))

# settings (profile, security, new admins, activity log)
@bp.route('/settings', methods=['GET', 'POST'])
@admin_required
def settings():
    u = current_user
    if request.method == 'POST':
        f, act = request.form, request.form.get('action')
        if act == 'name' and f.get('name', '').strip():
            u.name = f['name'].strip()[:60]; db.session.commit(); flash('Profile updated.', 'success')
        elif act == 'password':
            if not u.check_password(f.get('old', '')):
                flash('Current password is wrong.', 'danger')
            elif len(f.get('new', '')) < 10 or f.get('new') != f.get('confirm'):
                flash('Admin passwords need 10+ characters and must match the confirmation.', 'danger')
            else:
                u.set_password(f['new']); S.audit(u.id, 'password_change'); db.session.commit(); flash('Password changed.', 'success')
        elif act == 'new_admin':
            email = f.get('email', '').strip().lower()
            if not u.check_password(f.get('old', '')):
                flash('Confirm with your own password to create an administrator.', 'danger')
            elif not f.get('name', '').strip() or not EMAIL.match(email) or len(f.get('new', '')) < 10:
                flash('Enter a name, a valid email and a password of 10+ characters.', 'danger')
            elif User.query.filter_by(email=email).first():
                flash('An account with this email already exists.', 'warning')
            else:
                a = User(name=f['name'].strip()[:60], email=email, role='admin'); a.set_password(f['new'])
                db.session.add(a); S.audit(u.id, 'admin_created', details=email); db.session.commit(); flash(f'Administrator {email} created.', 'success')
        return redirect(url_for('admin.settings'))
    return render_template('admin/settings.html', admins=User.query.filter_by(role='admin').all(),
                           logs=AuditLog.query.order_by(AuditLog.id.desc()).limit(60).all())
