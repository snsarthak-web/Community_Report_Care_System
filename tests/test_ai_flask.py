"""Integration tests for: five-model AI, video evidence, the Admin Filter fix and the footer account-switch fix.
Needs the real Flask-SQLAlchemy / Flask-Login stack (pip install -r requirements.txt):     python tests/test_ai_flask.py
A fake ultralytics supplies scripted detections, so no real weights are needed. Throw-away database, so no real data is touched.
If a line fails, the pass/fail text tells you which feature."""
import io, json, os, sys, tempfile, time, types
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import cv2, numpy as np
from PIL import Image

# fake ultralytics (detections depend on file name + frame colour)
class T(list):
    def tolist(self): return list(self)
class FBox:
    def __init__(s, xyxy, cls, conf): s.xyxy, s.cls, s.conf = [T(xyxy)], cls, conf
class FRes:
    def __init__(s, boxes): s.boxes, s.probs, s.orig_shape, s.names = boxes, None, (200, 300), {}
NAMES = {'Model_1.pt': {0: 'Pothole', 1: 'Garbage'}, 'Model_2.pt': {0: 'open_manhole', 1: 'litter'}, 'Model_3.pt': {0: 'broken_street_light'}, 'Model_4.pt': {0: 'pothole', 1: 'garbage'}, 'Model_5.pt': {0: 'pothole', 1: 'garbage'}}
class FakeYOLO:
    def __init__(s, path): s.fn, s.task, s.names = os.path.basename(path), 'detect', NAMES[os.path.basename(path)]
    def __call__(s, img, **kw):
        m = cv2.imread(img).reshape(-1, 3).mean(axis=0); blue = m[0] > m[1]            # blue-ish frame = "pothole scene", green-ish = "garbage scene"
        if s.fn == 'Model_4.pt' and blue: return [FRes([FBox((30, 40, 130, 140), 0, .9)])]
        if s.fn == 'Model_1.pt' and blue: return [FRes([FBox((35, 45, 135, 145), 0, .8)])]
        if s.fn == 'Model_2.pt' and not blue: return [FRes([FBox((180, 40, 280, 140), 1, .85)])]
        return [FRes([])]
fake = types.ModuleType('ultralytics'); fake.YOLO = FakeYOLO; sys.modules['ultralytics'] = fake

import ai.detectors.base as _B; _B.RETRY_AFTER = 0          # the app waits 30 s before retrying a missing model; the test copies the files in a moment later
from app import create_app
tmp = tempfile.mkdtemp(); mdir = os.path.join(tmp, 'models'); os.makedirs(mdir)
app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + os.path.join(tmp, 't.db').replace('\\', '/'), 'DB_PATH': os.path.join(tmp, 't.db'),
                  'UPLOAD_FOLDER': os.path.join(tmp, 'up'), 'ADMIN_EMAIL': 'boss@crc.local', 'ADMIN_PASSWORD': 'BossPassw0rd!',
                  'AI_MODELS_DIR': mdir, 'AI_RESULTS_DIR': os.path.join(tmp, 'results'), 'AI_RELIABILITY_FILE': os.path.join(tmp, 'none.json'), 'AI_CLASSMAP_FILE': os.path.join(tmp, 'none.json'),
                  'VIDEO_SAMPLE_SECONDS': 1.0, 'VIDEO_MAX_FRAMES': 6})
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
RES = []
def chk(name, cond): RES.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name)
def tok(c):
    with c.session_transaction() as s: return s.get('csrf')
def client(): c = app.test_client(); c.get('/login'); return c
def fresh(c): c.get('/', follow_redirects=True); return tok(c)
def txt(r): return r.get_data(as_text=True)
def reg(c, name, email, pw='Passw0rd!'): return c.post('/register', data=dict(name=name, email=email, password=pw, confirm=pw, phone='', csrf_token=tok(c)))
def blue_png(): b = io.BytesIO(); Image.new('RGB', (300, 200), (40, 60, 200)).save(b, 'PNG'); b.seek(0); return (b, 'a.png')
def make_video(path, frames=60, fps=10):
    w = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*'mp4v'), fps, (320, 240)); rng = np.random.default_rng(1)
    for k in range(frames):
        img = np.zeros((240, 320, 3), np.uint8); img[:] = (200, 50, 50) if k < frames // 2 else (50, 200, 50)
        img = np.clip(img.astype(int) + rng.integers(-40, 40, img.shape), 0, 255).astype(np.uint8)
        w.write(img if k % 10 == 0 else cv2.GaussianBlur(img, (15, 15), 0))
    w.release()

A, ADM = client(), client()
chk('register citizen', reg(A, 'Asha', 'a@x.com').status_code == 302)
chk('admin login', ADM.post('/admin/login', data=dict(email='boss@crc.local', password='BossPassw0rd!', csrf_token=tok(ADM))).status_code == 302); fresh(ADM)

# categories
chk('15 categories configured', len(app.config['CATEGORIES']) == 15 and 'Open Manhole' in app.config['CATEGORIES'] and 'Damaged Electrical Wires' in app.config['CATEGORIES'])
chk('a NEW category can be reported manually', A.post('/report/manual', data=dict(category='Open Manhole', location_text='Near the school gate', csrf_token=fresh(A))).status_code == 302)

# AI detect: no model files, then five models
H = {'X-CSRFToken': fresh(A)}
r = A.post('/upload/photo', data={'photo': blue_png()}, headers=H, content_type='multipart/form-data'); ph = r.json['photo_name']
r = A.post('/ai/detect', json={'photo_name': ph}, headers=H)
chk('no checkpoints -> status no_model, old keys + new keys present', r.status_code == 200 and r.json['status'] == 'no_model' and all(k in r.json for k in ('label', 'category', 'confidence', 'boxes', 'predictions', 'issues', 'models', 'needs_confirmation')))
for fn in NAMES: open(os.path.join(mdir, fn), 'wb').write(b'PK\x03\x04fake-checkpoint')
r = A.post('/ai/detect', json={'photo_name': ph}, headers=H); j = r.json
chk('five models ran on the same photo', j['status'] == 'ok' and j['models_available'] == 5 and j['models_total'] == 5)
chk('two models agree -> Pothole, with every model\'s prediction returned', j['category'] == 'Pothole' and j['suggested_category'] == 'Pothole' and len(j['predictions']) == 2 and {p['model'] for p in j['predictions']} == {'own_model', 'civicresolve'})
chk('response has reliability, confirmation flag and an annotated image URL', 'reliability' in j and j['needs_confirmation'] is False and j['annotated_url'] and os.path.exists(os.path.join(app.config['UPLOAD_FOLDER'], os.path.basename(j['annotated_url']))))      # the temp upload folder is not served by /static
chk('detect still blocks path traversal', A.post('/ai/detect', json={'photo_name': '../../etc/passwd'}, headers=H).status_code == 400)

# create a complaint: the citizen corrects the AI
form = lambda **k: dict(dict(category='Garbage', description='', lat='20.2700', lng='85.8400', location_text='Main Rd', photo_name=ph, csrf_token=tok(A)), **k)
r = A.post('/report/ai', data=form()); tid = r.headers['Location'].split('/')[-1]; chk('AI report created ' + tid, r.status_code == 302 and tid.startswith('CRC-'))
with app.app_context():
    from models import Complaint, AIPrediction, AIAnalysis, AIDetection, ComplaintVideo
    c = Complaint.query.filter_by(tracking_id=tid).first(); an = c.ai_analysis; preds = c.ai_predictions
    chk('complaint keeps the CITIZEN\'s category (AI never overwrites it)', c.category == 'Garbage')
    chk('every model prediction stored (model, original label, category, confidence, box)', len(preds) == 2 and all(p.model_name and p.model_label and p.category == 'Pothole' and p.confidence and p.bounding_box for p in preds))
    chk('AI suggestion and citizen choice both recorded in the analysis row', an and an.suggested_category == 'Pothole' and an.citizen_category == 'Garbage')
    chk('old AIDetection summary row still written (old screens keep working)', c.detection is not None and c.detection.detected_object)
    pid = preds[0].id
chk('citizen sees the AI panel on their complaint', 'AI analysis' in txt(A.get('/complaint/' + tid)) and 'Verdict' not in txt(A.get('/complaint/' + tid)))

# admin: panel, per-prediction verdict, filter fix
p = txt(ADM.get('/admin/complaint/' + tid)); chk('admin detail shows all model predictions + verdict controls', 'AI analysis' in p and 'own_model' in p and 'civicresolve' in p and 'ai-prediction' in p)
chk('admin marks one prediction correct', ADM.post(f'/admin/ai-prediction/{pid}', data=dict(verdict='1', csrf_token=tok(ADM)), follow_redirects=True).status_code == 200)
with app.app_context():
    chk('verdict stored with the admin and a time', AIPrediction.query.get(pid).verified is True and AIPrediction.query.get(pid).verified_by is not None)
chk('citizen cannot post an admin verdict', A.post(f'/admin/ai-prediction/{pid}', data=dict(verdict='0', csrf_token=tok(A))).status_code == 403)
chk('FILTER FIX: the exact URL the Filter button sends (empty department_id) works', ADM.get('/admin/complaints?q=&place=&status=&category=&priority=&department_id=&from=&to=').status_code == 200)
chk('FILTER FIX: with every field filled in', ADM.get('/admin/complaints?q=CRC&place=Main&status=Submitted&category=Garbage&priority=Low&department_id=1&from=2020-01-01&to=2099-01-01').status_code == 200)
chk('CSV export uses local-time headers', 'IST' in txt(ADM.get('/admin/complaints/export.csv')).splitlines()[0])

# video evidence
mp4 = os.path.join(tmp, 'clip.mp4'); make_video(mp4); H = {'X-CSRFToken': fresh(A)}
chk('non-video file refused', A.post('/upload/video', data={'video': (io.BytesIO(b'hello world' * 200), 'x.mp4')}, headers=H, content_type='multipart/form-data').status_code == 400)
chk('an image renamed .mp4 is refused (real file type is checked)', A.post('/upload/video', data={'video': (blue_png()[0], 'x.mp4')}, headers=H, content_type='multipart/form-data').status_code == 400)
chk('video upload without login is blocked', app.test_client().post('/upload/video', data={'video': (open(mp4, 'rb'), 'c.mp4')}, content_type='multipart/form-data').status_code in (302, 400, 401, 403))
gps = [{'t': 1, 'lat': 20.27, 'lng': 85.84, 'acc': 9}, {'t': 4, 'lat': 20.2701, 'lng': 85.8401, 'acc': 7}, {'t': 2, 'lat': 999, 'lng': 0}]
r = A.post('/upload/video', data={'video': (open(mp4, 'rb'), 'clip.mp4'), 'gps': json.dumps(gps)}, headers=H, content_type='multipart/form-data'); vname = r.json.get('video_name')
chk('video accepted and queued', r.status_code == 200 and vname and vname.startswith('vid_'))
st = {}
for _ in range(120):
    st = A.get(f'/ai/video/{vname}/status').json
    if st.get('status') in ('done', 'error'): break
    time.sleep(0.5)
res = st.get('result') or {}
chk('analysis finished (status polling works)', st.get('status') == 'done')
chk('both issues found with timestamps; models agree on the pothole', {i['category'] for i in res.get('issues', [])} == {'Pothole', 'Garbage'} and all(i['timestamps'] for i in res['issues']))
chk('result has frames, annotated image URLs, GPS-based location, best-frame photo', res.get('frames') and res.get('photo_name') and res.get('video_url') and res.get('location') and abs(res['location']['lat'] - 20.27) < 0.01)
chk('another citizen cannot read this video job', (lambda o: (reg(o, 'Other', 'o@x.com'), fresh(o), o.get(f'/ai/video/{vname}/status').status_code)[-1])(client()) == 404)
vph = res['photo_name']
r = A.post('/report/ai', data=form(photo_name=vph, video_name=vname, category='Pothole', lat='20.2700', lng='85.8400')); vtid = r.headers['Location'].split('/')[-1]
chk('complaint with video created', r.status_code == 302)
with app.app_context():
    c = Complaint.query.filter_by(tracking_id=vtid).first(); v = c.videos[0] if c.videos else None
    chk('video row saved: file, duration, frames, size', v and v.filename == vname and 5 < v.duration_sec < 7 and v.frames_analyzed >= 3 and v.size_bytes > 1000)
    chk('only the VALID GPS fixes were kept', v and len(v.gps) == 2)
    chk('video predictions carry timestamp + frame', c.ai_analysis.source == 'video' and c.ai_predictions and all(p.timestamp_sec is not None and p.frame_index is not None for p in c.ai_predictions))
    chk('best frame is the complaint\'s normal photo', c.image_path == vph)
chk('admin sees player, timeline, frames, GPS', all(x in txt(ADM.get('/admin/complaint/' + vtid)) for x in ('Video evidence', '<video', 'Analysed frames', 'GPS while recording')))
chk('admin list marks complaints that have video', 'Video' in txt(ADM.get('/admin/complaints')))
chk('the video file is downloadable (so the player can seek)', os.path.exists(os.path.join(app.config['UPLOAD_FOLDER'], os.path.basename(res['video_url']))))
chk('a video can only be attached by its owner and only with its own best-frame photo', (lambda o: (o.post('/report/ai', data=dict(category='Pothole', location_text='x', photo_name=vph, video_name=vname, csrf_token=tok(o))).status_code))(client()) in (302, 200))

# the two bugs from the last message
S1 = client(); reg(S1, 'Sw', 'sw@x.com'); fresh(S1)
chk('footer link in the CITIZEN area points at /admin/login?switch=1', '/admin/login?switch=1' in txt(S1.get('/dashboard')))
chk('citizen: /admin/login WITHOUT switch still bounces to the dashboard (unchanged)', S1.get('/admin/login').status_code == 302)
r = S1.get('/admin/login?switch=1'); chk('citizen footer "Admin Login" now opens the ADMIN login page', r.status_code == 200 and 'Admin Portal' in txt(r))
chk('...and the citizen session was ended (so the admin can sign in)', S1.get('/dashboard').status_code == 302)
AD2 = client(); AD2.post('/admin/login', data=dict(email='boss@crc.local', password='BossPassw0rd!', csrf_token=tok(AD2))); fresh(AD2)
chk('footer link in the ADMIN area points at /login?switch=1', '/login?switch=1' in txt(AD2.get('/admin/')))
chk('admin: /login WITHOUT switch still redirects away (unchanged)', AD2.get('/login').status_code == 302)
r = AD2.get('/login?switch=1'); chk('admin footer "Citizen Login" now opens the CITIZEN login page', r.status_code == 200 and 'Welcome Back' in txt(r))
chk('...and the admin session was ended', AD2.get('/admin/').status_code == 302)

print(f"\n{sum(RES)}/{len(RES)} passed"); sys.exit(0 if all(RES) else 1)
