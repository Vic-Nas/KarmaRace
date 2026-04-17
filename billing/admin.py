from django.contrib import admin

from billing.models import BillingProfile


@admin.register(BillingProfile)
class BillingProfileAdmin(admin.ModelAdmin):
    list_display = (
        'user',
        'subscription_status',
        'stripe_customer_id',
        'stripe_subscription_id',
        'current_period_end',
    )
    search_fields = ('user__username', 'user__email', 'stripe_customer_id', 'stripe_subscription_id')
