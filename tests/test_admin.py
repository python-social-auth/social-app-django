# -*- coding: utf-8
from __future__ import unicode_literals, absolute_import

from django.contrib.auth import get_user_model
from django.test import TestCase
from social_django.compat import reverse
from social_django.models import UserSocialAuth


class SocialAdminTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        User.objects.create_superuser(
            username='admin', email='admin@test.com', first_name='Admin',
            password='super-duper-test'
        )

    def test_admin_app_name(self):
        """App should not be registered in admin panel"""
        self.client.login(username='admin', password='super-duper-test')
        response = self.client.get(reverse('admin:index'))
        self.assertNotContains(response, "Django administration")

    # TODO: Figure out what this test is for
    # def test_social_auth_changelist(self):
    #     """The App name in the admin index page"""
    #     self.client.login(username='admin', password='super-duper-test')
    #     meta = UserSocialAuth._meta
    #     url_name = 'admin:%s_%s_changelist' % (meta.app_label, meta.model_name)
    #     self.client.get(reverse(url_name))
