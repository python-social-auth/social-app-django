import logging
from unittest import mock

from asgiref.sync import iscoroutinefunction
from django.contrib.messages import MessageFailure
from django.http import HttpResponse, HttpResponseRedirect
from django.test import AsyncRequestFactory, RequestFactory, TestCase, override_settings
from django.urls import reverse
from social_core.exceptions import AuthCanceled

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
