(function () {
  document.addEventListener('DOMContentLoaded', function () {
    var typeSelect = document.getElementById('id_type');
    var secretRow = document.getElementById('webhook-secret-row');
    var descInput = document.getElementById('id_description');
    var targetInput = document.getElementById('id_target_id');
    var targetInputRow = document.getElementById('target-input-row');
    var targetHelpText = document.getElementById('target-help-text');
    var githubTargetRow = document.getElementById('github-target-row');
    var githubTargetSelect = document.getElementById('id_github_target_select');
    var slugInput = document.getElementById('id_slug');
    var slugAvailability = document.getElementById('slug-availability');
    var saveBtn = document.getElementById('task-save-btn');
    if (!typeSelect) return;

    function isGithubType() {
      return typeSelect.value === 'GITHUB_STAR' || typeSelect.value === 'GITHUB_FORK';
    }

    function syncGithubTargetToInput() {
      if (!targetInput || !githubTargetSelect) return;
      if (isGithubType()) {
        targetInput.value = githubTargetSelect.value || '';
      }
    }

    function update() {
      var isWebhook = typeSelect.value === 'WEBHOOK';
      var isGithub = isGithubType();
      var useGithubDropdown = isGithub;
      secretRow.style.display = isWebhook ? '' : 'none';

      if (targetInputRow) {
        targetInputRow.style.display = useGithubDropdown ? 'none' : '';
      }
      if (githubTargetRow) {
        githubTargetRow.style.display = isGithub ? '' : 'none';
      }

      if (useGithubDropdown) {
        syncGithubTargetToInput();
      }

      if (targetHelpText) {
        if (isGithub) {
          targetHelpText.textContent = 'GitHub: selected from linked-account list';
        } else if (isWebhook) {
          targetHelpText.textContent = 'Webhook: full URL';
        } else {
          targetHelpText.textContent = '';
        }
      }

      if (descInput) {
        descInput.disabled = !isWebhook;
        descInput.style.opacity = isWebhook ? '1' : '0.5';
      }
    }

    var slugCheckTimer = null;
    var slugRequestSeq = 0;

    function setSlugStatus(ok, message) {
      if (!slugAvailability) return;
      slugAvailability.textContent = message || '';
      slugAvailability.className = 'small mt-1 ' + (ok ? 'text-success' : 'text-danger');
      if (saveBtn) saveBtn.disabled = !ok;
    }

    function checkSlugAvailability() {
      if (!slugInput || !slugAvailability) return;
      var slug = (slugInput.value || '').trim();
      var checkUrl = slugAvailability.getAttribute('data-check-url');
      var form = slugInput.closest('form');
      var taskId = form ? form.getAttribute('data-task-id') : '';

      if (!slug) {
        setSlugStatus(false, 'Slug is required.');
        return;
      }

      if (!checkUrl) return;
      var seq = ++slugRequestSeq;
      setSlugStatus(true, 'Checking...');

      var url = checkUrl + '?slug=' + encodeURIComponent(slug);
      if (taskId) url += '&task_id=' + encodeURIComponent(taskId);

      fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (data) {
          if (seq !== slugRequestSeq || !data) return;
          if (data.available) {
            setSlugStatus(true, 'Slug available.');
          } else {
            setSlugStatus(false, data.reason || 'Slug is unavailable.');
          }
        })
        .catch(function () {
          if (seq !== slugRequestSeq) return;
          setSlugStatus(false, 'Could not validate slug right now.');
        });
    }

    function scheduleSlugCheck() {
      if (slugCheckTimer) window.clearTimeout(slugCheckTimer);
      slugCheckTimer = window.setTimeout(checkSlugAvailability, 250);
    }

    if (githubTargetSelect) {
      githubTargetSelect.addEventListener('change', syncGithubTargetToInput);
    }

    if (slugInput) {
      slugInput.addEventListener('input', scheduleSlugCheck);
      checkSlugAvailability();
    }

    var form = typeSelect.closest('form');
    if (form) {
      form.addEventListener('submit', syncGithubTargetToInput);
    }

    typeSelect.addEventListener('change', update);
    update();
  });
})();
