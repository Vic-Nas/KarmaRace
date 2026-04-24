(function () {
  document.addEventListener('DOMContentLoaded', function () {
    var form = document.getElementById('prefs-form');
    var saved = document.getElementById('prefs-saved');
    if (!form) return;

    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var data = new FormData(form);
      // Checkboxes not checked won't be in FormData — add explicit 0
      form.querySelectorAll('input[type="checkbox"]').forEach(function (cb) {
        if (!cb.checked) data.set(cb.name, '0');
      });

      fetch('/notifications/preferences/', {
        method: 'POST',
        headers: { 'X-CSRFToken': data.get('csrfmiddlewaretoken') },
        body: data,
      })
      .then(function (r) { return r.json(); })
      .then(function (res) {
        if (res.ok) {
          saved.style.display = 'inline';
          setTimeout(function () { saved.style.display = 'none'; }, 2500);
        }
      })
      .catch(function () {});
    });
  });
})();
