"""Name normalization through the default core pipeline and Django storage."""

from django.test import TestCase, override_settings
from social_core.backends.base import BaseAuth
from social_core.pipeline import DEFAULT_AUTH_PIPELINE

from social_django.models import DjangoStorage
from social_django.strategy import DjangoStrategy


class NameAuth(BaseAuth):
    name = "names"
    ID_KEY = "id"

    def get_user_details(self, response):
        return {key: value for key, value in response.items() if key != "id"}


class TestNames(TestCase):
    def setUp(self):
        self.strategy = DjangoStrategy(DjangoStorage)
        self.backend = NameAuth(self.strategy)

    def login(self, username="name-user", **names):
        return self.backend.pipeline(
            self.strategy.get_pipeline(self.backend),
            response={"id": username, "username": username, **names},
        )

    def test_full_name_is_persisted_on_creation_and_login(self):
        user = self.login(fullname="Mary Jane Watson")
        user.refresh_from_db()
        self.assertEqual((user.first_name, user.last_name), ("Mary", "Jane Watson"))
        returning_user = self.login(fullname="Mary Parker")
        returning_user.refresh_from_db()
        self.assertEqual(returning_user.pk, user.pk)
        self.assertEqual((returning_user.first_name, returning_user.last_name), ("Mary", "Parker"))

    def test_single_name(self):
        user = self.login(fullname="Prince")
        user.refresh_from_db()
        self.assertEqual((user.first_name, user.last_name), ("Prince", ""))

    def test_component_names_are_preserved(self):
        user = self.login(fullname="Display Name", first_name="Given", last_name="Surname")
        user.refresh_from_db()
        self.assertEqual((user.first_name, user.last_name), ("Given", "Surname"))

    def test_missing_names_do_not_clear_existing_names(self):
        user = self.login(first_name="Ada", last_name="Lovelace")
        self.login(fullname=None, first_name=None, last_name=None)
        user.refresh_from_db()
        self.assertEqual((user.first_name, user.last_name), ("Ada", "Lovelace"))

    def test_protected_name(self):
        user = self.login(first_name="Chosen")
        with override_settings(SOCIAL_AUTH_PROTECTED_USER_FIELDS=["first_name"]):
            self.login(fullname="Provider Surname")
        user.refresh_from_db()
        self.assertEqual((user.first_name, user.last_name), ("Chosen", "Surname"))

    @override_settings(SOCIAL_AUTH_IMMUTABLE_USER_FIELDS=["first_name", "last_name"])
    def test_immutable_names_are_populated_once(self):
        user = self.login(fullname="Ada Lovelace")
        self.login(fullname="Grace Hopper")
        user.refresh_from_db()
        self.assertEqual((user.first_name, user.last_name), ("Ada", "Lovelace"))

    @override_settings(SOCIAL_AUTH_NAMES_FIRSTLAST_FROM_FULL=False)
    def test_backend_can_disable_splitting(self):
        user = self.login(fullname="Ada Lovelace")
        user.refresh_from_db()
        self.assertEqual((user.first_name, user.last_name), ("", ""))

    @override_settings(
        SOCIAL_AUTH_PIPELINE=[step for step in DEFAULT_AUTH_PIPELINE if not step.endswith(".social_names")]
    )
    def test_custom_pipeline_can_omit_normalization(self):
        user = self.login(fullname="Ada Lovelace")
        user.refresh_from_db()
        self.assertEqual((user.first_name, user.last_name), ("", ""))
