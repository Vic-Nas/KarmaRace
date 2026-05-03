# accounts/management/commands/harvest_outreach.py
"""Management command to manually harvest outreach emails (for missed cron)."""
import logging
import random
import urllib.parse
from tqdm import tqdm

from django.core.management.base import BaseCommand
from django.conf import settings
from django.utils import timezone

from accounts.outreach.config import BATCH

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Harvest outreach email candidates. Defaults to BATCH=500.'

    def add_arguments(self, parser):
        parser.add_argument(
            'limit',
            nargs='?',
            type=int,
            default=BATCH,
            help=f'Max candidates to harvest (default: {BATCH})'
        )

    def handle(self, *args, **options):
        if not getattr(settings, 'REACH', False):
            self.stdout.write(self.style.WARNING('REACH is disabled. Skipping.'))
            return

        limit = options['limit']
        if limit <= 0:
            self.stdout.write(self.style.ERROR('Limit must be positive.'))
            return

        # Import here to avoid issues if REACH is disabled
        from accounts.models import OutreachRecord, OutreachContactedEmail, OutreachDailyStats
        from accounts.outreach.config import GITHUB_API, SEARCH_BASE, LANGUAGES, score_user, gh_get

        queued    = set(OutreachRecord.objects.values_list('email', flat=True))
        contacted = set(OutreachContactedEmail.objects.values_list('email', flat=True))
        skip      = queued | contacted

        new_records = []
        page = 1
        lang = random.choice(LANGUAGES)
        query = urllib.parse.quote(SEARCH_BASE + ' language:' + lang)

        self.stdout.write(f'Starting harvest (limit={limit}, lang={lang})...')

        with tqdm(total=limit, desc='Harvesting candidates', unit='candidate', dynamic_ncols=True) as pbar:
            while len(new_records) < limit:
                url = f'{GITHUB_API}/search/users?q={query}&per_page=30&page={page}'
                data = gh_get(url)
                if not data or not data.get('items'):
                    pbar.write(f'ℹ No more results at page {page}. Stopping.')
                    break

                for item in data['items']:
                    if len(new_records) >= limit:
                        break

                    profile = gh_get(f'{GITHUB_API}/users/{item["login"]}')
                    if not profile:
                        continue

                    email = (profile.get('email') or '').strip().lower()
                    if not email or email in skip:
                        continue

                    repos = gh_get(f'{GITHUB_API}/users/{item["login"]}/repos?per_page=30')
                    if not repos or not any(r.get('homepage') for r in repos):
                        continue

                    score = score_user(profile, repos)
                    skip.add(email)
                    new_records.append(OutreachRecord(email=email, score=score))
                    pbar.update(1)

                page += 1

        if new_records:
            OutreachRecord.objects.bulk_create(new_records, ignore_conflicts=True)
            self.stdout.write(self.style.SUCCESS(f'✓ Harvested {len(new_records)} candidates'))
        else:
            self.stdout.write(self.style.WARNING('No new candidates harvested.'))

        # Update daily stats
        today = timezone.now().date()
        stats, _ = OutreachDailyStats.objects.get_or_create(date=today)
        stats.harvested = len(new_records)
        stats.save(update_fields=['harvested', 'updated_at'])

        logger.info('harvest_outreach: harvested=%d (lang=%s)', len(new_records), lang)
