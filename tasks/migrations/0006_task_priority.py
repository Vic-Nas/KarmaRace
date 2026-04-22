from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0005_task_karma_reward'),
    ]

    operations = [
        migrations.AddField(
            model_name='task',
            name='priority',
            field=models.PositiveSmallIntegerField(default=0, db_index=True),
        ),
    ]
