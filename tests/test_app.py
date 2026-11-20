"""Run this after `pip install -r requirements.txt`:   python tests/test_app.py
It uses a throw-away database and exercises the real Flask-SQLAlchemy + Flask-Login stack."""
import io, os, re, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from PIL import Image
from app import create_app

tmp = tempfile.mkdtemp()
app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + os.path.join(tmp, 't.db').replace('\\', '/'),
                  'DB_PATH': os.path.join(tmp, 't.db'), 'UPLOAD_FOLDER': os.path.join(tmp, 'up'), 'AI_RESULTS_DIR': os.path.join(tmp, 'results'), 'AI_MODELS_DIR': os.path.join(tmp, 'no_models'), 'ADMIN_EMAIL': 'boss@crc.local', 'ADMIN_PASSWORD': 'BossPassw0rd!'})
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
RES = []
def chk(name, cond):
    RES.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name)
def tok(c):
    with c.session_transaction() as s: return s.get('csrf')
def client():
    c = app.test_client(); c.get('/login'); return c
def fresh(c):                       # a real browser loads a page after login, which creates a new CSRF token
    c.get('/', follow_redirects=True); return tok(c)      # follow the redirect like a browser: the page it lands on mints the CSRF token
def txt(r): return r.get_data(as_text=True)
def png(): b = io.BytesIO(); Image.new('RGB', (300, 200), (120, 90, 60)).save(b, 'PNG'); b.seek(0); return (b, 'a.png')
def reg(c, name, email, pw='Passw0rd!', phone=''):
    return c.post('/register', data=dict(name=name, email=email, password=pw, confirm=pw, phone=phone, csrf_token=tok(c)))

A, B, ADM = client(), client(), client()
chk('landing has Admin Login link in footer', 'Admin Login' in txt(app.test_client().get('/')))
chk('register A', reg(A, 'Asha', 'a@x.com', phone='9876543210').status_code == 302); chk('register B', reg(B, 'Bob', 'b@x.com').status_code == 302)
chk('duplicate email rejected', 'already exists' in txt(reg(client(), 'Z', 'a@x.com')))
H0 = client(); H0.post('/register', data=dict(name='Hacker', email='h@x.com', password='Passw0rd!', confirm='Passw0rd!', role='admin', csrf_token=tok(H0)))
with app.app_context():
    from models import User
    chk('role cannot be forced to admin through the register form', User.query.filter_by(email='h@x.com').first().role == 'citizen')
c = client(); c.post('/login', data=dict(email='a@x.com', password='bad', csrf_token=tok(c))); chk('bad login stays out', c.get('/dashboard').status_code == 302)
chk('POST without CSRF blocked', app.test_client().post('/login', data=dict(email='a@x.com', password='x')).status_code == 400)
chk('anon dashboard redirects to login', '/login' in app.test_client().get('/dashboard').headers['Location'])
chk('anon admin redirects to ADMIN login', '/admin/login' in app.test_client().get('/admin/').headers['Location'])
for u in ['/dashboard', '/report', '/report/ai', '/report/manual', '/complaints', '/complaints?view=supported', '/track', '/map', '/notifications', '/profile']:
    chk(f'citizen GET {u}', A.get(u).status_code == 200)

# lockout after repeated failures
L = client()
for _ in range(5): L.post('/login', data=dict(email='lock@x.com', password='nope', csrf_token=tok(L)))
chk('lock-out after 5 failures', 'Too many failed attempts' in txt(L.post('/login', data=dict(email='lock@x.com', password='nope', csrf_token=tok(L)))))

# OTP login (kept from v1.0)
O = client(); r = O.post('/login/otp', data=dict(phone='9811111111', name='Otp User', csrf_token=tok(O)))
with O.session_transaction() as s: code = s['otp']['code']
chk('OTP page shows code', code in re.sub(r'<[^>]+>', '', txt(O.get('/login/otp/verify'))))      # the code is rendered as one <span> per digit
wrong = '111111' if code == '000000' else '000000'
chk('wrong OTP rejected', 'Wrong code' in txt(O.post('/login/otp/verify', data=dict(otp=wrong, csrf_token=tok(O)))))
chk('right OTP logs in (creates phone-only account)', O.post('/login/otp/verify', data=dict(otp=code, csrf_token=tok(O))).status_code == 302 and O.get('/dashboard').status_code == 200)
O2 = client(); O2.post('/login/otp', data=dict(phone='9876543210', csrf_token=tok(O2)))
with O2.session_transaction() as s: code2 = s['otp']['code']
O2.post('/login/otp/verify', data=dict(otp=code2, csrf_token=tok(O2))); chk('OTP logs in existing email account by saved phone', 'Asha' in txt(O2.get('/dashboard')))

# uploads
H = {'X-CSRFToken': tok(A)}
r = A.post('/upload/photo', data={'photo': png()}, headers=H, content_type='multipart/form-data'); chk('upload valid png', r.status_code == 200); ph = r.json['photo_name']
chk('upload txt rejected', A.post('/upload/photo', data={'photo': (io.BytesIO(b'hi'), 'x.txt')}, headers=H, content_type='multipart/form-data').status_code == 400)
chk('fake image rejected', A.post('/upload/photo', data={'photo': (io.BytesIO(b'nope'), 'x.png')}, headers=H, content_type='multipart/form-data').status_code == 400)
r = A.post('/ai/detect', json={'photo_name': ph}, headers=H); chk('AI detect without model degrades gracefully', r.status_code == 200 and r.json['status'] == 'no_model')
chk('detect blocks path traversal', A.post('/ai/detect', json={'photo_name': '../../etc/passwd'}, headers=H).status_code == 400)

# reporting
det = {'label': 'pothole', 'confidence': 0.91, 'boxes': [{'label': 'pothole', 'confidence': .91, 'x': .1, 'y': .1, 'w': .4, 'h': .3}], 'annotated': None, 'model_name': 'best.pt'}
with A.session_transaction() as s: s['ai_results'] = {ph: det}
for fn in os.listdir(app.config['AI_RESULTS_DIR']):      # the earlier no-model /ai/detect call stored a result for this photo; this test injects its own
    os.remove(os.path.join(app.config['AI_RESULTS_DIR'], fn))
form = lambda **k: dict(dict(category='Pothole', description='', lat='20.2700', lng='85.8400', location_text='Main Rd', photo_name=ph, csrf_token=tok(A)), **k)
r = A.post('/report/ai', data=form()); tid = r.headers['Location'].split('/')[-1]; chk('AI report created ' + tid, r.status_code == 302 and tid.startswith('CRC-'))
chk('detail shows AI detection', 'AI detected' in txt(A.get('/complaint/' + tid)))
chk('AI mode needs a photo', 'photo is required' in txt(A.post('/report/ai', data=form(photo_name=''), follow_redirects=True)))
chk('invalid category rejected', 'choose a category' in txt(A.post('/report/manual', data=form(category='Hack'), follow_redirects=True)))
chk('manual report, no photo, landmark only', A.post('/report/manual', data=dict(category='Garbage', location_text='Near school', csrf_token=tok(A))).status_code == 302)

# duplicates, voting, privacy
chk('nearby warns B', len(B.get('/api/nearby?category=Pothole&lat=20.2701&lng=85.8401').json) == 1)
chk('B cannot view A complaint (404)', B.get('/complaint/' + tid).status_code == 404)
vh = lambda c: {'X-CSRFToken': tok(c)}
chk('B votes', B.post(f'/complaint/{tid}/vote', json={}, headers=vh(B)).json['ok'])
chk('B cannot vote twice', not B.post(f'/complaint/{tid}/vote', json={}, headers=vh(B)).json['ok'])
chk('owner cannot vote own', not A.post(f'/complaint/{tid}/vote', json={}, headers=vh(A)).json['ok'])
chk('B can view after voting', B.get('/complaint/' + tid).status_code == 200)
for i in range(3):
    c = client(); reg(c, f'U{i}', f'u{i}@x.com'); fresh(c); c.post(f'/complaint/{tid}/vote', json={}, headers=vh(c))
chk('5 supporters -> Critical', 'Critical' in txt(A.get('/complaint/' + tid)))

# admin portal
chk('citizen cannot use admin login', 'Incorrect' in txt(ADM.post('/admin/login', data=dict(email='a@x.com', password='Passw0rd!', csrf_token=tok(ADM)))))
AC = client(); chk('admin cannot use the citizen login page', 'Admin Portal' in txt(AC.post('/login', data=dict(email='boss@crc.local', password='BossPassw0rd!', csrf_token=tok(AC)))))
r = ADM.post('/admin/login', data=dict(email='boss@crc.local', password='BossPassw0rd!', csrf_token=tok(ADM))); chk('admin login ok', r.status_code == 302)
fresh(ADM)
for u in ['/admin/', '/admin/?days=7', '/admin/complaints', '/admin/complaints?status=Submitted&category=Pothole&from=2020-01-01&q=CRC', '/admin/ai-review', '/admin/ai-review?v=pending', '/admin/map',
          '/admin/departments', '/admin/votes', '/admin/notifications', '/admin/reports', '/admin/reports?days=7', '/admin/users', '/admin/settings', '/admin/complaint/' + tid, '/admin/complaints/export.csv']:
    chk(f'admin GET {u}', ADM.get(u).status_code == 200)
chk('CSV export contains complaint', tid in txt(ADM.get('/admin/complaints/export.csv')))
chk('citizen blocked from admin (403)', A.get('/admin/').status_code == 403 and A.get('/admin/complaints').status_code == 403 and A.get('/admin/users').status_code == 403)
chk('citizen cannot POST admin update', A.post('/admin/complaint/' + tid, data=dict(status='Resolved', csrf_token=tok(A))).status_code == 403)
upd = lambda **k: ADM.post('/admin/complaint/' + tid, data=dict(dict(status='Assigned', category='Pothole', department_id='1', officer='R. Sharma', priority='High', note='Crew assigned', verdict='1', csrf_token=tok(ADM)), **k), content_type='multipart/form-data', follow_redirects=True)
chk('admin assigns', 'updated' in txt(upd()))
page = txt(A.get('/complaint/' + tid)); chk('citizen sees status, note, dept, officer', 'Assigned' in page and 'Crew assigned' in page and 'Roads' in page and 'R. Sharma' in page)
chk('owner and voter notified', 'assigned to' in txt(A.get('/notifications')) and 'assigned to' in txt(B.get('/notifications')))
chk('resolving needs an after-repair photo', 'after-repair photo' in txt(upd(status='Resolved')))
chk('resolve with photo', 'updated' in txt(upd(status='Resolved', evidence=png())))
page = txt(A.get('/complaint/' + tid)); chk('citizen sees BEFORE and AFTER + feedback form', 'After repair' in page and 'Was the problem really fixed' in page)
chk('citizen disputes -> re-opened', A.post(f'/complaint/{tid}/feedback', data=dict(answer='not_fixed', note='still a hole', csrf_token=tok(A))).status_code == 302 and 'Under Review' in txt(A.get('/complaint/' + tid)))
chk('admin alerted about dispute', 'NOT fixed' in txt(ADM.get('/admin/notifications')))
import html as _html
chk('audit log records who changed what', 'officer -> R. Sharma' in _html.unescape(txt(ADM.get('/admin/settings'))))
chk('AI performance visible', 'AI performance' in txt(ADM.get('/admin/ai-review')))
chk('admin creates new admin', 'created' in txt(ADM.post('/admin/settings', data=dict(action='new_admin', name='Second', email='second@crc.local', new='SecondPass123', old='BossPassw0rd!', csrf_token=tok(ADM)), follow_redirects=True)))
chk('admin deactivates Bob', 'deactivated' in txt(ADM.post('/admin/users/3/toggle', data=dict(csrf_token=tok(ADM)), follow_redirects=True)))
chk('deactivated user is logged out at once', B.get('/dashboard').status_code == 302)

# dashboards use real data
with app.app_context():
    from services import complaint_service as S
    from models import User
    d = S.citizen_dashboard(User.query.filter_by(email='a@x.com').first().id, 14)
    chk('citizen dashboard numbers match DB', d['s']['total'] == 2 and sum(d['trend']['reported']) == 2)
chk('logout works', A.get('/logout').status_code == 302 and A.get('/dashboard').status_code == 302)
chk('404 page', app.test_client().get('/nope').status_code == 404)
print(f"\n{sum(RES)}/{len(RES)} passed"); sys.exit(0 if all(RES) else 1)
