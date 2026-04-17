# setup/urls.py
from django.contrib import admin
from django.urls import path, include

# setup/urls.py
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('allauth.urls')),
    path('', include('feed.urls')),
    path('', include('accounts.urls')),
    path('projects/', include('projects.urls')),
    path('tasks/', include('tasks.urls')),
]