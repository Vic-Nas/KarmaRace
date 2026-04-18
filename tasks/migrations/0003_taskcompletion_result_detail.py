from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0002_ph_comment_to_engagement'),
    ]

    operations = [
        migrations.AddField(
            model_name='taskcompletion',
            name='result_detail',
            field=models.TextField(blank=True, default=''),
        ),
    ]
