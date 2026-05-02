from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from django.shortcuts import render, redirect
from django.contrib import messages

from karma.models import KarmaTransaction
from karma.services import adjust_karma_by_staff, get_balance


class AdjustKarmaForm:
    """Simple form for adjusting karma."""
    def __init__(self, user):
        self.user = user
        self.balance = get_balance(user)


@admin.register(KarmaTransaction)
class KarmaTransactionAdmin(admin.ModelAdmin):
    list_display  = ('user_link', 'delta', 'reason', 'created_at')
    list_filter   = ('reason', 'created_at')
    search_fields = ('user__username', 'user__email')
    ordering      = ('-created_at',)
    readonly_fields = ('user', 'delta', 'reason', 'related_object_id', 'created_at')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def user_link(self, obj):
        url = reverse('admin:accounts_user_change', args=[obj.user.id])
        return format_html('<a href="{}">{}</a>', url, obj.user.username)
    user_link.short_description = 'User'


# Register User admin to add karma adjustment
from accounts.models import User
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    """Extended User admin with karma adjustment actions."""
    fieldsets = DjangoUserAdmin.fieldsets + (
        ('KarmaRace', {'fields': ('karma_balance',)}),
    )
    readonly_fields = ('karma_balance',)

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

