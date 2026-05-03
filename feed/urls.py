# feed/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('', views.feed, name='feed'),
    path('check/<int:task_id>/', views.check, name='feed_check'),
    path('check-status/<int:task_id>/', views.check_status, name='feed_check_status'),
    path('done/<int:task_id>/', views.done, name='feed_done'),
    path('switch/', views.switch, name='feed_switch'),
]