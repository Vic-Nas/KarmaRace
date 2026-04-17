# tasks/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('<int:project_pk>/add/', views.task_create, name='task_create'),
]