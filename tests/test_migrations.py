from importlib import import_module
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase


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
            MigrationExecutor(connection).migrate(new_target)
