"""Periodic outreach tasks (harvest and send)."""
import logging
import random
import urllib.parse

from django.conf import settings
from django.utils import timezone
from procrastinate.contrib.django import app

from .config import BATCH, GITHUB_API, SUBJECT, LANGUAGES, SEARCH_BASE, score_user, gh_get, resend_post
from .email import build_html, build_plaintext

logger = logging.getLogger(__name__)


@app.periodic(cron="0 2 * * *")
@app.task
def harvest_outreach_emails():
	"""Harvest scored GitHub user candidates into OutreachRecord queue.

	Only includes users who:
	- Match SEARCH_BASE filters (followers/repos in target range)
	- Have at least one repo with a homepage URL (active project promotion)
	- Have a public email
	- Have not already been contacted (per OutreachContactedEmail)
	"""
	if not getattr(settings, "REACH", False):
		logger.info("harvest_outreach_emails: REACH is False, skipping.")
		return

	from accounts.models import OutreachRecord, OutreachContactedEmail

	queued    = set(OutreachRecord.objects.values_list("email", flat=True))
	contacted = set(OutreachContactedEmail.objects.values_list("email", flat=True))
	skip      = queued | contacted

	new_records = []
	page = 1
	lang = random.choice(LANGUAGES)
	query = urllib.parse.quote(SEARCH_BASE + " language:" + lang)

	while len(new_records) < BATCH:
		url = f"{GITHUB_API}/search/users?q={query}&per_page=30&page={page}"
		data = gh_get(url)
		if not data or not data.get("items"):
			break

		for item in data["items"]:
			if len(new_records) >= BATCH:
				break

			profile = gh_get(f"{GITHUB_API}/users/{item['login']}")
			if not profile:
				continue

			email = (profile.get("email") or "").strip().lower()
			if not email or email in skip:
				continue

			repos = gh_get(f"{GITHUB_API}/users/{item['login']}/repos?per_page=30")
			if not repos or not any(r.get("homepage") for r in repos):
				continue

			score = score_user(profile, repos)
			skip.add(email)
			new_records.append(OutreachRecord(email=email, score=score))

		page += 1

	if new_records:
		OutreachRecord.objects.bulk_create(new_records, ignore_conflicts=True)

	# Stats: track harvest count for today's row
	today = timezone.now().date()
	from accounts.models import OutreachDailyStats
	stats, _ = OutreachDailyStats.objects.get_or_create(date=today)
	stats.harvested = len(new_records)
	stats.save(update_fields=["harvested", "updated_at"])

	logger.info(
		"harvest_outreach_emails: harvested=%d (lang=%s)", len(new_records), lang
	)


@app.periodic(cron="0 6 * * *")
@app.task
def send_outreach_emails():
	"""Send top-scored pending records (up to DAILY_REACH) via Resend.

	After each attempt: delete OutreachRecord, log email in OutreachContactedEmail,
	and upsert today's OutreachDailyStats row.
	"""
	if not getattr(settings, "REACH", False):
		logger.info("send_outreach_emails: REACH is False, skipping.")
		return

	from accounts.models import OutreachRecord, OutreachContactedEmail, OutreachDailyStats

	daily_reach = getattr(settings, "DAILY_REACH", 100)
	domain      = settings.DOMAIN
	from_addr   = "KarmaRace <outreach@" + domain + ">"
	html        = build_html(domain)
	plaintext   = build_plaintext(domain)

	pending = list(
		OutreachRecord.objects.order_by("-score", "created_at")[:daily_reach]
	)

	sent = failed = 0
	for record in pending:
		ok = resend_post({
			"from":    from_addr,
			"to":      [record.email],
			"subject": SUBJECT,
			"html":    html,
			"text":    plaintext,
		})
		OutreachContactedEmail.objects.get_or_create(email=record.email)
		record.delete()
		if ok:
			sent += 1
		else:
			failed += 1

	today = timezone.now().date()
	pending_after = OutreachRecord.objects.count()
	stats, _ = OutreachDailyStats.objects.get_or_create(date=today)
	stats.queued_count  = len(pending)
	stats.sent_count    = sent
	stats.failed_count  = failed
	stats.pending_after = pending_after
	stats.save(update_fields=[
		"queued_count", "sent_count", "failed_count", "pending_after", "updated_at"
	])

	logger.info(
		"send_outreach_emails: sent=%d failed=%d pending_after=%d",
		sent, failed, pending_after,
	)
