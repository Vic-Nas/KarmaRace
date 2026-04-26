# feed/views.py
from django.conf import settings
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.urls import reverse
from django.utils.http import urlencode
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.db.models import Sum, Value, Q
from django.db.models.functions import Coalesce
from datetime import timedelta

from tasks.check_feedback import msg
from tasks.models import Task, TaskCompletion, ReciprocityObligation
from setup.platform_rules import WEBHOOK_FAILURE_RATE_EPSILON

SESSION_FEED_PIN_KEY = 'feed_pinned_task_id'
DEFAULT_COMPLETION   = 'not_completed'
DEFAULT_ARCHIVE      = 'not_archived'
PREF_FEED_COMPLETION  = 'feed_filter_completion'
PREF_FEED_ARCHIVE     = 'feed_filter_archive'
PREF_FEED_TASK_TYPES  = 'feed_filter_task_types'

ALL_TASK_TYPES = [Task.Type.GITHUB_STAR, Task.Type.GITHUB_FORK, Task.Type.WEBHOOK]
TASK_TYPE_LABELS = {
    Task.Type.GITHUB_STAR: 'GitHub Star',
    Task.Type.GITHUB_FORK: 'GitHub Fork',
    Task.Type.WEBHOOK:     'Webhook',
}


def _normalize_task_types(values):
    valid, normalized, seen = set(ALL_TASK_TYPES), [], set()
    for raw in values or []:
        for item in str(raw or '').split(','):
            t = item.strip()
            if t and t in valid and t not in seen:
                seen.add(t)
                normalized.append(t)
    return normalized or list(ALL_TASK_TYPES)


def _load_filter_preferences(user):
    if not user.is_authenticated:
        return DEFAULT_COMPLETION, DEFAULT_ARCHIVE, list(ALL_TASK_TYPES)
    from accounts.models import UserPreference
    prefs = dict(
        UserPreference.objects.filter(
            user=user, key__in=[PREF_FEED_COMPLETION, PREF_FEED_ARCHIVE, PREF_FEED_TASK_TYPES],
        ).values_list('key', 'value')
    )
    return (
        prefs.get(PREF_FEED_COMPLETION) or DEFAULT_COMPLETION,
        prefs.get(PREF_FEED_ARCHIVE) or DEFAULT_ARCHIVE,
        _normalize_task_types((prefs.get(PREF_FEED_TASK_TYPES) or '').split(',')),
    )


def _save_filter_preferences(user, completion, archive, task_types):
    if not user.is_authenticated:
        return
    from accounts.models import UserPreference
    for key, value in {
        PREF_FEED_COMPLETION: completion,
        PREF_FEED_ARCHIVE:    archive,
        PREF_FEED_TASK_TYPES: ','.join(_normalize_task_types(task_types)),
    }.items():
        UserPreference.objects.update_or_create(user=user, key=key, defaults={'value': value})


def _open_obligations(user):
    """Return open obligations ordered oldest first — clears debts in the order they were created."""
    if not user.is_authenticated:
        return []
    return list(
        ReciprocityObligation.objects.filter(
            debtor=user, state=ReciprocityObligation.State.OPEN,
        ).order_by('created_at').select_related('creditor')
    )


def _active_lock_obligations(user, obligations):
    if not obligations:
        return []
    candidate = _get_feed_task(user, completion='not_completed', archive='not_archived', obligations=obligations)
    return obligations if candidate else []


def _feed_queryset(user, completion='not_completed', archive='not_archived', task_types=None, obligations=None):
    """
    Rank: owner karma desc → task priority desc → newest first.
    Priority is owner-set drag order on My Tasks page.
    """
    task_types = _normalize_task_types(task_types)
    qs = Task.objects.filter(is_deleted=False, hidden=False).select_related('owner')

    if user.is_authenticated:
        qs = qs.exclude(owner=user)
        if obligations:
            allowed = Q(pk__in=[])
            for ob in obligations:
                allowed |= Q(owner_id=ob.creditor_id, type=ob.task_type)
            qs = (qs.filter(allowed)
                    .exclude(archived_by=user)
                    .exclude(completions__tester=user, completions__state=TaskCompletion.State.CONFIRMED))
        else:
            if archive == 'not_archived':
                qs = qs.exclude(archived_by=user)
            elif archive == 'archived':
                qs = qs.filter(archived_by=user)
            if completion == 'not_completed':
                qs = qs.exclude(completions__tester=user, completions__state=TaskCompletion.State.CONFIRMED)
            elif completion == 'completed':
                qs = qs.filter(completions__tester=user, completions__state=TaskCompletion.State.CONFIRMED)
            qs = qs.filter(type__in=task_types)
    else:
        qs = qs.filter(type__in=task_types)

    return qs.annotate(
        owner_balance=Coalesce(Sum('owner__karma_transactions__delta'), Value(0)),
    ).order_by('-owner_balance', '-priority', '-created_at')


def _get_feed_task(user, completion='not_completed', archive='not_archived', task_types=None, obligations=None):
    return _feed_queryset(user, completion=completion, archive=archive,
                          task_types=task_types, obligations=obligations).first()


def _get_pinned_task(request, archive='not_archived', task_types=None, obligations=None):
    task_types = _normalize_task_types(task_types)
    if not request.user.is_authenticated or obligations or archive != 'not_archived':
        return None
    pinned_id = request.session.get(SESSION_FEED_PIN_KEY)
    if not pinned_id:
        return None
    task = Task.objects.filter(pk=pinned_id, is_deleted=False, hidden=False).select_related('owner').first()
    if not task or task.owner_id == request.user.id:
        request.session.pop(SESSION_FEED_PIN_KEY, None)
        return None
    if task.archived_by.filter(pk=request.user.pk).exists() or task.type not in task_types:
        request.session.pop(SESSION_FEED_PIN_KEY, None)
        return None
    return task


def _webhook_stats(task):
    if task.type != Task.Type.WEBHOOK:
        return None
    cqs = TaskCompletion.objects.filter(task=task)
    tried_failed = cqs.filter(state=TaskCompletion.State.FAILED).count()
    completed    = cqs.filter(state=TaskCompletion.State.CONFIRMED).count()
    not_tried    = (task.archived_by.exclude(task_completions__task=task)
                    .exclude(id=task.owner_id).distinct().count())
    denom = completed + tried_failed + not_tried + WEBHOOK_FAILURE_RATE_EPSILON
    return {
        'tried_failed': tried_failed, 'completed': completed, 'not_tried': not_tried,
        'failure_rate_percent': int(round(tried_failed / denom * 100)),
    }


def feed(request):
    check_result = (request.GET.get('check_result') or '').strip().upper()
    check_detail = (request.GET.get('check_detail') or '').strip()
    if check_result == TaskCompletion.State.CONFIRMED:
        messages.success(request, msg('CHECK_CONFIRMED'))
    elif check_result == TaskCompletion.State.FAILED:
        messages.error(request, check_detail or msg('CHECK_FAILED_GENERIC'))

    has_overrides = any(k in request.GET for k in ('completion', 'archive', 'task_types'))
    if has_overrides:
        completion         = request.GET.get('completion') or DEFAULT_COMPLETION
        archive            = request.GET.get('archive') or DEFAULT_ARCHIVE
        selected_types     = _normalize_task_types(request.GET.getlist('task_types'))
    else:
        completion, archive, selected_types = _load_filter_preferences(request.user)

    checking_task_id = request.GET.get('checking_task') or ''

    if has_overrides:
        _save_filter_preferences(request.user, completion, archive, selected_types)
        base = reverse('feed')
        if checking_task_id:
            return redirect(f'{base}?{urlencode({"checking_task": checking_task_id})}')
        return redirect(base)

    obligations = _active_lock_obligations(request.user, _open_obligations(request.user))

    task = _get_pinned_task(request, archive=archive, task_types=selected_types, obligations=obligations)
    if task is None:
        task = _get_feed_task(request.user, completion=completion, archive=archive,
                              task_types=selected_types, obligations=obligations)
        if request.user.is_authenticated and not obligations and archive == 'not_archived':
            request.session[SESSION_FEED_PIN_KEY] = task.id if task else None
            if not task:
                request.session.pop(SESSION_FEED_PIN_KEY, None)

    completed_task_ids = set()
    if task and request.user.is_authenticated:
        completed_task_ids = set(
            TaskCompletion.objects.filter(
                tester=request.user, task=task, state=TaskCompletion.State.CONFIRMED,
            ).values_list('task_id', flat=True)
        )

    verified_emails = []
    if request.user.is_authenticated and task and task.type == Task.Type.WEBHOOK:
        verified_emails = list(request.user.verified_emails.values_list('email', flat=True).order_by('verified_at'))

    is_checking = False
    if task and request.user.is_authenticated and checking_task_id:
        try:
            cid = int(checking_task_id)
        except ValueError:
            cid = 0
        if cid == task.id:
            is_checking = TaskCompletion.objects.filter(
                task=task, tester=request.user, state=TaskCompletion.State.PENDING,
            ).exists()

    # Which obligation does the current task satisfy?
    obligation_creditor = None
    if obligations and task:
        for ob in obligations:
            if ob.creditor_id == task.owner_id and ob.task_type == task.type:
                obligation_creditor = ob.creditor.username
                break

    return render(request, 'feed/index.html', {
        'task':                  task,
        'task_reward':           task.karma_reward if task else '?',
        'completed_task_ids':    completed_task_ids,
        'feed_empty':            task is None,
        'completion':            completion,
        'archive':               archive,
        'selected_task_types':   selected_types,
        'selected_task_types_csv': ','.join(selected_types),
        'all_task_types': [
            {'value': t, 'label': TASK_TYPE_LABELS.get(t, t.replace('_', ' ').title())}
            for t in ALL_TASK_TYPES
        ],
        'obligation_mode':       bool(obligations),
        'open_obligations_count': len(obligations),
        'obligation_creditor':   obligation_creditor,
        'webhook_stats':         _webhook_stats(task) if task else None,
        'checking_task_id':      task.id if is_checking else '',
        'verified_emails':       verified_emails,
    })


def _redirect_to_feed_with_filters(request, extra_params=None):
    completion    = (request.POST.get('completion') or DEFAULT_COMPLETION).strip() or DEFAULT_COMPLETION
    archive       = (request.POST.get('archive') or DEFAULT_ARCHIVE).strip() or DEFAULT_ARCHIVE
    selected_types = _normalize_task_types(request.POST.getlist('task_types'))
    _save_filter_preferences(request.user, completion, archive, selected_types)
    params = {k: v for k, v in (extra_params or {}).items() if v not in (None, '', [])}
    url = reverse('feed')
    return redirect(f'{url}?{urlencode(params, doseq=True)}') if params else redirect(url)


def _precheck_linked_account(user, task):
    if task.type in (Task.Type.GITHUB_STAR, Task.Type.GITHUB_FORK):
        if not user.linked_accounts.filter(platform='github').exists():
            return msg('GITHUB_LINK_REQUIRED')
    return None


@require_POST
def done(request, task_id):
    if not request.user.is_authenticated:
        return redirect('account_login')
    obligations = _active_lock_obligations(request.user, _open_obligations(request.user))
    if obligations:
        messages.error(request, msg('ARCHIVE_DISABLED_OBLIGATIONS'))
        return _redirect_to_feed_with_filters(request)
    task = get_object_or_404(Task, pk=task_id, is_deleted=False, hidden=False)
    if task.owner_id != request.user.id:
        task.archived_by.add(request.user)
        if request.session.get(SESSION_FEED_PIN_KEY) == task.id:
            request.session.pop(SESSION_FEED_PIN_KEY, None)
    return _redirect_to_feed_with_filters(request)


@require_POST
def check(request, task_id):
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    def respond(state, detail='', extra_params=None):
        if is_ajax:
            payload = {'state': state}
            if detail:      payload['detail'] = detail
            if extra_params: payload.update(extra_params)
            return JsonResponse(payload)
        if state == TaskCompletion.State.CONFIRMED:
            messages.success(request, detail or msg('CHECK_CONFIRMED'))
            return _redirect_to_feed_with_filters(request)
        if state == TaskCompletion.State.FAILED:
            messages.error(request, detail or msg('CHECK_FAILED_GENERIC'))
            return _redirect_to_feed_with_filters(request)
        if state == TaskCompletion.State.PENDING:
            messages.info(request, detail or msg('CHECK_STARTED'))
            return _redirect_to_feed_with_filters(request, extra_params={'checking_task': str(task.pk)})
        return _redirect_to_feed_with_filters(request)

    if not request.user.is_authenticated:
        if is_ajax:
            return JsonResponse({'state': 'UNAUTHENTICATED', 'detail': 'Sign in required.'}, status=401)
        return redirect('account_login')

    from feed.tasks import process_task_check
    task = get_object_or_404(Task, pk=task_id, is_deleted=False, hidden=False)
    if task.owner_id == request.user.id:
        return respond(TaskCompletion.State.FAILED, 'You cannot check your own task.')

    precheck_error = _precheck_linked_account(request.user, task)
    if precheck_error:
        return respond(TaskCompletion.State.FAILED, precheck_error)

    google_email = ''
    if task.type == Task.Type.WEBHOOK:
        google_email = (request.POST.get('google_email') or '').strip()
        if not google_email:
            return respond(TaskCompletion.State.FAILED, 'Select a verified email before checking a webhook task.')

    completion, created = TaskCompletion.objects.get_or_create(
        task=task, tester=request.user, defaults={'state': TaskCompletion.State.PENDING},
    )

    if completion.state == TaskCompletion.State.CONFIRMED:
        from karma.services import get_balance
        return respond(TaskCompletion.State.CONFIRMED, msg('ALREADY_CONFIRMED'),
                       extra_params={'karma_delta': 0, 'karma_balance': get_balance(request.user)})

    if completion.state == TaskCompletion.State.PENDING and not created:
        if completion.created_at <= timezone.now() - timedelta(seconds=45):
            completion.state = TaskCompletion.State.FAILED
            completion.save(update_fields=['state'])
        else:
            return respond(TaskCompletion.State.PENDING, msg('CHECK_IN_PROGRESS'))

    if not created:
        completion.state         = TaskCompletion.State.PENDING
        completion.result_detail = ''
        completion.created_at    = timezone.now()
        completion.save(update_fields=['state', 'result_detail', 'created_at'])

    try:
        process_task_check.defer(task_id=task.pk, tester_id=request.user.pk, google_email=google_email)
    except Exception:
        try:
            process_task_check(task_id=task.pk, tester_id=request.user.pk, google_email=google_email)
            completion.refresh_from_db(fields=['state', 'result_detail'])
            if completion.state == TaskCompletion.State.CONFIRMED:
                from karma.services import get_balance
                return respond(TaskCompletion.State.CONFIRMED, msg('QUEUE_UNAVAILABLE_CONFIRMED'),
                               extra_params={'karma_delta': task.karma_reward, 'karma_balance': get_balance(request.user)})
            return respond(TaskCompletion.State.FAILED, completion.result_detail or msg('QUEUE_UNAVAILABLE_FAILED'))
        except Exception:
            completion.state         = TaskCompletion.State.FAILED
            completion.result_detail = msg('QUEUE_FAILED')
            completion.save(update_fields=['state', 'result_detail'])
            return respond(TaskCompletion.State.FAILED, msg('QUEUE_FAILED'))

    return respond(TaskCompletion.State.PENDING, msg('CHECK_STARTED'))


def check_status(request, task_id):
    if not request.user.is_authenticated:
        return JsonResponse({'state': 'UNAUTHENTICATED'}, status=401)
    completion = TaskCompletion.objects.filter(task_id=task_id, tester=request.user).first()
    if completion is None:
        return JsonResponse({'state': 'NOT_STARTED'})
    if (completion.state == TaskCompletion.State.PENDING
            and completion.created_at <= timezone.now() - timedelta(seconds=45)):
        completion.state         = TaskCompletion.State.FAILED
        completion.result_detail = msg('CHECK_TIMEOUT_WORKER_HINT') if settings.DEBUG else msg('CHECK_TIMEOUT')
        completion.save(update_fields=['state', 'result_detail'])
        return JsonResponse({'state': TaskCompletion.State.FAILED, 'detail': completion.result_detail})
    if completion.state == TaskCompletion.State.FAILED:
        return JsonResponse({'state': completion.state,
                             'detail': completion.result_detail or msg('CHECK_FAILED_GENERIC')})
    if completion.state == TaskCompletion.State.CONFIRMED:
        from karma.services import get_balance
        task = Task.objects.filter(pk=task_id).first()
        return JsonResponse({'state': completion.state, 'detail': msg('CHECK_CONFIRMED'),
                             'karma_delta': task.karma_reward if task else 0,
                             'karma_balance': get_balance(request.user)})
    return JsonResponse({'state': completion.state})
