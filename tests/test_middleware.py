import logging
from unittest import mock

from asgiref.sync import iscoroutinefunction
from django.contrib.messages import MessageFailure
from django.http import HttpResponse, HttpResponseRedirect
from django.test import AsyncRequestFactory, RequestFactory, TestCase, override_settings
from django.urls import reverse
from social_core.exceptions import AuthCanceled

from social_django.middleware import SocialAuthExceptionMiddleware


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
