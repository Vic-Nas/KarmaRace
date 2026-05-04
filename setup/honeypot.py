# setup/honeypot.py
"""
Honeypot + tarpit middleware for KarmaRace.

Strategy:
  1. Any path that is not a known KarmaRace URL and matches known scanner
     patterns → slow-drip 200 honeypot response (always max size).
  2. Paths that look like real app routes (wrong slug, typo, broken link from
     our own pages) still get a real 404 with a WARNING log so we notice
     broken buttons / links in the app.

Under ASGI (uvicorn workers), Django detects async_capable=True and calls
__acall__ directly, so asyncio.sleep is used and tarpitted bots cost nothing.
Under WSGI, the sync __call__ fallback runs with time.sleep instead.
"""

import asyncio
import hashlib
import logging
import re
import time

from django.http import StreamingHttpResponse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tuning knobs
# ---------------------------------------------------------------------------

MAX_PAYLOAD_BYTES = 600_000
STREAM_CHUNK = 1_024
STREAM_DELAY = 0.05

# ---------------------------------------------------------------------------
# Known-good KarmaRace path prefixes / exact paths.
# ---------------------------------------------------------------------------

_LEGITIMATE_PREFIXES = (
    "/admin/",
    "/accounts/",
    "/app/accounts/",
    "/u/",
    "/billing/",
    "/help/",
    "/legal/",
    "/tasks/",
    "/notifications/",
    "/balance/",
    "/leaderboard/",
    "/check/",
    "/check-status/",
    "/done/",
    "/static/",
    "/favicon.ico",
    "/robots.txt",
)

def _is_legitimate_path(path: str) -> bool:
    if path == "/":
        return True
    return any(path.startswith(p) for p in _LEGITIMATE_PREFIXES)


# ---------------------------------------------------------------------------
# Scanner fingerprints
# ---------------------------------------------------------------------------

_SCANNER_PATTERNS = re.compile(
    r"""
    # WordPress / PHP CMSes
    ^/wp-(?:admin|login|content|includes|json|cron|signup|trackback|comments|xmlrpc)
    | ^/wordpress/
    | ^/xmlrpc\.php
    | ^/wp\.php
    | ^/wp\d*\.php

    # Generic PHP probes
    | ^/phpmyadmin
    | ^/pma/
    | ^/myadmin/
    | ^/mysql/
    | ^/sqladmin/
    | ^/phpinfo\.php
    | ^/test\.php
    | ^/info\.php
    | ^/php\.php
    | ^/shell\.php
    | ^/cmd\.php
    | ^/eval\.php
    | ^/install\.php

    # Joomla / Drupal / Laravel / other CMSes
    | ^/joomla
    | ^/drupal
    | ^/laravel
    | ^/magento
    | ^/prestashop
    | ^/opencart
    | ^/oscommerce
    | ^/administrator/
    | ^/index\.php/admin

    # Secrets / config leaks
    | ^/\.env
    | ^/\.git/
    | ^/\.svn/
    | ^/\.htaccess
    | ^/\.htpasswd
    | ^/\.DS_Store
    | ^/config\.php
    | ^/configuration\.php
    | ^/config\.yml
    | ^/config\.json
    | ^/secrets\.json
    | ^/credentials
    | ^/backup
    | ^/dump\.sql
    | ^/database\.sql
    | ^/db\.sql
    | ^/site\.sql

    # Common admin panels / login pages (not ours)
    | ^/login(?:\.php)?$
    | ^/signin(?:\.php)?$
    | ^/panel/
    | ^/cpanel
    | ^/webmail
    | ^/roundcube
    | ^/plesk
    | ^/whm/
    | ^/manager/html
    | ^/server-status
    | ^/server-info

    # Directory submission / SEO spam bots
    | ^/submit(?:-\w+)?/?$
    | ^/add(?:-\w+)?/?$
    | ^/add-(?:url|site|listing|saas|software|product|your-site|your-business)
    | ^/list-(?:your-)?(?:site|saas|software|product|business|listing)
    | ^/register/?$
    | ^/new-listing
    | ^/create-listing
    | ^/get-listed
    | ^/join-(?:us|our-directory)
    | ^/become-a-contributor
    | ^/partner-with-us
    | ^/write-for-us
    | ^/guest-post/?$
    | ^/contribute/?$
    | ^/sponsor/?$
    | ^/feature-yours
    | ^/(?:saas|software|products|vendors)/(?:submit|new|sign-up)
    | ^/submit\.php
    | ^/submitsite\.php

    # Asset scanners / fingerprinting
    | ^/media/system/
    | ^/media/jui/
    | ^/includes/js/
    | ^/modules/mod_
    | ^/components/com_
    | ^/templates/[^/]+/
    | ^/plugins/[^/]+/

    # Well-known files we explicitly do NOT serve
    | ^/crossdomain\.xml
    | ^/clientaccesspolicy\.xml
    | ^/sitemap\.xml
    | ^/sitemap_index\.xml
    | ^/ads\.txt
    | ^/app-ads\.txt
    | ^/apple-touch-icon
    | ^/browserconfig\.xml

    # Credential stuffing / auth scanning (not our auth paths)
    | ^/user/login
    | ^/user/register
    | ^/member/login
    | ^/auth/login
    | ^/api/v\d+/(?:login|users|admin)
    | ^/v\d+/(?:login|users|admin)

    # Cloud metadata — exfiltration attempt
    | ^/latest/meta-data
    | ^/metadata/
    """,
    re.VERBOSE | re.IGNORECASE,
)


def _is_scanner_path(path: str) -> bool:
    return bool(_SCANNER_PATTERNS.match(path))


# ---------------------------------------------------------------------------
# Response generators
# ---------------------------------------------------------------------------

_FAKE_TEMPLATES = [
    # Fake WordPress login
    b"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Log In &lsaquo; Site &#8212; WordPress</title>
<link rel="stylesheet" href="/wp-includes/css/buttons.min.css">
</head>
<body class="login login-action-login wp-core-ui">
<div id="login">
<h1><a href="https://wordpress.org/">Powered by WordPress</a></h1>
<form name="loginform" id="loginform" action="/wp-login.php" method="post">
<p><label for="user_login">Username or Email Address<br>
<input type="text" name="log" id="user_login" value="" size="20" autocapitalize="none" autocomplete="username"></label></p>
<p><label for="user_pass">Password<br>
<input type="password" name="pwd" id="user_pass" value="" size="20" autocomplete="current-password"></label></p>
<p class="forgetmenot"><label for="rememberme"><input name="rememberme" type="checkbox" id="rememberme" value="forever">Remember Me</label></p>
<p class="submit"><input type="submit" name="wp-submit" id="wp-submit" class="button button-primary button-large" value="Log In">
<input type="hidden" name="redirect_to" value="/wp-admin/"><input type="hidden" name="testcookie" value="1"></p>
</form>
<p id="nav"><a href="/wp-login.php?action=lostpassword">Lost your password?</a></p>
</div>
</body></html>""",

    # Fake phpMyAdmin
    b"""<!DOCTYPE html>
<html lang="en" dir="ltr">
<head><meta charset="utf-8"><title>phpMyAdmin</title></head>
<body>
<div id="pma_navigation">
<div id="pma_navigation_header"></div>
</div>
<div id="page_content">
<form method="post" action="index.php" name="login_form" id="login_form">
<fieldset id="fieldset_login">
<legend>Log in</legend>
<input type="hidden" name="token" value="7a3f91bc2d854e6a">
<div class="item"><label for="input_username">Username:</label>
<input type="text" name="pma_username" id="input_username" value="" size="24" class="textfield" autocomplete="username"></div>
<div class="item"><label for="input_password">Password:</label>
<input type="password" name="pma_password" id="input_password" value="" size="24" class="textfield" autocomplete="current-password"></div>
<div class="item"><label for="select_server">Server Choice:</label>
<select name="server" id="select_server"><option value="1" selected="selected">127.0.0.1</option></select></div>
<div class="item"><input type="submit" value="Go" id="input_go"></div>
</fieldset>
</form>
</div>
</body></html>""",

    # Fake .env file
    b"""APP_NAME=Laravel
APP_ENV=production
APP_KEY=base64:V2hhdCBhcmUgeW91IGxvb2tpbmcgZm9yPw==
APP_DEBUG=false
APP_URL=http://localhost

DB_CONNECTION=mysql
DB_HOST=127.0.0.1
DB_PORT=3306
DB_DATABASE=homestead
DB_USERNAME=homestead
DB_PASSWORD=secret

REDIS_HOST=127.0.0.1
REDIS_PASSWORD=null
REDIS_PORT=6379

MAIL_DRIVER=smtp
MAIL_HOST=smtp.mailtrap.io
MAIL_PORT=2525
MAIL_USERNAME=null
MAIL_PASSWORD=null
MAIL_ENCRYPTION=null

AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
AWS_DEFAULT_REGION=us-east-1
AWS_BUCKET=
""",

    # Fake admin panel
    b"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><title>Administration</title></head>
<body>
<div id="wrapper">
<div id="header"><h2>Control Panel</h2></div>
<div id="content">
<form method="post" action="/admin/login">
<table>
<tr><td>Username:</td><td><input type="text" name="username"></td></tr>
<tr><td>Password:</td><td><input type="password" name="password"></td></tr>
<tr><td colspan="2"><input type="submit" value="Login"></td></tr>
</table>
</form>
</div>
</div>
</body></html>""",

    # Fake Joomla
    b"""<!DOCTYPE html>
<html lang="en-GB" dir="ltr">
<head><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Administrator - Control Panel</title>
<meta name="generator" content="Joomla! - Open Source Content Management">
</head>
<body class="admin">
<div id="wrapper_div">
<div id="header"><div id="logo"></div></div>
<div id="content_div">
<form action="/administrator/index.php" method="post" id="form-login" class="form-inline">
<div class="form-group"><label class="sr-only" for="mod-login-username">User Name</label>
<input name="username" tabindex="1" id="mod-login-username" type="text" class="form-control" placeholder="User Name"></div>
<div class="form-group"><label class="sr-only" for="mod-login-password">Password</label>
<input name="passwd" tabindex="2" id="mod-login-password" type="password" class="form-control" placeholder="Password"></div>
<input type="submit" tabindex="3" class="btn btn-primary btn-block" name="Submit" value="Log in">
<input type="hidden" name="option" value="com_login">
<input type="hidden" name="task" value="login">
</form>
</div>
</div>
</body></html>""",
]

_PADDING_COMMENT = b"<!-- " + b"x" * 76 + b" -->\n"  # 84 bytes


def _build_payload(path: str) -> bytes:
    """Build a max-size honeypot payload, template chosen by path hash."""
    idx = int(hashlib.md5(path.encode()).hexdigest(), 16) % len(_FAKE_TEMPLATES)
    base = _FAKE_TEMPLATES[idx]
    chunks = [base]
    size = len(base)
    while size < MAX_PAYLOAD_BYTES:
        chunks.append(_PADDING_COMMENT)
        size += len(_PADDING_COMMENT)
    return b"".join(chunks)


def _sync_streaming_response(path: str) -> StreamingHttpResponse:
    """Sync fallback — used under WSGI."""
    payload = _build_payload(path)

    def _gen():
        for i in range(0, len(payload), STREAM_CHUNK):
            yield payload[i : i + STREAM_CHUNK]
            time.sleep(STREAM_DELAY)

    resp = StreamingHttpResponse(_gen(), status=200, content_type="text/html; charset=utf-8")
    resp["X-Content-Type-Options"] = "nosniff"
    return resp


def _async_streaming_response(path: str) -> StreamingHttpResponse:
    """
    Async generator inside a sync function — Django gets a real response
    object immediately, but the generator uses asyncio.sleep so each chunk
    suspends the coroutine instead of blocking a thread.
    """
    payload = _build_payload(path)

    async def _gen():
        for i in range(0, len(payload), STREAM_CHUNK):
            yield payload[i : i + STREAM_CHUNK]
            await asyncio.sleep(STREAM_DELAY)

    resp = StreamingHttpResponse(_gen(), status=200, content_type="text/html; charset=utf-8")
    resp["X-Content-Type-Options"] = "nosniff"
    return resp


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

class HoneypotMiddleware:
    """
    Dual sync/async middleware. Under ASGI Django calls __acall__ directly
    (free asyncio.sleep tarpit). Under WSGI falls back to sync time.sleep.

    Position in settings.py MIDDLEWARE list:
        'django.middleware.security.SecurityMiddleware',
        'whitenoise.middleware.WhiteNoiseMiddleware',
        'setup.honeypot.HoneypotMiddleware',      <- here
        'django.contrib.sessions.middleware.SessionMiddleware',
        ...
    """

    async_capable = True
    sync_capable = True

    def __init__(self, get_response):
        self.get_response = get_response
        if asyncio.iscoroutinefunction(self.get_response):
            self._is_coroutine = asyncio.coroutines._is_coroutine

    def __call__(self, request):
        path = request.path
        if _is_legitimate_path(path):
            return self.get_response(request)
        if _is_scanner_path(path):
            logger.debug("honeypot: path=%s ua=%s", path,
                request.META.get("HTTP_USER_AGENT", "")[:120])
            return _sync_streaming_response(path)
        return self.get_response(request)

    async def __acall__(self, request):
        path = request.path
        if _is_legitimate_path(path):
            return await self.get_response(request)
        if _is_scanner_path(path):
            logger.debug("honeypot: path=%s ua=%s", path,
                request.META.get("HTTP_USER_AGENT", "")[:120])
            return _async_streaming_response(path)
        return await self.get_response(request)