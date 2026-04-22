(function () {
  var POLL_MS = 5000;
  var KARMA_EVENTS = ['TASK_CONFIRMED', 'KARMA_LOW', 'KARMA_RESTORED'];
  var LAST_SEEN_KEY = 'kr_last_seen_notif_id';
  var seen = new Set();
  var bellBtn, dotEl, countEl, dropdown, dropList;

  function getLastSeenId() {
    var v = parseInt(window.sessionStorage.getItem(LAST_SEEN_KEY) || '0', 10);
    return Number.isFinite(v) ? v : 0;
  }
  function setLastSeenId(id) {
    if (Number.isFinite(id) && id > 0) window.sessionStorage.setItem(LAST_SEEN_KEY, String(id));
  }

  function eventLabel(ev) {
    return ({
      TASK_CONFIRMED: '✓ Task confirmed', TASK_HEALTH_FAILED: '⚠ Task health failed',
      KARMA_LOW: '↓ Karma low', KARMA_RESTORED: '↑ Karma restored',
      WEBHOOK_CHECK: '↗ Webhook check', PROJECT_STATE: '● Project update',
      APPRECIATION: '♥ Appreciation', FLAG_UP_RECEIVED: '⚑ Flag received', FLAG_UP_SENT: '⚑ Flag sent',
    })[ev] || ev;
  }

  function timeAgo(iso) {
    var diff = Math.floor((Date.now() - new Date(iso)) / 1000);
    if (diff < 60) return 'just now';
    if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
    return Math.floor(diff / 86400) + 'd ago';
  }

  function showToast(notif) {
    var t = document.createElement('div');
    t.className = 'kr-toast';
    t.innerHTML = '<div class="kr-toast__event">' + eventLabel(notif.event) + '</div>' +
                  '<div class="kr-toast__msg">' + (notif.summary || '') + '</div>';
    document.body.appendChild(t);
    t.addEventListener('click', function () { dismiss(t); });
    setTimeout(function () { dismiss(t); }, 5000);
  }

  function dismiss(el) {
    el.classList.add('fading');
    el.addEventListener('animationend', function () { el.remove(); }, { once: true });
  }

  function updateBell(count) {
    if (!dotEl || !countEl) return;
    if (count > 0) {
      dotEl.classList.add('visible'); countEl.classList.add('visible');
      countEl.textContent = count > 9 ? '9+' : count;
    } else {
      dotEl.classList.remove('visible'); countEl.classList.remove('visible');
    }
  }

  function getCsrf() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    if (meta) return meta.getAttribute('content');
    var m = document.cookie.match(/csrftoken=([^;]+)/);
    return m ? m[1] : '';
  }

  function buildDropItem(notif) {
    var li = document.createElement('div');
    li.className = 'kr-notif-item' + (notif.read_at ? '' : ' unread');
    li.innerHTML = '<div>' + eventLabel(notif.event) + (notif.summary ? ' — ' + notif.summary : '') + '</div>' +
                   '<div class="kr-notif-item__time">' + timeAgo(notif.created_at) + '</div>';
    li.addEventListener('click', function () {
      fetch('/notifications/mark-read/' + notif.id + '/', { method: 'POST', headers: { 'X-CSRFToken': getCsrf() } });
      li.classList.remove('unread');
    });
    return li;
  }

  window._KRNotifUI = { showToast: showToast, updateBell: updateBell, buildDropItem: buildDropItem,
    getLastSeenId: getLastSeenId, setLastSeenId: setLastSeenId, seen: seen,
    KARMA_EVENTS: KARMA_EVENTS, getCsrf: getCsrf };

  document.addEventListener('DOMContentLoaded', function () {
    bellBtn = document.getElementById('notif-bell');
    dotEl   = document.getElementById('notif-dot');
    countEl = document.getElementById('notif-count');
    dropdown = document.getElementById('notif-dropdown');
    dropList = document.getElementById('notif-drop-list');
    if (!bellBtn) return;

    bellBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      var open = dropdown.classList.toggle('open');
      if (open) window._KRNotifPoll && window._KRNotifPoll.refreshDropdown(dropList);
    });
    document.addEventListener('click', function (e) {
      if (dropdown && !dropdown.contains(e.target) && e.target !== bellBtn)
        dropdown.classList.remove('open');
    });
  });
})();
