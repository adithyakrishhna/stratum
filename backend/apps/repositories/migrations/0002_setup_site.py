"""
Data migration: update the default django.contrib.sites Site record
from 'example.com' to 'localhost:8000'.

Allauth uses the Site to build callback URLs during OAuth. This must
match the Authorization callback URL registered in your GitHub OAuth App.
"""
from django.db import migrations


def set_local_site(apps, schema_editor):
    Site = apps.get_model('sites', 'Site')
    Site.objects.update_or_create(
        id=1,
        defaults={'domain': 'localhost:8000', 'name': 'Stratum (local)'},
    )


def revert_site(apps, schema_editor):
    Site = apps.get_model('sites', 'Site')
    Site.objects.filter(id=1).update(domain='example.com', name='example.com')


class Migration(migrations.Migration):

    dependencies = [
        ('repositories', '0001_initial'),
        ('sites', '0002_alter_domain_unique'),
    ]

    operations = [
        migrations.RunPython(set_local_site, revert_site),
    ]
