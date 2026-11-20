from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db, utcnow

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(60), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)     # NULL for phone-only (OTP) accounts
    phone = db.Column(db.String(15), unique=True, nullable=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(10), nullable=False, default='citizen')   # 'citizen' | 'admin'
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=utcnow)
    complaints = db.relationship('Complaint', back_populates='user', foreign_keys='Complaint.user_id')

    @property
    def is_active(self):                       # Flask-Login uses this
        return bool(self.active)

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw):
        return check_password_hash(self.password_hash, pw)

    @property
    def contact(self):
        return self.email or (f'+91 {self.phone}' if self.phone else '-')

class LoginAttempt(db.Model):
    __tablename__ = 'login_attempts'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), index=True)
    ip = db.Column(db.String(60), index=True)
    success = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=utcnow, index=True)
