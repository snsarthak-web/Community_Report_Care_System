from datetime import timedelta
from flask import current_app
from extensions import db, utcnow
from models.user import LoginAttempt

def locked_minutes(email, ip):
    """Minutes left if this email+ip (or this ip overall) is locked out, else 0."""
    cfg = current_app.config
    since = utcnow() - timedelta(minutes=cfg['LOCKOUT_MINUTES'])
    q = LoginAttempt.query.filter(LoginAttempt.created_at >= since, LoginAttempt.success.is_(False))
    mine = q.filter(LoginAttempt.email == email, LoginAttempt.ip == ip).count()
    anyone = q.filter(LoginAttempt.ip == ip).count()
    if mine >= cfg['LOGIN_MAX_ATTEMPTS'] or anyone >= cfg['LOGIN_MAX_ATTEMPTS'] * 4:
        return cfg['LOCKOUT_MINUTES']
    return 0

def record(email, ip, ok):
    if ok:
        LoginAttempt.query.filter_by(email=email, ip=ip, success=False).delete()
    else:
        db.session.add(LoginAttempt(email=email, ip=ip, success=False))
    db.session.commit()
