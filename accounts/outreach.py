# accounts/outreach.py
#
# Two periodic Procrastinate tasks:
#
#   harvest_outreach_emails  — 02:00 UTC daily, fetches up to 100 new GitHub
#                              user emails into OutreachRecord.
#
#   send_outreach_emails     — 06:00 UTC daily, sends up to 100 pending records
#                              via Resend.
#
# Gated by settings.REACH (bool). Add to settings.py:
#   REACH = env.bool('REACH', default=False)
#
# Register in accounts/apps.py ready():
#   import accounts.outreach  # noqa: F401

import json
import logging
import random
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from procrastinate.contrib.django import app

logger = logging.getLogger(__name__)

BATCH        = 100
DAILY_LIMIT  = 100
GITHUB_API   = "https://api.github.com"
RESEND_API   = "https://api.resend.com/emails"
SUBJECT      = "Your project deserves users — not a bigger budget"
LANGUAGES    = ["python", "javascript", "typescript", "go", "rust"]
SEARCH_BASE  = "type:user followers:10..500 repos:5..100"


# ── GitHub helpers ────────────────────────────────────────────────────────────

def _gh_headers() -> dict:
    return {
        "Authorization":        f"Bearer {settings.GITHUB_TOKEN}",
        "Accept":               "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _gh_get(url: str):
    req = urllib.request.Request(url, headers=_gh_headers())
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.URLError as exc:
        logger.error("GitHub API error %s: %s", url, exc)
        return None


# ── Resend helper ─────────────────────────────────────────────────────────────

def _resend_post(payload: dict) -> bool:
    req = urllib.request.Request(
        RESEND_API,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {settings.RESEND_API_KEY}",
            "Content-Type":  "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status in (200, 201)
    except urllib.error.HTTPError as exc:
        logger.error("Resend error %s: %s", exc.code, exc.read().decode(errors="replace"))
        return False


# ── Email content ─────────────────────────────────────────────────────────────

def _build_html(domain: str) -> str:
    root      = "https://" + domain
    help_href = root + "/help"
    priv_href = root + "/legal/privacy"

    css = (
        "body,table,td,a{-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%;}"
        "table,td{mso-table-lspace:0pt;mso-table-rspace:0pt;border-collapse:collapse;}"
        "body{margin:0;padding:0;background-color:#0f0f0f;"
        "font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;color:#e8e8e8;}"
        ".wrapper{width:100%;background-color:#0f0f0f;}"
        ".container{max-width:560px;margin:0 auto;padding:40px 24px;}"
        ".logo{font-size:28px;letter-spacing:-0.5px;color:#fff;font-weight:700;margin-bottom:8px;}"
        ".logo span{color:#a78bfa;}"
        ".tagline{font-size:12px;letter-spacing:2px;text-transform:uppercase;"
        "color:#555;margin-bottom:36px;}"
        ".hero{font-size:22px;font-weight:700;line-height:1.35;color:#fff;margin-bottom:16px;}"
        ".hero em{font-style:normal;color:#a78bfa;}"
        "p{font-size:15px;line-height:1.7;color:#aaa;margin:0 0 16px 0;}"
        ".steps{margin:24px 0;padding:0;list-style:none;}"
        ".steps li{font-size:14px;color:#ccc;padding:10px 0;"
        "border-bottom:1px solid #1e1e1e;display:flex;gap:12px;align-items:flex-start;}"
        ".steps li:last-child{border-bottom:none;}"
        ".step-num{display:inline-block;min-width:22px;height:22px;line-height:22px;"
        "text-align:center;background:#1e1e1e;color:#a78bfa;font-size:11px;"
        "font-weight:700;border-radius:4px;flex-shrink:0;}"
        ".cta-wrap{text-align:center;margin:32px 0 24px;}"
        ".cta{display:inline-block;background:#a78bfa;color:#0f0f0f !important;"
        "font-size:15px;font-weight:700;text-decoration:none;"
        "padding:14px 36px;border-radius:6px;letter-spacing:0.3px;}"
        ".footer{margin-top:40px;padding-top:20px;border-top:1px solid #1e1e1e;"
        "font-size:12px;color:#444;line-height:1.6;}"
        ".footer a{color:#555;text-decoration:none;}"
        "@media only screen and (max-width:600px){"
        ".container{padding:28px 16px;}.hero{font-size:19px;}}"
    )

    return (
        "<!DOCTYPE html>"
        '<html lang="en"><head>'
        '<meta charset="UTF-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
        "<title>KarmaRace</title>"
        "<!--[if mso]><noscript><xml><o:OfficeDocumentSettings>"
        "<o:PixelsPerInch>96</o:PixelsPerInch>"
        "</o:OfficeDocumentSettings></xml></noscript><![endif]-->"
        "<style>" + css + "</style>"
        "</head><body>"
        '<div class="wrapper"><div class="container">'
        '<div class="logo">&#9775; Karma<span>Race</span></div>'
        '<div class="tagline">Task exchange for developers</div>'
        '<div class="hero">Your project deserves users.<br>Not a <em>marketing budget</em>.</div>'
        "<p>Big products win feeds because they outspend you &mdash; not because they&rsquo;re"
        " better. KarmaRace levels that. It&rsquo;s a free task-exchange community where"
        " builders publish clear task requests and other users complete them for karma.</p>"
        "<p>No ads. No algorithms for sale. Just reciprocity &mdash; you do something for"
        " someone, they do something for you. Karma tracks the balance and ranks the feed.</p>"
        "<p><strong>What KarmaRace is for:</strong> turning growth goals into clear tasks"
        " users can complete (GitHub star/fork goals, webhook checks, and platform-specific"
        " actions) without paying for shallow reach.</p>"
        '<ul class="steps">'
        '<li><span class="step-num">1</span> Connect account(s) needed for the tasks you want to run</li>'
        '<li><span class="step-num">2</span> Publish tasks so users know exactly what your platform needs</li>'
        '<li><span class="step-num">3</span> Complete tasks for others to earn karma</li>'
        '<li><span class="step-num">4</span> Karma lifts your visibility &mdash; no wallet required</li>'
        "</ul>"
        '<p style="color:#777;font-size:13px;">Reciprocity is automatic &mdash; if someone'
        " completes your task, a reverse obligation is created and settled fairly before the"
        " feed reopens. Nobody freeloads.</p>"
        '<div class="cta-wrap">'
        '<a class="cta" href="' + root + '">Join free &rarr;</a>'
        "</div>"
        '<div class="footer">'
        "You&rsquo;re receiving this because you build things worth discovering.<br>"
        "No tracking pixels. No follow-up drip. Just this one email.<br><br>"
        "&copy; 2025 KarmaRace &mdash; "
        '<a href="' + help_href + '">Help</a> &middot; '
        '<a href="' + priv_href + '">Privacy</a>'
        "</div>"
        "</div></div></body></html>"
    )


def _build_plaintext(domain: str) -> str:
    root = "https://" + domain
    return (
        "\u262f KarmaRace \u2014 Task exchange for developers\n"
        "-------------------------------------------\n\n"
        "Your project deserves users. Not a marketing budget.\n\n"
        "Big products win feeds because they outspend you \u2014 not because they're better.\n"
        "KarmaRace levels that. It's a free task-exchange community where builders\n"
        "publish clear task requests and other users complete them for karma.\n\n"
        "No ads. No algorithms for sale. Just reciprocity \u2014 karma tracks the balance\n"
        "and ranks the feed.\n\n"
        "WHAT KARMARACE IS FOR\n"
        "  - Turning growth goals into clear tasks users can complete\n"
        "  - Running GitHub and webhook verification tasks with real outcomes\n"
        "  - Getting traction without buying ads\n\n"
        "HOW IT WORKS\n"
        "  1. Connect account(s) needed for the tasks you want to run\n"
        "  2. Publish tasks so users know exactly what your platform needs\n"
        "  3. Complete tasks for others to earn karma\n"
        "  4. Karma lifts your visibility \u2014 no wallet required\n\n"
        "Join free: " + root + "\n\n"
        "---\n"
        "You're receiving this because you build things worth discovering.\n"
        "No tracking pixels. No follow-up drip. Just this one email.\n"
        "KarmaRace \u2014 " + root + "/legal/privacy\n"
    )


# ── Periodic tasks ────────────────────────────────────────────────────────────

@app.periodic(cron="0 2 * * *")
@app.task
def harvest_outreach_emails():
    """Fetch up to BATCH GitHub user emails and store new ones as OutreachRecords."""
    if not getattr(settings, "REACH", False):
        logger.info("harvest_outreach_emails: REACH is False, skipping.")
        return

    from accounts.models import OutreachRecord

    existing = set(OutreachRecord.objects.values_list("email", flat=True))
    collected = []
    page = 1
    lang = random.choice(LANGUAGES)
    query = urllib.parse.quote(SEARCH_BASE + " language:" + lang)

    while len(collected) < BATCH:
        url = f"{GITHUB_API}/search/users?q={query}&per_page=30&page={page}"
        data = _gh_get(url)
        if not data or not data.get("items"):
            break

        for item in data["items"]:
            if len(collected) >= BATCH:
                break
            profile = _gh_get(f"{GITHUB_API}/users/{item['login']}")
            if not profile:
                continue
            email = (profile.get("email") or "").strip().lower()
            if not email or email in existing:
                continue
            existing.add(email)
            collected.append(email)

        page += 1

    if collected:
        OutreachRecord.objects.bulk_create(
            [OutreachRecord(email=e, state=OutreachRecord.State.PENDING) for e in collected],
            ignore_conflicts=True,
        )
        logger.info("harvest_outreach_emails: stored %d new addresses (lang=%s)", len(collected), lang)
    else:
        logger.info("harvest_outreach_emails: no new addresses found (lang=%s)", lang)


@app.periodic(cron="0 6 * * *")
@app.task
def send_outreach_emails():
    """Send up to DAILY_LIMIT emails to pending OutreachRecords via Resend."""
    if not getattr(settings, "REACH", False):
        logger.info("send_outreach_emails: REACH is False, skipping.")
        return

    from accounts.models import OutreachRecord

    domain    = settings.DOMAIN
    from_addr = "KarmaRace <outreach@" + domain + ">"
    html      = _build_html(domain)
    plaintext = _build_plaintext(domain)

    pending = OutreachRecord.objects.filter(
        state=OutreachRecord.State.PENDING
    ).order_by("created_at")[:DAILY_LIMIT]

    sent = failed = 0
    for record in pending:
        ok = _resend_post({
            "from":    from_addr,
            "to":      [record.email],
            "subject": SUBJECT,
            "html":    html,
            "text":    plaintext,
        })
        record.state = OutreachRecord.State.SENT if ok else OutreachRecord.State.FAILED
        record.save(update_fields=["state"])
        if ok:
            sent += 1
        else:
            failed += 1

    logger.info("send_outreach_emails: sent=%d failed=%d", sent, failed)