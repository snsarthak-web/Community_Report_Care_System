"""Server-side storage of one AI analysis per uploaded photo.
The session cookie is only about 4 KB and five models' predictions can overflow it, so the full result is kept in a small JSON file.
The file belongs to the user who uploaded the photo, and the complaint is created from this copy, not from browser values."""
import json, os, re, time

SAFE = re.compile(r'[0-9a-f]{16}\.jpg')
MAX_AGE = 7 * 86400

def _path(folder, photo):
    return os.path.join(folder, photo[:-4] + '.json')

def save(folder, photo, user_id, result):
    if not SAFE.fullmatch(photo or ''):
        return False
    os.makedirs(folder, exist_ok=True)
    tmp = _path(folder, photo) + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump({'user_id': user_id, 'saved': time.time(), 'result': result}, fh)
    os.replace(tmp, _path(folder, photo))
    now = time.time()
    for fn in os.listdir(folder):                         # prune old files
        fp = os.path.join(folder, fn)
        try:
            if fn.endswith('.json') and now - os.path.getmtime(fp) > MAX_AGE:
                os.remove(fp)
        except OSError:
            pass
    return True

def load(folder, photo, user_id):
    if not SAFE.fullmatch(photo or ''):
        return None
    try:
        with open(_path(folder, photo), encoding='utf-8') as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        return None
    return d.get('result') if d.get('user_id') == user_id else None
