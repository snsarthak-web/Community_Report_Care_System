"""Draw every used box on the photo, one colour per model, so people can see which model saw what."""
PALETTE = {'civicresolve': (219, 112, 37), 'civic_guardian': (60, 160, 60), 'streetlight': (0, 170, 230), 'own_model': (60, 60, 230), 'best_civic_model': (30, 190, 240)}   # BGR
FALLBACK = (160, 60, 160)
from ai.model_labels import label

def draw(src, predictions, dst):
    """Returns True when the annotated JPEG was written."""
    try:
        import cv2
        img = cv2.imread(src)
        if img is None:
            return False
        h, w = img.shape[:2]
        for p in sorted((p for p in predictions if p.get('used') and p.get('bbox')), key=lambda q: q.get('score', 0)):
            x, y, bw, bh = p['bbox']
            x1, y1, x2, y2 = int(x * w), int(y * h), int((x + bw) * w), int((y + bh) * h)
            col = PALETTE.get(p['model'], FALLBACK)
            cv2.rectangle(img, (x1, y1), (x2, y2), col, 4 if p.get('selected') else 2)
            text = f"{label(p['model'])[:10]} {p['label'][:18]} {int(p['confidence'] * 100)}%"
            (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
            top = max(0, y1 - th - 10)
            cv2.rectangle(img, (x1, top), (x1 + tw + 8, top + th + 10), col, -1)
            cv2.putText(img, text, (x1 + 4, top + th + 3), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)
        return bool(cv2.imwrite(dst, img))
    except Exception:
        return False
