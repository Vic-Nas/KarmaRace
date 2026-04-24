"""
management command: reach

Usage:
    python manage.py reach <gdrive_share_url> [--dry-run]

Fetches a plain-text email list from a public Google Drive file,
previews it for validation, then sends the KarmaRace outreach
email via Resend.

Required settings (setup/settings.py):
    RESEND_API_KEY  — Resend API key
    DOMAIN          — e.g. "karmarace.dev"  →  sender: KarmaRace <reach@{DOMAIN}>

Dry-run writes tmp/reach_preview.html and tmp/reach_preview.txt for review.
"""

import json
import pathlib
import re
import sys
import urllib.error
import urllib.request

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


RESEND_API_URL = "https://api.resend.com/emails"
SUBJECT        = "Your project deserves users — not a bigger budget"
PREVIEW_COUNT  = 10


# ── URL resolution ────────────────────────────────────────────────────────────

def gdrive_direct_url(share_url: str) -> str:
    """
    Convert a Google Drive share link to a direct download URL.
    Expects: https://drive.google.com/file/d/{FILE_ID}/view?usp=sharing
    Returns: https://drive.google.com/uc?export=download&id={FILE_ID}
    """
    match = re.search(r"/file/d/([^/]+)", share_url)
    if not match:
        raise CommandError(
            f"Could not extract a file ID from the URL: {share_url}\n"
            "Expected format: https://drive.google.com/file/d/FILE_ID/view?usp=sharing"
        )
    return f"https://drive.google.com/uc?export=download&id={match.group(1)}"


# ── Fetch ─────────────────────────────────────────────────────────────────────

def fetch_emails(share_url: str) -> list[str]:
    """Download the file and return a deduplicated, validated list of emails."""
    url = gdrive_direct_url(share_url)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        raise CommandError(f"Could not fetch email list: {exc}") from exc

    EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
    seen, emails = set(), []
    for line in raw.splitlines():
        line = line.strip().strip(",;")
        if EMAIL_RE.fullmatch(line) and line not in seen:
            seen.add(line)
            emails.append(line)
    return emails


# ── Email content ─────────────────────────────────────────────────────────────

def build_html(domain: str) -> str:
    root      = f"https://{domain}"
    cta_href  = root
    help_href = f"{root}/help"
    priv_href = f"{root}/legal/privacy"

    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>KarmaRace</title>
<!--[if mso]><noscript><xml><o:OfficeDocumentSettings>
<o:PixelsPerInch>96</o:PixelsPerInch>
</o:OfficeDocumentSettings></xml></noscript><![endif]-->
<style>
  body,table,td,a{{-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%;}}
  table,td{{mso-table-lspace:0pt;mso-table-rspace:0pt;border-collapse:collapse;}}
  img{{border:0;outline:none;text-decoration:none;-ms-interpolation-mode:bicubic;}}
  body{{margin:0;padding:0;background-color:#0f0f0f;
    font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;color:#e8e8e8;}}
  .wrapper{{width:100%;background-color:#0f0f0f;}}
  .container{{max-width:560px;margin:0 auto;padding:40px 24px;}}
  .logo{{font-size:28px;letter-spacing:-0.5px;color:#fff;font-weight:700;margin-bottom:8px;}}
  .logo span{{color:#a78bfa;}}
  .tagline{{font-size:12px;letter-spacing:2px;text-transform:uppercase;color:#555;margin-bottom:36px;}}
  .hero{{font-size:22px;font-weight:700;line-height:1.35;color:#fff;margin-bottom:16px;}}
  .hero em{{font-style:normal;color:#a78bfa;}}
  p{{font-size:15px;line-height:1.7;color:#aaa;margin:0 0 16px 0;}}
  .steps{{margin:24px 0;padding:0;list-style:none;}}
  .steps li{{font-size:14px;color:#ccc;padding:10px 0;
    border-bottom:1px solid #1e1e1e;display:flex;gap:12px;align-items:flex-start;}}
  .steps li:last-child{{border-bottom:none;}}
  .step-num{{display:inline-block;min-width:22px;height:22px;line-height:22px;
    text-align:center;background:#1e1e1e;color:#a78bfa;font-size:11px;
    font-weight:700;border-radius:4px;flex-shrink:0;}}
  .cta-wrap{{text-align:center;margin:32px 0 24px;}}
  .cta{{display:inline-block;background:#a78bfa;color:#0f0f0f !important;
    font-size:15px;font-weight:700;text-decoration:none;
    padding:14px 36px;border-radius:6px;letter-spacing:0.3px;}}
  .footer{{margin-top:40px;padding-top:20px;border-top:1px solid #1e1e1e;
    font-size:12px;color:#444;line-height:1.6;}}
  .footer a{{color:#555;text-decoration:none;}}
  @media only screen and (max-width:600px){{
    .container{{padding:28px 16px;}}.hero{{font-size:19px;}}}}
</style>
</head>
<body>
<div class="wrapper"><div class="container">

  <div class="logo">&#9775; Karma<span>Race</span></div>
  <div class="tagline">Task exchange for developers</div>

  <div class="hero">
    Your project deserves users.<br>
    Not a <em>marketing budget</em>.
  </div>

  <p>Big products win feeds because they outspend you &mdash; not because
  they&rsquo;re better. KarmaRace levels that. It&rsquo;s a free
  task-exchange community where developers trade real GitHub engagement:
  stars, forks, and more.</p>

  <p>No ads. No algorithms for sale. Just reciprocity &mdash; you do
  something for someone, they do something for you. Karma tracks the
  balance and ranks the feed.</p>

  <ul class="steps">
    <li><span class="step-num">1</span> Connect your GitHub account</li>
    <li><span class="step-num">2</span> Post your repo as a task (star or fork)</li>
    <li><span class="step-num">3</span> Complete tasks for others to earn karma</li>
    <li><span class="step-num">4</span> Karma lifts your visibility &mdash; no wallet required</li>
  </ul>

  <p style="color:#777;font-size:13px;">Reciprocity is automatic &mdash; if someone
  completes your task, a reverse obligation is created and settled fairly before
  the feed reopens. Nobody freeloads.</p>

  <div class="cta-wrap">
    <a class="cta" href="{cta_href}">Join free &rarr;</a>
  </div>

  <div class="footer">
    You&rsquo;re receiving this because you build things worth discovering.<br>
    No tracking pixels. No follow-up drip. Just this one email.<br><br>
    &copy; 2025 KarmaRace &mdash;
    <a href="{help_href}">Help</a> &middot;
    <a href="{priv_href}">Privacy</a>
  </div>

</div></div>
</body>
</html>"""


def build_plaintext(domain: str) -> str:
    root = f"https://{domain}"
    return (
        "\u262f KarmaRace \u2014 Task exchange for developers\n"
        "-------------------------------------------\n\n"
        "Your project deserves users. Not a marketing budget.\n\n"
        "Big products win feeds because they outspend you \u2014 not because they're better.\n"
        "KarmaRace levels that. It's a free task-exchange community where developers\n"
        "trade real GitHub engagement: stars, forks, and more.\n\n"
        "No ads. No algorithms for sale. Just reciprocity \u2014 karma tracks the balance\n"
        "and ranks the feed.\n\n"
        "HOW IT WORKS\n"
        "  1. Connect your GitHub account\n"
        "  2. Post your repo as a task (star or fork)\n"
        "  3. Complete tasks for others to earn karma\n"
        "  4. Karma lifts your visibility \u2014 no wallet required\n\n"
        f"Join free: {root}\n\n"
        "---\n"
        "You're receiving this because you build things worth discovering.\n"
        "No tracking pixels. No follow-up drip. Just this one email.\n"
        f"KarmaRace \u2014 {root}/legal/privacy\n"
    )


# ── Sending ───────────────────────────────────────────────────────────────────

def send_via_resend(api_key: str, from_addr: str, to: str, domain: str) -> bool:
    """Send one email via the Resend API. Returns True on success."""
    payload = json.dumps({
        "from":    from_addr,
        "to":      [to],
        "subject": SUBJECT,
        "html":    build_html(domain),
        "text":    build_plaintext(domain),
    }).encode()

    req = urllib.request.Request(
        RESEND_API_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type":  "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status in (200, 201)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        sys.stderr.write(f"  Resend error {exc.code} for {to}: {body}\n")
        return False


# ── Command ───────────────────────────────────────────────────────────────────

class Command(BaseCommand):
    help = "Send the KarmaRace outreach email to a list from a public Google Drive file."

    def add_arguments(self, parser):
        parser.add_argument(
            "share_url",
            type=str,
            help="Google Drive share URL (file must be 'Anyone with the link can view').",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Preview the list and write HTML/text to tmp/ without sending.",
        )

    def handle(self, *args, **options):
        share_url = options["share_url"]
        dry_run   = options["dry_run"]
        domain    = settings.DOMAIN
        api_key   = settings.RESEND_API_KEY
        from_addr = f"KarmaRace <reach@{domain}>"

        if not dry_run and not api_key:
            raise CommandError(
                "RESEND_API_KEY is not set in settings. "
                "Use --dry-run to preview without sending."
            )

        # ── Fetch ─────────────────────────────────────────────────────────────
        self.stdout.write("Fetching email list…")
        emails = fetch_emails(share_url)
        if not emails:
            raise CommandError("No valid email addresses found in the file.")

        # ── Preview ───────────────────────────────────────────────────────────
        self.stdout.write(self.style.SUCCESS(f"\n✔ {len(emails)} addresses loaded\n"))
        self.stdout.write("First addresses:")
        for addr in emails[:PREVIEW_COUNT]:
            self.stdout.write(f"  {addr}")
        if len(emails) > PREVIEW_COUNT:
            self.stdout.write(f"  … and {len(emails) - PREVIEW_COUNT} more")

        # ── Dry-run ───────────────────────────────────────────────────────────
        if dry_run:
            tmp = pathlib.Path("tmp")
            tmp.mkdir(exist_ok=True)
            html_path = tmp / "reach_preview.html"
            txt_path  = tmp / "reach_preview.txt"
            html_path.write_text(build_html(domain), encoding="utf-8")
            txt_path.write_text(build_plaintext(domain), encoding="utf-8")
            self.stdout.write(self.style.WARNING(
                f"\n[dry-run] No emails sent."
                f"\n  HTML preview : {html_path}"
                f"\n  Text fallback: {txt_path}"
            ))
            return

        # ── Confirm ───────────────────────────────────────────────────────────
        self.stdout.write(
            f"\nFrom   : {from_addr}"
            f"\nSubject: {SUBJECT}"
            f"\nTotal  : {len(emails)} recipients\n"
        )
        if input("Send to all? [yes/N] ").strip().lower() != "yes":
            self.stdout.write(self.style.WARNING("Aborted."))
            return

        # ── Send ──────────────────────────────────────────────────────────────
        sent = failed = 0
        for i, addr in enumerate(emails, 1):
            if send_via_resend(api_key, from_addr, addr, domain):
                sent += 1
                self.stdout.write(f"  [{i}/{len(emails)}] \u2714 {addr}")
            else:
                failed += 1
                self.stdout.write(self.style.ERROR(f"  [{i}/{len(emails)}] \u2717 {addr}"))

        # ── Summary ───────────────────────────────────────────────────────────
        self.stdout.write("\n" + "\u2500" * 40)
        self.stdout.write(self.style.SUCCESS(f"Sent   : {sent}"))
        if failed:
            self.stdout.write(self.style.ERROR(f"Failed : {failed}"))