from django.db import migrations


def drop_open_webhook_obligations(apps, schema_editor):
    ReciprocityObligation = apps.get_model('tasks', 'ReciprocityObligation')
    ReciprocityObligation.objects.filter(task_type='WEBHOOK').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0002_reciprocityobligation'),
    ]

    operations = [
        migrations.RunPython(drop_open_webhook_obligations, migrations.RunPython.noop),
    ]
