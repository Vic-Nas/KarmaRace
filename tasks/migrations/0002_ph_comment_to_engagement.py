from django.db import migrations, models


def forward_map_ph_comment_to_engagement(apps, schema_editor):
    Task = apps.get_model('tasks', 'Task')
    ReciprocityObligation = apps.get_model('tasks', 'ReciprocityObligation')

    Task.objects.filter(type='PH_COMMENT').update(type='PH_ENGAGEMENT')
    ReciprocityObligation.objects.filter(task_type='PH_COMMENT').update(task_type='PH_ENGAGEMENT')


def reverse_map_engagement_to_ph_comment(apps, schema_editor):
    Task = apps.get_model('tasks', 'Task')
    ReciprocityObligation = apps.get_model('tasks', 'ReciprocityObligation')

    Task.objects.filter(type='PH_ENGAGEMENT').update(type='PH_COMMENT')
    ReciprocityObligation.objects.filter(task_type='PH_ENGAGEMENT').update(task_type='PH_COMMENT')


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(
            forward_map_ph_comment_to_engagement,
            reverse_map_engagement_to_ph_comment,
        ),
        migrations.AlterField(
            model_name='task',
            name='type',
            field=models.CharField(
                choices=[
                    ('GITHUB_STAR', 'Github Star'),
                    ('GITHUB_FORK', 'Github Fork'),
                    ('PH_ENGAGEMENT', 'Ph Engagement'),
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
                    ('PH_ENGAGEMENT', 'Ph Engagement'),
                    ('WEBHOOK', 'Webhook'),
                ],
                max_length=20,
            ),
        ),
    ]
