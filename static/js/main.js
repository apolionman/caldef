// Toast notification
function showToast(message, type = 'default') {
  const existing = document.querySelector('.toast');
  if (existing) existing.remove();

  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.textContent = message;
  document.body.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(-50%) translateY(10px)';
    toast.style.transition = 'all 0.2s ease';
    setTimeout(() => toast.remove(), 200);
  }, 3000);
}

// Achievement toast notifications (used on log_food and dashboard)
function handleAchievements(list) {
  if (!list || !list.length) return;
  list.forEach((a, i) => {
    setTimeout(() => {
      const t = document.createElement('div');
      t.className = 'achievement-toast';
      t.innerHTML = `<span class="ach-icon">${a.icon}</span><div><b>Achievement Unlocked!</b><br>${a.name}</div>`;
      document.body.appendChild(t);
      setTimeout(() => { t.style.opacity = '0'; setTimeout(() => t.remove(), 400); }, 4000);
    }, i * 600);
  });
}

// Auto-dismiss flash messages
document.querySelectorAll('.flash').forEach(el => {
  setTimeout(() => {
    el.style.opacity = '0';
    el.style.transform = 'translateX(20px)';
    el.style.transition = 'all 0.3s ease';
    setTimeout(() => el.remove(), 300);
  }, 5000);
});
