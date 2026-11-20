/* Subtle GSAP motion for the signed-in app pages (dashboard cards, toasts). Purely visual; everything works without GSAP.
   The landing page and the login/register pages have their own scripts (landing.js, auth.js). */
(function () {
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  /* count-up: only animates the number already rendered from the real database value */
  function countUp(el) {
    const raw = (el.dataset.count ?? el.textContent).toString().trim(), suf = el.dataset.suffix || '';
    if (!/^\d+$/.test(raw) || reduce || !window.gsap) return;          // integers only; decimals/dashes are left exactly as rendered
    const end = parseInt(raw, 10);
    const o = { v: 0 };
    gsap.to(o, { v: end, duration: 1.1, ease: 'power2.out', onUpdate: () => { el.textContent = Math.round(o.v) + suf; }, onComplete: () => { el.textContent = end + suf; } });
  }
  function init() {
    if (reduce || !window.gsap) return;
    const g = window.gsap, ST = window.ScrollTrigger; if (ST) g.registerPlugin(ST);
    const reveal = document.querySelectorAll('.cards5 > *, .dashboard-bottom > .card, .content > .card, .stat7 > *, .timeline li');
    reveal.forEach(el => {
      const opts = { y: 22, opacity: 0, duration: .55, ease: 'power2.out', clearProps: 'all' };
      if (ST) g.from(el, { ...opts, scrollTrigger: { trigger: el, start: 'top 92%', once: true } }); else g.from(el, opts);
    });
    document.querySelectorAll('.scard .num, .sc2 .num').forEach(countUp);
    document.querySelectorAll('.toast-lite').forEach(t => g.from(t, { x: 30, opacity: 0, duration: .4, clearProps: 'all' }));
  }
  if (document.readyState === 'complete') init(); else window.addEventListener('load', init);
})();
