/* Animated SVG line chart for "Reported vs Resolved". Reads window.__TREND = {labels, reported, resolved}. No libraries. */
(function () {
  'use strict';
  var host = document.getElementById('trend'), T = window.__TREND;
  if (!host || !T || !T.labels) return;
  var NS = 'http://www.w3.org/2000/svg', reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var SERIES = [{ k: 'reported', name: 'Reported', c: '#2563EB' }, { k: 'resolved', name: 'Resolved', c: '#16A34A' }];
  var el = function (n, a, p) { var e = document.createElementNS(NS, n); for (var k in a) e.setAttribute(k, a[k]); if (p) p.appendChild(e); return e; };

  function smooth(pts) {                       // Catmull-Rom -> cubic Bezier, control points clamped so the curve never dips below its neighbours
    if (pts.length < 2) return 'M' + pts[0][0] + ',' + pts[0][1];
    var d = 'M' + pts[0][0] + ',' + pts[0][1];
    for (var i = 0; i < pts.length - 1; i++) {
      var p0 = pts[i - 1] || pts[i], p1 = pts[i], p2 = pts[i + 1], p3 = pts[i + 2] || p2, t = 0.18;
      var c1y = Math.min(Math.max(p1[1] + (p2[1] - p0[1]) * t, Math.min(p1[1], p2[1])), Math.max(p1[1], p2[1]));
      var c2y = Math.min(Math.max(p2[1] - (p3[1] - p1[1]) * t, Math.min(p1[1], p2[1])), Math.max(p1[1], p2[1]));
      d += 'C' + (p1[0] + (p2[0] - p0[0]) * t) + ',' + c1y + ' ' + (p2[0] - (p3[0] - p1[0]) * t) + ',' + c2y + ' ' + p2[0] + ',' + p2[1];
    }
    return d;
  }

  function draw() {
    var w = host.clientWidth, h = host.clientHeight; if (w < 60 || h < 60) return;
    host.innerHTML = ''; host.classList.remove('on');
    var n = T.labels.length, m = { l: 30, r: 12, t: 14, b: 28 }, iw = w - m.l - m.r, ih = h - m.t - m.b;
    var max = Math.max.apply(null, [1].concat(T.reported, T.resolved)), step = Math.max(1, Math.ceil(max / 4)), top = step * Math.ceil(max / step);
    var X = function (i) { return m.l + (n === 1 ? iw / 2 : i * iw / (n - 1)); }, Y = function (v) { return m.t + ih - (v / top) * ih; };
    var svg = el('svg', { viewBox: '0 0 ' + w + ' ' + h, 'aria-hidden': 'true' }, host), defs = el('defs', {}, svg);
    SERIES.forEach(function (s) { var g = el('linearGradient', { id: 'g-' + s.k, x1: 0, y1: 0, x2: 0, y2: 1 }, defs); el('stop', { offset: '0%', 'stop-color': s.c, 'stop-opacity': s.k === 'reported' ? .28 : .16 }, g); el('stop', { offset: '100%', 'stop-color': s.c, 'stop-opacity': 0 }, g); });
    for (var v = 0; v <= top; v += step) { el('line', { x1: m.l, x2: w - m.r, y1: Y(v), y2: Y(v), 'class': 'grid' }, svg); var t = el('text', { x: m.l - 8, y: Y(v) + 4, 'text-anchor': 'end', 'class': 'axis' }, svg); t.textContent = v; }
    var every = Math.max(1, Math.ceil(n / Math.max(2, Math.floor(iw / 62))));
    T.labels.forEach(function (l, i) { if ((n - 1 - i) % every) return; var tx = el('text', { x: X(i), y: h - 6, 'text-anchor': i === 0 ? 'start' : i === n - 1 ? 'end' : 'middle', 'class': 'axis' }, svg); tx.textContent = l; });
    var guide = el('line', { y1: m.t, y2: m.t + ih, 'class': 'guide' }, svg), dots = {};
    var total = T.reported.concat(T.resolved).reduce(function (a, b) { return a + b; }, 0);
    SERIES.slice().reverse().forEach(function (s) {
      var pts = T[s.k].map(function (val, i) { return [X(i), Y(val)]; }), d = smooth(pts);
      el('path', { d: d + 'L' + X(n - 1) + ',' + (m.t + ih) + 'L' + X(0) + ',' + (m.t + ih) + 'Z', fill: 'url(#g-' + s.k + ')', 'class': 'area' }, svg);
      var line = el('path', { d: d, stroke: s.c, 'class': 'line', pathLength: 1 }, svg);
      if (!reduce) { line.style.strokeDasharray = 1; line.style.strokeDashoffset = 1; line.style.transition = 'stroke-dashoffset 1.3s cubic-bezier(.22,.8,.24,1)'; line.getBoundingClientRect(); requestAnimationFrame(function () { line.style.strokeDashoffset = 0; }); }
      if (n <= 16) pts.forEach(function (p) { el('circle', { cx: p[0], cy: p[1], r: 3.4, fill: '#fff', stroke: s.c, 'stroke-width': 2, 'class': 'pt' }, svg); });
      dots[s.k] = el('circle', { r: 5.5, fill: s.c, stroke: '#fff', 'stroke-width': 2.5, 'class': 'dot' }, svg);
    });
    var tip = document.createElement('div'); tip.className = 'tip'; host.appendChild(tip);
    if (!total) { var none = document.createElement('div'); none.className = 'none'; none.textContent = 'No activity in these days yet'; host.appendChild(none); }
    var tb = document.createElement('div'); tb.className = 'srt'; tb.innerHTML = '<table><caption>Reported and resolved complaints per day</caption><tr><th>Day</th><th>Reported</th><th>Resolved</th></tr>' + T.labels.map(function (l, i) { return '<tr><td>' + l + '</td><td>' + T.reported[i] + '</td><td>' + T.resolved[i] + '</td></tr>'; }).join('') + '</table>'; host.appendChild(tb);   /* wrapped in a clipped div: overflow:hidden is ignored on tables */

    function show(ev) {
      var r = host.getBoundingClientRect(), x = (ev.touches ? ev.touches[0].clientX : ev.clientX) - r.left;
      var i = Math.min(n - 1, Math.max(0, Math.round(n === 1 ? 0 : (x - m.l) / iw * (n - 1))));
      guide.setAttribute('x1', X(i)); guide.setAttribute('x2', X(i)); guide.style.opacity = 1;
      SERIES.forEach(function (s) { dots[s.k].setAttribute('cx', X(i)); dots[s.k].setAttribute('cy', Y(T[s.k][i])); dots[s.k].style.opacity = 1; });
      tip.innerHTML = '<b>' + T.labels[i] + '</b>' + SERIES.map(function (s) { return '<span><i style="background:' + s.c + '"></i>' + s.name + ': <strong>' + T[s.k][i] + '</strong></span>'; }).join('');
      var tw = tip.offsetWidth / 2 + 6; tip.style.left = Math.min(w - tw, Math.max(tw, X(i))) + 'px'; tip.style.top = Math.max(Y(Math.max(T.reported[i], T.resolved[i])), 36) + 'px'; tip.style.opacity = 1;
    }
    function hide() { guide.style.opacity = 0; tip.style.opacity = 0; SERIES.forEach(function (s) { dots[s.k].style.opacity = 0; }); }
    host.onpointermove = show; host.onpointerdown = show; host.onpointerleave = hide;
    requestAnimationFrame(function () { host.classList.add('on'); });
  }
  draw();
  var last = host.clientWidth; if (window.ResizeObserver) new ResizeObserver(function () { if (host.clientWidth !== last) { last = host.clientWidth; draw(); } }).observe(host); else window.addEventListener('resize', draw);
})();
