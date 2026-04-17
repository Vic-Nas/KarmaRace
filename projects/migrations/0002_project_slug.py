from django.db import migrations, models
from django.utils.text import slugify


def populate_project_slugs(apps, schema_editor):
    Project = apps.get_model('projects', 'Project')

    existing_slugs = set(
        Project.objects.exclude(slug='').values_list('slug', flat=True)
    )

    for project in Project.objects.all().order_by('id'):
        if project.slug:
            continue

        base_slug = slugify(project.name)[:120] or 'project'
        slug = base_slug
        counter = 2
        while slug in existing_slugs:
            suffix = f'-{counter}'
            slug = f'{base_slug[:140 - len(suffix)]}{suffix}'
            counter += 1

        project.slug = slug
        project.save(update_fields=['slug'])
        existing_slugs.add(slug)


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='project',
            name='slug',
            field=models.SlugField(blank=True, max_length=140, unique=True),
        ),
        migrations.RunPython(populate_project_slugs, migrations.RunPython.noop),
    ]
