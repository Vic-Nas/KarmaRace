(function () {
  document.addEventListener('DOMContentLoaded', function () {
    var typeSelect = document.getElementById('id_type');
    var secretRow = document.getElementById('webhook-secret-row');
    var descInput = document.getElementById('id_description');
    if (!typeSelect) return;

    function update() {
      var isWebhook = typeSelect.value === 'WEBHOOK';
      secretRow.style.display = isWebhook ? '' : 'none';
      if (descInput) {
        descInput.disabled = !isWebhook;
        descInput.style.opacity = isWebhook ? '1' : '0.5';
      }
    }

    typeSelect.addEventListener('change', update);
    update();
  });
})();
