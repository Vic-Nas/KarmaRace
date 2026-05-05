# accounts/outreach/tasks.py
"""Periodic outreach tasks (harvest and send)."""
import logging
import re
import random

from django.conf import settings
from django.utils import timezone
from procrastinate.contrib.django import app

from .config import (
	BATCH, SUBJECT, LANGUAGES, SEARCH_BASE,
	score_user, iter_candidates,
	sendpulse_post,
)
from .email import build_html, build_plaintext

logger = logging.getLogger(__name__)


def run_harvest(limit=None, log=None):
	"""Core harvest logic. Shared by the periodic task and management command.

	Continues from where the last harvest left off using OutreachState.
	Returns number of records harvested.
	log: callable for progress output. Optional.
	"""
	if not getattr(settings, "REACH", False):
		logger.info("harvest: REACH is False, skipping.")
		return 0

	from accounts.models import OutreachRecord, OutreachContactedEmail, OutreachState

	queued    = set(OutreachRecord.objects.values_list("email", flat=True))
	contacted = set(OutreachContactedEmail.objects.values_list("email", flat=True))
	skip      = queued | contacted

	state  = OutreachState.get()
	batch  = limit or BATCH
	lang   = state.harvest_lang or random.choice(LANGUAGES)
	offset = state.harvest_offset
	query  = SEARCH_BASE + " language:" + lang
	max_candidates = batch * 20

	if log:
		log(f"Harvesting (limit={batch}, lang={lang}, offset={offset}, skip={len(skip)})...")

	new_records = []
	last_idx    = offset
	for idx, profile, repos in iter_candidates(query, max_candidates, max_repos=60, offset=offset):
		if len(new_records) >= batch:
			break
		last_idx = idx
		email = (profile.get("email") or "").strip().lower()
		if not email or email in skip or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
			continue
		score = score_user(profile, repos)
		skip.add(email)
		new_records.append(OutreachRecord(email=email, score=score))
		if log:
			log(f"  +{len(new_records)} {email} (score={score})")

	if new_records:
		OutreachRecord.objects.bulk_create(new_records, ignore_conflicts=True)

	# Advance offset; rotate language when results are exhausted
	new_offset = last_idx + 1
	if len(new_records) < batch:
		new_offset = 0
		lang = random.choice([l for l in LANGUAGES if l != lang] or LANGUAGES)
		if log:
			log(f"  End of results, rotating lang to {lang}")

	state.harvest_offset = new_offset
	state.harvest_lang   = lang
	state.save(update_fields=['harvest_offset', 'harvest_lang', 'updated_at'])

	logger.info("harvest: harvested=%d lang=%s offset=%d->%d", len(new_records), lang, offset, new_offset)
	return len(new_records)


def run_send(limit=None, log=None):
	"""Core send logic. Shared by the periodic task and management command.

	Sends top-scored pending OutreachRecords via SendPulse.
	Only deletes a record from the queue after a successful send.
	Returns (sent, failed).
	log: callable for progress output. Optional.
	"""
	if not getattr(settings, "REACH", False):
		logger.info("send: REACH is False, skipping.")
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

	logger.info("send: sent=%d failed=%d", sent, failed)
	return sent, failed


@app.periodic(cron="0 2 * * *")
@app.task
def harvest_outreach_emails(timestamp=None, limit=None):
	"""Periodic task: harvest GitHub candidates into the queue."""
	run_harvest(limit=limit)


@app.periodic(cron="0 */2 * * *")
@app.task
def send_outreach_emails(timestamp=None, limit=None):
	"""Periodic task: send top-scored pending records via SendPulse."""
	run_send(limit=limit)