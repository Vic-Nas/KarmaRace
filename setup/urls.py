from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('allauth.urls')),
    path('app/accounts/', include('accounts.urls')),
    path('', include('feed.urls')),
    path('tasks/', include('tasks.urls')),
]
