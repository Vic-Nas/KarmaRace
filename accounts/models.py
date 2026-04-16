# accounts/models.py
from django.contrib.auth.models import AbstractUser
from django.db import models

class User(AbstractUser):
    pass

class LinkedAccount(models.Model):
    GITHUB = 'github'
    DISCORD = 'discord'
    # add platforms here as you need them
    PLATFORM_CHOICES = [
        (GITHUB, 'GitHub'),
        (DISCORD, 'Discord'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='linked_accounts')
    platform = models.CharField(max_length=50, choices=PLATFORM_CHOICES)
    platform_id = models.CharField(max_length=200)       # immutable ID from the platform
    platform_username = models.CharField(max_length=200) # for display only
    connected_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('user', 'platform'), ('platform', 'platform_id')]