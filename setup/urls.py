from django.contrib import admin
from django.urls import path, include
from . import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('allauth.urls')),
    path('app/accounts/', include('accounts.urls')),
    path('help/', views.help_index, name='help_index'),
    path('legal/privacy/', views.legal_privacy, name='legal_privacy'),
    path('legal/terms/', views.legal_terms, name='legal_terms'),
    path('', include('feed.urls')),
    path('tasks/', include('tasks.urls')),
]
