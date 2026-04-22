from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0002_alter_linkedaccount_platform'),
    ]

    operations = [
        migrations.CreateModel(
            name='UserProfile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('first_name', models.CharField(blank=True, max_length=100)),
                ('last_name', models.CharField(blank=True, max_length=100)),
                ('contact_email', models.EmailField(blank=True)),
                ('show_first_name', models.BooleanField(default=True)),
                ('show_last_name', models.BooleanField(default=False)),
                ('show_contact_email', models.BooleanField(default=False)),
                ('show_github', models.BooleanField(default=True)),
                ('show_karma', models.BooleanField(default=True)),
                ('show_joined', models.BooleanField(default=True)),
                ('user', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='profile',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
        ),
    ]
