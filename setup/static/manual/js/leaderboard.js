(function () {
  var table = document.getElementById('lb-table');
  var searchInput = document.getElementById('lb-search-input');

  function isSearchActive() {
    return searchInput && searchInput.value.trim().length > 0;
  }

  function rankClass(rank) {
    if (rank === 1) return 'lb-row__rank--gold';
    if (rank === 2) return 'lb-row__rank--silver';
    if (rank === 3) return 'lb-row__rank--bronze';
    return '';
  }

  function buildRow(row) {
    var a = document.createElement('a');
    a.className = 'lb-row';
    a.href = '/u/' + encodeURIComponent(row.username) + '/';

    var rank = document.createElement('span');
    rank.className = 'lb-row__rank ' + rankClass(row.rank);
    rank.textContent = '#' + row.rank;

    var username = document.createElement('span');
    username.className = 'lb-row__username';
    username.textContent = row.username;

    var karma = document.createElement('span');
    karma.className = 'lb-row__karma';
    karma.textContent = '\u262F ' + row.karma; /* ☯ yin-yang to match navbar */

    a.appendChild(rank);
    a.appendChild(username);
    a.appendChild(karma);
    return a;
  }

  function renderRows(rows) {
    if (!table) return;
    table.innerHTML = '';
    if (!rows || !rows.length) {
      var empty = document.createElement('div');
      empty.className = 'lb-empty';
      empty.textContent = 'No results.';
      table.appendChild(empty);
      return;
    }
    rows.forEach(function (row) { table.appendChild(buildRow(row)); });
  }

  function startSSE() {
    if (isSearchActive() || !window.EventSource) return;
    var es = new EventSource('/leaderboard/stream/');
    es.onmessage = function (e) {
      if (isSearchActive()) return;
      try { renderRows(JSON.parse(e.data)); } catch (_) {}
    };
    es.onerror = function () {
      es.close();
      setTimeout(startSSE, 15000);
    };
  }

  document.addEventListener('DOMContentLoaded', startSSE);
})();