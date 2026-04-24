from uuid import uuid4

from django.db import migrations


def randomize_task_slugs(apps, schema_editor):
    Task = apps.get_model('tasks', 'Task')

    for task in Task.objects.all().order_by('id'):
        while True:
            candidate = f't-{uuid4().hex[:12]}'
            if not Task.objects.exclude(pk=task.pk).filter(owner_id=task.owner_id, slug=candidate).exists():
                task.slug = candidate
                task.save(update_fields=['slug'])
                break


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0003_task_slug'),
    ]

    operations = [
        migrations.RunPython(randomize_task_slugs, migrations.RunPython.noop),
    ]
