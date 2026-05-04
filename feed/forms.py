from django import forms


class WebhookCheckForm(forms.Form):
    google_email = forms.EmailField(required=True)
    difficulty = forms.IntegerField(min_value=1, max_value=5, required=True)
