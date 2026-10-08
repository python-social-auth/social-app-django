from importlib import import_module
from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, override_settings


class PendingMigrationsTests(TestCase):
    def test_no_pending_migrations(self):
        out = StringIO()
        try:
            call_command(
                "makemigrations",
                "--dry-run",
                "--check",
                stdout=out,
                stderr=StringIO(),
            )
        except SystemExit:  # pragma: no cover
            raise AssertionError("Pending migrations:\n" + out.getvalue()) from None


class OidcNonceLifetimeMigrationTests(TransactionTestCase):
    def test_legacy_nonces_receive_grace_period(self):
        old_target = [("social_django", "0018_usersocialauth_id_key")]
        new_target = [("social_django", "0019_oidc_nonce_lifetime")]
        executor = MigrationExecutor(connection)
        executor.migrate(old_target)
        try:
            old_apps = executor.loader.project_state(old_target).apps
            association = old_apps.get_model("social_django", "Association")
            original = (
                ("legacy-one", "", 0, 0),
                ("legacy-two", "", 0, 0),
                ("real-openid", "c2VjcmV0", 0, 0),
                ("bounded-nonce", "", 1000, 1800),
                ("zero-issued", "", 0, 1800),
            )
            for handle, secret, issued, lifetime in original:
                association.objects.create(
                    server_url="https://example.com",
                    handle=handle,
                    secret=secret,
                    issued=issued,
                    lifetime=lifetime,
                    assoc_type="state",
                )
            with patch("time.time", return_value=2000):
                executor = MigrationExecutor(connection)
                executor.migrate(new_target)
            apps = executor.loader.project_state(new_target).apps
            association = apps.get_model("social_django", "Association")
            for handle, secret, issued, lifetime in original:
                row = association.objects.get(handle=handle)
                expected = (2000, 1800) if handle.startswith("legacy-") else (issued, lifetime)
                self.assertEqual((row.issued, row.lifetime), expected)
                self.assertEqual(row.secret, secret)
                self.assertEqual(row.assoc_type, "state")
            # Reapplying the function must not extend the grace period.
            migration = import_module("social_django.migrations.0019_oidc_nonce_lifetime")
            with connection.schema_editor() as schema_editor, patch("time.time", return_value=3000):
                migration.bound_legacy_oidc_nonces(apps, schema_editor)
            self.assertEqual(association.objects.get(handle="legacy-one").issued, 2000)
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())


class IdentifierKeyMigrationTests(TransactionTestCase):
    @override_settings(SOCIAL_AUTH_OLD_ID_KEYS={"custom": "old_subject", "google-oauth2": "sub", "trello": None})
    def test_backfill_defaults_overrides_and_rerun(self):
        old_target = [("social_django", "0019_oidc_nonce_lifetime")]
        new_target = [("social_django", "0020_backfill_id_keys")]
        executor = MigrationExecutor(connection)
        executor.migrate(old_target)
        try:
            apps = executor.loader.project_state(old_target).apps
            user = apps.get_model("auth", "User").objects.create(username="migration")
            social_auth = apps.get_model("social_django", "UserSocialAuth")
            original = (
                ("github", "1", "", "id"),
                ("okta-oauth2", "old-name", "", "preferred_username"),
                ("google-oauth2", "stable-subject", "", "sub"),
                ("custom", "2", "", "old_subject"),
                ("trello", "old-name", "", ""),
                ("unknown", "3", "", ""),
                ("github", "4", "existing", "existing"),
            )
            timestamps = {}
            for provider, uid, key, _ in original:
                row = social_auth.objects.create(
                    user=user, provider=provider, uid=uid, id_key=key, extra_data={"sample": 1}
                )
                timestamps[row.pk] = (row.created, row.modified)
            executor = MigrationExecutor(connection)
            executor.migrate(new_target)
            apps = executor.loader.project_state(new_target).apps
            social_auth = apps.get_model("social_django", "UserSocialAuth")
            migration = import_module("social_django.migrations.0020_backfill_id_keys")
            with connection.schema_editor() as schema_editor:
                migration.backfill_id_keys(apps, schema_editor)
            for provider, uid, _, expected in original:
                row = social_auth.objects.get(provider=provider, uid=uid)
                self.assertEqual(row.id_key, expected)
                self.assertEqual(row.extra_data, {"sample": 1})
                self.assertEqual((row.created, row.modified), timestamps[row.pk])
        finally:
            MigrationExecutor(connection).migrate(new_target)

    def test_database_alias_and_set_based_updates(self):
        migration = import_module("social_django.migrations.0020_backfill_id_keys")
        apps = Mock()
        model = apps.get_model.return_value
        model._meta.get_field.side_effect = lambda name: SimpleNamespace(max_length=32 if name == "provider" else 255)
        with override_settings(SOCIAL_AUTH_OLD_ID_KEYS={}), patch.object(migration, "OLD_ID_KEYS", {"github": "id"}):
            migration.backfill_id_keys(apps, SimpleNamespace(connection=SimpleNamespace(alias="other")))
        model.objects.using.assert_called_once_with("other")
        model.objects.using.return_value.filter.assert_called_once_with(provider="github", id_key="")
        model.objects.using.return_value.filter.return_value.update.assert_called_once_with(id_key="id")

    def test_invalid_settings_fail_before_updates(self):
        migration = import_module("social_django.migrations.0020_backfill_id_keys")
        apps = Mock()
        apps.get_model.return_value._meta.get_field.side_effect = lambda name: SimpleNamespace(
            max_length=32 if name == "provider" else 255
        )
        invalid_overrides: tuple[object, ...] = ([], {"github": ""}, {"github": 1}, {"github": "x" * 256}, {1: "id"})
        for overrides in invalid_overrides:
            with (
                self.subTest(overrides=overrides),
                override_settings(SOCIAL_AUTH_OLD_ID_KEYS=overrides),
                self.assertRaises((TypeError, ValueError)),
            ):
                migration.backfill_id_keys(apps, SimpleNamespace(connection=connection))
        apps.get_model.return_value.objects.using.assert_not_called()
