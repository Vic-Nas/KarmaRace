# karma/models.py
from django.db import models
from accounts.models import User


class KarmaTransaction(models.Model):

    class Reason(models.TextChoices):
        TASK_EARNED       = 'TASK_EARNED'
        TASK_COST         = 'TASK_COST'
        FLAG_UP_SENT      = 'FLAG_UP_SENT'
        FLAG_UP_RECEIVED  = 'FLAG_UP_RECEIVED'
        STAFF_ADJUSTMENT  = 'STAFF_ADJUSTMENT'

    user              = models.ForeignKey(User, on_delete=models.CASCADE, related_name='karma_transactions')
    delta             = models.IntegerField()
    reason            = models.CharField(max_length=30, choices=Reason.choices)
    related_object_id = models.IntegerField(null=True, blank=True)
    created_at        = models.DateTimeField(auto_now_add=True)