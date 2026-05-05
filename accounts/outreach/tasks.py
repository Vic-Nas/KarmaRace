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


def run_harvest(limit=None, log=None):
	"""Core harvest logic. Shared by the periodic task and management command.

	Returns number of records harvested.
	log: callable for progress output (e.g. print or self.stdout.write). Optional.
	"""
	if not getattr(settings, "REACH", False):
		logger.info("harvest: REACH is False, skipping.")
		return 0

	from accounts.models import OutreachRecord, OutreachContactedEmail

	queued    = set(OutreachRecord.objects.values_list("email", flat=True))
	contacted = set(OutreachContactedEmail.objects.values_list("email", flat=True))
	skip      = queued | contacted

	batch     = limit or BATCH
	lang      = random.choice(LANGUAGES)
	query     = SEARCH_BASE + " language:" + lang
	max_candidates = batch * 20

	if log:
		log(f"Harvesting (limit={batch}, lang={lang}, skip={len(skip)})...")

	new_records = []
	for profile, repos in iter_candidates(query, max_candidates, max_repos=60):
		if len(new_records) >= batch:
			break
		email = (profile.get("email") or "").strip().lower()
		if not email or email in skip:
			continue
		if not repos or not any(getattr(r, 'homepage', '') for r in repos):
			continue
		score = score_user(profile, repos)
		skip.add(email)
		new_records.append(OutreachRecord(email=email, score=score))
		if log:
			log(f"  +{len(new_records)} {email}")

	if new_records:
		OutreachRecord.objects.bulk_create(new_records, ignore_conflicts=True)

	update_daily_stats(timezone.now().date(), harvested=len(new_records))
	logger.info("harvest: harvested=%d lang=%s", len(new_records), lang)
	return len(new_records)


def run_send(limit=None, log=None):
	"""Core send logic. Shared by the periodic task and management command.

	Sends top-scored pending OutreachRecords via SendPulse.
	Only deletes a record from the queue after a successful send.
	On failure, leaves the record in place for the next run.
	Returns (sent, failed).
	log: callable for progress output. Optional.
	"""
	if not getattr(settings, "REACH", False):
		logger.info("send: REACH is False, skipping.")
		return 0, 0

	from accounts.models import monthly_sent_count, increment_monthly_sent
	monthly_cap = getattr(settings, 'MONTHLY_REACH', 12000)
	already_sent = monthly_sent_count()
	if already_sent >= monthly_cap:
		logger.info('send: monthly cap reached (%d/%d), skipping.', already_sent, monthly_cap)
		return 0, 0

	from accounts.models import OutreachRecord, OutreachContactedEmail

	domain = settings.DOMAIN
	try:
		html      = build_html(domain)
		plaintext = build_plaintext(domain)
		logger.info('send: html=%d chars plaintext=%d chars', len(html), len(plaintext))
	except Exception as exc:
		logger.error('send: failed to build email templates: %s', exc)
		return 0, 0

	batch   = limit or getattr(settings, "SEND_BATCH", 50)
	pending = list(OutreachRecord.objects.order_by("-score", "created_at")[:batch])

	if not pending:
		logger.info("send: queue empty, nothing to send.")
		return 0, 0

	if log:
		log(f"Sending {len(pending)} emails...")

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
		if ok:
			# Only mark contacted and remove from queue on success
			OutreachContactedEmail.objects.get_or_create(email=record.email)
			record.delete()
			sent += 1
			if log:
				log(f"  ✓ {record.email}")
		else:
			failed += 1
			logger.error("send: failed for %s", record.email)
			if log:
				log(f"  ✗ {record.email}")

	if sent:
		increment_monthly_sent(sent)

	update_daily_stats(
		timezone.now().date(),
		queued_count=len(pending),
		sent_count=sent,
		failed_count=failed,
		pending_after=OutreachRecord.objects.count(),
	)
	logger.info("send: sent=%d failed=%d", sent, failed)
	return sent, failed


@app.periodic(cron="0 2 * * *")
@app.task
def harvest_outreach_emails(timestamp=None):
	"""Periodic task: harvest GitHub candidates into the queue."""
	run_harvest()


@app.periodic(cron="0 */2 * * *")
@app.task
def send_outreach_emails(timestamp=None):
	"""Periodic task: send top-scored pending records via SendPulse."""
	run_send()