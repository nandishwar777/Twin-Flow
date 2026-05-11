/* Renders the sidebar and wires up logout / theme toggle. Call after requireAuth. */
function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function renderUserAvatarMarkup(user, className = 'user-avatar') {
  const initials = (user.username || 'U').slice(0, 2).toUpperCase();
  const label = escapeHtml(user.username || 'User');
  if (user.profilePhoto) {
    return `
      <div class="${className} has-photo" data-user-avatar>
        <img src="${user.profilePhoto}" alt="${label} profile photo" />
      </div>
    `;
  }
  return `
    <div class="${className}" data-user-avatar aria-label="${label} initials">
      ${escapeHtml(initials)}
    </div>
  `;
}

function updateLayoutUser(user) {
  const avatarHost = document.querySelector('[data-sidebar-avatar-host]');
  const nameEl = document.querySelector('[data-sidebar-name]');
  const emailEl = document.querySelector('[data-sidebar-email]');

  if (avatarHost) {
    avatarHost.innerHTML = renderUserAvatarMarkup(user);
  }
  if (nameEl) {
    nameEl.textContent = user.username || 'TwinFlow User';
  }
  if (emailEl) {
    emailEl.textContent = user.email || '';
  }
}

function renderLayout(user, activePage) {
  const nav = [
    { href: '/dashboard.html', label: 'Dashboard', key: 'dashboard', icon: '&#10022;' },
    { href: '/log.html', label: 'Daily Log', key: 'log', icon: '&#9998;' },
    { href: '/schedule.html', label: 'Schedule', key: 'schedule', icon: '&#128197;' },
    { href: '/history.html', label: 'History', key: 'history', icon: '&#8987;' },
    { href: '/analytics.html', label: 'Analytics', key: 'analytics', icon: '&#128200;' },
    { href: '/settings.html', label: 'Settings', key: 'settings', icon: '&#9881;' },
    { href: '/about.html', label: 'About Us', key: 'about', icon: '&#9432;' },
  ];

  const sidebar = `
    <aside class="sidebar">
      <div class="sidebar-brand">
        <span class="sidebar-brand-icon">&#9889;</span>
        <div>
          <span>TwinFlow</span>
          <small>Your digital twin</small>
        </div>
      </div>
      <div class="sidebar-nav">
        ${nav.map((item) => `
          <a href="${item.href}" class="nav-item${activePage === item.key ? ' active' : ''}">
            <span class="icon">${item.icon}</span>
            <span>${item.label}</span>
          </a>
        `).join('')}
      </div>
      <div class="sidebar-footer">
        <div class="user-row">
          <div data-sidebar-avatar-host>${renderUserAvatarMarkup(user)}</div>
          <div class="user-info">
            <div class="name" data-sidebar-name>${escapeHtml(user.username)}</div>
            <div class="email" data-sidebar-email>${escapeHtml(user.email)}</div>
          </div>
        </div>
        <div class="row sidebar-actions">
          <button class="btn btn-ghost sidebar-action-btn" onclick="toggleTheme()" title="Switch theme">
            <span class="sidebar-action-icon" data-theme-icon aria-hidden="true">&#9728;</span>
            <span data-theme-label>Dark mode</span>
          </button>
          <button class="btn btn-ghost sidebar-action-btn" onclick="logout()" title="Logout">
            <span class="sidebar-action-icon" aria-hidden="true">&#10502;</span>
            <span>Logout</span>
          </button>
        </div>
      </div>
    </aside>
  `;

  const shell = document.createElement('div');
  shell.className = 'app-shell';
  shell.innerHTML = sidebar + '<main class="main-content" id="main-content"></main>';
  document.body.appendChild(shell);
  return document.getElementById('main-content');
}

window.escapeHtml = escapeHtml;
window.renderUserAvatarMarkup = renderUserAvatarMarkup;
window.updateLayoutUser = updateLayoutUser;
window.renderLayout = renderLayout;
