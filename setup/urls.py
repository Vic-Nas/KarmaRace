# setup/urls.py
from django.contrib import admin
from django.urls import path, include
from . import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/login/', views.account_login_redirect, name='account_login_redirect'),
    path('accounts/', include('allauth.urls')),
    path('app/accounts/', include('accounts.urls')),
    path('u/<str:username>/', views.public_profile_redirect, name='public_profile'),
    path('billing/', include('billing.urls')),
    path('billing/', include('djstripe.urls', namespace='djstripe')),
    path('help/', views.help_index, name='help_index'),
    path('legal/privacy/', views.legal_privacy, name='legal_privacy'),
    path('legal/terms/', views.legal_terms, name='legal_terms'),
    path('', include('feed.urls')),
    path('tasks/', include('tasks.urls')),
    path('', include('notifications.urls')),
    path('', include('karma.urls')),
]

# Error handlers (when DEBUG=False)
handler404 = views.handler404
handler403 = views.handler403
handler500 = views.handler500

