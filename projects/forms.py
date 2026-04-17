# projects/forms.py — see feed/index.html patch below
from django import forms
from .models import Project


class ProjectForm(forms.ModelForm):
    activate = forms.BooleanField(
        required=False,
        label='Set as Active',
        help_text='Project will only go active if all tasks pass validation.',
    )

    class Meta:
        model = Project
        fields = ['name', 'url', 'description']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 4}),
        }