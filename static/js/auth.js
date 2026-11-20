/* Auth page visuals only (eagle video + Login<->Register transition). Never touches forms, routes or validation. */
(function () {
  'use strict';
  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var video = document.getElementById('eagleVideo'), KEY = 'crcEagleT';
  function remember() { try { if (video) sessionStorage.setItem(KEY, String(video.currentTime || 0)); } catch (e) {} }

  if (video) {
    /* resume where the previous auth page left off, so switching Login <-> Register feels continuous */
    var saved = parseFloat(sessionStorage.getItem(KEY) || '');
    var start = function () {
      var t = isFinite(saved) && saved > 0.2 && (!video.duration || saved < video.duration - 0.4) ? saved : 0;
      if (reduce) t = 2.5;                                   // calm still frame for reduced motion
      try { if (t) video.currentTime = t; } catch (e) {}
      if (reduce) video.pause();
    };
    if (video.readyState >= 1) start(); else video.addEventListener('loadedmetadata', start, { once: true });
    if (reduce) video.removeAttribute('autoplay'); else { var pr = video.play(); if (pr && pr.catch) pr.catch(function () {}); }
    window.addEventListener('pagehide', remember);
  }

  /* smooth Login <-> Register switch: quick fade-out, then normal navigation (works without JS too) */
  document.querySelectorAll('a[data-switch]').forEach(function (a) {
    a.addEventListener('click', function (e) {
      if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0 || reduce) return;
      e.preventDefault(); remember(); document.body.classList.add('leaving');
      setTimeout(function () { window.location.href = a.href; }, 170);
    });
  });
  window.addEventListener('pageshow', function (e) { if (e.persisted) document.body.classList.remove('leaving'); });
})();
