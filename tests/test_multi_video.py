"""One video -> several verified complaints, with separate locations; location provenance; model families; old-database safety.
Real Flask app + real OpenCV video files + a fake ultralytics (scripted by frame colour). No weights needed.   Run:  python tests/test_multi_video.py"""
import io, json, os, shutil, sqlite3, sys, tempfile, time, types
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import cv2, numpy as np
from PIL import Image

class T(list):
    def tolist(self): return list(self)
class FBox:
    def __init__(s, xyxy, cls, conf): s.xyxy, s.cls, s.conf = [T(xyxy)], cls, conf
class FRes:
    def __init__(s, boxes): s.boxes, s.probs, s.orig_shape, s.names = boxes, None, (200, 300), {}
NAMES = {'Model_1.pt': {0: 'Pothole', 1: 'Garbage'}, 'Model_2.pt': {0: 'open_manhole', 1: 'litter'}, 'Model_3.pt': {0: 'broken_street_light'}, 'Model_4.pt': {0: 'pothole', 1: 'garbage'}, 'Model_5.pt': {0: 'pothole', 1: 'garbage'}}
class FakeYOLO:        # blue-ish frame = pothole (two models), green-ish = garbage (civic_guardian), red-ish = pothole again (own_model only)
    def __init__(s, path): s.fn, s.task, s.names = os.path.basename(path), 'detect', NAMES[os.path.basename(path)]
    def __call__(s, img, **kw):
        b, g, r = cv2.imread(img).reshape(-1, 3).mean(axis=0)
        if s.fn == 'Model_4.pt' and (b > g and b > r or r > g and r > b): return [FRes([FBox((30, 40, 130, 140), 0, .9)])]
        if s.fn == 'Model_1.pt' and b > g and b > r: return [FRes([FBox((35, 45, 135, 145), 0, .8)])]
        if s.fn == 'Model_2.pt' and g > b and g > r: return [FRes([FBox((180, 40, 280, 140), 1, .85)])]
        return [FRes([])]
fake = types.ModuleType('ultralytics'); fake.YOLO = FakeYOLO; sys.modules['ultralytics'] = fake
import ai.detectors.base as _B; _B.RETRY_AFTER = 0
from app import create_app
from ai import decision as D, video as V, video_jobs as J

tmp = tempfile.mkdtemp(); mdir = os.path.join(tmp, 'models'); os.makedirs(mdir)
for fn in NAMES: open(os.path.join(mdir, fn), 'wb').write(b'PK\x03\x04fake')
app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + os.path.join(tmp, 't.db').replace('\\', '/'), 'DB_PATH': os.path.join(tmp, 't.db'),
                  'UPLOAD_FOLDER': os.path.join(tmp, 'up'), 'ADMIN_EMAIL': 'boss@crc.local', 'ADMIN_PASSWORD': 'BossPassw0rd!', 'AI_MODELS_DIR': mdir,
                  'AI_RESULTS_DIR': os.path.join(tmp, 'results'), 'AI_RELIABILITY_FILE': os.path.join(tmp, 'none.json'), 'AI_CLASSMAP_FILE': os.path.join(tmp, 'none.json'),
                  'VIDEO_SAMPLE_SECONDS': 1.0, 'VIDEO_MAX_FRAMES': 9, 'AI_FAMILY_BY_FILE': {}})
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
RES = []
def chk(name, cond): RES.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name)
def tok(c):
    with c.session_transaction() as s: return s.get('csrf')
def client(): c = app.test_client(); c.get('/login'); return c
def fresh(c): c.get('/', follow_redirects=True); return tok(c)
def txt(r): return r.get_data(as_text=True)
def reg(c, name, email, pw='Passw0rd!'): return c.post('/register', data=dict(name=name, email=email, password=pw, confirm=pw, phone='', csrf_token=tok(c)))
def jpost(c, url, body): return c.post(url, json=body, headers={'X-CSRFToken': fresh(c)})
def png(): b = io.BytesIO(); Image.new('RGB', (300, 200), (40, 60, 200)).save(b, 'PNG'); b.seek(0); return (b, 'a.png')

# decision engine: families and containment
def pred(model, cat, conf, box, fam=None): return {'model': model, 'label': cat.lower(), 'class_id': 0, 'confidence': conf, 'bbox': box, 'task': 'detect', 'image_level': False, 'category': cat, 'family': fam or model}
BOX = (.2, .2, .4, .4)
two_indep = D.decide([pred('a', 'Pothole', .8, BOX), pred('b', 'Pothole', .8, BOX)], {}, {})
two_fam = D.decide([pred('a', 'Pothole', .8, BOX, 'f'), pred('b', 'Pothole', .8, BOX, 'f')], {}, {})
chk('[family] two INDEPENDENT models agreeing reinforce each other (status agreed, higher score)', two_indep['issues'][0]['status'] == 'agreed' and two_indep['issues'][0]['score'] > two_fam['issues'][0]['score'])
chk('[family] two checkpoints of ONE family are a single vote (status single, score = the stronger one, both still listed)', two_fam['issues'][0]['status'] == 'single' and len(two_fam['issues'][0]['models']) == 2
    and abs(two_fam['issues'][0]['score'] - round(.8 * .6, 3)) < 1e-6)
loose = D.decide([pred('a', 'Pothole', .9, (.1, .1, .6, .6)), pred('b', 'Pothole', .8, (.2, .2, .3, .3))], {}, {})
chk('[containment] a tight box inside a loose box of the SAME category is one issue, not two', len(loose['issues']) == 1)
tiny = D.decide([pred('a', 'Pothole', .9, (.1, .1, .7, .7)), pred('b', 'Pothole', .8, (.3, .3, .1, .1))], {}, {})
chk('[containment] a tiny box inside a huge one (under 15% of its area) is NOT merged: it may be a different pothole', len(tiny['issues']) == 2)
mixed = D.decide([pred('a', 'Pothole', .9, (.1, .1, .7, .7)), pred('b', 'Garbage', .8, (.3, .3, .2, .2))], {}, {})
chk('[containment] a Garbage box inside a Pothole box is NOT merged away (different category = different object)', len(mixed['issues']) == 2 or mixed['issues'][0]['status'] == 'conflict')
far = D.decide([pred('a', 'Pothole', .9, (.0, .0, .2, .2)), pred('b', 'Pothole', .8, (.6, .6, .2, .2))], {}, {})
chk('[containment] two separate potholes stay two issues', len(far['issues']) == 2)
from ai.calibrate import evaluate
ev = evaluate({f'i{k}': [{'model': 'm', 'category': 'Pothole', 'confidence': .9, 'bbox': BOX}, {'model': 'm', 'category': 'Garbage', 'confidence': .8, 'bbox': (.7, .7, .2, .2)}] for k in range(10)},
              {f'i{k}': [{'category': 'Pothole', 'bbox': BOX}] for k in range(10)})
chk('[calibrate] a category with NO ground truth gets no number (never a fake precision 0.0)', 'Garbage' not in ev['m'] and ev['m']['Pothole']['precision'] == 1.0)

# GPS helpers
rec = [{'t': t, 'lat': 20.0 + t * 0.00004, 'lng': 85.0, 'acc': 8, 'k': 'rec'} for t in range(0, 10)]
chk('[gps] a sample taken while filming, near the moment, is offered with its time distance', V.locate(rec, 4.2, 6)['kind'] == 'video_gps' and V.locate(rec, 4.2, 6)['dt'] <= 0.5)
chk('[gps] a moment far from every sample gets NO location (never guessed)', V.locate(rec, 60, 6) is None)
up = [{'t': 0, 'lat': 20.0, 'lng': 85.0, 'acc': 20, 'k': 'up'}]
chk('[gps] an upload-time fix is offered only as APPROXIMATE (it may not be where the video was filmed)', V.locate(up, 4, 6)['kind'] == 'upload_fix' and V.locate(up, 4, 6)['approx'])
chk('[gps] clean_gps keeps the sample kind and defaults to the cautious "up"', J.clean_gps([{'t': 1, 'lat': 1, 'lng': 1, 'k': 'rec'}, {'t': 1, 'lat': 1, 'lng': 1}])[0]['k'] == 'rec' and J.clean_gps([{'t': 1, 'lat': 1, 'lng': 1}])[0]['k'] == 'up')

# accounts
A, B, ADM = client(), client(), client()
reg(A, 'Asha', 'a@x.com'); reg(B, 'Bob', 'b@x.com')
ADM.post('/admin/login', data=dict(email='boss@crc.local', password='BossPassw0rd!', csrf_token=tok(ADM))); fresh(ADM)

# a 9 s video: pothole (0-3 s), garbage (3-6 s), a second pothole (6-9 s), filmed while walking
def make_video(path, fps=10):
    w = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*'mp4v'), fps, (320, 240)); rng = np.random.default_rng(3)
    for k in range(9 * fps):
        seg = k // (3 * fps); img = np.zeros((240, 320, 3), np.uint8); img[:] = [(200, 50, 50), (50, 200, 50), (50, 50, 200)][seg]       # BGR
        img = np.clip(img.astype(int) + rng.integers(-40, 40, img.shape), 0, 255).astype(np.uint8)
        w.write(img if k % 5 == 0 else cv2.GaussianBlur(img, (15, 15), 0))
    w.release()
mp4 = os.path.join(tmp, 'walk.mp4'); make_video(mp4)
walk = [{'t': round(t * 0.5, 1), 'lat': 20.2700 + t * 0.5 * 0.00012, 'lng': 85.8400, 'acc': 9, 'k': 'rec'} for t in range(0, 19)]      # ~13 m per second: 40 m between segments

def upload(client_, gps):
    H = {'X-CSRFToken': fresh(client_)}
    r = client_.post('/upload/video', data={'video': (open(mp4, 'rb'), 'walk.mp4'), 'gps': json.dumps(gps)}, headers=H, content_type='multipart/form-data')
    name = r.json['video_name']
    for _ in range(120):
        s = client_.get(f'/ai/video/{name}/status').json
        if s['status'] in ('done', 'error'): return name, s
        time.sleep(.5)
    return name, s
name, st = upload(A, walk)
res = st.get('result') or {}
iss = res.get('issues', [])
cats = [i['category'] for i in iss]
chk('[video] analysed: ' + str([(i['id'], i['category'], i['timestamps']) for i in iss]), st['status'] == 'done' and sorted(cats) == ['Garbage', 'Pothole', 'Pothole'])
poth = sorted([i for i in iss if i['category'] == 'Pothole'], key=lambda i: i['best_t'])
chk('[video] the TWO potholes are two separate issues (one video, same category, different places)', len(poth) == 2 and poth[0]['best_t'] < 3 and poth[1]['best_t'] >= 6)
chk('[video] every issue has its OWN saved frame, its own location from the GPS sample nearest in time',
    all(i.get('photo_url') and i.get('location') and i['location']['kind'] == 'video_gps' and i['location']['dt'] <= 1.5 for i in iss)
    and len({(round(i['location']['lat'], 5)) for i in iss}) == 3)
chk('[video] pothole 1 and 2 are tens of metres apart according to GPS', V.dist_m(poth[0]['location'], poth[1]['location']) > 25)
up_dir = app.config['UPLOAD_FOLDER']
chk('[video] frames exist on disk', all(os.path.exists(os.path.join(up_dir, i['photo_name'])) for i in iss) )

# the AI output video: the full video with boxes + labels
from ai import video_render as VR
ann = res.get('annotated_video')
ap = os.path.join(up_dir, ann) if ann else None
cap = cv2.VideoCapture(ap) if ap else None
n_ann = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) if cap else 0
chk('[output video] the job rendered the whole video with AI boxes: ' + str(ann), bool(ann) and os.path.getsize(ap) > 2000 and n_ann >= 60)
from models import User
with app.app_context(): UID = User.query.filter_by(email='a@x.com').first().id
chk('[output video] it is registered for clean-up (job files) and its URL is returned to the browser', ann in (J.read(app.config['AI_RESULTS_DIR'], name, UID) or {}).get('files', []) and st['result'].get('annotated_video_url'))
chk('[output video] length matches the original (about 9 s)', cap and 7.5 <= n_ann / (cap.get(cv2.CAP_PROP_FPS) or 1) <= 10.5)
def frame_at(path, t):
    c = cv2.VideoCapture(path); c.set(cv2.CAP_PROP_POS_MSEC, t * 1000); ok, im = c.read(); c.release(); return im if ok else None
poth1 = min((i for i in iss if i['category'] == 'Pothole'), key=lambda i: i['best_t'])
a_img, o_img = frame_at(ap, poth1['best_t']), frame_at(mp4, poth1['best_t'])
h_, w_ = a_img.shape[:2]; x_, y_, bw_, bh_ = poth1['box']
band = a_img[int(y_ * h_):int(y_ * h_) + 6, int(x_ * w_):int((x_ + bw_) * w_)]
chk('[output video] at the analysed moment the issue\'s box is drawn on the video (box edge colour present)', band.size and (np.abs(band.astype(int) - np.array([0, 140, 255])).sum(axis=2) < 150).mean() > 0.3)
chk('[output video] the original upload is untouched (still a separate file, no boxes)', o_img is not None and os.path.exists(os.path.join(up_dir, name)))
cw = cv2.VideoCapture(os.path.join(up_dir, name)); cw.release()
r2 = VR.render(mp4, tmp, iss, dict(app.config, VIDEO_USE_FFMPEG=False))
cw = cv2.VideoCapture(os.path.join(tmp, r2)); chk('[output video] without ffmpeg a WebM is written and opens: ' + str(r2), r2 and r2.endswith('.webm') and cw.get(cv2.CAP_PROP_FRAME_COUNT) >= 60); cw.release()
chk('[output video] nothing to draw -> no file (no empty video)', VR.render(mp4, tmp, [{'sightings': []}], {}) is None)
# the box follows the object: a real photo panned sideways, box given at one moment only
import glob as _g
ph_ = sorted(_g.glob(os.path.join(os.path.dirname(__file__), 'data', 'real_potholes', '*.jpg')))
if ph_:
    big = cv2.resize(cv2.imread(ph_[0]), (1200, 480)); W2, H2, shift = 640, 480, 8                     # camera pans 8 px per frame to the right
    wv = cv2.VideoWriter(os.path.join(tmp, 'pan.mp4'), cv2.VideoWriter_fourcc(*'mp4v'), 10, (W2, H2))
    for k in range(40): wv.write(big[:, k * shift:k * shift + W2])
    wv.release()
    G = [cv2.cvtColor(cv2.resize(im, (320, 240)), cv2.COLOR_BGR2GRAY) for _k, im in VR._frames(os.path.join(tmp, 'pan.mp4'), 1.0)]
    box0 = (100, 60, 60, 50)                                                                            # pixels in the 320x240 frame at k=10
    tr = dict(VR._track(G, 10, box0, 1, 8))
    expect = 10 * 0 + 8 * (320 / 640)                                                                    # object moves left 4 px (320 px scale) per frame
    ok_follow = tr and all(abs((box0[0] - 4 * (k - 10)) - b[0]) < 3 for k, b in tr.items())
    chk(f'[output video] tracking follows a panning camera within 3 px over {len(tr)} frames', len(tr) >= 6 and ok_follow)
else:
    print('SKIP tracking test (sample photos missing)')
# a failing renderer must never lose the analysis
_orig = VR.render
VR.render = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom'))
nameX, stX = upload(A, walk)
VR.render = _orig
chk('[output video] if rendering fails the analysis still completes (no annotated video, everything else intact)', stX['status'] == 'done' and not stX['result'].get('annotated_video') and len(stX['result']['issues']) == 3)

# submit: 2 of the 3 issues; one category corrected by the citizen; one pin moved
idp = {i['best_t'] < 3 and i['category'] == 'Pothole': i for i in iss if i['category'] == 'Pothole'}
p1, p2 = poth[0], poth[1]; garbage = next(i for i in iss if i['category'] == 'Garbage')
pin = lambda i, **k: dict(dict(id=i['id'], category=i['category'], lat=i['location']['lat'], lng=i['location']['lng'], location_text='', origin='video_gps', acc=i['location']['acc'],
                                cap_lat=i['location']['lat'], cap_lng=i['location']['lng'], dt=i['location']['dt']), **k)
from models import Complaint, ComplaintGeo, ComplaintVideoIssue, ComplaintVideo
with app.app_context(): before = Complaint.query.count()
bad = [('nobody else can submit it', B, dict(video_name=name, issues=[pin(p1)])), ]
chk('[submit] another citizen cannot submit my video', jpost(B, '/report/video/submit', dict(video_name=name, issues=[pin(p1)])).status_code == 400)
chk('[submit] nothing selected -> refused', jpost(A, '/report/video/submit', dict(video_name=name, issues=[])).status_code == 400)
chk('[submit] an issue id that is not in this video -> refused', jpost(A, '/report/video/submit', dict(video_name=name, issues=[pin(p1, id='i99')])).status_code == 400)
chk('[submit] an unknown category -> refused', jpost(A, '/report/video/submit', dict(video_name=name, issues=[pin(p1, category='Hack')])).status_code == 400)
chk('[submit] the same issue twice -> refused', jpost(A, '/report/video/submit', dict(video_name=name, issues=[pin(p1), pin(p1)])).status_code == 400)
chk('[submit] an issue with no place at all -> refused (GPS denied is fine, but SOME place is needed)', jpost(A, '/report/video/submit', dict(video_name=name, issues=[pin(p1, lat=None, lng=None, location_text='', origin=None)])).status_code == 400)
chk('[submit] invalid coordinates -> refused', jpost(A, '/report/video/submit', dict(video_name=name, issues=[pin(p1, lat=95)])).status_code == 400)
with app.app_context(): chk('[submit] every refused attempt saved NOTHING', Complaint.query.count() == before)
moved_lat = p2['location']['lat'] + 0.0004                                     # the citizen drags pothole 2's pin about 44 m
r = jpost(A, '/report/video/submit', dict(video_name=name, description='Two potholes and the cover is missing', issues=[
    pin(p1), pin(p2, lat=moved_lat), ]))
chk('[submit] two confirmed issues -> two complaints: ' + str(r.json), r.status_code == 200 and r.json['ok'] and len(r.json['tracking_ids']) == 2)
t1, t2 = r.json['tracking_ids']
with app.app_context():
    c1, c2 = Complaint.query.filter_by(tracking_id=t1).first(), Complaint.query.filter_by(tracking_id=t2).first()
    chk('[submit] separate complaints with separate coordinates and separate frames', c1.latitude != c2.latitude and c1.image_path != c2.image_path and c1.category == c2.category == 'Pothole')
    chk('[submit] both share ONE group and the SAME original video file', c1.video_issue.group_id == c2.video_issue.group_id and c1.videos[0].filename == c2.videos[0].filename == name
        and os.path.exists(os.path.join(up_dir, name)))
    chk('[submit] each remembers its own moment in the video', c1.video_issue.timestamp_sec < 3 and c2.video_issue.timestamp_sec >= 6)
    chk('[provenance] untouched GPS pin: source video_gps, accuracy and sample distance kept', c1.geo.source == 'video_gps' and c1.geo.accuracy_m == 9 and c1.geo.sample_dt_sec is not None and (c1.geo.moved_m or 0) < 5)
    chk('[provenance] a pin the citizen moved is recorded as adjusted, with the distance', c2.geo.source == 'video_gps_adjusted' and 35 < c2.geo.moved_m < 55 and abs(c2.latitude - moved_lat) < 1e-5)
    chk('[ai] each complaint has its own AI record (predictions of ITS frame), and the old summary row', len(c1.ai_predictions) >= 1 and c1.detection is not None and c1.ai_analysis.source == 'video'
        and all(p.timestamp_sec is not None and p.timestamp_sec < 3.5 for p in c1.ai_predictions))
    chk('[submit] 1 video + 2 complaints: the garbage issue the citizen did NOT tick created nothing and its frame was removed', Complaint.query.count() == before + 2 and not os.path.exists(os.path.join(up_dir, garbage['photo_name'])))
chk('[submit] the video cannot be submitted a second time', jpost(A, '/report/video/submit', dict(video_name=name, issues=[pin(garbage)])).status_code == 409)
with app.app_context():
    chk('[output video] saved with the complaint (summary keeps the file name) and shared by sibling complaints', Complaint.query.filter_by(tracking_id=t1).first().videos[0].summary.get('annotated_video') == ann == Complaint.query.filter_by(tracking_id=t2).first().videos[0].summary.get('annotated_video'))
chk('[pages] citizen video evidence plays the video WITH boxes by default and can switch to the original', all(x in txt(A.get('/complaint/' + t1)) for x in ('With AI boxes', 'Original video', 'data-ann=', 'data-orig=', ann)))
chk('[pages] citizen page shows where the location came from and links the sibling complaint', all(x in txt(A.get('/complaint/' + t1)) for x in ('Location source', t2, 'Reported from a video')))
page = txt(ADM.get('/admin/complaint/' + t2)); chk('[pages] admin page: provenance, "pin moved", sibling link, video evidence', all(x in page for x in ('pin moved', t1, 'Reported from a video', 'Video evidence')))
chk('[pages] admin map and filters render (department / priority filters added)', ADM.get('/admin/map?priority=Low&department_id=').status_code == 200 and 'All departments' in txt(ADM.get('/admin/map')))
r = ADM.get('/admin/ai-review'); chk('[pages] admin AI Review shows the model scoreboard with files and families', r.status_code == 200 and 'Admin verdicts' in txt(r) and 'Model_4' in txt(r))
chk('[pages] other citizens cannot see these complaints', B.get('/complaint/' + t1).status_code == 404)

# one-issue video, and a video with no GPS (still works: pins are placed by hand)
name2, st2 = upload(A, [])
iss2 = (st2.get('result') or {}).get('issues', [])
chk('[nogps] no GPS at all: issues are still found, none gets an invented location', st2['status'] == 'done' and len(iss2) >= 2 and all(not i.get('location') for i in iss2))
g2 = next(i for i in iss2 if i['category'] == 'Garbage')
r = jpost(A, '/report/video/submit', dict(video_name=name2, issues=[dict(id=g2['id'], category='Garbage', lat=20.28, lng=85.85, location_text='', origin=None)]))
chk('[nogps] one ticked issue, pin placed by hand -> one complaint, source map_pin', r.status_code == 200 and len(r.json['tracking_ids']) == 1)
with app.app_context(): chk('[nogps] geo source map_pin, no accuracy, no sample time', ComplaintGeo.query.join(Complaint).filter(Complaint.tracking_id == r.json['tracking_ids'][0]).first().source == 'map_pin')
name3, st3 = upload(A, [{'t': 0, 'lat': 20.5, 'lng': 85.5, 'acc': 25, 'k': 'up'}])
i3 = (st3.get('result') or {}).get('issues', [])
chk('[upload-fix] a fix taken at upload time is offered as approximate, never as video GPS', i3 and all(i['location'] and i['location']['kind'] == 'upload_fix' and i['location']['approx'] for i in i3))

# photo / manual reports: GPS optional and recorded honestly
H = {'X-CSRFToken': fresh(A)}; ph = A.post('/upload/photo', data={'photo': png()}, headers=H, content_type='multipart/form-data').json['photo_name']
form = lambda **k: dict(dict(category='Pothole', description='', lat='20.2700', lng='85.8400', location_text='', photo_name=ph, csrf_token=fresh(A)), **k)
def geo_of(r):
    tid = r.headers['Location'].split('/')[-1]
    with app.app_context(): return Complaint.query.filter_by(tracking_id=tid).first().geo
g = geo_of(A.post('/report/manual', data=form(loc_origin='gps', loc_acc='12.5', cap_lat='20.2700', cap_lng='85.8400')))
chk('[location] GPS pin left alone -> source gps, accuracy 12.5 m kept', g.source == 'gps' and g.accuracy_m == 12.5 and g.moved_m < 1)
g = geo_of(A.post('/report/manual', data=form(loc_origin='gps', loc_acc='12.5', cap_lat='20.2690', cap_lng='85.8400')))
chk('[location] pin dragged away from the GPS fix -> gps_adjusted, ~111 m recorded', g.source == 'gps_adjusted' and 100 < g.moved_m < 125)
g = geo_of(A.post('/report/manual', data=form()))
chk('[location] GPS refused, pin tapped on the map -> map_pin (GPS denial never blocks a report)', g.source == 'map_pin' and g.accuracy_m is None)
g = geo_of(A.post('/report/manual', data=form(lat='', lng='', location_text='Opposite City Hospital')))
chk('[location] GPS refused and no pin, only a landmark -> landmark', g.source == 'landmark')
r = A.post('/report/manual', data=form(lat='', lng='', location_text='')); chk('[location] no GPS, no pin, no landmark -> asked for a place', r.status_code == 302 and '/report/manual' in r.headers['Location'])
r = A.post('/report/manual', data=form(loc_origin='gps', loc_acc='-5', cap_lat='999', cap_lng='0')); chk('[location] garbage accuracy / capture values are ignored safely (no crash)', r.status_code == 302 and geo_of(r).source == 'map_pin')

# the report page itself
page = txt(A.get('/report/ai'))
chk('[page] Step 1 has ONE optional location tick-box with the pending / captured / unavailable states', 'id="use-loc"' in page and 'Location not captured yet' in page and 'locstate' in page and 'id="vgps"' not in page)
chk('[page] Step 5 shows coordinates + accuracy panel, and the video issue picker/category containers exist', 'id="coords"' in page and 'id="ai-picker"' in page and 'id="cat-multi"' in page and 'data-video-submit' in page)
js = open(os.path.join(os.path.dirname(__file__), '..', 'static', 'js', 'report.js'), encoding='utf-8').read()
import subprocess
node = shutil.which('node')
if node: chk('[js] report.js, video.js and ai_panel.js are syntactically valid (node --check)', all(subprocess.run([node, '--check', os.path.join(os.path.dirname(__file__), '..', 'static', 'js', f_)], capture_output=True).returncode == 0 for f_ in ('report.js', 'video.js', 'ai_panel.js')))
apj = open(os.path.join(os.path.dirname(__file__), '..', 'static', 'js', 'ai_panel.js'), encoding='utf-8').read()
chk('[js] ai_panel.js keeps the timestamp seek handler and the AI-boxes / original switch', 'data-seek' in apj and 'data-vsrc' in apj and 'offsetParent' in apj)
chk('[js] getCurrentPosition is only called from requestFix (one place), never from navigation', js.count('getCurrentPosition') == 1 and 'function requestFix' in js)
vjs = open(os.path.join(os.path.dirname(__file__), '..', 'static', 'js', 'video.js'), encoding='utf-8').read()
chk('[js] video.js asks the browser for a fix only while recording (watchPosition); gallery videos reuse Step 1\'s fix', vjs.count('getCurrentPosition') == 0 and "k: 'rec'" in vjs and "k: 'up'" in vjs)

# the shipped database (old complaint) still works
shipped = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'instance', 'database.db')
if os.path.exists(shipped):
    old = os.path.join(tmp, 'old.db'); shutil.copyfile(shipped, old)
    n_before = sqlite3.connect(old).execute('select count(*) from complaints').fetchone()[0]
    app2 = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + old.replace('\\', '/'), 'DB_PATH': old, 'UPLOAD_FOLDER': os.path.join(tmp, 'up2'), 'AI_MODELS_DIR': os.path.join(tmp, 'nomodels')})
    cx = sqlite3.connect(old); tabs = {r[0] for r in cx.execute("select name from sqlite_master where type='table'")}
    chk('[old db] new tables were ADDED, no old table touched, old complaint count unchanged', {'complaint_geo', 'complaint_video_issues'} <= tabs and cx.execute('select count(*) from complaints').fetchone()[0] == n_before)
    with app2.app_context():
        c = Complaint.query.first()
        if c:
            chk('[old db] an old complaint loads with no geo / video rows (all new relations are optional)', c.geo is None and c.video_issue is None and c.videos == [] and c.ai_predictions == [])
            cl = app2.test_client(); cl.get('/login')
            u = c.user
            from extensions import db
            from services import complaint_service as S2
            adm = app2.test_client(); adm.get('/admin/login')
            r = adm.post('/admin/login', data=dict(email=app2.config['ADMIN_EMAIL'], password=app2.config['ADMIN_PASSWORD'], csrf_token=tok(adm)))
            if r.status_code == 302:
                adm.get('/', follow_redirects=True)
                chk('[old db] admin opens the OLD complaint page, list, map, AI review and CSV', all(adm.get(u_).status_code == 200 for u_ in ('/admin/complaint/' + c.tracking_id, '/admin/complaints', '/admin/map', '/admin/ai-review', '/admin/complaints/export.csv')))
else:
    print('SKIP shipped database not found')

print(f'\n{sum(RES)}/{len(RES)} checks passed'); sys.exit(0 if all(RES) else 1)
