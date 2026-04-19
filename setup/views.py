from urllib.parse import urlencode

from django.shortcuts import redirect, render
from django.urls import reverse


def legal_privacy(request):
    return render(request, 'legal/privacy.html')


def legal_terms(request):
    return render(request, 'legal/terms.html')


def help_index(request):
    return render(request, 'help/index.html')


def account_login_redirect(request):
    next_url = (request.GET.get('next') or '').strip() or '/'
    params = urlencode({'process': 'login', 'next': next_url})
    return redirect(f"{reverse('google_login')}?{params}")
