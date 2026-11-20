"""Background analysis of an uploaded video. Pure Python (no Flask / DB).
Upload -> job file  <results_dir>/vid_<hex>.json  {status, progress, result ...}  -> a worker thread runs ai.video.analyze_video().
The browser polls the status; progress lives in the JSON file so any server worker can answer.
At most VIDEO_MAX_CONCURRENT videos are analysed at once (the models are CPU/RAM heavy); the rest wait as 'queued'."""
import json, os, re, shutil, threading, time, traceback, uuid
from ai import video as V

NAME = re.compile(r'vid_[0-9a-f]{16}\.(?:mp4|mov|webm|3gp)')
_SEM, _SEM_N, _LOCK = None, 0, threading.Lock()

def new_name(ext):
    return f'vid_{uuid.uuid4().hex[:16]}.{ext}'

def _meta(results_dir, name):
    return os.path.join(results_dir, name.rsplit('.', 1)[0] + '.json')

def _write(results_dir, name, data):
    os.makedirs(results_dir, exist_ok=True)
    p = _meta(results_dir, name)
    tmp = p + '.' + uuid.uuid4().hex[:6] + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(data, fh)
    os.replace(tmp, p)

def read(results_dir, name, user_id):
    """The job record, only for its owner and only for names this app generated."""
    if not NAME.fullmatch(name or ''):
        return None
    try:
        with open(_meta(results_dir, name), encoding='utf-8') as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        return None
    return d if d.get('user_id') == user_id else None

def clean_gps(raw, max_points=120):
    """GPS fixes recorded in the browser: [{'t','lat','lng','acc'}]. Anything invalid is dropped; it is evidence, never verified."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return []
    out = []
    for p in (raw if isinstance(raw, list) else [])[:max_points]:
        try:
            lat, lng, t = float(p['lat']), float(p['lng']), float(p.get('t', 0))
            acc = float(p['acc']) if p.get('acc') is not None else None
        except (KeyError, TypeError, ValueError):
            continue
        if -90 <= lat <= 90 and -180 <= lng <= 180 and 0 <= t <= 3600 and (acc is None or 0 <= acc <= 100000) and not (lat == 0 and lng == 0):
            # k: 'rec' = sampled by the page while recording (tied to video time); anything else = one fix taken at upload time (not tied to the video)
            out.append({'t': round(t, 2), 'lat': round(lat, 6), 'lng': round(lng, 6), 'acc': None if acc is None else round(acc, 1), 'k': 'rec' if p.get('k') == 'rec' else 'up'})
    return out

def fix_near(gps, t):
    """The GPS fix closest in time to t (prefers accurate fixes). None when there is no usable fix."""
    if not gps:
        return None
    return min(gps, key=lambda g: abs(g['t'] - (t or 0)) + (g['acc'] or 50) / 100.0)

def count_open(results_dir, user_id):
    """How many of this user's uploaded videos are not yet attached to a complaint (stops people filling the disk)."""
    n = 0
    try:
        for fn in os.listdir(results_dir):
            if fn.startswith('vid_') and fn.endswith('.json'):
                with open(os.path.join(results_dir, fn), encoding='utf-8') as fh:
                    d = json.load(fh)
                n += d.get('user_id') == user_id and not d.get('attached')
    except (OSError, ValueError):
        pass
    return n

def create(results_dir, name, user_id, gps, size):
    _write(results_dir, name, {'user_id': user_id, 'status': 'queued', 'stage': 'queued', 'done': 0, 'total': 1, 'error': None, 'created': time.time(),
                               'attached': False, 'gps': clean_gps(gps), 'size': size, 'files': [], 'result': None, 'photo_name': None})

def _sem(cfg):
    global _SEM, _SEM_N
    n = max(1, int(cfg.get('VIDEO_MAX_CONCURRENT', 1)))
    with _LOCK:
        if _SEM is None or _SEM_N != n:
            _SEM, _SEM_N = threading.Semaphore(n), n
        return _SEM

def start(cfg, results_dir, upload_dir, name, user_id):
    t = threading.Thread(target=_work, args=(dict(cfg), results_dir, upload_dir, name, user_id), daemon=True)
    t.start()
    return t

def _work(cfg, results_dir, upload_dir, name, user_id):
    rec = read(results_dir, name, user_id)
    if rec is None:
        return
    tmp = os.path.join(results_dir, 'tmp_' + name.rsplit('.', 1)[0])
    def save(**kw):
        rec.update(kw)
        _write(results_dir, name, rec)
    try:
        with _sem(cfg):
            save(status='processing', stage='extracting', done=0, total=1)
            last = [0.0]
            def progress(stage, done, total):
                if stage == 'extracting' or time.time() - last[0] > 0.2 or done >= total:
                    last[0] = time.time(); save(stage=stage, done=done, total=total)
            result, frames = V.analyze_video(os.path.join(upload_dir, name), cfg, tmp, upload_dir, progress, rec['gps'])
            result['video'] = dict(result.get('video') or {}, name=name)
            files = [f['annotated'] for f in frames if f.get('annotated')]
            result['gps_points'] = len(rec['gps'])
            bf = result.get('best_frame')
            if not bf and frames:                                   # nothing detected: the middle frame still becomes the photo, so the citizen can go on
                mid = frames[len(frames) // 2]
                bf = {'path': mid['path'], 't': mid['t'], 'index': mid['index']}
            if bf:                                                  # the sharpest frame of the main issue becomes the complaint's ordinary photo
                photo = uuid.uuid4().hex[:16] + '.jpg'
                shutil.copyfile(bf['path'], os.path.join(upload_dir, photo))
                files.append(photo)
                result['photo_name'] = photo
                result['location'] = V.locate(rec['gps'], bf['t'], cfg.get('VIDEO_GPS_MAX_DT', 6.0))
                bf.pop('path', None)
                result['best_frame'] = bf
                from ai import store
                store.save(results_dir, photo, user_id, result)       # same store the image flow uses -> complaint creation needs no special case
                save(photo_name=photo)
            from ai import store as _store
            by_idx = {f['index']: f for f in frames}
            for iss in result.get('issues', []):                   # every issue gets its own photo + its own stored analysis -> each can become a complete complaint
                fr = by_idx.get(iss['best_frame'])
                if not fr:
                    continue
                pn = uuid.uuid4().hex[:16] + '.jpg'
                shutil.copyfile(fr['path'], os.path.join(upload_dir, pn)); files.append(pn)
                iss['photo_name'] = pn
                _store.save(results_dir, pn, user_id, V.issue_detection(result, iss, fr))
            result.pop('predictions_full', None)
            if cfg.get('VIDEO_ANNOTATED_OUTPUT', True) and result.get('issues'):      # the whole video with boxes + labels; failing here never loses the analysis
                try:
                    from ai import video_render as _R
                    save(stage='rendering', done=0, total=1)
                    ann = _R.render(os.path.join(upload_dir, name), upload_dir, result['issues'], cfg, lambda d, t: progress('rendering', d, t))
                    if ann:
                        result['annotated_video'] = ann; files.append(ann)
                except Exception:
                    traceback.print_exc()
            save(status='done', stage='done', done=1, total=1, result=result, files=files)
    except ValueError as e:                                        # friendly, expected problems (bad/long video ...)
        save(status='error', error=str(e))
    except Exception as e:                                         # unexpected: log, show a generic message
        traceback.print_exc()
        save(status='error', error='The video could not be analysed. Please try again or report with a photo.')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

def mark_attached(results_dir, name):
    """Called when a complaint keeps the video, so the clean-up below never deletes it."""
    try:
        with open(_meta(results_dir, name), encoding='utf-8') as fh:
            d = json.load(fh)
        d['attached'] = True
        _write(results_dir, name, d)
    except (OSError, ValueError):
        pass

def prune_orphans(results_dir, upload_dir, max_age=2 * 86400):
    """Delete videos (and their annotated frames) that were uploaded but never attached to a complaint."""
    now = time.time()
    try:
        names = [f for f in os.listdir(results_dir) if f.startswith('vid_') and f.endswith('.json')]
    except OSError:
        return 0
    n = 0
    for fn in names:
        p = os.path.join(results_dir, fn)
        try:
            with open(p, encoding='utf-8') as fh:
                d = json.load(fh)
            active = d.get('status') in ('queued', 'processing') and now - d.get('created', now) < 3600     # a job stuck for an hour is dead (server restarted)
            if d.get('attached') or active or now - d.get('created', now) < max_age:
                continue
            stem = fn[:-5]
            for ext in V.ALLOWED:
                f = os.path.join(upload_dir, f'{stem}.{ext}')
                if os.path.exists(f):
                    os.remove(f)
            for f in d.get('files', []):
                if re.fullmatch(r'(?:ai_[0-9a-f]{12}|[0-9a-f]{16})\.jpg', f) and os.path.exists(os.path.join(upload_dir, f)):
                    os.remove(os.path.join(upload_dir, f))
            os.remove(p); n += 1
        except (OSError, ValueError):
            continue
    return n
