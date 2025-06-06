# Generated by Django 5.1.7 on 2025-03-14 12:16

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("social_django", "0016_alter_usersocialauth_extra_data"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="usersocialauth",
            constraint=models.CheckConstraint(
                condition=models.Q(("uid", ""), _negated=True),
                name="user_social_auth_uid_required",
            ),
        ),
    ]
