from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0004_randomize_existing_task_slugs'),
    ]

    operations = [
        migrations.AddField(
            model_name='task',
            name='karma_reward',
            field=models.PositiveSmallIntegerField(default=0),
        ),
    ]
