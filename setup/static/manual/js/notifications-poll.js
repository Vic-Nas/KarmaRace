(function () {
  var POLL_MS = 5000;
  // TASK_CONFIRMED excluded — feed-check-poll.js already handles badge update for that
  var KARMA_EVENTS = ['KARMA_ADJUSTED', 'KARMA_LOW', 'KARMA_RESTORED'];

  var ui = window._KRNotifUI;
  if (!ui) return;

  function updateKarmaBadge(notif) {
    if (KARMA_EVENTS.indexOf(notif.event) === -1) return;
    var delta = notif.karma_delta;
    if (!delta) return;
    var badge = document.getElementById('karma-badge');
    if (!badge) return;
    var cur = parseInt((badge.textContent || '').replace(/[^0-9-]/g, ''), 10);
    if (Number.isFinite(cur)) badge.textContent = '\u2635 ' + (cur + delta);
    if (window.KarmaFX) KarmaFX.fire(delta, badge);
  }

  function poll() {
    var lastId = ui.getLastSeenId();
    fetch('/notifications/unread/?since=' + lastId, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data) return;
        ui.updateBell(data.unread_count);
        var maxId = lastId;
        data.notifications.forEach(function (notif) {
          if (ui.seen.has(notif.id)) return;
          ui.seen.add(notif.id);
          ui.showToast(notif);
          updateKarmaBadge(notif);
          if (notif.id > maxId) maxId = notif.id;
        });
        if (maxId > lastId) ui.setLastSeenId(maxId);
      })
      .catch(function () {});
  }

  window._KRNotifPoll = {
    refreshDropdown: function (dropList) {
      if (!dropList) return;
      fetch('/notifications/recent/', { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (data) {
          if (!data) return;
          dropList.innerHTML = '';
          if (!data.notifications.length) {
            dropList.innerHTML = '<div class="kr-notif-item text-muted">No notifications yet.</div>';
            return;
          }
          data.notifications.forEach(function (n) { dropList.appendChild(ui.buildDropItem(n)); });
        })
        .catch(function () {});
    }
  };

  document.addEventListener('DOMContentLoaded', function () {
    poll();
    setInterval(poll, POLL_MS);
  });
})();