# -*- coding: utf-8
from __future__ import unicode_literals, absolute_import

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from social_django.models import UserSocialAuth, Code, Partial


class TestSocialAuthUser(TestCase):
    def test_user_relationship_none(self):
        """Accessing User.social_user outside of the pipeline doesn't work"""
        User = get_user_model()
        user = User.objects.create_user(username="randomtester")
        with self.assertRaises(AttributeError):
            user.social_user

    def test_user_existing_relationship(self):
        """Accessing User.social_user outside of the pipeline doesn't work"""
        User = get_user_model()
        user = User.objects.create_user(username="randomtester")
        UserSocialAuth.objects.create(user=user,
                                      provider='my-provider',
                                      uid='1234')
        with self.assertRaises(AttributeError):
            user.social_user

    def test_get_social_auth(self):
        User = get_user_model()
        user = User.objects.create_user(username="randomtester")
        user_social = UserSocialAuth.objects.create(user=user,
                                                    provider='my-provider',
                                                    uid='1234')
        other = UserSocialAuth.get_social_auth('my-provider', '1234')
        self.assertEqual(other, user_social)

    def test_get_social_auth_none(self):
        other = UserSocialAuth.get_social_auth('my-provider', '1234')
        self.assertIsNone(other)

    def test_cleanup(self):
        Code.objects.create(email='first@example.com')
        Code.objects.create(email='second@example.com')
        code = Code.objects.create(email='expire@example.com')
        code.timestamp -= timedelta(days=30)
        code.save()

        Partial.objects.create()
        partial = Partial.objects.create()
        partial.timestamp -= timedelta(days=30)
        partial.save()

        call_command('clearsocial')

        self.assertEqual(2, Code.objects.count())
        self.assertEqual(1, Partial.objects.count())
