from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from social_django.models import UserSocialAuth


class SocialAdminTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()  # noqa: N806
        User._default_manager.create_superuser(  # noqa: SLF001
            username="admin",
            email="admin@test.com",
            first_name="Admin",
            password="super-duper-test",  # noqa: S106
        )

    def test_admin_app_name(self):
        """The App name in the admin index page"""
        self.client.login(
            username="admin",
            password="super-duper-test",  # noqa: S106
        )
        response = self.client.get(reverse("admin:index"))
        self.assertContains(response, "Python Social Auth")

    def test_social_auth_changelist(self):
        """The App name in the admin index page"""
        self.client.login(
            username="admin",
            password="super-duper-test",  # noqa: S106
        )
        meta = UserSocialAuth._meta  # noqa: SLF001
        url_name = f"admin:{meta.app_label}_{meta.model_name}_changelist"
        self.client.get(reverse(url_name))
