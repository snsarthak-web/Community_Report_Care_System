"""AI pipeline tests. Pure Python: no Flask, no database, no real weights, no gpu.
A fake `ultralytics.YOLO` returns scripted detections, so the real detector / manager / decision code is exercised.
Run:   python tests/test_ai_pipeline.py
(With your real .pt files use `python -m ai.inspect_models` and `python -m ai.benchmark` instead.)"""
import json, os, shutil, sys, tempfile, types
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from PIL import Image

# fake ultralytics
SCRIPT, LOADS = {}, []
class T(list):
    def tolist(self): return list(self)
class FBox:
    def __init__(s, xyxy, cls, conf): s.xyxy, s.cls, s.conf = [T(xyxy)], cls, conf
class FProbs:
    def __init__(s, top1, conf): s.top1, s.top1conf = top1, conf
class FRes:
    def __init__(s, boxes=(), probs=None): s.boxes, s.probs, s.orig_shape, s.names = list(boxes), probs, (200, 300), {}
class FakeYOLO:
    def __init__(s, path):
        s.fn = os.path.basename(path); LOADS.append(s.fn); spec = SCRIPT[s.fn]
        if spec.get('corrupt'): raise RuntimeError('invalid pickle')
        s.task, s.names = spec.get('task', 'detect'), spec['names']
    def __call__(s, img, **kw):
        spec = SCRIPT[s.fn]
        if spec.get('raise'): raise RuntimeError('CUDA out of memory')
        if s.task == 'classify': return [FRes(probs=FProbs(*spec['top1']))]
        return [FRes([FBox(*b) for b in spec.get('boxes', [])])]
fake = types.ModuleType('ultralytics'); fake.YOLO = FakeYOLO; sys.modules['ultralytics'] = fake

from ai import manager as M, decision as D, category_mapper as CM, safety, store, calibrate, annotate
from ai.detectors.base import BaseDetector
RES = []
def chk(name, cond): RES.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name)

NAMES = {'Model_1.pt': {0: 'Pothole', 1: 'Garbage', 2: 'Water_logging'}, 'Model_2.pt': {0: 'open_manhole', 1: 'litter', 2: 'damaged_wires', 3: 'cracks'},
         'Model_3.pt': {0: 'broken_street_light', 1: 'working_light'}, 'Model_4.pt': {0: 'pothole', 1: 'garbage'}, 'Model_5.pt': {0: 'pothole', 1: 'garbage'}}
LEFT, RIGHT, LEFT2 = (30, 40, 130, 140), (180, 40, 280, 140), (35, 45, 135, 145)       # pixel boxes on a 300x200 photo

def world(files=tuple(NAMES), **boxes):
    """fresh models folder + photo; boxes = {'Model_4.pt': [(xyxy, cls, conf)], ...}"""
    d = tempfile.mkdtemp(); SCRIPT.clear(); LOADS.clear(); M._CACHE.clear()
    for fn, names in NAMES.items():
        SCRIPT[fn] = {'names': names, 'boxes': boxes.get(fn, [])}
        if fn in files: open(os.path.join(d, fn), 'wb').write(b'PK\x03\x04fake-checkpoint')
    img = os.path.join(d, 'photo.jpg'); Image.new('RGB', (300, 200), (90, 90, 90)).save(img)
    return d, img, {'AI_MODELS_DIR': d, 'AI_RELIABILITY_FILE': os.path.join(d, 'none.json'), 'AI_CLASSMAP_FILE': os.path.join(d, 'none.json')}

# 1. each checkpoint individually
d, img, cfg = world(**{'Model_4.pt': [(LEFT, 0, .9)], 'Model_1.pt': [(LEFT, 0, .8)], 'Model_2.pt': [(RIGHT, 0, .7)], 'Model_3.pt': [(LEFT, 0, .85)], 'Model_5.pt': [(LEFT, 0, .8)]})
for det in M.get_detectors(cfg):
    p = det.predict(img, 0.25)
    chk(f'[individual] {det.display_name}: loads, task={det.task}, classes={len(det.names)}, 1 prediction ({p[0].label}, {p[0].confidence})', det.load() and len(p) == 1 and det.task == 'detect')
chk('[individual] boxes are normalised 0-1', all(0 <= v <= 1 for det in M.get_detectors(cfg) for pr in det.predict(img, .25) for v in pr.bbox))

# 2. all five together
r = M.analyze(img, cfg, d)
chk('[all five] 5 of 5 models available', r['models_available'] == 5 and r['models_total'] == 5)
chk('[all five] every model\'s prediction preserved (5 predictions)', len(r['predictions']) == 5 and {p['model'] for p in r['predictions']} == {'civicresolve', 'civic_guardian', 'streetlight', 'own_model', 'best_civic_model'})
chk('[all five] old keys still present (status,label,category,confidence,boxes,annotated,model_name)', all(k in r for k in ('status', 'label', 'category', 'confidence', 'boxes', 'annotated', 'model_name')))
chk('[all five] annotated image written', r['annotated'] and os.path.exists(os.path.join(d, r['annotated'])))

# 3-6. single-issue photos
d, img, cfg = world(**{'Model_4.pt': [(LEFT, 0, .9)], 'Model_1.pt': [(LEFT2, 0, .8)]})
r = M.analyze(img, cfg)
chk('[pothole] two models agree on one object -> Pothole, no confirmation needed', r['category'] == 'Pothole' and r['issues'][0]['status'] == 'agreed' and not r['needs_confirmation'] and len(r['issues']) == 1)
chk('[pothole] agreement raises the score above either model alone', r['reliability'] > max(.9, .8) * .6)
d, img, cfg = world(**{'Model_4.pt': [(LEFT, 1, .88)], 'Model_2.pt': [(LEFT2, 1, .6)]})
r = M.analyze(img, cfg); chk('[garbage] own "garbage" + guardian "litter" -> Garbage', r['category'] == 'Garbage' and r['issues'][0]['models'] == ['civic_guardian', 'own_model'])
d, img, cfg = world(**{'Model_3.pt': [((100, 10, 160, 190), 0, .9)]})
r = M.analyze(img, cfg); chk('[streetlight] broken_street_light -> Streetlight (single model)', r['category'] == 'Streetlight' and r['issues'][0]['status'] == 'single' and r['model_name'] == 'streetlight')
d, img, cfg = world(**{'Model_3.pt': [((100, 10, 160, 190), 1, .95)]})
r = M.analyze(img, cfg); chk('[streetlight] a WORKING light is NOT reported as a broken streetlight (unclassified, flagged)', r['category'] == 'Other' and r['needs_confirmation'] and r['issues'][0]['status'] == 'unclassified')
d, img, cfg = world(**{'Model_2.pt': [(LEFT, 0, .75)]})
r = M.analyze(img, cfg); chk('[open manhole] open_manhole -> Open Manhole', r['category'] == 'Open Manhole')

# 7. conflicting predictions
d, img, cfg = world(**{'Model_4.pt': [(LEFT, 0, .80)], 'Model_1.pt': [(LEFT2, 1, .78)]})
r = M.analyze(img, cfg)
chk('[conflict] same object, different categories, similar scores -> flagged for confirmation', r['conflict'] and r['needs_confirmation'] and r['issues'][0]['status'] == 'conflict')
chk('[conflict] both candidates are kept (alternatives) and both predictions preserved', r['issues'][0]['alternatives'] and len(r['predictions']) == 2 and r['reasons'])
json.dump({'own_model': {'Pothole': {'precision': 0.50}}, 'civicresolve': {'Garbage': {'precision': 0.95}}}, open(cfg['AI_RELIABILITY_FILE'], 'w'))
r = M.analyze(img, cfg)
chk('[reliability] NOT highest raw confidence: pothole has higher raw conf (0.80 vs 0.78) but Garbage wins on validation reliability', r['category'] == 'Garbage' and max(p['confidence'] for p in r['predictions']) == .80 and r['reliability_calibrated'])
chk('[reliability] a clear winner is not flagged as a conflict', not r['conflict'] and r['issues'][0]['status'] == 'resolved')
d, img, cfg = world(**{'Model_4.pt': [(LEFT, 0, .85)], 'Model_2.pt': [(LEFT2, 3, .8)]})
r = M.analyze(img, cfg); chk('[compatible] pothole + cracks on one object -> Pothole (a pothole IS road damage), not a conflict', r['category'] == 'Pothole' and r['issues'][0]['status'] == 'compatible' and not r['conflict'])

# 8. multiple issues in one image
d, img, cfg = world(**{'Model_4.pt': [(LEFT, 0, .9), (RIGHT, 1, .85)], 'Model_2.pt': [((100, 150, 190, 199), 0, .8)]})
r = M.analyze(img, cfg)
cats = sorted(i['category'] for i in r['issues'])
chk('[multiple] 3 separate issues kept, not discarded: ' + str(cats), len(r['issues']) == 3 and cats == ['Garbage', 'Open Manhole', 'Pothole'])
chk('[multiple] different objects are NOT treated as conflicts', not r['conflict'] and all(i['status'] != 'conflict' for i in r['issues']))
chk('[multiple] flagged so the citizen is told, all 3 predictions stored', r['multiple_issues'] and r['needs_confirmation'] and len(r['predictions']) == 3 and any('Different kinds' in x for x in r['reasons']))

# 9. missing / broken model
d, img, cfg = world(files=('Model_4.pt', 'Model_1.pt', 'Model_3.pt', 'Model_5.pt'), **{'Model_4.pt': [(LEFT, 0, .9)], 'Model_1.pt': [(LEFT2, 0, .8)]})
r = M.analyze(img, cfg); bad = [m for m in r['models'] if m['status'] != 'ok']
chk('[missing file] Model_2.pt absent -> other 4 still run, result still Pothole', r['models_available'] == 4 and r['category'] == 'Pothole' and r['status'] == 'ok')
chk('[missing file] the failure is reported with a reason: ' + str(bad[0]['error']), len(bad) == 1 and bad[0]['name'] == 'civic_guardian' and 'not found' in bad[0]['error'])
d, img, cfg = world(**{'Model_4.pt': [(LEFT, 0, .9)], 'Model_1.pt': [(LEFT2, 0, .8)]}); SCRIPT['Model_3.pt']['raise'] = True; SCRIPT['Model_2.pt']['corrupt'] = True
r = M.analyze(img, cfg); st = {m['name']: m['status'] for m in r['models']}
chk('[broken models] one crashes at inference, one is a corrupt checkpoint -> others unaffected: ' + str(st), st['streetlight'] == 'error' and st['civic_guardian'] == 'unavailable' and r['category'] == 'Pothole')
d, img, cfg = world(files=()); r = M.analyze(img, cfg)
chk('[no files] no checkpoints at all -> status no_model (old graceful behaviour), no crash', r['status'] == 'no_model' and r['category'] is None and r['predictions'] == [])
d, img, cfg = world(); sys.modules['ultralytics'] = None; M._CACHE.clear(); r = M.analyze(img, cfg); sys.modules['ultralytics'] = fake
chk('[no ultralytics] library missing -> no_model with a clear message', r['status'] == 'no_model' and 'not installed' in r['models'][0]['error'])
d, img, cfg = world(**{'Model_4.pt': []}); r = M.analyze(img, cfg)
chk('[nothing detected] models run, find nothing -> status none, empty prediction list', r['status'] == 'none' and r['predictions'] == [] and r['models_available'] == 5)
d, img, cfg = world(files=('best.pt',)); SCRIPT['best.pt'] = {'names': {0: 'pothole'}, 'boxes': [(LEFT, 0, .9)]}; open(os.path.join(d, 'best.pt'), 'wb').write(b'PK\x03\x04x'); r = M.analyze(img, cfg)
chk('[legacy] an old ai/models/best.pt is still used as the "own model"', r['category'] == 'Pothole' and r['models_available'] == 1)
LEGACY = {'civicresolve': 'pothole_garbage_v1.pt', 'civic_guardian': 'civic_guardian.pt', 'streetlight': 'multiclass_streetlight_tree.pt', 'own_model': 'pothole_garbage_v2.pt', 'best_civic_model': 'best_civic_model.pt'}
d, img, cfg = world(files=())
for fn in LEGACY.values():
    SCRIPT[fn] = {'names': {0: 'pothole'}, 'boxes': [(LEFT, 0, .9)]}; open(os.path.join(d, fn), 'wb').write(b'PK\x03\x04fake-checkpoint')
dets = {x.name: x for x in M.get_detectors(cfg)}; [x.load() for x in dets.values()]
chk('[rename] checkpoints still carrying their ORIGINAL names load into the same five slots', all(dets[n].info()['file_loaded'] == fn for n, fn in LEGACY.items()))
for n, nm in (('civicresolve', 'Model_1.pt'), ('civic_guardian', 'Model_2.pt'), ('streetlight', 'Model_3.pt'), ('own_model', 'Model_4.pt'), ('best_civic_model', 'Model_5.pt')):
    SCRIPT[nm] = {'names': {0: 'pothole'}, 'boxes': [(LEFT, 0, .9)]}; open(os.path.join(d, nm), 'wb').write(b'PK\x03\x04fake-checkpoint')
M._CACHE.clear(); dets = {x.name: x for x in M.get_detectors(cfg)}; [x.load() for x in dets.values()]
chk('[rename] Model_1.pt .. Model_5.pt are the canonical names and win over the old names', all(dets[n].info()['file_loaded'] == nm for n, nm in (('civicresolve', 'Model_1.pt'), ('civic_guardian', 'Model_2.pt'), ('streetlight', 'Model_3.pt'), ('own_model', 'Model_4.pt'), ('best_civic_model', 'Model_5.pt'))))

# 10. caching / parallel
d, img, cfg = world(**{'Model_4.pt': [(LEFT, 0, .9)], 'Model_1.pt': [(LEFT2, 0, .8)]})
for _ in range(5): M.analyze(img, cfg)
chk('[cache] 5 analyses -> each checkpoint loaded exactly once: ' + str(sorted(LOADS)), sorted(LOADS) == sorted(NAMES))
seq = M.analyze(img, cfg); par = M.analyze(img, dict(cfg, AI_PARALLEL=True))
chk('[parallel] threaded run gives the same decision as sequential', (seq['category'], seq['reliability'], len(seq['predictions'])) == (par['category'], par['reliability'], len(par['predictions'])))

# other model tasks
d, img, cfg = world(**{'Model_4.pt': [(LEFT, 0, .9)]}); SCRIPT['Model_2.pt'].update(task='classify', top1=(0, .8), names={0: 'pothole'})
r = M.analyze(img, cfg); gp = [p for p in r['predictions'] if p['model'] == 'civic_guardian']
chk('[classify] an image-level classifier saying the same category REINFORCES the box (1 issue, 2 models)', len(gp) == 1 and gp[0]['image_level'] and gp[0]['bbox'] is None and len(r['issues']) == 1 and r['issues'][0]['models'] == ['civic_guardian', 'own_model'])
d, img, cfg = world(**{'Model_4.pt': [(LEFT, 0, .9)]}); SCRIPT['Model_2.pt'].update(task='classify', top1=(1, .8))
r = M.analyze(img, cfg)
chk('[classify] a classifier naming a DIFFERENT category is kept as a separate issue, not a conflict', len(r['issues']) == 2 and not r['conflict'] and r['multiple_issues'])
d, img, cfg = world(); SCRIPT['Model_4.pt']['task'] = 'pose'; r = M.analyze(img, cfg)
chk('[unsupported task] a pose model is refused with a clear reason', any(m['name'] == 'own_model' and m['status'] == 'unavailable' and 'unsupported' in m['error'] for m in r['models']))

# category mapper
for lab, exp in (('pothole', 'Pothole'), ('garbage', 'Garbage'), ('litter', 'Garbage'), ('waste', 'Garbage'), ('cracks', 'Road Damage'), ('damaged_concrete', 'Road Damage'), ('damaged_roads', 'Road Damage'),
                 ('open_manhole', 'Open Manhole'), ('broken_street_light', 'Streetlight'), ('streetlight', 'Streetlight'), ('water_leak', 'Water Leakage'), ('fallen_tree', 'Fallen Tree'),
                 ('illegal_parking', 'Illegal Parking'), ('broken_sign', 'Broken Sign'), ('damaged_wires', 'Damaged Electrical Wires'), ('dead_animal', 'Dead Animal')):
    chk(f'[mapper] "{lab}" -> {exp}', CM.map_label('m', lab)[0] == exp)
chk('[mapper] unknown labels stay unclassified (never guessed)', all(CM.map_label('m', l)[0] is None for l in ('person', 'car', 'designated', 'tree', 'sign', 'light')))
ov = tmp = os.path.join(tempfile.mkdtemp(), 'cm.json'); json.dump({'streetlight': {'broken': 'Streetlight', '1': 'Other', 'x': 'NotACategory'}}, open(tmp, 'w'))
o = CM.load_overrides(tmp)
chk('[mapper] per-model override file wins and by class index; invalid categories ignored', CM.map_label('streetlight', 'broken', 0, o) == ('Streetlight', 'override') and CM.map_label('streetlight', 'zzz', 1, o)[0] == 'Other' and CM.map_label('streetlight', 'x', None, o)[0] is None)
chk('[mapper] same label, different model: no assumption across models', CM.map_label('own_model', 'broken', 0, o)[0] is None)
chk('[mapper] 15 categories, all in config', set(CM.CANONICAL) == set(__import__('config').Config.CATEGORIES) and len(CM.CANONICAL) == 15)

# decision maths
chk('[iou] identical = 1, disjoint = 0, half overlap = 1/3', D.iou((0, 0, 1, 1), (0, 0, 1, 1)) == 1 and D.iou((0, 0, 1, 1), (2, 2, 1, 1)) == 0 and abs(D.iou((0, 0, 2, 2), (1, 0, 2, 2)) - 1 / 3) < 1e-9)
chk('[thresholds] category threshold overrides model threshold overrides default', D.threshold_for({'AI_CATEGORY_THRESHOLDS': {'Pothole': .6}, 'AI_MODEL_THRESHOLDS': {'a': .4}}, 'a', 'Pothole') == .6 and D.threshold_for({'AI_MODEL_THRESHOLDS': {'a': .4}}, 'a', 'Garbage') == .4 and D.threshold_for({}, 'a', 'x') == .25)
r = D.decide([{'model': 'a', 'label': 'p', 'class_id': 0, 'confidence': .30, 'bbox': (.1, .1, .3, .3), 'category': 'Pothole', 'task': 'detect', 'image_level': False}], {'AI_CATEGORY_THRESHOLDS': {'Pothole': .5}})
chk('[thresholds] a prediction below its class threshold is kept but not used', r['status'] == 'none' and r['predictions'][0]['used'] is False)
r = D.decide([{'model': 'a', 'label': 'p', 'class_id': 0, 'confidence': .5, 'bbox': (.1, .1, .3, .3), 'category': 'Pothole', 'task': 'detect', 'image_level': False}])
chk('[low score] a weak single-model result (0.5 x 0.6 default = 0.30) is flagged for confirmation', r['needs_confirmation'] and r['issues'][0]['low_score'] and r['issues'][0]['status'] == 'single')

# checkpoint safety
base = tempfile.mkdtemp(); outside = tempfile.mkdtemp(); open(os.path.join(base, 'ok.pt'), 'wb').write(b'abc'); open(os.path.join(outside, 'evil.pt'), 'wb').write(b'x')
os.symlink(os.path.join(outside, 'evil.pt'), os.path.join(base, 'link.pt')); open(os.path.join(base, 'big.pt'), 'wb').write(b'x' * 2_100_000); open(os.path.join(base, 'empty.pt'), 'wb').close(); open(os.path.join(base, 'm.txt'), 'wb').write(b'x')
import hashlib
chk('[safety] normal checkpoint accepted', safety.resolve_checkpoint(base, 'ok.pt')[1] is None)
chk('[safety] path traversal refused', safety.resolve_checkpoint(base, '../x.pt')[0] is None and safety.resolve_checkpoint(base, os.path.join(outside, 'evil.pt'))[0] is None)
chk('[safety] symlink pointing OUTSIDE the models folder refused', 'outside' in (safety.resolve_checkpoint(base, 'link.pt')[1] or ''))
chk('[safety] oversized, empty and non-.pt files refused', safety.resolve_checkpoint(base, 'big.pt', max_mb=2)[0] is None and safety.resolve_checkpoint(base, 'empty.pt')[0] is None and safety.resolve_checkpoint(base, 'm.txt')[0] is None)
good = hashlib.sha256(b'abc').hexdigest()
chk('[safety] pinned SHA-256: match accepted, mismatch refused', safety.resolve_checkpoint(base, 'ok.pt', sha256=good)[1] is None and 'SHA-256' in safety.resolve_checkpoint(base, 'ok.pt', sha256='0' * 64)[1])
d, img, cfg = world(**{'Model_4.pt': [(LEFT, 0, .9)]}); cfg['AI_MODEL_SHA256'] = {'Model_4.pt': '0' * 64}; r = M.analyze(img, cfg)
chk('[safety] a tampered checkpoint is never loaded (YOLO() not called for it)', 'Model_4.pt' not in LOADS and any(m['name'] == 'own_model' and 'SHA-256' in m['error'] for m in r['models']))

# result store
sd = tempfile.mkdtemp()
chk('[store] save + load for the owner', store.save(sd, 'a' * 16 + '.jpg', 7, {'category': 'Pothole'}) and store.load(sd, 'a' * 16 + '.jpg', 7) == {'category': 'Pothole'})
chk('[store] another user cannot read it; unsafe names refused', store.load(sd, 'a' * 16 + '.jpg', 8) is None and not store.save(sd, '../x.jpg', 7, {}) and store.load(sd, '../../etc/passwd', 7) is None)

# calibration
preds = {f'i{k}': [{'model': 'm1', 'category': 'Pothole', 'confidence': .9 - k * .01, 'bbox': (.1, .1, .3, .3)}] for k in range(10)}
gts = {f'i{k}': [{'category': 'Pothole', 'bbox': (.1, .1, .3, .3)}] for k in range(8)}                       # 8 true, 2 false positives
cal = calibrate.evaluate(preds, gts)
chk('[calibrate] precision measured on validation data: 8/10 = 0.8, recall 1.0', cal['m1']['Pothole']['precision'] == .8 and cal['m1']['Pothole']['recall'] == 1.0 and cal['m1']['Pothole']['fp'] == 2)
chk('[calibrate] too few predictions -> no number invented', calibrate.evaluate({'a': preds['i0']}, {'a': gts['i0']}) == {})
# annotate
chk('[annotate] draws without a model and fails safely on a bad path', annotate.draw(img, [], os.path.join(tempfile.mkdtemp(), 'o.jpg')) and not annotate.draw('/nope.jpg', [], '/tmp/x.jpg'))

print(f'\n{sum(RES)}/{len(RES)} checks passed'); sys.exit(0 if all(RES) else 1)
