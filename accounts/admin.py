from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.urls import reverse
from django.utils.html import format_html

from accounts.models import (
    User,
    VerifiedEmail,
    OutreachRecord,
    OutreachContactedEmail,
    OutreachDailyStats,
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

    actions = ['adjust_karma_add', 'adjust_karma_subtract']

    def adjust_karma_add(self, request, queryset):
        """Action to add karma to selected users."""
        if request.method == 'POST':
            try:
                amount = int(request.POST.get('karma_amount', 0))
                reason = request.POST.get('karma_reason', 'Manual adjustment from admin').strip()
                
                if amount <= 0:
                    self.message_user(request, 'Amount must be positive.', messages.ERROR)
                    return

                for user in queryset:
                    adjust_karma_by_staff(user, amount, reason)
                
                self.message_user(
                    request,
                    f'✓ Added {amount} karma to {queryset.count()} user(s).',
                    messages.SUCCESS
                )
                return redirect(request.get_full_path())
            except (ValueError, TypeError):
                self.message_user(request, 'Invalid amount.', messages.ERROR)
                return

        return render(
            request,
            'admin/karma_adjust.html',
            {
                'title': 'Add Karma',
                'queryset': queryset,
                'action': 'adjust_karma_add',
                'operation': 'Add',
            }
        )
    adjust_karma_add.short_description = '➕ Add Karma'

    def adjust_karma_subtract(self, request, queryset):
        """Action to subtract karma from selected users."""
        if request.method == 'POST':
            try:
                amount = int(request.POST.get('karma_amount', 0))
                reason = request.POST.get('karma_reason', 'Manual adjustment from admin').strip()
                
                if amount <= 0:
                    self.message_user(request, 'Amount must be positive.', messages.ERROR)
                    return

                for user in queryset:
                    adjust_karma_by_staff(user, -amount, reason)
                
                self.message_user(
                    request,
                    f'✓ Subtracted {amount} karma from {queryset.count()} user(s).',
                    messages.SUCCESS
                )
                return redirect(request.get_full_path())
            except (ValueError, TypeError):
                self.message_user(request, 'Invalid amount.', messages.ERROR)
                return

        return render(
            request,
            'admin/karma_adjust.html',
            {
                'title': 'Subtract Karma',
                'queryset': queryset,
                'action': 'adjust_karma_subtract',
                'operation': 'Subtract',
            }
        )
    adjust_karma_subtract.short_description = '➖ Subtract Karma'


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


@admin.register(OutreachDailyStats)
class OutreachDailyStatsAdmin(admin.ModelAdmin):
    list_display = (
        "date", "harvested", "queued_count", "sent_count",
        "failed_count", "pending_after", "updated_at",
    )
    ordering = ("-date",)

