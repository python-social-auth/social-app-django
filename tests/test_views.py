# -*- coding: utf-8 -*-
import unittest.mock as mock
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractBaseUser

from django.test import TestCase, override_settings

from social_django.compat import reverse
from social_django.models import UserSocialAuth
from social_django.views import get_session_timeout
from .compat import base_url


@override_settings(SOCIAL_AUTH_FACEBOOK_KEY='1',
                   SOCIAL_AUTH_FACEBOOK_SECRET='2')
class TestViews(TestCase):
    def setUp(self):
        session = self.client.session
        session['facebook_state'] = '1'
        session.save()

    def test_begin_view(self):
        response = self.client.get(reverse('social:begin', kwargs={'backend': 'facebook'}))
        self.assertEqual(response.status_code, 302)

        url = reverse('social:begin', kwargs={'backend': 'blabla'})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    @mock.patch('social_core.backends.base.BaseAuth.request')
    def test_complete(self, mock_request):
        url = reverse('social:complete', kwargs={'backend': 'facebook'})
        url += '?code=2&state=1'
        mock_request.return_value.json.return_value = {'access_token': '123'}
        with mock.patch('django.contrib.sessions.backends.base.SessionBase'
                        '.set_expiry', side_effect=[OverflowError, None]):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.url, base_url + '/accounts/profile/')

    @mock.patch('social_core.backends.base.BaseAuth.request')
    def test_disconnect(self, mock_request):
        user_model = get_user_model()
        user = user_model.objects.create_user(username='test', password='pwd')
        UserSocialAuth.objects.create(user=user, provider='facebook')
        self.client.login(username='test', password='pwd')

        url = reverse('social:disconnect', kwargs={'backend': 'facebook'})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, 'http://testserver/accounts/profile/')

        url = reverse('social:disconnect_individual',
                      kwargs={'backend': 'facebook', 'association_id': '123'})
        hup = AbstractBaseUser.has_usable_password
        del AbstractBaseUser.has_usable_password
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, 'http://testserver/accounts/profile/')
        AbstractBaseUser.has_usable_password = hup


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
