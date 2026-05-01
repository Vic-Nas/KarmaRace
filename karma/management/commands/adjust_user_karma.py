from django.core.management.base import BaseCommand, CommandError
from accounts.models import User
from karma.services import adjust_karma_by_staff


class Command(BaseCommand):
    help = 'Adjust user karma by amount (positive=credit, negative=debit). Sends KARMA_ADJUSTED notification.'

    def add_arguments(self, parser):
        parser.add_argument('username', type=str, help='Username to adjust karma for')
        parser.add_argument('delta', type=int, help='Amount to adjust (positive=credit, negative=debit)')
        parser.add_argument(
            '--reason',
            type=str,
            default=None,
            help='Optional reason (appears in user notification)'
        )

    def handle(self, *args, **options):
        username = options['username']
        delta = options['delta']
        reason = options['reason']

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            raise CommandError(f'User "{username}" not found')

        try:
            new_balance = adjust_karma_by_staff(user, delta, reason)
            self.stdout.write(
                self.style.SUCCESS(
                    f'✓ Adjusted {username} karma by {delta:+d} → new balance: {new_balance}'
                )
            )
        except Exception as e:
            raise CommandError(f'Error adjusting karma: {str(e)}')
