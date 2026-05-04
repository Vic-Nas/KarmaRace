(function () {
  function startPollingIfNeeded(form) {
    var checkingUrl = form.getAttribute('data-checking-status-url');
    if (checkingUrl) FeedCheck.start(checkingUrl);
  }

  function bindFormIfPresent(form) {
    var checkUrl = form.getAttribute('data-check-url');
    var statusUrl = form.getAttribute('data-status-url');
    if (checkUrl && statusUrl) FeedCheck.bindForm('#' + form.id, checkUrl, statusUrl);
  }

  function wireDifficultyToggle() {
    var btn = document.getElementById('feed-check-btn');
    var radios = document.querySelectorAll('.diff-radio-input');
    if (!btn || !radios.length) return;

    function update() {
      var picked = document.querySelector('.diff-radio-input:checked');
      btn.disabled = !picked;
    }

    radios.forEach(function (r) { r.addEventListener('change', update); });
    update();
  }

  document.addEventListener('DOMContentLoaded', function () {
    var form = document.getElementById('feed-check-form');
    if (!form) return;
    startPollingIfNeeded(form);
    bindFormIfPresent(form);
    wireDifficultyToggle();
  });
})();
