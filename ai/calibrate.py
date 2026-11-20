"""Measures how reliable each model is per category on a validation set and writes ai/reliability.json.
python -m ai.calibrate --images val/images --labels val/labels --gt-map gt_map.json
  labels: YOLO txt files (class xc yc w h, normalised), one per image
  gt_map.json: validation class id -> app category, e.g. {"0": "Pothole", "1": "Garbage"}
Precision = true positives / all predictions of that category by that model (IoU >= 0.5). A prediction's confidence is
multiplied by this number in the decision step."""
import argparse, json, os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from ai.decision import iou

def evaluate(pred_by_image, gt_by_image, iou_thr=0.5, min_support=5):
    """pred_by_image {img: [{'model','category','confidence','bbox'(x,y,w,h)}]}, gt_by_image {img: [{'category','bbox'}]}
    -> {model: {category: {'precision','recall','tp','fp','fn','n'}}}; categories with < min_support predictions are left out."""
    stats, gt_total = {}, {}
    for img, gts in gt_by_image.items():
        for g in gts:
            gt_total[g['category']] = gt_total.get(g['category'], 0) + 1
    for img in set(pred_by_image) | set(gt_by_image):
        gts = gt_by_image.get(img, [])
        for model in {p['model'] for p in pred_by_image.get(img, [])}:
            for cat in {p['category'] for p in pred_by_image[img] if p['model'] == model and p['category']}:
                used, s = set(), stats.setdefault(model, {}).setdefault(cat, {'tp': 0, 'fp': 0})
                for p in sorted((p for p in pred_by_image[img] if p['model'] == model and p['category'] == cat), key=lambda q: -q['confidence']):
                    best, bv = None, iou_thr
                    for k, g in enumerate(gts):
                        if k not in used and g['category'] == cat and p['bbox'] and iou(p['bbox'], g['bbox']) >= bv:
                            best, bv = k, iou(p['bbox'], g['bbox'])
                    if best is None:
                        s['fp'] += 1
                    else:
                        used.add(best); s['tp'] += 1
    out = {}
    for model, cats in stats.items():
        for cat, s in cats.items():
            n = s['tp'] + s['fp']
            tot = gt_total.get(cat, 0)
            if n < min_support or tot == 0:        # no ground truth for this category in the validation set -> no number (never a fake 0.0)
                continue
            out.setdefault(model, {})[cat] = {'precision': round(s['tp'] / n, 3), 'recall': round(s['tp'] / tot, 3) if tot else None,
                                              'tp': s['tp'], 'fp': s['fp'], 'fn': max(tot - s['tp'], 0), 'n': n}
    return out

def read_yolo_labels(path, gt_map):
    rows = []
    try:
        for line in open(path):
            c, xc, yc, w, h = line.split()[:5]
            if c in gt_map:
                rows.append({'category': gt_map[c], 'bbox': (float(xc) - float(w) / 2, float(yc) - float(h) / 2, float(w), float(h))})
    except OSError:
        pass
    return rows

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--images', required=True); ap.add_argument('--labels', required=True); ap.add_argument('--gt-map', required=True)
    ap.add_argument('--out', default=None); ap.add_argument('--min-support', type=int, default=5)
    a = ap.parse_args()
    from ai import manager as M, category_mapper as CM
    gt_map = json.load(open(a.gt_map))
    ov = CM.load_overrides(os.path.join(M.HERE, 'class_map.json'))
    dets, preds, gts = M.get_detectors({}), {}, {}
    for fn in sorted(os.listdir(a.images)):
        if not fn.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
            continue
        path = os.path.join(a.images, fn)
        gts[fn] = read_yolo_labels(os.path.join(a.labels, os.path.splitext(fn)[0] + '.txt'), gt_map)
        preds[fn] = []
        for d in dets:
            if not d.load():
                continue
            for p in d.predict(path, conf=0.25):
                cat, _ = CM.map_label(p.model, p.label, p.class_id, ov)
                preds[fn].append({'model': p.model, 'category': cat, 'confidence': p.confidence, 'bbox': p.bbox})
    result = evaluate(preds, gts, min_support=a.min_support)
    result['_generated'] = time.strftime('%Y-%m-%d %H:%M')
    out = a.out or os.path.join(M.HERE, 'reliability.json')
    json.dump(result, open(out, 'w'), indent=2)
    print('wrote', out)
    for m, cats in result.items():
        if not m.startswith('_'):
            print(m, {c: v['precision'] for c, v in cats.items()})

if __name__ == '__main__':
    main()
