document.querySelectorAll('.toast-lite').forEach((t, i) => setTimeout(() => { t.style.transition = '.4s'; t.style.opacity = 0; setTimeout(() => t.remove(), 400); }, 7000 + i * 600));
/* collapsible sidebar: remembers the choice on desktop, starts closed on phones */
const shell = document.getElementById('shell'), burger = document.getElementById('burger');
if (shell && burger) {
  const small = () => window.innerWidth < 992;
  if (small() || localStorage.getItem('crc-side') === 'closed') shell.classList.add('collapsed');
  burger.onclick = () => { shell.classList.toggle('collapsed'); if (!small()) localStorage.setItem('crc-side', shell.classList.contains('collapsed') ? 'closed' : 'open'); };
  document.getElementById('scrim').onclick = () => shell.classList.add('collapsed');
}
/* show/hide password */
document.querySelectorAll('[data-showpw]').forEach(b => b.onclick = () => { const i = document.getElementById(b.dataset.showpw); i.type = i.type === 'password' ? 'text' : 'password'; });
/* decorative background videos: keep them still for people who prefer reduced motion */
if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) document.querySelectorAll('video[data-bgvideo]').forEach(v => { v.removeAttribute('autoplay'); v.pause(); });
