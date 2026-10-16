from importlib.util import find_spec
from types import SimpleNamespace
from unittest import skipUnless
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
        self.request.session = {}
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

    def test_older_core_metadata_fallback(self) -> None:
        with patch.object(BaseAuth, "get_title", None, create=True):
            data = backends(self.request)["backends"]
            self.assertEqual(data["metadata"]["custom"]["title"], "custom")
            self.assertEqual(data["metadata"]["openinfra"]["title"], "OpenInfraID")

    @skipUnless(find_spec("social_core.backends.weblate"), "Weblate requires a newer social-auth-core")
    @override_settings(AUTHENTICATION_BACKENDS=["social_core.backends.weblate.WeblateOpenIdConnect"])
    def test_weblate_titles_without_network(self) -> None:
        with patch(
            "social_core.backends.weblate.WeblateOpenIdConnect.request",
            side_effect=AssertionError("Unexpected provider request"),
        ):
            for endpoint, title in (
                ("https://hosted.weblate.org/oidc", "Hosted Weblate"),
                ("https://weblate.example.com/prefix/oidc/", "Weblate"),
            ):
                with self.subTest(endpoint=endpoint), override_settings(SOCIAL_AUTH_WEBLATE_OIDC_ENDPOINT=endpoint):
                    data = backends(self.request)["backends"]
                    self.assertEqual(
                        data["metadata"]["weblate"],
                        {"title": title, "icon": "social_auth/icons/weblate.svg"},
                    )

    @skipUnless(find_spec("social_core.backends.weblate"), "Weblate requires a newer social-auth-core")
    @override_settings(AUTHENTICATION_BACKENDS=["social_core.backends.weblate.WeblateOpenIdConnect"])
    def test_weblate_default_title(self) -> None:
        data = backends(self.request)["backends"]
        self.assertEqual(data["metadata"]["weblate"]["title"], "Hosted Weblate")
