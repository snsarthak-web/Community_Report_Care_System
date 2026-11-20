"""real checkpoints + real photos (no fakes). Skips itself (exit 0) when ultralytics, the five .pt files or the sample photos are missing.
  1. all five checkpoints load from ai/models and every class maps to a reporting category
  2. each sample photo is recognised as a pothole by the combined decision
  3. a video built from the photos, with a walking GPS track, yields several separate Pothole issues at separate places
  4. ticking them creates one complaint each; all keep the same original video
Run:  python tests/test_real_models.py"""
import glob, json, os, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, '..'))
try:
    import cv2, ultralytics  # noqa: F401
except Exception as e:
    print('SKIP ultralytics / opencv not installed:', e); sys.exit(0)
from config import Config
MD, PHOTOS = Config.AI_MODELS_DIR, sorted(glob.glob(os.path.join(HERE, 'data', 'real_potholes', '*.jpg')))
from ai import manager as M, category_mapper as CM, video as V
cfg = {k: getattr(Config, k) for k in dir(Config) if k.startswith(('AI_', 'VIDEO_'))}
dets = M.get_detectors(cfg)
if not all(d.load() for d in dets) or len(PHOTOS) < 3:
    print('SKIP the five checkpoints and/or the sample photos are not present:', [(d.name, d.error) for d in dets if d.error]); sys.exit(0)
RES = []
def chk(name, cond): RES.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name)

want = {'civicresolve': 10, 'civic_guardian': 7, 'streetlight': 4, 'own_model': 2, 'best_civic_model': 1}
chk('[models] all five load from ai/models with the expected class counts: ' + str({d.name: len(d.names) for d in dets}), {d.name: len(d.names) for d in dets} == want)
chk('[models] every class of every model maps to an app category (nothing UNMAPPED)', all(CM.map_label(d.name, n, int(i), None)[0] for d in dets for i, n in d.names.items()))
chk('[models] the checkpoints listed together in AI_FAMILY_BY_FILE are ONE family; the others are independent', len({cfg['AI_FAMILY_BY_FILE'].get(os.path.basename(d.path), d.name) for d in dets}) == 4)
chk('[models] files can be pinned: SHA-256 of a loaded file matches itself (pin mechanism works)', __import__('ai.safety', fromlist=['x']).resolve_checkpoint(MD, os.path.basename(dets[0].path), 500,
    __import__('ai.safety', fromlist=['x']).sha256_of(dets[0].path))[1] is None)
chk('[models] a WRONG pin refuses to load the file', __import__('ai.safety', fromlist=['x']).resolve_checkpoint(MD, os.path.basename(dets[0].path), 500, '0' * 64)[0] is None)

for p in PHOTOS:
    r = M.analyze(p, cfg, None)
    chk(f'[photo] {os.path.basename(p)}: suggested {r["category"]} ({r["confidence"]}), {len([x for x in r["predictions"] if x["used"]])} model predictions, models ok {r["models_available"]}/5',
        r['status'] == 'ok' and r['category'] == 'Pothole' and r['models_available'] == 5)

# a fifth checkpoint, added by copying the file only (a copy of an existing checkpoint is used as Model_5.pt in this test)
import shutil
x5 = tempfile.mkdtemp()
for d in dets: shutil.copyfile(d.path, os.path.join(x5, os.path.basename(d.path)))
shutil.copyfile(dets[0].path, os.path.join(x5, 'Model_5.pt'))
r5 = M.analyze(PHOTOS[0], dict(cfg, AI_MODELS_DIR=x5), None)
chk(f'[extra] real checkpoint dropped in as Model_5.pt: {r5["models_available"]}/{r5["models_total"]} models ran, it predicted {len([p for p in r5["predictions"] if p["model"] == "best_civic_model"])} objects',
    r5['models_total'] == 5 and r5['models_available'] == 5 and any(p['model'] == 'best_civic_model' for p in r5['predictions']))

# one video, several potholes, a walking GPS track
tmp = tempfile.mkdtemp(); mp4 = os.path.join(tmp, 'road.mp4')
w = cv2.VideoWriter(mp4, cv2.VideoWriter_fourcc(*'mp4v'), 10, (640, 480))
for p in PHOTOS:
    im = cv2.resize(cv2.imread(p), (640, 480))
    for _ in range(30): w.write(im)
w.release()
gps = [{'t': round(t * 0.5, 1), 'lat': 20.2700 + t * 0.5 * 0.00015, 'lng': 85.84, 'acc': 8, 'k': 'rec'} for t in range(25)]
from app import create_app
app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + os.path.join(tmp, 't.db').replace('\\', '/'), 'DB_PATH': os.path.join(tmp, 't.db'),
                  'UPLOAD_FOLDER': os.path.join(tmp, 'up'), 'AI_RESULTS_DIR': os.path.join(tmp, 'res'), 'ADMIN_EMAIL': 'b@c.d', 'ADMIN_PASSWORD': 'BossPassw0rd!'})
c = app.test_client(); c.get('/login')
def tok():
    with c.session_transaction() as s: return s['csrf']
c.post('/register', data=dict(name='A', email='a@x.com', password='Passw0rd!', confirm='Passw0rd!', phone='', csrf_token=tok())); c.get('/', follow_redirects=True)
r = c.post('/upload/video', data={'video': (open(mp4, 'rb'), 'road.mp4'), 'gps': json.dumps(gps)}, headers={'X-CSRFToken': tok()}, content_type='multipart/form-data')
name = r.json['video_name']
for _ in range(300):
    s = c.get(f'/ai/video/{name}/status').json
    if s['status'] in ('done', 'error'): break
    time.sleep(1)
iss = (s.get('result') or {}).get('issues', [])
chk(f'[video] analysed by the real models: {len(iss)} issues {[(i["category"], i["timestamps"]) for i in iss]}', s['status'] == 'done' and len(iss) >= len(PHOTOS) - 1 and all(i['category'] == 'Pothole' for i in iss))
ann = (s.get('result') or {}).get('annotated_video')
annp = os.path.join(app.config['UPLOAD_FOLDER'], ann) if ann else None
nf = int(cv2.VideoCapture(annp).get(cv2.CAP_PROP_FRAME_COUNT)) if ann else 0
chk(f'[output video] the real-model analysis also produced the full video with boxes and labels: {ann}, {nf} frames', ann and nf >= 100)
chk('[video] every issue has its own frame and its own GPS-linked location (within 1 s of the detection)', all(i.get('photo_url') and i.get('location') and i['location']['dt'] <= 1.0 for i in iss))
spots = [(i['location']['lat'], i['location']['lng']) for i in iss]
chk('[video] the locations are DIFFERENT places (not one pin for the whole video)', len({(round(a, 5), round(b, 5)) for a, b in spots}) == len(spots))
body = {'video_name': name, 'description': 'Potholes along the road', 'issues': [dict(id=i['id'], category='Pothole', lat=i['location']['lat'], lng=i['location']['lng'], location_text='', origin='video_gps',
        acc=i['location']['acc'], cap_lat=i['location']['lat'], cap_lng=i['location']['lng'], dt=i['location']['dt']) for i in iss]}
r = c.post('/report/video/submit', json=body, headers={'X-CSRFToken': tok()})
chk('[submit] one complaint per ticked issue: ' + str(r.json.get('tracking_ids')), r.status_code == 200 and len(r.json['tracking_ids']) == len(iss))
from models import Complaint
with app.app_context():
    cs = Complaint.query.all()
    chk('[submit] separate coordinates; ONE shared original video file; one group', len({(x.latitude, x.longitude) for x in cs}) == len(cs) and len({x.videos[0].filename for x in cs}) == 1
        and len({x.video_issue.group_id for x in cs}) == 1 and os.path.exists(os.path.join(app.config['UPLOAD_FOLDER'], name)))
    chk('[submit] every complaint kept the real models\' predictions of ITS frame', all(len(x.ai_predictions) >= 1 and x.detection is not None for x in cs))
print(f'\n{sum(RES)}/{len(RES)} checks passed'); sys.exit(0 if all(RES) else 1)
