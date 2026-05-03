# tasks/models.py
from django.db import models
from accounts.models import User


class Task(models.Model):

    class Type(models.TextChoices):
        GITHUB_STAR = 'GITHUB_STAR'
        GITHUB_FORK = 'GITHUB_FORK'
        WEBHOOK     = 'WEBHOOK'

    owner          = models.ForeignKey(User, on_delete=models.CASCADE, related_name='owned_tasks')
    type           = models.CharField(max_length=20, choices=Type.choices)
    slug           = models.SlugField(max_length=180, blank=True, db_index=True)
    description    = models.TextField()
    target_id      = models.CharField(max_length=500)
    webhook_secret = models.CharField(max_length=255, blank=True, default='')
    priority       = models.PositiveSmallIntegerField(default=0, db_index=True)
    succeed_count  = models.PositiveIntegerField(default=0)
    tried_count    = models.PositiveIntegerField(default=0)
    is_deleted          = models.BooleanField(default=False)
    hidden              = models.BooleanField(default=False)
    owner_unpublished   = models.BooleanField(default=False)
    health_failure_streak       = models.PositiveSmallIntegerField(default=0)
    health_last_failure_reason  = models.TextField(blank=True, default='')
    health_last_checked_at      = models.DateTimeField(null=True, blank=True)
    webhook_health_success_count = models.PositiveIntegerField(default=0)
    webhook_health_failure_count = models.PositiveIntegerField(default=0)
    health_last_result  = models.CharField(max_length=64, blank=True, default='')
    difficulty_sum   = models.PositiveIntegerField(default=0)
    difficulty_count = models.PositiveIntegerField(default=0)
    archived_by         = models.ManyToManyField(User, blank=True, related_name='archived_tasks')
    created_at          = models.DateTimeField(auto_now_add=True)

    @property
    def difficulty(self):
        """Average difficulty rating (1-5). Defaults to 1 if no ratings yet."""
        if self.difficulty_count > 0:
            return max(1, min(5, round(self.difficulty_sum / self.difficulty_count)))
        return 1

    @property
    def target_url(self):
        target = (self.target_id or '').strip()
        if not target:
            return ''
        if self.type in (self.Type.GITHUB_STAR, self.Type.GITHUB_FORK):
            return f'https://github.com/{target}'
        if self.type == self.Type.WEBHOOK:
            return target
        return ''

    @property
    def webhook_owner_reason_summary(self):
        if self.type != self.Type.WEBHOOK:
            return self.health_last_failure_reason
        result = (self.health_last_result or '').strip().lower()
        summaries = {
            'request_error':     'Webhook endpoint is unreachable from the server.',
            'invalid_json':      'Webhook endpoint must return JSON with "verified": true or false.',
            'invalid_shape':     'Webhook response JSON is missing a boolean "verified" field.',
            'not_verified':      'Webhook responded with verified=false.',
            'not_verified_health': 'Webhook responded with verified=false.',
            'verified':          'Last health check passed.',
        }
        return summaries.get(result, 'Webhook health check failed. See Notifications for details.')

    def __str__(self):
        return f'{self.owner.username} — {self.type}'


class TaskCompletion(models.Model):

    class State(models.TextChoices):
        PENDING   = 'PENDING'
        CONFIRMED = 'CONFIRMED'
        FAILED    = 'FAILED'

    task          = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='completions')
    tester        = models.ForeignKey(User, on_delete=models.CASCADE, related_name='task_completions')
    state         = models.CharField(max_length=10, choices=State.choices, default=State.PENDING)
    result_detail = models.TextField(blank=True, default='')
    reward        = models.PositiveSmallIntegerField(default=0)
    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('task', 'tester')]


class ReciprocityObligation(models.Model):

    class State(models.TextChoices):
        OPEN      = 'OPEN'
        FULFILLED = 'FULFILLED'
        CANCELLED = 'CANCELLED'

    debtor    = models.ForeignKey(User, on_delete=models.CASCADE, related_name='obligations_owed')
    creditor  = models.ForeignKey(User, on_delete=models.CASCADE, related_name='obligations_due')
    task_type = models.CharField(max_length=20, choices=Task.Type.choices)
    state     = models.CharField(max_length=12, choices=State.choices, default=State.OPEN)
    error_strike_count = models.PositiveSmallIntegerField(default=0)
    source_difficulty  = models.PositiveSmallIntegerField(null=True, blank=True)
    source_task = models.ForeignKey(
        Task, on_delete=models.SET_NULL, null=True, blank=True, related_name='obligations_created',
    )
    fulfilled_by_task = models.ForeignKey(
        Task, on_delete=models.SET_NULL, null=True, blank=True, related_name='obligations_fulfilled',
    )
    created_at   = models.DateTimeField(auto_now_add=True)
    fulfilled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['debtor', 'state']),
            models.Index(fields=['debtor', 'creditor', 'task_type', 'state']),
        ]

    def __str__(self):
        return f'{self.debtor_id} owes {self.creditor_id} ({self.task_type}) [{self.state}]'
