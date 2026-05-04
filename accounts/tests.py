# accounts/tests.py
from django.test import TestCase
from django.contrib.auth import get_user_model
from accounts.models import OutreachMonthlyStats, monthly_sent_count, increment_monthly_sent

User = get_user_model()


class MonthlyStatsTests(TestCase):

    def test_monthly_sent_count_zero_when_no_row(self):
        self.assertEqual(monthly_sent_count(), 0)

    def test_increment_creates_and_accumulates(self):
        increment_monthly_sent(5)
        self.assertEqual(monthly_sent_count(), 5)
        increment_monthly_sent(3)
        self.assertEqual(monthly_sent_count(), 8)

    def test_increment_unique_per_month(self):
        from django.utils import timezone
        from unittest.mock import patch
        import datetime
        jan = datetime.datetime(2026, 1, 15, tzinfo=datetime.timezone.utc)
        feb = datetime.datetime(2026, 2, 15, tzinfo=datetime.timezone.utc)
        with patch('accounts.models.timezone') as mock_tz:
            mock_tz.now.return_value = jan
            increment_monthly_sent(10)
        with patch('accounts.models.timezone') as mock_tz:
            mock_tz.now.return_value = feb
            increment_monthly_sent(7)
        self.assertEqual(OutreachMonthlyStats.objects.count(), 2)
