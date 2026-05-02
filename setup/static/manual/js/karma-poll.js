// Polls /karma/balance/ and fires KarmaFX animation on change.
(function () {
  var INTERVAL_MS = 15000;
  var badge = document.getElementById('karma-badge');
  if (!badge) return;

  function currentBalance() {
    return parseInt((badge.textContent || '').replace(/[^0-9-]/g, ''), 10);
  }

  setInterval(function () {
    fetch('/karma/balance/', { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data || typeof data.balance !== 'number') return;
        var prev = currentBalance();
        if (!Number.isFinite(prev) || prev === data.balance) return;
        var delta = data.balance - prev;
        badge.textContent = '\u2635 ' + data.balance;
        if (window.KarmaFX) KarmaFX.fire(delta, badge);
      })
      .catch(function () {});
  }, INTERVAL_MS);
})();
