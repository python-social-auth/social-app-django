from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.sessions.middleware import SessionMiddleware
from django.db import models
from django.test import RequestFactory, TestCase, override_settings
from django.test.utils import isolate_apps
from social_core.backends.keycloak import KeycloakOAuth2
from social_core.backends.mediawiki import MediaWiki
from social_core.exceptions import AuthConfigurationError

from social_django.utils import load_strategy


class GroupSyncTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="user")
        request = RequestFactory().get("/")
        SessionMiddleware(lambda _request: None).process_request(request)
        self.strategy = load_strategy(request=request)
        self.backend = KeycloakOAuth2(self.strategy)
        self.a = Group.objects.create(name="A")
        self.b = Group.objects.create(name="B")
        self.unrelated = Group.objects.create(name="Unrelated")

    @override_settings(SOCIAL_AUTH_KEYCLOAK_GROUPS_MAP={"a": ["A"], "b": ["B"]})
    def test_sync_preserves_unrelated_groups_and_is_idempotent(self):
        self.user.groups.add(self.b, self.unrelated)
        self.user.__dict__["_perm_cache"] = {"old.permission"}
        for _ in range(2):
            self.strategy.sync_user_groups(self.user, ["a", "unknown"], backend=self.backend, response={})
            self.assertEqual(set(self.user.groups.values_list("name", flat=True)), {"A", "Unrelated"})
        self.assertFalse(hasattr(self.user, "_perm_cache"))
        self.strategy.sync_user_groups(self.user, [], backend=self.backend, response={})
        self.assertEqual(list(self.user.groups.all()), [self.unrelated])

    @override_settings(SOCIAL_AUTH_KEYCLOAK_GROUPS_MAP={"a": ["A"], "b": ["B"]})
    def test_replica_loaded_user_updates_memberships_on_write_database(self):
        self.user.groups.add(self.b, self.unrelated)
        with (
            patch.object(self.user._state, "db", "replica"),  # noqa: SLF001
            patch("social_django.strategy.router.db_for_read", return_value="replica"),
            patch("social_django.strategy.router.db_for_write", return_value="default"),
        ):
            self.strategy.sync_user_groups(self.user, ["a"], backend=self.backend, response={})
            self.assertEqual(set(self.user.groups.using("default").values_list("name", flat=True)), {"A", "Unrelated"})
            self.strategy.sync_user_groups(self.user, [], backend=self.backend, response={})
            self.assertEqual(list(self.user.groups.using("default").all()), [self.unrelated])

    @override_settings(SOCIAL_AUTH_KEYCLOAK_GROUPS_MAP={"a": ["A"], "b": ["Missing"]})
    def test_missing_target_does_not_modify_memberships(self):
        self.user.groups.add(self.a)
        with self.assertRaises(AuthConfigurationError):
            self.strategy.sync_user_groups(self.user, [], backend=self.backend, response={})
        self.assertEqual(list(self.user.groups.all()), [self.a])

    @override_settings(SOCIAL_AUTH_KEYCLOAK_GROUPS_MAP={"a": [1]})
    def test_integer_targets_are_rejected_without_modifying_memberships(self):
        self.user.groups.add(self.a)
        with self.assertRaises(AuthConfigurationError) as caught:
            self.strategy.sync_user_groups(self.user, ["a"], backend=self.backend, response={})
        self.assertEqual(caught.exception.code, "invalid_setting")
        self.assertEqual(caught.exception.parameter, "GROUPS_MAP")
        self.assertEqual(list(self.user.groups.all()), [self.a])

    @override_settings(SOCIAL_AUTH_KEYCLOAK_GROUPS_MAP={"a": ["A"]})
    def test_unsupported_user_group_models_are_rejected(self):
        for user in (SimpleNamespace(), SimpleNamespace(groups=SimpleNamespace(model=object))):
            with self.subTest(user=user), self.assertRaises(AuthConfigurationError) as caught:
                self.strategy.sync_user_groups(user, ["a"], backend=self.backend, response={})
            self.assertEqual(caught.exception.code, "invalid_setting")
            self.assertEqual(caught.exception.parameter, "GROUPS_MAP")

    @isolate_apps()
    @override_settings(SOCIAL_AUTH_KEYCLOAK_GROUPS_MAP={"a": ["A"]})
    def test_custom_intermediary_is_rejected_before_membership_changes(self):
        class Membership(models.Model):
            user = models.ForeignKey(get_user_model(), on_delete=models.CASCADE)
            group = models.ForeignKey(Group, on_delete=models.CASCADE)
            metadata = models.CharField(max_length=100)

            class Meta:
                app_label = "tests"

        self.user.groups.add(self.a, self.unrelated)
        relation = self.user._meta.get_field("groups").remote_field  # noqa: SLF001
        with (
            patch.object(relation, "through", Membership),
            self.assertNumQueries(0),
            self.assertRaises(AuthConfigurationError) as caught,
        ):
            self.strategy.sync_user_groups(self.user, [], backend=self.backend, response={})
        self.assertEqual(caught.exception.code, "invalid_setting")
        self.assertEqual(caught.exception.parameter, "GROUPS_MAP")
        self.assertEqual(set(self.user.groups.values_list("name", flat=True)), {"A", "Unrelated"})

    @override_settings(SOCIAL_AUTH_KEYCLOAK_GROUPS_MAP={"a": ["A"], "b": ["B"]})
    def test_failed_addition_rolls_back_membership_removals(self):
        self.user.groups.add(self.b, self.unrelated)
        with (
            patch.object(type(self.user.groups), "add", side_effect=RuntimeError("write failed")),
            self.assertRaisesRegex(RuntimeError, "write failed"),
        ):
            self.strategy.sync_user_groups(self.user, ["a"], backend=self.backend, response={})
        self.assertEqual(set(self.user.groups.values_list("name", flat=True)), {"B", "Unrelated"})

    @override_settings(SOCIAL_AUTH_KEYCLOAK_GROUPS_MAP={"a": ["A"]})
    def test_disabled_extraction_with_mapping_fails(self):
        with self.assertRaises(AuthConfigurationError):
            self.strategy.sync_user_groups(self.user, None, backend=self.backend, response={})

    def test_unconfigured_sync_does_nothing(self):
        self.user.groups.add(self.a)
        self.strategy.sync_user_groups(self.user, None, backend=self.backend, response={})
        self.assertEqual(list(self.user.groups.all()), [self.a])

    @override_settings(
        AUTHENTICATION_BACKENDS=("social_core.backends.mediawiki.MediaWiki",),
        SOCIAL_AUTH_MEDIAWIKI_KEY="key",
        SOCIAL_AUTH_MEDIAWIKI_SECRET="secret",  # noqa: S106
        SOCIAL_AUTH_MEDIAWIKI_URL="https://example.com/wiki",
    )
    def test_mediawiki_default_login_does_not_assign_many_to_many_details(self):
        backend = MediaWiki(self.strategy)
        identity = {
            "iss": "https://example.com/wiki",
            "iat": 0,
            "nonce": "nonce",
            "username": "wikiuser",
            "sub": "wiki-id",
            "groups": ["sysop"],
        }
        response = SimpleNamespace(
            content=b"identity", request=SimpleNamespace(headers={"Authorization": 'oauth_nonce="nonce"'})
        )
        with (
            patch.object(backend, "request", return_value=response) as request,
            patch("social_core.backends.mediawiki.jwt.decode", return_value=identity),
        ):
            user = backend.do_auth({"oauth_token": "token", "oauth_token_secret": "secret"})
        self.assertEqual(user.username, "wikiuser")
        self.assertFalse(user.groups.exists())
        request.assert_called_once()
