from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0003_taskcompletion_result_detail'),
    ]

    operations = [
        migrations.AddField(
            model_name='task',
            name='health_failure_streak',
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='task',
            name='health_last_checked_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='task',
            name='health_last_failure_reason',
            field=models.TextField(blank=True, default=''),
        ),
    ]
