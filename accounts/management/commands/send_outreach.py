# accounts/management/commands/send_outreach.py
"""Management command to manually send outreach emails (for missed cron)."""
import logging
from tqdm import tqdm

from django.core.management.base import BaseCommand
from django.conf import settings

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Send pending outreach emails. Defaults to DAILY_REACH=50. Pass --email to send to a specific address.'

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group()
        group.add_argument(
            'limit',
            nargs='?',
            type=int,
            default=None,
            help='Max emails to send from the queue (default: DAILY_REACH from settings, typically 50)'
        )
        group.add_argument(
            '--email',
            type=str,
            default=None,
            help='Send directly to this email address (skips DB queue and duplicate checks)'
        )

    def handle(self, *args, **options):
        if not getattr(settings, 'REACH', False):
            self.stdout.write(self.style.WARNING('REACH is disabled. Skipping.'))
            return

        from accounts.models import monthly_sent_count, increment_monthly_sent
        if monthly_sent_count() >= getattr(settings, 'MONTHLY_REACH', 12000):
            self.stdout.write(self.style.WARNING('Monthly send cap reached.'))
            return

        from accounts.outreach.config import SUBJECT, sendpulse_post, update_daily_stats
        from accounts.outreach.email import build_html, build_plaintext

        domain = settings.DOMAIN
        html = build_html(domain)
        plaintext = build_plaintext(domain)

        def send_one(email: str) -> bool:
            payload = {
                'email': {
                    'from': {'name': 'KarmaRace', 'email': f'outreach@{domain}'},
                    'to': [{'name': '', 'email': email}],
                    'subject': SUBJECT,
                    'html': html,
                    'text': plaintext,
                }
            }
            return sendpulse_post(payload)

        target_email = options.get('email')

        # --- Single-address mode ---
        if target_email:
            self.stdout.write(f'Sending to {target_email}...')
            ok = send_one(target_email)
            if ok:
                increment_monthly_sent(1)
                self.stdout.write(self.style.SUCCESS(f'✓ Sent to {target_email}.'))
            else:
                self.stdout.write(self.style.ERROR(f'✗ Failed to send to {target_email}.'))
            return

        # --- Queue mode ---
        from django.utils import timezone
        from accounts.models import OutreachRecord, OutreachContactedEmail

        daily_reach = getattr(settings, 'DAILY_REACH', 50)
        limit = options['limit'] if options['limit'] is not None else daily_reach

        if limit <= 0:
            self.stdout.write(self.style.ERROR('Limit must be positive.'))
            return

        pending = list(
            OutreachRecord.objects.order_by('-score', 'created_at')[:limit]
        )

        if not pending:
            self.stdout.write(self.style.WARNING('No pending outreach records.'))
            return

        sent = failed = 0
        with tqdm(pending, desc='Sending emails', unit='email', dynamic_ncols=True) as pbar:
            for record in pbar:
                ok = send_one(record.email)
                OutreachContactedEmail.objects.get_or_create(email=record.email)
                record.delete()

                if ok:
                    sent += 1
                else:
                    failed += 1
                    self.stdout.write(self.style.ERROR(f'✗ Failed: from=outreach@{domain} to={record.email}'))

                pbar.set_postfix({'sent': sent, 'failed': failed}, refresh=True)

        if sent:
            increment_monthly_sent(sent)

        update_daily_stats(
            timezone.now().date(),
            queued_count=len(pending),
            sent_count=sent,
            failed_count=failed,
            pending_after=OutreachRecord.objects.count(),
        )

        pending_after = OutreachRecord.objects.count()
        self.stdout.write(self.style.SUCCESS(
            f'✓ Sent {sent} emails, {failed} failed. {pending_after} pending remaining.'
        ))

        logger.info(
            'send_outreach: sent=%d failed=%d pending_after=%d',
            sent, failed, pending_after,
        )