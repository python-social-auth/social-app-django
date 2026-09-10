from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractBaseUser
from django.test import TestCase, override_settings
from django.urls import reverse
from social_core.backends.open_id_connect import OpenIdConnectAuth

from social_django.models import UserSocialAuth
from social_django.views import get_session_timeout


class MockOIDCBackend(OpenIdConnectAuth):
    name = "mock-oidc"
    AUTHORIZATION_URL = "https://idp.example.com/auth"
    ACCESS_TOKEN_URL = "https://idp.example.com/token"  # noqa: S105
    ID_TOKEN_ISSUER = "https://idp.example.com"  # noqa: S105


@override_settings(SOCIAL_AUTH_FACEBOOK_KEY="1", SOCIAL_AUTH_FACEBOOK_SECRET="2")  # noqa: S106
class TestViews(TestCase):
    def setUp(self):
        session = self.client.session
        session["facebook_state"] = "1"
        session.save()

    def test_begin_view(self):
        response = self.client.post(reverse("social:begin", kwargs={"backend": "facebook"}))
        self.assertEqual(response.status_code, 302)

        url = reverse("social:begin", kwargs={"backend": "blabla"})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 404)

    def test_begin_view_requires_post(self):
        response = self.client.get(reverse("social:begin", kwargs={"backend": "facebook"}))
        self.assertEqual(response.status_code, 405)

    @mock.patch("social_core.backends.base.BaseAuth.request")
    def test_complete(self, mock_request):
        url = reverse("social:complete", kwargs={"backend": "facebook"})
        url += "?code=2&state=1"
        mock_request.return_value.json.return_value = {"access_token": "123"}
        with mock.patch(
            "django.contrib.sessions.backends.base.SessionBase.set_expiry",
            side_effect=[OverflowError, None],
        ):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.url, "/accounts/profile/")

    @mock.patch("social_core.backends.base.BaseAuth.request")
    def test_disconnect(self, _mock_request):
        user_model = get_user_model()
        user = user_model._default_manager.create_user(  # noqa: SLF001
            username="test",
            password="pwd",  # noqa: S106
        )
        UserSocialAuth.objects.create(user=user, provider="facebook", uid="some-mock-facebook-uid")
        self.client.login(username="test", password="pwd")  # noqa: S106

        url = reverse("social:disconnect", kwargs={"backend": "facebook"})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "http://testserver/accounts/profile/")

        url = reverse(
            "social:disconnect_individual",
            kwargs={"backend": "facebook", "association_id": "123"},
        )
        hup = AbstractBaseUser.has_usable_password
        del AbstractBaseUser.has_usable_password
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "http://testserver/accounts/profile/")
        AbstractBaseUser.has_usable_password = hup


class TestGetSessionTimeout(TestCase):
    """
    Ensure that the branching logic of get_session_timeout behaves as expected.
    """

    def setUp(self):
        self.social_user = mock.MagicMock()
        self.social_user.expiration_datetime.return_value = None
        super().setUp()

    def set_user_expiration(self, seconds):
        self.social_user.expiration_datetime.return_value = mock.MagicMock(
            total_seconds=mock.MagicMock(return_value=seconds),
        )

    def test_expiration_disabled_no_max(self):
        self.set_user_expiration(60)
        expiration_length = get_session_timeout(self.social_user, enable_session_expiration=False)
        self.assertIsNone(expiration_length)

    def test_expiration_disabled_with_max(self):
        expiration_length = get_session_timeout(
            self.social_user,
            enable_session_expiration=False,
            max_session_length=60,
        )
        self.assertEqual(expiration_length, 60)

    def test_expiration_disabled_with_zero_max(self):
        expiration_length = get_session_timeout(self.social_user, enable_session_expiration=False, max_session_length=0)
        self.assertEqual(expiration_length, 0)

    def test_user_has_session_length_no_max(self):
        self.set_user_expiration(60)
        expiration_length = get_session_timeout(self.social_user, enable_session_expiration=True)
        self.assertEqual(expiration_length, 60)

    def test_user_has_session_length_larger_max(self):
        self.set_user_expiration(60)
        expiration_length = get_session_timeout(self.social_user, enable_session_expiration=True, max_session_length=90)
        self.assertEqual(expiration_length, 60)

    def test_user_has_session_length_smaller_max(self):
        self.set_user_expiration(60)
        expiration_length = get_session_timeout(self.social_user, enable_session_expiration=True, max_session_length=30)
        self.assertEqual(expiration_length, 30)

    def test_user_has_no_session_length_with_max(self):
        expiration_length = get_session_timeout(self.social_user, enable_session_expiration=True, max_session_length=60)
        self.assertEqual(expiration_length, 60)

    def test_user_has_no_session_length_no_max(self):
        expiration_length = get_session_timeout(self.social_user, enable_session_expiration=True)
        self.assertIsNone(expiration_length)


@override_settings(
    AUTHENTICATION_BACKENDS=(
        "tests.test_views.MockOIDCBackend",
        "social_core.backends.facebook.FacebookOAuth2",
        "django.contrib.auth.backends.ModelBackend",
    ),
    SOCIAL_AUTH_MOCK_OIDC_KEY="1",
    SOCIAL_AUTH_MOCK_OIDC_SECRET="2",  # noqa: S106
    SOCIAL_AUTH_MOCK_OIDC_ID_TOKEN_ISSUER="https://idp.example.com",  # noqa: S106
    SOCIAL_AUTH_FACEBOOK_KEY="1",
    SOCIAL_AUTH_FACEBOOK_SECRET="2",  # noqa: S106
)
class TestLaunchViews(TestCase):
    def test_idp_launch_renders_form(self):
        url = reverse("social:idp_launch", kwargs={"backend": "mock-oidc"})
        response = self.client.get(url, {"iss": "https://idp.example.com"})
        self.assertEqual(response.status_code, 200)

        content = response.content.decode()
        self.assertIn('method="post"', content)
        self.assertIn('action="/login/mock-oidc/"', content)
        self.assertIn('name="csrfmiddlewaretoken"', content)
        self.assertIn('name="iss" value="https://idp.example.com"', content)
        self.assertIn("autoLoginForm", content)
        self.assertIn("form.submit()", content)

    def test_idp_launch_whitelists_allowed_params(self):
        url = reverse("social:idp_launch", kwargs={"backend": "mock-oidc"})
        response = self.client.get(
            url,
            {
                "iss": "https://idp.example.com",
                "target_link_uri": "/dashboard",
                "untrusted_param": "attacker_value",
            },
        )
        self.assertEqual(response.status_code, 200)

        content = response.content.decode()
        self.assertIn('name="iss" value="https://idp.example.com"', content)
        self.assertIn('name="next" value="/dashboard"', content)
        self.assertNotIn("untrusted_param", content)
        self.assertNotIn("attacker_value", content)

    def test_idp_launch_no_state_change(self):
        url = reverse("social:idp_launch", kwargs={"backend": "mock-oidc"})
        session_before = dict(self.client.session)
        response = self.client.get(url, {"iss": "https://idp.example.com"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(dict(self.client.session), session_before)

    def test_idp_launch_rejects_post(self):
        url = reverse("social:idp_launch", kwargs={"backend": "mock-oidc"})
        response = self.client.post(url, {"iss": "https://idp.example.com"})
        self.assertEqual(response.status_code, 405)

    def test_idp_launch_invalid_backend_returns_404(self):
        url = reverse("social:idp_launch", kwargs={"backend": "nonexistent"})
        response = self.client.get(url, {"iss": "https://idp.example.com"})
        self.assertEqual(response.status_code, 404)

    def test_idp_launch_unsupported_backend_returns_400(self):
        url = reverse("social:idp_launch", kwargs={"backend": "facebook"})
        response = self.client.get(url, {"iss": "https://facebook.com"})
        self.assertEqual(response.status_code, 400)

    def test_idp_launch_invalid_or_missing_issuer_returns_400(self):
        url = reverse("social:idp_launch", kwargs={"backend": "mock-oidc"})
        # Missing iss
        response = self.client.get(url)
        self.assertEqual(response.status_code, 400)

        # Insecure scheme
        response = self.client.get(url, {"iss": "http://idp.example.com"})
        self.assertEqual(response.status_code, 400)

    def test_idp_launch_mismatched_iss_returns_400(self):
        url = reverse("social:idp_launch", kwargs={"backend": "mock-oidc"})
        response = self.client.get(url, {"iss": "https://other-idp.example.com"})
        self.assertEqual(response.status_code, 400)

    @override_settings(SOCIAL_AUTH_MOCK_OIDC_ALLOWED_ID_TOKEN_ISSUERS=["https://allowed-alias.example.com"])
    def test_idp_launch_allowed_issuers_list(self):
        url = reverse("social:idp_launch", kwargs={"backend": "mock-oidc"})
        response = self.client.get(url, {"iss": "https://allowed-alias.example.com"})
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('name="iss" value="https://allowed-alias.example.com"', content)

    def test_idp_launch_backend_with_multiple_issuers(self):
        with mock.patch.object(
            MockOIDCBackend,
            "id_token_issuer",
            return_value=["https://idp1.example.com", "https://idp2.example.com"],
        ):
            url = reverse("social:idp_launch", kwargs={"backend": "mock-oidc"})

            # First issuer succeeds
            response = self.client.get(url, {"iss": "https://idp1.example.com"})
            self.assertEqual(response.status_code, 200)
            self.assertIn('name="iss" value="https://idp1.example.com"', response.content.decode())

            # Second issuer succeeds
            response = self.client.get(url, {"iss": "https://idp2.example.com"})
            self.assertEqual(response.status_code, 200)
            self.assertIn('name="iss" value="https://idp2.example.com"', response.content.decode())

    def test_idp_launch_security_headers(self):
        url = reverse("social:idp_launch", kwargs={"backend": "mock-oidc"})
        response = self.client.get(url, {"iss": "https://idp.example.com"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("X-Frame-Options"), "DENY")
        self.assertIn("frame-ancestors 'none'", response.headers.get("Content-Security-Policy", ""))

    def test_idp_launch_oidc_target_link_uri_and_open_redirect_prevention(self):
        url = reverse("social:idp_launch", kwargs={"backend": "mock-oidc"})

        # Unsafe open redirect target discarded
        response = self.client.get(
            url,
            {"iss": "https://idp.example.com", "target_link_uri": "https://evil.com/phishing"},
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertNotIn("evil.com", content)

        # Safe internal path preserved
        response = self.client.get(
            url,
            {"iss": "https://idp.example.com", "target_link_uri": "/my/app/home"},
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('name="next" value="/my/app/home"', content)

        # Allowed external redirect host from settings preserved
        with override_settings(SOCIAL_AUTH_ALLOWED_REDIRECT_HOSTS=["frontend.example.com"]):
            response = self.client.get(
                url,
                {
                    "iss": "https://idp.example.com",
                    "target_link_uri": "https://frontend.example.com/welcome",
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn('name="next" value="https://frontend.example.com/welcome"', response.content.decode())

    def test_idp_launch_fetch_metadata_iframe_fallback(self):
        url = reverse("social:idp_launch", kwargs={"backend": "mock-oidc"})
        response = self.client.get(
            url,
            {"iss": "https://idp.example.com"},
            headers={"sec-fetch-mode": "iframe"},
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Click below to continue signing in.", content)
        self.assertIn('<button type="submit">Next</button>', content)
        self.assertNotIn("form.submit()", content)

    def test_idp_launch_authenticated_user_redirects(self):
        user_model = get_user_model()
        user_model._default_manager.create_user(username="launch_tester", password="pwd")  # noqa: S106, SLF001
        self.client.login(username="launch_tester", password="pwd")  # noqa: S106

        url = reverse("social:idp_launch", kwargs={"backend": "mock-oidc"})

        # With safe target_link_uri
        response = self.client.get(url, {"iss": "https://idp.example.com", "target_link_uri": "/portal"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/portal")

        # Without target_link_uri -> redirects to LOGIN_REDIRECT_URL
        response = self.client.get(url, {"iss": "https://idp.example.com"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/accounts/profile/")

    def test_app_launch_success(self):
        url = reverse("social:app_launch", kwargs={"backend": "mock-oidc"})
        response = self.client.get(
            url,
            {"next": "/dashboard", "target_link_uri": "/ignored"},
            headers={"sec-fetch-site": "same-origin"},
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('name="iss" value="https://idp.example.com"', content)
        self.assertIn('name="next" value="/dashboard"', content)
        self.assertNotIn("/ignored", content)
        self.assertIn("autoLoginForm", content)
        self.assertIn("form.submit()", content)

    @override_settings(SOCIAL_AUTH_ALLOWED_REDIRECT_HOSTS=["frontend.example.com"])
    def test_app_launch_with_allowed_redirect_host(self):
        url = reverse("social:app_launch", kwargs={"backend": "mock-oidc"})
        response = self.client.get(
            url,
            {"next": "https://frontend.example.com/portal"},
            headers={"sec-fetch-site": "same-origin"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('name="next" value="https://frontend.example.com/portal"', response.content.decode())

    def test_app_launch_with_explicit_iss(self):
        url = reverse("social:app_launch", kwargs={"backend": "mock-oidc"})
        # Valid explicit iss matching configured issuer
        response = self.client.get(
            url,
            {"iss": "https://idp.example.com", "next": "/home"},
            headers={"sec-fetch-site": "same-origin"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('name="iss" value="https://idp.example.com"', response.content.decode())

        # Invalid explicit iss rejected with 400
        response = self.client.get(
            url,
            {"iss": "https://attacker-idp.example.com"},
            headers={"sec-fetch-site": "same-origin"},
        )
        self.assertEqual(response.status_code, 400)

    def test_app_launch_multi_issuer_selection(self):
        with mock.patch.object(
            MockOIDCBackend,
            "id_token_issuer",
            return_value=["https://primary.example.com", "https://secondary.example.com"],
        ):
            url = reverse("social:app_launch", kwargs={"backend": "mock-oidc"})

            # Defaults to primary issuer when omitted
            response = self.client.get(url, headers={"sec-fetch-site": "same-origin"})
            self.assertEqual(response.status_code, 200)
            self.assertIn('name="iss" value="https://primary.example.com"', response.content.decode())

            # Uses secondary issuer when requested
            response = self.client.get(
                url,
                {"iss": "https://secondary.example.com"},
                headers={"sec-fetch-site": "same-origin"},
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn('name="iss" value="https://secondary.example.com"', response.content.decode())

    def test_app_launch_rejects_cross_site_fetch_site(self):
        url = reverse("social:app_launch", kwargs={"backend": "mock-oidc"})
        response = self.client.get(url, headers={"sec-fetch-site": "cross-site"})
        self.assertEqual(response.status_code, 400)

    def test_app_launch_rejects_untrusted_referer(self):
        url = reverse("social:app_launch", kwargs={"backend": "mock-oidc"})
        response = self.client.get(
            url,
            headers={"sec-fetch-site": "same-origin", "referer": "https://attacker.example.com"},
        )
        self.assertEqual(response.status_code, 400)

    def test_app_launch_rejects_missing_origin_evidence(self):
        url = reverse("social:app_launch", kwargs={"backend": "mock-oidc"})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 400)

    def test_app_launch_unsupported_backend_returns_400(self):
        url = reverse("social:app_launch", kwargs={"backend": "facebook"})
        response = self.client.get(url, headers={"sec-fetch-site": "same-origin"})
        self.assertEqual(response.status_code, 400)

    def test_app_launch_authenticated_user_redirects(self):
        user_model = get_user_model()
        user_model._default_manager.create_user(username="app_tester", password="pwd")  # noqa: S106, SLF001
        self.client.login(username="app_tester", password="pwd")  # noqa: S106

        url = reverse("social:app_launch", kwargs={"backend": "mock-oidc"})
        response = self.client.get(
            url,
            {"next": "/my-dashboard"},
            headers={"sec-fetch-site": "same-origin"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/my-dashboard")
