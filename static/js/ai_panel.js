/* clickable timestamps: jump the video to that moment */
document.addEventListener('click', function (e) {
  var b = e.target.closest('[data-seek]'); if (!b) return;
  var v = Array.prototype.find.call(document.querySelectorAll('.vp-player'), function (x) { return x.offsetParent; }); if (!v) return;
  v.currentTime = parseFloat(b.dataset.seek) || 0; var p = v.play(); if (p && p.catch) p.catch(function () {});
  v.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
});

/* switch between the video with the AI's boxes and the original, keeping the position */
document.addEventListener('click', function (e) {
  var b = e.target.closest('[data-vsrc]'); if (!b) return;
  var v = b.closest('.vp').querySelector('.vp-player'), url = v.dataset[b.dataset.vsrc]; if (!url) return;
  var t = v.currentTime, was = !v.paused; v.src = url; v.load();
  v.addEventListener('loadedmetadata', function once() { v.removeEventListener('loadedmetadata', once); v.currentTime = t; if (was) { var p = v.play(); if (p && p.catch) p.catch(function () {}); } });
  b.parentNode.querySelectorAll('[data-vsrc]').forEach(function (x) { x.classList.toggle('on', x === b); });
});
