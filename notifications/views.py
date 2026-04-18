# notifications/views.py
import json
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.views.decorators.http import require_POST
from django.utils import timezone

from notifications.models import Notification, NotificationPreference


def _notif_summary(notif):
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
    p = notif.payload or {}
    delta = p.get('delta')
    if isinstance(delta, (int, float)):
        return int(delta)
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
    Notification.objects.filter(user=request.user, read_at__isnull=True).update(read_at=timezone.now())

    return render(request, 'notifications/inbox.html', {
        'notifications': notifications,
        'summaries': {n.pk: _notif_summary(n) for n in notifications},
    })


@login_required
@require_POST
def save_preferences(request):
    """Save notification preferences for Pro users. Email + webhook per event,
    shared webhook URL and secret across all events."""
    if not request.user.is_pro:
        return JsonResponse({'ok': False, 'error': 'Pro required'}, status=403)

    webhook_url = request.POST.get('webhook_url', '').strip()
    webhook_secret = request.POST.get('webhook_secret', '').strip()

    for event, _ in Notification.Event.choices:
        email_enabled = request.POST.get(f'email_{event}') == '1'
        webhook_enabled = request.POST.get(f'webhook_{event}') == '1'
        defaults = {
            'email_enabled': email_enabled,
            'webhook_url': webhook_url if webhook_enabled else '',
        }
        # Store secret if model supports it
        if hasattr(NotificationPreference, 'webhook_secret'):
            defaults['webhook_secret'] = webhook_secret if webhook_enabled else ''
        # Store webhook_enabled flag if model has it
        if hasattr(NotificationPreference, 'webhook_enabled'):
            defaults['webhook_enabled'] = webhook_enabled

        NotificationPreference.objects.update_or_create(
            user=request.user,
            event=event,
            defaults=defaults,
        )

    return JsonResponse({'ok': True})