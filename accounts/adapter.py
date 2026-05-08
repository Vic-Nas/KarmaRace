# accounts/adapter.py
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.core.exceptions import ImmediateHttpResponse
from django.shortcuts import render
from django.urls import reverse

from accounts.models import VerifiedEmail


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    def pre_social_login(self, request, sociallogin):
        email = (sociallogin.account.extra_data.get('email') or '').strip().lower()
        if not email:
            return
        existing = VerifiedEmail.objects.filter(email=email).first()
        if existing and existing.user_id != (sociallogin.user.pk if sociallogin.user.pk else None):
            raise ImmediateHttpResponse(
                render(request, 'accounts/email_claimed.html', {'email': email})
            )

    def get_login_redirect_url(self, request):
        from tasks.models import Task
        user = request.user
        if user.is_authenticated and not Task.objects.filter(owner=user).exists():
            return reverse('onboarding')
        return super().get_login_redirect_url(request)