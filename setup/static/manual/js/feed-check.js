var FeedCheck = (function () {
  function start(statusUrl) {
    var pollMs = 1200;
    var maxMs = 30000;
    var elapsed = 0;

    var timer = setInterval(function () {
      elapsed += pollMs;
      fetch(statusUrl, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (data) {
          if (data && data.state && data.state !== 'PENDING') {
            clearInterval(timer);
            var url = new URL(window.location.href);
            url.searchParams.delete('checking_task');
            if (data.state === 'CONFIRMED') {
              url.searchParams.set('check_result', 'CONFIRMED');
              url.searchParams.delete('check_detail');
            } else if (data.state === 'FAILED') {
              url.searchParams.set('check_result', 'FAILED');
              if (data.detail) {
                url.searchParams.set('check_detail', data.detail);
              } else {
                url.searchParams.delete('check_detail');
              }
            }
            window.location.href = url.toString();
          }
        })
        .catch(function () {});
      if (elapsed >= maxMs) {
        clearInterval(timer);
        var fallbackUrl = new URL(window.location.href);
        fallbackUrl.searchParams.delete('checking_task');
        window.location.href = fallbackUrl.toString();
      }
    }, pollMs);
  }
  return { start: start };
})();
