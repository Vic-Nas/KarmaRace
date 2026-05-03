# billing/urls.py
from django.urls import path

from billing import views

urlpatterns = [
    path('plan/', views.billing_plan, name='billing_plan'),
    path('checkout/', views.start_checkout, name='billing_checkout'),
    path('portal/', views.billing_portal, name='billing_portal'),
    path('webhook/', views.stripe_webhook, name='billing_webhook'),
]
