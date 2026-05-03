var FeedCheck = (function () {
  var POLL_MS = 1200;
  var MAX_MS  = 120000;

  function start(statusUrl) {
    var elapsed = 0;
    FeedCheckUI.setCheckButtonDisabled(true);

    var timer = setInterval(function () {
      elapsed += POLL_MS;
      fetch(statusUrl, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (data) {
          if (!data || data.state === 'PENDING') return;
          clearInterval(timer);
          if (data.state === 'CONFIRMED') {
            FeedCheckUI.setBanner('success', 'Check confirmed. Karma transferred.');
            FeedCheckUI.addCompletedBadge();
            FeedCheckUI.applyKarmaUpdate(data);
          } else if (data.state === 'FAILED') {
            var kind = data.result_code === 'not_verified' ? 'warning' : 'danger';
            FeedCheckUI.setBanner(kind, data.detail || 'Check failed. Please retry.');
          } else {
            FeedCheckUI.setBanner('danger', 'Check ended unexpectedly. Please retry.');
          }
          FeedCheckUI.setCheckButtonDisabled(false);
          FeedCheckUI.clearCheckingParam();
        })
        .catch(function () {});

      if (elapsed >= MAX_MS) {
        clearInterval(timer);
        FeedCheckUI.setBanner('warning', 'Verification timed out. Please retry.');
        FeedCheckUI.setCheckButtonDisabled(false);
        FeedCheckUI.clearCheckingParam();
      }
    }, POLL_MS);
  }

  function bindForm(selector, checkUrl, statusUrl) {
    var form = document.querySelector(selector);
    if (!form) return;

    form.addEventListener('submit', function (evt) {
      evt.preventDefault();
      FeedCheckUI.setCheckButtonDisabled(true);
      FeedCheckUI.setBanner('info', 'Starting verification...');

      fetch(checkUrl, {
        method: 'POST',
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
        body: new FormData(form),
      })
        .then(function (r) {
          if (r.ok) return r.json();
          return r.json().catch(function () { return null; }).then(function (d) {
            return { state: 'FAILED', detail: (d && d.detail) || 'Check request failed.' };
          });
        })
        .then(function (data) {
          if (!data || !data.state) {
            FeedCheckUI.setBanner('danger', 'Check request failed. Please retry.');
            FeedCheckUI.setCheckButtonDisabled(false);
            return;
          }
          if (data.state === 'PENDING') {
            FeedCheckUI.setBanner('info', data.detail || 'Verification in progress...');
            start(statusUrl);
            return;
          }
          if (data.state === 'CONFIRMED') {
            FeedCheckUI.setBanner('success', data.detail || 'Check confirmed. Karma transferred.');
            FeedCheckUI.addCompletedBadge();
            FeedCheckUI.applyKarmaUpdate(data);
          } else {
            var kind = data.result_code === 'not_verified' ? 'warning' : 'danger';
            FeedCheckUI.setBanner(kind, data.detail || 'Check failed. Please retry.');
          }
          FeedCheckUI.setCheckButtonDisabled(false);
          FeedCheckUI.clearCheckingParam();
        })
        .catch(function () {
          FeedCheckUI.setBanner('danger', 'Network error. Please retry.');
          FeedCheckUI.setCheckButtonDisabled(false);
        });
    });
  }

  return { start: start, bindForm: bindForm };
})();
