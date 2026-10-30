// Progressive enhancement: content and links work with JavaScript or WebGL disabled.
const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
const ideas = {
  egg: ['Trứng sốt cà chua', 'Trứng mềm, cà chua chín và một chút hành. Một món quen để bắt đầu bữa cơm.'],
  tofu: ['Đậu phụ sốt nấm', 'Đậu phụ, nấm và hành lá. Thêm chút nước sốt để món ăn đậm đà, hợp cùng cơm nóng.'],
  greens: ['Rau xanh xào tỏi', 'Rau xanh và tỏi thơm. Một đĩa rau đơn giản để mâm cơm thêm màu sắc.'],
};
document.querySelectorAll('[data-ingredient]').forEach(button => {
  button.addEventListener('click', () => {
    const idea = ideas[button.dataset.ingredient];
    if (!idea) return;
    document.querySelectorAll('[data-ingredient]').forEach(other => other.setAttribute('aria-pressed', String(other === button)));
    document.getElementById('recipe-name').textContent = idea[0];
    document.getElementById('recipe-description').textContent = idea[1];
  });
});

const reveals = new IntersectionObserver(entries => {
  for (const entry of entries) {
    if (!entry.isIntersecting) continue;
    if (!reducedMotion.matches) entry.target.animate(
      [{ opacity: .3, transform: 'translateY(30px)' }, { opacity: 1, transform: 'translateY(0)' }],
      { duration: 650, easing: 'cubic-bezier(.2,.65,.2,1)' },
    );
    reveals.unobserve(entry.target);
  }
}, { threshold: .12 });
document.querySelectorAll('.reveal').forEach(element => reveals.observe(element));

const download = document.getElementById('android-download');
if (download) {
  const url = download.getAttribute('href');
  const label = download.innerHTML;
  const checkDownload = async () => {
    try {
      // A CDN may retain an earlier 404 while the signed APK is building.
      const readyUrl = `${url}?ready=${Date.now()}`;
      const response = await fetch(readyUrl, { method: 'HEAD', cache: 'no-store' });
      if (response.ok) {
        download.setAttribute('href', readyUrl);
        download.removeAttribute('aria-disabled');
        download.innerHTML = label;
        return;
      }
      download.removeAttribute('href');
      download.setAttribute('aria-disabled', 'true');
      download.textContent = 'Bản Android mới đang được cập nhật…';
    } catch { /* Retry after a temporary network error. */ }
    setTimeout(checkDownload, 30000);
  };
  checkDownload();
}
