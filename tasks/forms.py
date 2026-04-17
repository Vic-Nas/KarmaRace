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
        self.fields['description'].required = False

        task_type = self._selected_task_type()
        if task_type and task_type != Task.Type.WEBHOOK:
            self.fields['description'].disabled = True
            self.fields['description'].help_text = 'Auto-generated for this task type.'
            self.fields['description'].widget.attrs['placeholder'] = 'Auto-generated from type and target.'

    def _selected_task_type(self):
        if self.is_bound:
            return self.data.get(self.add_prefix('type'))
        if self.instance and self.instance.pk:
            return self.instance.type
        return self.initial.get('type')

    @staticmethod
    def _auto_description(task_type, target_id):
        if task_type == Task.Type.GITHUB_STAR:
            return f'Star GitHub repo {target_id}'
        if task_type == Task.Type.GITHUB_FORK:
            return f'Fork GitHub repo {target_id}'
        if task_type == Task.Type.PH_COMMENT:
            return f'Comment on Product Hunt post {target_id}'
        return ''

    def clean_description(self):
        task_type = self.cleaned_data.get('type') or self._selected_task_type()
        target_id = self.cleaned_data.get('target_id') or getattr(self.instance, 'target_id', '')
        description = (self.cleaned_data.get('description') or '').strip()

        if task_type == Task.Type.WEBHOOK:
            if not description:
                raise forms.ValidationError('Description is required for webhook tasks.')
            return description

        return self._auto_description(task_type, target_id)