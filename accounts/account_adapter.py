# accounts/account_adapter.py
from allauth.account.adapter import DefaultAccountAdapter
from django.urls import reverse


class AccountAdapter(DefaultAccountAdapter):
    def get_login_redirect_url(self, request):
        from tasks.models import Task
        if request.user.is_authenticated and not Task.objects.filter(owner=request.user).exists():
            return reverse('onboarding')
        return super().get_login_redirect_url(request)