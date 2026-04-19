(function () {
  const POLL_MS = 5000;
  const KARMA_EVENTS = ['TASK_CONFIRMED', 'KARMA_LOW', 'KARMA_RESTORED'];
  const LAST_SEEN_KEY = 'kr_last_seen_notif_id';
  const seen = new Set();
  let bellBtn, dotEl, countEl, dropdown, dropList;

  function getLastSeenId() {
    const value = parseInt(window.sessionStorage.getItem(LAST_SEEN_KEY) || '0', 10);
    return Number.isFinite(value) ? value : 0;
  }

  function setLastSeenId(id) {
    if (!Number.isFinite(id) || id <= 0) return;
    window.sessionStorage.setItem(LAST_SEEN_KEY, String(id));
  }

  function eventLabel(ev) {
    return {
      TASK_CONFIRMED:     '✓ Task confirmed',
      TASK_HEALTH_FAILED: '⚠ Task health failed',
      KARMA_LOW:          '↓ Karma low',
      KARMA_RESTORED:     '↑ Karma restored',
      WEBHOOK_CHECK:      '↗ Webhook check',
      PROJECT_STATE:      '● Project update',
      APPRECIATION:       '♥ Appreciation',
      FLAG_UP_RECEIVED:   '⚑ Flag received',
      FLAG_UP_SENT:       '⚑ Flag sent',
    }[ev] || ev;
  }

  function eventIcon(ev) {
    return {
      TASK_CONFIRMED: '✔', TASK_HEALTH_FAILED: '⚠', KARMA_LOW: '↓',
      KARMA_RESTORED: '↑', WEBHOOK_CHECK: '↗', PROJECT_STATE: '◉', APPRECIATION: '♥',
      FLAG_UP_RECEIVED: '⚑', FLAG_UP_SENT: '⚐',
    }[ev] || '●';
  }

  function timeAgo(iso) {
    const diff = Math.floor((Date.now() - new Date(iso)) / 1000);
    if (diff < 60) return 'just now';
    if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
    return Math.floor(diff / 86400) + 'd ago';
  }

  function showToast(notif) {
    const t = document.createElement('div');
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

  function updateBell(unreadCount) {
    if (!dotEl || !countEl) return;
    if (unreadCount > 0) {
      dotEl.classList.add('visible');
      countEl.textContent = unreadCount > 9 ? '9+' : unreadCount;
      countEl.classList.add('visible');
    } else {
      dotEl.classList.remove('visible');
      countEl.classList.remove('visible');
    }
  }

  function buildDropdownItem(notif) {
    const li = document.createElement('div');
    li.className = 'kr-notif-item' + (notif.read_at ? '' : ' unread');
    li.innerHTML = '<div>' + eventLabel(notif.event) + (notif.summary ? ' — ' + notif.summary : '') + '</div>' +
                   '<div class="kr-notif-item__time">' + timeAgo(notif.created_at) + '</div>';
    li.addEventListener('click', function () {
      fetch('/notifications/mark-read/' + notif.id + '/', { method: 'POST', headers: { 'X-CSRFToken': getCsrf() } });
      li.classList.remove('unread');
    });
    return li;
  }

  function getCsrf() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    if (meta) return meta.getAttribute('content');
    const m = document.cookie.match(/csrftoken=([^;]+)/);
    return m ? m[1] : '';
  }

  function poll() {
    fetch('/notifications/unread/', { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data) return;

        const notifications = (data.notifications || []);
        const lastSeen = getLastSeenId();
        let maxId = lastSeen;
        notifications.forEach(function (n) {
          if (!seen.has(n.id)) seen.add(n.id);
          if (typeof n.id === 'number' && n.id > maxId) maxId = n.id;
        });

        const fresh = notifications.filter(function (n) {
          return typeof n.id === 'number' && n.id > lastSeen;
        });

        fresh.forEach(function (n) {
          showToast(n);
          if (KARMA_EVENTS.includes(n.event)) {
            const delta = (typeof n.karma_delta === 'number') ? n.karma_delta : 0;
            if (delta !== 0) KarmaFX.fire(delta, document.querySelector('.kr-nav__karma'));
          }
        });

        setLastSeenId(maxId);
        updateBell(data.unread_count || 0);
        if (dropList && dropdown && dropdown.classList.contains('open')) {
          refreshDropdown();
        }
      })
      .catch(function () {});
  }

  function refreshDropdown() {
    fetch('/notifications/recent/', { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data || !dropList) return;
        dropList.innerHTML = '';
        (data.notifications || []).forEach(function (n) {
          dropList.appendChild(buildDropdownItem(n));
        });
        if (!data.notifications.length) {
          dropList.innerHTML = '<div class="kr-notif-item" style="color:var(--text-muted)">No notifications yet.</div>';
        }
      })
      .catch(function () {});
  }

  document.addEventListener('DOMContentLoaded', function () {
    bellBtn  = document.getElementById('notif-bell');
    dotEl    = document.getElementById('notif-dot');
    countEl  = document.getElementById('notif-count');
    dropdown = document.getElementById('notif-dropdown');
    dropList = document.getElementById('notif-drop-list');

    if (!bellBtn) return;

    bellBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      const open = dropdown.classList.toggle('open');
      if (open) refreshDropdown();
    });

    document.addEventListener('click', function (e) {
      if (dropdown && !dropdown.contains(e.target) && e.target !== bellBtn) {
        dropdown.classList.remove('open');
      }
    });

    poll();
    setInterval(poll, POLL_MS);
  });
})();
