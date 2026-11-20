"""Report on the five checkpoints and on how well they work together.
python -m ai.model_report                                  # checkpoint facts and SHA-256 values
python -m ai.model_report --images val/images --labels val/labels --gt-map gt_map.json      # plus measured results
Section 1: file, size, SHA-256, task, classes and their app categories, training info stored in the checkpoint.
Section 2 (needs labelled images the models were not trained on): each model alone, all five as independent votes,
and the app setting where models of one family count as one vote. A category with no ground truth gets no number."""
import argparse, json, os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from ai import category_mapper as CM, decision as D, manager as M
from ai.calibrate import read_yolo_labels
from ai.safety import sha256_of

IMG = ('.jpg', '.jpeg', '.png', '.webp')

def _cfg():
    from config import Config
    return {k: getattr(Config, k) for k in dir(Config) if k.startswith(('AI_', 'VIDEO_'))}

def checkpoint_facts(cfg):
    rows = []
    for d in M.get_detectors(cfg):
        d.load()
        row = {'slot': d.name, 'display': d.display_name, 'file': d._pick_file(), 'loaded': d.model is not None, 'error': d.error}
        if d.model is not None:
            ck = getattr(d.model, 'ckpt', None) or {}
            args, tm = ck.get('train_args') or {}, ck.get('train_metrics') or {}
            row.update(size_mb=round(os.path.getsize(d.path) / 1048576, 1), sha256=sha256_of(d.path), task=d.task,
                       classes=[(int(i), n, CM.map_label(d.name, n, int(i), None)[0]) for i, n in sorted(d.names.items())],
                       base=os.path.basename(str(args.get('model', '?')).replace('\\', '/')), epochs=args.get('epochs'), imgsz=args.get('imgsz'),
                       trained=str(ck.get('date', ''))[:10], family=(cfg.get('AI_FAMILY_BY_FILE') or {}).get(d._pick_file(), d.name),
                       train_val={k.split('/')[1].split('(')[0]: round(float(v), 3) for k, v in tm.items() if k.startswith('metrics/')})
        rows.append(row)
    return rows

def _issue_stats(issues, gts, cats, iou_thr=0.5):
    """issues: decision issues; gts: [{'category','bbox'}] -> per-category tp/fp/fn counts (one issue = one reported object)."""
    out = {c: [0, 0, 0] for c in cats}
    for c in cats:
        used = set()
        for i in sorted((i for i in issues if i['category'] == c and i['box']), key=lambda i: -i['score']):
            best, bv = None, iou_thr
            for k, g in enumerate(gts):
                v = D.iou(i['box'], g['bbox']) if g['category'] == c and k not in used else 0
                if v >= bv:
                    best, bv = k, v
            if best is None:
                out[c][1] += 1
            else:
                used.add(best); out[c][0] += 1
        out[c][2] += sum(1 for k, g in enumerate(gts) if g['category'] == c and k not in used)
    return out

def compare(images_dir, labels_dir, gt_map, cfg, limit=None):
    ov = CM.load_overrides(os.path.join(M.HERE, 'class_map.json'))
    rel = D.load_reliability(os.path.join(M.HERE, 'reliability.json'))
    fam = cfg.get('AI_FAMILY_BY_FILE') or {}
    dets = [d for d in M.get_detectors(cfg) if d.load()]
    files = sorted(f for f in os.listdir(images_dir) if f.lower().endswith(IMG))[:limit]
    cats = sorted(set(gt_map.values()))
    min_score = cfg.get('AI_MIN_SCORE', 0.45)
    names = [d.name for d in dets] + ['all five, independent votes', 'all five, families merged (the app)']
    modes = {(n, cut): [0, 0, 0] for n in names for cut in ('all', 'confident')}      # confident = score >= AI_MIN_SCORE (not flagged 'low score')
    secs = {d.name: 0.0 for d in dets}
    for fn in files:
        path = os.path.join(images_dir, fn)
        gts = read_yolo_labels(os.path.join(labels_dir, os.path.splitext(fn)[0] + '.txt'), gt_map)
        preds = []
        for d in dets:
            t = time.time()
            for p in d.predict(path, conf=cfg.get('AI_CONFIDENCE', 0.25)):
                q = p.to_dict(); q['category'] = CM.map_label(p.model, p.label, p.class_id, ov)[0]
                q['family'] = fam.get(os.path.basename(d.path), p.model); q['_indep'] = p.model; preds.append(q)
            secs[d.name] += time.time() - t
        views = {d.name: [p for p in preds if p['model'] == d.name] for d in dets}
        views['all five, independent votes'] = [dict(p, family=p['_indep']) for p in preds]
        views['all five, families merged (the app)'] = preds
        for name, plist in views.items():
            res = D.decide(plist, cfg, rel)
            for cut in ('all', 'confident'):
                iss = [i for i in res['issues'] if cut == 'all' or i['score'] >= min_score]
                for c, (tp, fp, fn_) in _issue_stats(iss, gts, cats).items():
                    for k, v in enumerate((tp, fp, fn_)):
                        modes[(name, cut)][k] += v
    table = []
    for (name, cut), (tp, fp, fn_) in modes.items():
        p, r = (tp / (tp + fp) if tp + fp else None), (tp / (tp + fn_) if tp + fn_ else None)
        table.append({'mode': name, 'cut': cut, 'tp': tp, 'fp': fp, 'fn': fn_, 'precision': p, 'recall': r,
                      'f1': (2 * p * r / (p + r)) if p and r else None, 'ms_per_image': round(secs[name] / max(len(files), 1) * 1000) if name in secs else None})
    return {'images': len(files), 'categories': cats, 'table': table, 'min_score': min_score}

def render(facts, cmp_res=None):
    f = lambda v: '-' if v is None else f'{v:.3f}'
    L = ['# Model report', f'_Generated {time.strftime("%Y-%m-%d %H:%M")} by `python -m ai.model_report`._', '', '## 1. Checkpoints', '']
    L += ['| Slot | File | Task | Classes | Trained from | Epochs | Family | Size | Train-run val (P / R / mAP50) |', '|---|---|---|---|---|---|---|---|---|']
    for r in facts:
        if not r['loaded']:
            L.append(f"| {r['slot']} | {r['file']} | **NOT LOADED**: {r['error']} | | | | | | |"); continue
        tv = r['train_val']
        L.append(f"| {r['slot']} ({r['display']}) | `{r['file']}` | {r['task']} | {len(r['classes'])} | {r['base']} | {r['epochs']} | {r['family']} | {r['size_mb']} MB | "
                 f"{tv.get('precision', '-')} / {tv.get('recall', '-')} / {tv.get('mAP50', '-')} |")
    L += ['', '_The last column is what the checkpoint recorded at the end of its own training run on that run\'s own validation split; it is not comparable between rows trained on different datasets._', '', '### Classes and the app category each maps to', '']
    for r in facts:
        if r['loaded']:
            L.append(f"* **{r['slot']}**: " + ', '.join(f"{n} → {c or 'UNMAPPED'}" for _, n, c in r['classes']))
    L += ['', '### SHA-256 (paste into `AI_MODEL_SHA256` in config.py to pin the exact files)', '', '```']
    L += [f"'{r['file']}': '{r['sha256']}'," for r in facts if r['loaded']] + ['```', '']
    if cmp_res:
        L += [f"## 2. Measured on {cmp_res['images']} labelled images ({', '.join(cmp_res['categories'])})", '']
        for cut, title in (('confident', f"Issues the app would NOT flag as low-score (reliability-weighted score >= {cmp_res['min_score']}): the operating point"),
                           ('all', 'Every reported issue, no score cut')):
            L += [f'### {title}', '', '| Strategy | True pos | False pos | Missed | Precision | Recall | F1 | Model time / image |', '|---|---|---|---|---|---|---|---|']
            for t in (t for t in cmp_res['table'] if t['cut'] == cut):
                L.append(f"| {t['mode']} | {t['tp']} | {t['fp']} | {t['fn']} | {f(t['precision'])} | {f(t['recall'])} | {f(t['f1'])} | {str(t['ms_per_image']) + ' ms' if t['ms_per_image'] is not None else ''} |")
            L.append('')
        L += ['One reported issue = one object; a hit needs IoU >= 0.5 with a labelled box. Only categories present in your labels are scored.',
              '"Independent votes" and "families merged" find the same boxes: merging a family changes the SCORE (it stops two related checkpoints from reinforcing each other), not the box count.', '']
    return '\n'.join(L)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--images'); ap.add_argument('--labels'); ap.add_argument('--gt-map'); ap.add_argument('--limit', type=int)
    ap.add_argument('--out', default=os.path.join(M.HERE, '..', 'docs', 'MODEL_REPORT.md')); ap.add_argument('--json')
    a = ap.parse_args()
    cfg = _cfg(); facts = checkpoint_facts(cfg); cmp_res = None
    if a.images:
        if not (a.labels and a.gt_map):
            sys.exit('--images needs --labels and --gt-map')
        cmp_res = compare(a.images, a.labels, json.load(open(a.gt_map)), cfg, a.limit)
    text = render(facts, cmp_res)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    open(a.out, 'w', encoding='utf-8').write(text)
    if a.json:
        json.dump({'facts': facts, 'compare': cmp_res}, open(a.json, 'w'), indent=1)
    print(text); print('\nwrote', os.path.abspath(a.out))

if __name__ == '__main__':
    main()
