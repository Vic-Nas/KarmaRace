"""Management command to manually send outreach emails (for missed cron)."""
import logging

from django.core.management.base import BaseCommand
from django.conf import settings

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Send pending outreach emails. Defaults to DAILY_REACH=100.'

    def add_arguments(self, parser):
        parser.add_argument(
            'limit',
            nargs='?',
            type=int,
            default=None,
            help='Max emails to send (default: DAILY_REACH from settings, typically 100)'
        )

    def handle(self, *args, **options):
        if not getattr(settings, 'REACH', False):
            self.stdout.write(self.style.WARNING('REACH is disabled. Skipping.'))
            return

        daily_reach = getattr(settings, 'DAILY_REACH', 100)
        limit = options['limit'] if options['limit'] is not None else daily_reach

        if limit <= 0:
            self.stdout.write(self.style.ERROR('Limit must be positive.'))
            return

        # Import here to avoid issues if REACH is disabled
        from django.utils import timezone
        from accounts.models import OutreachRecord, OutreachContactedEmail, OutreachDailyStats
        from accounts.outreach.config import RESEND_API, SUBJECT
        from accounts.outreach.email import build_html, build_plaintext
        from accounts.outreach.config import resend_post

        domain = settings.DOMAIN
        from_addr = 'KarmaRace <outreach@' + domain + '>'
        html = build_html(domain)
        plaintext = build_plaintext(domain)

        pending = list(
            OutreachRecord.objects.order_by('-score', 'created_at')[:limit]
        )

        if not pending:
            self.stdout.write(self.style.WARNING('No pending outreach records.'))
            return

        self.stdout.write(f'Sending {len(pending)} emails...')

        sent = failed = 0
        for i, record in enumerate(pending, 1):
            ok = resend_post({
                'from': from_addr,
                'to': [record.email],
                'subject': SUBJECT,
                'html': html,
                'text': plaintext,
            })
            OutreachContactedEmail.objects.get_or_create(email=record.email)
            record.delete()
            
            if ok:
                sent += 1
                status = '✓'
            else:
                failed += 1
                status = '✗'
            
            if i % 10 == 0 or i == len(pending):
                self.stdout.write(f'  {i}/{len(pending)} emails processed ({sent} sent, {failed} failed)')

        # Update daily stats
        today = timezone.now().date()
        pending_after = OutreachRecord.objects.count()
        stats, _ = OutreachDailyStats.objects.get_or_create(date=today)
        stats.queued_count = len(pending)
        stats.sent_count = sent
        stats.failed_count = failed
        stats.pending_after = pending_after
        stats.save(update_fields=[
            'queued_count', 'sent_count', 'failed_count', 'pending_after', 'updated_at'
        ])

        self.stdout.write(self.style.SUCCESS(
            f'✓ Sent {sent} emails, {failed} failed. {pending_after} pending remaining.'
        ))

        logger.info(
            'send_outreach: sent=%d failed=%d pending_after=%d',
            sent, failed, pending_after,
        )
