import os
from flask import Flask, render_template, request, redirect, flash, jsonify
from flask_login import current_user
from config import Config
from extensions import db, login_manager, csrf_token, csrf_input, check_csrf, utcnow
from services import timeutil as TZ

def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(os.path.dirname(app.config['DB_PATH']), exist_ok=True)
    db.init_app(app)
    login_manager.init_app(app)

    from routes.auth import bp as auth_bp
    from routes.citizen import bp as citizen_bp
    from routes.admin import bp as admin_bp
    from routes.ai import bp as ai_bp
    for b in (auth_bp, citizen_bp, admin_bp, ai_bp):
        app.register_blueprint(b)
    app.before_request(check_csrf)

    @app.after_request
    def headers(r):
        r.headers.setdefault('X-Content-Type-Options', 'nosniff')
        r.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
        return r

    off = lambda: app.config.get('TZ_OFFSET_MINUTES', 330)

    @app.template_filter('mlabel')
    def _mlabel(v):
        from ai.model_labels import label
        return label(v)

    @app.template_filter('d')
    def fmt_date(v):
        return TZ.to_local(v, off()).strftime('%b %d, %Y') if v else ''

    @app.template_filter('dt')
    def fmt_dt(v):
        return TZ.to_local(v, off()).strftime('%Y-%m-%d %H:%M') if v else ''

    @app.template_filter('tm')
    def fmt_time(v):
        return TZ.to_local(v, off()).strftime('%I:%M %p').lstrip('0') if v else ''

    @app.template_filter('ago')
    def fmt_ago(v):
        return TZ.ago(v, utcnow(), off()) if v else ''

    @app.template_filter('daylabel')
    def fmt_daylabel(v):
        return TZ.day_label(v, utcnow(), off()) if v else ''

    @app.context_processor
    def inject():
        from services import complaint_service as S
        from models.complaint import STATUSES
        return dict(csrf_token=csrf_token, csrf_input=csrf_input, STATUSES=STATUSES, GEO_LABEL=S.SOURCE_LABEL,
                    now_local=lambda: TZ.to_local(utcnow(), off()), COMPANY_NAME=app.config['COMPANY_NAME'], COPYRIGHT_YEAR=app.config['COPYRIGHT_YEAR'] or None, tz_label=app.config.get('TZ_LABEL', 'IST'),
                    unread=S.unread_count(current_user.id) if current_user.is_authenticated else 0)

    @app.errorhandler(413)
    def too_big(e):
        msg = f"Upload too large (max {app.config['MAX_IMAGE_MB']} MB per photo, {app.config['VIDEO_MAX_MB']} MB per video)."
        if request.path.startswith(('/upload', '/ai')):
            return jsonify(error=msg), 413
        flash(msg, 'danger'); return redirect(request.referrer or '/')

    for code, text in ((400, 'Bad request'), (403, "You don't have access to this page"), (404, 'Page not found')):
        app.register_error_handler(code, lambda e, code=code, text=text: (render_template('errors/error.html', code=code, text=text, detail=getattr(e, 'description', '')), code))

    with app.app_context():
        import models  # noqa: F401  (registers all tables)
        db.create_all()
        bootstrap(app)
    return app

def bootstrap(app):
    """First-run data: default departments and the first administrator (from .env). Citizens can never become admins by registering."""
    from models.user import User
    from models.complaint import Department
    for name in app.config['DEPARTMENTS']:
        if not Department.query.filter_by(name=name).first():
            db.session.add(Department(name=name))
    if not User.query.filter_by(role='admin').first():
        a = User(name='Administrator', email=app.config['ADMIN_EMAIL'].lower(), role='admin')
        a.set_password(app.config['ADMIN_PASSWORD'])
        db.session.add(a)
    db.session.commit()

if __name__ == '__main__':
    create_app().run(debug=True, port=5004)
