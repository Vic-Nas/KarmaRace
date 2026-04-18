(function () {
  // Slots injected from template: window.KR_ADS = { client, slots: [...] }
  // Left col = railway fallback, Right col = koho fallback
  var RAILWAY = {
    url: 'https://railway.com/?referralCode=ZIdvo-',
    logo: 'https://railway.com/brand/logo-light.png',
    name: 'Railway',
    tag: 'Deploy in seconds',
  };
  var KOHO = {
    url: 'https://referral.koho.ca/mzHiGL4',
    logo: 'https://www.koho.ca/wp-content/themes/koho/assets/images/koho-logo.svg',
    name: 'KOHO',
    tag: 'Spend smarter',
  };

  function makeFallback(partner) {
    var a = document.createElement('a');
    a.className = 'ad-fallback';
    a.href = partner.url;
    a.target = '_blank';
    a.rel = 'noopener noreferrer sponsored';
    var img = document.createElement('img');
    img.src = partner.logo;
    img.alt = partner.name;
    img.onerror = function () { img.style.display = 'none'; };
    var name = document.createElement('div');
    name.className = 'ad-fallback__name';
    name.textContent = partner.name;
    var tag = document.createElement('div');
    tag.className = 'ad-fallback__tagline';
    tag.textContent = partner.tag;
    a.appendChild(img);
    a.appendChild(name);
    a.appendChild(tag);
    return a;
  }

  function makeAdsense(client, slot) {
    var ins = document.createElement('ins');
    ins.className = 'adsbygoogle';
    ins.style.display = 'block';
    ins.style.width = '100%';
    ins.style.height = '100%';
    ins.setAttribute('data-ad-client', client);
    ins.setAttribute('data-ad-slot', slot);
    ins.setAttribute('data-ad-format', 'auto');
    return ins;
  }

  document.addEventListener('DOMContentLoaded', function () {
    var cfg = window.KR_ADS || {};
    var client = cfg.client || '';
    var slots = (cfg.slots || []).filter(Boolean);

    var leftBoxes  = Array.from(document.querySelectorAll('.kr-ads--left .ad-box'));
    var rightBoxes = Array.from(document.querySelectorAll('.kr-ads--right .ad-box'));
    var allBoxes   = leftBoxes.concat(rightBoxes); // slots 0-2 left, 3-5 right

    allBoxes.forEach(function (box, i) {
      var slot = slots[i] || null;
      var partner = i < 3 ? RAILWAY : KOHO;

      if (client && slot) {
        var ins = makeAdsense(client, slot);
        box.appendChild(ins);
        try { (window.adsbygoogle = window.adsbygoogle || []).push({}); } catch (e) {}
        // If adsense collapses the unit, swap in fallback
        setTimeout(function () {
          if (ins.offsetHeight < 10) {
            box.innerHTML = '';
            box.appendChild(makeFallback(partner));
          }
        }, 3000);
      } else {
        box.appendChild(makeFallback(partner));
      }
    });
  });
})();
