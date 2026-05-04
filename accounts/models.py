# accounts/models.py
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    is_pro = models.BooleanField(default=False)


class LinkedAccount(models.Model):
    GITHUB   = 'github'
    DISCORD  = 'discord'
    PLATFORM_CHOICES = [(GITHUB, 'GitHub'), (DISCORD, 'Discord')]

    user              = models.ForeignKey(User, on_delete=models.CASCADE, related_name='linked_accounts')
    platform          = models.CharField(max_length=50, choices=PLATFORM_CHOICES)
    platform_id       = models.CharField(max_length=200)
    platform_username = models.CharField(max_length=200)
    access_token             = models.CharField(max_length=500, blank=True)
    discord_notifs_thread_id = models.CharField(max_length=30, blank=True, default='')
    connected_at             = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('user', 'platform'), ('platform', 'platform_id')]


class UserPreference(models.Model):
    """
    Per-user overrides for platform defaults.
    Lookup pattern: check here first, fall back to setup/platform_rules.py if absent.
    """
    user  = models.ForeignKey(User, on_delete=models.CASCADE, related_name='preferences')
    key   = models.CharField(max_length=100)
    value = models.CharField(max_length=500)

    class Meta:
        unique_together = [('user', 'key')]

    def __str__(self):
        return f'{self.user_id} / {self.key} = {self.value}'


class UserProfile(models.Model):
    """Public-facing profile info. One row per user, created on demand."""
    user          = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    first_name    = models.CharField(max_length=100, blank=True)
    last_name     = models.CharField(max_length=100, blank=True)
    contact_email = models.EmailField(blank=True)

    # Visibility flags: True means the field is shown publicly.
    show_first_name    = models.BooleanField(default=True)
    show_last_name     = models.BooleanField(default=False)
    show_contact_email = models.BooleanField(default=False)
    show_github        = models.BooleanField(default=True)
    show_karma         = models.BooleanField(default=True)
    show_joined        = models.BooleanField(default=True)

    def __str__(self):
        return f'Profile({self.user_id})'


class VerifiedEmail(models.Model):
    user        = models.ForeignKey(User, on_delete=models.CASCADE, related_name='verified_emails')
    email       = models.EmailField(unique=True)
    verified_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.user_id}: {self.email}'


class OutreachRecord(models.Model):
    """Pending outreach queue. Ephemeral; deleted after send attempt."""

    email      = models.EmailField(unique=True)
    score      = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=['-score'])]

    def __str__(self):
        return f'{self.email} (score={self.score})'


class OutreachContactedEmail(models.Model):
    """Permanent dedup log: emails we've already attempted to reach."""

    email        = models.EmailField(unique=True)
    contacted_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.email


class OutreachDailyStats(models.Model):
    """Latest daily outreach results. One row per date, updated each run."""

    date           = models.DateField(unique=True)
    queued_count   = models.IntegerField(default=0)
    sent_count     = models.IntegerField(default=0)
    failed_count   = models.IntegerField(default=0)
    pending_after  = models.IntegerField(default=0)
    harvested      = models.IntegerField(default=0)
    updated_at     = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date']

    def __str__(self):
        return f'{self.date}: sent={self.sent_count} failed={self.failed_count}'
 

class OutreachMonthlyStats(models.Model):
    year       = models.IntegerField()
    month      = models.IntegerField()  # 1-12
    sent_count = models.IntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('year', 'month')
        ordering = ['-year', '-month']

    def __str__(self):
        return f'{self.year}-{self.month:02d}: sent={self.sent_count}'


def monthly_sent_count() -> int:
    """Return total emails sent this calendar month."""
    from django.utils import timezone
    now = timezone.now()
    obj = OutreachMonthlyStats.objects.filter(
        year=now.year, month=now.month
    ).first()
    return obj.sent_count if obj else 0


def increment_monthly_sent(count: int) -> None:
    """Add count to this month's sent total (upsert)."""
    from django.utils import timezone
    now = timezone.now()
    obj, _ = OutreachMonthlyStats.objects.get_or_create(
        year=now.year, month=now.month
    )
    obj.sent_count = models.F('sent_count') + count
    obj.save(update_fields=['sent_count', 'updated_at'])
