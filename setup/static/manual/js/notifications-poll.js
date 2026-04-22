(function () {
  var POLL_MS = 5000;

  function refreshDropdown(dropList) {
    fetch('/notifications/recent/', { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data || !dropList) return;
        dropList.innerHTML = '';
        var items = data.notifications || [];
        items.forEach(function (n) {
          dropList.appendChild(window._KRNotifUI.buildDropItem(n));
        });
        if (!items.length) {
          dropList.innerHTML = '<div class="kr-notif-item" style="color:var(--text-muted)">No notifications yet.</div>';
        }
      })
      .catch(function () {});
  }

  function poll() {
    var ui = window._KRNotifUI;
    if (!ui) return;
    fetch('/notifications/unread/', { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data) return;
        var notifications = data.notifications || [];
        var lastSeen = ui.getLastSeenId();
        var maxId = lastSeen;
        notifications.forEach(function (n) {
          ui.seen.add(n.id);
          if (typeof n.id === 'number' && n.id > maxId) maxId = n.id;
        });
        var fresh = notifications.filter(function (n) {
          return typeof n.id === 'number' && n.id > lastSeen;
        });
        fresh.forEach(function (n) {
          ui.showToast(n);
          if (ui.KARMA_EVENTS.includes(n.event)) {
            var delta = typeof n.karma_delta === 'number' ? n.karma_delta : 0;
            if (delta !== 0 && window.KarmaFX) {
              KarmaFX.fire(delta, document.querySelector('.kr-nav__karma'));
            }
          }
        });
        ui.setLastSeenId(maxId);
        ui.updateBell(data.unread_count || 0);
        var dropdown = document.getElementById('notif-dropdown');
        var dropList = document.getElementById('notif-drop-list');
        if (dropList && dropdown && dropdown.classList.contains('open')) {
          refreshDropdown(dropList);
        }
      })
      .catch(function () {});
  }

  window._KRNotifPoll = { refreshDropdown: refreshDropdown };

  document.addEventListener('DOMContentLoaded', function () {
    poll();
    setInterval(poll, POLL_MS);
  });
})();
