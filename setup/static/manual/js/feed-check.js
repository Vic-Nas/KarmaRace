var FeedCheck = (function () {
  function setBanner(kind, text) {
    var banner = document.getElementById('check-loading-banner');
    if (!banner) return;

    banner.style.display = '';

    banner.classList.remove('alert-info', 'alert-success', 'alert-danger', 'alert-warning');
    if (kind === 'success') {
      banner.classList.add('alert-success');
    } else if (kind === 'warning') {
      banner.classList.add('alert-warning');
    } else {
      banner.classList.add('alert-danger');
    }
    banner.textContent = text;
  }

  function setCheckButtonDisabled(disabled) {
    var btn = document.querySelector('#feed-check-form button[type="submit"]');
    if (!btn) return;
    btn.disabled = !!disabled;
  }

  function addCompletedBadge() {
    var reward = document.querySelector('.task-card__reward');
    if (!reward) return;
    if (reward.querySelector('.badge-success')) return;

    var badge = document.createElement('span');
    badge.className = 'badge badge-success';
    badge.style.marginLeft = '0.4rem';
    badge.textContent = 'Completed';
    reward.appendChild(badge);
  }

  function clearCheckingParam() {
    var url = new URL(window.location.href);
    if (!url.searchParams.has('checking_task')) return;
    url.searchParams.delete('checking_task');
    window.history.replaceState({}, '', url.toString());
  }

  function start(statusUrl) {
    var pollMs = 1200;
    var maxMs = 30000;
    var elapsed = 0;

    setCheckButtonDisabled(true);

    var timer = setInterval(function () {
      elapsed += pollMs;
      fetch(statusUrl, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (data) {
          if (data && data.state && data.state !== 'PENDING') {
            clearInterval(timer);
            if (data.state === 'CONFIRMED') {
              setBanner('success', 'Check confirmed. Karma transferred.');
              addCompletedBadge();
            } else if (data.state === 'FAILED') {
              setBanner('danger', data.detail || 'Check failed. Please retry.');
            } else {
              setBanner('danger', 'Check ended unexpectedly. Please retry.');
            }
            setCheckButtonDisabled(false);
            clearCheckingParam();
          }
        })
        .catch(function () {});
      if (elapsed >= maxMs) {
        clearInterval(timer);
        setBanner('warning', 'Verification timed out. Please retry.');
        setCheckButtonDisabled(false);
        clearCheckingParam();
      }
    }, pollMs);
  }

  function bindForm(selector, checkUrl, statusUrl) {
    var form = document.querySelector(selector);
    if (!form) return;

    form.addEventListener('submit', function (evt) {
      evt.preventDefault();

      setCheckButtonDisabled(true);
      setBanner('info', 'Starting verification...');

      fetch(checkUrl, {
        method: 'POST',
        headers: {
          'X-Requested-With': 'XMLHttpRequest'
        },
        body: new FormData(form)
      })
        .then(function (r) {
          if (r.ok) return r.json();
          return r.json().catch(function () { return null; }).then(function (data) {
            return { state: 'FAILED', detail: (data && data.detail) || 'Check request failed.' };
          });
        })
        .then(function (data) {
          if (!data || !data.state) {
            setBanner('danger', 'Check request failed. Please retry.');
            setCheckButtonDisabled(false);
            return;
          }

          if (data.state === 'PENDING') {
            setBanner('info', data.detail || 'Verification in progress...');
            start(statusUrl);
            return;
          }

          if (data.state === 'CONFIRMED') {
            setBanner('success', data.detail || 'Check confirmed. Karma transferred.');
            addCompletedBadge();
          } else {
            setBanner('danger', data.detail || 'Check failed. Please retry.');
          }
          setCheckButtonDisabled(false);
          clearCheckingParam();
        })
        .catch(function () {
          setBanner('danger', 'Network error while starting check. Please retry.');
          setCheckButtonDisabled(false);
        });
    });
  }

  return { start: start, bindForm: bindForm };
})();
