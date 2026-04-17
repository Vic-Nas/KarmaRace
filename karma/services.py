# karma/services.py
from django.db.models import Sum
from django.utils import timezone

from karma.models import KarmaTransaction
from projects.models import Project


def get_balance(user) -> int:
    result = KarmaTransaction.objects.filter(user=user).aggregate(balance=Sum('delta'))
    return result['balance'] or 0


def credit_karma(user, delta: int, reason: str, related_object_id: int = None):
    KarmaTransaction.objects.create(
        user=user,
        delta=abs(delta),
        reason=reason,
        related_object_id=related_object_id,
    )


def debit_karma(user, delta: int, reason: str, related_object_id: int = None) -> bool:
    from projects.services import has_testable_projects

    balance = get_balance(user)
    if balance < delta:
        # Grace: skip debit if the feed is exhausted — user cannot earn karma
        if not has_testable_projects(user):
            return True

        # Debit to zero, deactivate affected project
        if balance > 0:
            KarmaTransaction.objects.create(
                user=user,
                delta=-balance,
                reason=reason,
                related_object_id=related_object_id,
            )
        Project.objects.filter(owner=user, state=Project.State.ACTIVE).update(
            state=Project.State.INACTIVE,
            went_inactive_at=timezone.now(),
        )
        return False

    KarmaTransaction.objects.create(
        user=user,
        delta=-delta,
        reason=reason,
        related_object_id=related_object_id,
    )
    return True