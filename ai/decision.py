"""Combine the predictions of all models for one photo into a suggestion. Pure Python (no Flask / DB / YOLO imports).

Why not "highest confidence wins"?  Confidence values of different YOLO models are not comparable (different training sets,
different calibration). So each prediction gets
        score = raw_confidence x reliability(model, category)
where reliability comes from ai/reliability.json (per-model, per-category precision measured on a validation set, see
`python -m ai.calibrate`). Until you calibrate, a neutral default (AI_DEFAULT_RELIABILITY) is used and reported as 'uncalibrated'.

Steps
 1. drop predictions below the model's / category's confidence threshold (they stay in the output, flagged used=False)
 2. group boxes that overlap (IoU >= AI_IOU_MATCH) into one physical object; boxes that do not overlap are different issues,
    not conflicts. Image-level (classification) predictions only add support to an object of the same category.
 3. inside one object, models that agree reinforce each other (noisy-or of their scores); models that disagree compete
 4. if the best and second-best category are closer than AI_CONFLICT_MARGIN, or the winner's score is below AI_MIN_SCORE,
    the object is flagged and the citizen/admin must confirm. Nothing here is ground truth: it is only a suggestion."""
import json, os

DEFAULTS = dict(AI_CONFIDENCE=0.25, AI_MODEL_THRESHOLDS={}, AI_CATEGORY_THRESHOLDS={}, AI_IOU_MATCH=0.5, AI_CONFLICT_MARGIN=0.15,
                AI_MIN_SCORE=0.45, AI_DEFAULT_RELIABILITY=0.6, AI_CONTAIN_MATCH=0.7)
MIN_OVERLAP_FOR_CONTAINMENT = 0.15      # boxes that barely touch are never merged, however small one of them is
COMPATIBLE_SPECIFIC = ('Pothole', 'Road Damage')       # a pothole is road damage: not a real disagreement, prefer the specific one

def _cfg(cfg, key):
    return cfg.get(key, DEFAULTS[key]) if cfg is not None else DEFAULTS[key]

def iou(a, b):
    """a, b = (x, y, w, h) in any common unit."""
    ax2, ay2, bx2, by2 = a[0] + a[2], a[1] + a[3], b[0] + b[2], b[1] + b[3]
    iw, ih = min(ax2, bx2) - max(a[0], b[0]), min(ay2, by2) - max(a[1], b[1])
    if iw <= 0 or ih <= 0:
        return 0.0
    inter = iw * ih
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0

def contain(a, b):
    """Intersection divided by the smaller box: 1.0 when one box lies completely inside the other."""
    iw = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
    ih = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
    smaller = min(a[2] * a[3], b[2] * b[3])
    return 0.0 if iw <= 0 or ih <= 0 or smaller <= 0 else iw * ih / smaller

def same_object(a, b, iou_thr=0.5, contain_thr=0.7):
    """-> match strength (0 = different objects). Two models rarely draw the same box: one draws a loose box, another a tight one
    inside it (IoU is low, yet it is one pothole). Measured on 200 held-out pothole photos, IoU alone reported 97 false alarms for
    137 hits; adding this containment rule: 64 false alarms for 140 hits (see docs/MODEL_REPORT.md)."""
    v = iou(a, b)
    if v >= iou_thr:
        return v
    if contain_thr and v >= MIN_OVERLAP_FOR_CONTAINMENT and contain(a, b) >= contain_thr:
        return max(v, iou_thr * 0.99)
    return 0.0

def noisy_or(scores):
    p = 1.0
    for s in scores:
        p *= (1.0 - min(max(s, 0.0), 1.0))
    return 1.0 - p

_REL_CACHE = {}
def load_reliability(path):
    """{model: {category: {'precision': 0.8, ...} | 0.8, '_default': ...}}"""
    try:
        m = os.path.getmtime(path)
        if _REL_CACHE.get(path, (None,))[0] != m:
            with open(path, encoding='utf-8') as fh:
                _REL_CACHE[path] = (m, {k: v for k, v in json.load(fh).items() if not k.startswith('_') and isinstance(v, dict)})
        return _REL_CACHE[path][1]
    except (OSError, ValueError):
        return {}

def reliability_of(rel, model, category, default):
    table = rel.get(model) or {}
    e = table.get(category) if category else None
    if e is None:
        e = table.get('_default')
    if isinstance(e, dict):
        e = e.get('precision')
    if isinstance(e, (int, float)) and not isinstance(e, bool) and 0 <= e <= 1:
        return float(e), True
    return float(default), False

def threshold_for(cfg, model, category):
    ct, mt = _cfg(cfg, 'AI_CATEGORY_THRESHOLDS'), _cfg(cfg, 'AI_MODEL_THRESHOLDS')
    if category in ct:
        return float(ct[category])
    if model in mt:
        return float(mt[model])
    return float(_cfg(cfg, 'AI_CONFIDENCE'))

def _evaluate(cluster, margin, min_score):
    """Models of one family (checkpoints trained from one another) make correlated mistakes: they count as one vote, the
    strongest of them. Only independent families reinforce each other (noisy-or)."""
    by = {}                                                    # category -> {family: best score}
    for m in cluster['members']:
        d = by.setdefault(m['category'], {})
        fam = m.get('family') or m['model']
        d[fam] = max(d.get(fam, 0.0), m['score'])
    agg = {cat: noisy_or(list(fams.values())) for cat, fams in by.items()}
    ranked = sorted(((c, s) for c, s in agg.items() if c is not None), key=lambda kv: -kv[1])
    if not ranked:                                             # only unclassified labels
        return None, max(agg.values()), 'unclassified', [], by
    winner, wscore = ranked[0]
    runner = ranked[1] if len(ranked) > 1 else None
    if runner is None:
        status = 'agreed' if len(by[winner]) >= 2 else 'single'
    elif {winner, runner[0]} == set(COMPATIBLE_SPECIFIC) and agg[COMPATIBLE_SPECIFIC[0]] >= min_score:
        winner, wscore, status = COMPATIBLE_SPECIFIC[0], agg[COMPATIBLE_SPECIFIC[0]], 'compatible'
    elif wscore - runner[1] < margin:
        status = 'conflict'
    else:
        status = 'resolved'
    alts = [{'category': c, 'score': round(s, 3)} for c, s in ranked if c != winner]
    return winner, wscore, status, alts, by

def decide(predictions, cfg=None, reliability=None):
    """predictions: list of dicts (ai.detectors.base.Prediction.to_dict() + 'category').  Returns the analysis dict."""
    cfg, rel = cfg if cfg is not None else {}, reliability or {}
    default, iou_thr, contain_thr = _cfg(cfg, 'AI_DEFAULT_RELIABILITY'), _cfg(cfg, 'AI_IOU_MATCH'), _cfg(cfg, 'AI_CONTAIN_MATCH')
    margin, min_score = _cfg(cfg, 'AI_CONFLICT_MARGIN'), _cfg(cfg, 'AI_MIN_SCORE')
    preds = [dict(p) for p in predictions]
    for p in preds:
        r, cal = reliability_of(rel, p['model'], p.get('category'), default)
        p.update(reliability=round(r, 3), calibrated=cal, score=round(min(1.0, p['confidence'] * r), 4),
                 used=p['confidence'] >= threshold_for(cfg, p['model'], p.get('category')), issue=None, selected=False, conflict=False)

    clusters = []
    for p in sorted((p for p in preds if p['used'] and p.get('bbox')), key=lambda q: -q['score']):
        best, bv = None, 0.0
        for c in clusters:
            same_cat = any(m.get('category') == p.get('category') for m in c['members'])         # loose-vs-tight boxes of the same thing only: a garbage box inside a pothole box stays a different object
            v = same_object(c['box'], p['bbox'], iou_thr, contain_thr if same_cat else None)
            if v > bv:
                best, bv = c, v
        if best:
            best['members'].append(p)
        else:
            clusters.append({'box': p['bbox'], 'members': [p]})
    for p in sorted((p for p in preds if p['used'] and not p.get('bbox')), key=lambda q: -q['score']):
        target = next((c for c in clusters if p.get('category') and any(m.get('category') == p['category'] for m in c['members'])), None)
        if target:
            target['members'].append(p)
        else:
            clusters.append({'box': None, 'members': [p]})

    issues = []
    for c in clusters:
        winner, wscore, status, alts, by = _evaluate(c, margin, min_score)
        low = wscore < min_score
        issues.append({'category': winner, 'score': round(wscore, 3), 'status': status, 'low_score': low,
                       'needs_confirmation': status in ('conflict', 'unclassified') or low,
                       'models': sorted({m['model'] for m in c['members'] if (winner is None or m['category'] == winner)}),
                       'box': None if c['box'] is None else [round(v, 4) for v in c['box']], 'alternatives': alts, '_members': c['members']})
    issues.sort(key=lambda i: -i['score'])
    for n, i in enumerate(issues):
        for m in i['_members']:
            m['issue'], m['conflict'] = n, i['status'] == 'conflict'

    out = dict(status='ok', suggested_category=None, reliability=0.0, reliability_calibrated=False, confidence=0.0, label=None,
               needs_confirmation=False, conflict=False, multiple_issues=False, issues=[], reasons=[], predictions=preds)
    if not issues:
        out['status'] = 'none'
        return out
    top = issues[0]
    sel = [m for m in top['_members'] if top['category'] is None or m.get('category') == top['category']]
    for m in sel:
        m['selected'] = True
    best = max(sel, key=lambda m: m['score'])
    confident = {i['category'] for i in issues if i['category'] and not i['low_score']}
    out.update(suggested_category=top['category'] or 'Other', reliability=top['score'], confidence=round(max(m['confidence'] for m in sel), 3),
               label=best['label'], reliability_calibrated=all(m['calibrated'] for m in sel),
               conflict=any(i['status'] == 'conflict' for i in issues), multiple_issues=len(confident) > 1)
    out['needs_confirmation'] = top['needs_confirmation'] or out['conflict'] or out['multiple_issues']
    for i in issues:
        i.pop('_members')
    out['issues'] = issues
    r = out['reasons']
    for n, i in enumerate(issues):
        if i['status'] == 'conflict':
            r.append('Models disagree on issue %d: %s (%.2f) vs %s (%.2f).' % (n + 1, i['category'], i['score'], i['alternatives'][0]['category'], i['alternatives'][0]['score']))
        elif i['status'] == 'unclassified':
            r.append('Issue %d was detected but its label is not mapped to a reporting category.' % (n + 1))
        elif i['low_score']:
            r.append('Issue %d (%s) has a low reliability score (%.2f).' % (n + 1, i['category'], i['score']))
    if out['multiple_issues']:
        r.append('Different kinds of issues were detected in this photo: ' + ', '.join(sorted(confident)) + '.')
    if not out['reliability_calibrated']:
        r.append('Reliability is not calibrated on validation data yet (neutral default used).')
    return out
