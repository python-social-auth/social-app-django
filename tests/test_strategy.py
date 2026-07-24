from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpResponse, QueryDict
from django.test import RequestFactory, TestCase
from django.utils.translation import gettext_lazy
from social_core.utils import PARTIAL_TOKEN_PENDING_CONFIRMATION_SESSION_NAME

from social_django.strategy import PARTIAL_PIPELINE_CONFIRMATION_NONCE_PARAMETER
from social_django.utils import load_backend, load_strategy


class TestStrategy(TestCase):
    def setUp(self):
        self.request_factory = RequestFactory()
        self.request = self.request_factory.get("/", data={"x": "1"})
        SessionMiddleware(lambda: None).process_request(self.request)
        self.strategy = load_strategy(request=self.request)

    def test_request_methods(self):
        self.assertEqual(self.strategy.request_port(), "80")
        self.assertEqual(self.strategy.request_path(), "/")
        self.assertEqual(self.strategy.request_host(), "testserver")
        self.assertEqual(self.strategy.request_is_secure(), False)
        self.assertEqual(self.strategy.request_data(), QueryDict("x=1"))
        self.assertEqual(self.strategy.request_get(), QueryDict("x=1"))
        self.assertEqual(self.strategy.request_post(), {})
        self.request.method = "POST"
        self.assertEqual(self.strategy.request_data(merge=False), {})

    def test_build_absolute_uri(self):
        self.assertEqual(self.strategy.build_absolute_uri("/"), "http://testserver/")

    def test_settings(self):
        with self.settings(LOGIN_ERROR_URL="/"):
            self.assertEqual(self.strategy.get_setting("LOGIN_ERROR_URL"), "/")
        with self.settings(LOGIN_ERROR_URL=gettext_lazy("/")):
            self.assertEqual(self.strategy.get_setting("LOGIN_ERROR_URL"), "/")

    def test_session_methods(self):
        self.strategy.session_set("k", "v")
        self.assertEqual(self.strategy.session_get("k"), "v")
        self.assertEqual(self.strategy.session_setdefault("k", "x"), "v")
        self.assertEqual(self.strategy.session_pop("k"), "v")

    def test_get_session_id_creates_session(self):
        self.assertIsNone(self.strategy.session.session_key)

        session_id = self.strategy.get_session_id()

        self.assertIsNotNone(session_id)
        self.assertTrue(self.strategy.session.exists(session_id))

    def test_get_session_id_reuses_existing_session(self):
        self.strategy.session.create()
        session_id = self.strategy.session.session_key

        self.assertEqual(self.strategy.get_session_id(), session_id)

    def test_new_session_can_be_restored_without_cookie(self):
        session_id = self.strategy.get_session_id()
        if session_id is None:
            self.fail("session ID was not created")
        self.strategy.session_set("saml_authn_request_id", "TEST_ID")
        self.strategy.session.save()

        callback_request = self.request_factory.post("/")
        SessionMiddleware(lambda _request: HttpResponse()).process_request(callback_request)
        callback_strategy = load_strategy(request=callback_request)
        callback_strategy.restore_session(session_id, {})

        self.assertEqual(callback_strategy.session_get("saml_authn_request_id"), "TEST_ID")
        self.assertNotEqual(callback_strategy.get_session_id(), session_id)

    def test_random_string(self):
        rs1 = self.strategy.random_string()
        self.assertEqual(len(rs1), 12)
        self.assertNotEqual(rs1, self.strategy.random_string())

    def test_session_value(self):
        user_model = get_user_model()
        user = user_model._default_manager.create_user(username="test")  # noqa: SLF001
        ctype = ContentType.objects.get_for_model(user_model)

        val = self.strategy.to_session_value(val=user)
        self.assertEqual(val, {"pk": user.pk, "ctype": ctype.pk})

        instance = self.strategy.from_session_value(val=val)
        self.assertEqual(instance, user)

    def test_session_value_flattens_request_data(self):
        request = self.request_factory.get(
            "/complete/facebook/",
            data={"partial_token": "external-token", "verification_code": "code"},
        )
        SessionMiddleware(lambda: None).process_request(request)
        strategy = load_strategy(request=request)

        val = strategy.to_session_value(strategy.request_data())

        self.assertEqual(
            val,
            {"partial_token": "external-token", "verification_code": "code"},
        )

    def test_get_language(self):
        self.assertEqual(self.strategy.get_language(), "en-us")

    def test_html(self):
        result = self.strategy.render_html(tpl="test.html")
        self.assertEqual(result, "test\n")

        result = self.strategy.render_html(html="xoxo")
        self.assertEqual(result, "xoxo")

        with self.assertRaisesMessage(ValueError, "Missing template or html parameters"):
            self.strategy.render_html()

        result = self.strategy.html(content="xoxo")
        self.assertIsInstance(result, HttpResponse)
        self.assertEqual(result.content, b"xoxo")

        ctx = {"x": 1}
        result = self.strategy.tpl.render_template(tpl="test.html", context=ctx)
        self.assertEqual(result, "test\n")

        result = self.strategy.tpl.render_string(html="xoxo", context=ctx)
        self.assertEqual(result, "xoxo")

    def test_partial_pipeline_external_resume_confirmation(self):
        request = self.request_factory.get(
            "/complete/facebook/",
            data={"partial_token": "external-token", "verification_code": "code"},
        )
        SessionMiddleware(lambda: None).process_request(request)
        strategy = load_strategy(request=request)
        backend = load_backend(strategy=strategy, name="facebook", redirect_uri="/")

        response = strategy.partial_pipeline_external_resume_confirmation(backend, mock.Mock(), strategy.request_data())

        self.assertIsInstance(response, HttpResponse)
        nonce = strategy.session_get(PARTIAL_TOKEN_PENDING_CONFIRMATION_SESSION_NAME)
        self.assertTrue(nonce)
        content = response.content.decode()
        self.assertIn('action="/complete/facebook/"', content)
        self.assertIn('name="partial_pipeline_confirm"', content)
        self.assertIn(f'name="{PARTIAL_PIPELINE_CONFIRMATION_NONCE_PARAMETER}"', content)
        self.assertIn(f'value="{nonce}"', content)
        self.assertNotIn("partial_token", content)
        self.assertNotIn("verification_code", content)

    def test_partial_pipeline_external_resume_confirmation_uses_custom_parameter(self):
        request = self.request_factory.get("/complete/facebook/")
        SessionMiddleware(lambda: None).process_request(request)
        strategy = load_strategy(request=request)
        backend = load_backend(strategy=strategy, name="facebook", redirect_uri="/")

        with self.settings(SOCIAL_AUTH_PARTIAL_PIPELINE_EXTERNAL_RESUME_CONFIRMATION_PARAMETER="continue_auth"):
            response = strategy.partial_pipeline_external_resume_confirmation(
                backend, mock.Mock(), strategy.request_data()
            )

        content = response.content.decode()
        self.assertIn('name="continue_auth"', content)
        self.assertNotIn('name="partial_pipeline_confirm"', content)
        self.assertIn(f'name="{PARTIAL_PIPELINE_CONFIRMATION_NONCE_PARAMETER}"', content)

    def test_partial_pipeline_external_resume_confirmed(self):
        request = self.request_factory.post(
            "/complete/facebook/",
            data={
                "partial_pipeline_confirm": "1",
                PARTIAL_PIPELINE_CONFIRMATION_NONCE_PARAMETER: "nonce",
            },
        )
        SessionMiddleware(lambda: None).process_request(request)
        strategy = load_strategy(request=request)
        backend = load_backend(strategy=strategy, name="facebook", redirect_uri="/")
        strategy.session_set(PARTIAL_TOKEN_PENDING_CONFIRMATION_SESSION_NAME, "nonce")

        self.assertTrue(strategy.partial_pipeline_external_resume_confirmed(backend, strategy.request_data()))

    def test_partial_pipeline_external_resume_confirmed_uses_custom_parameter(self):
        request = self.request_factory.post(
            "/complete/facebook/",
            data={
                "continue_auth": "1",
                PARTIAL_PIPELINE_CONFIRMATION_NONCE_PARAMETER: "nonce",
            },
        )
        SessionMiddleware(lambda: None).process_request(request)
        strategy = load_strategy(request=request)
        backend = load_backend(strategy=strategy, name="facebook", redirect_uri="/")
        strategy.session_set(PARTIAL_TOKEN_PENDING_CONFIRMATION_SESSION_NAME, "nonce")

        with self.settings(SOCIAL_AUTH_PARTIAL_PIPELINE_EXTERNAL_RESUME_CONFIRMATION_PARAMETER="continue_auth"):
            self.assertTrue(strategy.partial_pipeline_external_resume_confirmed(backend, strategy.request_data()))

    def test_partial_pipeline_external_resume_confirmation_without_request(self):
        strategy = load_strategy()
        backend = load_backend(strategy=strategy, name="facebook", redirect_uri="/")

        self.assertIsNone(strategy.partial_pipeline_external_resume_confirmation(backend, mock.Mock(), {}))

    def test_partial_pipeline_external_resume_confirmed_without_request(self):
        strategy = load_strategy()
        backend = load_backend(strategy=strategy, name="facebook", redirect_uri="/")
        strategy.session_set(PARTIAL_TOKEN_PENDING_CONFIRMATION_SESSION_NAME, "nonce")

        self.assertFalse(
            strategy.partial_pipeline_external_resume_confirmed(
                backend,
                {
                    "partial_pipeline_confirm": "1",
                    PARTIAL_PIPELINE_CONFIRMATION_NONCE_PARAMETER: "nonce",
                },
            )
        )

    def test_partial_pipeline_external_resume_confirmation_rejects_get(self):
        strategy = load_strategy(request=self.request)
        backend = load_backend(strategy=strategy, name="facebook", redirect_uri="/")
        strategy.session_set(PARTIAL_TOKEN_PENDING_CONFIRMATION_SESSION_NAME, "nonce")

        self.assertFalse(strategy.partial_pipeline_external_resume_confirmed(backend, strategy.request_data()))

    def test_partial_pipeline_external_resume_confirmation_rejects_missing_parameter(self):
        request = self.request_factory.post(
            "/complete/facebook/",
            data={PARTIAL_PIPELINE_CONFIRMATION_NONCE_PARAMETER: "nonce"},
        )
        SessionMiddleware(lambda: None).process_request(request)
        strategy = load_strategy(request=request)
        backend = load_backend(strategy=strategy, name="facebook", redirect_uri="/")
        strategy.session_set(PARTIAL_TOKEN_PENDING_CONFIRMATION_SESSION_NAME, "nonce")

        self.assertFalse(strategy.partial_pipeline_external_resume_confirmed(backend, strategy.request_data()))

    def test_partial_pipeline_external_resume_confirmation_rejects_missing_nonce(self):
        request = self.request_factory.post(
            "/complete/facebook/",
            data={"partial_pipeline_confirm": "1"},
        )
        SessionMiddleware(lambda: None).process_request(request)
        strategy = load_strategy(request=request)
        backend = load_backend(strategy=strategy, name="facebook", redirect_uri="/")
        strategy.session_set(PARTIAL_TOKEN_PENDING_CONFIRMATION_SESSION_NAME, "nonce")

        self.assertFalse(strategy.partial_pipeline_external_resume_confirmed(backend, strategy.request_data()))

    def test_partial_pipeline_external_resume_confirmation_rejects_wrong_nonce(self):
        request = self.request_factory.post(
            "/complete/facebook/",
            data={
                "partial_pipeline_confirm": "1",
                PARTIAL_PIPELINE_CONFIRMATION_NONCE_PARAMETER: "wrong",
            },
        )
        SessionMiddleware(lambda: None).process_request(request)
        strategy = load_strategy(request=request)
        backend = load_backend(strategy=strategy, name="facebook", redirect_uri="/")
        strategy.session_set(PARTIAL_TOKEN_PENDING_CONFIRMATION_SESSION_NAME, "nonce")

        self.assertFalse(strategy.partial_pipeline_external_resume_confirmed(backend, strategy.request_data()))

    def test_authenticate(self):
        backend = load_backend(strategy=self.strategy, name="facebook", redirect_uri="/")
        user = mock.Mock()
        with mock.patch("social_core.backends.base.BaseAuth.pipeline", return_value=user):
            result = self.strategy.authenticate(backend=backend, response=mock.Mock())
            self.assertEqual(result, user)
            self.assertEqual(result.backend, "social_core.backends.facebook.FacebookOAuth2")

    def test_clean_authenticate_args(self):
        args, kwargs = self.strategy.clean_authenticate_args(self.request)
        self.assertEqual(args, ())
        self.assertEqual(kwargs, {"request": self.request})

    def test_clean_authenticate_args_none(self):
        # When called from continue_pipeline(), request is None. Issue #222
        args, kwargs = self.strategy.clean_authenticate_args(None)
        self.assertEqual(args, ())
        self.assertEqual(kwargs, {"request": None})

    def test_session_creation_without_request(self):
        strategy = load_strategy()
        self.assertIsNone(strategy.request)
        self.assertIsNotNone(strategy.session)
