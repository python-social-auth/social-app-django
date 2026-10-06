import time

from django.db import migrations


def bound_legacy_oidc_nonces(apps, schema_editor):
    association = apps.get_model("social_django", "Association")
    association.objects.using(schema_editor.connection.alias).filter(secret="", issued=0, lifetime=0).update(
        issued=int(time.time()), lifetime=1800
    )


class Migration(migrations.Migration):
    dependencies = [("social_django", "0018_usersocialauth_id_key")]

    operations = [
        migrations.RunPython(bound_legacy_oidc_nonces, migrations.RunPython.noop),
    ]
