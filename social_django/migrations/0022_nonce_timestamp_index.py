from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("social_django", "0021_repair_twitch_id_keys")]

    operations = [
        migrations.AlterField(
            model_name="nonce",
            name="timestamp",
            field=models.IntegerField(db_index=True),
        ),
    ]
