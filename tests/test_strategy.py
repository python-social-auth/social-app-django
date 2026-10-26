import json
from unittest import mock

from django.contrib.auth import authenticate as django_authenticate
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpResponse, QueryDict
from django.test import RequestFactory, TestCase
from django.utils.translation import gettext_lazy
from social_core.pipeline.utils import partial_prepare
from social_core.utils import PARTIAL_TOKEN_PENDING_CONFIRMATION_SESSION_NAME

from social_django.models import Partial, UserSocialAuth
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
        for value in (None, ""):
            with self.subTest(value=value), self.settings(LOGIN_ERROR_URL=value):
                self.assertEqual(self.strategy.get_setting("LOGIN_ERROR_URL"), value)

    def test_session_methods(self):
        self.strategy.session_set("k", "v")
        self.assertEqual(self.strategy.session_get("k"), "v")
        self.assertEqual(self.strategy.session_setdefault("k", "x"), "v")
        self.assertEqual(self.strategy.session_pop("k"), "v")

    def test_random_string(self):
        rs1 = self.strategy.random_string()
        self.assertEqual(len(rs1), 12)
        self.assertNotEqual(rs1, self.strategy.random_string())

    def test_session_value(self):
        user_model = get_user_model()
        user = user_model._default_manager.create_user(username="test")
        ctype = ContentType.objects.get_for_model(user_model)

        val = self.strategy.to_session_value(val=user)
        self.assertEqual(
            val,
            {
                "__social_django_session_value__": 1,
                "kind": "model",
                "value": {"pk": user.pk, "ctype": ctype.pk},
            },
        )

        instance = self.strategy.from_session_value(val=json.loads(json.dumps(val)))
        self.assertEqual(instance, user)

    def test_session_value_preserves_plain_data(self):
        user = get_user_model().objects.create_user(username="test")
        reference = {"pk": user.pk, "ctype": ContentType.objects.get_for_model(user).pk}
        envelope = {"__social_django_session_value__": 1, "kind": "model", "value": reference}
        values = (
            None,
            False,
            1,
            "value",
            {},
            {"provider": "facebook", "uid": "test"},
            reference,
            {**reference, "email": "test@example.com"},
            {"pk": "missing", "ctype": "invalid"},
            envelope,
            {"__social_django_session_value__": "invalid"},
            {"__social_django_session_value__": 1, "kind": "plain", "value": envelope},
            {"nested": envelope},
            [reference, envelope],
        )
        for value in values:
            with self.subTest(value=value), self.assertNumQueries(0):
                encoded = self.strategy.to_session_value(value)
                decoded = self.strategy.from_session_value(json.loads(json.dumps(encoded)))
                self.assertEqual(decoded, value)

    def test_from_session_value_preserves_legacy_request_data(self):
        for value in (
            {"pk": "1", "ctype": "1"},
            {"pk": "missing", "ctype": "invalid"},
            {"pk": 1, "ctype": "1"},
            {"pk": 1, "ctype": True},
            {"pk": 1, "ctype": 1.0},
            {"pk": 1, "ctype": 1, "extra": "data"},
            {"pk": 1},
            {"ctype": 1},
            {"nested": {"pk": 1, "ctype": 1}},
        ):
            with self.subTest(value=value), self.assertNumQueries(0):
                self.assertIs(self.strategy.from_session_value(value), value)

    def test_from_session_value_preserves_unsupported_envelopes(self):
        envelope = {
            "__social_django_session_value__": 1,
            "kind": "model",
            "value": {"pk": 1, "ctype": 1},
        }
        values = (
            {"__social_django_session_value__": 1},
            {**envelope, "extra": "data"},
            {**envelope, "__social_django_session_value__": True},
            {**envelope, "__social_django_session_value__": 1.0},
            {**envelope, "__social_django_session_value__": "1"},
            {**envelope, "__social_django_session_value__": 2},
            {**envelope, "kind": "unknown"},
            {**envelope, "kind": []},
            {**envelope, "value": None},
            {**envelope, "value": {"pk": 1, "ctype": "1"}},
            {**envelope, "value": {"pk": 1, "ctype": True}},
            {**envelope, "value": {"pk": 1, "ctype": 1, "extra": "data"}},
            {**envelope, "kind": "plain", "value": []},
            {**envelope, "pk": 1, "ctype": 1},
        )
        for value in values:
            with self.subTest(value=value), self.assertNumQueries(0):
                self.assertIs(self.strategy.from_session_value(value), value)

    def test_session_value_preserves_model_lookup_errors(self):
        user_model = get_user_model()
        user = user_model.objects.create_user(username="test")
        ctype = ContentType.objects.get_for_model(user)
        stale = ContentType.objects.create(app_label="missing", model="missing")
        cases = (
            ({"pk": user.pk + 1, "ctype": ctype.pk}, user_model.DoesNotExist),
            ({"pk": user.pk, "ctype": stale.pk + 1}, ContentType.DoesNotExist),
            ({"pk": user.pk, "ctype": stale.pk}, TypeError),
        )
        for reference, error in cases:
            for value in (
                reference,
                {"__social_django_session_value__": 1, "kind": "model", "value": reference},
            ):
                with self.subTest(value=value), self.assertRaises(error):
                    self.strategy.from_session_value(value)

    def test_partial_round_trip_with_model_and_plain_values(self):
        user = get_user_model().objects.create_user(username="test")
        social = UserSocialAuth.objects.create(user=user, provider="facebook", uid="test")
        reference = {"pk": user.pk, "ctype": ContentType.objects.get_for_model(user).pk}
        for probe in (
            {"pk": "missing", "ctype": "invalid"},
            {"__social_django_session_value__": "1", "kind": "model", "value": "request"},
        ):
            with self.subTest(probe=probe):
                request = self.request_factory.get("/complete/facebook/", data=probe)
                SessionMiddleware(lambda: None).process_request(request)
                strategy = load_strategy(request=request)
                backend = load_backend(strategy=strategy, name="facebook", redirect_uri="/")
                partial = partial_prepare(strategy, backend, 0, user, social, user, response=reference)
                strategy.storage.partial.store(partial)

                loaded = strategy.partial_load(partial.token)

                self.assertEqual(loaded.args, [user])
                self.assertEqual(loaded.kwargs["user"], user)
                self.assertEqual(loaded.kwargs["social"], social)
                self.assertEqual(loaded.kwargs["response"], reference)
                self.assertEqual(loaded.request_data, probe)

    def test_partial_load_preserves_legacy_values(self):
        user = get_user_model().objects.create_user(username="test")
        social = UserSocialAuth.objects.create(user=user, provider="facebook", uid="test")
        reference = {"pk": user.pk, "ctype": ContentType.objects.get_for_model(user).pk}
        backend = load_backend(strategy=self.strategy, name="facebook", redirect_uri="/")
        probe = {"pk": "missing", "ctype": "invalid", "email": "test@example.com"}
        for legacy_request in (False, True):
            with self.subTest(legacy_request=legacy_request):
                data = {
                    "args": [reference],
                    "kwargs": {
                        "user": user.pk,
                        "social": {"provider": social.provider, "uid": social.uid},
                        "response": probe,
                    },
                }
                if legacy_request:
                    data["kwargs"]["request"] = probe
                else:
                    data["request_data"] = probe
                partial = Partial.objects.create(
                    token=Partial.generate_token(), backend=backend.name, next_step=0, data=data
                )

                loaded = self.strategy.partial_load(partial.token)

                self.assertEqual(loaded.args, [user])
                self.assertEqual(loaded.kwargs["user"], user)
                self.assertEqual(loaded.kwargs["social"], social)
                self.assertEqual(loaded.kwargs["response"], probe)
                self.assertEqual(loaded.request_data, probe)
                self.assertNotIn("request", loaded.kwargs)

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

    def test_partial_snapshot_flattens_request_data(self):
        request = self.request_factory.get(
            "/complete/facebook/",
            data={"verification_code": ["first", "last"]},
        )
        SessionMiddleware(lambda: None).process_request(request)
        strategy = load_strategy(request=request)
        backend = load_backend(strategy=strategy, name="facebook", redirect_uri="/")
        partial = partial_prepare(strategy, backend, 0)
        self.assertEqual(partial.data["request_data"], {"verification_code": "last"})
        self.assertNotIn("request", partial.kwargs)

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

    def test_html_missing_template_falls_back_to_string(self):
        result = self.strategy.render_html(tpl="missing.html", html="Hello {{ name }}", context={"name": "world"})
        self.assertEqual(result, "Hello world")

    def test_html_with_headers(self):
        result = self.strategy.html_with_headers("xoxo", {"Cache-Control": "no-store"})
        self.assertEqual(result.content, b"xoxo")
        self.assertEqual(result["Cache-Control"], "no-store")

    def test_html_template_type_error_falls_back_to_string(self):
        with mock.patch("social_django.strategy.loader.get_template", side_effect=TypeError):
            result = self.strategy.render_html(tpl="test.html", html="fallback")
        self.assertEqual(result, "fallback")

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

    def test_authenticate_uses_strategy_request_without_forwarding_it(self):
        backend = load_backend(strategy=self.strategy, name="facebook", redirect_uri="/")
        user = mock.Mock()
        with (
            mock.patch("social_django.strategy.authenticate", wraps=django_authenticate) as authenticate,
            mock.patch("social_core.backends.base.BaseAuth.pipeline", return_value=user) as pipeline,
        ):
            self.strategy.authenticate(
                backend=backend,
                response=mock.Mock(),
                request=QueryDict("partial_token=token"),
            )

        self.assertIs(authenticate.call_args.args[0], self.request)
        self.assertNotIn("request", pipeline.call_args.kwargs)

    def test_clean_authenticate_args(self):
        args, kwargs = self.strategy.clean_authenticate_args(self.request)
        self.assertEqual(args, ())
        self.assertEqual(kwargs, {})

    def test_clean_authenticate_args_none(self):
        # When called from continue_pipeline(), request is None. Issue #222
        args, kwargs = self.strategy.clean_authenticate_args(None)
        self.assertEqual(args, ())
        self.assertEqual(kwargs, {})

    def test_session_creation_without_request(self):
        strategy = load_strategy()
        self.assertIsNone(strategy.request)
        self.assertIsNotNone(strategy.session)
