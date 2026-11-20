import os
from flask import Blueprint, request, jsonify, current_app, url_for
from flask_login import current_user
from extensions import citizen_required
from services.helpers import save_image, safe_photo
from ai import manager, store, video as V, video_jobs as J

bp = Blueprint('ai', __name__)

def _legacy_error():
    """Same shape the old single-model detector returned when something went wrong (plus the new keys)."""
    return {'status': 'error', 'label': None, 'category': None, 'confidence': 0, 'boxes': [], 'annotated': None, 'model_name': None, 'predictions': [],
            'issues': [], 'models': [], 'needs_confirmation': False, 'conflict': False, 'multiple_issues': False, 'reasons': [], 'suggested_category': None,
            'reliability': 0, 'models_available': 0, 'models_total': 0}

def _up(name):
    return url_for('static', filename='uploads/' + name) if name else None

@bp.route('/upload/photo', methods=['POST'])
@citizen_required
def upload_photo():
    try:
        return jsonify(photo_name=save_image(request.files.get('photo')))
    except ValueError as e:
        return jsonify(error=str(e)), 400

@bp.route('/ai/detect', methods=['POST'])
@citizen_required
def detect():
    cfg = current_app.config
    name = safe_photo((request.get_json(silent=True) or {}).get('photo_name'))
    if not name:
        return jsonify(error='Photo not found. Please add it again.'), 400
    try:
        res = manager.analyze(os.path.join(cfg['UPLOAD_FOLDER'], name), cfg, cfg['UPLOAD_FOLDER'])      # all available models, same original image
    except Exception:
        current_app.logger.exception('AI analysis failed')
        res = _legacy_error()
    # the complaint is created from this server-side copy, never from values sent back by the browser (and it is too big for the cookie session)
    try:
        store.save(cfg['AI_RESULTS_DIR'], name, current_user.id, res)
    except OSError:
        current_app.logger.exception('could not store AI result')
    return jsonify({**res, 'annotated_url': _up(res.get('annotated'))})

# video evidence
def _public(result):
    """Add browser URLs to a finished video analysis."""
    r = dict(result)
    r['annotated_url'] = _up(r.get('annotated'))
    r['photo_url'] = _up(r.get('photo_name'))
    r['video_url'] = _up((r.get('video') or {}).get('name'))
    r['annotated_video_url'] = _up(r.get('annotated_video'))
    r['frames'] = [dict(f, url=_up(f.get('annotated'))) for f in r.get('frames', [])]
    r['issues'] = [dict(i, photo_url=_up(i.get('photo_name')), annotated_url=_up(i.get('annotated'))) for i in r.get('issues', [])]
    return r

@bp.route('/upload/video', methods=['POST'])
@citizen_required
def upload_video():
    cfg = current_app.config
    fs = request.files.get('video')
    if not fs:
        return jsonify(error='No video selected.'), 400
    fs.stream.seek(0, 2); size = fs.stream.tell(); fs.stream.seek(0)
    if size < 1024:
        return jsonify(error='That video file is empty.'), 400
    if size > cfg['VIDEO_MAX_MB'] * 1024 * 1024:
        return jsonify(error=f"Video is too large (max {cfg['VIDEO_MAX_MB']} MB)."), 400
    ext = V.sniff_container(fs.stream.read(16)); fs.stream.seek(0)                  # real container type, never the file name / content-type
    if ext not in V.ALLOWED:
        return jsonify(error='Unsupported video. Please use an MP4, MOV, 3GP or WebM video.'), 400
    results = cfg['AI_RESULTS_DIR']
    J.prune_orphans(results, cfg['UPLOAD_FOLDER'])
    if J.count_open(results, current_user.id) >= cfg['VIDEO_MAX_OPEN']:
        return jsonify(error='You have several videos waiting. Please submit or wait for them to finish first.'), 429
    name = J.new_name(ext); path = os.path.join(cfg['UPLOAD_FOLDER'], name)
    fs.save(path)
    try:
        info = V.probe(path, cfg)
    except ValueError as e:
        os.remove(path)
        return jsonify(error=str(e)), 400
    except Exception:
        current_app.logger.exception('video probe failed')
        os.remove(path)
        return jsonify(error='This video could not be read. Please try recording it again.'), 400
    J.create(results, name, current_user.id, request.form.get('gps'), size)
    J.start(cfg, results, cfg['UPLOAD_FOLDER'], name, current_user.id)
    return jsonify(video_name=name, status='queued', duration=info['duration'])

@bp.route('/ai/video/<name>/status')
@citizen_required
def video_status(name):
    rec = J.read(current_app.config['AI_RESULTS_DIR'], name, current_user.id)
    if rec is None:
        return jsonify(error='Video not found.'), 404
    out = {'status': rec['status'], 'stage': rec.get('stage'), 'done': rec.get('done', 0), 'total': rec.get('total', 1), 'error': rec.get('error')}
    if rec['status'] == 'done' and rec.get('result'):
        out['result'] = _public(rec['result'])
    return jsonify(out)
