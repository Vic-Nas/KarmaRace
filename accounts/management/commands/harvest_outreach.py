# accounts/management/commands/harvest_outreach.py
"""Management command to manually harvest outreach emails (for missed cron)."""
import logging
import random
from tqdm import tqdm

from django.core.management.base import BaseCommand
from django.conf import settings
from django.utils import timezone

from accounts.outreach.config import BATCH, LANGUAGES, SEARCH_BASE, score_user, iter_candidates, update_daily_stats

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = f'Harvest outreach email candidates. Defaults to BATCH={BATCH}.'

    def add_arguments(self, parser):
        parser.add_argument('limit', nargs='?', type=int, default=BATCH,
                            help=f'Max candidates to harvest (default: {BATCH})')

    def handle(self, *args, **options):
        if not getattr(settings, 'REACH', False):
            self.stdout.write(self.style.WARNING('REACH is disabled. Skipping.'))
            return

        limit = options['limit']
        if limit <= 0:
            self.stdout.write(self.style.ERROR('Limit must be positive.'))
            return

        from accounts.models import OutreachRecord, OutreachContactedEmail

        queued    = set(OutreachRecord.objects.values_list('email', flat=True))
        contacted = set(OutreachContactedEmail.objects.values_list('email', flat=True))
        skip      = queued | contacted

        new_records = []
        lang  = random.choice(LANGUAGES)
        query = SEARCH_BASE + ' language:' + lang

        self.stdout.write(f'Starting harvest (limit={limit}, lang={lang})...')

        with tqdm(total=limit, desc='Harvesting candidates', unit='candidate', dynamic_ncols=True) as pbar:
            for profile, repos in iter_candidates(query, max_candidates=limit * 5, max_repos=30):
                if len(new_records) >= limit:
                    break
                email = (profile.get('email') or '').strip().lower()
                if not email or email in skip:
                    continue
                if not any(getattr(r, 'homepage', '') for r in repos):
                    continue
                score = score_user(profile, repos)
                skip.add(email)
                new_records.append(OutreachRecord(email=email, score=score))
                pbar.update(1)

        if new_records:
            OutreachRecord.objects.bulk_create(new_records, ignore_conflicts=True)
            self.stdout.write(self.style.SUCCESS(f'✓ Harvested {len(new_records)} candidates'))
        else:
            self.stdout.write(self.style.WARNING('No new candidates harvested.'))

        update_daily_stats(timezone.now().date(), harvested=len(new_records))
        logger.info('harvest_outreach: harvested=%d (lang=%s)', len(new_records), lang)