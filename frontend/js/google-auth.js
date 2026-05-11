(function () {
  const GOOGLE_LOAD_TIMEOUT_MS = 10000;

  function waitForGoogleIdentity() {
    if (window.google && window.google.accounts && window.google.accounts.id) {
      return Promise.resolve(window.google.accounts.id);
    }

    return new Promise((resolve, reject) => {
      const startedAt = Date.now();
      const timer = window.setInterval(() => {
        if (window.google && window.google.accounts && window.google.accounts.id) {
          window.clearInterval(timer);
          resolve(window.google.accounts.id);
          return;
        }

        if (Date.now() - startedAt >= GOOGLE_LOAD_TIMEOUT_MS) {
          window.clearInterval(timer);
          reject(new Error('Google sign-in could not be loaded right now.'));
        }
      }, 120);
    });
  }

  function setHint(hintId, message, isError) {
    const hint = hintId ? document.getElementById(hintId) : null;
    if (!hint) return;
    hint.textContent = message || '';
    hint.classList.toggle('is-error', Boolean(isError));
  }

  function renderUnavailableButton(container, label) {
    container.innerHTML = `
      <button type="button" class="btn btn-outline btn-block google-fallback-btn" disabled>
        ${label}
      </button>
    `;
  }

  function setSubmitButtonState(buttonId, nextLabel) {
    const button = buttonId ? document.getElementById(buttonId) : null;
    if (!button) return null;

    if (!button.dataset.originalText) {
      button.dataset.originalText = button.textContent;
    }

    button.disabled = true;
    button.textContent = nextLabel;
    return button;
  }

  function resetSubmitButtonState(button) {
    if (!button) return;
    button.disabled = false;
    button.textContent = button.dataset.originalText || button.textContent;
  }

  async function initGoogleButton(options) {
    const container = document.getElementById(options.containerId);
    if (!container) return;

    renderUnavailableButton(container, 'Loading Google...');

    try {
      const config = await api.get('/api/auth/google/config');
      if (!config.enabled || !config.clientId) {
        renderUnavailableButton(container, 'Continue with Google');
        setHint(
          options.hintId,
          config.message || 'Google sign-in is not configured yet.',
          true,
        );
        return;
      }

      const googleId = await waitForGoogleIdentity();
      container.innerHTML = '';

      googleId.initialize({
        client_id: config.clientId,
        callback: async ({ credential }) => {
          if (!credential) {
            showToast('Google did not return a valid sign-in credential.', 'error');
            return;
          }

          const submitButton = setSubmitButtonState(
            options.loadingButtonId,
            options.loadingText || 'Please wait...',
          );

          try {
            await api.post('/api/auth/google', { credential });
            window.location.href = options.redirectTo || '/dashboard.html';
          } catch (err) {
            resetSubmitButtonState(submitButton);
            showToast(err.message || 'Google sign-in failed', 'error');
          }
        },
      });

      googleId.renderButton(container, {
        theme: document.body.classList.contains('dark') ? 'outline' : 'filled_blue',
        size: 'large',
        text: options.text || 'continue_with',
        shape: 'pill',
        width: Math.max(260, Math.min(options.maxWidth || 392, container.clientWidth || 392)),
        logo_alignment: 'left',
      });

      setHint(
        options.hintId,
        options.readyMessage || 'Use your Google account to continue instantly.',
        false,
      );
    } catch (err) {
      renderUnavailableButton(container, 'Google unavailable');
      setHint(
        options.hintId,
        err.message || 'Google sign-in could not be loaded right now.',
        true,
      );
    }
  }

  window.twinFlowGoogleAuth = {
    initGoogleButton,
  };
})();
