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
    """Pending outreach queue. Ephemeral; deleted after successful send."""

    email      = models.EmailField(unique=True)
    score      = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=['-score'])]

    def __str__(self):
        return f'{self.email} (score={self.score})'


class OutreachContactedEmail(models.Model):
    """Permanent dedup log: emails we've successfully reached."""

    email        = models.EmailField(unique=True)
    contacted_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.email


class OutreachState(models.Model):
    """Persistent harvest state. Single-row singleton (pk=1)."""

    harvest_offset = models.IntegerField(default=0)
    harvest_lang   = models.CharField(max_length=50, blank=True, default='')
    updated_at     = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Outreach State'

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return f'OutreachState(offset={self.harvest_offset}, lang={self.harvest_lang})'