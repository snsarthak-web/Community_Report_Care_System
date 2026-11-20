import csv, io, math
from datetime import datetime, timedelta
from flask import current_app
from extensions import db, utcnow
from models.user import User
from services import timeutil as TZ
from models.complaint import (Department, Complaint, AIDetection, ComplaintVote, StatusHistory, Notification, AuditLog,
                              ComplaintGeo, ComplaintVideoIssue, STATUSES, GROUPS, PRIORITIES)

def priority_for(votes):
    return 'Critical' if votes >= 5 else 'High' if votes >= 3 else 'Medium' if votes == 2 else 'Low'

def _dist(lat1, lng1, lat2, lng2):
    dx = (lng2 - lng1) * 111320 * math.cos(math.radians((lat1 + lat2) / 2))
    return round(math.hypot(dx, (lat2 - lat1) * 110540))

def notify(user_id, complaint_id, msg):
    db.session.add(Notification(user_id=user_id, complaint_id=complaint_id, message=msg[:400]))

def notify_admins(complaint, msg):
    for a in User.query.filter_by(role='admin', active=True).all():
        notify(a.id, complaint.id, msg)

def audit(admin_id, action, complaint=None, details=''):
    db.session.add(AuditLog(admin_id=admin_id, action=action, complaint_id=complaint.id if complaint else None, details=details[:500]))

# create / read
ORIGINS = ('gps', 'video_gps', 'upload_fix')
SOURCE_LABEL = {'gps': 'Device GPS', 'gps_adjusted': 'Device GPS, pin moved by the citizen', 'video_gps': 'GPS sampled while filming',
                'video_gps_adjusted': 'GPS sampled while filming, pin moved by the citizen', 'upload_fix': 'Phone location when the video was uploaded (approximate)',
                'upload_fix_adjusted': 'Upload-time location, pin moved by the citizen', 'map_pin': 'Pin placed on the map by the citizen', 'landmark': 'Landmark text only (no coordinates)'}

def _num(v, lo, hi):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if lo <= x <= hi else None

def clean_geo(raw, lat, lng):
    """How the coordinates came about, decided here from what the device reported and where the pin finally is (the browser's claim is not trusted
    for 'adjusted'). raw: {'origin','acc','cap_lat','cap_lng','dt'}. -> dict for ComplaintGeo."""
    raw = raw or {}
    if lat is None:
        return dict(source='landmark')
    cl, cg = _num(raw.get('cap_lat'), -90, 90), _num(raw.get('cap_lng'), -180, 180)
    origin = raw.get('origin') if raw.get('origin') in ORIGINS else None
    if origin and cl is not None and cg is not None and not (cl == 0 and cg == 0):
        moved = _dist(cl, cg, lat, lng)
        return dict(source=origin + ('_adjusted' if moved > 5 else ''), accuracy_m=_num(raw.get('acc'), 0, 100000), captured_lat=cl, captured_lng=cg,
                    moved_m=moved, sample_dt_sec=_num(raw.get('dt'), 0, 3600))
    return dict(source='map_pin')

def create(user, d, det=None, video=None, commit=True):
    import json
    c = Complaint(user_id=user.id, category=d['category'], description=d.get('description'), reporting_method=d['method'],
                  image_path=d.get('image'), location_text=d.get('location_text'), latitude=d.get('lat'), longitude=d.get('lng'))
    db.session.add(c)
    db.session.flush()                                   # assigns c.id
    c.tracking_id = f"CRC-{utcnow().year}-{c.id:05d}"
    db.session.add(StatusHistory(complaint_id=c.id, old_status=None, new_status='Submitted', note='Complaint registered', updated_by=user.id))
    if det and det.get('label'):
        import json
        db.session.add(AIDetection(complaint_id=c.id, detected_object=det['label'], confidence=det['confidence'],
                                   bounding_box=json.dumps(det['boxes']), model_name=det.get('model_name'), annotated_path=det.get('annotated')))
    if d.get('geo'):
        db.session.add(ComplaintGeo(complaint_id=c.id, **d['geo']))
    vi = d.get('video_issue')
    if vi:
        db.session.add(ComplaintVideoIssue(complaint_id=c.id, timestamps_json=json.dumps(vi.get('timestamps') or []), **{k: v for k, v in vi.items() if k != 'timestamps'}))
    _save_ai_details(c, det, d['category'], video)
    notify(user.id, c.id, f'Your complaint {c.tracking_id} was registered successfully.')
    notify_admins(c, f'New complaint {c.tracking_id}: {c.category}' + (' (AI-assisted)' if det and det.get('label') else '') + (' with video' if video else ''))
    if commit:
        db.session.commit()
    return c.tracking_id

def _save_ai_details(c, det, citizen_category, video=None):
    """Everything the AI saw, kept next to the complaint: one row per model prediction, one summary row, and the video evidence.
    The complaint's own category is whatever the citizen chose: nothing here changes it."""
    import json
    from models.complaint import AIPrediction, AIAnalysis, ComplaintVideo
    det = det or {}
    src = det.get('source', 'image')
    for p in (det.get('predictions') or [])[:120]:
        db.session.add(AIPrediction(
            complaint_id=c.id, source=src, model_name=p.get('model', '')[:40], model_label=str(p.get('label', ''))[:80], category=p.get('category'),
            confidence=p.get('confidence'), reliability=p.get('reliability'), score=p.get('score'),
            bounding_box=json.dumps(p['bbox']) if p.get('bbox') else None, task=p.get('task'), image_level=bool(p.get('image_level')),
            issue_index=p.get('issue'), is_selected=bool(p.get('selected')), is_conflict=bool(p.get('conflict')),
            annotated_path=(p.get('frame_image') if src == 'video' else det.get('annotated')), frame_index=p.get('frame_index'), timestamp_sec=p.get('timestamp_sec')))
    if det.get('models') or det.get('predictions') or det.get('issues'):
        db.session.add(AIAnalysis(
            complaint_id=c.id, source=src, suggested_category=det.get('suggested_category'), reliability=det.get('reliability'),
            calibrated=bool(det.get('reliability_calibrated')), needs_confirmation=bool(det.get('needs_confirmation')), conflict=bool(det.get('conflict')),
            multiple_issues=bool(det.get('multiple_issues')), citizen_category=citizen_category,
            issues_json=json.dumps(det.get('issues') or []), models_json=json.dumps(det.get('models') or []), reasons_json=json.dumps(det.get('reasons') or [])))
    if video:
        r, info = video.get('result') or {}, (video.get('result') or {}).get('video') or {}
        db.session.add(ComplaintVideo(
            complaint_id=c.id, filename=video['name'], thumb=video.get('thumb') or r.get('photo_name'), duration_sec=info.get('duration'), fps=info.get('fps'), width=info.get('width'),
            height=info.get('height'), size_bytes=info.get('size_bytes') or video.get('size'), frames_analyzed=info.get('frames_analyzed'),
            gps_json=json.dumps(video.get('gps') or []), summary_json=json.dumps({'issues': r.get('issues', []), 'frames': r.get('frames', []), 'annotated_video': r.get('annotated_video')})))

def get_by_tid(tid):
    return Complaint.query.filter_by(tracking_id=(tid or '').strip().upper()).first()

def has_voted(c, uid):
    return ComplaintVote.query.filter_by(complaint_id=c.id, user_id=uid).first() is not None

def can_view(c, user):
    return bool(user and user.is_authenticated) and (user.role == 'admin' or c.user_id == user.id or has_voted(c, user.id))

def listing(uid=None, supported_by=None, group='', status='', category='', priority='', department_id=None, q='', place='',
            date_from='', date_to='', ai=''):
    query = Complaint.query
    if uid is not None:
        query = query.filter(Complaint.user_id == uid)
    if supported_by is not None:
        query = query.filter(Complaint.id.in_(db.select(ComplaintVote.complaint_id).where(ComplaintVote.user_id == supported_by)))
    if group in GROUPS:
        query = query.filter(Complaint.status.in_(GROUPS[group]))
    if status in STATUSES:
        query = query.filter(Complaint.status == status)
    if category:
        query = query.filter(Complaint.category == category)
    if priority in PRIORITIES:
        query = query.filter(Complaint.priority == priority)
    if department_id:
        query = query.filter(Complaint.department_id == department_id)
    if q:
        query = query.filter(db.or_(Complaint.tracking_id.ilike(f'%{q}%'), Complaint.location_text.ilike(f'%{q}%')))
    if place:
        query = query.filter(Complaint.location_text.ilike(f'%{place}%'))
    if date_from:
        query = query.filter(db.func.date(Complaint.created_at) >= date_from)
    if date_to:
        query = query.filter(db.func.date(Complaint.created_at) <= date_to)
    if ai == 'yes':
        query = query.filter(Complaint.detection.has())
    return query.order_by(Complaint.id.desc()).all()

# duplicates & voting
def nearby(category, lat, lng, uid):
    r = current_app.config['DUP_RADIUS_DEG']
    rows = Complaint.query.filter(Complaint.category == category, Complaint.status != 'Resolved', Complaint.latitude.isnot(None),
                                  db.func.abs(Complaint.latitude - lat) < r, db.func.abs(Complaint.longitude - lng) < r).all()
    out = [{'tracking_id': c.tracking_id, 'votes': c.vote_count, 'status': c.status, 'location_text': c.location_text, 'image': c.image_path,
            'distance_m': _dist(lat, lng, c.latitude, c.longitude), 'is_owner': c.user_id == uid, 'has_voted': has_voted(c, uid)} for c in rows]
    return sorted(out, key=lambda x: x['distance_m'])[:3]

def vote(c, uid):
    """True if a new vote was counted. The owner and repeat votes are rejected."""
    if c.user_id == uid or has_voted(c, uid):
        return False
    db.session.add(ComplaintVote(complaint_id=c.id, user_id=uid))
    db.session.flush()
    votes = 1 + ComplaintVote.query.filter_by(complaint_id=c.id).count()
    if not c.priority_locked:
        c.priority = priority_for(votes)
    notify(c.user_id, c.id, f'Another citizen supports your complaint {c.tracking_id} ({votes} supporters).')
    if votes >= 5 and not c.priority_locked:
        notify_admins(c, f'{c.tracking_id} reached {votes} supporters (Critical priority).')
    db.session.commit()
    return True

def citizen_feedback(c, fixed, note):
    """Owner confirms the fix, or says it is still unresolved (which re-opens the complaint)."""
    c.feedback_note = (note or '')[:300] or None
    if fixed:
        c.citizen_feedback = 'confirmed'
        notify_admins(c, f'Citizen confirmed {c.tracking_id} is fixed.')
    else:
        c.citizen_feedback = 'disputed'
        db.session.add(StatusHistory(complaint_id=c.id, old_status=c.status, new_status='Under Review', updated_by=c.user_id,
                                     note='Citizen reports the problem is still unresolved' + (f': {c.feedback_note}' if c.feedback_note else '')))
        c.status, c.resolved_at = 'Under Review', None
        notify_admins(c, f'ATTENTION: citizen says {c.tracking_id} is NOT fixed. The complaint was re-opened.')
    db.session.commit()

# admin actions
STATUS_MSG = {'Under Review': 'is now under review', 'Assigned': 'has been assigned to {dept}', 'In Progress': 'is now in progress',
              'Resolved': 'has been resolved', 'Submitted': 'was moved back to Submitted'}

def admin_update(c, admin, f, evidence=None):
    """Applies the admin form. Returns an error string, or None on success."""
    cats = current_app.config['CATEGORIES']
    new_status = f.get('status') if f.get('status') in STATUSES else c.status
    note = (f.get('note') or '').strip()[:300]
    resolving = new_status == 'Resolved' and c.status != 'Resolved'
    if resolving and not (evidence or c.resolution_image or f.get('no_evidence')):
        return 'Upload an after-repair photo to resolve this complaint (or tick "Resolve without photo").'
    changes = []
    cat = f.get('category')
    if cat in cats and cat != c.category:
        changes.append(f'category {c.category} -> {cat}'); c.category = cat
    dept_id = f.get('department_id', type=int)
    dept = db.session.get(Department, dept_id) if dept_id else None
    if (dept.id if dept else None) != c.department_id:
        changes.append(f"department -> {dept.name if dept else 'unassigned'}"); c.department = dept
    officer = (f.get('officer') or '').strip()[:80] or None
    if officer != c.assigned_officer:
        changes.append(f"officer -> {officer or 'none'}"); c.assigned_officer = officer
    pr = f.get('priority')
    if pr in PRIORITIES and pr != c.priority:
        changes.append(f'priority {c.priority} -> {pr}'); c.priority, c.priority_locked = pr, True
    if evidence:
        c.resolution_image = evidence; changes.append('after-repair photo uploaded')
    det = c.detection
    if det and f.get('verdict') in ('1', '0', ''):
        v = {'1': True, '0': False, '': None}[f['verdict']]
        if v != det.prediction_verified:
            det.prediction_verified = v; changes.append('AI prediction marked ' + {True: 'correct', False: 'incorrect', None: 'not reviewed'}[v])
    old = c.status
    if new_status != old:
        changes.append(f'status {old} -> {new_status}'); c.status = new_status
        db.session.add(StatusHistory(complaint_id=c.id, old_status=old, new_status=new_status, note=note or None, updated_by=admin.id))
        if new_status == 'Resolved':
            c.resolved_at, c.citizen_feedback = utcnow(), None
        elif old == 'Resolved':
            c.resolved_at = None
        msg = f'Your complaint {c.tracking_id} ' + STATUS_MSG.get(new_status, f'status changed to {new_status}').format(dept=dept.name if dept else 'a department') + '.'
        if new_status == 'Resolved' and c.resolution_image:
            msg += ' An after-repair photo is available.'
        if note:
            msg += f' Note: {note}'
        for uid in {c.user_id} | {v.user_id for v in c.votes}:
            notify(uid, c.id, msg)
    elif note:
        db.session.add(StatusHistory(complaint_id=c.id, old_status=old, new_status=old, note=note, updated_by=admin.id))
        changes.append('note added'); notify(c.user_id, c.id, f'Update on {c.tracking_id}: {note}')
    if changes:
        audit(admin.id, 'update', c, '; '.join(changes))
    db.session.commit()
    return None

def export_csv(rows):
    def safe(v):                                            # stop spreadsheet formula injection
        s = '' if v is None else str(v)
        return "'" + s if s[:1] in ('=', '+', '-', '@') else s
    off, tz = current_app.config.get('TZ_OFFSET_MINUTES', 330), current_app.config.get('TZ_LABEL', 'IST')
    loc = lambda t: TZ.to_local(t, off).strftime('%Y-%m-%d %H:%M')
    buf = io.StringIO(); w = csv.writer(buf)
    w.writerow(['Tracking ID', f'Created ({tz})', 'Category', 'Status', 'Priority', 'Supporters', 'Department', 'Officer', 'Method', 'Reporter',
                'Location', 'Latitude', 'Longitude', 'Description', 'AI label', 'AI confidence', 'AI verified', f'Resolved ({tz})', 'Citizen feedback'])
    for c in rows:
        d = c.detection
        w.writerow([safe(x) for x in [c.tracking_id, loc(c.created_at), c.category, c.status, c.priority, c.vote_count,
                    c.department.name if c.department else '', c.assigned_officer, c.reporting_method, c.user.name, c.location_text, c.latitude,
                    c.longitude, c.description, d.detected_object if d else '', round(d.confidence, 3) if d else '',
                    '' if not d or d.prediction_verified is None else ('yes' if d.prediction_verified else 'no'),
                    loc(c.resolved_at) if c.resolved_at else '', c.citizen_feedback]])
    return buf.getvalue()

# notifications
def unread_count(uid):
    return Notification.query.filter_by(user_id=uid, is_read=False).count()

def mark_read(uid, nid=None):
    q = Notification.query.filter_by(user_id=uid, is_read=False)
    if nid:
        q = q.filter_by(id=nid)
    q.update({'is_read': True})
    db.session.commit()

# dashboards & analytics (all numbers come from the database)
def _trend(uid, days):
    off = current_app.config.get('TZ_OFFSET_MINUTES', 330)      # days are local (IST) days; the database stores UTC
    dates = [TZ.local_today(utcnow(), off) - timedelta(days=i) for i in range(days - 1, -1, -1)]
    start = TZ.local_day_start_utc(dates[0], off)
    rq = db.session.query(Complaint.created_at).filter(Complaint.created_at >= start)
    sq = (db.session.query(StatusHistory.created_at)
          .join(Complaint, Complaint.id == StatusHistory.complaint_id).filter(StatusHistory.new_status == 'Resolved', StatusHistory.created_at >= start))
    if uid is not None:
        rq, sq = rq.filter(Complaint.user_id == uid), sq.filter(Complaint.user_id == uid)
    rep = TZ.bucket_by_local_day([r[0] for r in rq.all()], off)
    res = TZ.bucket_by_local_day([r[0] for r in sq.all()], off)
    return {'labels': [d.strftime('%b %d') for d in dates], 'reported': [rep.get(d.isoformat(), 0) for d in dates],
            'resolved': [res.get(d.isoformat(), 0) for d in dates]}

def _cats(uid):
    q = db.session.query(Complaint.category, db.func.count(Complaint.id))
    if uid is not None:
        q = q.filter(Complaint.user_id == uid)
    rows = q.group_by(Complaint.category).order_by(db.func.count(Complaint.id).desc()).all()
    total = sum(n for _, n in rows) or 1
    return [{'name': c, 'n': n, 'pct': round(n * 100 / total)} for c, n in rows]

def citizen_dashboard(uid, days=14):
    days = days if days in (7, 14, 30) else 14
    base = Complaint.query.filter(Complaint.user_id == uid)
    counts = dict(base.with_entities(Complaint.status, db.func.count(Complaint.id)).group_by(Complaint.status).all())
    wk = dict(base.filter(Complaint.created_at >= utcnow() - timedelta(days=7)).with_entities(Complaint.status, db.func.count(Complaint.id)).group_by(Complaint.status).all())
    g = lambda d, ks: sum(d.get(k, 0) for k in ks)
    s = {'pending': g(counts, GROUPS['pending']), 'progress': g(counts, GROUPS['progress']), 'solved': g(counts, GROUPS['solved']),
         'pending_wk': g(wk, GROUPS['pending']), 'progress_wk': g(wk, GROUPS['progress']), 'solved_wk': g(wk, GROUPS['solved'])}
    s['total'] = s['pending'] + s['progress'] + s['solved']
    s['rate'] = round(s['solved'] * 100 / s['total']) if s['total'] else None      # None -> shown as a dash, not a fake 100%
    return {'s': s, 'trend': _trend(uid, days), 'cats': _cats(uid), 'days': days,
            'recent': base.order_by(Complaint.id.desc()).limit(5).all()}

def admin_dashboard(days=14):
    from ai.detector import category_for
    days = days if days in (7, 14, 30) else 14
    counts = dict(Complaint.query.with_entities(Complaint.status, db.func.count(Complaint.id)).group_by(Complaint.status).all())
    dets = AIDetection.query.all()
    rev = [d for d in dets if d.prediction_verified is not None]
    ai = {'total': len(dets), 'reviewed': len(rev), 'correct': sum(1 for d in rev if d.prediction_verified),
          'incorrect': sum(1 for d in rev if not d.prediction_verified),
          'changed': sum(1 for d in dets if d.complaint and category_for(d.detected_object) != d.complaint.category)}
    ai['accuracy'] = round(ai['correct'] * 100 / len(rev)) if rev else None
    depts = [(n or 'Unassigned', k) for n, k in db.session.query(Department.name, db.func.count(Complaint.id))
             .select_from(Complaint).outerjoin(Department, Complaint.department_id == Department.id)
             .group_by(Department.name).order_by(db.func.count(Complaint.id).desc()).all()]
    cats = _cats(None)
    return {'counts': counts, 'total': sum(counts.values()), 'ai': ai, 'depts': depts, 'trend': _trend(None, days), 'cats': cats,
            'maxcat': max([c['n'] for c in cats], default=1), 'days': days,
            'disputed': Complaint.query.filter(Complaint.citizen_feedback == 'disputed').count(),
            'recent': Complaint.query.order_by(Complaint.id.desc()).limit(6).all()}

def analytics(days=30):
    days = days if days in (7, 14, 30) else 30
    resolved = Complaint.query.filter(Complaint.resolved_at.isnot(None)).all()
    def avg_days(rows):
        return round(sum((c.resolved_at - c.created_at).total_seconds() for c in rows) / len(rows) / 86400, 1) if rows else None
    by_cat = []
    for cat in current_app.config['CATEGORIES']:
        tot = Complaint.query.filter_by(category=cat).count()
        if tot:
            r = [c for c in resolved if c.category == cat]
            by_cat.append({'name': cat, 'total': tot, 'resolved': len(r), 'avg_days': avg_days(r)})
    by_dept = []
    for d in Department.query.order_by(Department.name).all():
        r = [c for c in resolved if c.department_id == d.id]
        by_dept.append({'name': d.name, 'total': len(d.complaints), 'resolved': len(r), 'avg_days': avg_days(r)})
    prio = dict(Complaint.query.with_entities(Complaint.priority, db.func.count(Complaint.id)).group_by(Complaint.priority).all())
    total = Complaint.query.count()
    return {'days': days, 'total': total, 'resolved': len(resolved), 'rate': round(len(resolved) * 100 / total) if total else None,
            'avg_days': avg_days(resolved), 'disputed': Complaint.query.filter_by(citizen_feedback='disputed').count(),
            'by_cat': by_cat, 'by_dept': by_dept, 'prio': [(p, prio.get(p, 0)) for p in PRIORITIES], 'trend': _trend(None, days)}

def vote_groups(limit=40):
    """Complaints ranked by supporters, with nearby same-category complaints (possible duplicates) for admin review."""
    r = current_app.config['DUP_RADIUS_DEG']
    rows = Complaint.query.filter(Complaint.status != 'Resolved').all()
    rows.sort(key=lambda c: c.vote_count, reverse=True)
    out = []
    for c in rows[:limit]:
        sims = [o.tracking_id for o in rows if o.id != c.id and o.category == c.category and c.latitude is not None and o.latitude is not None
                and abs(o.latitude - c.latitude) < r and abs(o.longitude - c.longitude) < r]
        out.append({'c': c, 'similar': sims})
    return out

def siblings(c):
    """Other complaints made from the same video (empty for ordinary complaints)."""
    vi = c.video_issue
    if not vi or not vi.group_id:
        return []
    ids = [r.complaint_id for r in ComplaintVideoIssue.query.filter(ComplaintVideoIssue.group_id == vi.group_id, ComplaintVideoIssue.complaint_id != c.id).all()]
    return Complaint.query.filter(Complaint.id.in_(ids)).order_by(Complaint.id).all() if ids else []

def model_stats():
    """Per-model scoreboard from the admin's own verdicts on individual predictions (AIPrediction.verified): the real-world check on the validation numbers."""
    from models.complaint import AIPrediction
    rows = db.session.query(AIPrediction.model_name, AIPrediction.category, AIPrediction.verified, db.func.count(AIPrediction.id)) \
        .group_by(AIPrediction.model_name, AIPrediction.category, AIPrediction.verified).all()
    out = {}
    for model, cat, ver, n in rows:
        d = out.setdefault(model, {'total': 0, 'correct': 0, 'incorrect': 0, 'by_cat': {}})
        d['total'] += n
        if ver is True: d['correct'] += n
        elif ver is False: d['incorrect'] += n
        e = d['by_cat'].setdefault(cat or 'unclassified', {'total': 0, 'correct': 0, 'incorrect': 0})
        e['total'] += n
        if ver is True: e['correct'] += n
        elif ver is False: e['incorrect'] += n
    for d in out.values():
        r = d['correct'] + d['incorrect']
        d['reviewed'], d['precision'] = r, (round(d['correct'] * 100 / r) if r else None)
    return out
