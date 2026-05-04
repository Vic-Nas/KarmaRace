# notifications/tests.py
from django.test import TestCase
from django.contrib.auth import get_user_model
from notifications.models import Notification
from notifications.services import notify

User = get_user_model()


class NotifyTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(username='notifuser', password='x')

    def test_notify_creates_notification(self):
        notify(self.user, Notification.Event.KARMA_LOW, payload={'balance': 5, 'threshold': 20})
        self.assertEqual(Notification.objects.filter(user=self.user).count(), 1)

    def test_notification_unread_by_default(self):
        notify(self.user, Notification.Event.KARMA_LOW, payload={'balance': 5, 'threshold': 20})
        notif = Notification.objects.get(user=self.user)
        self.assertIsNone(notif.read_at)

    def test_notify_stores_payload(self):
        notify(self.user, Notification.Event.KARMA_ADJUSTED, payload={'delta': 10, 'new_balance': 25})
        notif = Notification.objects.get(user=self.user)
        self.assertEqual(notif.payload['delta'], 10)
