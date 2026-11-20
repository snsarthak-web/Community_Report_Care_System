"""Checkpoint safety. A .pt file is a Python pickle, so loading it can run code. A file is only loaded when it
  * is directly inside ai/models/ (no request-supplied path, no symlink leaving the folder),
  * is a regular .pt file of acceptable size,
  * and matches its SHA-256 in AI_MODEL_SHA256 when one is set."""
import hashlib, os

def sha256_of(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for block in iter(lambda: fh.read(chunk), b''):
            h.update(block)
    return h.hexdigest()

def resolve_checkpoint(models_dir, filename, max_mb=500, sha256=None):
    """-> (absolute_path, None) when safe, otherwise (None, 'reason')."""
    if not filename or os.path.basename(filename) != filename or not filename.lower().endswith('.pt'):
        return None, 'not a plain .pt file name'
    base = os.path.realpath(models_dir)
    path = os.path.join(models_dir, filename)
    if not os.path.lexists(path):
        return None, 'file not found'
    real = os.path.realpath(path)
    if os.path.dirname(real) != base:
        return None, 'refused: file resolves outside the models folder'
    if not os.path.isfile(real):
        return None, 'not a regular file'
    size = os.path.getsize(real)
    if size == 0:
        return None, 'file is empty'
    if size > max_mb * 1024 * 1024:
        return None, f'refused: file larger than {max_mb} MB'
    if sha256 and sha256_of(real).lower() != str(sha256).lower():
        return None, 'refused: SHA-256 does not match the pinned value'
    return real, None
