(function () {
  var KEY  = 'kr-theme';
  var html = document.documentElement;

  function apply(theme) { html.setAttribute('data-theme', theme); }
  function saved()      { return localStorage.getItem(KEY) || 'light'; }

  apply(saved());

  document.addEventListener('DOMContentLoaded', function () {
    var btn = document.getElementById('theme-toggle');
    if (!btn) return;

    function render(theme) {
      btn.textContent = theme === 'dark' ? '\u2600 Light' : '\u263E Dark';
    }
    render(saved());

    btn.addEventListener('click', function () {
      var next = saved() === 'dark' ? 'light' : 'dark';
      localStorage.setItem(KEY, next);
      apply(next);
      render(next);
    });
  });
})();
