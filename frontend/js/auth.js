/* Page-level auth guard. Call on protected pages. */
async function requireAuth() {
  try {
    const user = await api.get('/api/auth/me');
    return user;
  } catch (err) {
    if (err.status === 401) {
      window.location.href = '/login.html';
    }
    return null;
  }
}

async function logout() {
  try { await api.post('/api/auth/logout'); } catch (_) {}
  window.location.href = '/login.html';
}

window.requireAuth = requireAuth;
window.logout = logout;
