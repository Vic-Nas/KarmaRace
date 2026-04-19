from django.db import migrations, models


LEGACY_TYPES = ('PH_ENGAGEMENT', 'PH_COMMENT')



def purge_legacy_task_types(apps, schema_editor):
    Task = apps.get_model('tasks', 'Task')
    ReciprocityObligation = apps.get_model('tasks', 'ReciprocityObligation')

    Task.objects.filter(type__in=LEGACY_TYPES).delete()
    ReciprocityObligation.objects.filter(task_type__in=LEGACY_TYPES).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0005_task_owner_unpublished'),
    ]

    operations = [
        migrations.AlterField(
            model_name='task',
            name='type',
            field=models.CharField(
                choices=[
                    ('GITHUB_STAR', 'Github Star'),
                    ('GITHUB_FORK', 'Github Fork'),
                    ('WEBHOOK', 'Webhook'),
                ],
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name='reciprocityobligation',
            name='task_type',
            field=models.CharField(
                choices=[
                    ('GITHUB_STAR', 'Github Star'),
                    ('GITHUB_FORK', 'Github Fork'),
                    ('WEBHOOK', 'Webhook'),
                ],
                max_length=20,
            ),
        ),
        migrations.RunPython(purge_legacy_task_types, migrations.RunPython.noop),
    ]
