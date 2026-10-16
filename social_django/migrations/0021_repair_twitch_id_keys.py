"""Correct the shared Twitch provider's historical OpenID Connect key."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings
from django.db import migrations

if TYPE_CHECKING:
    from django.db.backends.base.schema import BaseDatabaseSchemaEditor
    from django.db.migrations.state import StateApps


# Frozen class paths avoid importing installed backends in a historical migration.
# Current configuration is only a default: overrides describe historical usage.
TWITCH_ID_KEYS = {
    "social_core.backends.twitch.TwitchOAuth2": "id",
    "social_core.backends.twitch.TwitchOpenIdConnect": "sub",
}


def repair_twitch_id_keys(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    overrides = getattr(settings, "SOCIAL_AUTH_OLD_ID_KEYS", {})
    if not isinstance(overrides, dict):
        msg = "SOCIAL_AUTH_OLD_ID_KEYS must be a provider-to-historical-key mapping"
        raise TypeError(msg)

    configured_keys = {TWITCH_ID_KEYS[path] for path in settings.AUTHENTICATION_BACKENDS if path in TWITCH_ID_KEYS}
    default_key = "sub" if configured_keys == {"sub"} else "id"
    key = overrides.get("twitch", default_key)
    social_auth = apps.get_model("social_django", "UserSocialAuth")
    key_length = social_auth._meta.get_field("id_key").max_length
    if key is not None and (not isinstance(key, str) or not key or len(key) > key_length):
        msg = "SOCIAL_AUTH_OLD_ID_KEYS keys must be nonempty strings fitting id_key, or None"
        raise ValueError(msg)

    if key == "sub":
        social_auth.objects.using(schema_editor.connection.alias).filter(provider="twitch", id_key="id").update(
            id_key="sub"
        )


class Migration(migrations.Migration):
    dependencies = [("social_django", "0020_backfill_id_keys")]
    # Reversal cannot distinguish repaired rows from originally correct sub rows.
    operations = [migrations.RunPython(repair_twitch_id_keys, migrations.RunPython.noop)]
