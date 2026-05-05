# accounts/management/commands/send_outreach.py
"""Management command to trigger an outreach send job on the worker."""
from django.core.management.base import BaseCommand
from django.conf import settings


class Command(BaseCommand):
    help = (
        'Defer a send job to the worker, or run inline with --now. '
        'Pass --email to send a one-off test to a specific address.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            'limit', nargs='?', type=int, default=None,
            help='Max emails to send from the queue (default: SEND_BATCH from settings)',
        )
        parser.add_argument(
            '--now', action='store_true',
            help='Run inline in this process instead of deferring to a worker (shows progress)',
        )
        parser.add_argument(
            '--email', type=str, default=None,
            help='Send a one-off test email to this address (skips queue and duplicate checks)',
        )

    def handle(self, *args, **options):
        if not getattr(settings, 'REACH', False):
            self.stdout.write(self.style.WARNING('REACH is disabled. Skipping.'))
            return

        # --- One-off test send ---
        if options['email']:
            from accounts.outreach.config import SUBJECT, sendpulse_post
            from accounts.outreach.email import build_html, build_plaintext

            domain = settings.DOMAIN
            target = options['email']
            self.stdout.write(f'Sending test to {target}...')
            ok = sendpulse_post({
                'email': {
                    'from':    {'name': 'KarmaRace', 'email': f'outreach@{domain}'},
                    'to':      [{'name': '', 'email': target}],
                    'subject': SUBJECT,
                    'html':    build_html(domain),
                    'text':    build_plaintext(domain),
                }
            })
            if ok:
                self.stdout.write(self.style.SUCCESS(f'✓ Sent to {target}.'))
            else:
                self.stdout.write(self.style.ERROR(f'✗ Failed to send to {target}.'))
            return

        # --- Queue mode ---
        if options['now']:
            from accounts.outreach.tasks import run_send
            sent, failed = run_send(limit=options['limit'], log=self.stdout.write)
            self.stdout.write(self.style.SUCCESS(f'✓ Sent {sent}, failed {failed}.'))
        else:
            from accounts.outreach.tasks import send_outreach_emails
            send_outreach_emails.defer(limit=options["limit"])
            self.stdout.write(self.style.SUCCESS(
                '✓ Send job deferred to worker. '
                'Use --now to run inline with progress output.'
            ))