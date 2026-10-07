from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from social_django.models import UserSocialAuth


class SocialAdminTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()  # ruff: ignore[non-lowercase-variable-in-function]
        User._default_manager.create_superuser(
            username="admin",
            email="admin@test.com",
            first_name="Admin",
            password="super-duper-test",  # ruff: ignore[hardcoded-password-func-arg]
        )

    def test_admin_app_name(self):
        """The App name in the admin index page"""
        self.client.login(
            username="admin",
            password="super-duper-test",  # ruff: ignore[hardcoded-password-func-arg]
        )
        response = self.client.get(reverse("admin:index"))
        self.assertContains(response, "Python Social Auth")

    def test_social_auth_changelist(self):
        """The App name in the admin index page"""
        self.client.login(
            username="admin",
            password="super-duper-test",  # ruff: ignore[hardcoded-password-func-arg]
        )
        meta = UserSocialAuth._meta
        url_name = f"admin:{meta.app_label}_{meta.model_name}_changelist"
        self.client.get(reverse(url_name))
