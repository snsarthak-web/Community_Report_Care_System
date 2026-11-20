import os, uuid, re
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, abort, current_app, jsonify
from flask_login import current_user
from extensions import db, citizen_required
from models.user import User
from models.complaint import Notification, STATUSES
from services import complaint_service as S
from services.helpers import safe_photo
from ai import store as ai_store, video_jobs as ai_jobs
from ai.detector import category_for

bp = Blueprint('citizen', __name__)

def _num(v, lo, hi):
    return S._num(v, lo, hi)

@bp.route('/dashboard')
@citizen_required
def dashboard():
    return render_template('citizen/dashboard.html', **S.citizen_dashboard(current_user.id, request.args.get('days', 14, type=int)))

# reporting
@bp.route('/report')
@citizen_required
def report_choose():
    return render_template('citizen/report_choose.html')

@bp.route('/report/<mode>', methods=['GET', 'POST'])
@citizen_required
def report(mode):
    if mode not in ('ai', 'manual'):
        abort(404)
    cfg = current_app.config
    if request.method == 'POST':
        f = request.form
        back = redirect(url_for('citizen.report', mode=mode))
        cat = f.get('category')
        if cat not in cfg['CATEGORIES']:
            flash('Please choose a category.', 'danger'); return back
        try:
            lat = float(f['lat']) if f.get('lat') else None
            lng = float(f['lng']) if f.get('lng') else None
            if lat is not None and not (-90 <= lat <= 90 and -180 <= lng <= 180):
                raise ValueError
        except (ValueError, TypeError):
            flash('That location is not valid. Please pick it on the map again.', 'danger'); return back
        place = f.get('location_text', '').strip()[:200]
        if lat is None and not place:
            flash('Please set the location: use GPS, tap the map, or type a landmark.', 'danger'); return back
        photo = safe_photo(f.get('photo_name'))
        if mode == 'ai' and not photo:
            flash('A photo is required for AI reporting. Choose manual reporting if you have no photo.', 'danger'); return back
        cfg = current_app.config
        det = None
        if mode == 'ai' and photo:
            det = ai_store.load(cfg['AI_RESULTS_DIR'], photo, current_user.id) or session.get('ai_results', {}).get(photo)    # full analysis (server side); old session copy as fallback
        video = None
        vname = f.get('video_name', '')
        if mode == 'ai' and photo and vname:                      # video evidence: only the video that produced this photo, owned by this citizen
            rec = ai_jobs.read(cfg['AI_RESULTS_DIR'], vname, current_user.id)
            if rec and rec.get('status') == 'done' and rec.get('photo_name') == photo and os.path.exists(os.path.join(cfg['UPLOAD_FOLDER'], vname)):
                video = dict(rec, name=vname)
        geo = S.clean_geo({'origin': f.get('loc_origin'), 'acc': f.get('loc_acc'), 'cap_lat': f.get('cap_lat'), 'cap_lng': f.get('cap_lng')}, lat, lng)
        tid = S.create(current_user, dict(category=cat, description=f.get('description', '').strip()[:500], method=mode, image=photo,
                                          location_text=place, lat=lat, lng=lng, geo=geo), det, video)
        if video:
            ai_jobs.mark_attached(cfg['AI_RESULTS_DIR'], vname)
        flash(f'Complaint registered! Your tracking ID is {tid}', 'success')
        return redirect(url_for('citizen.detail', tid=tid))
    return render_template('citizen/report.html', mode=mode)

@bp.route('/report/video/submit', methods=['POST'])
@citizen_required
def report_video():
    """one analysed video -> one complaint per issue the citizen confirmed. Each complaint has its own category, frame, AI record, moment
    and location; all of them keep the same original video as evidence. All are created together or none are."""
    cfg, data = current_app.config, request.get_json(silent=True) or {}
    bad = lambda msg, code=400: (jsonify(ok=False, error=msg), code)
    vname = data.get('video_name', '')
    rec = ai_jobs.read(cfg['AI_RESULTS_DIR'], vname, current_user.id)
    if not rec or rec.get('status') != 'done' or not os.path.exists(os.path.join(cfg['UPLOAD_FOLDER'], vname)):
        return bad('This video is not ready or was not found. Please upload it again.')
    if rec.get('attached'):
        return bad('This video has already been submitted.', 409)
    result = rec.get('result') or {}
    known = {i['id']: i for i in result.get('issues', []) if i.get('id') and i.get('photo_name')}
    items = data.get('issues')
    if not isinstance(items, list) or not 1 <= len(items) <= cfg['VIDEO_MAX_ISSUES']:
        return bad('Select at least one detected issue to report.')
    desc = str(data.get('description') or '').strip()[:500]
    group, plans, seen = 'vg' + uuid.uuid4().hex[:16], [], set()
    for n, it in enumerate(items, 1):
        it = it if isinstance(it, dict) else {}
        iid = it.get('id')
        if iid not in known or iid in seen:
            return bad(f'Issue {n} is not part of this video.')
        seen.add(iid)
        if it.get('category') not in cfg['CATEGORIES']:
            return bad(f'Please choose a category for issue {n}.')
        lat, lng = _num(it.get('lat'), -90, 90), _num(it.get('lng'), -180, 180)
        place = str(it.get('location_text') or '').strip()[:200]
        if (lat is None) != (lng is None) or (lat == 0 and lng == 0):
            return bad(f'The location of issue {n} is not valid. Please set the pin again.')
        if lat is None and not place:
            return bad(f'Please set a location for issue {n}: use the map, GPS, or type a landmark.')
        iss = known[iid]
        photo = safe_photo(iss['photo_name'])
        det = ai_store.load(cfg['AI_RESULTS_DIR'], photo, current_user.id) if photo else None
        if not photo or not det:
            return bad(f'The saved frame for issue {n} is missing. Please upload the video again.')
        plans.append(dict(iss=iss, photo=photo, det=det, cat=it['category'], lat=lat, lng=lng, place=place,
                          geo=S.clean_geo({'origin': it.get('origin'), 'acc': it.get('acc'), 'cap_lat': it.get('cap_lat'), 'cap_lng': it.get('cap_lng'), 'dt': it.get('dt')}, lat, lng)))
    tids = []
    try:
        for p in plans:
            i = p['iss']
            vi = dict(group_id=group, video_filename=vname, issue_id=i['id'], category_ai=i['category'], timestamp_sec=i.get('best_t'),
                      timestamps=i.get('timestamps'), score=i.get('score'), frames_seen=i.get('frames_seen'))
            tids.append(S.create(current_user, dict(category=p['cat'], description=desc, method='ai', image=p['photo'], location_text=p['place'], lat=p['lat'], lng=p['lng'],
                                                    geo=p['geo'], video_issue=vi), p['det'], dict(rec, name=vname, thumb=p['photo']), commit=False))
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('video complaints failed')
        return bad('Could not register the complaints. Nothing was saved; please try again.', 500)
    ai_jobs.mark_attached(cfg['AI_RESULTS_DIR'], vname)
    for i in result.get('issues', []):                                      # frames of issues the citizen did not report are not kept
        if i.get('id') not in seen and i.get('photo_name'):
            for fn in (os.path.join(cfg['UPLOAD_FOLDER'], i['photo_name']), os.path.join(cfg['AI_RESULTS_DIR'], i['photo_name'][:-4] + '.json')):
                try: os.remove(fn)
                except OSError: pass
    flash(f"{len(tids)} complaint{'s' if len(tids) > 1 else ''} registered from your video: " + ', '.join(tids), 'success')
    return jsonify(ok=True, tracking_ids=tids, url=url_for('citizen.complaints') if len(tids) > 1 else url_for('citizen.detail', tid=tids[0]))

@bp.route('/api/nearby')
@citizen_required
def nearby():
    try:
        lat, lng = float(request.args['lat']), float(request.args['lng'])
    except (KeyError, ValueError):
        return jsonify([])
    cat = request.args.get('category', '')
    return jsonify(S.nearby(cat, lat, lng, current_user.id) if cat in current_app.config['CATEGORIES'] else [])

# viewing
@bp.route('/complaints')
@citizen_required
def complaints():
    a, uid = request.args, current_user.id
    supported = a.get('view') == 'supported'
    rows = S.listing(uid=None if supported else uid, supported_by=uid if supported else None, group=a.get('group', ''),
                     category=a.get('category', ''), q=a.get('q', '').strip())
    return render_template('citizen/complaints.html', rows=rows, supported=supported)

@bp.route('/track', methods=['GET', 'POST'])
@citizen_required
def track():
    tid = (request.values.get('id') or '').strip()
    if tid:
        c = S.get_by_tid(tid)
        if c and S.can_view(c, current_user):
            return redirect(url_for('citizen.detail', tid=c.tracking_id))
        flash('No complaint found with that tracking ID in your account.', 'danger')
    return render_template('citizen/track.html')

def _visible_or_404(tid):
    c = S.get_by_tid(tid)
    if not c or not S.can_view(c, current_user):
        abort(404)          # 404 (not 403) so other people's IDs are not revealed
    return c

@bp.route('/complaint/<tid>')
@citizen_required
def detail(tid):
    c = _visible_or_404(tid)
    owner = c.user_id == current_user.id
    return render_template('citizen/detail.html', c=c, sibs=S.siblings(c) if owner else [], det=c.detection, hist=c.history, stages=STATUSES, is_owner=owner,
                           voted=S.has_voted(c, current_user.id), can_feedback=owner and c.status == 'Resolved' and c.citizen_feedback is None)

@bp.route('/complaint/<tid>/vote', methods=['POST'])
@citizen_required
def vote(tid):
    c = S.get_by_tid(tid)
    if not c:
        return jsonify(ok=False, message='Complaint not found.'), 404
    ok = S.vote(c, current_user.id)
    msg = 'Thanks! Your support was added.' if ok else 'You cannot vote on your own complaint or vote twice.'
    if request.is_json:
        return jsonify(ok=ok, message=msg, url=url_for('citizen.detail', tid=c.tracking_id) if ok else None)
    flash(msg, 'success' if ok else 'warning')
    return redirect(url_for('citizen.detail', tid=c.tracking_id) if ok or S.can_view(c, current_user) else url_for('citizen.dashboard'))

@bp.route('/complaint/<tid>/feedback', methods=['POST'])
@citizen_required
def feedback(tid):
    c = _visible_or_404(tid)
    if c.user_id != current_user.id or c.status != 'Resolved' or c.citizen_feedback:
        flash('Feedback is not available for this complaint.', 'warning')
    else:
        S.citizen_feedback(c, request.form.get('answer') == 'fixed', request.form.get('note', '').strip())
        flash('Thank you for your feedback.' if request.form.get('answer') == 'fixed' else 'Thanks. The complaint has been re-opened for the administrators.', 'success')
    return redirect(url_for('citizen.detail', tid=c.tracking_id))

@bp.route('/map')
@citizen_required
def map_view():
    mine = S.listing(uid=current_user.id) + S.listing(supported_by=current_user.id)
    pts = [dict(tracking_id=c.tracking_id, category=c.category, status=c.status, latitude=c.latitude, longitude=c.longitude) for c in mine if c.latitude is not None]
    return render_template('citizen/map.html', points=pts)

# notifications & profile
@bp.route('/notifications')
@citizen_required
def notifications():
    rows = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.id.desc()).limit(100).all()
    return render_template('citizen/notifications.html', rows=rows)

@bp.route('/notifications/read-all', methods=['POST'])
@citizen_required
def read_all():
    S.mark_read(current_user.id)
    return redirect(url_for('citizen.notifications'))

@bp.route('/notifications/<int:nid>/open')
@citizen_required
def open_notification(nid):
    n = Notification.query.filter_by(id=nid, user_id=current_user.id).first_or_404()
    S.mark_read(current_user.id, nid)
    return redirect(url_for('citizen.detail', tid=n.complaint.tracking_id) if n.complaint else url_for('citizen.notifications'))

@bp.route('/profile', methods=['GET', 'POST'])
@citizen_required
def profile():
    u = current_user
    if request.method == 'POST':
        f, act = request.form, request.form.get('action')
        if act == 'name':
            name = f.get('name', '').strip()[:60]
            phone = ''.join(ch for ch in f.get('phone', '') if ch.isdigit())[-10:]
            if not name:
                flash('Name cannot be empty.', 'danger')
            elif f.get('phone', '').strip() and len(phone) != 10:
                flash('Enter a valid 10-digit phone number (used for OTP login).', 'danger')
            elif phone and User.query.filter(User.phone == phone, User.id != u.id).first():
                flash('That phone number belongs to another account.', 'danger')
            else:
                u.name, u.phone = name, phone or None
                db.session.commit(); flash('Profile updated.', 'success')
        elif act == 'password':
            if u.email is None:
                flash('Add an email address first. Phone-only accounts log in with OTP.', 'warning')
            elif len(f.get('new', '')) < 8 or f.get('new') != f.get('confirm'):
                flash('New password must be 8+ characters and match the confirmation.', 'danger')
            elif not u.check_password(f.get('old', '')):
                flash('Current password is wrong.', 'danger')
            else:
                u.set_password(f['new']); db.session.commit(); flash('Password changed.', 'success')
        return redirect(url_for('citizen.profile'))
    return render_template('citizen/profile.html')
