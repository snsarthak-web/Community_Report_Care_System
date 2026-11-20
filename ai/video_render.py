"""The full video played back with the AI's boxes and labels drawn on it (the 'AI output video'). Pure Python (OpenCV + optional ffmpeg).

How honest boxes are drawn: the models only look at sampled frames (about one per VIDEO_SAMPLE_SECONDS), so
  * at an analysed moment the box is drawn thick (the AI really looked at that frame),
  * around it the box is followed for up to VIDEO_TRACK_SEC seconds with optical-flow tracking and drawn thin, so it stays on the
    pothole while the camera moves; tracking stops as soon as the object is lost, so no box floats over empty road.
Labels read '#1 Pothole 82%': the number is the issue number the citizen sees in the picker. Audio is kept when ffmpeg is installed.
Output: H.264 MP4 through ffmpeg when available (plays everywhere), otherwise WebM through OpenCV (plays in every modern browser)."""
import os, shutil, subprocess, uuid
import cv2
import numpy as np

COLORS = [(0, 140, 255), (60, 200, 60), (230, 120, 40), (200, 60, 200), (0, 200, 220), (120, 120, 255), (200, 200, 40), (160, 100, 60), (90, 220, 160), (140, 60, 220)]   # BGR, one per issue
DEFAULTS = dict(VIDEO_OUT_MAX_SIDE=854, VIDEO_OUT_MAX_FPS=15, VIDEO_TRACK_SEC=1.0, VIDEO_USE_FFMPEG=True)

def _c(cfg, k):
    return (cfg or {}).get(k, DEFAULTS[k])

def _frames(path, step):
    """Yield (output_index, BGR frame) taking every `step`-th source frame (step = source fps / output fps)."""
    cap = cv2.VideoCapture(path)
    try:
        fi, nxt, k = 0, 0.0, 0
        while True:
            ok, img = cap.read()
            if not ok:
                return
            if fi + 1e-6 >= nxt:
                yield k, img
                k += 1
                nxt += step
            fi += 1
    finally:
        cap.release()

def _track(G, k0, box, direction, nsteps):
    """Follow a box (pixels x,y,w,h) from small grey frame k0 in one direction; yield (k, box) while the object is still being followed."""
    x, y, w, h = box
    sh, sw = G[k0].shape
    mask = np.zeros_like(G[k0]); mask[max(0, int(y)):int(y + h), max(0, int(x)):int(x + w)] = 255
    pts = cv2.goodFeaturesToTrack(G[k0], 40, 0.01, 3, mask=mask)
    if pts is None or len(pts) < 6:
        return
    prev, k = G[k0], k0
    for _ in range(nsteps):
        k += direction
        if not 0 <= k < len(G):
            return
        p1, st, _e = cv2.calcOpticalFlowPyrLK(prev, G[k], pts, None, winSize=(21, 21), maxLevel=3)
        good = st.ravel() == 1
        if good.sum() < 5:
            return
        d = np.median((p1 - pts)[good].reshape(-1, 2), axis=0)
        x, y = x + float(d[0]), y + float(d[1])
        if not (0 <= x + w / 2 <= sw and 0 <= y + h / 2 <= sh):
            return
        pts, prev = p1[good].reshape(-1, 1, 2), G[k]
        yield k, (x, y, w, h)

def _label(img, text, x, y, col, scale):
    (tw, th), _b = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 2)
    top = int(max(0, y - th - 10)); x = int(max(0, min(x, img.shape[1] - tw - 8)))
    cv2.rectangle(img, (x, top), (x + tw + 8, top + th + 10), col, -1)
    cv2.putText(img, text, (x + 4, top + th + 3), cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), 2, cv2.LINE_AA)

class _Out:
    """ffmpeg (H.264 + the original audio) when installed, otherwise OpenCV WebM."""
    def __init__(self, src, dst_base, w, h, fps, cfg):
        self.proc, self.vw, self.path, self.ext = None, None, None, None
        ff = shutil.which('ffmpeg') if _c(cfg, 'VIDEO_USE_FFMPEG') else None
        if ff:
            self.path, self.ext = dst_base + '.mp4', 'mp4'
            cmd = [ff, '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{w}x{h}', '-r', f'{fps:g}', '-i', '-', '-i', src,
                   '-map', '0:v', '-map', '1:a?', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '27', '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
                   '-c:a', 'aac', '-b:a', '96k', '-shortest', self.path]
            try:
                self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
                return
            except OSError:
                self.proc = None
        for cc in ('VP80', 'VP90'):
            self.path, self.ext = dst_base + '.webm', 'webm'
            vw = cv2.VideoWriter(self.path, cv2.VideoWriter_fourcc(*cc), fps, (w, h))
            if vw.isOpened():
                self.vw = vw
                return
        raise RuntimeError('no usable video encoder')

    def write(self, img):
        if self.proc:
            self.proc.stdin.write(img.tobytes())
        else:
            self.vw.write(img)

    def close(self):
        if self.proc:
            try:
                self.proc.stdin.close()
            except OSError:
                pass
            if self.proc.wait(timeout=120) != 0:
                raise RuntimeError('ffmpeg failed')
        else:
            self.vw.release()

def render(src, out_dir, issues, cfg=None, progress=None):
    """-> file name (inside out_dir) of the annotated video, or None when there is nothing to draw. Raises on real failures; callers treat that as 'no annotated video'."""
    cap = cv2.VideoCapture(src)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    W, H = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    if W <= 0 or H <= 0 or not any(i.get('sightings') for i in issues):
        return None
    out_fps = min(fps, _c(cfg, 'VIDEO_OUT_MAX_FPS')); step = fps / out_fps
    sc = min(1.0, _c(cfg, 'VIDEO_OUT_MAX_SIDE') / max(W, H)); ow, oh = int(W * sc) // 2 * 2, int(H * sc) // 2 * 2
    sw = 320; sh = max(2, int(H * sw / W))
    # pass 1: small grey frames at the output rate (for tracking)
    G = [cv2.cvtColor(cv2.resize(img, (sw, sh), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY) for _k, img in _frames(src, step)]
    if not G:
        return None
    anchor, reach = max(1, int(round(0.25 * out_fps))), int(round(_c(cfg, 'VIDEO_TRACK_SEC') * out_fps))
    overlay = {}                                                   # output frame -> {issue index: (x, y, w, h normalised, analysed?)}
    def put(k, n, box, analysed, dist):
        cur = overlay.setdefault(k, {}).get(n)
        if cur is None or dist < cur[3]:
            overlay[k][n] = (box, analysed, dist, dist)
    for n, iss in enumerate(issues):
        for s in iss.get('sightings') or []:
            k0 = min(len(G) - 1, max(0, int(round(s['t'] * out_fps))))
            b = s.get('box')
            if not b:                                              # image-level classifier: no box, a label bar for the moment
                for k in range(max(0, k0 - anchor), min(len(G), k0 + anchor + 1)):
                    put(k, n, None, True, abs(k - k0))
                continue
            for k in range(max(0, k0 - anchor), min(len(G), k0 + anchor + 1)):
                put(k, n, tuple(b), True, abs(k - k0))
            px = (b[0] * sw, b[1] * sh, b[2] * sw, b[3] * sh)
            for direction in (1, -1):
                for k, (x, y, w, h) in _track(G, k0, px, direction, reach):
                    if abs(k - k0) > anchor:
                        put(k, n, (x / sw, y / sh, w / sw, h / sh), False, abs(k - k0))
    base = os.path.join(out_dir, 'ann_' + uuid.uuid4().hex[:16])
    out = _Out(src, base, ow, oh, out_fps, cfg)
    ok = False
    try:
        total = len(G)
        for k, img in _frames(src, step):
            if sc < 1.0:
                img = cv2.resize(img, (ow, oh), interpolation=cv2.INTER_AREA)
            bar = 0
            for n, (box, analysed, _d, _x) in sorted(overlay.get(k, {}).items()):
                iss, col = issues[n], COLORS[n % len(COLORS)]
                text = f"#{n + 1} {iss['category']} {int(round(iss['score'] * 100))}%"
                if box is None:
                    _label(img, text, 8, 30 + 30 * bar, col, 0.7); bar += 1
                    continue
                x1, y1, x2, y2 = int(box[0] * ow), int(box[1] * oh), int((box[0] + box[2]) * ow), int((box[1] + box[3]) * oh)
                cv2.rectangle(img, (x1, y1), (x2, y2), col, 4 if analysed else 2, cv2.LINE_AA)
                _label(img, text, x1, y1, col, 0.6)
            out.write(img)
            if progress and k % 15 == 0:
                progress(k, total)
        ok = True
    finally:
        try:
            out.close()
        except Exception:
            ok = False
        if not ok:
            try: os.remove(out.path)
            except OSError: pass
    return os.path.basename(out.path) if ok and os.path.getsize(out.path) > 1000 else None
