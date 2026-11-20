/* Landing page motion: purely visual (never touches forms, routes or data). Works without it: content is visible if JS fails. */
(function () {
  'use strict';
  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var $ = function (s, r) { return (r || document).querySelector(s); }, $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var clamp = function (v, a, b) { return Math.min(b, Math.max(a, v)); };

  /* background video: respect reduced motion (poster stays), otherwise make sure it plays */
  var vid = $('.lp-bg video');
  if (vid) { if (reduce) { vid.removeAttribute('autoplay'); vid.pause(); } else { var p = vid.play(); if (p && p.catch) p.catch(function () {}); } }

  /* nav: glass bar after scrolling + mobile menu */
  var nav = $('#lpNav'), burger = $('#lpBurger');
  if (burger && nav) {
    burger.addEventListener('click', function () { var o = nav.classList.toggle('open'); burger.setAttribute('aria-expanded', o); });
    $$('#lpLinks a').forEach(function (a) { a.addEventListener('click', function () { nav.classList.remove('open'); burger.setAttribute('aria-expanded', 'false'); }); });
  }

  /* split text into words (keeps <em>, <span> and <br> structure) */
  function split(el, cls) {
    var i = 0;
    el.setAttribute('aria-label', el.textContent.trim().replace(/\s+/g, ' '));
    (function walk(node) {
      Array.prototype.slice.call(node.childNodes).forEach(function (n) {
        if (n.nodeType === 3) {
          var frag = document.createDocumentFragment();
          n.textContent.split(/(\s+)/).forEach(function (t) {
            if (!t) return;
            if (/^\s+$/.test(t)) frag.appendChild(document.createTextNode(' '));
            else { var s = document.createElement('span'); s.className = cls; s.style.setProperty('--i', i++); s.setAttribute('aria-hidden', 'true'); s.textContent = t; frag.appendChild(s); }
          });
          n.replaceWith(frag);
        } else if (n.nodeType === 1 && n.tagName !== 'BR') walk(n);
      });
    })(el);
    return i;
  }
  var splitEls = $$('[data-split]'); splitEls.forEach(function (el) { split(el, 'w'); });
  var scrubEl = $('[data-scrub]'), scrubWords = [];
  if (scrubEl) { split(scrubEl, 'sw'); scrubWords = $$('.sw', scrubEl); }

  /* reveal on scroll */
  var revealTargets = $$('.rv').concat(splitEls);
  if (reduce || !('IntersectionObserver' in window)) revealTargets.forEach(function (e) { e.classList.add('in'); });
  else {
    var io = new IntersectionObserver(function (es) { es.forEach(function (e) { if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); } }); }, { threshold: 0.18, rootMargin: '0px 0px -6% 0px' });
    revealTargets.forEach(function (e) { io.observe(e); });
  }

  /* count-up: animates the number already rendered from the database; non-integers are left untouched */
  function countUp(el) {
    var raw = String(el.dataset.count || '').trim(), suf = el.dataset.suffix || '';
    if (!/^\d+$/.test(raw) || reduce) return;
    var end = parseInt(raw, 10), t0 = null, dur = 1300;
    if (end === 0) return;
    el.textContent = '0' + suf;
    (function tick(t) { if (t0 === null) t0 = t; var k = clamp((t - t0) / dur, 0, 1), v = 1 - Math.pow(1 - k, 3); el.textContent = Math.round(end * v) + suf; if (k < 1) requestAnimationFrame(tick); else el.textContent = end + suf; })(performance.now());
  }
  var counters = $$('[data-count]');
  if ('IntersectionObserver' in window) {
    var cio = new IntersectionObserver(function (es) { es.forEach(function (e) { if (e.isIntersecting) { countUp(e.target); cio.unobserve(e.target); } }); }, { threshold: 0.6 });
    counters.forEach(function (c) { cio.observe(c); });
  }

  /* category tiles: cursor spotlight */
  $$('.lp-cat').forEach(function (c) {
    c.addEventListener('pointermove', function (e) { var r = c.getBoundingClientRect(); c.style.setProperty('--mx', (e.clientX - r.left) + 'px'); c.style.setProperty('--my', (e.clientY - r.top) + 'px'); });
  });

  /* scroll-linked effects (one rAF-throttled handler) */
  var dim = $('#lpDim'), heroIn = $('#lpHeroIn'), tl = $('#lpTl'), steps = $$('.lp-step'), tlBar = tl && $('.lp-tl-line i', tl), ticking = false;
  function frame() {
    ticking = false;
    var y = window.scrollY || 0, vh = window.innerHeight;
    if (nav) nav.classList.toggle('scrolled', y > 30);
    if (dim) dim.style.setProperty('--dim', clamp(y / (vh * 1.25), 0, 1) * 0.78);
    if (!reduce && heroIn && y < vh * 1.2) { heroIn.style.transform = 'translate3d(0,' + (y * 0.16).toFixed(1) + 'px,0)'; heroIn.style.opacity = clamp(1 - y / (vh * 0.8), 0, 1); }
    if (scrubWords.length) {
      var r = scrubEl.getBoundingClientRect(), p = clamp((vh * 0.88 - r.top) / (r.height + vh * 0.12), 0, 1), n = scrubWords.length;
      scrubWords.forEach(function (w, k) { w.style.opacity = reduce ? 1 : (0.16 + 0.84 * clamp(p * (n + 3) - k, 0, 1)).toFixed(3); });
    }
    if (tl) {
      var tr = tl.getBoundingClientRect();
      tl.style.setProperty('--p', (clamp((vh * 0.6 - tr.top) / tr.height, 0, 1) * 100).toFixed(1) + '%');
      if (tlBar) tlBar.parentNode.style.setProperty('--p', (clamp((vh * 0.6 - tr.top) / tr.height, 0, 1) * 100).toFixed(1) + '%');
      steps.forEach(function (s) { var sr = s.getBoundingClientRect(); s.classList.toggle('on', sr.top + sr.height * 0.25 < vh * 0.62); });
    }
  }
  function onScroll() { if (!ticking) { ticking = true; requestAnimationFrame(frame); } }
  window.addEventListener('scroll', onScroll, { passive: true }); window.addEventListener('resize', onScroll);
  frame();
})();
