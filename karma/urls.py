# karma/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('balance/', views.balance, name='balance'),
    path('leaderboard/', views.leaderboard, name='leaderboard'),
    path('leaderboard/stream/', views.leaderboard_stream, name='leaderboard_stream'),
]
