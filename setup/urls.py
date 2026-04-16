# setup/urls.py
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('allauth.urls')),
    path('', include('feed.urls')),  # feed handles root
    path('', include('accounts.urls')),
]