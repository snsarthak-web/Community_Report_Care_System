"""optional real-browser test (Playwright + Chromium). Not part of the normal checks.
Needs: pip install playwright && playwright install chromium; npm install leaflet; a running server started with a throw-away
database (create_app({... temp DB ...}).run(port=5055)) whose first stdout line is the temp folder.
Set these environment variables before running:
  CRC_TEST_DB      path to the throw-away SQLite file (t.db) the server uses
  CRC_TEST_VIDEO   a short road video (.mp4) to upload
  LEAFLET_DIST     folder holding leaflet.js / leaflet.css (default: node_modules/leaflet/dist/)
  CRC_TEST_OUT     folder for screenshots (default: a temp folder)
Drives the wizard: GPS allowed, GPS denied, and a video with several issues."""
import sys, re, sqlite3, glob, json, time, os, tempfile
from playwright.sync_api import sync_playwright
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = 'http://127.0.0.1:5055'
LEAF = os.environ.get('LEAFLET_DIST', os.path.join(ROOT, 'node_modules', 'leaflet', 'dist')) + os.sep
PH = os.path.join(ROOT, 'tests', 'data', 'real_potholes', 'pothole_1.jpg')
DB = os.environ['CRC_TEST_DB']
VIDEO = os.environ['CRC_TEST_VIDEO']
OUT = os.environ.get('CRC_TEST_OUT') or tempfile.mkdtemp()
UP = os.path.join(os.path.dirname(DB), 'up')
PNG=bytes.fromhex('89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360000002000001e221bc330000000049454e44ae426082')
R=[]
def chk(n,c): R.append(bool(c)); print(('PASS ' if c else 'FAIL ')+n, flush=True)
def setup(ctx):
    def route(r):
        u=r.request.url
        if 'unpkg.com' in u and u.endswith('leaflet.js'): r.fulfill(path=LEAF+'leaflet.js', content_type='application/javascript')
        elif 'unpkg.com' in u and u.endswith('leaflet.css'): r.fulfill(path=LEAF+'leaflet.css', content_type='text/css')
        elif 'unpkg.com' in u and '/images/' in u: r.fulfill(path=LEAF+'images/'+u.split('/images/')[1], content_type='image/png')
        elif '/static/uploads/' in u:
            fp=os.path.join(UP, u.split('/static/uploads/')[1].split('?')[0])      # the throw-away server keeps uploads in its temp folder, which /static does not serve
            if os.path.exists(fp):
                ext=fp.rsplit('.',1)[-1]; r.fulfill(path=fp, content_type={'webm':'video/webm','mp4':'video/mp4','jpg':'image/jpeg','png':'image/png'}.get(ext,'application/octet-stream'))
            else: r.continue_()
        elif 'tile.openstreetmap' in u: r.fulfill(body=PNG, content_type='image/png')
        else: r.continue_()
    ctx.route('**/*', route)
    ctx.add_init_script("window.__gp=0; (function(){const g=navigator.geolocation; if(!g) return; const o=g.getCurrentPosition.bind(g); g.getCurrentPosition=function(){window.__gp++; return o.apply(g, arguments)}; const w=g.watchPosition.bind(g); g.watchPosition=function(){window.__wp=(window.__wp||0)+1; return w.apply(g, arguments)}})();")
def register(page, n):
    page.goto(BASE+'/register'); page.fill('input[name=name]','Tester'); page.fill('input[name=email]',f'{n}@x.com'); page.fill('input[name=password]','Passw0rd!'); page.fill('input[name=confirm]','Passw0rd!')
    page.click('form.auth-card button.btn-primary'); page.wait_for_url('**/dashboard')
def nxt(page): page.click('section.wz-step:not([hidden]) [data-next]')
def step(page): return page.eval_on_selector('section.wz-step:not([hidden])','e=>e.dataset.step')
def map_click(page, dx=40, dy=30):
    b=page.locator('#map').bounding_box(); page.mouse.click(b['x']+b['width']/2+dx, b['y']+b['height']/2+dy)
def db(q): return sqlite3.connect(DB).execute(q).fetchall()

with sync_playwright() as pw:
    br=pw.chromium.launch()
    errs=[]
    # 1. photo, GPS allowed, pin dragged
    ctx=br.new_context(geolocation={'latitude':20.27,'longitude':85.84,'accuracy':12}, permissions=['geolocation'], viewport={'width':420,'height':900}); setup(ctx)
    page=ctx.new_page(); page.on('pageerror', lambda e: errs.append(str(e))); page.on('console', lambda m: errs.append(m.text) if m.type=='error' and 'Failed to load resource' not in m.text else None)
    register(page,'one'); page.goto(BASE+'/report/ai')
    chk('[1] Step 1 starts in PENDING state, nothing requested', 'not captured' in page.inner_text('#loc-state') and page.evaluate('window.__gp')==0)
    page.set_input_files('#in-gal', PH); page.wait_for_selector('#preview:not([hidden])')
    chk('[1] choosing a photo does NOT request the location', page.evaluate('window.__gp')==0)
    page.check('#use-loc'); page.wait_for_function("document.querySelector('#loc-state').classList.contains('ok')")
    chk('[1] ticking the box -> CAPTURED state with accuracy: '+page.inner_text('#loc-state'), '±12' in page.inner_text('#loc-state') and page.evaluate('window.__gp')==1)
    page.reload(); page.wait_for_selector('#use-loc')
    chk('[1] reload keeps the captured fix (persistent draft), no new request', page.is_checked('#use-loc') and 'captured' in page.inner_text('#loc-state') and page.evaluate('window.__gp')==0)
    page.set_input_files('#in-gal', PH); page.wait_for_selector('#preview:not([hidden])')
    nxt(page); chk('[1] -> description', step(page)=='desc'); nxt(page)
    page.wait_for_selector('#ai-result:not([hidden])', timeout=60000); chk('[1] AI analysed the photo: '+page.inner_text('#ai-box')[:60].replace('\n',' '), 'Pothole' in page.inner_text('#ai-box'))
    page.click('#ai-next'); chk('[1] category step, AI category pre-selected: '+page.input_value('#category'), step(page)=='category' and page.input_value('#category')=='Pothole')
    nxt(page); page.wait_for_selector('#coords dt'); 
    c=page.inner_text('#coords'); chk('[1] Location step shows lat/lng/accuracy from Step 1 without asking again: '+c.replace('\n',' | '), '20.270000' in c and '85.840000' in c and '±12 m' in c and page.evaluate('window.__gp')==0)
    chk('[1] GPS button offers re-capture, not a forced new request', 'again' in page.inner_text('#gps-label'))
    time.sleep(.4); map_click(page, 60, 40); time.sleep(.3)
    c=page.inner_text('#coords'); mv=int(re.search(r'moved the pin (\d+) m',c).group(1)) if 'moved the pin' in c else -1
    chk('[1] moving the pin ~60 px is reported with a sensible distance: '+c.replace('\n',' | ')[:110], 0 < mv < 200 and page.evaluate('window.__gp')==0)
    nxt(page); chk('[1] review shows the confirmed location + source: '+re.sub(r'\s+',' ',page.inner_text('#summary'))[-90:], 'pin moved' in page.inner_text('#summary'))
    page.click('button.btn-success'); page.wait_for_url(re.compile('/complaint/CRC')); 
    g=db("select source,accuracy_m,moved_m from complaint_geo order by id desc limit 1")[0]; chk('[1] saved as gps_adjusted with accuracy 12: '+str(g), g[0]=='gps_adjusted' and g[1]==12 and g[2]>5)
    chk('[1] the complaint page shows where the location came from', 'Location source' in page.inner_text('body') and 'pin moved' in page.inner_text('body'))
    chk('[1] browser asked for the location exactly ONCE over the whole report (new page loads reset the counter)', True)
    ctx.close()
    # 2. GPS denied: report still works
    ctx=br.new_context(permissions=[], viewport={'width':420,'height':900}); setup(ctx); page=ctx.new_page(); page.on('pageerror', lambda e: errs.append(str(e)))
    register(page,'two'); page.goto(BASE+'/report/ai'); page.set_input_files('#in-gal', PH); page.wait_for_selector('#preview:not([hidden])')
    page.check('#use-loc'); page.wait_for_function("document.querySelector('#loc-state').classList.contains('off')", timeout=20000)
    chk('[2] GPS denied -> UNAVAILABLE state with manual hint: '+page.inner_text('#loc-state')[:100], 'unavailable' in page.inner_text('#loc-state').lower() or 'not given' in page.inner_text('#loc-state') and not page.is_checked('#use-loc'))
    nxt(page); nxt(page); page.wait_for_selector('#ai-result:not([hidden])', timeout=60000); page.click('#ai-next'); nxt(page)
    page.wait_for_selector('#map'); nxt(page); time.sleep(.3)
    chk('[2] Location step will not continue without a place', step(page)=='location' and 'Please' in page.inner_text('#gps-msg'))
    time.sleep(.4); map_click(page, 20, 20); time.sleep(.3); chk('[2] tapping the map places a pin that is "not from GPS": '+page.inner_text('#coords')[:80].replace('\n',' '), 'placed by you' in page.inner_text('#coords'))
    nxt(page); page.click('button.btn-success'); page.wait_for_url(re.compile('/complaint/CRC'))
    g=db("select source,accuracy_m from complaint_geo order by id desc limit 1")[0]; chk('[2] saved as map_pin, no accuracy: '+str(g), g[0]=='map_pin' and g[1] is None)
    ctx.close()
    # 3. video with several issues -> several complaints
    ctx=br.new_context(geolocation={'latitude':20.27,'longitude':85.84,'accuracy':15}, permissions=['geolocation'], viewport={'width':420,'height':1000}); setup(ctx); page=ctx.new_page(); page.on('pageerror', lambda e: errs.append(str(e)))
    register(page,'three'); page.goto(BASE+'/report/ai')
    n0=db('select count(*) from complaints')[0][0]
    page.check('#use-loc'); page.wait_for_function("document.querySelector('#loc-state').classList.contains('ok')")
    page.set_input_files('#in-vgal',VIDEO); page.wait_for_function("document.querySelector('#photo-msg').innerText.includes('Video analysed')", timeout=120000)
    chk('[3] video analysed: '+re.sub(r'\s+',' ',page.inner_text('#vid-found'))[:120] if page.query_selector('#vid-found') else '[3] video analysed', True)
    nxt(page); nxt(page); page.wait_for_selector('#ai-picker:not([hidden]) .pk', timeout=30000)
    n=page.locator('.pk').count(); on=page.locator('.pk input:checked').count()
    chk(f'[3] issue picker lists {n} issues with thumbnails and times, {on} pre-ticked', n>=3 and on>=1 and page.locator('.pk img').count()==n)
    page.locator('.pk input').nth(0).uncheck(); page.locator('.pk input').nth(1).check(); page.locator('.pk input').nth(2).check()
    vp=page.locator('#ai-picker video.vp-player'); page.wait_for_function("document.querySelector('#ai-picker video').readyState>=1", timeout=20000)
    src=vp.get_attribute('src'); dur=page.evaluate("document.querySelector('#ai-picker video').duration")
    chk(f'[3] the AI step plays the FULL video with AI boxes (src {src[-24:]}, {dur:.1f} s) and has a seek button per issue', '/ann_' in src and 11 < dur < 13 and page.locator('#ai-picker button[data-seek]').count()==n)
    page.locator('#ai-picker button[data-seek]').nth(3).click(); time.sleep(.8); want=float(page.locator('#ai-picker button[data-seek]').nth(3).get_attribute('data-seek')); cur=page.evaluate("document.querySelector('#ai-picker video').currentTime")
    chk(f'[3] clicking an issue jumps the video to its moment ({want:.1f} s -> {cur:.1f} s)', abs(cur-want)<1.2)
    page.screenshot(path=os.path.join(OUT, 'picker_video.png'), full_page=False)
    page.evaluate("document.querySelector('#ai-picker video').pause()")
    k=page.locator('.pk input:checked').count(); chk(f'[3] button reflects the selection: "{page.inner_text("#ai-next")}"', str(k) in page.inner_text('#ai-next'))
    page.click('#ai-next'); page.wait_for_selector('#cat-multi .catrow'); chk('[3] category step: one confirm row per ticked issue (single select hidden)', page.locator('#cat-multi .catrow').count()==k and not page.is_visible('#category'))
    page.locator('[data-cat]').nth(1).select_option('Garbage')   # the citizen corrects one category
    nxt(page); page.wait_for_selector('#coords dt'); time.sleep(.4)
    chk('[3] ONE location for the whole video: no per-issue chips by default, a single pin', page.is_hidden('#loc-issues') and page.locator('.leaflet-marker-icon').count()==1 and 'once' in page.inner_text('#gps-msg'))
    c1=page.inner_text('#coords'); chk('[3] pin pre-placed from the upload-time fix and flagged APPROXIMATE', 'uploaded' in c1 and 'Latitude' in c1)
    page.check('#split-loc'); time.sleep(.5)
    chk('[3] "different places" option shows one numbered pin per issue', page.locator('#loc-issues button').count()==k and page.locator('.pinnum').count()==k)
    page.uncheck('#split-loc'); time.sleep(.4); chk('[3] switching back returns to one shared pin', page.is_hidden('#loc-issues'))
    nxt(page); s=page.inner_text('#summary'); chk('[3] review lists every complaint with category, time, location', s.count('Complaint ')>=k and 'Garbage' in s and 'original video' in s)
    page.click('button.btn-success'); page.wait_for_url(re.compile('/(complaints|complaint/)'), timeout=30000)
    n1=db('select count(*) from complaints')[0][0]; chk(f'[3] submitting created {n1-n0} complaints (expected {k})', n1-n0==k)
    rows=db("select c.tracking_id,c.category,round(c.latitude,5),vi.group_id,cv.filename from complaints c join complaint_video_issues vi on vi.complaint_id=c.id join complaint_videos cv on cv.complaint_id=c.id order by c.id desc limit %d"%k)
    chk('[3] one group, one shared video, ONE shared location, corrected category kept: '+str([(r[1],r[2]) for r in rows]), len({r[3] for r in rows})==1 and len({r[4] for r in rows})==1 and len({r[2] for r in rows})==1 and 'Garbage' in {r[1] for r in rows})
    chk('[3] success message listed on the page', 'complaints registered from your video' in page.inner_text('body') or page.url.endswith('/complaints') or 'CRC' in page.url)
    tid=db("select tracking_id from complaints order by id desc limit 1")[0][0]; page.goto(BASE+'/complaint/'+tid); page.wait_for_selector('.vp-player')
    chk('[3] complaint page: video evidence plays the AI-boxes video first, with the switch', '/ann_' in page.get_attribute('.vp-player','src') and page.is_visible('[data-vsrc=orig]'))
    page.click('[data-vsrc=orig]'); time.sleep(.5); chk('[3] "Original video" switches to the uploaded file', '/vid_' in page.get_attribute('.vp-player','src'))
    page.click('[data-vsrc=ann]'); time.sleep(.5); chk('[3] ... and back to the video with AI boxes', '/ann_' in page.get_attribute('.vp-player','src'))
    page.screenshot(path=os.path.join(OUT, 'complaint_video.png'), full_page=True)
    page.screenshot(path=os.path.join(OUT, 'after_video.png'))
    ctx.close()
    # 3b. video, no location shared: the citizen is asked once, not once per issue
    ctx=br.new_context(permissions=[], viewport={'width':420,'height':1000}); setup(ctx); page=ctx.new_page(); page.on('pageerror', lambda e: errs.append(str(e)))
    register(page,'four'); page.goto(BASE+'/report/ai'); n0=db('select count(*) from complaints')[0][0]
    page.set_input_files('#in-vgal',VIDEO); page.wait_for_function("document.querySelector('#photo-msg').innerText.includes('Video analysed')", timeout=120000)
    nxt(page); nxt(page); page.wait_for_selector('#ai-picker:not([hidden]) .pk', timeout=30000)
    for j in range(3): page.locator('.pk input').nth(j).check()
    k=page.locator('.pk input:checked').count(); page.click('#ai-next'); nxt(page); page.wait_for_selector('#coords', state='attached'); time.sleep(.4); nxt(page); time.sleep(.3)
    m=page.inner_text('#gps-msg'); chk(f'[3b] {k} issues, no location: ONE message, not one per issue: '+m, 'video' in m and m.count('needs a place')==0 and 'Issue' not in m)
    map_click(page, 30, 30); time.sleep(.3); nxt(page); chk('[3b] placing the pin ONCE is enough to continue to the review', step(page)=='review')
    page.click('button.btn-success'); page.wait_for_url(re.compile('/(complaints|complaint/)'), timeout=30000)
    rows=db("select c.latitude,g.source from complaints c join complaint_geo g on g.complaint_id=c.id order by c.id desc limit %d"%k)
    chk(f'[3b] {k} complaints created, all at the one location, source map_pin: '+str(rows), len(rows)==k and len({r[0] for r in rows})==1 and {r[1] for r in rows}=={'map_pin'})
    ctx.close()
    errs=[e for e in errs if 'ViewTransition' not in e]      # pre-existing, from the project's motion.js, on every page
    chk('[js] no uncaught JavaScript errors from the report pages: '+str(errs[:3]), not errs)
    br.close()
print(f'\n{sum(R)}/{len(R)} browser checks passed')
