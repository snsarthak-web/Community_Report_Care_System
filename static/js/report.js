/* Report wizard: photo -> description -> (AI) -> category -> location -> review -> submit */
(function () {
  const f = document.getElementById('rf'); if (!f) return;
  const $ = id => document.getElementById(id), $$ = s => [...document.querySelectorAll(s)];
  const csrf = document.querySelector('meta[name=csrf-token]').content, mode = f.dataset.mode;
  const ORDER = mode === 'ai' ? ['photo', 'desc', 'ai', 'category', 'location', 'review'] : ['category', 'photo', 'desc', 'location', 'review'];
  const LABEL = { photo: 'Photograph', desc: 'Description', ai: 'AI detection', category: 'Category', location: 'Location', review: 'Review' };
  const steps = {}; $$('.wz-step').forEach(e => steps[e.dataset.step] = e);
  const MAXMB = 8, OK = ['image/jpeg', 'image/png', 'image/webp'];
  let idx = 0, photoUrl = null, ai = null, videoAI = null;
  let multi = false, selFor = null, sel = {}, issuesById = {};      // multi: a video with detected issues -> one complaint per ticked issue          // videoAI: finished video analysis (see video.js); it replaces the photo AI call

  function show(name) {
    idx = ORDER.indexOf(name);
    ORDER.forEach(k => steps[k].hidden = k !== name);
    $('wz-fill').style.width = ((idx + 1) / ORDER.length * 100) + '%';
    $('wz-label').textContent = `Step ${idx + 1} of ${ORDER.length}: ${LABEL[name]}`;
    if (name === 'category') renderCats();
    if (name === 'location') enterLocation();
    if (name === 'review') review();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }
  const msg = (el, text, cls = '') => { el.className = 'note ' + cls; el.textContent = text; };

  /* photo: camera + gallery */
  const cam = $('in-cam'), gal = $('in-gal');
  /* one pipeline for every source (live camera, phone camera app, gallery): validate -> preview -> upload to the server */
  async function handleFile(file) {
    if (!file) return;
    if (!OK.includes(file.type)) return msg($('photo-msg'), 'Unsupported format. Please use a JPG, PNG or WEBP photo.', 'err');
    if (file.size > MAXMB * 1048576) return msg($('photo-msg'), `Photo is too large (max ${MAXMB} MB).`, 'err');
    $('pimg').src = photoUrl = URL.createObjectURL(file); $('preview').hidden = false; $('photo_name').value = ''; ai = null; clearVideo();
    msg($('photo-msg'), 'Uploading…');
    const fd = new FormData(); fd.append('photo', file);
    try {
      const r = await fetch(f.dataset.upload, { method: 'POST', body: fd, headers: { 'X-CSRFToken': csrf } }), d = await r.json();
      if (!r.ok) { $('preview').hidden = true; $('photo_name').value = ''; return msg($('photo-msg'), d.error || 'Upload failed.', 'err'); }
      $('photo_name').value = d.photo_name; msg($('photo-msg'), 'Photo ready ✓', 'ok');
    } catch (e) { $('preview').hidden = true; msg($('photo-msg'), 'Upload failed. Check your connection and try again.', 'err'); }
  }
  [cam, gal].forEach(inp => inp.addEventListener('change', () => { const file = inp.files[0]; inp.value = ''; handleFile(file); }));
  ['btn-gal', 're-gal'].forEach(id => $(id).onclick = () => gal.click());

  /* ---- live camera: opens the camera straight away (getUserMedia). If the browser cannot (needs https or localhost),
          fall back to the device's native camera input (capture="environment"). ---- */
  const dlg = $('camx'), vid = $('camx-v'), cmsg = $('camx-msg'), shot = $('camx-shot');
  let stream = null, facing = 'environment', lastBtn = null;
  const canLive = () => !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.isSecureContext);
  function stopCam() { if (stream) { stream.getTracks().forEach(t => t.stop()); stream = null; } vid.srcObject = null; }
  function closeCam() { stopCam(); dlg.hidden = true; document.body.classList.remove('camx-open'); if (lastBtn && lastBtn.focus) lastBtn.focus(); }
  async function startCam() {
    stopCam(); cmsg.textContent = 'Starting camera…'; cmsg.hidden = false; shot.disabled = true;
    try {
      const s = await navigator.mediaDevices.getUserMedia({ audio: false, video: { facingMode: { ideal: facing }, width: { ideal: 1920 }, height: { ideal: 1080 } } });
      if (dlg.hidden) { s.getTracks().forEach(t => t.stop()); return; }          // closed while the permission prompt was open
      stream = s; vid.srcObject = s; vid.classList.toggle('mirror', facing === 'user'); await vid.play();
      cmsg.hidden = true; shot.disabled = false; shot.focus();
      navigator.mediaDevices.enumerateDevices().then(d => { $('camx-flip').hidden = d.filter(x => x.kind === 'videoinput').length < 2; }).catch(() => {});
    } catch (e) {
      closeCam();
      const why = e && e.name === 'NotAllowedError' ? 'Camera access was blocked. Allow it in your browser settings, or use Upload Photo.'
        : e && e.name === 'NotFoundError' ? 'No camera was found on this device. Use Upload Photo instead.' : 'The camera could not be started. Use Upload Photo instead.';
      msg($('photo-msg'), why, 'warn');
    }
  }
  function openCam(ev) {
    lastBtn = ev && ev.currentTarget;
    if (!canLive()) { cam.click(); return; }                                       // phone camera app / older browsers
    dlg.hidden = false; document.body.classList.add('camx-open'); $('camx-x').focus(); startCam();
  }
  ['btn-cam', 're-cam'].forEach(id => $(id).onclick = openCam);
  $('camx-x').onclick = closeCam;
  $('camx-flip').onclick = () => { facing = facing === 'environment' ? 'user' : 'environment'; startCam(); };
  $('camx-gal').onclick = () => { closeCam(); gal.click(); };
  dlg.addEventListener('click', e => { if (e.target === dlg) closeCam(); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && !dlg.hidden) { e.preventDefault(); closeCam(); } });   // works wherever focus is
  dlg.addEventListener('keydown', e => {
    if (e.key === 'Tab') { const f = [...dlg.querySelectorAll('button:not([disabled]):not([hidden])')]; if (!f.length) return; const i = f.indexOf(document.activeElement);
      if (e.shiftKey && i <= 0) { e.preventDefault(); f[f.length - 1].focus(); } else if (!e.shiftKey && i === f.length - 1) { e.preventDefault(); f[0].focus(); } }
  });
  shot.onclick = () => {
    if (!vid.videoWidth) return;
    const c = document.createElement('canvas'); c.width = vid.videoWidth; c.height = vid.videoHeight; c.getContext('2d').drawImage(vid, 0, 0, c.width, c.height);
    const fl = $('camx-flash'); fl.classList.remove('go'); void fl.offsetWidth; fl.classList.add('go');
    c.toBlob(b => { if (!b) return msg($('photo-msg'), 'Could not capture the photo. Please try again.', 'err'); closeCam(); handleFile(new File([b], 'camera-' + Date.now() + '.jpg', { type: 'image/jpeg' })); }, 'image/jpeg', 0.9);
  };

  /* description: add / skip */
  const seg = $$('[data-desc]');
  seg.forEach(b => b.onclick = () => { seg.forEach(x => x.classList.remove('on')); b.classList.add('on');
    const add = b.dataset.desc === 'add'; $('descbox').hidden = !add; if (add) $('description').focus(); else $('description').value = ''; });

  /* everything the AI found: several issues, doubts, which models ran, times (video), every detection. Nothing is hidden. */
  const mmss = t => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, '0')}`;
  function findings(d) {
    let h = '';
    const issues = d.issues || [], why = (d.reasons || []).filter(r => !/calibrated/i.test(r));
    if (d.needs_confirmation || issues.length > 1) {
      h += `<div class="note warn aiwarn"><b>Please check this suggestion.</b>${d.multiple_issues ? ' More than one kind of problem was found. A report covers one category: choose the main one now; the other findings are saved with your complaint and you can report them separately.' : ''}`
        + (why.length ? '<ul>' + why.map(r => `<li>${esc(r)}</li>`).join('') + '</ul>' : '') + '</div>';
    }
    if (issues.length) {
      h += '<div class="aimulti"><b>Issues found</b><ul>' + issues.map(i => `<li><span><b>${esc(i.category || 'Unclassified')}</b> · ${Math.round(i.score * 100)}% reliability${i.models && i.models.length ? ' · ' + i.models.length + ' model' + (i.models.length > 1 ? 's' : '') : ''}</span>`
        + (i.timestamps ? `<span class="mut">at ${i.timestamps.map(mmss).join(', ')} · seen in ${i.frames_seen} of ${i.frames_total} frames</span>` : '') + '</li>').join('') + '</ul></div>';
    }
    const preds = (d.predictions || []).filter(p => p.used);
    if (preds.length) {
      h += `<details class="aidet"><summary>All detections (${preds.length})</summary><div class="table-responsive"><table class="tbl"><thead><tr><th>Model</th><th>Found</th><th>Confidence</th>${d.source === 'video' ? '<th>Time</th>' : ''}</tr></thead><tbody>`
        + preds.map(p => `<tr><td>${esc(p.model_display || p.model)}</td><td>${esc(p.label)}${p.category ? ' → ' + esc(p.category) : ''}</td><td>${Math.round(p.confidence * 100)}%</td>${d.source === 'video' ? `<td>${mmss(p.timestamp_sec || 0)}</td>` : ''}</tr>`).join('') + '</tbody></table></div></details>';
    }
    if (d.source === 'video' && (d.frames || []).some(x => x.url)) {
      h += '<div class="aiframes"><b>Analysed frames</b><div>' + d.frames.filter(x => x.url).map(x => `<figure><a href="${esc(x.url)}" target="_blank" rel="noopener"><img src="${esc(x.url)}" alt="Annotated frame at ${mmss(x.t)}" loading="lazy"></a><figcaption>${mmss(x.t)} · ${esc(x.category || 'nothing found')}</figcaption></figure>`).join('') + '</div></div>';
    }
    if (d.models_total && d.models_available < d.models_total) h += `<p class="sm mut mb-0">AI models available: ${d.models_available} of ${d.models_total}.</p>`;
    return h;
  }

  /* hooks used by video.js (video evidence): it hands over the analysed video as if it were a photo + its AI result */
  function clearVideo() { videoAI = null; multi = false; selFor = null; sel = {}; const v = $('video_name'); if (v) v.value = ''; if (window.CRCVideo) window.CRCVideo.reset(); }
  window.CRCReport = {
    csrf, form: f, msg, mmss,
    locOn: () => !!($('use-loc') && $('use-loc').checked && navigator.geolocation && LOC.state !== 'unavailable'),
    getFix: () => (LOC.state === 'captured' ? { lat: LOC.lat, lng: LOC.lng, acc: LOC.acc } : null),
    useVideo(result, name) {                                       // result.photo_name = the video's best frame, stored server-side like any photo
      $('photo_name').value = result.photo_name; $('video_name').value = name; $('pimg').src = photoUrl = result.photo_url; $('preview').hidden = false;
      msg($('photo-msg'), 'Video analysed. The clearest frame is used as your photo ✓', 'ok'); videoAI = ai = result; delete pins.main;
    },
    dropVideo() { clearVideo(); $('photo_name').value = ''; $('preview').hidden = true; ai = null; msg($('photo-msg'), ''); },
  };

  /* AI detection (Flask -> ai/manager.py -> the five YOLO models) */
  async function runAI() {
    $('ai-loading').hidden = false; $('ai-result').hidden = true; $('ai-next').disabled = true; msg($('ai-loading'), 'Analysing your photo…');
    let d;
    if (videoAI && videoAI.photo_name === $('photo_name').value) d = videoAI;              // video: already analysed (all frames, all five models)
    else try { const r = await fetch(f.dataset.detect, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf }, body: JSON.stringify({ photo_name: $('photo_name').value }) }); d = await r.json(); if (!r.ok) throw 0; }
    catch (e) { d = { status: 'error' }; }
    ai = d; $('ai-loading').hidden = true; $('ai-result').hidden = false; $('ai-next').disabled = false;
    multi = d.source === 'video' && d.status === 'ok' && (d.issues || []).some(i => i.id && i.photo_url);
    $('ai-picker').hidden = !multi; $('ai-imgs').hidden = multi; $('cat-hint').hidden = true;
    if (multi) { initIssues(d); $('ai-foot').textContent = 'AI only suggests. Tick the issues that are real: each ticked issue becomes its own complaint, and the original video is kept as evidence for all of them.'; }
    else $('ai-foot').textContent = 'AI only suggests. You decide the final category on the next screen.';
    $('ai-orig').src = photoUrl; $('ai-annwrap').hidden = !(d.status === 'ok' && d.annotated_url); if (d.annotated_url) $('ai-ann').src = d.annotated_url;
    const box = $('ai-box'), hint = $('cat-hint');
    if (multi) {
      box.innerHTML = findings(d);
    } else if (d.status === 'ok') {
      const p = Math.round(d.confidence * 100);
      box.innerHTML = `<small class="mut">Detected issue</small><div class="big">${esc(d.label || d.category)}</div><div class="conf"><i style="width:${p}%"></i></div><small>Confidence: ${p}% · Suggested category: <b>${esc(d.category)}</b></small>` + findings(d);
      $('category').value = d.category; hint.hidden = false; hint.textContent = `${d.category} – suggested by AI (${p}%). Change it if it is wrong.`;
    } else {
      const t = d.status === 'none' ? `AI could not find a known civic issue in this ${d.source === 'video' ? 'video' : 'photo'}.` : d.status === 'no_model' ? 'The AI model is not available right now.' : 'AI analysis failed.';
      box.innerHTML = `<div class="note warn">${t} No problem: choose the category yourself on the next screen.</div>` + findings(d); hint.hidden = true;
    }
  }

  /* ================================================================ location
     one optional, user-chosen request (Step 1 checkbox). The result is kept in loc (+ sessionStorage, so a reload keeps it) and in hidden
     fields: later steps never ask the browser again unless the citizen presses the GPS button. Three states:
       captured    -> coordinates received, verify them on the map
       pending     -> not asked yet / still being obtained
       unavailable -> denied / no GPS: choose the place on the map (optional, never blocks the report)                                   */
  const LKEY = 'crc_loc_draft_v1', LOC = { state: 'pending', lat: null, lng: null, acc: null, ts: 0, msg: '', busy: false };
  const POOR = +f.dataset.poorAcc || 50;
  const store = { get() { try { return JSON.parse(sessionStorage.getItem(LKEY) || 'null'); } catch (e) { return null; } },
                  set(v) { try { v ? sessionStorage.setItem(LKEY, JSON.stringify(v)) : sessionStorage.removeItem(LKEY); } catch (e) { /* private mode */ } } };
  function drawLoc() {
    $$('.locstate').forEach(el => {
      const t = el.querySelector('span');
      if (LOC.state === 'captured') { el.className = 'locstate ok'; t.textContent = `Location captured ✓ (±${Math.round(LOC.acc || 0)} m). You can check it on the map in the Location step.`; }
      else if (LOC.state === 'unavailable') { el.className = 'locstate off'; t.textContent = (LOC.msg || 'Location unavailable') + ' You can choose the place on the map in the Location step (optional).'; }
      else { el.className = 'locstate pending'; t.textContent = LOC.busy ? 'Getting your location… allow the browser prompt.' : 'Location not captured yet (optional).'; }
    });
    const g = $('gps-label'); if (g) g.textContent = LOC.state === 'captured' ? 'Capture GPS again' : 'Use my GPS';
  }
  function requestFix() {                                            // only ever called by an explicit click / tick
    if (LOC.busy) return;
    if (!navigator.geolocation) { Object.assign(LOC, { state: 'unavailable', msg: 'GPS is not supported on this device.', busy: false }); store.set(LOC); return drawLoc(); }
    LOC.busy = true; drawLoc();
    navigator.geolocation.getCurrentPosition(p => {
      Object.assign(LOC, { state: 'captured', lat: p.coords.latitude, lng: p.coords.longitude, acc: p.coords.accuracy, ts: Date.now(), msg: '', busy: false });
      store.set(LOC); drawLoc(); if (ORDER[idx] === 'location') enterLocation(true);
    }, err => {
      Object.assign(LOC, { state: 'unavailable', busy: false, lat: null, lng: null, acc: null, msg: err && err.code === 1 ? 'Location permission was not given.' : 'Your location could not be found.' });
      store.set(LOC); drawLoc(); if ($('use-loc')) $('use-loc').checked = false;
    }, { enableHighAccuracy: true, timeout: 12000, maximumAge: 0 });
  }
  const saved = store.get();
  if (saved && ((saved.state === 'captured' && Date.now() - saved.ts < 30 * 60000) || saved.state === 'unavailable')) Object.assign(LOC, saved, { busy: false });
  if ($('use-loc')) {
    $('use-loc').checked = LOC.state === 'captured';
    $('use-loc').onchange = e => {
      if (e.target.checked) { if (LOC.state !== 'captured') requestFix(); }                 // already captured: no second request
      else {
        Object.assign(LOC, { state: 'pending', lat: null, lng: null, acc: null, msg: '' }); store.set(null); drawLoc();
        if (pins.main && pins.main.origin === 'gps' && !pins.main.touched) { delete pins.main; if (marks.main) { map.removeLayer(marks.main); delete marks.main; } syncHidden(); }
      }   // un-ticking withdraws the consent and forgets the fix
    };
  }
  drawLoc();

  /* pins: 'main' (one complaint) or one per ticked video issue. pin = {lat,lng,acc,origin,capLat,capLng,dt,text} */
  const map = L.map('map').setView([20.59, 78.96], 5), marks = {}, circles = {}; let active = 'main';
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution: '© OpenStreetMap' }).addTo(map);
  /* A video has one location by default (the pin 'main', asked once). Separate pins per issue exist only when the issues really are at different places. */
  let split = false, splitUser = false;
  const pins = {}, ids = () => Object.keys(sel).filter(k => sel[k].on), keys = () => (multi ? ids() : ['main']);
  const pinKeys = () => (multi && split ? ids() : ['main']), pinOf = k => (multi && !split ? pins.main : pins[k]);
  const firstLoc = () => { const l = ids().map(k => issuesById[k].location).filter(Boolean); return l.find(x => x.kind === 'video_gps') || l[0] || null; };
  const autoSplit = () => { const l = ids().map(k => issuesById[k].location).filter(x => x && x.kind === 'video_gps'); return l.some(a => l.some(b => metres(a.lat, a.lng, b.lat, b.lng) > 25)); };
  const metres = (a, b, c, d) => { const dx = (d - b) * 111320 * Math.cos((a + c) / 2 * Math.PI / 180), dy = (c - a) * 110540; return Math.hypot(dx, dy); };
  const issueNo = k => keys().indexOf(k) + 1;
  function icon(k) { return multi && split ? L.divIcon({ className: 'pinnum' + (k === active ? ' on' : ''), html: String(issueNo(k)), iconSize: [30, 30], iconAnchor: [15, 15] }) : new L.Icon.Default(); }
  function seedPin(k) {                                              // a starting position that came from a real device fix; otherwise none (citizen taps the map)
    if (pins[k]) return;
    if (multi) { const l = split ? (issuesById[k] || {}).location : firstLoc(); if (l) pins[k] = { lat: l.lat, lng: l.lng, acc: l.acc, origin: l.kind, capLat: l.lat, capLng: l.lng, dt: l.dt, text: '' }; }
    else if (videoAI && videoAI.location) { const l = videoAI.location; pins.main = { lat: l.lat, lng: l.lng, acc: l.acc, origin: l.kind, capLat: l.lat, capLng: l.lng, dt: l.dt, text: '' }; }
    else if (LOC.state === 'captured') pins[k] = { lat: LOC.lat, lng: LOC.lng, acc: LOC.acc, origin: 'gps', capLat: LOC.lat, capLng: LOC.lng, dt: null, text: '' };
  }
  function place(k, lat, lng, userMoved) {
    const pin = pins[k] = Object.assign(pins[k] || { origin: null, capLat: null, capLng: null, acc: null, dt: null, text: '' }, { lat, lng });
    if (!marks[k]) { marks[k] = L.marker([lat, lng], { draggable: true, icon: icon(k) }).addTo(map); marks[k].on('dragend', () => { const q = marks[k].getLatLng(); place(k, q.lat, q.lng, true); setActive(k); }); marks[k].on('click', () => setActive(k)); }
    else marks[k].setLatLng([lat, lng]);
    const moved = pin.capLat != null ? metres(pin.capLat, pin.capLng, lat, lng) : null;
    if (circles[k]) { map.removeLayer(circles[k]); delete circles[k]; }
    if (pin.acc && moved != null && moved <= 5) circles[k] = L.circle([lat, lng], { radius: pin.acc, color: '#2563eb', weight: 1, fillOpacity: .1, interactive: false }).addTo(map);
    if (userMoved) pin.touched = true;
    if (k === active) showCoords();
    syncHidden();
  }
  function showCoords() {
    const el = $('coords'), pin = pins[active];
    if (!pin || pin.lat == null) { el.innerHTML = ''; return; }
    const moved = pin.capLat != null ? Math.round(metres(pin.capLat, pin.capLng, pin.lat, pin.lng)) : null, row = (a, b) => `<div><dt>${a}</dt><dd>${b}</dd></div>`;
    let acc, note = '';
    if (pin.capLat == null) acc = '<span class="mut">not from GPS: the pin was placed by you</span>';
    else if (moved > 5) acc = `<span class="mut">GPS was ±${Math.round(pin.acc || 0)} m; you moved the pin ${moved} m</span>`;
    else acc = `±${Math.round(pin.acc || 0)} m`;
    if (pin.capLat != null && moved <= 5 && (pin.acc || 0) > POOR) note = `GPS accuracy is low (±${Math.round(pin.acc)} m). Please check that the pin is on the problem.`;
    if (pin.origin === 'video_gps' && pin.dt != null && moved <= 5) note += ` This fix was taken ${pin.dt} s from the moment in the video${pin.dt > 2.5 ? ': the vehicle may have moved, please check the pin.' : '.'}`;
    if (pin.origin === 'upload_fix' && moved <= 5) note += ' This is where your phone was when the video was uploaded, which may not be where it was filmed. Please check the pin.';
    el.innerHTML = row('Latitude', pin.lat.toFixed(6)) + row('Longitude', pin.lng.toFixed(6)) + row('GPS accuracy', acc) + (note ? `<p class="note warn">${esc(note)}</p>` : '');
  }
  function syncHidden() {                                            // single complaint: mirror the pin into the form fields the server reads
    const p = pins.main || {}; if (multi) return;
    $('lat').value = p.lat != null ? p.lat.toFixed(6) : ''; $('lng').value = p.lng != null ? p.lng.toFixed(6) : '';
    $('cap_lat').value = p.capLat != null ? p.capLat : ''; $('cap_lng').value = p.capLng != null ? p.capLng : ''; $('loc_acc').value = p.acc != null ? p.acc : ''; $('loc_origin').value = p.origin || '';
  }
  function setActive(k) {
    if (multi && active !== k) pins[active] && (pins[active].text = $('location_text').value);
    active = k; $('location_text').value = (pins[k] && pins[k].text) || '';
    $$('#loc-issues button').forEach(b => b.classList.toggle('on', b.dataset.k === k));
    Object.keys(marks).forEach(m => marks[m].setIcon(icon(m)));
    if (pins[k] && pins[k].lat != null) map.setView([pins[k].lat, pins[k].lng], Math.max(map.getZoom(), 17)); showCoords();
  }
  function enterLocation(fromGps) {
    Object.keys(marks).forEach(k => { map.removeLayer(marks[k]); delete marks[k]; if (circles[k]) { map.removeLayer(circles[k]); delete circles[k]; } });
    if (multi && !splitUser) split = ids().length > 1 && autoSplit();            // GPS from the filming shows different places -> separate pins, already placed
    const ks = pinKeys(); if (!ks.includes(active)) active = ks[0];
    $('split-wrap').hidden = !(multi && ids().length > 1); $('split-loc').checked = split;
    if (fromGps && !multi && LOC.state === 'captured') pins.main = { lat: LOC.lat, lng: LOC.lng, acc: LOC.acc, origin: 'gps', capLat: LOC.lat, capLng: LOC.lng, dt: null, text: (pins.main || {}).text || '' };
    ks.forEach(seedPin);
    $('loc-issues').hidden = !(multi && split);
    if (multi && split) $('loc-issues').innerHTML = ks.map((k, n) => { const i = issuesById[k]; return `<button type="button" data-k="${k}" class="${k === active ? 'on' : ''}"><b>${n + 1}</b> ${esc(sel[k].category)} <small>${mmss(i.best_t || 0)}</small><i class="${pins[k] && pins[k].lat != null ? 'set' : ''}"></i></button>`; }).join('');
    $$('#loc-issues button').forEach(b => b.onclick = () => setActive(b.dataset.k));
    ks.forEach(k => pins[k] && pins[k].lat != null && place(k, pins[k].lat, pins[k].lng, false));
    /* centre at once (the step is already visible), and once more after the layout settles */
    map.invalidateSize(); setActive(active);
    setTimeout(() => { map.invalidateSize(); setActive(active); const pts = ks.filter(k => pins[k] && pins[k].lat != null).map(k => [pins[k].lat, pins[k].lng]); if (pts.length > 1) map.fitBounds(pts, { padding: [40, 40], maxZoom: 18 }); }, 80);
    msg($('gps-msg'), !multi ? '' : split ? 'Pick an issue above, then tap the map to place it. Each issue has its own pin.' : (ids().length > 1 ? `Place the video's location once: it is used for all ${ids().length} issues.` : ''));
    drawLoc(); $('location_text').oninput = () => { const k = active; (pins[k] = pins[k] || { lat: null, lng: null, origin: null, capLat: null, capLng: null, acc: null, dt: null }).text = $('location_text').value; };
  }
  map.on('click', e => place(active, e.latlng.lat, e.latlng.lng, true));
  $('split-loc').onchange = e => {
    split = e.target.checked; splitUser = true;
    if (split) { const m = pins.main; ids().forEach(k => { if (!pins[k]) { const l = issuesById[k].location; pins[k] = l ? { lat: l.lat, lng: l.lng, acc: l.acc, origin: l.kind, capLat: l.lat, capLng: l.lng, dt: l.dt, text: '' } : m ? Object.assign({}, m) : null; if (!pins[k]) delete pins[k]; } }); }
    else if (!pins.main && pins[ids()[0]]) pins.main = Object.assign({}, pins[ids()[0]]);
    active = split ? ids()[0] : 'main'; enterLocation();
  };
  $('gps').onclick = () => requestFix();                              // explicit click only

  /* video with several detected issues */
  function initIssues(d) {
    issuesById = {}; (d.issues || []).forEach(i => { if (i.id && i.photo_url) issuesById[i.id] = i; });
    if (selFor === d.photo_name) return;                              // same video: keep the citizen's ticks, categories and pins
    selFor = d.photo_name; sel = {}; split = false; splitUser = false; Object.keys(pins).forEach(k => delete pins[k]);
    Object.values(issuesById).forEach(i => { sel[i.id] = { on: !i.low_score && i.status !== 'conflict' && !i.maybe_same_as, category: i.category }; });      // a lone sighting is normal in a sparsely sampled video: pre-ticked but labelled 'please check'
    renderPicker();
  }
  function renderPicker() {
    const ids = Object.keys(issuesById), n = () => ids.filter(k => sel[k].on).length;
    const av = ai && ai.annotated_video_url, vsrc = av || (ai && ai.video_url);
    const player = vsrc ? `<div class="vidbox"><video class="vp-player" controls playsinline preload="metadata" src="${esc(vsrc)}"></video><p class="mut sm mb-2">${av ? "Your video with the AI's boxes and labels (#1, #2 … match the list). A <b>thick</b> box is a moment the AI checked; a <b>thin</b> box follows it for a second." : 'Your video.'}</p></div>` : '';
    $('ai-picker').innerHTML = `${player}<p class="mb-2"><b>${ids.length} possible issue${ids.length > 1 ? 's' : ''} found in your video.</b> Tick the ones that are real.</p><div class="pklist">` + ids.map((k, x) => {
      const i = issuesById[k], flags = [i.needs_confirmation ? '<span class="chip warn">please check</span>' : '', i.maybe_same_as ? `<span class="chip">may be the same as #${+i.maybe_same_as.slice(1) + 1}</span>` : '',
        i.location ? (i.location.kind === 'video_gps' ? '<span class="chip ok">GPS near this moment</span>' : '<span class="chip">approximate location</span>') : '<span class="chip">no GPS for this moment</span>'].join(' ');
      return `<label class="pk"><input type="checkbox" data-iid="${k}" ${sel[k].on ? 'checked' : ''}><img src="${esc(i.annotated_url || i.photo_url)}" alt="Frame at ${mmss(i.best_t || 0)}" loading="lazy">`
        + `<span><b>#${x + 1} ${esc(i.category)}</b> · ${Math.round(i.score * 100)}% · at ${(i.timestamps || []).map(mmss).join(', ')}<br><span class="mut sm">seen in ${i.frames_seen} of ${i.frames_total} frames · ${(i.models || []).length} model${(i.models || []).length === 1 ? '' : 's'}</span><br>${flags} ${vsrc ? `<button type="button" class="vp-t" data-seek="${Math.max(0, (i.best_t || 0) - 0.5)}">▶ ${mmss(i.best_t || 0)}</button>` : ''}</span></label>`;
    }).join('') + '</div>';
    const upd = () => { $('ai-next').disabled = n() === 0; $('ai-next').textContent = n() > 1 ? `Confirm ${n()} categories →` : 'Confirm category →'; };
    $$('#ai-picker input[data-iid]').forEach(c => c.onchange = () => { sel[c.dataset.iid].on = c.checked; upd(); }); upd();
  }
  function renderCats() {
    $('cat-multi').hidden = !multi; $('cat-single').hidden = multi;
    if (!multi) return;
    const opts = [...$('category').options].filter(o => o.value).map(o => o.value);
    $('cat-multi').innerHTML = '<p class="mut sm">AI suggested these categories. Change any that are wrong.</p>' + keys().map((k, x) => { const i = issuesById[k];
      return `<div class="catrow"><img src="${esc(i.photo_url)}" alt=""><div><b>Issue ${x + 1}</b> <span class="mut sm">at ${mmss(i.best_t || 0)}</span><select class="form-select" data-cat="${k}" aria-label="Category for issue ${x + 1}">`
        + opts.map(o => `<option ${o === sel[k].category ? 'selected' : ''}>${esc(o)}</option>`).join('') + '</select></div></div>'; }).join('');
    $$('[data-cat]').forEach(s2 => s2.onchange = () => { sel[s2.dataset.cat].category = s2.value; });
  }

  /* review + duplicate warning */
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  function whereText(k) {
    const p = pinOf(k) || {}, ak = multi && !split ? 'main' : k, t = esc((ak === active ? $('location_text').value : p.text) || '').trim() || (p.text ? esc(p.text) : '');
    const moved = p.capLat != null && p.lat != null ? Math.round(metres(p.capLat, p.capLng, p.lat, p.lng)) : null;
    const how = p.lat == null ? '' : p.capLat == null ? 'pin placed by you' : moved > 5 ? `GPS, pin moved ${moved} m` : `GPS ±${Math.round(p.acc || 0)} m`;
    return (p.lat != null ? `${p.lat.toFixed(5)}, ${p.lng.toFixed(5)} <span class="mut sm">(${how})</span>` : '<span class="mut">No coordinates</span>') + (t ? `<div>${t}</div>` : '');
  }
  async function dupCheck(k, lat, lng, cat, into) {
    try {
      const rows = await (await fetch(`${f.dataset.nearby}?category=${encodeURIComponent(cat)}&lat=${lat}&lng=${lng}`)).json(); if (!rows.length) return;
      into.hidden = false;
      into.insertAdjacentHTML('beforeend', `<div class="dupbox"><b>${multi ? 'Issue ' + (issueNo(k)) + ': s' : 'S'}imilar complaint nearby</b><p class="sm mb-1">Support an existing complaint instead of creating another one. If yours is different, just submit below.</p>` +
        rows.map(r => `<div class="dupitem"><span>${esc(r.tracking_id)} · ${r.distance_m} m away · ${r.votes} ${r.votes === 1 ? 'supporter' : 'supporters'} · ${esc(r.status)}${r.location_text ? ' · ' + esc(r.location_text) : ''}</span>` +
          (r.is_owner ? '<span class="mut sm">Your complaint</span>' : r.has_voted ? '<span class="mut sm">You already support it</span>' : `<button type="button" class="btn btn-sm btn-primary" data-vote="${esc(r.tracking_id)}">Support this</button>`) + '</div>').join('') + '</div>');
      $$('[data-vote]').forEach(b => b.onclick = async () => {
        const r = await fetch(`/complaint/${b.dataset.vote}/vote`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf }, body: '{}' }), d = await r.json();
        if (d.url) location = d.url; else alert(d.message || 'Could not add your support.');
      });
    } catch (e) { /* duplicate check is optional - never block submission */ }
  }
  async function review() {
    if (multi && pins[active]) pins[active].text = $('location_text').value;
    const desc = $('description').value.trim(), dup = $('dup'); dup.hidden = true; dup.innerHTML = '';
    const row = (k, v) => `<div class="sumrow"><span>${k}</span><div>${v}</div></div>`;
    if (multi) {
      const ks = keys();
      $('summary').innerHTML = row('Method', 'AI-based reporting from a video') + row('Complaints', `<b>${ks.length}</b> separate complaint${ks.length > 1 ? 's' : ''} will be created`)
        + row('Video', 'The original video is attached to every complaint as evidence') + row('Description', desc ? esc(desc) + ' <span class="mut sm">(shared by all)</span>' : '<span class="mut">Not provided</span>')
        + ks.map((k, x) => { const i = issuesById[k]; return `<div class="sumcard"><img src="${esc(i.photo_url)}" alt=""><div><b>Complaint ${x + 1}: ${esc(sel[k].category)}</b>${sel[k].category !== i.category ? ` <span class="mut sm">(AI said ${esc(i.category)})</span>` : ''}<div class="mut sm">at ${mmss(i.best_t || 0)} in the video</div><div>${whereText(k)}</div></div></div>`; }).join('');
      ks.forEach(k => { const q = pinOf(k); q && q.lat != null && dupCheck(k, q.lat, q.lng, sel[k].category, dup); });
      return;
    }
    const loc = $('location_text').value.trim(), lat = $('lat').value;
    $('summary').innerHTML = row('Method', mode === 'ai' ? 'AI-based reporting' : 'Manual reporting')
      + row('Photograph', $('photo_name').value ? `<img class="sumimg" src="${photoUrl}" alt="">` : '<span class="mut">No photo</span>')
      + ($('video_name') && $('video_name').value ? row('Video', 'Attached as evidence (the AI checked several frames)') : '')
      + (mode === 'ai' ? row('AI result', ai && ai.status === 'ok' ? `${esc(ai.label)} (${Math.round(ai.confidence * 100)}%)` : '<span class="mut">No detection</span>') : '')
      + row('Category', esc($('category').value)) + row('Description', desc ? esc(desc) : '<span class="mut">Not provided</span>')
      + row('Confirmed location', (pins.main && pins.main.lat != null ? whereText('main') : (loc ? `<div>${esc(loc)}</div>` : '<span class="mut">None</span>')));
    if (lat) dupCheck('main', lat, $('lng').value, $('category').value, dup);
  }
  async function submitMulti() {
    const btn = f.querySelector('button.btn-success'); btn.disabled = true;
    const issues = keys().map(k => { const p = pinOf(k) || {}; return { id: k, category: sel[k].category, lat: p.lat != null ? p.lat : null, lng: p.lng != null ? p.lng : null, location_text: (p.text || '').trim(),
      origin: p.origin, acc: p.acc, cap_lat: p.capLat, cap_lng: p.capLng, dt: p.dt }; });
    try {
      const r = await fetch(f.dataset.videoSubmit, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf }, body: JSON.stringify({ video_name: $('video_name').value, description: $('description').value.trim(), issues }) }), d = await r.json();
      if (!r.ok || !d.ok) { alert(d.error || 'Could not submit. Please try again.'); btn.disabled = false; return; }
      store.set(null); location = d.url;
    } catch (e) { alert('Could not submit. Check your connection and try again.'); btn.disabled = false; }
  }
  f.addEventListener('submit', e => { if (multi) { e.preventDefault(); submitMulti(); } else store.set(null); });

  /* navigation + validation */
  function valid(name) {
    if (name === 'photo' && mode === 'ai' && !$('photo_name').value) { msg($('photo-msg'), 'Please take or upload a photo to continue (or use manual reporting).', 'err'); return false; }
    if (name === 'ai' && multi && !keys().length) { alert('Tick at least one issue to report.'); return false; }
    if (name === 'category' && !multi && !$('category').value) { alert('Please choose a category.'); return false; }
    if (name === 'location') {
      if (multi) {
        if (pins[active]) pins[active].text = $('location_text').value;
        const pk = pinKeys(), miss = pk.findIndex(k => !(pins[k] && (pins[k].lat != null || (pins[k].text || '').trim())));
        if (miss >= 0) { msg($('gps-msg'), split ? `Issue ${ids().indexOf(pk[miss]) + 1} still needs a place: tap the map, or type a landmark.` : "Please set the video's location once: tap the map, use GPS, or type a landmark.", 'err'); setActive(pk[miss]); return false; }
      } else if (!$('lat').value && !$('location_text').value.trim()) { msg($('gps-msg'), 'Please use GPS, tap the map, or type a landmark.', 'err'); return false; }
    }
    return true;
  }
  $$('[data-next]').forEach(b => b.onclick = async () => {
    const cur = ORDER[idx]; if (!valid(cur)) return; const nxt = ORDER[idx + 1];
    show(nxt); if (nxt === 'ai') runAI();
  });
  $$('[data-back]').forEach(b => b.onclick = () => show(ORDER[Math.max(0, idx - 1)]));
  $$('[data-goto]').forEach(b => b.onclick = () => show(b.dataset.goto));
  f.addEventListener('keydown', e => { if (e.key === 'Enter' && e.target.tagName !== 'TEXTAREA') e.preventDefault(); });
  show(ORDER[0]);
})();
