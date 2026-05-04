# karma/tests.py
from django.test import TestCase
from django.contrib.auth import get_user_model
from karma.services import get_balance, credit_karma, debit_karma
from karma.models import KarmaTransaction

User = get_user_model()


class KarmaServicesTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='x')

    def test_balance_zero_initially(self):
        self.assertEqual(get_balance(self.user), 0)

    def test_credit_increases_balance(self):
        credit_karma(self.user, 10, KarmaTransaction.Reason.TASK_EARNED)
        self.assertEqual(get_balance(self.user), 10)

    def test_debit_decreases_balance(self):
        credit_karma(self.user, 20, KarmaTransaction.Reason.TASK_EARNED)
        debit_karma(self.user, 5, KarmaTransaction.Reason.TASK_COST)
        self.assertEqual(get_balance(self.user), 15)

    def test_debit_skipped_if_insufficient_balance(self):
        credit_karma(self.user, 5, KarmaTransaction.Reason.TASK_EARNED)
        debit_karma(self.user, 10, KarmaTransaction.Reason.TASK_COST)
        self.assertEqual(get_balance(self.user), 5)  # unchanged

    def test_credit_and_debit_create_transactions(self):
        credit_karma(self.user, 10, KarmaTransaction.Reason.TASK_EARNED)
        debit_karma(self.user, 3, KarmaTransaction.Reason.TASK_COST)
        self.assertEqual(KarmaTransaction.objects.filter(user=self.user).count(), 2)
