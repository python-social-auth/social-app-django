from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import IntegrityError
from django.test import TestCase, override_settings
from social_core.exceptions import AuthAlreadyAssociated

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


class TestSocialAuthUser(TestCase):
    def test_user_relationship_none(self):
        """Accessing User.social_user outside of the pipeline doesn't work"""
        User = get_user_model()  # noqa: N806
        user = User._default_manager.create_user(username="randomtester")  # noqa: SLF001
        with self.assertRaises(AttributeError):
            user.social_user  # noqa: B018

    def test_user_existing_relationship(self):
        """Accessing User.social_user outside of the pipeline doesn't work"""
        User = get_user_model()  # noqa: N806
        user = User._default_manager.create_user(username="randomtester")  # noqa: SLF001
        UserSocialAuth.objects.create(user=user, provider="my-provider", uid="1234")
        with self.assertRaises(AttributeError):
            user.social_user  # noqa: B018

    def test_get_social_auth(self):
        User = get_user_model()  # noqa: N806
        user = User._default_manager.create_user(username="randomtester")  # noqa: SLF001
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
        self.user = self.user_model._default_manager.create_user(username="randomtester", email="user@example.com")  # noqa: SLF001
        self.usa = UserSocialAuth.objects.create(user=self.user, provider="my-provider", uid="1234")

    def test_changed(self):
        self.user.email = eml = "test@example.com"
        UserSocialAuth.changed(user=self.user)
        db_eml = self.user_model._default_manager.get(username=self.user.username).email  # noqa: SLF001
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
        with self.assertRaises(AuthAlreadyAssociated):
            UserSocialAuth.create_user(username=self.user.username, email=None)

    @mock.patch("social_django.models.UserSocialAuth.username_field", return_value="email")
    @mock.patch("django.contrib.auth.models.UserManager.create_user", return_value="<User>")
    def test_create_user_custom_username(self, *args):
        UserSocialAuth.create_user(username=self.user.email)

    @mock.patch("django.contrib.auth.models.UserManager.create_user", side_effect=IntegrityError)
    def test_create_user_existing(self, *args):
        with self.assertRaises(AuthAlreadyAssociated):
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


class TestNonce(TestCase):
    def test_use(self):
        self.assertEqual(Nonce.objects.count(), 0)
        self.assertTrue(Nonce.use(server_url="/", timestamp=1, salt="1"))
        self.assertFalse(Nonce.use(server_url="/", timestamp=1, salt="1"))
        self.assertEqual(Nonce.objects.count(), 1)


class TestAssociation(TestCase):
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
        token_value = "x"  # noqa: S105
        p = Partial.objects.create(token=token_value, backend="y", data={})
        self.assertEqual(Partial.load(token=token_value), p)
        self.assertIsNone(Partial.load(token="y"))  # noqa: S106

        Partial.destroy(token=token_value)
        self.assertEqual(Partial.objects.count(), 0)


class TestDjangoStorage(TestCase):
    def test_is_integrity_error(self):
        self.assertTrue(DjangoStorage.is_integrity_error(IntegrityError()))
