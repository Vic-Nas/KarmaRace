# notifications/views.py
import json
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.views.decorators.http import require_POST
from django.utils import timezone

from accounts.models import UserPreference
from notifications.models import Notification, NotificationPreference


def _notif_summary(notif):
    """Return a short human-readable summary from notification payload."""
    p = notif.payload or {}
    event = notif.event
    if event == Notification.Event.TASK_CONFIRMED:
        return f"Task #{p.get('task_id', '?')} confirmed."
    if event == Notification.Event.TASK_HEALTH_FAILED:
        return f"Task #{p.get('task_id', '?')} failed health check."
    if event == Notification.Event.KARMA_LOW:
        return "Your karma balance is low."
    if event == Notification.Event.KARMA_RESTORED:
        return "Your karma balance is restored."
    if event == Notification.Event.APPRECIATION:
        return p.get('message', 'You received appreciation.')
    return str(p)[:80]


def _karma_delta(notif):
    """Return signed karma delta if event carries one, else 0."""
    p = notif.payload or {}
    if notif.event == Notification.Event.TASK_CONFIRMED:
        return p.get('delta', 5)
    if notif.event == Notification.Event.KARMA_LOW:
        return p.get('delta', -1)
    if notif.event == Notification.Event.KARMA_RESTORED:
        return p.get('delta', 1)
    return 0


def _serialize(notif):
    return {
        'id': notif.pk,
        'event': notif.event,
        'summary': _notif_summary(notif),
        'karma_delta': _karma_delta(notif),
        'read_at': notif.read_at.isoformat() if notif.read_at else None,
        'created_at': notif.created_at.isoformat(),
    }


@login_required
def unread_poll(request):
    """Polled by JS every 5s. Returns new unread notifications since last seen id."""
    since_id = request.GET.get('since', 0)
    try:
        since_id = int(since_id)
    except (TypeError, ValueError):
        since_id = 0

    qs = Notification.objects.filter(user=request.user, read_at__isnull=True)
    if since_id:
        qs = qs.filter(pk__gt=since_id)

    notifications = list(qs.order_by('pk')[:20])
    return JsonResponse({
        'unread_count': Notification.objects.filter(user=request.user, read_at__isnull=True).count(),
        'notifications': [_serialize(n) for n in notifications],
    })


@login_required
def recent_poll(request):
    """Returns last 10 notifications for dropdown display."""
    qs = Notification.objects.filter(user=request.user).order_by('-created_at')[:10]
    return JsonResponse({'notifications': [_serialize(n) for n in qs]})


@login_required
@require_POST
def mark_read(request, notif_id):
    notif = get_object_or_404(Notification, pk=notif_id, user=request.user)
    if not notif.read_at:
        notif.read_at = timezone.now()
        notif.save(update_fields=['read_at'])
    return JsonResponse({'ok': True})


@login_required
@require_POST
def mark_all_read(request):
    Notification.objects.filter(user=request.user, read_at__isnull=True).update(read_at=timezone.now())
    return JsonResponse({'ok': True})


@login_required
def inbox(request):
    notifications = Notification.objects.filter(user=request.user).order_by('-created_at')[:50]
    # Mark all read on inbox visit
    Notification.objects.filter(user=request.user, read_at__isnull=True).update(read_at=timezone.now())

    # Notification preferences (Pro only)
    prefs = {}
    if request.user.is_pro:
        for pref in NotificationPreference.objects.filter(user=request.user):
            prefs[pref.event] = pref

    # UserPreference-driven: check if user has opted out of in-app notifications
    try:
        muted = UserPreference.objects.get(user=request.user, key='notifications_muted').value == 'true'
    except UserPreference.DoesNotExist:
        muted = False

    return render(request, 'notifications/inbox.html', {
        'notifications': notifications,
        'prefs': prefs,
        'muted': muted,
        'all_events': Notification.Event.choices,
        'summaries': {n.pk: _notif_summary(n) for n in notifications},
    })


@login_required
@require_POST
def save_preferences(request):
    """Save notification preferences. Stores email/webhook per event for Pro users.
    Also stores mute preference via UserPreference."""
    muted = request.POST.get('muted') == '1'
    UserPreference.objects.update_or_create(
        user=request.user,
        key='notifications_muted',
        defaults={'value': 'true' if muted else 'false'},
    )

    if request.user.is_pro:
        for event, _ in Notification.Event.choices:
            email_enabled = request.POST.get(f'email_{event}') == '1'
            webhook_url = request.POST.get(f'webhook_{event}', '').strip()
            NotificationPreference.objects.update_or_create(
                user=request.user,
                event=event,
                defaults={'email_enabled': email_enabled, 'webhook_url': webhook_url},
            )

    return JsonResponse({'ok': True})
