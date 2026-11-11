from importlib import import_module
from io import StringIO
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import ANY, Mock, call, patch

from django.core.management import call_command
from django.db import connection, connections
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from social_core.backends.twitch import TwitchOpenIdConnect

from social_django.models import UserSocialAuth


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


class ExtraDataMigrationTests(TestCase):
    def test_database_alias_for_forward_and_backward_writes(self):
        migration = import_module("social_django.migrations.0013_migrate_extra_data")
        schema_editor = SimpleNamespace(connection=SimpleNamespace(alias="other"))
        for function, field, partial_field in (
            (migration.migrate_json_field, "extra_data_new", "data_new"),
            (migration.migrate_json_field_backwards, "extra_data", "data"),
        ):
            with self.subTest(function=function.__name__), patch.object(migration, "MAX_BATCH_SIZE", 2):
                apps = Mock()
                model = apps.get_model.return_value
                queryset = model.objects.using.return_value
                queryset.exclude.return_value = queryset
                queryset.iterator.return_value = [Mock(), Mock(), Mock()]
                partial = Mock()
                queryset.all.return_value = [partial]
                function(apps, schema_editor)
                # Reads, both batched writes, and the Partial scan go through the migrated alias.
                self.assertEqual(model.objects.using.call_args_list, [call("other")] * 4)
                model.objects.bulk_update.assert_not_called()
                self.assertEqual(queryset.bulk_update.call_args_list, [call(ANY, [field])] * 2)
                partial.save.assert_called_once_with(using="other", update_fields=[partial_field])


class PopulatedExtraDataMigrationTests(TransactionTestCase):
    databases: ClassVar[set[str]] = {"default", "other"}

    def test_forward_and_reverse_keep_each_database_isolated(self):
        old_target = [("social_django", "0012_usersocialauth_extra_data_new")]
        migration = import_module("social_django.migrations.0013_migrate_extra_data")
        for alias in self.databases:
            MigrationExecutor(connections[alias]).migrate(old_target)
        try:
            apps = MigrationExecutor(connection).loader.project_state(old_target).apps
            user_model = apps.get_model("auth", "User")
            social_model = apps.get_model("social_django", "UserSocialAuth")
            partial_model = apps.get_model("social_django", "Partial")
            for alias, marker in (("default", "default"), ("other", "other")):
                user = user_model.objects.using(alias).create(username=marker)
                social_model.objects.using(alias).create(
                    pk=1,
                    user_id=user.pk,
                    provider="email",
                    uid=marker,
                    extra_data='{"source":"' + marker + '"}',
                    extra_data_new={"source": "original"},
                )
                partial_model.objects.using(alias).create(
                    pk=1,
                    token=marker,
                    backend="email",
                    data='{"source":"' + marker + '"}',
                    data_new={"source": "original"},
                )

            with connections["other"].schema_editor() as editor:
                migration.migrate_json_field(apps, editor)
            self.assertEqual(social_model.objects.using("default").get(pk=1).extra_data_new, {"source": "original"})
            self.assertEqual(social_model.objects.using("other").get(pk=1).extra_data_new, {"source": "other"})
            self.assertEqual(partial_model.objects.using("other").get(pk=1).data_new, {"source": "other"})

            social_model.objects.using("other").filter(pk=1).update(extra_data='{"source":"stale"}')
            partial_model.objects.using("other").filter(pk=1).update(data='{"source":"stale"}')
            with connections["other"].schema_editor() as editor:
                migration.migrate_json_field_backwards(apps, editor)
            self.assertEqual(social_model.objects.using("default").get(pk=1).extra_data, '{"source":"default"}')
            self.assertEqual(social_model.objects.using("other").get(pk=1).extra_data, '{"source": "other"}')
            self.assertEqual(partial_model.objects.using("default").get(pk=1).data, '{"source":"default"}')
            self.assertEqual(partial_model.objects.using("other").get(pk=1).data, '{"source": "other"}')
        finally:
            for alias in self.databases:
                db = connections[alias]
                MigrationExecutor(db).migrate(MigrationExecutor(db).loader.graph.leaf_nodes())


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
            migration = import_module("social_django.migrations.0019_oidc_nonce_lifetime")
            with patch.object(migration, "_time", return_value=2000):
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
            with (
                connection.schema_editor() as schema_editor,
                patch.object(migration, "_time", return_value=3000),
            ):
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
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())

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


class TwitchIdentifierKeyMigrationTests(TransactionTestCase):
    migrate_to: ClassVar = [("social_django", "0021_repair_twitch_id_keys")]
    oidc_path = "social_core.backends.twitch.TwitchOpenIdConnect"
    oauth2_path = "social_core.backends.twitch.TwitchOAuth2"

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_upgrade_from_before_identifier_tracking(self):
        for backend_path, expected in ((self.oidc_path, "sub"), (self.oauth2_path, "id")):
            with (
                self.subTest(backend=backend_path),
                override_settings(AUTHENTICATION_BACKENDS=(backend_path,), SOCIAL_AUTH_OLD_ID_KEYS={}),
            ):
                old_target = [("social_django", "0017_usersocialauth_user_social_auth_uid_required")]
                executor = MigrationExecutor(connection)
                executor.migrate(old_target)
                apps = executor.loader.project_state(old_target).apps
                user = apps.get_model("auth", "User").objects.create(username=expected)
                social_auth = apps.get_model("social_django", "UserSocialAuth")
                row = social_auth.objects.create(
                    user=user, provider="twitch", uid=expected, extra_data={"id": expected}
                )
                original = (row.user_id, row.uid, row.extra_data, row.created, row.modified)

                MigrationExecutor(connection).migrate(self.migrate_to)
                repaired = UserSocialAuth.objects.get(pk=row.pk)
                self.assertEqual(repaired.id_key, expected)
                self.assertEqual(
                    (repaired.user_id, repaired.uid, repaired.extra_data, repaired.created, repaired.modified), original
                )

    @override_settings(
        AUTHENTICATION_BACKENDS=("social_core.backends.twitch.TwitchOpenIdConnect",), SOCIAL_AUTH_OLD_ID_KEYS={}
    )
    def test_repair_preserves_data_and_returning_login(self):
        old_target = [("social_django", "0020_backfill_id_keys")]
        executor = MigrationExecutor(connection)
        executor.migrate(old_target)
        apps = executor.loader.project_state(old_target).apps
        user_model = apps.get_model("auth", "User")
        user = user_model.objects.create(username="streamer", email="streamer@example.com")
        social_auth = apps.get_model("social_django", "UserSocialAuth")
        original = []
        for provider, uid, key in (
            ("twitch", "12345", "id"),
            ("twitch", "already-correct", "sub"),
            ("twitch", "custom-key", "custom"),
            ("twitch", "skipped", ""),
            ("github", "12345", "id"),
        ):
            row = social_auth.objects.create(user=user, provider=provider, uid=uid, id_key=key, extra_data={"id": uid})
            original.append(row)

        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        apps = executor.loader.project_state(self.migrate_to).apps
        migration = import_module("social_django.migrations.0021_repair_twitch_id_keys")
        with connection.schema_editor() as schema_editor:
            migration.repair_twitch_id_keys(apps, schema_editor)
        # A populated reverse migration must retain repaired metadata.
        MigrationExecutor(connection).migrate(old_target)
        for before in original:
            after = UserSocialAuth.objects.get(pk=before.pk)
            self.assertEqual(
                after.id_key, "sub" if before.provider == "twitch" and before.id_key == "id" else before.id_key
            )
            self.assertEqual(
                (after.user_id, after.uid, after.extra_data, after.created, after.modified),
                (before.user_id, before.uid, before.extra_data, before.created, before.modified),
            )
        MigrationExecutor(connection).migrate(self.migrate_to)

        def complete(backend, *args, **kwargs):
            # Stand in for the provider exchange, then run the real authentication pipeline.
            backend.id_token = {"sub": "12345", "preferred_username": "streamer", "email": user.email}
            return backend.strategy.authenticate(*args, backend=backend, response=backend.id_token, **kwargs)

        with patch.object(TwitchOpenIdConnect, "auth_complete", complete):
            for _ in range(2):
                self.client.logout()
                response = self.client.get(reverse("social:complete", kwargs={"backend": "twitch"}))
                self.assertEqual(response.status_code, 302)
                self.assertEqual(self.client.session["_auth_user_id"], str(user.pk))
                self.assertEqual(user_model.objects.count(), 1)
                self.assertEqual(UserSocialAuth.objects.count(), len(original))
                self.assertEqual(UserSocialAuth.objects.get(provider="twitch", uid="12345").user_id, user.pk)

    def test_backend_selection_and_override_precedence(self):
        migration = import_module("social_django.migrations.0021_repair_twitch_id_keys")
        cases = (
            ((self.oidc_path,), {}, True),
            ((self.oauth2_path,), {}, False),
            ((), {}, False),
            ((self.oidc_path, self.oauth2_path), {}, False),
            (("custom.backends.TwitchOpenIdConnect",), {}, False),
            (("custom.backends.TwitchOpenIdConnect",), {"twitch": "sub"}, True),
            ((self.oauth2_path,), {"twitch": "sub"}, True),
            ((self.oidc_path,), {"twitch": "id"}, False),
            ((self.oidc_path,), {"twitch": None}, False),
            ((self.oidc_path,), {"twitch": "custom"}, False),
            ((self.oidc_path,), {"github": "id"}, True),
        )
        for backends, overrides, repair in cases:
            with (
                self.subTest(backends=backends, overrides=overrides),
                override_settings(AUTHENTICATION_BACKENDS=backends, SOCIAL_AUTH_OLD_ID_KEYS=overrides),
            ):
                apps = Mock()
                model = apps.get_model.return_value
                model._meta.get_field.return_value.max_length = 255
                migration.repair_twitch_id_keys(apps, SimpleNamespace(connection=SimpleNamespace(alias="other")))
                if repair:
                    model.objects.using.assert_called_once_with("other")
                    model.objects.using.return_value.filter.assert_called_once_with(provider="twitch", id_key="id")
                    model.objects.using.return_value.filter.return_value.update.assert_called_once_with(id_key="sub")
                else:
                    model.objects.using.assert_not_called()

    def test_invalid_overrides_fail_before_updates(self):
        migration = import_module("social_django.migrations.0021_repair_twitch_id_keys")
        apps = Mock()
        apps.get_model.return_value._meta.get_field.return_value.max_length = 255
        invalid_overrides: tuple[object, ...] = ([], {"twitch": ""}, {"twitch": 1}, {"twitch": "x" * 256})
        for overrides in invalid_overrides:
            with (
                self.subTest(overrides=overrides),
                override_settings(SOCIAL_AUTH_OLD_ID_KEYS=overrides),
                self.assertRaises((TypeError, ValueError)),
            ):
                migration.repair_twitch_id_keys(apps, SimpleNamespace(connection=connection))
        apps.get_model.return_value.objects.using.assert_not_called()
