# projects/models.py
from django.db import models
from accounts.models import User


class Project(models.Model):

    class State(models.TextChoices):
        ACTIVE   = 'ACTIVE'
        INACTIVE = 'INACTIVE'

    owner                = models.ForeignKey(User, on_delete=models.CASCADE, related_name='projects')
    name                 = models.CharField(max_length=120)
    url                  = models.URLField()
    description          = models.TextField(max_length=500)
    state                = models.CharField(max_length=10, choices=State.choices, default=State.INACTIVE)
    total_tests_received = models.PositiveIntegerField(default=0)
    archived_by          = models.ManyToManyField(User, blank=True, related_name='archived_projects')
    created_at           = models.DateTimeField(auto_now_add=True)
    went_inactive_at     = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.name