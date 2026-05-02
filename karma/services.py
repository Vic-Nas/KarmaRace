# karma/services.py
from django.db.models import Sum

from karma.models import KarmaTransaction
from setup.platform_rules import KARMA_LOW_THRESHOLD


def get_balance(user) -> int:
    result = KarmaTransaction.objects.filter(user=user).aggregate(balance=Sum('delta'))
    return result['balance'] or 0


def _karma_low_threshold(user) -> int:
    """
    Resolve the karma-low threshold for a user.
    Checks UserPreference first; falls back to static platform rules.
    """
    from accounts.models import UserPreference

    pref = UserPreference.objects.filter(user=user, key='karma_low_threshold').first()
    if pref is not None:
        return int(pref.value)
    return int(KARMA_LOW_THRESHOLD)


def credit_karma(user, delta: int, reason: str, related_object_id: int = None):
    balance = get_balance(user)
    credit = abs(delta)

    KarmaTransaction.objects.create(
        user=user,
        delta=credit,
        reason=reason,
        related_object_id=related_object_id,
    )

    try:
        threshold = _karma_low_threshold(user)
    except Exception:
        return

    _maybe_notify_karma_threshold_transition(
        user=user,
        new_balance=balance + credit,
        threshold=threshold,
    )


def debit_karma(user, delta: int, reason: str, related_object_id: int = None):
    """
    Debit karma from a user.

    - If balance >= delta: writes the transaction row.
    - If balance < delta: skips silently. No transaction written, no project
      state change. Owner is already ranked at the bottom due to low balance.
        - After a successful debit: fires threshold transition notification
            if balance moved into/out of the low-karma zone.
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
        return  # Invalid per-user threshold — skip notification rather than crash

    _maybe_notify_karma_threshold_transition(
        user=user,
        new_balance=new_balance,
        threshold=threshold,
    )


def _maybe_notify_karma_threshold_transition(user, new_balance: int, threshold: int):
    """
    Send KARMA_LOW / KARMA_RESTORED only on state transitions.

    This enforces alternation and avoids repeated consecutive notifications
    while balance stays in the same zone.
    """
    from notifications.models import Notification
    from notifications.services import notify

    if new_balance < threshold:
        target_event = Notification.Event.KARMA_LOW
    elif new_balance > threshold:
        target_event = Notification.Event.KARMA_RESTORED
    else:
        return

    last_event = (
        Notification.objects
        .filter(
            user=user,
            event__in=[Notification.Event.KARMA_LOW, Notification.Event.KARMA_RESTORED],
        )
        .order_by('-created_at')
        .values_list('event', flat=True)
        .first()
    )

    if last_event == target_event:
        return

    notify(
        user=user,
        event=target_event,
        payload={'balance': new_balance, 'threshold': threshold},
    )


def adjust_karma_by_staff(user, delta: int, reason: str = None):
    """
    Staff adjustment to user karma. Auto-detects credit/debit by sign.
    
    Args:
        user: Target user
        delta: Amount to adjust (positive = credit, negative = debit)
        reason: Optional staff-provided reason for the adjustment
    
    Returns:
        New balance
    """
    balance = get_balance(user)
    
    KarmaTransaction.objects.create(
        user=user,
        delta=delta,
        reason=KarmaTransaction.Reason.STAFF_ADJUSTMENT,
        related_object_id=None,
    )
    
    new_balance = balance + delta
    
    try:
        from notifications.models import Notification
        from notifications.services import notify
        notify(
            user=user,
            event=Notification.Event.KARMA_ADJUSTED,
            payload={
                'delta': delta,
                'new_balance': new_balance,
                'reason': reason or 'Staff adjustment',
            },
        )
        threshold = _karma_low_threshold(user)
        _maybe_notify_karma_threshold_transition(user=user, new_balance=new_balance, threshold=threshold)
    except Exception:
        pass

    return new_balance