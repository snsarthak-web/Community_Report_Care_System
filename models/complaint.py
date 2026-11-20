import json
from extensions import db, utcnow

STATUSES = ['Submitted', 'Under Review', 'Assigned', 'In Progress', 'Resolved']
GROUPS = {'pending': STATUSES[:3], 'progress': ['In Progress'], 'solved': ['Resolved']}
PRIORITIES = ('Low', 'Medium', 'High', 'Critical')

class Department(db.Model):
    __tablename__ = 'departments'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    complaints = db.relationship('Complaint', back_populates='department')

class Complaint(db.Model):
    __tablename__ = 'complaints'
    id = db.Column(db.Integer, primary_key=True)
    tracking_id = db.Column(db.String(20), unique=True, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    category = db.Column(db.String(40), nullable=False, index=True)
    description = db.Column(db.Text)
    reporting_method = db.Column(db.String(10), nullable=False)          # 'ai' | 'manual'
    image_path = db.Column(db.String(80))
    location_text = db.Column(db.String(200))
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    status = db.Column(db.String(20), nullable=False, default='Submitted', index=True)
    priority = db.Column(db.String(10), nullable=False, default='Low')
    priority_locked = db.Column(db.Boolean, default=False)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'))
    assigned_officer = db.Column(db.String(80))
    resolution_image = db.Column(db.String(80))                         # after-repair photo
    resolved_at = db.Column(db.DateTime)
    citizen_feedback = db.Column(db.String(12))                          # 'confirmed' | 'disputed'
    feedback_note = db.Column(db.String(300))
    created_at = db.Column(db.DateTime, default=utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    user = db.relationship('User', back_populates='complaints', foreign_keys=[user_id])
    department = db.relationship('Department', back_populates='complaints')
    detection = db.relationship('AIDetection', back_populates='complaint', uselist=False, cascade='all, delete-orphan')
    ai_predictions = db.relationship('AIPrediction', back_populates='complaint', cascade='all, delete-orphan', order_by='AIPrediction.id')
    ai_analysis = db.relationship('AIAnalysis', back_populates='complaint', uselist=False, cascade='all, delete-orphan')
    videos = db.relationship('ComplaintVideo', back_populates='complaint', cascade='all, delete-orphan', order_by='ComplaintVideo.id')
    geo = db.relationship('ComplaintGeo', back_populates='complaint', uselist=False, cascade='all, delete-orphan')
    video_issue = db.relationship('ComplaintVideoIssue', back_populates='complaint', uselist=False, cascade='all, delete-orphan')
    votes = db.relationship('ComplaintVote', back_populates='complaint', cascade='all, delete-orphan')
    history = db.relationship('StatusHistory', back_populates='complaint', cascade='all, delete-orphan', order_by='StatusHistory.id')

    @property
    def vote_count(self):                      # the reporter counts as the first supporter
        return 1 + len(self.votes)

    @property
    def boxes(self):
        try:
            return json.loads(self.detection.bounding_box) if self.detection and self.detection.bounding_box else []
        except ValueError:
            return []

class AIDetection(db.Model):
    __tablename__ = 'ai_detections'
    id = db.Column(db.Integer, primary_key=True)
    complaint_id = db.Column(db.Integer, db.ForeignKey('complaints.id'), nullable=False, unique=True)
    detected_object = db.Column(db.String(60))
    confidence = db.Column(db.Float)
    bounding_box = db.Column(db.Text)
    model_name = db.Column(db.String(80))
    annotated_path = db.Column(db.String(80))
    prediction_verified = db.Column(db.Boolean, nullable=True)            # None = not reviewed, True = correct, False = incorrect
    created_at = db.Column(db.DateTime, default=utcnow)
    complaint = db.relationship('Complaint', back_populates='detection')

def _j(text, default):
    try:
        return json.loads(text) if text else default
    except ValueError:
        return default

class AIPrediction(db.Model):
    """one prediction of one model (a complaint has many: up to five models x several objects, image or video frames).
    The older AIDetection row is kept as the one-line summary so existing screens keep working."""
    __tablename__ = 'ai_predictions'
    id = db.Column(db.Integer, primary_key=True)
    complaint_id = db.Column(db.Integer, db.ForeignKey('complaints.id'), nullable=False, index=True)
    source = db.Column(db.String(8), default='image')                    # 'image' | 'video'
    model_name = db.Column(db.String(40), nullable=False)
    model_label = db.Column(db.String(80))                               # the model's own class name
    category = db.Column(db.String(40))                                  # normalised reporting category; NULL = unclassified
    confidence = db.Column(db.Float)                                     # raw model confidence
    reliability = db.Column(db.Float)                                    # class-specific validation reliability used
    score = db.Column(db.Float)                                          # confidence x reliability
    bounding_box = db.Column(db.Text)                                    # JSON [x, y, w, h] normalised, NULL for image-level classifiers
    task = db.Column(db.String(12))
    image_level = db.Column(db.Boolean, default=False)
    issue_index = db.Column(db.Integer)                                  # which physical object (0 = the main one)
    is_selected = db.Column(db.Boolean, default=False)                   # part of the suggested issue
    is_conflict = db.Column(db.Boolean, default=False)
    annotated_path = db.Column(db.String(80))                            # annotated image / annotated video frame
    frame_index = db.Column(db.Integer)                                  # video only
    timestamp_sec = db.Column(db.Float)                                  # video only
    verified = db.Column(db.Boolean, nullable=True)                      # admin verdict: None = not reviewed
    verified_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    verified_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow)
    complaint = db.relationship('Complaint', back_populates='ai_predictions')
    verifier = db.relationship('User', foreign_keys=[verified_by])

    @property
    def box(self):
        return _j(self.bounding_box, None)

class AIAnalysis(db.Model):
    """The decision summary for a complaint (one row): suggestion, conflicts, model availability."""
    __tablename__ = 'ai_analyses'
    id = db.Column(db.Integer, primary_key=True)
    complaint_id = db.Column(db.Integer, db.ForeignKey('complaints.id'), nullable=False, unique=True)
    source = db.Column(db.String(8), default='image')
    suggested_category = db.Column(db.String(40))
    reliability = db.Column(db.Float)
    calibrated = db.Column(db.Boolean, default=False)
    needs_confirmation = db.Column(db.Boolean, default=False)
    conflict = db.Column(db.Boolean, default=False)
    multiple_issues = db.Column(db.Boolean, default=False)
    citizen_category = db.Column(db.String(40))                          # what the citizen finally chose (never overwritten by AI)
    issues_json = db.Column(db.Text)
    models_json = db.Column(db.Text)
    reasons_json = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=utcnow)
    complaint = db.relationship('Complaint', back_populates='ai_analysis')

    @property
    def issues(self): return _j(self.issues_json, [])
    @property
    def models(self): return _j(self.models_json, [])
    @property
    def reasons(self): return _j(self.reasons_json, [])

class ComplaintVideo(db.Model):
    """Video evidence attached to a complaint (plus the optional GPS fixes recorded while filming)."""
    __tablename__ = 'complaint_videos'
    id = db.Column(db.Integer, primary_key=True)
    complaint_id = db.Column(db.Integer, db.ForeignKey('complaints.id'), nullable=False, index=True)
    filename = db.Column(db.String(60), nullable=False)
    thumb = db.Column(db.String(80))
    duration_sec = db.Column(db.Float)
    fps = db.Column(db.Float)
    width = db.Column(db.Integer)
    height = db.Column(db.Integer)
    size_bytes = db.Column(db.Integer)
    frames_analyzed = db.Column(db.Integer)
    gps_json = db.Column(db.Text)                                        # [{"t":1.2,"lat":..,"lng":..,"acc":..}, ...]  optional, unverified
    summary_json = db.Column(db.Text)                                    # per-issue timeline
    created_at = db.Column(db.DateTime, default=utcnow)
    complaint = db.relationship('Complaint', back_populates='videos')

    @property
    def gps(self): return _j(self.gps_json, [])
    @property
    def summary(self): return _j(self.summary_json, {})

class ComplaintGeo(db.Model):
    """how the complaint's coordinates were obtained (new table: complaints keep their own lat/lng columns, nothing old is altered).
    A phone's GPS fix is where the phone was, with an accuracy radius: never presented as the exact spot of the problem."""
    __tablename__ = 'complaint_geo'
    id = db.Column(db.Integer, primary_key=True)
    complaint_id = db.Column(db.Integer, db.ForeignKey('complaints.id'), nullable=False, unique=True)
    source = db.Column(db.String(20))                                    # gps | gps_adjusted | video_gps | video_gps_adjusted | upload_fix | map_pin | landmark
    accuracy_m = db.Column(db.Float)                                     # radius reported by the device (None when no GPS was used)
    captured_lat = db.Column(db.Float)                                   # what the device reported, before any pin adjustment
    captured_lng = db.Column(db.Float)
    moved_m = db.Column(db.Float)                                        # how far the citizen moved the pin from the device fix
    sample_dt_sec = db.Column(db.Float)                                  # video: seconds between the detection and the GPS sample used
    created_at = db.Column(db.DateTime, default=utcnow)
    complaint = db.relationship('Complaint', back_populates='geo')

class ComplaintVideoIssue(db.Model):
    """One complaint that came out of a video: which moment, which video, and which sibling complaints share the same video (group_id)."""
    __tablename__ = 'complaint_video_issues'
    id = db.Column(db.Integer, primary_key=True)
    complaint_id = db.Column(db.Integer, db.ForeignKey('complaints.id'), nullable=False, unique=True)
    group_id = db.Column(db.String(24), index=True)
    video_filename = db.Column(db.String(60), nullable=False)
    issue_id = db.Column(db.String(8))
    category_ai = db.Column(db.String(40))                               # what the AI saw (the complaint's category is what the citizen confirmed)
    timestamp_sec = db.Column(db.Float)                                  # best moment
    timestamps_json = db.Column(db.Text)
    score = db.Column(db.Float)
    frames_seen = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=utcnow)
    complaint = db.relationship('Complaint', back_populates='video_issue')

    @property
    def timestamps(self): return _j(self.timestamps_json, [])

class ComplaintVote(db.Model):
    __tablename__ = 'complaint_votes'
    id = db.Column(db.Integer, primary_key=True)
    complaint_id = db.Column(db.Integer, db.ForeignKey('complaints.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow)
    __table_args__ = (db.UniqueConstraint('complaint_id', 'user_id', name='uq_vote_once'),)
    complaint = db.relationship('Complaint', back_populates='votes')
    user = db.relationship('User')

class StatusHistory(db.Model):
    __tablename__ = 'status_history'
    id = db.Column(db.Integer, primary_key=True)
    complaint_id = db.Column(db.Integer, db.ForeignKey('complaints.id'), nullable=False, index=True)
    old_status = db.Column(db.String(20))
    new_status = db.Column(db.String(20), nullable=False)
    note = db.Column(db.String(300))
    updated_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=utcnow)
    complaint = db.relationship('Complaint', back_populates='history')
    author = db.relationship('User', foreign_keys=[updated_by])

class Notification(db.Model):
    __tablename__ = 'notifications'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    complaint_id = db.Column(db.Integer, db.ForeignKey('complaints.id'))
    message = db.Column(db.String(400), nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=utcnow)
    complaint = db.relationship('Complaint')

class AuditLog(db.Model):
    """Who (admin) did what, and when. Never edited from the UI."""
    __tablename__ = 'audit_log'
    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    action = db.Column(db.String(40), nullable=False)
    complaint_id = db.Column(db.Integer, db.ForeignKey('complaints.id'))
    details = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=utcnow, index=True)
    admin = db.relationship('User')
    complaint = db.relationship('Complaint')
