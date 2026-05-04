# setup/models.py
from django.db import models


class FiredError(models.Model):
    signature = models.CharField(max_length=64, unique=True)
    github_issue_url = models.URLField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
