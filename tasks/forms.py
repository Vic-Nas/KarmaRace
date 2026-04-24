# tasks/forms.py
from django import forms
from .models import Task
from .services import get_user_github_repo_choices_cached


class TaskForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = ['type', 'slug', 'description', 'target_id', 'webhook_secret']
        widgets = {
            'type': forms.Select(attrs={'class': 'form-select', 'id': 'id_type'}),
            'slug': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'task-slug',
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control', 'rows': 2,
                'placeholder': 'Tell testers what to do (e.g. "Star our repo so we can gauge interest")',
            }),
            'target_id': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'owner/repo  — or https://your-webhook.com/verify',
            }),
            'webhook_secret': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Optional secret sent as Authorization: Bearer …',
            }),
        }
        labels = {
            'slug': 'Slug',
            'target_id': 'Target',
            'webhook_secret': 'Webhook secret (optional)',
        }
        help_texts = {
            'slug': 'URL slug used in task management links. Letters, numbers, hyphens, underscores.',
            'target_id': 'GitHub: <code>owner/repo</code> &nbsp;·&nbsp; Webhook: full URL',
            'type': '',
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        self.force_repo_reload = bool(kwargs.pop('force_repo_reload', False))
        super().__init__(*args, **kwargs)
        # webhook_secret only relevant for WEBHOOK tasks; hide it initially via JS
        self.fields['webhook_secret'].required = False
        self.fields['description'].required = False

        self.github_repo_choices = []
        self.github_repo_load_error = ''
        self.github_repo_selected = ''
        if self.user is not None:
            self.github_repo_choices, self.github_repo_load_error = get_user_github_repo_choices_cached(
                self.user,
                force_reload=self.force_repo_reload,
            )

        if self.is_bound:
            current_target = (self.data.get(self.add_prefix('target_id')) or '').strip()
        elif self.instance and self.instance.pk:
            current_target = (self.instance.target_id or '').strip()
        else:
            current_target = (self.initial.get('target_id') or '').strip()

        if current_target:
            self.github_repo_selected = current_target
            values = {value for value, _ in self.github_repo_choices}
            if current_target not in values:
                self.github_repo_choices.insert(0, (current_target, f'{current_target} (current)'))

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

    def clean_target_id(self):
        task_type = self.cleaned_data.get('type') or self._selected_task_type()
        target_id = (self.cleaned_data.get('target_id') or '').strip()

        if task_type in (Task.Type.GITHUB_STAR, Task.Type.GITHUB_FORK):
            allowed_targets = {value for value, _ in self.github_repo_choices}
            if not allowed_targets:
                raise forms.ValidationError('No eligible GitHub repositories were discovered for your account. Reload repos after reconnecting GitHub.')
            if not target_id or target_id not in allowed_targets:
                raise forms.ValidationError('Select a GitHub repository from your linked-account list.')

        return target_id

    def clean_slug(self):
        slug = (self.cleaned_data.get('slug') or '').strip()
        if not slug:
            return slug

        if self.user is None:
            return slug

        qs = Task.objects.filter(owner=self.user, slug=slug)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError('This slug is already used by one of your tasks.')
        return slug