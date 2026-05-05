# accounts/admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.urls import reverse
from django.utils.html import format_html
from django.shortcuts import render, redirect
from django.contrib import messages
from django.http import HttpResponse

from accounts.models import (
    User,
    VerifiedEmail,
    OutreachRecord,
    OutreachContactedEmail,

)
from karma.services import get_balance, adjust_karma_by_staff
from django.shortcuts import render, redirect
from django.contrib import messages


class UserAdmin(DjangoUserAdmin):
    """Extended User admin with karma adjustment actions."""
    fieldsets = DjangoUserAdmin.fieldsets + (
        ('KarmaRace', {'fields': ('karma_balance',)}),
    )
    readonly_fields = DjangoUserAdmin.readonly_fields + ('karma_balance',)

    def karma_balance(self, obj):
        """Display current karma balance."""
        balance = get_balance(obj)
        return format_html(
            '<strong style="color: {};">{}</strong>',
            '#28a745' if balance > 0 else '#dc3545' if balance < 0 else '#6c757d',
            balance
        )
    karma_balance.short_description = 'Current Karma Balance'

    actions = ['adjust_karma']

    def adjust_karma(self, request, queryset):
        """Action to adjust karma (positive to add, negative to subtract)."""
        # Check if form was submitted with delta value
        delta_str = request.POST.get('delta', '').strip()
        
        if delta_str:  # Form submitted
            try:
                delta = int(delta_str)
                reason = request.POST.get('reason', '').strip() or 'Manual adjustment from admin'
                
                if delta == 0:
                    self.message_user(request, 'Amount cannot be zero.', messages.ERROR)
                    return

                for user in queryset:
                    adjust_karma_by_staff(user, delta, reason)
                
                op = 'added' if delta > 0 else 'subtracted'
                self.message_user(
                    request,
                    f'✓ {op.capitalize()} {abs(delta)} karma to {queryset.count()} user(s).',
                    messages.SUCCESS
                )
            except (ValueError, TypeError):
                self.message_user(request, 'Invalid amount.', messages.ERROR)
            return

        # Show form on initial click
        return render(
            request,
            'admin/karma_adjust.html',
            {'queryset': queryset}
        )
    adjust_karma.short_description = '⚙️ Adjust Karma'


admin.site.register(User, UserAdmin)
admin.site.register(VerifiedEmail)


@admin.register(OutreachRecord)
class OutreachRecordAdmin(admin.ModelAdmin):
    list_display  = ("email", "score", "created_at")
    list_filter   = ("created_at",)
    search_fields = ("email",)
    ordering      = ("-score", "created_at")


@admin.register(OutreachContactedEmail)
class OutreachContactedEmailAdmin(admin.ModelAdmin):
    list_display  = ("email", "contacted_at")
    search_fields = ("email",)
    ordering      = ("-contacted_at",)