window.KarmaFX = (function () {
  function fire(delta, anchorEl) {
    const el = document.createElement('div');
    el.className = 'karma-float ' + (delta > 0 ? 'karma-float--gain' : 'karma-float--loss');
    el.textContent = (delta > 0 ? '+' : '') + delta;

    if (anchorEl) {
      const rect = anchorEl.getBoundingClientRect();
      el.style.left = (rect.left + rect.width / 2 - 20) + 'px';
      el.style.top  = (rect.top - 10) + 'px';
    } else {
      el.style.right = '2rem';
      el.style.top   = '4rem';
    }

    document.body.appendChild(el);
    el.addEventListener('animationend', function () { el.remove(); });

    const badge = document.querySelector('.kr-nav__karma');
    if (badge) {
      badge.classList.remove('karma-pulse');
      void badge.offsetWidth;
      badge.classList.add('karma-pulse');
    }
  }

  return { fire };
})();
