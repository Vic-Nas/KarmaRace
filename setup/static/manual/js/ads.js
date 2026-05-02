(function () {
  var KOHO = {
    url:  'https://referral.koho.ca/mzHiGL4',
    logo: 'https://www.koho.ca/favicon-32x32.png',
    name: 'KOHO',
    tag:  'Canada\'s smartest card',
    lines: [
      'No monthly fees.',
      'Cash back on every purchase.',
      'Save automatically, spend wisely.'
    ],
    cta: 'Get KOHO Free'
  };

  var RAILWAY = {
    url:  'https://railway.com/?referralCode=ZIdvo-',
    logo: 'https://railway.com/brand/logo-light.png',
    name: 'Railway',
    tag:  'Hosts KarmaRace',
    lines: [
      'Deploy any app in seconds.',
      'No DevOps. No headaches.',
      'Free tier available.'
    ],
    cta: 'Try Railway'
  };

  function makeFallback(partner) {
    var a = document.createElement('a');
    a.className = 'ad-fallback';
    a.href = partner.url;
    a.target = '_blank';
    a.rel = 'noopener noreferrer sponsored';

    var img = document.createElement('img');
    img.src  = partner.logo;
    img.alt  = partner.name;
    img.className = 'ad-fallback__logo';
    img.onerror = function () { img.style.display = 'none'; };

    var name = document.createElement('div');
    name.className   = 'ad-fallback__name';
    name.textContent = partner.name;

    var tag = document.createElement('div');
    tag.className   = 'ad-fallback__tag';
    tag.textContent = partner.tag;

    var desc = document.createElement('div');
    desc.className   = 'ad-fallback__desc';
    desc.textContent = partner.lines[Math.floor(Math.random() * partner.lines.length)];

    var cta = document.createElement('div');
    cta.className   = 'ad-fallback__cta';
    cta.textContent = partner.cta;

    a.appendChild(img);
    a.appendChild(name);
    a.appendChild(tag);
    a.appendChild(desc);
    a.appendChild(cta);
    return a;
  }

  function makeAdsense(client, slot) {
    var ins = document.createElement('ins');
    ins.className = 'adsbygoogle';
    ins.style.cssText = 'display:block;width:100%;height:100%';
    ins.setAttribute('data-ad-client', client);
    ins.setAttribute('data-ad-slot',   slot);
    ins.setAttribute('data-ad-format', 'auto');
    return ins;
  }

  function loadAdsenseScript(client) {
    if (document.querySelector('script[src*="adsbygoogle"]')) return;
    var s = document.createElement('script');
    s.async = true;
    s.src = 'https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=' + client;
    s.crossOrigin = 'anonymous';
    document.head.appendChild(s);
  }

  document.addEventListener('DOMContentLoaded', function () {
    var cfg    = window.KR_ADS || {};
    var client = cfg.client || '';
    var slots  = (cfg.slots || []).filter(Boolean);
    var isPro  = !!cfg.isPro;

    if (isPro) return;

    var leftBoxes  = Array.from(document.querySelectorAll('.kr-ads--left  .ad-box'));
    var rightBoxes = Array.from(document.querySelectorAll('.kr-ads--right .ad-box'));
    var allBoxes   = leftBoxes.concat(rightBoxes);

    if (client && slots.length) loadAdsenseScript(client);

    allBoxes.forEach(function (box, i) {
      var slot    = slots[i] || null;
      var partner = i < 3 ? KOHO : RAILWAY;

      if (client && slot) {
        var ins = makeAdsense(client, slot);
        box.appendChild(ins);
        try { (window.adsbygoogle = window.adsbygoogle || []).push({}); } catch (e) {}
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