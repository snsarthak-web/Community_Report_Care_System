"""Demo data for the dashboards: python seed_demo.py
Creates demo citizens (password Demo@12345) and about 40 complaints over the last 30 days."""
import random
from datetime import timedelta
from app import create_app
from extensions import db, utcnow
from models import User, Department, Complaint, StatusHistory
from services import complaint_service as S

app = create_app()
with app.app_context():
    cfg = app.config
    users = []
    for i, n in enumerate(['Demo Citizen', 'Asha Verma', 'Ravi Kumar', 'Sneha Patel', 'Imran Khan']):
        email = 'demo@crc.local' if i == 0 else f"{n.split()[0].lower()}@crc.local"
        u = User.query.filter_by(email=email).first()
        if not u:
            u = User(name=n, email=email, phone=f'90000000{i:02d}', role='citizen'); u.set_password('Demo@12345'); db.session.add(u); db.session.commit()
        users.append(u)
    admin = User.query.filter_by(role='admin').first()
    depts = Department.query.all()
    places = ['Main Road', 'Market Chowk', 'Station Road', 'Ward 12', 'Temple Street', 'Bus Stand']
    for _ in range(40):
        owner = random.choice(users)
        tid = S.create(owner, dict(category=random.choice(cfg['CATEGORIES'][:6]), description='Demo complaint', method=random.choice(['ai', 'manual']),
                                   location_text=random.choice(places), lat=20.27 + random.uniform(-.06, .06), lng=85.84 + random.uniform(-.06, .06)))
        c = S.get_by_tid(tid)
        for v in random.sample([u for u in users if u.id != owner.id], random.choice([0, 0, 1, 2, 4])):
            S.vote(c, v.id)
        days = random.randint(0, 29)
        c.created_at = utcnow() - timedelta(days=days)
        for h in c.history:
            h.created_at = c.created_at
        path = random.choice([[], [], ['Under Review'], ['Under Review', 'Assigned'], ['Under Review', 'Assigned', 'In Progress'], ['Under Review', 'Assigned', 'In Progress', 'Resolved']])
        prev = 'Submitted'
        for k, st in enumerate(path):
            when = utcnow() - timedelta(days=max(0, days - k - 1))
            db.session.add(StatusHistory(complaint_id=c.id, old_status=prev, new_status=st, note=f'Moved to {st}', updated_by=admin.id, created_at=when))
            prev = st
            if st == 'Resolved':
                c.resolved_at = when
        c.status = prev
        if path:
            c.department = random.choice(depts)
    db.session.commit()
    print('Seeded 40 demo complaints.\nCitizen login: demo@crc.local / Demo@12345\nAdmin login (/admin/login):', cfg['ADMIN_EMAIL'], '/', cfg['ADMIN_PASSWORD'])
