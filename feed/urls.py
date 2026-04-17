# feed/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('', views.feed, name='feed'),
    path('check/<int:task_id>/', views.check, name='feed_check'),
    path('done/<int:task_id>/', views.done, name='feed_done'),
]