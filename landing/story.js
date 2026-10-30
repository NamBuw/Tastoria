// A clearly labelled editorial example; no API call or personal data collection.
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

// Web can be published before its signed Android build is ready.
const download = document.getElementById('android-download');
if (download) {
  const url = download.getAttribute('href');
  const label = download.textContent;
  const checkDownload = async () => {
    try {
      const response = await fetch(url, { method: 'HEAD', cache: 'no-store' });
      if (response.ok) {
        download.setAttribute('href', url);
        download.removeAttribute('aria-disabled');
        download.textContent = label;
        return;
      }
      download.removeAttribute('href');
      download.setAttribute('aria-disabled', 'true');
      download.textContent = 'Android 0.1.2 đang được cập nhật…';
    } catch {
      // Network failure: retain the ordinary download link and retry later.
    }
    setTimeout(checkDownload, 30000);
  };
  checkDownload();
}
