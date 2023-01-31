import logging
from unittest import mock

from django.contrib.messages import MessageFailure
from django.http import HttpResponseRedirect
from django.test import TestCase, override_settings
from django.urls import reverse
from social_core.exceptions import AuthCanceled


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
