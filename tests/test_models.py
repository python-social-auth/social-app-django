import runpy
import sqlite3
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import ClassVar
from unittest import mock
from uuid import UUID
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import IntegrityError, connection, models
from django.test import TestCase, override_settings
from django.test.utils import isolate_apps
from social_core.backends.cognito import CognitoOAuth2
from social_core.exceptions import AuthAssociationError
from social_core.pipeline.user import get_username

from social_django import storage
from social_django.managers import UserSocialAuthManager
from social_django.models import (
    AbstractUserSocialAuth,
    Association,
    Code,
    DjangoStorage,
    Nonce,
    Partial,
    UserSocialAuth,
)
from social_django.storage import SQLITE_PRIMARY_KEY_ERROR_CODE, SQLITE_UNIQUE_ERROR_CODE
from social_django.strategy import DjangoStrategy


class TestCodeExpiry(TestCase):
    @override_settings(TIME_ZONE="Europe/Prague")
    def test_lifetime_across_daylight_saving_time(self):
        timestamp = datetime(2026, 10, 24, 12, tzinfo=ZoneInfo("Europe/Prague"))
        for use_tz in (True, False):
            with self.subTest(use_tz=use_tz), override_settings(USE_TZ=use_tz):
                code = Code.make_code("expiry@example.com")
                code.timestamp = timestamp if use_tz else timestamp.replace(tzinfo=None)
                code.save()
                now = datetime(2026, 10, 25, 11, tzinfo=ZoneInfo("Europe/Prague"))
                with mock.patch("social_django.storage.timezone.now", return_value=now):
                    self.assertTrue(code.is_expired(24 * 60 * 60))

    @override_settings(TIME_ZONE="Europe/Prague")
    def test_persisted_code_expiry(self):
        for use_tz in (True, False):
            with self.subTest(use_tz=use_tz), override_settings(USE_TZ=use_tz):
                code = Code.make_code("expiry@example.com")
                code.refresh_from_db()
                self.assertIsNotNone(code.timestamp)
                strategy = DjangoStrategy(DjangoStorage)
                self.assertTrue(strategy.validate_email(code.email, code.code))
                self.assertFalse(strategy.validate_email(code.email, code.code))

                code = Code.make_code("expiry@example.com")
                now = code.timestamp
                Code.objects.filter(pk=code.pk).update(timestamp=now - timedelta(days=7))
                with mock.patch("social_django.storage.timezone.now", return_value=now):
                    self.assertFalse(strategy.validate_email(code.email, code.code))
                code.refresh_from_db()
                self.assertFalse(code.verified)

                Code.objects.filter(pk=code.pk).update(timestamp=now - timedelta(days=7) + timedelta(microseconds=1))
                with mock.patch("social_django.storage.timezone.now", return_value=now):
                    self.assertTrue(strategy.validate_email(code.email, code.code))

    @override_settings(SOCIAL_AUTH_EMAIL_VALIDATION_EXPIRED_THRESHOLD=60)
    def test_configured_expiry(self):
        code = Code.make_code("expiry@example.com")
        Code.objects.filter(pk=code.pk).update(timestamp=code.timestamp - timedelta(seconds=61))
        strategy = DjangoStrategy(DjangoStorage)
        self.assertFalse(strategy.validate_email(code.email, code.code))
        code.refresh_from_db()
        self.assertFalse(code.verified)

    def test_disabled_expiry(self):
        for threshold in (None, 0):
            with (
                self.subTest(threshold=threshold),
                override_settings(SOCIAL_AUTH_EMAIL_VALIDATION_EXPIRED_THRESHOLD=threshold),
            ):
                code = Code.make_code("expiry@example.com")
                Code.objects.filter(pk=code.pk).update(timestamp=code.timestamp - timedelta(days=30))
                strategy = DjangoStrategy(DjangoStorage)
                self.assertTrue(strategy.validate_email(code.email, code.code))
                self.assertFalse(strategy.validate_email(code.email, code.code))


class TestSocialAuthUser(TestCase):
    def test_user_relationship_none(self):
        """Accessing User.social_user outside of the pipeline doesn't work"""
        User = get_user_model()  # ruff: ignore[non-lowercase-variable-in-function]
        user = User._default_manager.create_user(username="randomtester")
        with self.assertRaises(AttributeError):
            user.social_user  # ruff: ignore[useless-expression]

    def test_user_existing_relationship(self):
        """Accessing User.social_user outside of the pipeline doesn't work"""
        User = get_user_model()  # ruff: ignore[non-lowercase-variable-in-function]
        user = User._default_manager.create_user(username="randomtester")
        UserSocialAuth.objects.create(user=user, provider="my-provider", uid="1234")
        with self.assertRaises(AttributeError):
            user.social_user  # ruff: ignore[useless-expression]

    def test_get_social_auth(self):
        User = get_user_model()  # ruff: ignore[non-lowercase-variable-in-function]
        user = User._default_manager.create_user(username="randomtester")
        user_social = UserSocialAuth.objects.create(user=user, provider="my-provider", uid="1234")
        other = UserSocialAuth.get_social_auth("my-provider", "1234")
        self.assertEqual(other, user_social)

    def test_get_social_auth_none(self):
        other = UserSocialAuth.get_social_auth("my-provider", "1234")
        self.assertIsNone(other)

    def test_cleanup(self):
        Code.objects.create(email="first@example.com")
        Code.objects.create(email="second@example.com")
        code = Code.objects.create(email="expire@example.com")
        code.timestamp -= timedelta(days=30)
        code.save()

        Partial.objects.create()
        partial = Partial.objects.create()
        partial.timestamp -= timedelta(days=30)
        partial.save()

        call_command("clearsocial")

        self.assertEqual(2, Code.objects.count())
        self.assertEqual(1, Partial.objects.count())


class TestUserSocialAuth(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.user = self.user_model._default_manager.create_user(username="randomtester", email="user@example.com")
        self.usa = UserSocialAuth.objects.create(user=self.user, provider="my-provider", uid="1234")

    def test_changed(self):
        self.user.email = eml = "test@example.com"
        UserSocialAuth.changed(user=self.user)
        db_eml = self.user_model._default_manager.get(username=self.user.username).email
        self.assertEqual(db_eml, eml)

    def test_set_extra_data(self):
        self.usa.set_extra_data({"a": "b"})
        self.usa.refresh_from_db()
        db_data = UserSocialAuth.objects.get(id=self.usa.id).extra_data
        self.assertEqual(db_data, {"a": "b"})

    def test_disconnect(self):
        m = mock.Mock()
        UserSocialAuth.disconnect(m)
        self.assertListEqual(m.method_calls, [mock.call.delete()])

    def test_username_field(self):
        self.assertEqual(UserSocialAuth.username_field(), "username")
        with mock.patch(
            "social_django.models.UserSocialAuth.user_model",
            return_value=mock.Mock(USERNAME_FIELD="test"),
        ):
            self.assertEqual(UserSocialAuth.username_field(), "test")

    def test_user_exists(self):
        self.assertTrue(UserSocialAuth.user_exists(username=self.user.username))
        self.assertFalse(UserSocialAuth.user_exists(username="test"))

    def test_get_username(self):
        self.assertEqual(UserSocialAuth.get_username(self.user), self.user.username)

    def test_create_user(self):
        UserSocialAuth.create_user(username="testuser")

    def test_create_user_reraise(self):
        with self.assertRaises(AuthAssociationError):
            UserSocialAuth.create_user(username=self.user.username, email=None)

    @mock.patch("social_django.models.UserSocialAuth.username_field", return_value="email")
    @mock.patch("django.contrib.auth.models.UserManager.create_user", return_value="<User>")
    def test_create_user_custom_username(self, *args):
        UserSocialAuth.create_user(username=self.user.email)

    @mock.patch("django.contrib.auth.models.UserManager.create_user", side_effect=IntegrityError)
    def test_create_user_existing(self, *args):
        with self.assertRaises(IntegrityError):
            UserSocialAuth.create_user(username=self.user.email)

    def test_get_user(self):
        self.assertEqual(UserSocialAuth.get_user(pk=self.user.pk), self.user)
        self.assertIsNone(UserSocialAuth.get_user(pk=123))

    def test_get_users_by_email(self):
        qs = UserSocialAuth.get_users_by_email(email=self.user.email)
        self.assertEqual(qs.count(), 1)
        self.user.is_active = False
        self.user.save()
        qs = UserSocialAuth.get_users_by_email(email=self.user.email)
        self.assertEqual(qs.count(), 0)
        with override_settings(SOCIAL_AUTH_ACTIVE_USERS_FILTER={}):
            qs = UserSocialAuth.get_users_by_email(email=self.user.email)
            self.assertEqual(qs.count(), 1)

    def test_get_social_auth(self):
        usa = self.usa
        # Model
        self.assertEqual(UserSocialAuth.get_social_auth(provider=usa.provider, uid=usa.uid), usa)
        self.assertIsNone(UserSocialAuth.get_social_auth(provider="a", uid="1"))

        # Mixin
        self.assertEqual(
            super(AbstractUserSocialAuth, usa).get_social_auth(provider=usa.provider, uid=usa.uid),
            usa,
        )
        self.assertIsNone(super(AbstractUserSocialAuth, usa).get_social_auth(provider="a", uid="1"))

        # Manager
        self.assertEqual(
            UserSocialAuth.objects.get_social_auth(provider=usa.provider, uid=usa.uid),
            usa,
        )
        self.assertIsNone(UserSocialAuth.objects.get_social_auth(provider="a", uid="1"))

        usa.id_key = "id"
        usa.save(update_fields=["id_key"])
        self.assertEqual(
            UserSocialAuth.get_social_auth(provider=usa.provider, uid=usa.uid, id_key="id"),
            usa,
        )
        self.assertIsNone(UserSocialAuth.get_social_auth(provider=usa.provider, uid=usa.uid, id_key="email"))
        self.assertIsNone(UserSocialAuth.get_social_auth(provider=usa.provider, uid=usa.uid, id_key="ID"))

    def test_get_social_auth_int_uid(self):
        usa = self.usa
        int_uid = int(usa.uid)

        # Model
        self.assertEqual(UserSocialAuth.get_social_auth(provider=usa.provider, uid=int_uid), usa)

        # Mixin
        self.assertEqual(
            super(AbstractUserSocialAuth, usa).get_social_auth(provider=usa.provider, uid=usa.uid),
            usa,
        )

        # Manager
        self.assertEqual(
            UserSocialAuth.get_social_auth(provider=usa.provider, uid=int_uid),
            usa,
        )

    def test_get_social_auth_rejects_case_insensitive_id_key_match(self):
        self.usa.id_key = "id"
        filtered = mock.Mock()
        filtered.filter.return_value = [self.usa]
        manager = mock.Mock()
        manager.select_related.return_value.filter.return_value = filtered

        with mock.patch.object(UserSocialAuth, "objects", manager):
            self.assertIsNone(
                UserSocialAuth.get_social_auth(
                    provider=self.usa.provider,
                    uid=self.usa.uid,
                    id_key="ID",
                )
            )

    def test_manager_rejects_case_insensitive_id_key_match(self):
        self.usa.id_key = "id"
        filtered = mock.Mock()
        filtered.filter.return_value = [self.usa]

        with mock.patch.object(
            UserSocialAuthManager,
            "select_related",
            return_value=mock.Mock(filter=mock.Mock(return_value=filtered)),
        ):
            self.assertIsNone(
                UserSocialAuth.objects.get_social_auth(
                    provider=self.usa.provider,
                    uid=self.usa.uid,
                    id_key="ID",
                )
            )

    def test_indexed_lookups_reject_case_insensitive_provider_matches(self):
        manager = mock.Mock()
        manager.select_related.return_value.filter.return_value = [self.usa]
        manager.filter.return_value = [self.usa]
        wrong_provider = self.usa.provider.upper()
        with mock.patch.object(UserSocialAuth, "objects", manager):
            self.assertIsNone(UserSocialAuth.get_social_auth(wrong_provider, self.usa.uid))
            # Exercise the storage mixin directly, bypassing the model override.
            self.assertIsNone(
                storage.DjangoUserMixin.get_social_auth.__func__(UserSocialAuth, wrong_provider, self.usa.uid)
            )
        with mock.patch.object(UserSocialAuthManager, "select_related", return_value=manager):
            self.assertIsNone(UserSocialAuth.objects.get_social_auth(wrong_provider, self.usa.uid))

    def test_get_social_auth_for_user(self):
        qs = UserSocialAuth.get_social_auth_for_user(user=self.user, provider=self.usa.provider, id=self.usa.id)
        self.assertEqual(qs.count(), 1)

    def test_create_social_auth(self):
        usa = UserSocialAuth.create_social_auth(user=self.user, provider="test", uid=1, id_key="id")
        self.assertEqual(usa.uid, "1")
        self.assertEqual(usa.id_key, "id")
        self.assertEqual(str(usa), str(self.user))

    def test_get_social_auth_by_extra_data(self):
        self.usa.extra_data = {"stable_id": "stable-user"}
        self.usa.save(update_fields=["extra_data"])

        self.assertEqual(
            UserSocialAuth.get_social_auth_by_extra_data(self.usa.provider, "stable_id", "stable-user"),
            self.usa,
        )

        UserSocialAuth.objects.create(
            user=self.user,
            provider=self.usa.provider,
            uid="another-legacy-id",
            extra_data={"stable_id": "stable-user"},
        )
        with self.assertRaisesRegex(ValueError, "Multiple social-auth"):
            UserSocialAuth.get_social_auth_by_extra_data(self.usa.provider, "stable_id", "stable-user")

    def test_get_social_auth_by_numeric_extra_data(self):
        self.usa.extra_data = {"stable_id": 1234}
        self.usa.save(update_fields=["extra_data"])

        self.assertEqual(
            UserSocialAuth.get_social_auth_by_extra_data(self.usa.provider, "stable_id", "1234"),
            self.usa,
        )

    def test_get_social_auth_by_extra_data_requires_present_key(self):
        self.assertIsNone(UserSocialAuth.get_social_auth_by_extra_data(self.usa.provider, "missing", None))
        self.assertIsNone(UserSocialAuth.get_social_auth_by_extra_data(self.usa.provider, "missing", "None"))

    def test_get_social_auth_by_extra_data_rejects_case_insensitive_id_key_match(self):
        self.usa.id_key = "id"
        self.usa.extra_data = {"stable_id": "stable-user"}
        manager = mock.Mock()
        manager.filter.return_value.annotate.return_value.filter.return_value = [self.usa]

        with mock.patch.object(UserSocialAuth, "_manager", return_value=manager):
            self.assertIsNone(
                UserSocialAuth.get_social_auth_by_extra_data(
                    self.usa.provider,
                    "stable_id",
                    "stable-user",
                    id_key="ID",
                )
            )

    def test_get_social_auth_by_extra_data_rejects_case_insensitive_provider_match(
        self,
    ):
        self.usa.extra_data = {"stable_id": "stable-user"}
        manager = mock.Mock()
        manager.filter.return_value.annotate.return_value.filter.return_value = [self.usa]

        with mock.patch.object(UserSocialAuth, "_manager", return_value=manager):
            self.assertIsNone(
                UserSocialAuth.get_social_auth_by_extra_data(
                    self.usa.provider.upper(),
                    "stable_id",
                    "stable-user",
                )
            )

    def test_migrate_social_auth(self):
        migrated = UserSocialAuth.migrate_social_auth(self.usa, "stable-user", "stable_id")

        self.assertEqual(migrated.uid, "stable-user")
        self.assertEqual(migrated.id_key, "stable_id")

    def test_migrate_social_auth_rejects_concurrent_change(self):
        UserSocialAuth.objects.filter(pk=self.usa.pk).update(uid="changed")

        with self.assertRaisesRegex(IntegrityError, "changed during"):
            UserSocialAuth.migrate_social_auth(self.usa, "stable-user", "stable_id")

    def test_migrate_social_auth_revalidates_identifier_evidence(self):
        self.usa.extra_data = {"stable_id": "stable-user"}
        self.usa.save(update_fields=["extra_data"])
        UserSocialAuth.objects.filter(pk=self.usa.pk).update(extra_data={"stable_id": "changed-user"})

        with self.assertRaisesRegex(IntegrityError, "identifier evidence changed"):
            UserSocialAuth.migrate_social_auth(self.usa, "stable-user", "stable_id")

    def test_migrate_social_auth_revalidates_aliased_evidence(self):
        self.usa.extra_data = {"id": "stable-user"}
        self.usa.save(update_fields=["extra_data"])
        migrated = UserSocialAuth.migrate_social_auth(self.usa, "stable-user", "sub", evidence_key="id")
        self.assertEqual((migrated.uid, migrated.id_key), ("stable-user", "sub"))

    def test_migrate_social_auth_requires_requested_evidence(self):
        for value in (None, True, "another-user"):
            with self.subTest(value=value):
                self.usa.extra_data = {"id": value}
                with self.assertRaisesRegex(IntegrityError, "identifier evidence changed"):
                    UserSocialAuth.migrate_social_auth(self.usa, "stable-user", "sub", evidence_key="id")

    def test_unverified_migration_rejects_concurrently_added_evidence(self):
        UserSocialAuth.objects.filter(pk=self.usa.pk).update(extra_data={"sub": "someone-else"})
        with self.assertRaisesRegex(IntegrityError, "identifier evidence changed"):
            UserSocialAuth.migrate_social_auth(self.usa, "stable-user", "sub")

    def test_migrate_social_auth_rejects_identifier_conflict(self):
        UserSocialAuth.objects.create(
            user=self.user,
            provider=self.usa.provider,
            uid="stable-user",
        )

        with self.assertRaisesRegex(IntegrityError, "migration conflict"):
            UserSocialAuth.migrate_social_auth(self.usa, "stable-user", "stable_id")

    @mock.patch("social_django.storage.transaction.atomic")
    @mock.patch("social_django.storage.router.db_for_write", return_value="primary")
    def test_migrate_social_auth_uses_write_database(self, db_for_write, atomic):
        manager = mock.Mock()
        manager.model = UserSocialAuth
        query = manager.using.return_value
        locked = query.select_for_update.return_value.get.return_value
        locked.uid = self.usa.uid
        locked.id_key = self.usa.id_key
        locked.extra_data = self.usa.extra_data
        locked.provider = self.usa.provider
        locked.pk = self.usa.pk
        query.filter.return_value.exclude.return_value.exists.return_value = False

        with mock.patch.object(UserSocialAuth, "_manager", return_value=manager):
            UserSocialAuth.migrate_social_auth(self.usa, "stable-user", "stable_id")

        db_for_write.assert_called_once_with(UserSocialAuth, instance=self.usa)
        manager.using.assert_called_once_with("primary")
        atomic.assert_called_once_with(using="primary")

    def test_username_max_length(self):
        self.assertEqual(UserSocialAuth.username_max_length(), 150)

    @isolate_apps()
    def test_uuid_username_max_length(self):
        class CustomUUIDField(models.UUIDField):
            pass

        class UUIDUser(models.Model):
            USERNAME_FIELD = "identifier"
            identifier = models.UUIDField(unique=True)
            custom_identifier = CustomUUIDField(unique=True)

            class Meta:
                app_label = "tests"

        with mock.patch.object(UserSocialAuth, "user_model", return_value=UUIDUser):
            for name in ("identifier", "custom_identifier"):
                with self.subTest(field=name), mock.patch.object(UUIDUser, "USERNAME_FIELD", name):
                    self.assertEqual(UserSocialAuth.username_max_length(), 36)

    @isolate_apps()
    def test_custom_char_username_max_length(self):
        class CustomUser(models.Model):
            USERNAME_FIELD = "identifier"
            identifier = models.CharField(max_length=42, unique=True)

            class Meta:
                app_label = "tests"

        with mock.patch.object(UserSocialAuth, "user_model", return_value=CustomUser):
            self.assertEqual(UserSocialAuth.username_max_length(), 42)

    @isolate_apps()
    def test_cognito_uuid_username(self):
        class UUIDUser(models.Model):
            USERNAME_FIELD = "identifier"
            identifier = models.UUIDField(unique=True)

            class Meta:
                app_label = "tests"

        identifier = UUID("01e5206c-5e37-4548-bf59-cffd34d0d296")
        strategy = DjangoStrategy(DjangoStorage)
        backend = CognitoOAuth2(strategy)
        field = UUIDUser._meta.get_field("identifier")
        with (
            mock.patch.object(UserSocialAuth, "user_model", return_value=UUIDUser),
            mock.patch.object(UserSocialAuth, "user_exists", return_value=False),
        ):
            for username in (str(identifier), identifier.hex):
                with self.subTest(username=username):
                    details = backend.get_user_details({"username": username})
                    result = get_username(strategy, details, backend)
                    self.assertEqual(result["username"], username)
                    self.assertEqual(field.to_python(result["username"]), identifier)


class TestNonce(TestCase):
    def test_use(self):
        self.assertEqual(Nonce.objects.count(), 0)
        self.assertTrue(Nonce.use(server_url="/", timestamp=1, salt="1"))
        self.assertFalse(Nonce.use(server_url="/", timestamp=1, salt="1"))
        self.assertEqual(Nonce.objects.count(), 1)


class TestAssociation(TestCase):
    def test_cleanup_expired(self):
        for handle, secret, issued, lifetime in (
            ("active-nonce", "", 1000, 1800),
            ("expired-nonce", "", 999, 1800),
            ("active-openid", "c2VjcmV0", 1000, 1801),
            ("expired-openid", "c2VjcmV0", 900, 1900),
            ("zero-lifetime", "", 3000, 0),
            ("negative-lifetime", "", 3000, -1),
            ("large-expiry", "c2VjcmV0", 2147483640, 3600),
        ):
            Association.objects.create(
                server_url="https://example.com",
                handle=handle,
                secret=secret,
                issued=issued,
                lifetime=lifetime,
                assoc_type="state",
            )
        with mock.patch("social_django.storage.time.time", return_value=2799):
            self.assertEqual(Association.cleanup_expired(), 3)
        self.assertEqual(Association.cleanup_expired(now=2800), 2)
        self.assertEqual(Association.cleanup_expired(now=2800), 0)
        self.assertEqual(
            set(Association.objects.values_list("handle", flat=True)),
            {"active-openid", "large-expiry"},
        )

    def test_clearsocial_uses_association_lifetime(self):
        for handle, lifetime in (("expired", 60), ("active", 1800)):
            Association.objects.create(
                server_url="https://example.com",
                handle=handle,
                secret="",
                issued=1000,
                lifetime=lifetime,
                assoc_type="state",
            )
        with mock.patch("social_django.storage.time.time", return_value=1060):
            call_command("clearsocial", age=30)
        self.assertEqual(list(Association.objects.values_list("handle", flat=True)), ["active"])

    def test_store_get_remove(self):
        Association.store(
            server_url="/",
            association=mock.Mock(handle="a", secret=b"b", issued=1, lifetime=2, assoc_type="c"),
        )

        qs = Association.get(handle="a")
        self.assertEqual(qs.count(), 1)
        self.assertEqual(qs[0].secret, "Yg==\n")

        Association.remove(ids_to_delete=[qs.first().id])
        self.assertEqual(Association.objects.count(), 0)


class TestCode(TestCase):
    def test_get_code(self):
        code1 = Code.objects.create(email="test@example.com", code="abc")
        code2 = Code.get_code(code="abc")
        self.assertEqual(code1, code2)
        self.assertIsNone(Code.get_code(code="xyz"))


class TestPartial(TestCase):
    def test_load_destroy(self):
        token_value = "x"  # ruff: ignore[hardcoded-password-string]
        p = Partial.objects.create(token=token_value, backend="y", data={})
        self.assertEqual(Partial.load(token=token_value), p)
        self.assertIsNone(Partial.load(token="y"))  # ruff: ignore[hardcoded-password-func-arg]

        Partial.destroy(token=token_value)
        self.assertEqual(Partial.objects.count(), 0)


class TestDjangoStorage(TestCase):
    def test_is_integrity_error(self):
        self.assertTrue(DjangoStorage.is_integrity_error(IntegrityError()))


class UserCreationIntegrityTest(TestCase):
    def test_unrelated_integrity_error_is_preserved(self):
        error = IntegrityError("Unrelated constraint")
        manager = get_user_model().objects
        with mock.patch.object(manager, "create_user", side_effect=error), self.assertRaises(IntegrityError) as caught:
            UserSocialAuth.create_user(username="new-user")
        self.assertIs(caught.exception, error)

    def test_unique_username_has_structured_reason(self):
        UserSocialAuth.create_user(username="existing-user")
        with self.assertRaises(AuthAssociationError) as caught:
            UserSocialAuth.create_user(username="existing-user")
        self.assertEqual(caught.exception.code, "username_in_use")
        self.assertEqual(caught.exception.stage, "pipeline")
        self.assertIsInstance(caught.exception.__cause__, IntegrityError)

    def test_unrelated_unique_constraint_is_preserved(self):
        UserSocialAuth.create_user(username="existing-user")
        cause = sqlite3.IntegrityError("UNIQUE constraint failed: auth_user.other_field")
        cause.sqlite_errorcode = SQLITE_UNIQUE_ERROR_CODE
        error = IntegrityError("Unrelated uniqueness failure")
        error.__cause__ = cause
        with (
            mock.patch.object(get_user_model().objects, "create_user", side_effect=error),
            self.assertRaises(IntegrityError) as caught,
        ):
            UserSocialAuth.create_user(username="existing-user")
        self.assertIs(caught.exception, error)

    def test_positional_username_conflict(self):
        UserSocialAuth.create_user("existing-user")
        with self.assertRaises(AuthAssociationError) as caught:
            UserSocialAuth.create_user("existing-user")
        self.assertEqual(caught.exception.code, "username_in_use")

    def test_sqlite_without_extended_error_code(self):
        cause = sqlite3.IntegrityError("UNIQUE constraint failed: auth_user.username")
        self.assertFalse(hasattr(cause, "sqlite_errorcode"))
        error = IntegrityError("Username uniqueness failure")
        error.__cause__ = cause
        with (
            mock.patch.object(get_user_model().objects, "create_user", side_effect=error),
            self.assertRaises(AuthAssociationError) as caught,
        ):
            UserSocialAuth.create_user("existing-user")
        self.assertEqual(caught.exception.code, "username_in_use")

    def test_import_without_python_311_sqlite_constant(self):
        with mock.patch.dict(sqlite3.__dict__):
            sqlite3.__dict__.pop("SQLITE_CONSTRAINT_UNIQUE", None)
            sqlite3.__dict__.pop("SQLITE_CONSTRAINT_PRIMARYKEY", None)
            namespace = runpy.run_path(storage.__file__)
        self.assertEqual(namespace["SQLITE_UNIQUE_ERROR_CODE"], 2067)
        self.assertEqual(namespace["SQLITE_PRIMARY_KEY_ERROR_CODE"], 1555)

    @isolate_apps()
    def test_sqlite_primary_key_identifiers(self):
        class UsernamePrimaryKeyUser(models.Model):
            USERNAME_FIELD = "username"
            username = models.CharField(max_length=150, primary_key=True)

            class Meta:
                app_label = "tests"
                db_table = "primary_identifier"

        class EmailPrimaryKeyUser(models.Model):
            USERNAME_FIELD = "email"
            EMAIL_FIELD = "address"
            email = models.CharField(max_length=150)
            address = models.EmailField(primary_key=True)

            class Meta:
                app_label = "tests"
                db_table = "primary_identifier"

        for model, field, code in (
            (UsernamePrimaryKeyUser, "username", "username_in_use"),
            (EmailPrimaryKeyUser, "address", "email_in_use"),
        ):
            with self.subTest(field=field):
                database = sqlite3.connect(":memory:")
                try:
                    database.execute(f"CREATE TABLE primary_identifier ({field} TEXT PRIMARY KEY)")
                    database.execute("INSERT INTO primary_identifier VALUES ('existing')")
                    with self.assertRaises(sqlite3.IntegrityError) as caught:
                        database.execute("INSERT INTO primary_identifier VALUES ('existing')")
                finally:
                    database.close()
                cause = caught.exception
                self.assertEqual(getattr(cause, "sqlite_errorcode", SQLITE_PRIMARY_KEY_ERROR_CODE), 1555)
                error = IntegrityError("Primary key uniqueness failure")
                error.__cause__ = cause
                with (
                    mock.patch.object(UserSocialAuth, "user_model", return_value=model),
                    mock.patch.object(model.objects, "create_user", side_effect=error, create=True),
                    self.assertRaises(AuthAssociationError) as caught,
                ):
                    UserSocialAuth.create_user("existing")
                self.assertEqual(caught.exception.code, code)
                self.assertIs(caught.exception.__cause__, error)

                cause = sqlite3.IntegrityError("UNIQUE constraint failed: primary_identifier.other_field")
                cause.sqlite_errorcode = SQLITE_PRIMARY_KEY_ERROR_CODE
                error.__cause__ = cause
                with (
                    mock.patch.object(UserSocialAuth, "user_model", return_value=model),
                    mock.patch.object(model.objects, "create_user", side_effect=error, create=True),
                    self.assertRaises(IntegrityError) as caught,
                ):
                    UserSocialAuth.create_user("existing")
                self.assertIs(caught.exception, error)

    def test_common_named_username_constraint_is_recognized_without_introspection(self):
        for diagnostic in (
            SimpleNamespace(sqlstate="23505", diag=SimpleNamespace(constraint_name="auth_user_username_key")),
            SimpleNamespace(pgcode="23505", diag=SimpleNamespace(constraint_name="auth_user_username_key")),
            Exception(1062, "Duplicate entry 'private-value' for key 'username'"),
            Exception(1062, "Duplicate entry 'private-value' for key 'auth_user.username'"),
        ):
            error = IntegrityError("Username conflict")
            # Exception chaining requires an exception, including for structured diagnostics.
            if not isinstance(diagnostic, Exception):
                wrapped = Exception("Duplicate identifier")
                wrapped.__dict__.update(vars(diagnostic))
                cause = wrapped
            else:
                cause = diagnostic
            error.__cause__ = cause
            with (
                self.subTest(cause=cause),
                mock.patch.object(get_user_model().objects, "create_user", side_effect=error),
                self.assertRaises(AuthAssociationError) as caught,
            ):
                UserSocialAuth.create_user("existing")
            self.assertEqual(caught.exception.code, "username_in_use")
            self.assertIs(caught.exception.__cause__, error)
            self.assertNotIn("private-value", str(caught.exception))

    @isolate_apps()
    def test_explicit_single_field_constraint_names(self):
        class IdentifierUser(models.Model):
            USERNAME_FIELD = "username"
            username = models.CharField(max_length=150)
            email = models.EmailField()
            other = models.CharField(max_length=150)

            class Meta:
                app_label = "tests"
                constraints: ClassVar[list[models.BaseConstraint]] = [
                    models.UniqueConstraint(fields=["username"], name="unique_username"),
                    models.UniqueConstraint(fields=["email"], name="unique_email"),
                    models.UniqueConstraint(fields=["other"], name="unrelated"),
                    models.UniqueConstraint(fields=["username", "email"], name="composite"),
                ]

        for name, code in (
            ("unique_username", "username_in_use"),
            ("unique_email", "email_in_use"),
            ("unrelated", None),
            ("composite", None),
        ):
            error = IntegrityError("Unique constraint")
            cause = Exception("Duplicate identifier")
            cause.sqlstate = "23505"
            cause.diag = SimpleNamespace(constraint_name=name)
            error.__cause__ = cause
            family = AuthAssociationError if code is not None else IntegrityError
            with (
                self.subTest(name=name),
                mock.patch.object(UserSocialAuth, "user_model", return_value=IdentifierUser),
                mock.patch.object(IdentifierUser.objects, "create_user", side_effect=error, create=True),
                self.assertRaises(family) as caught,
            ):
                UserSocialAuth.create_user("existing")
            if code is not None:
                self.assertEqual(caught.exception.code, code)
            else:
                self.assertIs(caught.exception, error)

    def test_unrecognized_diagnostics_propagate_without_introspection(self):
        causes = [
            sqlite3.IntegrityError("UNIQUE constraint failed: index 'unique_lower_email'"),
            Exception(SimpleNamespace(code=1, message="ORA-00001: unique constraint (AUTH.EMAIL) violated")),
            Exception(1062, "Unknown duplicate diagnostic"),
            Exception(1048, "Column cannot be null"),
        ]
        for sqlstate, name in (("23505", "unknown_constraint"), ("23503", "auth_user_username_key")):
            cause = Exception("Storage failure")
            cause.sqlstate = sqlstate
            cause.diag = SimpleNamespace(constraint_name=name)
            causes.append(cause)
        for cause in causes:
            error = IntegrityError("Unrecognized constraint")
            error.__cause__ = cause
            with (
                self.subTest(cause=cause),
                mock.patch.object(get_user_model().objects, "create_user", side_effect=error),
                self.assertRaises(IntegrityError) as caught,
            ):
                UserSocialAuth.create_user("existing")
            self.assertIs(caught.exception, error)

    @isolate_apps()
    def test_inherited_identifier_conflicts_use_parent_table(self):
        class ParentUser(models.Model):
            USERNAME_FIELD = "username"
            username = models.CharField(max_length=150, unique=True)
            email = models.EmailField(unique=True)

            class Meta:
                app_label = "tests"

        class ChildUser(ParentUser):
            extra = models.CharField(max_length=150)

            class Meta:
                app_label = "tests"

        for field, code in (("username", "username_in_use"), ("email", "email_in_use")):
            for vendor in ("sqlite", "postgresql", "mysql"):
                if vendor == "sqlite":
                    cause = sqlite3.IntegrityError(f"UNIQUE constraint failed: tests_parentuser.{field}")
                elif vendor == "postgresql":
                    cause = Exception("Duplicate identifier")
                    cause.sqlstate = "23505"
                    cause.diag = SimpleNamespace(constraint_name=f"tests_parentuser_{field}_key")
                else:
                    cause = Exception(1062, f"Duplicate entry 'existing' for key '{field}'")
                error = IntegrityError("Inherited identifier conflict")
                error.__cause__ = cause
                with (
                    self.subTest(field=field, vendor=vendor),
                    mock.patch.object(UserSocialAuth, "user_model", return_value=ChildUser),
                    mock.patch.object(ChildUser.objects, "create_user", side_effect=error, create=True),
                    self.assertRaises(AuthAssociationError) as caught,
                ):
                    UserSocialAuth.create_user("existing")
                self.assertEqual(caught.exception.code, code)

    def test_migration_generated_constraint_names_need_no_database_queries(self):
        field = get_user_model()._meta.get_field("username")
        statement = connection.schema_editor()._create_unique_sql(field.model, [field])
        name = str(statement.parts["name"]).strip('"`')
        self.assertTrue(name.endswith("_uniq"))
        for vendor in ("postgresql", "mysql"):
            if vendor == "postgresql":
                cause = Exception("Duplicate identifier")
                cause.sqlstate = "23505"
                cause.diag = SimpleNamespace(constraint_name=name)
            else:
                cause = Exception(1062, f"Duplicate entry 'private-value' for key '{name}'")
            error = IntegrityError("Identifier conflict")
            error.__cause__ = cause
            with self.subTest(vendor=vendor), self.assertNumQueries(0):
                self.assertEqual(UserSocialAuth._user_creation_conflict(error), "username_in_use")

    @isolate_apps()
    def test_single_identifier_unique_together_needs_no_database_queries(self):
        class TogetherUser(models.Model):
            USERNAME_FIELD = "username"
            username = models.CharField(max_length=150)
            email = models.EmailField()
            other = models.CharField(max_length=150)

            class Meta:
                app_label = "tests"
                unique_together = (("username",), ("email",), ("username", "other"))

        for fields, code in (
            (("username",), "username_in_use"),
            (("email",), "email_in_use"),
            (("username", "other"), None),
        ):
            columns = [TogetherUser._meta.get_field(field) for field in fields]
            statement = connection.schema_editor()._create_unique_sql(TogetherUser, columns)
            name = str(statement.parts["name"]).strip('"`')
            for vendor in ("postgresql", "mysql"):
                if vendor == "postgresql":
                    cause = Exception("Duplicate identifier")
                    cause.sqlstate = "23505"
                    cause.diag = SimpleNamespace(constraint_name=name)
                else:
                    cause = Exception(1062, f"Duplicate entry 'private-value' for key '{name}'")
                error = IntegrityError("Identifier conflict")
                error.__cause__ = cause
                with (
                    self.subTest(fields=fields, vendor=vendor),
                    mock.patch.object(UserSocialAuth, "user_model", return_value=TogetherUser),
                    self.assertNumQueries(0),
                ):
                    self.assertEqual(UserSocialAuth._user_creation_conflict(error), code)
        # unique_together does not create inline field constraints.
        field = TogetherUser._meta.get_field("username")
        self.assertNotIn("username", UserSocialAuth._identifier_constraint_names(field, "mysql"))
        self.assertNotIn(
            f"{TogetherUser._meta.db_table}_username_key",
            UserSocialAuth._identifier_constraint_names(field, "postgresql"),
        )

    @isolate_apps()
    def test_mysql_primary_key_is_recognized_only_for_identifier_fields(self):
        class PrimaryUsernameUser(models.Model):
            USERNAME_FIELD = "username"
            username = models.CharField(max_length=150, primary_key=True)

            class Meta:
                app_label = "tests"

        class PrimaryEmailUser(models.Model):
            USERNAME_FIELD = "username"
            username = models.CharField(max_length=150)
            email = models.EmailField(primary_key=True)

            class Meta:
                app_label = "tests"

        for model, code in (
            (PrimaryUsernameUser, "username_in_use"),
            (PrimaryEmailUser, "email_in_use"),
            (get_user_model(), None),
        ):
            error = IntegrityError("Primary key conflict")
            error.__cause__ = Exception(1062, "Duplicate entry 'private-value' for key 'PRIMARY'")
            family = IntegrityError if code is None else AuthAssociationError
            with (
                self.subTest(model=model),
                mock.patch.object(UserSocialAuth, "user_model", return_value=model),
                mock.patch.object(model.objects, "create_user", side_effect=error, create=True),
                self.assertRaises(family) as caught,
            ):
                UserSocialAuth.create_user("existing")
            if code is None:
                self.assertIs(caught.exception, error)
            else:
                self.assertEqual(caught.exception.code, code)

    @isolate_apps()
    def test_explicit_unrelated_constraint_does_not_match_identifier_defaults(self):
        class ConstraintUser(models.Model):
            USERNAME_FIELD = "username"
            username = models.CharField(max_length=150, unique=True)
            email = models.EmailField(unique=True)
            other = models.CharField(max_length=150)

            class Meta:
                app_label = "tests"
                constraints: ClassVar[list[models.BaseConstraint]] = [
                    models.UniqueConstraint(fields=["other"], name="username"),
                    models.UniqueConstraint(fields=["other"], name="email"),
                ]

        for vendor in ("postgresql", "mysql"):
            for name in ("username", "email"):
                error = IntegrityError("Unrelated conflict")
                if vendor == "postgresql":
                    cause = Exception("Duplicate unrelated field")
                    cause.sqlstate = "23505"
                    cause.diag = SimpleNamespace(constraint_name=name)
                else:
                    cause = Exception(1062, f"Duplicate entry 'private-value' for key '{name}'")
                error.__cause__ = cause
                with (
                    self.subTest(vendor=vendor, name=name),
                    mock.patch.object(UserSocialAuth, "user_model", return_value=ConstraintUser),
                    mock.patch.object(ConstraintUser.objects, "create_user", side_effect=error, create=True),
                    self.assertRaises(IntegrityError) as caught,
                ):
                    UserSocialAuth.create_user("existing")
                self.assertIs(caught.exception, error)

    def test_postgresql_bare_column_names_are_not_inferred_to_be_identifiers(self):
        for name in ("username", "email"):
            error = IntegrityError("Unknown constraint")
            cause = Exception("Duplicate unrelated field")
            cause.sqlstate = "23505"
            cause.diag = SimpleNamespace(constraint_name=name)
            error.__cause__ = cause
            with (
                self.subTest(name=name),
                mock.patch.object(get_user_model().objects, "create_user", side_effect=error),
                self.assertRaises(IntegrityError) as caught,
            ):
                UserSocialAuth.create_user("existing")
            self.assertIs(caught.exception, error)
