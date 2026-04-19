(function () {
  document.addEventListener('DOMContentLoaded', function () {
    var typeSelect = document.getElementById('id_type');
    var secretRow = document.getElementById('webhook-secret-row');
    var descInput = document.getElementById('id_description');
    var targetInput = document.getElementById('id_target_id');
    var targetInputRow = document.getElementById('target-input-row');
    var githubTargetRow = document.getElementById('github-target-row');
    var githubTargetSelect = document.getElementById('id_github_target_select');
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
      secretRow.style.display = isWebhook ? '' : 'none';

      if (targetInputRow) {
        targetInputRow.style.display = isGithub ? 'none' : '';
      }
      if (githubTargetRow) {
        githubTargetRow.style.display = isGithub ? '' : 'none';
      }

      syncGithubTargetToInput();

      if (descInput) {
        descInput.disabled = !isWebhook;
        descInput.style.opacity = isWebhook ? '1' : '0.5';
      }
    }

    if (githubTargetSelect) {
      githubTargetSelect.addEventListener('change', syncGithubTargetToInput);
    }

    var form = typeSelect.closest('form');
    if (form) {
      form.addEventListener('submit', syncGithubTargetToInput);
    }

    typeSelect.addEventListener('change', update);
    update();
  });
})();
