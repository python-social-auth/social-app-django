import hmac
from base64 import urlsafe_b64decode, urlsafe_b64encode
from hashlib import sha256
from unittest import mock
from urllib.parse import parse_qs, urlencode, urlsplit

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractBaseUser, AnonymousUser
from django.contrib.contenttypes.models import ContentType
from django.contrib.messages import get_messages
from django.http import HttpRequest, HttpResponse
from django.middleware.csrf import get_token
from django.test import Client, TestCase, override_settings
from django.urls import include, path, reverse
from social_core.backends.facebook import FacebookOAuth2
from social_core.backends.open_id_connect import OpenIdConnectAuth
from social_core.utils import PARTIAL_TOKEN_PENDING_REQUEST_SESSION_NAME

from social_django.models import Code, Nonce, Partial, UserSocialAuth
from social_django.utils import LaunchBridge
from social_django.views import get_session_timeout


class MockOIDCBackend(OpenIdConnectAuth):
    name = "mock-oidc"
    AUTHORIZATION_URL = "https://idp.example.com/auth"
    ACCESS_TOKEN_URL = "https://idp.example.com/token"  # ruff: ignore[hardcoded-password-string]
    ID_TOKEN_ISSUER = "https://idp.example.com"  # ruff: ignore[hardcoded-password-string]


def launch_redirect_destination(request: HttpRequest) -> HttpResponse:
    return HttpResponse()


class LaunchRedirectURLConf:
    urlpatterns = (
        path("welcome/", launch_redirect_destination, name="dashboard"),
        path("", include("tests.urls")),
    )


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

    def test_login_parameters_survive_partial_resume(self):
        target = get_user_model().objects.create_user(username="target")
        ctype = ContentType.objects.get_for_model(target)
        url = reverse("social:complete", kwargs={"backend": "email"})
        for index, probe in enumerate((
            {"pk": str(target.pk), "ctype": str(ctype.pk)},
            {"pk": str(target.pk + 1), "ctype": str(ctype.pk)},
            {"pk": "invalid", "ctype": "invalid"},
            {"__social_django_session_value__": "1", "kind": "model", "value": "request"},
        )):
            with (
                self.subTest(probe=probe),
                self.settings(
                    SOCIAL_AUTH_PIPELINE=(
                        *settings.SOCIAL_AUTH_PIPELINE,
                        "social_core.pipeline.social_auth.load_extra_data",
                    )
                ),
                mock.patch("tests.test_views.send_validation") as send_email,
            ):
                email = f"confirm{index}@example.com"
                client, csrf_token = self.csrf_client()
                response = client.post(url, {"email": email, "csrfmiddlewaretoken": csrf_token, **probe})
                self.assertRedirects(response, "/email-sent/", fetch_redirect_response=False)
                response = client.get(url)
                self.assertRedirects(response, "/email-sent/", fetch_redirect_response=False)
                code = send_email.call_args.args[2]
                partial_token = send_email.call_args.args[3]
                response = client.get(url, {"verification_code": code.code, "partial_token": partial_token})
                context = response.context
                response = client.post(
                    context["action_url"],
                    {
                        "csrfmiddlewaretoken": csrf_token,
                        context["confirmation_parameter"]: context["confirmation_value"],
                        context["confirmation_nonce_parameter"]: context["confirmation_nonce"],
                    },
                )
                self.assertRedirects(response, "/done/", fetch_redirect_response=False)
                association = UserSocialAuth.objects.get(provider="email", uid=email)
                self.assertNotEqual(association.user_id, target.pk)
                self.assertEqual(int(client.session["_auth_user_id"]), association.user_id)
                self.assertTrue(Code.objects.get(pk=code.pk).verified)

    def test_confirmation_parameters_survive_session_storage(self):
        target = get_user_model().objects.create_user(username="target")
        ctype = ContentType.objects.get_for_model(target)
        url = reverse("social:complete", kwargs={"backend": "email"})
        for legacy in (False, True):
            for index, pk in enumerate((str(target.pk), "missing")):
                with self.subTest(legacy=legacy, pk=pk), mock.patch("tests.test_views.send_validation") as send_email:
                    email = f"confirm{legacy}{index}@example.com"
                    client, csrf_token = self.csrf_client()
                    client.post(url, {"email": email, "csrfmiddlewaretoken": csrf_token})
                    code = send_email.call_args.args[2]
                    partial_token = send_email.call_args.args[3]
                    probe = {
                        "verification_code": code.code,
                        "partial_token": partial_token,
                        "pk": pk,
                        "ctype": str(ctype.pk),
                    }
                    response = client.get(url, probe)
                    self.assertTemplateUsed(response, "social_django/partial_pipeline_external_resume.html")
                    if legacy:
                        session = client.session
                        session[PARTIAL_TOKEN_PENDING_REQUEST_SESSION_NAME] = probe
                        session.save()
                    context = response.context
                    response = client.post(
                        context["action_url"],
                        {
                            "csrfmiddlewaretoken": csrf_token,
                            context["confirmation_parameter"]: context["confirmation_value"],
                            context["confirmation_nonce_parameter"]: context["confirmation_nonce"],
                        },
                    )
                    self.assertRedirects(response, "/done/", fetch_redirect_response=False)
                    association = UserSocialAuth.objects.get(provider="email", uid=email)
                    self.assertNotEqual(association.user_id, target.pk)
                    self.assertEqual(int(client.session["_auth_user_id"]), association.user_id)
                    self.assertTrue(Code.objects.get(pk=code.pk).verified)

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

    def test_authenticated_user_cannot_confirm_anonymous_flow(self):
        url = reverse("social:complete", kwargs={"backend": "email"})
        user_model = get_user_model()
        victim = user_model._default_manager.create_user(
            username="victim",
            email="victim@example.com",
            first_name="Victim",
        )
        victim_client = Client()
        victim_client.force_login(victim)
        with mock.patch("tests.test_views.send_validation") as send_email:
            self.client.post(url, {"email": "attacker@example.com"})
            code = send_email.call_args.args[2]
            token = send_email.call_args.args[3]

            response = victim_client.get(
                url,
                {"verification_code": code.code, "partial_token": token},
            )

            self.assertRedirects(response, "/error/", fetch_redirect_response=False)
            self.assertFalse(Code.objects.get(pk=code.pk).verified)
            self.assertTrue(Partial.objects.filter(token=token).exists())
            self.assertFalse(UserSocialAuth.objects.filter(user=victim).exists())
            self.assertFalse(user_model._default_manager.filter(email=code.email).exists())
            victim.refresh_from_db()
            self.assertEqual(victim.first_name, "Victim")

    def test_authenticated_user_cannot_submit_anonymous_confirmation(self):
        url = reverse("social:complete", kwargs={"backend": "email"})
        victim = get_user_model()._default_manager.create_user(username="victim", email="victim@example.com")
        with mock.patch("tests.test_views.send_validation") as send_email:
            self.client.post(url, {"email": "attacker@example.com"})
            code = send_email.call_args.args[2]
            token = send_email.call_args.args[3]
            response = self.client.get(
                url,
                {"verification_code": code.code, "partial_token": token},
            )
            self.assertTemplateUsed(response, "social_django/partial_pipeline_external_resume.html")
            context = response.context
            self.client.force_login(victim)

            response = self.client.post(
                context["action_url"],
                {
                    context["confirmation_parameter"]: context["confirmation_value"],
                    context["confirmation_nonce_parameter"]: context["confirmation_nonce"],
                },
            )

            self.assertRedirects(response, "/error/", fetch_redirect_response=False)
            self.assertFalse(Code.objects.get(pk=code.pk).verified)
            self.assertTrue(Partial.objects.filter(token=token).exists())
            self.assertFalse(UserSocialAuth.objects.filter(user=victim).exists())

    def test_authenticated_user_can_confirm_own_flow(self):
        url = reverse("social:complete", kwargs={"backend": "email"})
        user = get_user_model()._default_manager.create_user(username="owner", email="owner@example.com")
        self.client.force_login(user)
        with mock.patch("tests.test_views.send_validation") as send_email:
            self.client.post(url, {"email": user.email})
            code = send_email.call_args.args[2]
            token = send_email.call_args.args[3]
            response = self.client.get(
                url,
                {"verification_code": code.code, "partial_token": token},
            )
            self.assertTemplateUsed(response, "social_django/partial_pipeline_external_resume.html")
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
            self.assertTrue(UserSocialAuth.objects.filter(user=user, provider="email", uid=code.email).exists())
            self.assertFalse(Partial.objects.filter(token=token).exists())


@override_settings(
    DEBUG=False,
    SESSION_ENGINE="django.contrib.sessions.backends.signed_cookies",
    SOCIAL_AUTH_FACEBOOK_KEY="1",
    SOCIAL_AUTH_FACEBOOK_SECRET="2",  # ruff: ignore[hardcoded-password-func-arg]
    SOCIAL_AUTH_LOGIN_ERROR_URL="/login-error/",
)
class TestOAuth2NonceClaim(TestCase):
    def test_same_session_snapshot_cannot_exchange_state_twice(self):
        if not hasattr(FacebookOAuth2, "_nonce_scope"):
            self.skipTest("requires the one-time OAuth2 state caller in social-auth-core")

        first = Client()
        begin_url = reverse("social:begin", kwargs={"backend": "facebook"})
        start = first.post(begin_url)
        self.assertEqual(start.status_code, 302)
        state = parse_qs(urlsplit(start["Location"]).query)["state"][0]
        second = Client()
        second.cookies = first.cookies.copy()
        complete_url = reverse("social:complete", kwargs={"backend": "facebook"})

        with mock.patch("social_core.backends.base.BaseAuth.request") as provider_request:
            provider_request.return_value.json.side_effect = [
                {"access_token": "token"},
                {"id": "facebook-user-123"},
            ]
            accepted = first.get(complete_url, {"code": "code", "state": state})
            rejected = second.get(complete_url, {"code": "code", "state": state})

        self.assertRedirects(accepted, "/accounts/profile/", fetch_redirect_response=False)
        self.assertRedirects(rejected, "/login-error/", fetch_redirect_response=False)
        self.assertEqual(provider_request.call_count, 2)
        self.assertFalse(rejected.wsgi_request.user.is_authenticated)
        self.assertFalse(Nonce.objects.exists())


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

    @override_settings(
        AUTHENTICATION_BACKENDS=(
            "social_core.backends.facebook.FacebookOAuth2",
            "social_core.backends.drip.DripOAuth",
            "django.contrib.auth.backends.ModelBackend",
        )
    )
    @mock.patch("social_core.backends.utils.BACKENDSCACHE", {})
    def test_disconnect_rejects_association_only_remaining_association(self):
        user = get_user_model()._default_manager.create_user(username="passwordless")
        working = UserSocialAuth.objects.create(user=user, provider="facebook", uid="working-facebook")
        self.assertFalse(user.has_usable_password())
        self.client.force_login(user)

        for individual in (False, True):
            with self.subTest(individual=individual):
                association_only = UserSocialAuth.objects.create(user=user, provider="drip", uid="association-only")
                url_name = "social:disconnect_individual" if individual else "social:disconnect"
                kwargs = {"backend": "facebook"}
                if individual:
                    kwargs["association_id"] = working.pk

                response = self.client.post(reverse(url_name, kwargs=kwargs))

                self.assertEqual(response.status_code, 403)
                self.assertQuerySetEqual(user.social_auth.order_by("pk"), [working, association_only])

                kwargs = {"backend": "drip"}
                if individual:
                    kwargs["association_id"] = association_only.pk
                response = self.client.post(reverse(url_name, kwargs=kwargs))

                self.assertEqual(response.status_code, 302)
                self.assertQuerySetEqual(user.social_auth.all(), [working])

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


@override_settings(
    DEBUG=False,
    SOCIAL_AUTH_FACEBOOK_KEY="1",
    SOCIAL_AUTH_FACEBOOK_SECRET="2",  # ruff: ignore[hardcoded-password-func-arg]
    SOCIAL_AUTH_FACEBOOK_EXTRA_DATA=["expires", "expires_on"],
    SOCIAL_AUTH_SESSION_EXPIRATION=True,
    SOCIAL_AUTH_MAX_SESSION_LENGTH=3600,
    SOCIAL_AUTH_LOGIN_ERROR_URL="/login-error/",
)
class TestSessionExpiration(TestCase):
    def complete_login(self, field: str, expiry: int | str) -> tuple[Client, HttpResponse]:
        client = Client(enforce_csrf_checks=True)
        session = client.session
        session["facebook_state"] = "1"
        session["existing_data"] = "preserved"
        session.save()
        with mock.patch("social_core.backends.base.BaseAuth.request") as provider_request:
            provider_request.return_value.json.side_effect = [
                {"access_token": "123", field: expiry},
                {"id": "facebook-expiry-user", field: expiry},
            ]
            response = client.get(
                reverse("social:complete", kwargs={"backend": "facebook"}),
                {"code": "2", "state": "1"},
            )
        return client, response

    def test_invalid_expiry_does_not_authenticate(self):
        for error_url in ("/login-error/", None):
            for field in ("expires_in", "expires", "expires_on"):
                for expiry in ("unknown", "", "3600.0"):
                    with (
                        self.subTest(error_url=error_url, field=field, expiry=expiry),
                        override_settings(SOCIAL_AUTH_LOGIN_ERROR_URL=error_url),
                        self.assertLogs("social", level="ERROR") as logs,
                    ):
                        client, response = self.complete_login(field, expiry)
                        if error_url:
                            self.assertRedirects(response, error_url, fetch_redirect_response=False)
                        else:
                            self.assertEqual(response.status_code, 500)
                        self.assertIn("code=invalid_expiry", logs.output[0])
                        self.assertFalse(response.wsgi_request.user.is_authenticated)
                        self.assertNotIn("_auth_user_id", client.session)
                        self.assertNotIn("social_auth_last_login_backend", client.session)
                        self.assertEqual(client.session["existing_data"], "preserved")

    def test_valid_expiry_respects_maximum(self):
        client, response = self.complete_login("expires_in", 7200)

        self.assertRedirects(response, "/accounts/profile/", fetch_redirect_response=False)
        self.assertIn("_auth_user_id", client.session)
        self.assertEqual(client.session.get_expiry_age(), 3600)
        self.assertEqual(response.cookies[settings.SESSION_COOKIE_NAME]["max-age"], 3600)

    @override_settings(SOCIAL_AUTH_SESSION_EXPIRATION=False)
    def test_disabled_expiration_ignores_invalid_provider_expiry(self):
        client, response = self.complete_login("expires_in", "unknown")

        self.assertRedirects(response, "/accounts/profile/", fetch_redirect_response=False)
        self.assertIn("_auth_user_id", client.session)
        self.assertEqual(client.session.get_expiry_age(), 3600)


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
    @override_settings(
        LOGIN_REDIRECT_URL="/welcome/",
        SOCIAL_AUTH_ALLOWED_REDIRECT_HOSTS=["frontend.example.com:8443"],
        SOCIAL_AUTH_MOCK_OIDC_ALLOWED_REDIRECT_HOSTS=["backend.example.com:9443"],
    )
    def test_launch_targets_require_exact_authority(self):
        user = get_user_model()._default_manager.create_user(username="launch_authority")
        cases = [
            ("testserver", "https://testserver/dashboard", True),
            ("testserver", "https://testserver:8443/dashboard", False),
            ("testserver", "https://testserver:443/dashboard", False),
            ("testserver", "https://user@testserver/dashboard", False),
            ("testserver", "https://TESTSERVER/dashboard", False),
            ("testserver:8443", "https://testserver:8443/dashboard", True),
            ("testserver:8443", "https://testserver/dashboard", False),
            ("testserver:8443", "https://testserver:9443/dashboard", False),
            ("testserver", "https://frontend.example.com:8443/dashboard", True),
            ("testserver", "https://frontend.example.com:9443/dashboard", False),
            ("testserver", "https://backend.example.com:9443/dashboard", True),
            ("testserver", "https://backend.example.com:8443/dashboard", False),
        ]
        for authenticated in (False, True):
            if authenticated:
                self.client.force_login(user, backend="django.contrib.auth.backends.ModelBackend")
            for bridge, parameter in (("idp_launch", "target_link_uri"), ("app_launch", "next")):
                url = reverse(f"social:{bridge}", kwargs={"backend": "mock-oidc"})
                for host, target, accepted in cases:
                    with self.subTest(authenticated=authenticated, bridge=bridge, host=host, target=target):
                        headers = {"Host": host, "Sec-Fetch-Site": "same-origin"}
                        if bridge == "idp_launch":
                            headers["Sec-Fetch-Site"] = "cross-site"
                        response = self.client.get(
                            url,
                            {"iss": "https://idp.example.com", parameter: target},
                            secure=True,
                            headers=headers,
                        )
                        if authenticated:
                            self.assertEqual(response.status_code, 302)
                            self.assertEqual(response["Location"], target if accepted else "/welcome/")
                        else:
                            self.assertEqual(response.status_code, 200)
                            self.assertEqual(response.context["params"].get("next"), target if accepted else None)
                            self.assertContains(response, 'name="next"', count=1 if accepted else 0)
                            self.assertContains(response, f'value="{target}"', count=1 if accepted else 0)

    @override_settings(ROOT_URLCONF=LaunchRedirectURLConf)
    def test_authenticated_launch_targets_are_literal_urls(self):
        user = get_user_model()._default_manager.create_user(username="literal_target")
        self.client.force_login(user, backend="django.contrib.auth.backends.ModelBackend")
        self.assertEqual(reverse("dashboard"), "/welcome/")
        for bridge, parameter in (("idp_launch", "target_link_uri"), ("app_launch", "next")):
            url = reverse(f"social:{bridge}", kwargs={"backend": "mock-oidc"})
            for target in ("unknown", "dashboard", "?tab=x", "#top", "/dashboard"):
                with self.subTest(bridge=bridge, target=target):
                    response = self.client.get(
                        url,
                        {"iss": "https://idp.example.com", parameter: target},
                        headers={"sec-fetch-site": "same-origin"},
                    )
                    self.assertEqual(response.status_code, 302)
                    self.assertEqual(response["Location"], target)

    @override_settings(LOGIN_REDIRECT_URL="admin:index")
    def test_authenticated_launch_fallback_resolves_url_name(self):
        user = get_user_model()._default_manager.create_user(username="named_fallback")
        self.client.force_login(user, backend="django.contrib.auth.backends.ModelBackend")
        for bridge, parameter in (("idp_launch", "target_link_uri"), ("app_launch", "next")):
            url = reverse(f"social:{bridge}", kwargs={"backend": "mock-oidc"})
            for target in (None, "", "https://evil.example/phishing"):
                with self.subTest(bridge=bridge, target=target):
                    params = {"iss": "https://idp.example.com"}
                    if target is not None:
                        params[parameter] = target
                    response = self.client.get(url, params, headers={"sec-fetch-site": "same-origin"})
                    self.assertEqual(response.status_code, 302)
                    self.assertEqual(response["Location"], "/admin/")

    @override_settings(
        LOGIN_REDIRECT_URL="nonexistent-route",
        SOCIAL_AUTH_ALLOWED_REDIRECT_HOSTS=["frontend.example.com"],
    )
    def test_authenticated_launch_explicit_target_skips_fallback_resolution(self):
        user = get_user_model()._default_manager.create_user(username="explicit_target")
        self.client.force_login(user, backend="django.contrib.auth.backends.ModelBackend")
        for bridge, parameter in (("idp_launch", "target_link_uri"), ("app_launch", "next")):
            url = reverse(f"social:{bridge}", kwargs={"backend": "mock-oidc"})
            for target in ("dashboard", "https://frontend.example.com/portal"):
                with self.subTest(bridge=bridge, target=target):
                    response = self.client.get(
                        url,
                        {"iss": "https://idp.example.com", parameter: target},
                        headers={"sec-fetch-site": "same-origin"},
                    )
                    self.assertEqual(response.status_code, 302)
                    self.assertEqual(response["Location"], target)

    def test_anonymous_launch_preserves_relative_target(self):
        for bridge, parameter in (("idp_launch", "target_link_uri"), ("app_launch", "next")):
            with self.subTest(bridge=bridge):
                url = reverse(f"social:{bridge}", kwargs={"backend": "mock-oidc"})
                response = self.client.get(
                    url,
                    {"iss": "https://idp.example.com", parameter: "dashboard"},
                    headers={"sec-fetch-site": "same-origin"},
                )
                self.assertContains(response, 'name="next" value="dashboard"')

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
