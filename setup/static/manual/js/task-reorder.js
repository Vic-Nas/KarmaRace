(function () {
  var list = document.getElementById('mytask-list');
  if (!list) return;

  var dragging = null;

  function getCsrf() {
    var m = document.cookie.match(/csrftoken=([^;]+)/);
    return m ? m[1] : '';
  }

  function saveOrder() {
    var ids = Array.from(list.querySelectorAll('.mytask-item')).map(function (el) {
      return parseInt(el.dataset.id, 10);
    });
    fetch('/tasks/reorder/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrf() },
      body: JSON.stringify({ ids: ids }),
    }).catch(function () {});
  }

  function onDragStart(e) {
    dragging = e.currentTarget.closest('.mytask-item');
    dragging.classList.add('dragging');
    e.dataTransfer.effectAllowed = 'move';
  }

  function onDragEnd() {
    if (dragging) dragging.classList.remove('dragging');
    list.querySelectorAll('.mytask-item').forEach(function (el) {
      el.classList.remove('drag-over');
    });
    dragging = null;
    saveOrder();
  }

  function onDragOver(e) {
    e.preventDefault();
    var target = e.target.closest('.mytask-item');
    if (!target || target === dragging) return;
    list.querySelectorAll('.mytask-item').forEach(function (el) {
      el.classList.remove('drag-over');
    });
    target.classList.add('drag-over');
    var rect  = target.getBoundingClientRect();
    var after = e.clientY > rect.top + rect.height / 2;
    list.insertBefore(dragging, after ? target.nextSibling : target);
  }

  list.querySelectorAll('.mytask__handle').forEach(function (handle) {
    handle.setAttribute('draggable', 'true');
    handle.addEventListener('dragstart', onDragStart);
    handle.addEventListener('dragend',   onDragEnd);
  });

  list.addEventListener('dragover', onDragOver);
})();
