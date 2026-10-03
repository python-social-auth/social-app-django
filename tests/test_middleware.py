import logging
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from asgiref.sync import iscoroutinefunction
from django.contrib.messages import MessageFailure
from django.http import HttpResponse, HttpResponseRedirect
from django.test import AsyncRequestFactory, RequestFactory, TestCase, override_settings
from django.urls import reverse
from social_core.exceptions import AuthCanceled, AuthProviderError, AuthResponseError

from social_django.middleware import ErrorTransport, SocialAuthExceptionMiddleware


class MockAuthCanceled(AuthCanceled):
    def __init__(self, *args, **kwargs):
        if not args:
            kwargs.setdefault("backend", None)
        super().__init__(*args, **kwargs)


@mock.patch("social_core.backends.base.BaseAuth.request", side_effect=MockAuthCanceled)
class TestMiddleware(TestCase):
    def setUp(self):
        session = self.client.session
        session["facebook_state"] = "1"
        session.save()

        self.complete_url = reverse("social:complete", kwargs={"backend": "facebook"})
        self.complete_url += "?code=2&state=1"

    def test_sync_middleware(self, mocked):
        expected = HttpResponse()
        get_response = mock.Mock(return_value=expected)
        rf = RequestFactory()
        request = rf.get("/")

        middleware = SocialAuthExceptionMiddleware(get_response)
        resp = middleware(request)

        self.assertFalse(iscoroutinefunction(middleware))
        self.assertIs(resp, expected)
        get_response.assert_called_once_with(request)

    async def test_async_middleware(self, mocked):
        expected = HttpResponse()
        get_response = mock.AsyncMock(return_value=expected)
        async_rf = AsyncRequestFactory()
        request = async_rf.get("/")

        middleware = SocialAuthExceptionMiddleware(get_response)
        resp = await middleware(request)

        self.assertTrue(iscoroutinefunction(middleware))
        self.assertIs(resp, expected)
        get_response.assert_awaited_once_with(request)

    def test_exception(self, mocked):
        with self.assertRaises(MockAuthCanceled):
            self.client.get(self.complete_url)

    @override_settings(DEBUG=True)
    def test_exception_debug(self, mocked):
        logging.disable(logging.CRITICAL)
        with self.assertRaises(MockAuthCanceled):
            self.client.get(self.complete_url)
        logging.disable(logging.NOTSET)

    @override_settings(SOCIAL_AUTH_LOGIN_ERROR_URL="/")
    def test_login_error_url(self, mocked):
        response = self.client.get(self.complete_url)
        self.assertTrue(isinstance(response, HttpResponseRedirect))
        self.assertEqual(response.url, "/")

    @override_settings(SOCIAL_AUTH_LOGIN_ERROR_URL="/")
    @mock.patch("django.contrib.messages.error", side_effect=MessageFailure)
    def test_message_failure(self, mocked_request, mocked_error):
        response = self.client.get(self.complete_url)
        self.assertTrue(isinstance(response, HttpResponseRedirect))
        self.assertEqual(
            response.url,
            "/?message=Authentication%20process%20canceled&backend=facebook",
        )

    @override_settings(
        SOCIAL_AUTH_LOGIN_ERROR_URL="/default-error",
        SOCIAL_AUTH_FACEBOOK_LOGIN_ERROR_URL="/facebook-error",
    )
    def test_backend_specific_login_error_url(self, mocked):
        response = self.client.get(self.complete_url)
        self.assertTrue(isinstance(response, HttpResponseRedirect))
        self.assertEqual(response.url, "/facebook-error")

    @override_settings(
        DEBUG=False,
        SOCIAL_AUTH_RAISE_EXCEPTIONS=False,
        SOCIAL_AUTH_FACEBOOK_RAISE_EXCEPTIONS=True,
    )
    def test_backend_specific_raise_exceptions(self, mocked):
        logging.disable(logging.CRITICAL)
        with self.assertRaises(MockAuthCanceled):
            self.client.get(self.complete_url)
        logging.disable(logging.NOTSET)

    @override_settings(
        SOCIAL_AUTH_LOGIN_ERROR_URL="/login",
        SOCIAL_AUTH_ERROR_TRANSPORT=[ErrorTransport.QUERY],
    )
    @mock.patch("django.contrib.messages.error")
    def test_error_transport_query(self, mocked_error, mocked):
        """Test query parameter transport redirects with query parameters and skips messages."""
        response = self.client.get(self.complete_url)
        self.assertTrue(isinstance(response, HttpResponseRedirect))
        self.assertEqual(
            response.url,
            "/login?message=Authentication%20process%20canceled&backend=facebook",
        )
        mocked_error.assert_not_called()

    @override_settings(
        SOCIAL_AUTH_LOGIN_ERROR_URL="/login",
        SOCIAL_AUTH_ERROR_TRANSPORT="query",
    )
    def test_error_transport_query_as_string(self, mocked):
        """Test query parameter transport configured as a string value."""
        response = self.client.get(self.complete_url)
        self.assertTrue(isinstance(response, HttpResponseRedirect))
        self.assertEqual(
            response.url,
            "/login?message=Authentication%20process%20canceled&backend=facebook",
        )

    @override_settings(
        SOCIAL_AUTH_LOGIN_ERROR_URL="/login",
        SOCIAL_AUTH_ERROR_TRANSPORT=[ErrorTransport.MESSAGES],
        SOCIAL_AUTH_FACEBOOK_ERROR_TRANSPORT=[ErrorTransport.QUERY],
    )
    def test_backend_specific_error_transport(self, mocked):
        """Test backend-specific ERROR_TRANSPORT override."""
        response = self.client.get(self.complete_url)
        self.assertTrue(isinstance(response, HttpResponseRedirect))
        self.assertEqual(
            response.url,
            "/login?message=Authentication%20process%20canceled&backend=facebook",
        )

    @override_settings(
        SOCIAL_AUTH_LOGIN_ERROR_URL="/login",
        SOCIAL_AUTH_ERROR_TRANSPORT=[ErrorTransport.MESSAGES, ErrorTransport.QUERY],
    )
    @mock.patch("django.contrib.messages.error")
    def test_error_transport_multiple(self, mocked_error, mocked):
        """Test configuring multiple transports (both messages and query)."""
        response = self.client.get(self.complete_url)
        self.assertTrue(isinstance(response, HttpResponseRedirect))
        self.assertEqual(
            response.url,
            "/login?message=Authentication%20process%20canceled&backend=facebook",
        )
        mocked_error.assert_called_once()

    @override_settings(
        SOCIAL_AUTH_LOGIN_ERROR_URL="/login",
        SOCIAL_AUTH_ERROR_TRANSPORT=[ErrorTransport.QUERY],
        SOCIAL_AUTH_ERROR_PARAM_NAME="err",
        SOCIAL_AUTH_BACKEND_PARAM_NAME="auth_backend",
    )
    def test_custom_param_names_via_settings(self, mocked):
        """Test configuring custom query parameter names via Django settings."""
        response = self.client.get(self.complete_url)
        self.assertTrue(isinstance(response, HttpResponseRedirect))
        self.assertEqual(
            response.url,
            "/login?err=Authentication%20process%20canceled&auth_backend=facebook",
        )

    @override_settings(
        SOCIAL_AUTH_LOGIN_ERROR_URL="/login",
        SOCIAL_AUTH_ERROR_TRANSPORT=[ErrorTransport.QUERY],
        SOCIAL_AUTH_FACEBOOK_ERROR_PARAM_NAME="fb_err",
        SOCIAL_AUTH_FACEBOOK_BACKEND_PARAM_NAME="fb_backend",
    )
    def test_backend_specific_custom_param_names(self, mocked):
        """Test backend-specific custom query parameter names."""
        response = self.client.get(self.complete_url)
        self.assertTrue(isinstance(response, HttpResponseRedirect))
        self.assertEqual(
            response.url,
            "/login?fb_err=Authentication%20process%20canceled&fb_backend=facebook",
        )

    def test_custom_param_names_via_subclass(self, mocked):
        """Test custom parameter names configured via subclass attributes."""

        class CustomMiddleware(SocialAuthExceptionMiddleware):
            ERROR_PARAM_NAME = "custom_err"
            BACKEND_PARAM_NAME = "custom_be"

        rf = RequestFactory()
        request = rf.get("/")
        middleware = CustomMiddleware(mock.Mock())
        result_url = middleware.append_query_params(request, "/login", "failed", "google")
        self.assertEqual(result_url, "/login?custom_err=failed&custom_be=google")

    def test_append_query_params_preserves_existing_params_and_overwrites(self, mocked):
        """Test append_query_params preserves other params and overwrites duplicate error params."""
        rf = RequestFactory()
        request = rf.get("/")
        middleware = SocialAuthExceptionMiddleware(mock.Mock())

        # Preserves existing parameters
        url = middleware.append_query_params(request, "/login?next=/dashboard&mode=dark", "Error msg", "twitter")
        self.assertEqual(
            url,
            "/login?next=%2Fdashboard&mode=dark&message=Error%20msg&backend=twitter",
        )

        # Overwrites existing message and backend parameters
        overwrite_url = middleware.append_query_params(
            request,
            "/login?message=old_error&backend=old_backend&keep=1",
            "New error",
            "github",
        )
        self.assertEqual(
            overwrite_url,
            "/login?keep=1&message=New%20error&backend=github",
        )

    def test_append_query_params_preserves_url_fragment(self, mocked):
        """Test append_query_params places query parameters before URL fragment."""
        rf = RequestFactory()
        request = rf.get("/")
        middleware = SocialAuthExceptionMiddleware(mock.Mock())

        url = middleware.append_query_params(request, "/login/#/auth-callback", "Canceled", "facebook")
        self.assertEqual(
            url,
            "/login/?message=Canceled&backend=facebook#/auth-callback",
        )

    def test_append_query_params_empty_url(self, mocked):
        """Test append_query_params handles empty or None URL gracefully."""
        rf = RequestFactory()
        request = rf.get("/")
        middleware = SocialAuthExceptionMiddleware(mock.Mock())
        self.assertIsNone(middleware.append_query_params(request, None, "msg", "be"))
        self.assertEqual(middleware.append_query_params(request, "", "msg", "be"), "")

    @override_settings(
        SOCIAL_AUTH_LOGIN_ERROR_URL="/login",
        SOCIAL_AUTH_ERROR_TRANSPORT=["invalid_transport"],
    )
    @mock.patch("django.contrib.messages.error")
    def test_invalid_error_transport_fallback(self, mocked_error, mocked):
        """Test unrecognized transport falls back to DEFAULT_TRANSPORT (messages)."""
        response = self.client.get(self.complete_url)
        self.assertTrue(isinstance(response, HttpResponseRedirect))
        self.assertEqual(response.url, "/login")
        mocked_error.assert_called_once()

    @override_settings(
        SOCIAL_AUTH_LOGIN_ERROR_URL="/login",
        SOCIAL_AUTH_ERROR_TRANSPORT=[ErrorTransport.MESSAGES, ErrorTransport.QUERY],
    )
    @mock.patch("django.contrib.messages.error", side_effect=MessageFailure)
    def test_message_failure_when_query_already_in_transports(self, mocked_error, mocked):
        """Test MessageFailure fallback when QUERY is already enabled in transports."""
        response = self.client.get(self.complete_url)
        self.assertTrue(isinstance(response, HttpResponseRedirect))
        self.assertEqual(
            response.url,
            "/login?message=Authentication%20process%20canceled&backend=facebook",
        )

    @mock.patch("django.apps.apps.is_installed", return_value=False)
    @mock.patch("social_django.middleware.social_logger.error")
    def test_dispatch_error_messages_without_messages_installed(self, mock_logger, mock_is_installed, mocked):
        """Test dispatch_error logs error when messages app is not installed and query is disabled."""
        rf = RequestFactory()
        request = rf.get("/")
        middleware = SocialAuthExceptionMiddleware(mock.Mock())
        url = middleware.dispatch_error(
            request,
            transports=[ErrorTransport.MESSAGES],
            url="/login",
            message="Failed auth",
            backend_name="facebook",
        )
        self.assertEqual(url, "/login")
        mock_logger.assert_called_once_with("Failed auth")

    @mock.patch("django.apps.apps.is_installed", return_value=False)
    def test_dispatch_error_messages_not_installed_with_query_enabled(self, mock_is_installed, mocked):
        """Test dispatch_error when messages app is not installed but query transport is enabled."""
        rf = RequestFactory()
        request = rf.get("/")
        middleware = SocialAuthExceptionMiddleware(mock.Mock())
        url = middleware.dispatch_error(
            request,
            transports=[ErrorTransport.MESSAGES, ErrorTransport.QUERY],
            url="/login",
            message="Failed auth",
            backend_name="facebook",
        )
        self.assertEqual(
            url,
            "/login?message=Failed%20auth&backend=facebook",
        )

    def test_get_transport_modes_no_strategy(self, mocked):
        """Test get_transport_modes returns DEFAULT_TRANSPORT when social_strategy is None."""
        rf = RequestFactory()
        request = rf.get("/")
        middleware = SocialAuthExceptionMiddleware(mock.Mock())
        modes = middleware.get_transport_modes(request)
        self.assertEqual(modes, list(middleware.DEFAULT_TRANSPORT))

    def test_get_transport_modes_non_iterable_raw_transport(self, mocked):
        """Test get_transport_modes handles non-iterable, non-string configuration gracefully."""
        rf = RequestFactory()
        request = rf.get("/")
        mock_strategy = mock.Mock()
        mock_strategy.setting.return_value = 12345
        request.social_strategy = mock_strategy
        middleware = SocialAuthExceptionMiddleware(mock.Mock())
        modes = middleware.get_transport_modes(request)
        self.assertEqual(modes, list(middleware.DEFAULT_TRANSPORT))

    def test_get_transport_modes_deduplication(self, mocked):
        """Test get_transport_modes deduplicates candidate transports."""
        rf = RequestFactory()
        request = rf.get("/")
        mock_strategy = mock.Mock()
        mock_strategy.setting.return_value = ["query", "query", ErrorTransport.MESSAGES, "messages"]
        request.social_strategy = mock_strategy
        middleware = SocialAuthExceptionMiddleware(mock.Mock())
        modes = middleware.get_transport_modes(request)
        self.assertEqual(modes, [ErrorTransport.QUERY, ErrorTransport.MESSAGES])

    def test_raise_exception_without_strategy(self, mocked):
        """Test raise_exception returns None when social_strategy is None."""
        rf = RequestFactory()
        request = rf.get("/")
        middleware = SocialAuthExceptionMiddleware(mock.Mock())
        self.assertIsNone(middleware.raise_exception(request, Exception("error")))

    def test_get_redirect_uri_without_strategy(self, mocked):
        """Test get_redirect_uri returns None when social_strategy is None."""
        rf = RequestFactory()
        request = rf.get("/")
        middleware = SocialAuthExceptionMiddleware(mock.Mock())
        self.assertIsNone(middleware.get_redirect_uri(request, Exception("error")))


class MetadataTransportTest(TestCase):
    def make_request(self, include_metadata, **settings):
        request = RequestFactory().get("/")
        request.backend = mock.Mock(name="backend")
        request.backend.name = "test"
        request.social_strategy = mock.Mock()
        values = {
            "RAISE_EXCEPTIONS": False,
            "LOGIN_ERROR_URL": "/login?other=1#form",
            "ERROR_TRANSPORT": "query",
            "ERROR_INCLUDE_METADATA": include_metadata,
        }
        values.update(settings)
        request.social_strategy.setting.side_effect = lambda name, default=None, **_kwargs: values.get(name, default)
        return request

    def test_metadata_is_opt_in_and_diagnostics_are_private(self):
        middleware = SocialAuthExceptionMiddleware(mock.Mock())
        error = AuthResponseError(
            None, "secret-token", code="nonce_mismatch", stage="token_validation", context={"uid": "private-user"}
        )
        for include_metadata in (False, True):
            with self.subTest(include_metadata=include_metadata):
                response = middleware.process_exception(self.make_request(include_metadata), error)
                query = parse_qs(urlsplit(response.url).query)
                self.assertEqual(query["other"], ["1"])
                self.assertEqual(urlsplit(response.url).fragment, "form")
                self.assertEqual("error_code" in query, include_metadata)
                if include_metadata:
                    self.assertEqual(query["error_code"], ["nonce_mismatch"])
                    self.assertEqual(query["error_recovery"], ["restart_login"])
                self.assertNotIn("secret-token", response.url)
                self.assertNotIn("private-user", response.url)

    def test_metadata_fallback_and_stale_values(self):
        request = self.make_request(True)
        request.social_strategy.setting.side_effect = lambda name, default=None, **_kwargs: {
            "RAISE_EXCEPTIONS": False,
            "LOGIN_ERROR_URL": "/login?error_code=old",
            "ERROR_TRANSPORT": "messages",
            "ERROR_INCLUDE_METADATA": True,
        }.get(name, default)
        middleware = SocialAuthExceptionMiddleware(mock.Mock())
        with mock.patch("social_django.middleware.messages.error", side_effect=MessageFailure):
            response = middleware.process_exception(request, AuthProviderError(code="timeout", stage="user_info"))
        self.assertEqual(parse_qs(urlsplit(response.url).query)["error_code"], ["timeout"])

    def test_metadata_collisions_preserve_configured_parameters(self):
        middleware = SocialAuthExceptionMiddleware(mock.Mock())
        error = AuthProviderError(code="timeout", stage="user_info")
        for name, value in (("ERROR_PARAM_NAME", str(error)), ("BACKEND_PARAM_NAME", "test")):
            for key in error.public_metadata():
                with self.subTest(name=name, key=key):
                    request = self.make_request(
                        True, **{name: key, "LOGIN_ERROR_URL": f"/login?{key}=old&other=1#form"}
                    )
                    response = middleware.process_exception(request, error)
                    query = parse_qs(urlsplit(response.url).query)
                    self.assertEqual(query[key], [value])
                    self.assertEqual(query["other"], ["1"])
                    self.assertEqual(urlsplit(response.url).fragment, "form")
                    for metadata_key, metadata_value in error.public_metadata().items():
                        if metadata_key != key:
                            self.assertEqual(query[metadata_key], [metadata_value])

    def test_absent_metadata_keys_remove_stale_redirect_values(self):
        middleware = SocialAuthExceptionMiddleware(mock.Mock())
        error = AuthProviderError(code="timeout", stage="user_info")
        url = "/login?error_code=old&error_source=old&error_stage=old&error_recovery=old&other=1#form"
        for enabled in (False, True):
            for metadata in ({}, {"error_code": "timeout"}):
                with self.subTest(enabled=enabled, metadata=metadata):
                    request = self.make_request(enabled, LOGIN_ERROR_URL=url)
                    with mock.patch.object(error, "public_metadata", return_value=metadata):
                        response = middleware.process_exception(request, error)
                    query = parse_qs(urlsplit(response.url).query)
                    for key in ("error_code", "error_source", "error_stage", "error_recovery"):
                        if enabled:
                            self.assertEqual(query.get(key), [metadata[key]] if key in metadata else None)
                        else:
                            self.assertEqual(query[key], ["old"])
                    self.assertEqual(query["other"], ["1"])
                    self.assertEqual(urlsplit(response.url).fragment, "form")
