import os
from dotenv import load_dotenv
BASE = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(BASE, '.env'))
_DB = os.environ.get('DATABASE_PATH') or os.path.join(BASE, 'instance', 'database.db')

class Config:
    COMPANY_NAME = os.environ.get('COMPANY_NAME') or 'Community Report Care by snsarthak-web-Digital— Designed and built with passion.'  # footer text
    COPYRIGHT_YEAR = os.environ.get('COPYRIGHT_YEAR') or ''  # empty = current year
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-only-change-me'
    DB_PATH = _DB
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///' + _DB.replace('\\', '/')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER') or os.path.join(BASE, 'static', 'uploads')
    MAX_IMAGE_MB = 8
    VIDEO_MAX_MB = 60  # max video upload size
    VIDEO_MAX_SECONDS = 60
    VIDEO_MAX_FRAMES = 12  # frames analysed per video
    VIDEO_SAMPLE_SECONDS = 2.0  # seconds between analysed frames
    VIDEO_ISSUE_GAP_SEC = 3.0  # frames further apart than this count as a different issue
    VIDEO_SAME_SPOT_M = 25  # sightings closer than this (m) count as the same issue
    VIDEO_GPS_MAX_DT = 6.0  # max seconds between a GPS sample and a detection
    VIDEO_ANNOTATED_OUTPUT = True  # also write a copy of the video with boxes drawn
    VIDEO_OUT_MAX_SIDE = 854  # longest side of the annotated video (px)
    VIDEO_OUT_MAX_FPS = 15
    VIDEO_TRACK_SEC = 1.0  # seconds a box is tracked around an analysed frame
    VIDEO_USE_FFMPEG = True  # MP4 with audio when ffmpeg is installed, otherwise WebM
    VIDEO_MAX_ISSUES = 10  # max issues listed per video
    VIDEO_FRAME_MAX_SIDE = 1280
    VIDEO_MAX_CONCURRENT = 1  # videos analysed at the same time
    VIDEO_MAX_OPEN = 5  # unsubmitted videos allowed per citizen
    MAX_CONTENT_LENGTH = (VIDEO_MAX_MB + 4) * 1024 * 1024  # whole request size; images are limited by MAX_IMAGE_MB
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', 'admin@crc.local')
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'ChangeMe@12345')
    TZ_OFFSET_MINUTES = int(os.environ.get('TZ_OFFSET_MINUTES', 330))  # stored in UTC, shown as IST
    TZ_LABEL = os.environ.get('TZ_LABEL', 'IST')
    OTP_SECONDS = 20  # code validity in seconds
    OTP_MAX_TRIES = 5
    LOGIN_MAX_ATTEMPTS = 5  # failed logins before lock-out
    LOCKOUT_MINUTES = 15
    MODEL_PATH = os.environ.get('YOLO_MODEL_PATH') or os.path.join(BASE, 'ai', 'models', 'best.pt')
    AI_CONFIDENCE = 0.25  # minimum confidence
    # multi-model AI (ai/manager.py): checkpoints are Model_1.pt ... Model_5.pt in ai/models/ (old file names still work)
    AI_MODELS_DIR = os.environ.get('AI_MODELS_DIR') or os.path.join(BASE, 'ai', 'models')
    AI_RESULTS_DIR = os.path.join(BASE, 'instance', 'ai_results')  # full analysis per photo
    AI_MODEL_THRESHOLDS = {}  # per-model overrides
    AI_CATEGORY_THRESHOLDS = {}  # per-category overrides
    AI_IOU_MATCH = 0.5  # IoU at or above this = same object
    AI_CONTAIN_MATCH = 0.7  # box inside another by this fraction = same object (None = off)
    AI_CONFLICT_MARGIN = 0.15  # top two categories closer than this need confirmation
    AI_MIN_SCORE = 0.45  # lower scores need confirmation
    AI_DEFAULT_RELIABILITY = 0.6  # used until ai/reliability.json exists
    AI_PARALLEL = False  # run models in threads
    AI_IMGSZ = None  # inference size (None = model default)
    AI_MAX_DET = 20
    AI_MAX_CKPT_MB = 500  # max checkpoint size
    AI_MODEL_SHA256 = {}  # optional SHA-256 per checkpoint file
    AI_EXTRA_MODELS = {}  # extra checkpoints beyond Model_1..Model_5 (see ai/detectors/extra.py)
    AI_MODEL_FILES = {}  # override the file a slot loads
    # models trained from one another count as one vote
    # Model_1 and Model_4 are grouped for now; the old file names are kept so older copies still match
    AI_FAMILY_BY_FILE = {
    'Model_1.pt': 'model_1',
    'Model_4.pt': 'pothole_garbage',
    'pothole_garbage_v1.pt': 'pothole_garbage',
    'pothole_garbage_v2.pt': 'pothole_garbage'
}
    DUP_RADIUS_DEG = 0.004  # about 400 m
    GPS_MAX_ACCURACY_M = 100000  # upper sanity limit
    GPS_POOR_ACCURACY_M = 50  # above this the pin should be checked on the map
    ALLOWED_EXT = {'jpg', 'jpeg', 'png', 'webp'}
    CATEGORIES = ['Pothole', 'Garbage', 'Road Damage', 'Open Manhole', 'Drainage', 'Waterlogging', 'Water Leakage', 'Streetlight',
                  'Broken Sign', 'Illegal Parking', 'Fallen Tree', 'Vandalism', 'Dead Animal', 'Damaged Electrical Wires', 'Other']
    DEPARTMENTS = ['Roads & Highways', 'Sanitation', 'Drainage & Water', 'Electrical', 'General']
    STATUSES = ['Submitted', 'Under Review', 'Assigned', 'In Progress', 'Resolved']
