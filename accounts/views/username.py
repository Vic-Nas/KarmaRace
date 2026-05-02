"""Username selection after first social login."""
import re

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from accounts.models import UserPreference
from accounts.models import User


USERNAME_RE = re.compile(r'^[a-zA-Z0-9_]{3,30}$')
USERNAME_SET_KEY = 'username_set'


def username_needs_picking(user):
    """Return True if this user has not yet chosen a username."""
    return not UserPreference.objects.filter(
        user=user, key=USERNAME_SET_KEY
    ).exists()


@login_required
def pick_username(request):
    """Page where a new user picks their username."""
    if not username_needs_picking(request.user):
        return redirect('feed')

    error = None
    suggestion = _suggest(request.user)

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        error = _validate(username, request.user)
        if not error:
            request.user.username = username
            request.user.save(update_fields=['username'])
            UserPreference.objects.get_or_create(
                user=request.user, key=USERNAME_SET_KEY,
                defaults={'value': '1'},
            )
            return redirect('feed')

    return render(request, 'accounts/pick_username.html', {
        'suggestion': suggestion,
        'error': error,
    })


@require_GET
def username_check(request):
    """AJAX endpoint — returns {"available": true/false}."""
    username = request.GET.get('username', '').strip()
    if not USERNAME_RE.match(username):
        return JsonResponse({'available': False, 'reason': 'invalid'})
    taken = User.objects.filter(username__iexact=username).exclude(
        pk=request.user.pk if request.user.is_authenticated else None
    ).exists()
    return JsonResponse({'available': not taken})


def _validate(username, user):
    if not USERNAME_RE.match(username or ''):
        return 'Username must be 3–30 characters: letters, numbers, underscores only.'
    if User.objects.filter(username__iexact=username).exclude(pk=user.pk).exists():
        return 'That username is already taken.'
    return None


def _suggest(user):
    """Build a suggestion from the user's Google display name."""
    base = re.sub(r'[^a-zA-Z0-9_]', '', user.first_name or user.username or '')
    if len(base) < 3:
        base = re.sub(r'[^a-zA-Z0-9_]', '', user.email.split('@')[0])
    base = base[:25] or 'user'
    candidate = base
    suffix = 1
    while User.objects.filter(username__iexact=candidate).exclude(pk=user.pk).exists():
        candidate = f'{base}{suffix}'
        suffix += 1
    return candidate
