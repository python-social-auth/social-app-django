from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from social_core.backends.base import BaseAuth
from social_core.backends.utils import load_backends

from social_django.context_processors import backends, login_redirect


@override_settings(REDIRECT_FIELD_NAME="next")
class TestContextProcessors(TestCase):
    def setUp(self):
        self.request_factory = RequestFactory()

    def test_login_redirect_unicode_quote(self):
        request = self.request_factory.get("/", data={"next": "profile/sjó"})
        result = login_redirect(request)
        self.assertEqual(
            result,
            {
                "REDIRECT_FIELD_NAME": "next",
                "REDIRECT_FIELD_VALUE": "profile/sj%C3%B3",
                "REDIRECT_QUERYSTRING": "next=profile/sj%C3%B3",
            },
        )

    def test_login_redirect_malformed_post(self):
        request = self.request_factory.post("/", data="no boundary", content_type="multipart/form-data")
        result = login_redirect(request)
        self.assertEqual(
            result,
            {
                "REDIRECT_FIELD_NAME": "next",
                "REDIRECT_FIELD_VALUE": None,
                "REDIRECT_QUERYSTRING": "",
            },
        )


class CustomAuth(BaseAuth):
    name = "custom"


@override_settings(
    AUTHENTICATION_BACKENDS=[
        "social_core.backends.github_enterprise.GithubEnterpriseOrganizationOAuth2",
        "social_core.backends.openinfra.OpenInfraOpenId",
        "tests.test_context_processors.CustomAuth",
        "django.contrib.auth.backends.ModelBackend",
    ]
)
class TestBackendMetadata(SimpleTestCase):
    def setUp(self):
        load_backends([], force_load=True)
        self.addCleanup(load_backends, [], force_load=True)
        self.request = RequestFactory().get("/")
        self.request.user = AnonymousUser()

    def test_metadata_preserves_backend_lists(self):
        data = backends(self.request)["backends"]
        self.assertEqual(data["backends"], ["github-enterprise-org", "openinfra", "custom"])
        self.assertEqual(data["not_associated"], data["backends"])
        self.assertEqual(data["associated"], [])
        self.assertEqual(
            data["metadata"]["github-enterprise-org"],
            {
                "title": "GitHub Enterprise Organization",
                "icon": "social_auth/icons/github.svg",
            },
        )
        self.assertEqual(data["metadata"]["openinfra"], {"title": "OpenInfraID", "icon": None})
        self.assertEqual(data["metadata"]["custom"], {"title": "custom", "icon": None})

    def test_authenticated_associations_are_preserved(self):
        self.request.user = SimpleNamespace(is_authenticated=True)
        association = SimpleNamespace(provider="github-enterprise-org")
        with patch(
            "social_django.context_processors.Storage.user.get_social_auth_for_user", return_value=[association]
        ):
            data = backends(self.request)["backends"]
            self.assertEqual(data["associated"], [association])
            self.assertCountEqual(data["not_associated"], ["openinfra", "custom"])
            self.assertIn("github-enterprise-org", data["metadata"])
