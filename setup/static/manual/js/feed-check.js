var FeedCheckUI = (function () {
  function readRewardDelta() {
    var el = document.querySelector('.task-card__reward strong');
    if (!el) return 0;
    var v = parseInt((el.textContent || '').trim(), 10);
    return Number.isFinite(v) ? v : 0;
  }

  function updateKarmaBadge(balance) {
    if (typeof balance !== 'number') return;
    var badge = document.getElementById('karma-badge');
    if (badge) badge.textContent = '\u2635 ' + balance;
  }

  function updateKarmaBadgeByDelta(delta) {
    if (typeof delta !== 'number' || delta === 0) return;
    var badge = document.getElementById('karma-badge');
    if (!badge) return;
    var cur = parseInt((badge.textContent || '').replace(/[^0-9-]/g, ''), 10);
    if (Number.isFinite(cur)) badge.textContent = '\u2635 ' + (cur + delta);
  }

  function triggerKarmaFx(delta) {
    if (typeof delta !== 'number' || delta === 0) return;
    if (window.KarmaFX && typeof KarmaFX.fire === 'function') {
      KarmaFX.fire(delta, document.getElementById('karma-badge'));
    }
  }

  function applyKarmaUpdate(data) {
    if (!data) return;
    var delta = typeof data.karma_delta === 'number' ? data.karma_delta : readRewardDelta();
    triggerKarmaFx(delta);
    if (typeof data.karma_balance === 'number') {
      updateKarmaBadge(data.karma_balance);
    } else {
      updateKarmaBadgeByDelta(delta);
    }
  }

  function setBanner(kind, text) {
    var banner = document.getElementById('check-loading-banner');
    if (!banner) return;
    banner.style.display = '';
    banner.classList.remove('alert-info', 'alert-success', 'alert-danger', 'alert-warning');
    banner.classList.add('alert-' + (kind === 'success' ? 'success' : kind === 'info' ? 'info' : kind === 'warning' ? 'warning' : 'danger'));
    banner.textContent = text;
  }

  function setCheckButtonDisabled(disabled) {
    var btn = document.querySelector('#feed-check-form button[type="submit"]');
    if (btn) btn.disabled = !!disabled;
  }

  function addCompletedBadge() {
    var reward = document.querySelector('.task-card__reward');
    if (!reward || reward.querySelector('.badge-success')) return;
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

  return {
    applyKarmaUpdate: applyKarmaUpdate,
    setBanner: setBanner,
    setCheckButtonDisabled: setCheckButtonDisabled,
    addCompletedBadge: addCompletedBadge,
    clearCheckingParam: clearCheckingParam,
  };
})();
