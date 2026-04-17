# tasks/models.py
from django.db import models
from accounts.models import User


class Task(models.Model):

    class Type(models.TextChoices):
        GITHUB_STAR = 'GITHUB_STAR'
        GITHUB_FORK = 'GITHUB_FORK'
        PH_COMMENT  = 'PH_COMMENT'
        WEBHOOK     = 'WEBHOOK'

    owner          = models.ForeignKey(User, on_delete=models.CASCADE, related_name='owned_tasks')
    type           = models.CharField(max_length=20, choices=Type.choices)
    description    = models.TextField()
    target_id      = models.CharField(max_length=500)
    webhook_secret = models.CharField(max_length=255, blank=True, default='')
    succeed_count  = models.PositiveIntegerField(default=0)
    tried_count    = models.PositiveIntegerField(default=0)
    is_deleted     = models.BooleanField(default=False)
    hidden         = models.BooleanField(default=False)
    archived_by    = models.ManyToManyField(User, blank=True, related_name='archived_tasks')
    created_at     = models.DateTimeField(auto_now_add=True)

    @property
    def target_url(self):
        """Return a user-facing destination URL for this task."""
        target = (self.target_id or '').strip()
        if not target:
            return ''

        if self.type in (self.Type.GITHUB_STAR, self.Type.GITHUB_FORK):
            return f'https://github.com/{target}'

        if self.type == self.Type.PH_COMMENT:
            return f'https://www.producthunt.com/products/{target}'

        if self.type == self.Type.WEBHOOK:
            return target

        return ''

    def __str__(self):
        return f'{self.owner.username} — {self.type}'


class TaskCompletion(models.Model):

    class State(models.TextChoices):
        PENDING   = 'PENDING'
        CONFIRMED = 'CONFIRMED'
        FAILED    = 'FAILED'

    task       = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='completions')
    tester     = models.ForeignKey(User, on_delete=models.CASCADE, related_name='task_completions')
    state      = models.CharField(max_length=10, choices=State.choices, default=State.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('task', 'tester')]