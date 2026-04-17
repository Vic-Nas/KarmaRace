# feed/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('', views.feed, name='feed'),
    path('done/<int:task_id>/', views.done, name='feed_done'),
]