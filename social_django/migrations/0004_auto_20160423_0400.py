from django.db import migrations

from social_django.fields import JSONField


class Migration(migrations.Migration):
    dependencies = [
        ("social_django", "0003_alter_email_max_length"),
    ]

    operations = [
        migrations.AlterField(
            model_name="usersocialauth",
            name="extra_data",
            field=JSONField(default=dict),
        ),
    ]
