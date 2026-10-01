from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("social_django", "0017_usersocialauth_user_social_auth_uid_required")]

    operations = [
        migrations.AddField(
            model_name="usersocialauth",
            name="id_key",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
    ]
