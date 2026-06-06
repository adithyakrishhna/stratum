from django.db import migrations
from pgvector.django import VectorField


class Migration(migrations.Migration):

    dependencies = [
        ('clustering', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='semanticcluster',
            name='centroid',
            field=VectorField(blank=True, dimensions=768, null=True),
        ),
    ]
