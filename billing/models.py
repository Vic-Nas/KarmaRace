# billing/models.py
from django.conf import settings
from django.db import models


class BillingProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='billing_profile',
    )
    stripe_customer_id = models.CharField(max_length=120, blank=True, default='', db_index=True)
    stripe_subscription_id = models.CharField(max_length=120, blank=True, default='', db_index=True)
    subscription_status = models.CharField(max_length=40, blank=True, default='')
    current_period_end = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'BillingProfile(user={self.user_id}, status={self.subscription_status or "none"})'
