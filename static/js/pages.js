/* Overview / Track / Notifications / Profile: scroll reveal + password strength hint. Visual only. */
(function () {
  'use strict';
  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var els = [].slice.call(document.querySelectorAll('.rv2'));
  if (reduce || !('IntersectionObserver' in window)) els.forEach(function (e) { e.classList.add('in'); });
  else {
    var io = new IntersectionObserver(function (es) { es.forEach(function (e) { if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); } }); }, { threshold: 0.12 });
    els.forEach(function (e) { io.observe(e); });
  }
  var pw = document.querySelector('.pf-main input[name="new"]');
  if (pw) {
    var bar = document.querySelector('.pw-meter i'), hint = document.querySelector('.pw-hint');
    pw.addEventListener('input', function () {
      var v = pw.value, s = 0;
      if (v.length >= 8) s++; if (v.length >= 12) s++; if (/[a-z]/.test(v) && /[A-Z]/.test(v)) s++; if (/\d/.test(v)) s++; if (/[^A-Za-z0-9]/.test(v)) s++;
      var L = [['', 0, '#EF4444'], ['Too weak', 20, '#EF4444'], ['Weak', 40, '#F59E0B'], ['Fair', 60, '#EAB308'], ['Good', 80, '#22C55E'], ['Strong', 100, '#16A34A']][v ? Math.max(1, s) : 0];
      bar.style.width = L[1] + '%'; bar.style.background = L[2]; hint.textContent = v ? L[0] + (v.length < 8 ? ' · at least 8 characters needed' : '') : '';
    });
  }
})();
