from django.shortcuts import render, redirect


def account_login_redirect(request):
    return redirect('/accounts/google/login/?process=login')


def help_index(request):
    return render(request, 'help/index.html')


def legal_privacy(request):
    return render(request, 'legal/privacy.html')


def legal_terms(request):
    return render(request, 'legal/terms.html')


def public_profile_redirect(request, username):
    """Delegate to accounts.views to keep URL routing clean."""
    from accounts.views import public_profile
    return public_profile(request, username)
