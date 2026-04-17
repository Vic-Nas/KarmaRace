from django.shortcuts import render


def legal_privacy(request):
    return render(request, 'legal/privacy.html')


def legal_terms(request):
    return render(request, 'legal/terms.html')


def help_index(request):
    return render(request, 'help/index.html')
