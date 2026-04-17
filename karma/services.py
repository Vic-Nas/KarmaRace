# karma/services.py
from django.db.models import Sum

from karma.models import KarmaTransaction


def get_balance(user) -> int:
    result = KarmaTransaction.objects.filter(user=user).aggregate(balance=Sum('delta'))
    return result['balance'] or 0


def _karma_low_threshold(user) -> int:
    """
    Resolve the karma-low threshold for a user.
    Checks UserPreference first; falls back to PlatformConfig.
    """
    from accounts.models import UserPreference, PlatformConfig

    pref = UserPreference.objects.filter(user=user, key='karma_low_threshold').first()
    if pref is not None:
        return int(pref.value)
    return int(PlatformConfig.objects.get(key='karma_low_threshold').value)


def credit_karma(user, delta: int, reason: str, related_object_id: int = None):
    KarmaTransaction.objects.create(
        user=user,
        delta=abs(delta),
        reason=reason,
        related_object_id=related_object_id,
    )


def debit_karma(user, delta: int, reason: str, related_object_id: int = None):
    """
    Debit karma from a user.

    - If balance >= delta: writes the transaction row.
    - If balance < delta: skips silently. No transaction written, no project
      state change. Owner is already ranked at the bottom due to low balance.
    - After a successful debit: fires KARMA_LOW notification if the new
      balance has dropped below the user's resolved threshold.
    """
    balance = get_balance(user)
    if balance < delta:
        return

    KarmaTransaction.objects.create(
        user=user,
        delta=-delta,
        reason=reason,
        related_object_id=related_object_id,
    )

    new_balance = balance - delta
    try:
        threshold = _karma_low_threshold(user)
    except Exception:
        return  # PlatformConfig missing — skip notification rather than crash

    if new_balance < threshold:
        from notifications.services import fire_notification
        from notifications.models import Notification

        fire_notification(
            user=user,
            event=Notification.Event.KARMA_LOW,
            payload={'balance': new_balance, 'threshold': threshold},
        )