"""Adding Model_5.pt (a 5th checkpoint) by only copying the file, and the configurable footer. Fake YOLO, real Flask app.  Run: python tests/test_extra_model.py"""
import io, os, sys, tempfile, types
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from PIL import Image
class T(list):
    def tolist(self): return list(self)
class FBox:
    def __init__(s, xyxy, cls, conf): s.xyxy, s.cls, s.conf = [T(xyxy)], cls, conf
class FRes:
    def __init__(s, boxes): s.boxes, s.probs, s.orig_shape, s.names = boxes, None, (200, 300), {}
NAMES = {'Model_1.pt': {0: 'Pothole'}, 'Model_2.pt': {0: 'open_manhole'}, 'Model_3.pt': {0: 'broken_street_light'}, 'Model_4.pt': {0: 'pothole'},
         'Model_5.pt': {0: 'pothole', 1: 'mystery_thing'}, 'other_extra.pt': {0: 'garbage'}, 'broken_extra.pt': {0: 'pothole'}}
class FakeYOLO:
    def __init__(s, path):
        s.fn = os.path.basename(path)
        if s.fn == 'broken_extra.pt': raise RuntimeError('corrupt checkpoint')
        s.task, s.names = 'detect', NAMES[s.fn]
    def __call__(s, img, **kw):
        if s.fn == 'Model_5.pt': return [FRes([FBox((30, 40, 130, 140), 0, .9), FBox((200, 20, 260, 80), 1, .8)])]
        if s.fn == 'Model_4.pt': return [FRes([FBox((32, 42, 132, 142), 0, .8)])]
        if s.fn == 'other_extra.pt': return [FRes([FBox((150, 100, 250, 190), 0, .7)])]
        return [FRes([])]
fake = types.ModuleType('ultralytics'); fake.YOLO = FakeYOLO; sys.modules['ultralytics'] = fake
import ai.detectors.base as _B; _B.RETRY_AFTER = 0
from app import create_app
from ai import manager as M
RES = []
def chk(n, c): RES.append(bool(c)); print(('PASS ' if c else 'FAIL ') + n)
tmp = tempfile.mkdtemp(); mdir = os.path.join(tmp, 'models'); os.makedirs(mdir)
def put(fn): open(os.path.join(mdir, fn), 'wb').write(b'PK\x03\x04fake')
def png():
    p = os.path.join(tmp, 'p.png'); Image.new('RGB', (300, 200), (90, 90, 90)).save(p); return p
for fn in ('Model_1.pt', 'Model_2.pt', 'Model_3.pt', 'Model_4.pt'): put(fn)
def cfg(**k): return dict(AI_MODELS_DIR=mdir, AI_RESULTS_DIR=os.path.join(tmp, 'r'), AI_RELIABILITY_FILE=os.path.join(tmp, 'none.json'), AI_CLASSMAP_FILE=os.path.join(tmp, 'none.json'), **k)

r = M.analyze(png(), cfg(), None)
chk('[extra] file NOT copied yet: Model_5 is a built-in slot: 5 models listed, 4 available, Model_5 reported as unavailable', r['models_total'] == 5 and r['models_available'] == 4 and 'best_civic_model' in [m['name'] for m in r['models']])
put('Model_5.pt')
r = M.analyze(png(), cfg(), None)
names = [m['name'] for m in r['models']]
chk('[extra] copying Model_5.pt is enough: Model_5 becomes available without any config edit', r['models_total'] == 5 and names[-1] == 'best_civic_model' and r['models_available'] == 5)
ps = [p for p in r['predictions'] if p['model'] == 'best_civic_model']
chk('[extra] its predictions carry its own name and are mapped to app categories (pothole -> Pothole)', len(ps) == 2 and {p['category'] for p in ps} == {'Pothole', None})
chk('[extra] an unknown class name stays UNCLASSIFIED (never guessed) and cannot become a complaint category by itself', [p for p in ps if p['label'] == 'mystery_thing'][0]['category'] is None)
chk('[extra] it takes part in the decision: Pothole issue now lists best_civic_model with own_model', r['category'] == 'Pothole' and {'best_civic_model', 'own_model'} <= set(r['issues'][0]['models']))
chk('[extra] with no calibration yet its reliability is the neutral default and is flagged uncalibrated', all(p['reliability'] == 0.6 and not p['calibrated'] for p in ps) and not r['reliability_calibrated'])
fam = M.analyze(png(), cfg(AI_FAMILY_BY_FILE={'Model_5.pt': 'x', 'Model_4.pt': 'x'}), None)
chk('[extra] family map by FILE name works for it: related checkpoints count as one vote', fam['issues'][0]['status'] == 'single')
ov = os.path.join(tmp, 'cm.json'); open(ov, 'w').write('{"best_civic_model": {"mystery_thing": "Water Leakage"}}')
r2 = M.analyze(png(), dict(cfg(), AI_CLASSMAP_FILE=ov), None)
chk('[extra] class_map.json override (key = model name) maps its own class names', 'Water Leakage' in {p['category'] for p in r2['predictions'] if p['model'] == 'best_civic_model'})
# more extras, bad entries, broken file
put('other_extra.pt'); put('broken_extra.pt')
c2 = cfg(AI_EXTRA_MODELS={'best_civic_model': 'Model_5.pt', 'second_extra': {'file': 'other_extra.pt', 'display': 'Second'}, 'broken_one': {'file': 'broken_extra.pt'},
                         'Bad Name!': {'file': 'Model_5.pt'}, 'own_model': {'file': 'Model_5.pt'}, 'evil': {'file': '../../etc/passwd.pt'}, 'noext': {'file': 'readme.txt'}})
r3 = M.analyze(png(), c2, None); st = {m['name']: m['status'] for m in r3['models']}
chk('[extra] several extras work; invalid names, built-in names, path tricks and non-.pt files are ignored: ' + str(list(st)), set(st) == {'civicresolve', 'civic_guardian', 'streetlight', 'own_model', 'best_civic_model', 'second_extra', 'broken_one'})
chk('[extra] a corrupt extra only disables itself; every other model still answers', st['broken_one'] != 'ok' and st['best_civic_model'] == 'ok' and st['second_extra'] == 'ok' and r3['category'] == 'Pothole')
chk('[extra] removing the entry from config takes it out of the pipeline again', 'best_civic_model' not in [m['name'] for m in M.analyze(png(), cfg(AI_EXTRA_MODELS={}), None)['models']])
chk('[extra] the admin model table (availability) lists it too', 'best_civic_model' in [m['name'] for m in M.availability(cfg())])

# footer
app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + os.path.join(tmp, 't.db').replace('\\', '/'), 'DB_PATH': os.path.join(tmp, 't.db'), 'UPLOAD_FOLDER': os.path.join(tmp, 'up'),
                  'COMPANY_NAME': 'Acme <Civic> & Co', 'COPYRIGHT_YEAR': '2026', 'AI_MODELS_DIR': mdir})
c = app.test_client(); land = c.get('/').get_data(as_text=True)
chk('[footer] landing page footer shows your company name and year, HTML-escaped', '© 2026 Acme &lt;Civic&gt; &amp; Co. All rights reserved.' in land)
c.get('/login'); 
with c.session_transaction() as s: tk = s['csrf']
c.post('/register', data=dict(name='A', email='a@x.com', password='Passw0rd!', confirm='Passw0rd!', phone='', csrf_token=tk))
chk('[footer] the footer inside the app (dashboard) shows it too', '© 2026 Acme &lt;Civic&gt; &amp; Co. All rights reserved.' in c.get('/dashboard').get_data(as_text=True))
app2 = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + os.path.join(tmp, 't2.db').replace('\\', '/'), 'DB_PATH': os.path.join(tmp, 't2.db'), 'UPLOAD_FOLDER': os.path.join(tmp, 'up2'), 'COMPANY_NAME': 'Acme Ltd', 'COPYRIGHT_YEAR': ''})
from datetime import datetime
chk('[footer] empty year = the current year automatically', f'© {datetime.now().year} Acme Ltd.' in app2.test_client().get('/').get_data(as_text=True) or f'© {datetime.now().year + 0} Acme Ltd.' in app2.test_client().get('/').get_data(as_text=True))
print(f'\n{sum(RES)}/{len(RES)} checks passed'); sys.exit(0 if all(RES) else 1)
