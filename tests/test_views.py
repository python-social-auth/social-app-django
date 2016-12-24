# -*- coding: utf-8 -*-
from django.test import Client
from django.test import TestCase
try:
    from django.urls import reverse
except ImportError:
    from django.core.urlresolvers import reverse


class TestConfig(TestCase):
    client_class = Client

    def setUp(self):
        session = self.client.session
        session['somekey'] = 'test'
        session.save()

    def test_begin_view(self):
        response = self.client.get(reverse('social:begin', kwargs={'backend': 'facebook'}))
        self.assertEqual(response.status_code, 302)
