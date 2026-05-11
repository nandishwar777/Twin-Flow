/* Theme toggle: light/dark, persisted in localStorage */
(function() {
  const KEY = 'twinflow-theme';

  function applyStored() {
    const stored = localStorage.getItem(KEY) || 'light';
    if (document.body) {
      document.body.classList.toggle('dark', stored === 'dark');
    }
    if (document.documentElement) {
      document.documentElement.classList.toggle('dark', stored === 'dark');
    }
    updateIcons();
  }

  window.toggleTheme = function() {
    const isDark = !document.body.classList.contains('dark');
    document.body.classList.toggle('dark', isDark);
    document.documentElement.classList.toggle('dark', isDark);
    localStorage.setItem(KEY, isDark ? 'dark' : 'light');
    updateIcons();
  };

  function updateIcons() {
    const isDark = document.body && document.body.classList.contains('dark');
    document.querySelectorAll('[data-theme-icon]').forEach(el => {
      el.innerHTML = isDark ? '&#9728;' : '&#9790;';
    });
    document.querySelectorAll('[data-theme-label]').forEach(el => {
      el.textContent = isDark ? 'Light mode' : 'Dark mode';
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', applyStored);
  } else {
    applyStored();
  }
})();
