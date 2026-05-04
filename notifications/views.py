# notifications/views.py
import json

import django_filters
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST

from notifications.models import Notification, NotificationPreference


class NotificationFilter(django_filters.FilterSet):
    task_id = django_filters.NumberFilter(field_name='payload__task_id')

    class Meta:
        model = Notification
        fields = ['event', 'task_id']


SUMMARY_TEMPLATES = {
    Notification.Event.TASK_CONFIRMED: "Task #{task_id} confirmed.",
    Notification.Event.TASK_HEALTH_FAILED: "Task #{task_id} failed health check.",
    Notification.Event.WEBHOOK_CHECK: "Webhook {phase} for Task #{task_id} => {status}",
    Notification.Event.KARMA_LOW: "Your karma balance is low.",
    Notification.Event.KARMA_RESTORED: "Your karma balance is restored.",
    Notification.Event.PROJECT_STATE: "Project #{task_id} status changed to {status}.",
    Notification.Event.APPRECIATION: "You received appreciation.",
    Notification.Event.FLAG_UP_RECEIVED: "You received a flag-up from {from_username}.",
    Notification.Event.FLAG_UP_SENT: "You sent a flag-up to {to_username}.",
    Notification.Event.NEW_USER: "New user signed up: {username} (total: {total_users})",
}


def _notif_summary(notif):
    p = notif.payload or {}
    event = notif.event

    if event == Notification.Event.KARMA_ADJUSTED:
        delta = p.get('delta', 0)
        sign = '+' if delta >= 0 else ''
        reason = p.get('reason', 'Staff adjustment')
        new_bal = p.get('new_balance')
        bal_str = f' \u2192 {new_bal}' if new_bal is not None else ''
        return f'{sign}{delta} karma{bal_str} \u2014 {reason}'

    template = SUMMARY_TEMPLATES.get(event)
    if template:
        return template.format(
            task_id=p.get('task_id', '?'),
            phase=p.get('phase', 'check'),
            status=p.get('status', 'unknown'),
            username=p.get('username', '?'),
            total_users=p.get('total_users', '?'),
            from_username=p.get('from_username', '?'),
            to_username=p.get('to_username', '?'),
        )
    return str(p)[:80]


def _serialize(notif):
    payload = notif.payload or {}
    delta = payload.get('delta')
    karma_delta = int(delta) if isinstance(delta, (int, float)) else 0
    return {
        'id': notif.pk,
        'event': notif.event,
        'summary': _notif_summary(notif),
        'karma_delta': karma_delta,
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


def _poll_notifications(qs, order_by, limit, unread_count=None):
    notifications = list(qs.order_by(order_by)[:limit])
    payload = {'notifications': [_serialize(n) for n in notifications]}
    if unread_count is not None:
        payload['unread_count'] = unread_count
    return JsonResponse(payload)


@login_required
def unread_poll(request):
    try:
        since_id = int(request.GET.get('since', 0))
    except (TypeError, ValueError):
        since_id = 0
    base_qs = Notification.objects.filter(user=request.user, read_at__isnull=True)
    qs = base_qs
    if since_id:
        qs = qs.filter(pk__gt=since_id)
    return _poll_notifications(qs, 'pk', 20, unread_count=base_qs.count())


@login_required
def recent_poll(request):
    qs = Notification.objects.filter(user=request.user)
    return _poll_notifications(qs, '-created_at', 10)


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

    filterset = NotificationFilter(request.GET, queryset=qs)
    qs = filterset.qs

    selected_event = (filterset.form.cleaned_data.get('event') or '').strip() if filterset.is_valid() else ''
    selected_task_id = filterset.form.cleaned_data.get('task_id') if filterset.is_valid() else None
    query = (request.GET.get('q') or '').strip().lower()

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

    task_ids = sorted({
        tid for tid in Notification.objects.filter(user=request.user, payload__task_id__isnull=False)
        .order_by('-created_at')[:300].values_list('payload__task_id', flat=True)
        if isinstance(tid, int)
    })

    return render(request, 'notifications/inbox.html', {
        'notifications': notifications,
        'summaries': {n.pk: _notif_summary(n) for n in notifications},
        'payload_pretty': {n.pk: _pretty_payload(n.payload) for n in notifications},
        'events': Notification.USER_CONFIGURABLE_EVENTS,
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
    webhook_enabled = bool(webhook_url)

    for event, _ in Notification.USER_CONFIGURABLE_EVENTS:
        discord_enabled = request.POST.get(f'discord_{event}') == '1'

        defaults = {
            'webhook_url':     webhook_url if webhook_enabled else '',
            'discord_enabled': discord_enabled,
        }
        if hasattr(NotificationPreference, 'webhook_secret'):
            defaults['webhook_secret'] = webhook_secret if webhook_enabled else ''

        NotificationPreference.objects.update_or_create(
            user=request.user, event=event, defaults=defaults,
        )

    return JsonResponse({'ok': True})