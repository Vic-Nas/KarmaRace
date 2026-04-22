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
    if event == Notification.Event.WEBHOOK_CHECK:
        return f"Webhook {p.get('phase', 'check')} for Task #{p.get('task_id', '?')} => {p.get('status', 'unknown')}"
    if event == Notification.Event.KARMA_LOW:
        return 'Your karma balance is low.'
    if event == Notification.Event.KARMA_RESTORED:
        return 'Your karma balance is restored.'
    if event == Notification.Event.APPRECIATION:
        return p.get('message', 'You received appreciation.')
    return str(p)[:80]


def _karma_delta(notif):
    delta = (notif.payload or {}).get('delta')
    return int(delta) if isinstance(delta, (int, float)) else 0


def _serialize(notif):
    return {
        'id': notif.pk,
        'event': notif.event,
        'summary': _notif_summary(notif),
        'karma_delta': _karma_delta(notif),
        'read_at': notif.read_at.isoformat() if notif.read_at else None,
        'created_at': notif.created_at.isoformat(),
    }


def _pretty_payload(payload):
    if not payload:
        return '{}'
    try:
        return json.dumps(payload, indent=2, sort_keys=True)
    except (TypeError, ValueError):
        return str(payload)


def _safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@login_required
def unread_poll(request):
    since_id = _safe_int(request.GET.get('since', 0)) or 0
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
    qs = Notification.objects.filter(user=request.user)

    selected_event = (request.GET.get('event') or '').strip()
    selected_task_id = _safe_int(request.GET.get('task_id'))
    query = (request.GET.get('q') or '').strip().lower()

    if selected_event:
        qs = qs.filter(event=selected_event)
    if selected_task_id:
        qs = qs.filter(payload__task_id=selected_task_id)

    notifications = list(qs.order_by('-created_at')[:200])

    if query:
        notifications = [
            n for n in notifications
            if (
                query in _notif_summary(n).lower()
                or query in (n.event or '').lower()
                or query in _pretty_payload(n.payload).lower()
            )
        ]

    Notification.objects.filter(user=request.user, read_at__isnull=True).update(read_at=timezone.now())

    all_recent = Notification.objects.filter(user=request.user).order_by('-created_at')[:300]
    task_ids = sorted({
        p.get('task_id') for p in [n.payload or {} for n in all_recent]
        if isinstance(p.get('task_id'), int)
    })

    return render(request, 'notifications/inbox.html', {
        'notifications': notifications,
        'summaries': {n.pk: _notif_summary(n) for n in notifications},
        'payload_pretty': {n.pk: _pretty_payload(n.payload) for n in notifications},
        'events': Notification.Event.choices,
        'selected_event': selected_event,
        'selected_task_id': selected_task_id,
        'task_ids': task_ids,
        'search_query': request.GET.get('q', ''),
    })


@login_required
@require_POST
def save_preferences(request):
    """Save notification delivery preferences for Pro users."""
    if not request.user.is_pro:
        return JsonResponse({'ok': False, 'error': 'Pro required'}, status=403)

    webhook_url    = (request.POST.get('webhook_url', '') or '').strip()
    webhook_secret = (request.POST.get('webhook_secret', '') or '').strip()

    for event, _ in Notification.Event.choices:
        email_enabled   = request.POST.get(f'email_{event}') == '1'
        webhook_enabled = request.POST.get(f'webhook_{event}') == '1'
        discord_enabled = request.POST.get(f'discord_{event}') == '1'

        defaults = {
            'email_enabled':   email_enabled,
            'webhook_url':     webhook_url if webhook_enabled else '',
            'discord_enabled': discord_enabled,
        }
        if hasattr(NotificationPreference, 'webhook_secret'):
            defaults['webhook_secret'] = webhook_secret if webhook_enabled else ''

        NotificationPreference.objects.update_or_create(
            user=request.user, event=event, defaults=defaults,
        )

    return JsonResponse({'ok': True})
