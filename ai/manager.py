"""Runs every available YOLO model on the same photo and combines the answers (ai.decision).
 * models are loaded once per process and cached (ai.detectors.base)
 * a missing or failing model is reported in `models` and skipped, the others still run
 * sequential by default (AI_PARALLEL runs them in threads)
The result keeps the old keys (status, label, category, confidence, boxes, annotated, model_name) and adds:
predictions, issues, needs_confirmation, conflict, multiple_issues, reasons, models."""
import json, os, threading, time, uuid
from concurrent.futures import ThreadPoolExecutor
from ai.model_labels import label as _mlabel
from ai import annotate as AN, category_mapper as CM, decision as D
from ai.detectors import DETECTOR_CLASSES
from ai.detectors.extra import build_extras, extras_signature

HERE = os.path.dirname(os.path.abspath(__file__))
_LOCK, _CACHE = threading.Lock(), {}

def models_dir(cfg):
    return cfg.get('AI_MODELS_DIR') or os.path.join(HERE, 'models')

def get_detectors(cfg):
    key = (models_dir(cfg), json.dumps(cfg.get('AI_MODEL_SHA256') or {}, sort_keys=True), extras_signature(cfg, models_dir(cfg)))
    with _LOCK:
        if key not in _CACHE:
            _CACHE[key] = [cls(models_dir(cfg), cfg) for cls in DETECTOR_CLASSES] + build_extras(cfg, models_dir(cfg))
        return _CACHE[key]

def availability(cfg):
    """One dict per model (tries to load it). Used by the admin panel and `python -m ai.inspect_models`."""
    return [dict(d.info(), loaded=d.load() or d.model is not None, error=d.error) for d in get_detectors(cfg)]

def _base_conf(cfg, name):
    lows = [cfg.get('AI_MODEL_THRESHOLDS', {}).get(name, cfg.get('AI_CONFIDENCE', 0.25))] + list((cfg.get('AI_CATEGORY_THRESHOLDS') or {}).values())
    return min(lows)

def _run_one(det, image_path, cfg):
    t = time.time()
    info = {'name': det.name, 'display_name': det.display_name, 'status': 'ok', 'error': None, 'count': 0, 'task': None, 'file': None}
    preds = []
    try:
        if not det.load():
            info.update(status='unavailable', error=det.error)
        else:
            preds = det.predict(image_path, conf=_base_conf(cfg, det.name))
            info.update(count=len(preds), task=det.task, file=os.path.basename(det.path) if det.path else None)
    except Exception as e:                                         # one model failing must never stop the others
        info.update(status='error', error=f'{type(e).__name__}: {str(e)[:160]}')
        preds = []
    info['ms'] = int((time.time() - t) * 1000)
    return info, preds

def analyze(image_path, cfg, out_dir=None):
    t0 = time.time()
    dets = get_detectors(cfg)
    if cfg.get('AI_PARALLEL'):
        with ThreadPoolExecutor(max_workers=len(dets)) as ex:
            runs = list(ex.map(lambda d: _run_one(d, image_path, cfg), dets))
    else:
        runs = [_run_one(d, image_path, cfg) for d in dets]
    models = [r[0] for r in runs]
    overrides = CM.load_overrides(cfg.get('AI_CLASSMAP_FILE') or os.path.join(HERE, 'class_map.json'))
    preds, fam = [], cfg.get('AI_FAMILY_BY_FILE') or {}
    for info, plist in runs:
        for p in plist:
            d = p.to_dict()
            d['category'], d['mapped_by'] = CM.map_label(p.model, p.label, p.class_id, overrides)
            d['model_display'] = _mlabel(p.model)
            d['family'] = fam.get(info.get('file') or '', p.model)                 # models of one family are one vote (ai.decision)
            preds.append(d)
    res = D.decide(preds, cfg, D.load_reliability(cfg.get('AI_RELIABILITY_FILE') or os.path.join(HERE, 'reliability.json')))

    ok = [m for m in models if m['status'] == 'ok']
    if not ok:
        res['status'] = 'no_model' if all(m['status'] == 'unavailable' for m in models) else 'error'
    sel = [p for p in res['predictions'] if p['selected']]
    res.update(
        category=res['suggested_category'] if res['status'] == 'ok' else None,
        model_name='+'.join(sorted({p['model'] for p in sel})) or None,
        boxes=[{'label': p['label'], 'confidence': round(p['confidence'], 3), 'x': round(p['bbox'][0], 4), 'y': round(p['bbox'][1], 4),
                'w': round(p['bbox'][2], 4), 'h': round(p['bbox'][3], 4), 'model': p['model'], 'category': p['category']}
               for p in sorted((p for p in res['predictions'] if p['used'] and p['bbox']), key=lambda q: -q['score'])[:10]],
        models=models, models_available=len(ok), models_total=len(models), annotated=None, elapsed_ms=int((time.time() - t0) * 1000))
    res['predictions'] = res['predictions'][:40]
    if out_dir and any(p['used'] and p['bbox'] for p in res['predictions']):
        name = f'ai_{uuid.uuid4().hex[:12]}.jpg'
        if AN.draw(image_path, res['predictions'], os.path.join(out_dir, name)):
            res['annotated'] = name
    return res
