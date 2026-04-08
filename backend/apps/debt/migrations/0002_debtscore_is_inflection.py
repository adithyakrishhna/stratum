from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('debt', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='debtscore',
            name='is_inflection',
            field=models.BooleanField(default=False),
        ),
    ]
