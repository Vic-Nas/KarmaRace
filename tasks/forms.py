# tasks/forms.py
from django import forms
from .models import Task


class TaskForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = ['type', 'description', 'target_id', 'webhook_secret']
        widgets = {
            'type': forms.Select(attrs={'class': 'form-select', 'id': 'id_type'}),
            'description': forms.Textarea(attrs={
                'class': 'form-control', 'rows': 2,
                'placeholder': 'Tell testers what to do (e.g. "Star our repo so we can gauge interest")',
            }),
            'target_id': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'owner/repo  — or PH post ID  — or https://your-webhook.com/verify',
            }),
            'webhook_secret': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Optional secret sent as Authorization: Bearer …',
            }),
        }
        labels = {
            'target_id': 'Target',
            'webhook_secret': 'Webhook secret (optional)',
        }
        help_texts = {
            'target_id': 'GitHub: <code>owner/repo</code> &nbsp;·&nbsp; Product Hunt: post ID &nbsp;·&nbsp; Webhook: full URL',
            'type': '',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # webhook_secret only relevant for WEBHOOK tasks; hide it initially via JS
        self.fields['webhook_secret'].required = False