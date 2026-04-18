# notifications/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('notifications/',                        views.inbox,        name='notifications_inbox'),
    path('notifications/unread/',                 views.unread_poll,  name='notifications_unread'),
    path('notifications/recent/',                 views.recent_poll,  name='notifications_recent'),
    path('notifications/mark-read/<int:notif_id>/', views.mark_read, name='notifications_mark_read'),
    path('notifications/mark-all-read/',          views.mark_all_read, name='notifications_mark_all_read'),
    path('notifications/preferences/',            views.save_preferences, name='notifications_preferences'),
]
