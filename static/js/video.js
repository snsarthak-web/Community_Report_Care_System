/* Video evidence for AI reporting. Three ways in, one pipeline:
     1. Record Video  -> live camera inside the page (MediaRecorder), optional GPS sampled while filming
     2. Record Video  -> on browsers that cannot (plain http, old phones): the phone's own camera app (capture="environment")
     3. Upload Video  -> a video from the gallery
   The server checks the real file type, analyses frames with the same five YOLO models and returns the result; the best frame
   becomes the complaint's ordinary photo, so the rest of the wizard is unchanged. */
(function () {
  'use strict';
  const R = window.CRCReport; if (!R) return;
  const f = R.form, $ = id => document.getElementById(id);
  const MAX_MB = +f.dataset.vmax || 60, MAX_SEC = +f.dataset.vsec || 60, REC_MAX = 30;
  const panel = $('vid-panel'), bar = $('vid-bar'), text = $('vid-text'), title = $('vid-title'), found = $('vid-found'), rm = $('vid-remove');
  if (!panel) return;
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  let job = null, timer = null, gen = 0, xhr = null;      // gen: bumped on every reset, so work that was cancelled (photo chosen, video removed/replaced) can never complete later

  /* progress panel */
  function show(ttl, pct, txt, kind) {
    panel.hidden = false; panel.className = 'vid-panel ' + (kind || ''); title.textContent = ttl; bar.style.width = Math.max(0, Math.min(100, pct)) + '%';
    text.textContent = txt || ''; $('vid-barwrap').hidden = kind === 'err';
  }
  function reset() { gen++; if (xhr) { try { xhr.abort(); } catch (e) { /* already done */ } xhr = null; } clearTimeout(timer); job = null; panel.hidden = true; found.hidden = true; found.innerHTML = ''; rm.hidden = true; }
  window.CRCVideo = { reset };
  rm.onclick = () => R.dropVideo();

  /* GPS (optional) */
  const wantGps = () => R.locOn();                                 // the one location tick-box of Step 1 (never a second prompt)
  function oneFix() {                                              // for gallery / phone-camera videos: a single fix at upload time
    const fx = R.getFix();                                         // reuse what Step 1 captured: no new browser request. k:'up' = taken now, not while filming
    return Promise.resolve(wantGps() && fx ? [{ t: 0, lat: fx.lat, lng: fx.lng, acc: fx.acc, k: 'up' }] : []);
  }

  /* upload + analysis */
  function checkLength(file) {                                     // best-effort: some formats expose no duration until played
    return new Promise(res => {
      const v = document.createElement('video'), u = URL.createObjectURL(file); let done = false;
      const end = ok => { if (done) return; done = true; URL.revokeObjectURL(u); res(ok); };
      v.preload = 'metadata'; v.onloadedmetadata = () => end(!isFinite(v.duration) || v.duration <= MAX_SEC + 1); v.onerror = () => end(true); setTimeout(() => end(true), 3000); v.src = u;
    });
  }
  async function send(file, gps) {
    R.dropVideo();                                                 // replaces any previous photo / video (and cancels anything still running)
    const my = gen;
    if (file.size > MAX_MB * 1048576) return show('Video too large', 0, `Please choose a video under ${MAX_MB} MB (about ${REC_MAX} seconds of phone video is usually enough).`, 'err');
    if (file.type && !/^video\//.test(file.type)) return show('Not a video', 0, 'Please choose a video file (MP4, MOV, 3GP or WebM).', 'err');
    if (!(await checkLength(file))) return my === gen && show('Video too long', 0, `Please keep the video under ${MAX_SEC} seconds.`, 'err');
    show('Uploading video…', 2, 'Keep this page open.');
    const fd = new FormData(); fd.append('video', file, file.name || 'video');
    if (gps && gps.length) fd.append('gps', JSON.stringify(gps));
    let name;
    try {
      name = await new Promise((resolve, reject) => {
        const x = xhr = new XMLHttpRequest(); x.open('POST', f.dataset.uploadVideo); x.setRequestHeader('X-CSRFToken', R.csrf);
        x.upload.onprogress = e => { if (e.lengthComputable) show('Uploading video…', e.loaded / e.total * 20, `${Math.round(e.loaded / 1048576)} of ${Math.round(e.total / 1048576)} MB`); };
        x.onload = () => { let d = {}; try { d = JSON.parse(x.responseText); } catch (e) { /* not json */ } x.status === 200 && d.video_name ? resolve(d.video_name) : reject(new Error(d.error || 'Upload failed.')); };
        x.onerror = () => reject(new Error('Upload failed. Check your connection and try again.')); x.onabort = () => reject(new Error('cancelled')); x.send(fd);
      });
    } catch (e) { return my === gen && show('Upload failed', 0, e.message, 'err'); }
    xhr = null;
    if (my !== gen) return;                                        // cancelled while uploading: do not resume
    job = name; poll(name, Date.now());
  }
  function poll(name, t0) {
    if (job !== name) return;
    fetch(f.dataset.videoStatus + name + '/status', { headers: { 'X-CSRFToken': R.csrf } }).then(r => r.json().then(d => ({ ok: r.ok, d }))).then(({ ok, d }) => {
      if (job !== name) return;
      if (!ok || d.status === 'error') return show('Video could not be analysed', 0, (d && d.error) || 'Something went wrong. Please try again, or report with a photo.', 'err');
      if (d.status === 'done') return finished(d.result, name);
      const tot = Math.max(1, d.total || 1);
      if (d.stage === 'analyzing') show('Analysing video…', 25 + 70 * (d.done / tot), `Checking frame ${Math.min(d.done + 1, tot)} of ${tot} with the five AI models…`);
      else if (d.stage === 'rendering') show('Drawing the AI boxes on your video…', 94 + 5 * (d.done / tot), 'Making the video with the AI results marked on it…');
      else if (d.stage === 'queued') show('Analysing video…', 22, 'Waiting for the AI to be free…');
      else show('Analysing video…', 24, 'Reading the video and choosing the clearest frames…');
      if (Date.now() - t0 > 5 * 60 * 1000) return show('Taking too long', 0, 'The analysis is taking longer than expected. Please try a shorter video, or report with a photo.', 'err');
      timer = setTimeout(() => poll(name, t0), 1000);
    }).catch(() => { if (job === name) timer = setTimeout(() => poll(name, t0), 2500); });         // a hiccup in the network must not lose the job
  }
  function finished(r, name) {
    job = null; R.useVideo(r, name);
    const issues = r.issues || [];
    show('Video analysed ✓', 100, `${(r.video && r.video.frames_analyzed) || 0} frames checked · ${(r.video && r.video.duration) || 0}s${r.gps_points ? ' · ' + r.gps_points + ' GPS point' + (r.gps_points > 1 ? 's' : '') + ' saved' : ''}`, 'ok'); rm.hidden = false;
    found.hidden = false;
    found.innerHTML = issues.length ? `<b>${issues.length} possible issue${issues.length > 1 ? 's' : ''} found in your video</b><ul>` + issues.map(i => `<li><b>${esc(i.category)}</b> <span class="mut">at ${i.timestamps.map(R.mmss).join(', ')} · ${Math.round(i.score * 100)}%</span></li>`).join('') + '</ul>'
      : '<span class="mut">No known civic issue was found. You can still continue and choose the category yourself.</span>';
  }

  /* upload from gallery / phone camera app */
  const gal = $('in-vgal'), cam = $('in-vcam');
  $('btn-vgal').onclick = () => gal.click();
  [gal, cam].forEach(inp => inp.addEventListener('change', async () => { const file = inp.files[0]; inp.value = ''; if (file) send(file, await oneFix()); }));

  /* in-page recorder */
  const dlg = $('vrec'), vv = $('vrec-v'), vmsg = $('vrec-msg'), go = $('vrec-go'), tmr = $('vrec-timer'), gpsEl = $('vrec-gps');
  let stream = null, rec = null, chunks = [], facing = 'environment', t0 = 0, tick = null, watch = null, gps = [], discard = false, lastBtn = null, mime = '';
  const canRecord = () => !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder && window.isSecureContext);
  const pickMime = () => ['video/webm;codecs=vp9', 'video/webm;codecs=vp8', 'video/webm', 'video/mp4;codecs=avc1', 'video/mp4'].find(m => MediaRecorder.isTypeSupported(m)) || '';
  const clock = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;

  function stopStream() { if (stream) { stream.getTracks().forEach(t => t.stop()); stream = null; } vv.srcObject = null; }
  function stopGps() { if (watch !== null) { navigator.geolocation.clearWatch(watch); watch = null; } }
  function closeRec(keep) {
    if (rec && rec.state !== 'inactive') { discard = !keep; try { rec.stop(); } catch (e) { /* already stopped */ } }
    clearInterval(tick); stopGps(); stopStream(); dlg.hidden = true; document.body.classList.remove('camx-open'); go.classList.remove('on'); tmr.hidden = true; gpsEl.hidden = true;
    if (lastBtn && lastBtn.focus) lastBtn.focus();
  }
  async function startStream() {
    stopStream(); vmsg.textContent = 'Starting camera…'; vmsg.hidden = false; go.disabled = true;
    try {
      const s = await navigator.mediaDevices.getUserMedia({ audio: false, video: { facingMode: { ideal: facing }, width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: 30, max: 30 } } });
      if (dlg.hidden) { s.getTracks().forEach(t => t.stop()); return; }
      stream = s; vv.srcObject = s; vv.classList.toggle('mirror', facing === 'user'); await vv.play(); vmsg.hidden = true; go.disabled = false; go.focus();
      navigator.mediaDevices.enumerateDevices().then(d => { $('vrec-flip').hidden = d.filter(x => x.kind === 'videoinput').length < 2; }).catch(() => {});
    } catch (e) {
      closeRec(false);
      show('Camera not available', 0, e && e.name === 'NotAllowedError' ? 'Camera access was blocked. Allow it in your browser settings, or use Upload Video.' : 'The camera could not be started. Use Upload Video instead.', 'err');
    }
  }
  function startGps() {
    gps = []; gpsEl.hidden = !wantGps(); if (!wantGps()) return;
    gpsEl.textContent = 'Finding GPS…'; let last = -9;
    watch = navigator.geolocation.watchPosition(p => {
      const t = (performance.now() - t0) / 1000;
      if (gps.length && t - last < 2) return;                      // one fix every ~2 s is plenty
      last = t; if (gps.length < 120) gps.push({ t: Math.round(t * 100) / 100, lat: p.coords.latitude, lng: p.coords.longitude, acc: p.coords.accuracy, k: 'rec' });
      gpsEl.textContent = `GPS ✓ ±${Math.round(p.coords.accuracy)} m`;
    }, () => { gpsEl.textContent = 'GPS unavailable (you can place the pins on the map later)'; }, { enableHighAccuracy: true, maximumAge: 2000, timeout: 15000 });
  }
  function begin() {
    if (!stream) return;
    chunks = []; discard = false; mime = pickMime();
    try { rec = new MediaRecorder(stream, Object.assign({ videoBitsPerSecond: 2500000 }, mime ? { mimeType: mime } : {})); }
    catch (e) { closeRec(false); return show('Recording not supported', 0, 'This browser cannot record video here. Use Upload Video instead.', 'err'); }
    rec.ondataavailable = e => { if (e.data && e.data.size) chunks.push(e.data); };
    rec.onstop = () => {
      const secs = (performance.now() - t0) / 1000, type = (rec.mimeType || mime || 'video/webm').split(';')[0];
      if (discard) return;
      if (secs < 1.5 || !chunks.length) return show('Recording too short', 0, 'Please record at least 2 seconds.', 'err');
      const ext = type.includes('mp4') ? 'mp4' : 'webm';
      send(new File([new Blob(chunks, { type })], `recording.${ext}`, { type }), gps.slice());
    };
    rec.start(1000); t0 = performance.now(); startGps(); go.classList.add('on'); go.setAttribute('aria-label', 'Stop recording'); $('vrec-flip').hidden = true; $('vrec-gal').hidden = true;
    tmr.hidden = false; tick = setInterval(() => { const s = (performance.now() - t0) / 1000; tmr.textContent = `${clock(s)} / ${clock(REC_MAX)}`; if (s >= REC_MAX) closeRec(true); }, 200);
  }
  function openRec(ev) {
    lastBtn = ev && ev.currentTarget;
    if (!canRecord()) { cam.click(); return; }                     // phone camera app (needs no secure context) / older browsers
    dlg.hidden = false; document.body.classList.add('camx-open'); $('vrec-x').focus(); $('vrec-flip').hidden = false; $('vrec-gal').hidden = false; tmr.hidden = true; startStream();
  }
  $('btn-vrec').onclick = openRec;
  go.onclick = () => { if (rec && rec.state === 'recording') closeRec(true); else begin(); };
  $('vrec-x').onclick = () => closeRec(false);
  $('vrec-flip').onclick = () => { facing = facing === 'environment' ? 'user' : 'environment'; startStream(); };
  $('vrec-gal').onclick = () => { closeRec(false); gal.click(); };
  dlg.addEventListener('click', e => { if (e.target === dlg) closeRec(false); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && !dlg.hidden) { e.preventDefault(); closeRec(false); } });
  window.addEventListener('pagehide', () => { stopStream(); stopGps(); });
})();
