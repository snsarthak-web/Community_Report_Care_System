"""Single-model entry point. Flask calls YOLO only through detect(). If the model or ultralytics is missing or fails,
detect() reports it and the citizen continues with manual category selection."""
import os, uuid

_model = None
LABEL_MAP = {'pothole': 'Pothole', 'potholes': 'Pothole', 'garbage': 'Garbage', 'trash': 'Garbage', 'waste': 'Garbage',
             'drain': 'Drainage', 'streetlight': 'Streetlight', 'crack': 'Road Damage', 'road_damage': 'Road Damage'}

def category_for(label):
    old = LABEL_MAP.get((label or '').lower().replace(' ', '_'))
    if old:
        return old
    from ai.category_mapper import legacy_category          # the central 15-category mapper (superset of the old map)
    return legacy_category(label)

def _load(path):
    global _model
    if _model is None and os.path.exists(path):
        try:
            from ultralytics import YOLO
            _model = YOLO(path)
        except Exception:
            _model = None
    return _model

def annotate(src, boxes, dst):
    """Draw bounding boxes (normalised coords) on the photo and save it. Returns True on success."""
    try:
        import cv2
        img = cv2.imread(src)
        h, w = img.shape[:2]
        for b in boxes:
            x1, y1 = int(b['x'] * w), int(b['y'] * h)
            x2, y2 = int((b['x'] + b['w']) * w), int((b['y'] + b['h']) * h)
            cv2.rectangle(img, (x1, y1), (x2, y2), (0, 0, 255), 3)
            text = f"{b['label']} {int(b['confidence'] * 100)}%"
            (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
            top = max(0, y1 - th - 10)
            cv2.rectangle(img, (x1, top), (x1 + tw + 8, top + th + 10), (0, 0, 255), -1)
            cv2.putText(img, text, (x1 + 4, top + th + 3), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        return bool(cv2.imwrite(dst, img))
    except Exception:
        return False

def detect(image_path, model_path, conf=0.25, out_dir=None):
    res = {'status': 'no_model', 'label': None, 'category': None, 'confidence': 0, 'boxes': [], 'annotated': None,
           'model_name': os.path.basename(model_path)}
    model = _load(model_path)
    if model is None:
        return res
    r = model(image_path, conf=conf, verbose=False)[0]
    h, w = r.orig_shape
    boxes = []
    for b in r.boxes:
        x1, y1, x2, y2 = b.xyxy[0].tolist()
        boxes.append({'label': model.names[int(b.cls)], 'confidence': round(float(b.conf), 3),
                      'x': round(x1 / w, 4), 'y': round(y1 / h, 4), 'w': round((x2 - x1) / w, 4), 'h': round((y2 - y1) / h, 4)})
    if not boxes:
        return {**res, 'status': 'none'}
    top = max(boxes, key=lambda b: b['confidence'])
    res.update(status='ok', label=top['label'], category=category_for(top['label']), confidence=top['confidence'], boxes=boxes[:10])
    if out_dir:
        name = f"ai_{uuid.uuid4().hex[:12]}.jpg"
        if annotate(image_path, boxes, os.path.join(out_dir, name)):
            res['annotated'] = name
    return res
