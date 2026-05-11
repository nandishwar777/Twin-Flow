document.querySelectorAll('[data-password-toggle]').forEach((toggle) => {
  const inputId = toggle.getAttribute('aria-controls');
  const input = inputId ? document.getElementById(inputId) : null;

  if (!input) return;

  const text = toggle.querySelector('.toggle-text');

  const syncState = () => {
    const visible = input.type === 'text';
    toggle.classList.toggle('is-visible', visible);
    toggle.setAttribute('aria-pressed', String(visible));
    toggle.setAttribute('aria-label', visible ? 'Hide password' : 'Show password');
    if (text) {
      text.textContent = visible ? 'Hide' : 'Show';
    }
  };

  toggle.addEventListener('click', () => {
    input.type = input.type === 'password' ? 'text' : 'password';
    syncState();
    input.focus({ preventScroll: true });
    const cursor = input.value.length;
    input.setSelectionRange(cursor, cursor);
  });

  syncState();
});
