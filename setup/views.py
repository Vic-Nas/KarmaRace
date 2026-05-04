# setup/views.py
from django.http import HttpResponse
from django.shortcuts import render, redirect


def account_login_redirect(request):
    return redirect('/accounts/google/login/?process=login')


def robots_txt(request):
    lines = [
        "User-agent: *",
        # Keep bots out of auth, admin, and private app areas
        "Disallow: /admin/",
        "Disallow: /accounts/",
        "Disallow: /app/accounts/",
        "Disallow: /billing/",
        "Disallow: /notifications/",
        # Feed interaction endpoints — not useful to index
        "Disallow: /check/",
        "Disallow: /check-status/",
        "Disallow: /done/",
        # Task management (private) — but public task slugs are fine
        "Disallow: /tasks/mine/",
        "Disallow: /tasks/new/",
        "Disallow: /tasks/reorder/",
        "Disallow: /tasks/slug-available/",
        "",
        "Sitemap: https://karmarace.io/sitemap.xml",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")


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


# Error handlers
def handler404(request, exception=None):
    """Handle 404 — page not found."""
    return render(request, '404.html', status=404)


def handler403(request, exception=None):
    """Handle 403 — access denied."""
    return render(request, '403.html', status=403)


def handler500(request):
    """Handle 500 — server error."""
    return render(request, '500.html', status=500)
