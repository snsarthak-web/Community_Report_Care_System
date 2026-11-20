import os, re, uuid
from flask import current_app
from PIL import Image, ImageOps

def save_image(fs):
    """Validate (type, size, real image), fix phone rotation, shrink, store as JPEG. Raises ValueError with a friendly message."""
    cfg = current_app.config
    if not fs or not fs.filename:
        raise ValueError('No photo selected.')
    ext = fs.filename.rsplit('.', 1)[-1].lower() if '.' in fs.filename else ''
    if ext not in cfg['ALLOWED_EXT']:
        raise ValueError('Unsupported format. Please use a JPG, PNG or WEBP photo.')
    fs.stream.seek(0, 2); size = fs.stream.tell(); fs.stream.seek(0)
    if size > cfg['MAX_IMAGE_MB'] * 1024 * 1024:
        raise ValueError(f"Photo is too large (max {cfg['MAX_IMAGE_MB']} MB).")
    try:
        Image.open(fs.stream).verify(); fs.stream.seek(0)
        img = ImageOps.exif_transpose(Image.open(fs.stream)).convert('RGB')
    except Exception:
        raise ValueError('That file is not a valid image.')
    img.thumbnail((1600, 1600))
    name = f"{uuid.uuid4().hex[:16]}.jpg"
    img.save(os.path.join(cfg['UPLOAD_FOLDER'], name), 'JPEG', quality=85)
    return name

def safe_photo(name):
    """Only accept filenames this app generated, and only if the file exists."""
    name = os.path.basename(name or '')
    if re.fullmatch(r'[0-9a-f]{16}\.jpg', name) and os.path.exists(os.path.join(current_app.config['UPLOAD_FOLDER'], name)):
        return name
    return None
