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
