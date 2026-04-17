# tasks/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('new/', views.task_create, name='task_create'),
    path('<int:task_pk>/edit/', views.task_edit, name='task_edit'),
    path('<int:task_pk>/delete/', views.task_delete, name='task_delete'),
]