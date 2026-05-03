# accounts/context_processors.py
from karma.services import get_balance


def navbar_karma(request):
    if not request.user.is_authenticated:
        return {'navbar_karma': None}

    try:
        return {'navbar_karma': get_balance(request.user)}
    except Exception:
        return {'navbar_karma': 0}
