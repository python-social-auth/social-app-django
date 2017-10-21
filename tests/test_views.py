# -*- coding: utf-8 -*-
import mock

from django.test import Client
from django.test import TestCase

from social_django.compat import reverse
from social_django.views import get_session_timeout


class TestConfig(TestCase):
    client_class = Client

    def setUp(self):
        session = self.client.session
        session['somekey'] = 'test'
        session.save()

    def test_begin_view(self):
        response = self.client.get(reverse('social:begin', kwargs={'backend': 'facebook'}))
        self.assertEqual(response.status_code, 302)


class TestGetSessionTimeout(TestCase):
    """
    Ensure that the branching logic of get_session_timeout behaves as expected.
    """

    def setUp(self):
        self.social_user = mock.MagicMock()
        self.social_user.expiration_datetime.return_value = None
        super(TestGetSessionTimeout, self).setUp()

    def set_user_expiration(self, seconds):
        self.social_user.expiration_datetime.return_value = mock.MagicMock(
            total_seconds = mock.MagicMock(return_value=seconds)
        )

    def test_expiration_disabled_no_max(self):
        self.set_user_expiration(60)
        expiration_length = get_session_timeout(
            self.social_user,
            enable_session_expiration=False
        )
        self.assertIsNone(expiration_length)

    def test_expiration_disabled_with_max(self):
        expiration_length = get_session_timeout(
            self.social_user,
            enable_session_expiration=False,
            max_session_length=60
        )
        self.assertEqual(expiration_length, 60)

    def test_expiration_disabled_with_zero_max(self):
        expiration_length = get_session_timeout(
            self.social_user,
            enable_session_expiration=False,
            max_session_length=0
        )
        self.assertEqual(expiration_length, 0)

    def test_user_has_session_length_no_max(self):
        self.set_user_expiration(60)
        expiration_length = get_session_timeout(
            self.social_user,
            enable_session_expiration=True
        )
        self.assertEqual(expiration_length, 60)

    def test_user_has_session_length_larger_max(self):
        self.set_user_expiration(60)
        expiration_length = get_session_timeout(
            self.social_user,
            enable_session_expiration=True,
            max_session_length=90
        )
        self.assertEqual(expiration_length, 60)

    def test_user_has_session_length_smaller_max(self):
        self.set_user_expiration(60)
        expiration_length = get_session_timeout(
            self.social_user,
            enable_session_expiration=True,
            max_session_length=30
        )
        self.assertEqual(expiration_length, 30)

    def test_user_has_no_session_length_with_max(self):
        expiration_length = get_session_timeout(
            self.social_user,
            enable_session_expiration=True,
            max_session_length=60
        )
        self.assertEqual(expiration_length, 60)

    def test_user_has_no_session_length_no_max(self):
        expiration_length = get_session_timeout(
            self.social_user,
            enable_session_expiration=True
        )
        self.assertIsNone(expiration_length)
