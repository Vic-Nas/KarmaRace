(function () {
  const KEY = 'kr-theme';
  const html = document.documentElement;

  function apply(theme) {
    html.setAttribute('data-theme', theme);
  }

  function saved() {
    return localStorage.getItem(KEY) || 'light';
  }

  apply(saved());

  document.addEventListener('DOMContentLoaded', function () {
    const btn = document.getElementById('theme-toggle');
    if (!btn) return;
    btn.textContent = saved() === 'dark' ? '☀ Light' : '☾ Dark';
    btn.addEventListener('click', function () {
      const next = saved() === 'dark' ? 'light' : 'dark';
      localStorage.setItem(KEY, next);
      apply(next);
      btn.textContent = next === 'dark' ? '☀ Light' : '☾ Dark';
    });
  });
})();
