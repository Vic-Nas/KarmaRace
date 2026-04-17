# tasks/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('<slug:project_slug>/add/', views.task_create, name='task_create'),
    path('<slug:project_slug>/<int:task_pk>/edit/', views.task_edit, name='task_edit'),
    path('<slug:project_slug>/<int:task_pk>/delete/', views.task_delete, name='task_delete'),
]