"""Shared YOLO wrapper. One detector instance per checkpoint; it is loaded once per process (lazily, thread-safe) and cached.
A failing/missing checkpoint only disables that detector: the others keep working."""
import os, threading, time
from dataclasses import dataclass, asdict
from typing import Optional, Tuple
from ai.safety import resolve_checkpoint

RETRY_AFTER = 30            # seconds before a failed load is retried
SUPPORTED_TASKS = ('detect', 'segment', 'obb', 'classify')

@dataclass
class Prediction:
    model: str
    label: str                                  # the model's own class name
    class_id: int
    confidence: float                           # raw confidence from that model (not comparable between models)
    bbox: Optional[Tuple[float, float, float, float]] = None      # normalised (x, y, w, h); None for image-level classification
    task: str = 'detect'
    image_level: bool = False
    category: Optional[str] = None              # filled in by ai.category_mapper
    mapped_by: str = 'unmapped'
    family: Optional[str] = None                # models trained from one another share a family: they are one vote, not several (filled in by ai.manager)

    def to_dict(self):
        d = asdict(self)
        d['bbox'] = None if self.bbox is None else [round(v, 4) for v in self.bbox]
        d['confidence'] = round(float(self.confidence), 4)
        return d

class BaseDetector:
    name = ''                     # stable id (database / config / class_map.json)
    display_name = ''
    filenames = ()                # checkpoint names inside ai/models, first existing one wins

    def __init__(self, models_dir, cfg=None):
        self.models_dir, self.cfg = models_dir, cfg or {}
        self.model, self.error, self.task, self.names, self.path = None, None, None, {}, None
        self._lock, self._infer_lock = threading.Lock(), threading.Lock()
        self._failed_at = 0.0

    # loading
    def _candidates(self):
        override = (self.cfg.get('AI_MODEL_FILES') or {}).get(self.name)      # optional: {'own_model': 'my best (3).pt'}
        return ((override,) if override else ()) + tuple(self.filenames)

    def _pick_file(self):
        cands = self._candidates()
        for fn in cands:
            if os.path.lexists(os.path.join(self.models_dir, fn)):
                return fn
        return cands[0] if cands else ''

    def load(self):
        with self._lock:
            if self.model is not None:
                return True
            if self.error and time.time() - self._failed_at < RETRY_AFTER:
                return False
            self.error = None
            fn = self._pick_file()
            pins = self.cfg.get('AI_MODEL_SHA256') or {}
            path, err = resolve_checkpoint(self.models_dir, fn, self.cfg.get('AI_MAX_CKPT_MB', 500), pins.get(fn))
            if err:
                return self._fail(f'{fn}: {err}')
            try:
                from ultralytics import YOLO
            except Exception:
                return self._fail('ultralytics is not installed (pip install ultralytics)')
            try:
                model = YOLO(path)
                task = getattr(model, 'task', None) or 'detect'
                if task not in SUPPORTED_TASKS:
                    return self._fail(f'unsupported model task "{task}"')
                names = dict(getattr(model, 'names', None) or {})
            except Exception as e:                                          # corrupt / incompatible checkpoint
                return self._fail(f'could not load {fn}: {type(e).__name__}: {str(e)[:160]}')
            self.model, self.task, self.names, self.path = model, task, names, path
            return True

    def _fail(self, msg):
        self.error, self._failed_at = msg, time.time()
        return False

    def info(self):
        return {'name': self.name, 'display_name': self.display_name, 'file': self._pick_file(), 'loaded': self.model is not None,
                'task': self.task, 'file_loaded': os.path.basename(self.path) if self.path else None, 'classes': {int(k): v for k, v in self.names.items()}, 'error': self.error}

    # inference
    def predict(self, image_path, conf=0.25):
        """-> list[Prediction]  (empty list when nothing is detected). Raises only on real inference errors."""
        if not self.load():
            raise RuntimeError(self.error or 'model not available')
        kw = {'conf': conf, 'verbose': False}
        if self.cfg.get('AI_IMGSZ'):
            kw['imgsz'] = self.cfg['AI_IMGSZ']
        if self.cfg.get('AI_MAX_DET') and self.task != 'classify':
            kw['max_det'] = self.cfg['AI_MAX_DET']
        with self._infer_lock:                                              # one inference at a time per loaded model
            r = self.model(image_path, **kw)[0]
        return self._parse(r, conf)

    def _label(self, r, cid):
        return str((self.names or getattr(r, 'names', {}) or {}).get(cid, cid))

    def _parse(self, r, conf):
        out = []
        if self.task == 'classify':
            p = getattr(r, 'probs', None)
            if p is not None and float(p.top1conf) >= conf:
                cid = int(p.top1)
                out.append(Prediction(self.name, self._label(r, cid), cid, float(p.top1conf), None, 'classify', image_level=True))
            return out
        h, w = r.orig_shape
        if self.task == 'obb':
            o = getattr(r, 'obb', None)
            rows = [] if o is None else list(zip(o.xyxy.tolist(), [int(c) for c in o.cls.tolist()], [float(c) for c in o.conf.tolist()]))
        else:
            rows = [(b.xyxy[0].tolist(), int(b.cls), float(b.conf)) for b in (getattr(r, 'boxes', None) or [])]
        for (x1, y1, x2, y2), cid, c in rows:
            if c < conf:
                continue
            x1, y1, x2, y2 = (min(max(v, 0.0), m) for v, m in ((x1, w), (y1, h), (x2, w), (y2, h)))
            out.append(Prediction(self.name, self._label(r, cid), cid, c, (x1 / w, y1 / h, (x2 - x1) / w, (y2 - y1) / h), self.task))
        return out
