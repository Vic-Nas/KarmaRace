# accounts/management/commands/harvest_outreach.py
"""Management command to trigger an outreach harvest job on the worker."""
from django.core.management.base import BaseCommand
from django.conf import settings

from accounts.outreach.config import BATCH


class Command(BaseCommand):
    help = (
        'Defer a harvest job to the worker, or run inline with --now. '
        f'Default limit: BATCH={BATCH}.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            'limit', nargs='?', type=int, default=None,
            help=f'Max candidates to harvest (default: BATCH={BATCH})',
        )
        parser.add_argument(
            '--now', action='store_true',
            help='Run inline in this process instead of deferring to a worker (shows progress)',
        )

    def handle(self, *args, **options):
        if not getattr(settings, 'REACH', False):
            self.stdout.write(self.style.WARNING('REACH is disabled. Skipping.'))
            return

        limit = options['limit']

        if options['now']:
            from accounts.outreach.tasks import run_harvest
            count = run_harvest(limit=limit, log=self.stdout.write)
            self.stdout.write(self.style.SUCCESS(f'✓ Harvested {count} candidates.'))
        else:
            from accounts.outreach.tasks import harvest_outreach_emails
            harvest_outreach_emails.defer()
            self.stdout.write(self.style.SUCCESS(
                '✓ Harvest job deferred to worker. '
                'Use --now to run inline with progress output.'
            ))