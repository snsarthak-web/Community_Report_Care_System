"""Video pipeline tests: real OpenCV video files (mp4 / webm / avi) + a fake ultralytics (scripted detections).
No Flask, no database, no real weights.   Run:  python tests/test_ai_video.py"""
import json, os, sys, tempfile, time, types
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import cv2, numpy as np

# fake ultralytics: detections depend on the frame's colour
class T(list):
    def tolist(self): return list(self)
class FBox:
    def __init__(s, xyxy, cls, conf): s.xyxy, s.cls, s.conf = [T(xyxy)], cls, conf
class FRes:
    def __init__(s, boxes): s.boxes, s.probs, s.orig_shape, s.names = boxes, None, (200, 300), {}
NAMES = {'Model_1.pt': {0: 'Pothole', 1: 'Garbage'}, 'Model_2.pt': {0: 'open_manhole', 1: 'litter'}, 'Model_3.pt': {0: 'broken_street_light'}, 'Model_4.pt': {0: 'pothole', 1: 'garbage'}, 'Model_5.pt': {0: 'pothole', 1: 'garbage'}}
LEFT, RIGHT = (30, 40, 130, 140), (180, 40, 280, 140)
class FakeYOLO:
    def __init__(s, path): s.fn, s.task, s.names = os.path.basename(path), 'detect', NAMES[os.path.basename(path)]
    def __call__(s, img, **kw):
        m = cv2.imread(img).reshape(-1, 3).mean(axis=0)                    # BGR mean
        first_half = m[0] > m[1]                                           # blue-ish frame = first half of the video
        if s.fn == 'Model_4.pt' and first_half: return [FRes([FBox(LEFT, 0, .9)])]
        if s.fn == 'Model_1.pt' and first_half: return [FRes([FBox((35, 45, 135, 145), 0, .8)])]
        if s.fn == 'Model_2.pt' and not first_half: return [FRes([FBox(RIGHT, 1, .85)])]
        return [FRes([])]
fake = types.ModuleType('ultralytics'); fake.YOLO = FakeYOLO; sys.modules['ultralytics'] = fake
from ai import video as V, video_jobs as J, manager as M, store

RES = []
def chk(name, cond): RES.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name)
TMP = tempfile.mkdtemp()

def make_video(name, frames=60, fps=10, fourcc='mp4v', sharp_every=10, size=(320, 240)):
    """Blue-ish first half, green-ish second half. Only every `sharp_every`-th frame is sharp; the rest are blurred (like motion blur)."""
    path = os.path.join(TMP, name)
    w = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*fourcc), fps, size)
    rng = np.random.default_rng(1)
    for k in range(frames):
        img = np.zeros((size[1], size[0], 3), np.uint8); img[:] = (200, 50, 50) if k < frames // 2 else (50, 200, 50)
        img = np.clip(img.astype(int) + rng.integers(-60, 60, img.shape), 0, 255).astype(np.uint8)        # texture
        if k % sharp_every:
            img = cv2.GaussianBlur(img, (21, 21), 0)
        w.write(img)
    w.release()
    return path

def world():
    d = tempfile.mkdtemp(); M._CACHE.clear()
    for fn in NAMES: open(os.path.join(d, fn), 'wb').write(b'PK\x03\x04fake')
    up, res = os.path.join(d, 'uploads'), os.path.join(d, 'results'); os.makedirs(up); os.makedirs(res)
    return {'AI_MODELS_DIR': d, 'AI_RELIABILITY_FILE': os.path.join(d, 'x.json'), 'AI_CLASSMAP_FILE': os.path.join(d, 'x.json')}, up, res

# container sniffing (never trust the extension)
chk('[sniff] mp4 / mov / 3gp / webm recognised from magic bytes',
    V.sniff_container(b'\x00\x00\x00\x18ftypmp42....') == 'mp4' and V.sniff_container(b'\x00\x00\x00\x14ftypqt  ....') == 'mov'
    and V.sniff_container(b'\x00\x00\x00\x14ftyp3gp4....') == '3gp' and V.sniff_container(b'\x1a\x45\xdf\xa3\x01\x00\x00\x00') == 'webm')
chk('[sniff] images, scripts, avi, empty are rejected', all(V.sniff_container(h) is None for h in (b'\xff\xd8\xff\xe0' + b'0' * 20, b'<?php echo 1; ?>......', b'RIFF....AVI LIST', b'', b'GIF89a' + b'0' * 10)))

# probe
mp4 = make_video('a.mp4'); webm = make_video('a.webm', fourcc='VP90'); avi = make_video('a.avi', fourcc='MJPG')
for p in (mp4, webm, avi):
    i = V.probe(p, {}); chk(f'[probe] {os.path.splitext(p)[1]}: {i["duration"]}s, {i["fps"]} fps, {i["frames"]} frames, {i["width"]}x{i["height"]}', abs(i['duration'] - 6) < .3 and i['frames'] == 60)
junk = os.path.join(TMP, 'junk.mp4'); open(junk, 'wb').write(os.urandom(5000))
def raises(fn, text):
    try: fn(); return False
    except ValueError as e: return text in str(e)
chk('[probe] a non-video file renamed .mp4 is refused with a friendly message', raises(lambda: V.probe(junk, {}), 'could not be opened'))
chk('[probe] too long is refused (max seconds is configurable)', raises(lambda: V.probe(mp4, {'VIDEO_MAX_SECONDS': 3}), 'too long'))
tiny = make_video('tiny.mp4', frames=3)
chk('[probe] too short is refused', raises(lambda: V.probe(tiny, {}), 'too short'))

# frame planning + sharp-frame selection
for total, fps, dur in ((60, 10, 6), (900, 30, 30), (20, 10, 2), (5, 5, 1)):
    t = V.plan_targets(total, fps, dur, {}); chk(f'[plan] {dur}s video -> {len(t)} frames, sorted, unique, in range', t == sorted(set(t)) and 1 <= len(t) <= 8 and 0 <= t[0] and t[-1] < total)
fr = V.extract_frames(mp4, os.path.join(TMP, 'fr'), V.probe(mp4, {}), {})
sharp = [cv2.Laplacian(cv2.cvtColor(cv2.imread(f['path']), cv2.COLOR_BGR2GRAY), cv2.CV_64F).var() for f in fr]
chk('[extract] one frame per planned moment, timestamps increasing: ' + str([f['t'] for f in fr]), len(fr) == 3 and [f['t'] for f in fr] == sorted(f['t'] for f in fr))
chk('[extract] the SHARP frame is chosen in each window, blurred neighbours rejected: ' + str([f['index'] for f in fr]), [f['index'] for f in fr] == [10, 30, 50] and min(sharp) > 800)
fw = V.extract_frames(webm, os.path.join(TMP, 'frw'), V.probe(webm, {}), {})
chk('[extract] works on WebM (no seek index needed)', len(fw) == 3)

# full pipeline with the five (fake) models
cfg, up, res = world()
r, frames = V.analyze_video(mp4, dict(cfg, VIDEO_SAMPLE_SECONDS=1.0, VIDEO_MAX_FRAMES=6), os.path.join(TMP, 'f2'), up)   # 6 frames: 3 per half
cats = {i['category']: i for i in r['issues']}
chk('[video] both issues found, with timestamps: ' + str({c: i['timestamps'] for c, i in cats.items()}), set(cats) == {'Pothole', 'Garbage'} and all(t < 3.0 for t in cats['Pothole']['timestamps']) and all(t >= 3.0 for t in cats['Garbage']['timestamps']))
chk('[video] first half = Pothole seen by 2 models (agreed), second half = Garbage (1 model)', cats['Pothole']['status'] == 'agreed' and cats['Garbage']['status'] == 'single')
chk('[video] different issues at different times are NOT conflicts, but the citizen is told (multiple issues)', not r['conflict'] and r['multiple_issues'] and r['needs_confirmation'])
chk('[video] suggestion is the stronger issue; reliability/confidence/label reported', r['category'] == 'Pothole' and r['reliability'] > 0 and r['confidence'] == .9 and r['label'] == 'pothole')
chk('[video] annotated frame written for every analysed frame', len(r['frames']) == 6 and all(f['annotated'] and os.path.exists(os.path.join(up, f['annotated'])) for f in r['frames']))
chk('[video] predictions carry frame index + timestamp + model + bbox + frame image', all(p['timestamp_sec'] is not None and p['model'] and p['bbox'] and p['frame_image'] for p in r['predictions']) and len(r['predictions']) == 9)
chk('[video] all five models took part in every frame', r['models_total'] == 5 and r['models_available'] == 5 and r['source'] == 'video' and r['video']['frames_analyzed'] == 6)
chk('[video] best frame identified (sharpest frame of the main issue)', r['best_frame']['t'] < 3.0 and r['annotated'])

# aggregation rules (unit)
def fake_frame(i, t, issues, models=()):
    return {'index': i, 't': t, 'path': f'/x{i}.jpg', 'annotated': f'ai_{i:012x}.jpg', 'result': {'issues': issues, 'predictions': [], 'models': list(models), 'boxes': []}}
iss = lambda cat, s, st='single', models=('own_model',): {'category': cat, 'score': s, 'status': st, 'models': list(models), 'box': [0, 0, .1, .1]}
mk = lambda *fs: V.aggregate(list(fs), {})
a = mk(fake_frame(1, 1.0, [iss('Pothole', .7)]), fake_frame(2, 3.0, []), fake_frame(3, 5.0, []))
chk('[aggregate] a category seen in ONE of several frames is discounted and flagged', a['issues'][0]['score'] == round(.7 * .7, 3) and a['needs_confirmation'] and any('only one frame' in x for x in a['reasons']))
b = mk(*[fake_frame(i, i * 1.0, [iss('Pothole', .7)]) for i in range(1, 5)])
chk('[aggregate] the same category in 4 frames is NOT discounted (persistence)', b['issues'][0]['score'] == .7 and b['issues'][0]['frames_seen'] == 4 and not b['needs_confirmation'])
c = mk(*[fake_frame(i, i * 1.0, [iss('Pothole', .6, 'conflict')]) for i in range(1, 4)])
chk('[aggregate] frame-level conflicts carry into the video result', c['conflict'] and c['needs_confirmation'])
ok4 = [{'name': 'own_model', 'status': 'ok', 'error': None, 'ms': 1}]
d0 = mk(fake_frame(1, 1.0, [], ok4), fake_frame(2, 2.0, [], ok4))
chk('[aggregate] nothing detected in any frame -> status none, empty list', d0['status'] == 'none' and d0['issues'] == [] and d0['predictions'] == [])
n0 = V.aggregate([dict(fake_frame(1, 1.0, []), result={'issues': [], 'predictions': [], 'boxes': [], 'models': [{'name': 'a', 'status': 'unavailable', 'error': 'file not found'}]})], {})
chk('[aggregate] no model available -> no_model (graceful, like images)', n0['status'] == 'no_model')

# GPS
g = J.clean_gps(json.dumps([{'t': 1, 'lat': 12.9, 'lng': 77.6, 'acc': 8}, {'t': 2, 'lat': 91, 'lng': 0}, {'t': 3, 'lat': 0, 'lng': 0}, {'t': 'x', 'lat': 1, 'lng': 1}, {'lat': 'a', 'lng': 1}, 'junk', {'t': 9, 'lat': 12.91, 'lng': 77.61, 'acc': 30}]))
chk('[gps] invalid / (0,0) / malformed fixes dropped, valid kept: ' + str(len(g)), len(g) == 2 and g[0]['lat'] == 12.9)
chk('[gps] capped at 120 points; garbage input is safe', len(J.clean_gps([{'t': i, 'lat': 1, 'lng': 1} for i in range(500)])) == 120 and J.clean_gps('not json') == [] and J.clean_gps(None) == [])
chk('[gps] nearest accurate fix to a moment is chosen', J.fix_near(g, 8)['t'] == 9 and J.fix_near([], 1) is None)

# background job (thread, progress file, representative photo)
cfg, up, res = world(); name = J.new_name('mp4')
import shutil; shutil.copyfile(mp4, os.path.join(up, name))
J.create(res, name, 7, [{'t': 1, 'lat': 12.9, 'lng': 77.6, 'acc': 8}], os.path.getsize(mp4))
chk('[job] queued record exists, readable only by its owner', J.read(res, name, 7)['status'] == 'queued' and J.read(res, name, 8) is None)
t = J.start(cfg, res, up, name, 7); t.join(60)
rec = J.read(res, name, 7)
chk('[job] finished: status done, progress file complete', rec['status'] == 'done' and rec['result']['category'] == 'Pothole')
photo = rec['photo_name']
chk('[job] best frame saved as the complaint\'s ordinary photo (16-hex .jpg) so the existing flow works', photo and len(photo) == 20 and os.path.exists(os.path.join(up, photo)))
chk('[job] the image flow\'s store holds the same analysis (complaint creation needs no special case)', (store.load(res, photo, 7) or {}).get('source') == 'video' and store.load(res, photo, 8) is None)
chk('[job] GPS fix nearest the best frame is offered as the location', rec['result']['location'] and rec['result']['location']['lat'] == 12.9)
bad = J.new_name('mp4'); open(os.path.join(up, bad), 'wb').write(os.urandom(4000)); J.create(res, bad, 7, [], 4000); J.start(cfg, res, up, bad, 7).join(30)
b = J.read(res, bad, 7); chk('[job] an unreadable video ends as a friendly error, never a crash: ' + str(b['error']), b['status'] == 'error' and 'could not be opened' in b['error'])
chk('[job] names are validated (no path traversal)', J.read(res, '../../etc/passwd', 7) is None and J.read(res, 'vid_zzzz.mp4', 7) is None)

# orphan clean-up
old = J.new_name('mp4'); keep = J.new_name('mp4')
for n in (old, keep):
    open(os.path.join(up, n), 'wb').write(b'x'); J.create(res, n, 7, [], 1)
for n in (old, keep):
    p = os.path.join(res, n[:-4] + '.json'); d = json.load(open(p)); d['created'] = time.time() - 5 * 86400; json.dump(d, open(p, 'w'))
J.mark_attached(res, keep)
removed = J.prune_orphans(res, up)
chk('[cleanup] an old UNATTACHED video is deleted, an attached one is kept', removed >= 1 and not os.path.exists(os.path.join(up, old)) and os.path.exists(os.path.join(up, keep)))
live = J.new_name('mp4'); open(os.path.join(up, live), 'wb').write(b'x'); J.create(res, live, 7, [], 1)
d = json.load(open(os.path.join(res, live[:-4] + '.json'))); d.update(status='processing', created=time.time() - 600); json.dump(d, open(os.path.join(res, live[:-4] + '.json'), 'w'))
J.prune_orphans(res, up, max_age=60)
chk('[cleanup] a video that is still being analysed (10 min old) is never deleted', os.path.exists(os.path.join(up, live)))

print(f'\n{sum(RES)}/{len(RES)} checks passed'); sys.exit(0 if all(RES) else 1)
