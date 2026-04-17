# tasks/views.py
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect

from projects.models import Project
from .forms import TaskForm
from .services import on_task_created


@login_required
def task_create(request, project_pk):
	project = get_object_or_404(Project, pk=project_pk, owner=request.user)

	if request.method == 'POST':
		form = TaskForm(request.POST)
		if form.is_valid():
			task = form.save(commit=False)
			task.project = project
			task.save()
			on_task_created(task)
			return redirect('project_detail', pk=project.pk)
		# Fall through to detail view re-render with errors
		from projects.views import project_detail_with_task_form
		return project_detail_with_task_form(request, project, form)

	return redirect('project_detail', pk=project.pk)
from django.shortcuts import render

# Create your views here.
