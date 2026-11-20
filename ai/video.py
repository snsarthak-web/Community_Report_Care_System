"""Video evidence -> frames -> the same five YOLO models -> one combined suggestion with timestamps. Pure Python + OpenCV (no Flask / DB).

Pipeline:  sniff container (magic bytes) -> probe with OpenCV (duration/size limits) -> choose evenly spaced moments, and for each
moment keep the sharpest frame in a small window (phone video is often motion-blurred) -> manager.analyze() on every chosen frame
(all five models) -> aggregate().
Decoding is sequential on purpose: browser-recorded WebM has no seek index and often no duration, so seeking is unreliable."""
import math, os, uuid
from ai import manager as M, decision as D

ALLOWED = ('mp4', 'mov', 'webm', '3gp')
DEFAULTS = dict(VIDEO_MAX_SECONDS=60, VIDEO_MAX_FRAMES=8, VIDEO_SAMPLE_SECONDS=2.5, VIDEO_FRAME_MAX_SIDE=1280, AI_MIN_SCORE=0.45, AI_CONFLICT_MARGIN=0.15,
                VIDEO_ISSUE_GAP_SEC=3.0, VIDEO_SAME_SPOT_M=25, VIDEO_GPS_MAX_DT=6.0, VIDEO_MAX_ISSUES=10)

def _c(cfg, k):
    return cfg.get(k, DEFAULTS[k])

def dist_m(a, b):
    """Distance in metres between two {'lat','lng'} points (equirectangular: exact enough below a few km)."""
    dx = (b['lng'] - a['lng']) * 111320 * math.cos(math.radians((a['lat'] + b['lat']) / 2))
    return math.hypot(dx, (b['lat'] - a['lat']) * 110540)

def locate(gps, t, max_dt):
    """The location to offer for a detection at video time t. Never exact: it is where the phone was.
      * samples taken while recording ('rec') within max_dt seconds of t  -> the nearest one, with dt (seconds away)
      * only an upload-time fix ('up')  -> offered as approximate: the citizen may have filmed elsewhere and uploaded later
      * nothing usable -> None (the citizen picks the spot on the map)"""
    rec = [g for g in gps or [] if g.get('k') == 'rec']
    if rec:
        g = min(rec, key=lambda g: abs(g['t'] - (t or 0)) + (g.get('acc') or 50) / 100.0)
        dt = abs(g['t'] - (t or 0))
        if dt <= max_dt:
            return {'lat': g['lat'], 'lng': g['lng'], 'acc': g.get('acc'), 'dt': round(dt, 1), 'kind': 'video_gps', 'approx': dt > 2.5 or (g.get('acc') or 0) > 30}
        return None
    up = [g for g in gps or [] if g.get('k') != 'rec']
    if up:
        g = min(up, key=lambda g: (g.get('acc') or 50))
        return {'lat': g['lat'], 'lng': g['lng'], 'acc': g.get('acc'), 'dt': None, 'kind': 'upload_fix', 'approx': True}
    return None

def sniff_container(head):
    """Identify the container from its first bytes (never trust the file name or the browser's content-type)."""
    if len(head) >= 12 and head[4:8] == b'ftyp':
        brand = head[8:12]
        return 'mov' if brand == b'qt  ' else '3gp' if brand[:3] == b'3gp' else 'mp4'
    if head[:4] == b'\x1a\x45\xdf\xa3':
        return 'webm'
    return None

def probe(path, cfg):
    """-> {'duration','fps','frames','width','height'}; raises ValueError with a message that is safe to show to the citizen."""
    import cv2
    maxs = _c(cfg, 'VIDEO_MAX_SECONDS')
    cap = cv2.VideoCapture(path)
    try:
        if not cap.isOpened():
            raise ValueError('This video could not be opened. Please try recording again (MP4 or WebM).')
        w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps, n = float(cap.get(cv2.CAP_PROP_FPS) or 0), int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if not (64 <= w <= 4096 and 64 <= h <= 4096):
            raise ValueError('Unsupported video size.')
        reliable = 1 <= fps <= 240 and 1 <= n <= 240 * (maxs + 5)
        if not reliable:                                     # browser-recorded WebM: count the frames ourselves (capped)
            fps_guess, n, cap_limit = (fps if 1 <= fps <= 240 else 30.0), 0, int(240 * (maxs + 5))
            while cap.grab():
                n += 1
                if n > cap_limit:
                    raise ValueError(f'Video is too long (max {maxs} seconds).')
            dur_ms = cap.get(cv2.CAP_PROP_POS_MSEC)
            fps = n / (dur_ms / 1000.0) if dur_ms and dur_ms > 300 and 1 <= n / (dur_ms / 1000.0) <= 240 else fps_guess
        if n < 2:
            raise ValueError('The video has no readable frames.')
        dur = n / fps
        if dur < 0.5:
            raise ValueError('The video is too short (at least 1 second).')
        if dur > maxs + 0.5:
            raise ValueError(f'Video is too long (max {maxs} seconds).')
        return {'duration': round(dur, 2), 'fps': round(fps, 3), 'frames': n, 'width': w, 'height': h}
    finally:
        cap.release()

def plan_targets(total, fps, duration, cfg):
    """Evenly spaced frame indexes: about one per VIDEO_SAMPLE_SECONDS, at most VIDEO_MAX_FRAMES, centred inside their slot."""
    k = max(1, min(_c(cfg, 'VIDEO_MAX_FRAMES'), math.ceil(duration / _c(cfg, 'VIDEO_SAMPLE_SECONDS'))))
    k = min(k, total)
    return sorted({min(total - 1, int((i + 0.5) * total / k)) for i in range(k)})

def _sharpness(frame):
    import cv2
    small = cv2.resize(frame, (320, int(320 * frame.shape[0] / frame.shape[1])))
    g = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(g, cv2.CV_64F).var()) * (1.0 if g.mean() > 12 else 0.01)       # nearly black frames are never preferred

def extract_frames(path, out_dir, info, cfg):
    """-> [{'index': frame number, 't': seconds, 'path': jpg}] one sharp frame per planned moment."""
    import cv2
    os.makedirs(out_dir, exist_ok=True)
    total, fps = info['frames'], info['fps']
    targets = plan_targets(total, fps, info['duration'], cfg)
    gap = min([b - a for a, b in zip(targets, targets[1:])] or [total])
    half = min(max(1, int(fps * 0.3)), max(0, (gap - 1) // 2))
    wins = [(max(0, t - half), min(total - 1, t + half)) for t in targets]
    cap, out, wi, idx, best = cv2.VideoCapture(path), [], 0, 0, None
    side = _c(cfg, 'VIDEO_FRAME_MAX_SIDE')

    def flush():
        if best is None:
            return
        _, i, fr = best
        sc = side / max(fr.shape[:2])
        if sc < 1:
            fr = cv2.resize(fr, (int(fr.shape[1] * sc), int(fr.shape[0] * sc)))
        p = os.path.join(out_dir, f'f{len(out):02d}_{i}.jpg')
        if cv2.imwrite(p, fr, [cv2.IMWRITE_JPEG_QUALITY, 88]):
            out.append({'index': i, 't': round(i / fps, 2), 'path': p})
    try:
        while wi < len(wins) and cap.grab():
            lo, hi = wins[wi]
            if idx >= lo:
                ok, fr = cap.retrieve()
                if ok:
                    s = _sharpness(fr)
                    if best is None or s > best[0]:
                        best = (s, idx, fr.copy())
            if idx >= hi:
                flush(); best = None; wi += 1
            idx += 1
        flush()
    finally:
        cap.release()
    return out

def _mean(v):
    return sum(v) / len(v) if v else 0.0

def _instances(obs, gps, cfg):
    """Sightings of one category (time-ordered) -> separate physical issues. Two sightings are the same issue when they are close in
    time and (by GPS: closer than VIDEO_SAME_SPOT_M, or without GPS: their boxes are the same object). A driver passing three potholes
    must get three issues, not one. Splits are cheap for the citizen to untick; silent merges would lose complaints."""
    gap, spot, maxdt = _c(cfg, 'VIDEO_ISSUE_GAP_SEC'), _c(cfg, 'VIDEO_SAME_SPOT_M'), _c(cfg, 'VIDEO_GPS_MAX_DT')
    groups = []
    for o in sorted(obs, key=lambda o: o['t']):
        o['loc'] = locate(gps, o['t'], maxdt)
        home, proven_apart = None, set()
        for k, g in enumerate(groups):
            last = g['obs'][-1]
            if o['t'] - last['t'] > gap:
                continue
            if o['loc'] and last['loc'] and o['loc']['kind'] == last['loc']['kind'] == 'video_gps':
                same = dist_m(o['loc'], last['loc']) <= spot + (o['loc'].get('acc') or 0) * 0.5
                if not same:
                    proven_apart.add(k)                                   # GPS says: different places, so no 'maybe the same' hint
            elif o['box'] and last['box']:
                same = D.same_object(last['box'], o['box'], 0.2, 0.7) > 0
            else:
                same = True
            if same:
                home = g; break
        if home:
            home['obs'].append(o)
        else:
            groups.append({'obs': [o], 'maybe': next((k for k, g in enumerate(groups) if k not in proven_apart and o['t'] - g['obs'][-1]['t'] <= gap), None)})
    return groups

def aggregate(frames, cfg, info=None, gps=None):
    """frames: [{'index','t','path','annotated','result': ai.manager.analyze() output}] -> one analysis shaped like the image analysis,
    plus one entry in 'issues' per separate physical issue (a category seen in only one frame is discounted: a single-frame hit is more
    often a false alarm). gps: samples [{'t','lat','lng','acc','k'}] used to place each issue (see locate)."""
    min_score, margin = _c(cfg, 'AI_MIN_SCORE'), _c(cfg, 'AI_CONFLICT_MARGIN')
    cats = {}
    for f in frames:
        for iss in f['result'].get('issues', []):
            if iss['category']:
                cats.setdefault(iss['category'], []).append({'frame': f['index'], 't': f['t'], 'score': iss['score'], 'conflict': iss['status'] == 'conflict',
                                                            'models': iss['models'], 'box': iss['box'], 'annotated': f.get('annotated'), 'category': iss['category']})
    issues = []
    for cat, allseen in cats.items():
        for gi, grp in enumerate(_instances(allseen, gps, cfg)):
            seen = grp['obs']
            top = sorted(seen, key=lambda s: -s['score'])
            n = len({s['frame'] for s in seen})
            score = round(_mean([s['score'] for s in top[:3]]) * min(1.0, 0.7 + 0.15 * (n - 1)), 3)
            models = sorted({m for s in seen for m in s['models']})
            conflict = sum(s['conflict'] for s in seen) * 2 >= len(seen)
            lone = n == 1 and len(frames) > 1                                   # seen in a single frame only -> must be confirmed
            issues.append({'category': cat, 'score': score, 'status': 'conflict' if conflict else ('agreed' if len(models) > 1 else 'single'),
                           'low_score': score < min_score, 'single_frame': lone, 'needs_confirmation': conflict or lone or score < min_score, 'models': models,
                           'box': top[0]['box'], 'alternatives': [], 'frames_seen': n, 'frames_total': len(frames),
                           'timestamps': sorted({s['t'] for s in seen}), 'best_t': top[0]['t'], 'best_frame': top[0]['frame'], 'annotated': top[0]['annotated'],
                           'sightings': [{'t': s['t'], 'box': s['box']} for s in sorted(seen, key=lambda s: s['t'])],
                           'location': top[0].get('loc'), '_maybe': grp['maybe'], '_cat': cat, '_gi': gi})
    issues.sort(key=lambda i: -i['score'])
    issues = issues[:_c(cfg, 'VIDEO_MAX_ISSUES')]
    for n, i in enumerate(issues):
        i['id'] = f'i{n}'
    for i in issues:                                                              # same category, split only by box/time (no GPS proof): a hint, not a verdict
        m = i['_maybe']
        peer = next((j for j in issues if j is not i and j['_cat'] == i['_cat'] and j['_gi'] == m), None) if m is not None else None
        i['maybe_same_as'] = peer['id'] if peer else None
    for i in issues:
        for k in ('_maybe', '_cat', '_gi'):
            i.pop(k, None)
    mods = {}
    for f in frames:
        for m in f['result'].get('models', []):
            cur = mods.setdefault(m['name'], dict(m, ms=0))
            cur['ms'] += m.get('ms', 0)
            if m['status'] == 'ok':
                cur.update(status='ok', error=None)
    models = list(mods.values())
    preds = []
    for f in frames:
        for p in f['result'].get('predictions', []):
            if p.get('used'):
                preds.append(dict(p, frame_index=f['index'], timestamp_sec=f['t'], frame_image=f.get('annotated'),
                                  selected=bool(issues and p.get('category') == issues[0]['category'] and p.get('selected'))))
    out = dict(status='ok' if issues else 'none', suggested_category=None, category=None, reliability=0.0, reliability_calibrated=False, confidence=0.0,
               label=None, needs_confirmation=False, conflict=False, multiple_issues=False, issues=issues, reasons=[], predictions=preds[:120],
               boxes=[], annotated=None, model_name=None, models=models, models_available=sum(m['status'] == 'ok' for m in models), models_total=len(models),
               source='video', frames=[{'index': f['index'], 't': f['t'], 'annotated': f.get('annotated'),
                                        'category': (f['result'].get('issues') or [{}])[0].get('category'),
                                        'score': (f['result'].get('issues') or [{}])[0].get('score')} for f in frames], video=info or {})
    if models and not any(m['status'] == 'ok' for m in models):
        out['status'] = 'no_model' if all(m['status'] == 'unavailable' for m in models) else 'error'
    if not issues:
        return out
    top = issues[0]
    bf = next(f for f in frames if f['index'] == top['best_frame'])
    sel = [p for p in preds if p['frame_index'] == bf['index'] and p.get('category') == top['category']]
    confident = {i['category'] for i in issues if not i['low_score']}
    out.update(suggested_category=top['category'], category=top['category'] if out['status'] == 'ok' else None, reliability=top['score'],
               confidence=round(max([p['confidence'] for p in sel] or [0]), 3), label=(max(sel, key=lambda p: p['score'])['label'] if sel else None),
               reliability_calibrated=all(p.get('calibrated') for p in sel) if sel else False, conflict=any(i['status'] == 'conflict' for i in issues[:1]),
               multiple_issues=len(confident) > 1, annotated=bf.get('annotated'), model_name='+'.join(sorted({p['model'] for p in sel})) or None,
               boxes=bf['result'].get('boxes', []), best_frame=dict(index=bf['index'], t=bf['t'], path=bf['path'], annotated=bf.get('annotated')))
    out['needs_confirmation'] = top['needs_confirmation'] or out['conflict'] or out['multiple_issues']
    r = out['reasons']
    for i in issues:
        if i['single_frame']:
            r.append(f"{i['category']} was seen in only one frame (at {i['best_t']:.1f}s): please confirm it.")
        elif i['status'] == 'conflict':
            r.append(f"Models disagree about {i['category']} in this video.")
    if out['multiple_issues']:
        r.append('Different kinds of issues appear in this video: ' + ', '.join(sorted(confident)) + '.')
    if not out['reliability_calibrated']:
        r.append('Reliability is not calibrated on validation data yet (neutral default used).')
    return out

def analyze_video(path, cfg, frames_dir, out_dir, progress=None, gps=None):
    """Whole pipeline. progress(stage, done, total) is optional. Returns the aggregated analysis (+ 'frames' with annotated names)."""
    info = probe(path, cfg)
    info['size_bytes'] = os.path.getsize(path)
    if progress: progress('extracting', 0, 1)
    raw = extract_frames(path, frames_dir, info, cfg)
    if not raw:
        raise ValueError('No usable frames could be read from this video.')
    done = []
    for k, f in enumerate(raw):
        if progress: progress('analyzing', k, len(raw))
        res = M.analyze(f['path'], cfg, out_dir)
        done.append(dict(f, annotated=res.get('annotated'), result=res))
    info['frames_analyzed'] = len(done)
    if progress: progress('finishing', len(raw), len(raw))
    return aggregate(done, cfg, info, gps), done

def issue_detection(result, issue, frame):
    """The complete AI record of one issue of a video, shaped like an image analysis, so a complaint made from it needs no special case:
    the predictions of the issue's best frame in the issue's category, that frame's boxes, and the whole video's model status."""
    cat, fi = issue['category'], issue['best_frame']
    preds = [dict(p, selected=True) for p in result.get('predictions', []) if p.get('frame_index') == fi and p.get('category') == cat]
    boxes = [b for b in (frame.get('result') or {}).get('boxes', []) if b.get('category') == cat]
    best = max(preds, key=lambda p: p.get('score', 0)) if preds else None
    clean = {k: v for k, v in issue.items() if k not in ('photo_name',)}
    return dict(status='ok', source='video', category=cat, suggested_category=cat, label=best['label'] if best else cat,
                confidence=round(max([p['confidence'] for p in preds] or [0]), 3), reliability=issue['score'],
                reliability_calibrated=all(p.get('calibrated') for p in preds) if preds else False,
                needs_confirmation=issue['needs_confirmation'], conflict=issue['status'] == 'conflict', multiple_issues=False,
                issues=[clean], reasons=[f"Part of a video: seen at {', '.join('%d:%02d' % (t // 60, t % 60) for t in issue['timestamps'])}."],
                predictions=preds, boxes=boxes, annotated=issue.get('annotated'), model_name='+'.join(sorted({p['model'] for p in preds})) or None,
                models=result.get('models', []), models_available=result.get('models_available'), models_total=result.get('models_total'),
                video=result.get('video') or {})
