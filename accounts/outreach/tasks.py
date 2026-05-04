# accounts/outreach/tasks.py
"""Periodic outreach tasks (harvest and send)."""
import logging
import random

from django.conf import settings
from django.utils import timezone
from procrastinate.contrib.django import app

from .config import (
	BATCH, SUBJECT, LANGUAGES, SEARCH_BASE,
	score_user, iter_candidates,
	sendpulse_post, update_daily_stats,
)
from .email import build_html, build_plaintext

logger = logging.getLogger(__name__)


@app.periodic(cron="0 2 * * *")
@app.task
def harvest_outreach_emails(timestamp=None):
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
	lang = random.choice(LANGUAGES)
	query = SEARCH_BASE + " language:" + lang
	max_candidates = BATCH * 5

	for profile, repos in iter_candidates(query, max_candidates, max_repos=60):
		if len(new_records) >= BATCH:
			break
		email = (profile.get("email") or "").strip().lower()
		if not email or email in skip:
			continue
		if not repos or not any(getattr(r, 'homepage', '') for r in repos):
			continue
		score = score_user(profile, repos)
		skip.add(email)
		new_records.append(OutreachRecord(email=email, score=score))

	if new_records:
		OutreachRecord.objects.bulk_create(new_records, ignore_conflicts=True)

	# Stats: track harvest count for today's row
	update_daily_stats(timezone.now().date(), harvested=len(new_records))

	logger.info(
		"harvest_outreach_emails: harvested=%d (lang=%s)", len(new_records), lang
	)


@app.periodic(cron="0 * * * *")
@app.task
def send_outreach_emails(timestamp=None):
	"""Send top-scored pending records (up to DAILY_REACH) via SendPulse.

	After each attempt: delete OutreachRecord, log email in OutreachContactedEmail,
	and upsert today's OutreachDailyStats row.
	"""
	if not getattr(settings, "REACH", False):
		logger.info("send_outreach_emails: REACH is False, skipping.")
		return

	from accounts.models import monthly_sent_count, increment_monthly_sent
	if monthly_sent_count() >= getattr(settings, 'MONTHLY_REACH', 12000):
		logger.info('send_outreach_emails: monthly cap reached, skipping.')
		return

	from accounts.models import OutreachRecord, OutreachContactedEmail, OutreachDailyStats

	daily_reach = getattr(settings, "DAILY_REACH", 50)
	domain      = settings.DOMAIN
	html        = build_html(domain)
	plaintext   = build_plaintext(domain)

	pending = list(
		OutreachRecord.objects.order_by("-score", "created_at")[:daily_reach]
	)

	sent = failed = 0
	for record in pending:
		ok = sendpulse_post({
			'email': {
				'from':    {'name': 'KarmaRace', 'email': f'outreach@{domain}'},
				'to':      [{'name': '', 'email': record.email}],
				'subject': SUBJECT,
				'html':    html,
				'text':    plaintext,
			}
		})
		OutreachContactedEmail.objects.get_or_create(email=record.email)
		record.delete()
		if ok:
			sent += 1
		else:
			failed += 1

	if sent:
		increment_monthly_sent(sent)

	update_daily_stats(
		timezone.now().date(),
		queued_count=len(pending),
		sent_count=sent,
		failed_count=failed,
		pending_after=OutreachRecord.objects.count(),
	)

	logger.info(
		"send_outreach_emails: sent=%d failed=%d pending_after=%d",
		sent, failed, pending_after,
	)
