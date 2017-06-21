# -*- coding: utf-8
from __future__ import unicode_literals, absolute_import

from django.contrib.auth import get_user_model
from django.core.urlresolvers import reverse
from django.test import TestCase


class SocialAdminTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        User.objects.create_superuser(
            username='admin', email='admin@test.com', first_name='Admin',
            password='super-duper-test'
        )

    def test_admin_app_name(self):
        """The App name in the admin index page"""
        self.client.login(username='admin', password='super-duper-test')
        response = self.client.get(reverse('admin:index'))
        self.assertContains(response, "Social_Django")
