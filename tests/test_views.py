import hmac
from base64 import urlsafe_b64decode, urlsafe_b64encode
from hashlib import sha256
from unittest import mock
from urllib.parse import parse_qs, urlencode, urlsplit

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractBaseUser, AnonymousUser
from django.contrib.messages import get_messages
from django.http import HttpRequest
from django.middleware.csrf import get_token
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from social_core.backends.open_id_connect import OpenIdConnectAuth

from social_django.models import Code, Nonce, Partial, UserSocialAuth
from social_django.utils import LaunchBridge
from social_django.views import get_session_timeout


class MockOIDCBackend(OpenIdConnectAuth):
    name = "mock-oidc"
    AUTHORIZATION_URL = "https://idp.example.com/auth"
    ACCESS_TOKEN_URL = "https://idp.example.com/token"  # ruff: ignore[hardcoded-password-string]
    ID_TOKEN_ISSUER = "https://idp.example.com"  # ruff: ignore[hardcoded-password-string]


def send_validation(strategy, backend, code, partial_token):
    """Validation sender replaced by a mock in email confirmation tests."""


@override_settings(
    AUTHENTICATION_BACKENDS=("social_core.backends.email.EmailAuth",),
    SOCIAL_AUTH_PIPELINE=(
        "social_core.pipeline.social_auth.social_details",
        "social_core.pipeline.social_auth.social_uid",
        "social_core.pipeline.social_auth.social_user",
        "social_core.pipeline.user.get_username",
        "social_core.pipeline.mail.mail_validation",
        "social_core.pipeline.user.create_user",
        "social_core.pipeline.social_auth.associate_user",
    ),
    SOCIAL_AUTH_PASSWORDLESS=True,
    SOCIAL_AUTH_EMAIL_VALIDATION_FUNCTION="tests.test_views.send_validation",
    SOCIAL_AUTH_EMAIL_VALIDATION_URL="/email-sent/",
    LOGIN_REDIRECT_URL="/done/",
    SOCIAL_AUTH_LOGIN_ERROR_URL="/error/",
)
class TestEmailConfirmation(TestCase):
    @staticmethod
    def csrf_client() -> tuple[Client, str]:
        request = HttpRequest()
        token = get_token(request)
        client = Client(enforce_csrf_checks=True)
        client.cookies[settings.CSRF_COOKIE_NAME] = request.META["CSRF_COOKIE"]
        return client, token

    def test_login_form_requires_post(self):
        user = get_user_model()._default_manager.create_user(username="victim")
        self.client.force_login(user)
        url = reverse("social:complete", kwargs={"backend": "email"})
        with mock.patch("tests.test_views.send_validation") as send_email:
            response = self.client.get(url, {"email": "attacker@example.com"})
        self.assertEqual(response.status_code, 405)
        send_email.assert_not_called()
        self.assertFalse(Partial.objects.exists())
        self.assertFalse(UserSocialAuth.objects.filter(user=user).exists())

    def test_login_form_requires_csrf_token(self):
        url = reverse("social:complete", kwargs={"backend": "email"})
        client, token = self.csrf_client()
        with mock.patch("tests.test_views.send_validation") as send_email:
            response = client.post(url, {"email": "confirm@example.com"})
            self.assertEqual(response.status_code, 403)
            send_email.assert_not_called()

            response = client.post(
                url,
                {"email": "confirm@example.com", "csrfmiddlewaretoken": token},
            )
            self.assertRedirects(response, "/email-sent/", fetch_redirect_response=False)
            send_email.assert_called_once()

            code = send_email.call_args.args[2]
            partial_token = send_email.call_args.args[3]
            response = client.get(url, {"verification_code": code.code, "partial_token": partial_token})
            self.assertTemplateUsed(response, "social_django/partial_pipeline_external_resume.html")
            context = response.context
            response = client.post(
                context["action_url"],
                {
                    context["confirmation_parameter"]: context["confirmation_value"],
                    context["confirmation_nonce_parameter"]: context["confirmation_nonce"],
                },
            )
            self.assertRedirects(response, "/done/", fetch_redirect_response=False)
            self.assertTrue(Code.objects.get(pk=code.pk).verified)

    def test_authenticated_user_can_link_email_with_csrf_token(self):
        user = get_user_model()._default_manager.create_user(username="existing")
        client, token = self.csrf_client()
        client.force_login(user)
        url = reverse("social:complete", kwargs={"backend": "email"})
        with mock.patch("tests.test_views.send_validation") as send_email:
            response = client.post(
                url,
                {"email": "linked@example.com", "csrfmiddlewaretoken": token},
            )
            self.assertRedirects(response, "/email-sent/", fetch_redirect_response=False)
            code = send_email.call_args.args[2]
            partial_token = send_email.call_args.args[3]
            response = client.get(
                url,
                {"verification_code": code.code, "partial_token": partial_token},
            )
            context = response.context
            response = client.post(
                context["action_url"],
                {
                    context["confirmation_parameter"]: context["confirmation_value"],
                    context["confirmation_nonce_parameter"]: context["confirmation_nonce"],
                },
            )
        self.assertRedirects(response, "/done/", fetch_redirect_response=False)
        self.assertTrue(
            UserSocialAuth.objects.filter(
                user=user,
                provider="email",
                uid="linked@example.com",
            ).exists()
        )

    @override_settings(SOCIAL_AUTH_PASSWORDLESS=False)
    def test_existing_user_can_log_in_with_csrf_token(self):
        user = get_user_model()._default_manager.create_user(username="existing")
        UserSocialAuth.objects.create(
            user=user,
            provider="email",
            uid="existing@example.com",
            id_key="email",
        )
        client, token = self.csrf_client()
        url = reverse("social:complete", kwargs={"backend": "email"})
        with mock.patch("tests.test_views.send_validation") as send_email:
            response = client.post(
                url,
                {"email": "existing@example.com", "csrfmiddlewaretoken": token},
            )
        send_email.assert_not_called()
        self.assertRedirects(response, "/done/", fetch_redirect_response=False)
        self.assertEqual(int(client.session["_auth_user_id"]), user.pk)

    @override_settings(AUTHENTICATION_BACKENDS=("social_core.backends.username.UsernameAuth",))
    def test_username_login_form_requires_post_and_csrf_token(self):
        user = get_user_model()._default_manager.create_user(username="victim")
        self.client.force_login(user)
        url = reverse("social:complete", kwargs={"backend": "username"})
        self.assertEqual(self.client.get(url, {"username": "attacker"}).status_code, 405)

        client = Client(enforce_csrf_checks=True)
        client.force_login(user)
        self.assertEqual(client.post(url, {"username": "attacker"}).status_code, 403)
        self.assertFalse(Partial.objects.exists())
        self.assertFalse(UserSocialAuth.objects.filter(user=user).exists())

    def test_confirmation_replays_code_without_resending_email(self):
        url = reverse("social:complete", kwargs={"backend": "email"})
        with mock.patch("tests.test_views.send_validation") as send_email:
            self.assertRedirects(
                self.client.post(url, {"email": "confirm@example.com"}),
                "/email-sent/",
                fetch_redirect_response=False,
            )
            code = send_email.call_args.args[2]
            token = send_email.call_args.args[3]
            response = self.client.get(url, {"verification_code": code.code, "partial_token": token})
            self.assertTemplateUsed(response, "social_django/partial_pipeline_external_resume.html")
            self.assertFalse(get_user_model().objects.filter(email=code.email).exists())
            self.assertFalse(Code.objects.get(pk=code.pk).verified)
            context = response.context
            response = self.client.post(
                context["action_url"],
                {
                    context["confirmation_parameter"]: context["confirmation_value"],
                    context["confirmation_nonce_parameter"]: context["confirmation_nonce"],
                },
            )
            self.assertRedirects(response, "/done/", fetch_redirect_response=False)
            self.assertTrue(Code.objects.get(pk=code.pk).verified)
            self.assertTrue(get_user_model().objects.filter(email=code.email).exists())
            self.assertFalse(Partial.objects.filter(token=token).exists())
            send_email.assert_called_once()

    def test_invalid_confirmation_nonce_does_not_verify_code(self):
        url = reverse("social:complete", kwargs={"backend": "email"})
        with mock.patch("tests.test_views.send_validation") as send_email:
            self.client.post(url, {"email": "confirm@example.com"})
            code = send_email.call_args.args[2]
            token = send_email.call_args.args[3]
            response = self.client.get(url, {"verification_code": code.code, "partial_token": token})
            context = response.context
            response = self.client.post(
                context["action_url"],
                {
                    context["confirmation_parameter"]: context["confirmation_value"],
                    context["confirmation_nonce_parameter"]: "invalid",
                },
            )
            self.assertRedirects(response, "/error/", fetch_redirect_response=False)
            self.assertFalse(Code.objects.get(pk=code.pk).verified)
            self.assertTrue(Partial.objects.filter(token=token).exists())
            self.assertFalse(get_user_model().objects.filter(email=code.email).exists())
            send_email.assert_called_once()


@override_settings(SOCIAL_AUTH_FACEBOOK_KEY="1", SOCIAL_AUTH_FACEBOOK_SECRET="2")  # ruff: ignore[hardcoded-password-func-arg]
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

    def test_begin_view_passes_authenticated_user_to_prepare_auth(self):
        user = get_user_model()._default_manager.create_user(username="begin_tester")
        self.client.force_login(user)

        with mock.patch("social_core.backends.base.BaseAuth.prepare_auth") as prepare_auth:
            response = self.client.post(reverse("social:begin", kwargs={"backend": "facebook"}))

        self.assertEqual(response.status_code, 302)
        prepare_auth.assert_called_once()
        self.assertEqual(prepare_auth.call_args.kwargs["user"].pk, user.pk)

    def test_begin_view_passes_anonymous_user_to_prepare_auth(self):
        with mock.patch("social_core.backends.base.BaseAuth.prepare_auth") as prepare_auth:
            response = self.client.post(reverse("social:begin", kwargs={"backend": "facebook"}))

        self.assertEqual(response.status_code, 302)
        prepare_auth.assert_called_once()
        self.assertIsInstance(prepare_auth.call_args.kwargs["user"], AnonymousUser)

    def test_begin_view_requires_post(self):
        response = self.client.get(reverse("social:begin", kwargs={"backend": "facebook"}))
        self.assertEqual(response.status_code, 405)

    @mock.patch("social_core.backends.base.BaseAuth.request")
    def test_complete(self, mock_request):
        client = Client(enforce_csrf_checks=True)
        session = client.session
        session["facebook_state"] = "1"
        session.save()
        url = reverse("social:complete", kwargs={"backend": "facebook"})
        url += "?code=2&state=1"
        mock_request.return_value.json.side_effect = [
            {"access_token": "123"},
            {"id": "facebook-user-123"},
        ]
        with mock.patch(
            "django.contrib.sessions.backends.base.SessionBase.set_expiry",
            side_effect=[OverflowError, None],
        ):
            response = client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.url, "/accounts/profile/")

    @mock.patch("social_core.backends.base.BaseAuth.request")
    def test_disconnect(self, _mock_request):
        user_model = get_user_model()
        user = user_model._default_manager.create_user(
            username="test",
            password="pwd",  # ruff: ignore[hardcoded-password-func-arg]
        )
        UserSocialAuth.objects.create(user=user, provider="facebook", uid="some-mock-facebook-uid")
        self.client.login(username="test", password="pwd")  # ruff: ignore[hardcoded-password-func-arg]

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

    def test_disconnect_rejects_unconfigured_remaining_association(self):
        user = get_user_model()._default_manager.create_user(username="passwordless")
        working = UserSocialAuth.objects.create(user=user, provider="facebook", uid="working-facebook")
        UserSocialAuth.objects.create(user=user, provider="removed-provider", uid="stale-provider")
        self.client.force_login(user)

        response = self.client.post(reverse("social:disconnect", kwargs={"backend": "facebook"}))

        self.assertEqual(response.status_code, 403)
        self.assertTrue(UserSocialAuth.objects.filter(pk=working.pk).exists())

    def test_disconnect_individual_zero_id_keeps_last_association(self):
        user = get_user_model()._default_manager.create_user(username="passwordless")
        association = UserSocialAuth.objects.create(user=user, provider="facebook", uid="working-facebook")
        self.assertFalse(user.has_usable_password())
        self.client.force_login(user)

        for association_id, status in ((None, 403), (association.pk, 403), (0, 302)):
            with self.subTest(association_id=association_id):
                kwargs = {"backend": "facebook"}
                url_name = "social:disconnect"
                if association_id is not None:
                    kwargs["association_id"] = association_id
                    url_name = "social:disconnect_individual"
                response = self.client.post(reverse(url_name, kwargs=kwargs))

                self.assertEqual(response.status_code, status)
                self.assertQuerySetEqual(user.social_auth.all(), [association])


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
    SOCIAL_AUTH_MOCK_OIDC_SECRET="2",  # ruff: ignore[hardcoded-password-func-arg]
    SOCIAL_AUTH_MOCK_OIDC_ID_TOKEN_ISSUER="https://idp.example.com",  # ruff: ignore[hardcoded-password-func-arg]
    SOCIAL_AUTH_FACEBOOK_KEY="1",
    SOCIAL_AUTH_FACEBOOK_SECRET="2",  # ruff: ignore[hardcoded-password-func-arg]
    SOCIAL_AUTH_ENABLE_LAUNCH_BRIDGES=[LaunchBridge.APP, LaunchBridge.IDP],
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
        user_model._default_manager.create_user(username="launch_tester", password="pwd")  # ruff: ignore[hardcoded-password-func-arg]
        self.client.login(username="launch_tester", password="pwd")  # ruff: ignore[hardcoded-password-func-arg]

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
        user_model._default_manager.create_user(username="app_tester", password="pwd")  # ruff: ignore[hardcoded-password-func-arg]
        self.client.login(username="app_tester", password="pwd")  # ruff: ignore[hardcoded-password-func-arg]

        url = reverse("social:app_launch", kwargs={"backend": "mock-oidc"})
        response = self.client.get(
            url,
            {"next": "/my-dashboard"},
            headers={"sec-fetch-site": "same-origin"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/my-dashboard")

    @override_settings(SOCIAL_AUTH_ENABLE_LAUNCH_BRIDGES=None)
    def test_launch_bridges_disabled_by_default(self):
        idp_url = reverse("social:idp_launch", kwargs={"backend": "mock-oidc"})
        app_url = reverse("social:app_launch", kwargs={"backend": "mock-oidc"})
        self.assertEqual(self.client.get(idp_url, {"iss": "https://idp.example.com"}).status_code, 404)
        self.assertEqual(self.client.get(app_url, headers={"sec-fetch-site": "same-origin"}).status_code, 404)

    @override_settings(SOCIAL_AUTH_ENABLE_LAUNCH_BRIDGES=[])
    def test_launch_bridges_disabled_when_empty_list(self):
        idp_url = reverse("social:idp_launch", kwargs={"backend": "mock-oidc"})
        app_url = reverse("social:app_launch", kwargs={"backend": "mock-oidc"})
        self.assertEqual(self.client.get(idp_url, {"iss": "https://idp.example.com"}).status_code, 404)
        self.assertEqual(self.client.get(app_url, headers={"sec-fetch-site": "same-origin"}).status_code, 404)

    @override_settings(SOCIAL_AUTH_ENABLE_LAUNCH_BRIDGES=[LaunchBridge.APP])
    def test_only_app_launch_enabled(self):
        idp_url = reverse("social:idp_launch", kwargs={"backend": "mock-oidc"})
        app_url = reverse("social:app_launch", kwargs={"backend": "mock-oidc"})
        self.assertEqual(self.client.get(idp_url, {"iss": "https://idp.example.com"}).status_code, 404)
        self.assertEqual(self.client.get(app_url, headers={"sec-fetch-site": "same-origin"}).status_code, 200)

    @override_settings(SOCIAL_AUTH_ENABLE_LAUNCH_BRIDGES=[LaunchBridge.IDP])
    def test_only_idp_launch_enabled(self):
        idp_url = reverse("social:idp_launch", kwargs={"backend": "mock-oidc"})
        app_url = reverse("social:app_launch", kwargs={"backend": "mock-oidc"})
        self.assertEqual(self.client.get(idp_url, {"iss": "https://idp.example.com"}).status_code, 200)
        self.assertEqual(self.client.get(app_url, headers={"sec-fetch-site": "same-origin"}).status_code, 404)

    @override_settings(SOCIAL_AUTH_ENABLE_LAUNCH_BRIDGES=["app_launch"])
    def test_only_app_launch_enabled_with_string(self):
        idp_url = reverse("social:idp_launch", kwargs={"backend": "mock-oidc"})
        app_url = reverse("social:app_launch", kwargs={"backend": "mock-oidc"})
        self.assertEqual(self.client.get(idp_url, {"iss": "https://idp.example.com"}).status_code, 404)
        self.assertEqual(self.client.get(app_url, headers={"sec-fetch-site": "same-origin"}).status_code, 200)

    @override_settings(SOCIAL_AUTH_ENABLE_LAUNCH_BRIDGES=["idp_launch"])
    def test_only_idp_launch_enabled_with_string(self):
        idp_url = reverse("social:idp_launch", kwargs={"backend": "mock-oidc"})
        app_url = reverse("social:app_launch", kwargs={"backend": "mock-oidc"})
        self.assertEqual(self.client.get(idp_url, {"iss": "https://idp.example.com"}).status_code, 200)
        self.assertEqual(self.client.get(app_url, headers={"sec-fetch-site": "same-origin"}).status_code, 404)


@override_settings(
    DEBUG=False,
    AUTHENTICATION_BACKENDS=("social_core.backends.discourse.DiscourseAuth",),
    SOCIAL_AUTH_DISCOURSE_SERVER_URL="https://forum.example.com",
    SOCIAL_AUTH_DISCOURSE_SECRET="discourse-test-secret",  # ruff: ignore[hardcoded-password-func-arg]
    LOGIN_REDIRECT_URL="/done/",
)
class TestDiscourseCallback(TestCase):
    def signed_callback(self, **data: str) -> str:
        payload = urlsafe_b64encode(urlencode(data).encode()).decode()
        signature = hmac.new(b"discourse-test-secret", payload.encode(), sha256).hexdigest()
        url = reverse("social:complete", kwargs={"backend": "discourse"})
        return url + "?" + urlencode({"sso": payload, "sig": signature})

    def complete_login(self) -> str:
        response = self.client.post(reverse("social:begin", kwargs={"backend": "discourse"}))
        self.assertEqual(response.status_code, 302)
        query = parse_qs(urlsplit(response.url).query)
        request = parse_qs(urlsafe_b64decode(query["sso"][0]).decode())
        callback = self.signed_callback(
            nonce=request["nonce"][0], external_id="42", username="member42", email="member42@example.com"
        )
        response = self.client.get(callback)
        self.assertRedirects(response, "/done/", fetch_redirect_response=False)
        self.assertIn("_auth_user_id", self.client.session)
        self.assertEqual(UserSocialAuth.objects.get().uid, "42")
        self.assertFalse(Nonce.objects.exists())
        return callback

    def test_reused_callback_returns_authentication_error(self) -> None:
        callback = self.complete_login()
        client = Client()
        response = client.get(callback)
        self.assertEqual(response.status_code, 403)
        self.assertTemplateUsed(response, "social_django/error.html")
        self.assertEqual(response.context["error_code"], "nonce_mismatch")
        self.assertEqual(response.context["error_stage"], "callback")
        self.assertNotIn("_auth_user_id", client.session)
        self.assertEqual(get_user_model().objects.count(), 1)
        self.assertEqual(UserSocialAuth.objects.count(), 1)

    @override_settings(SOCIAL_AUTH_LOGIN_ERROR_URL="/error/")
    def test_reused_callback_redirects_to_login_error_url(self) -> None:
        callback = self.complete_login()
        client = Client()
        response = client.get(callback)
        self.assertRedirects(response, "/error/", fetch_redirect_response=False)
        self.assertTrue(list(get_messages(response.wsgi_request)))
        self.assertNotIn("_auth_user_id", client.session)
        self.assertEqual(get_user_model().objects.count(), 1)
        self.assertEqual(UserSocialAuth.objects.count(), 1)

    def test_unknown_or_missing_nonce_returns_authentication_error(self) -> None:
        for data in ({"nonce": "unknown"}, {"nonce": ""}, {}):
            with self.subTest(data=data):
                response = self.client.get(self.signed_callback(external_id="42", **data))
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.context["error_code"], "nonce_mismatch")
                self.assertNotIn("_auth_user_id", self.client.session)
                self.assertFalse(get_user_model().objects.exists())
                self.assertFalse(UserSocialAuth.objects.exists())
