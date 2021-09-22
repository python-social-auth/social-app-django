# coding=utf-8
from __future__ import unicode_literals, absolute_import

import unittest.mock as mock

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import QueryDict, HttpResponse
from django.test import TestCase, RequestFactory
from django.utils.translation import ugettext_lazy

from social_django.utils import load_strategy, load_backend


class TestStrategy(TestCase):
    def setUp(self):
        self.request_factory = RequestFactory()
        self.request = self.request_factory.get('/', data={'x': '1'})
        SessionMiddleware().process_request(self.request)
        self.strategy = load_strategy(request=self.request)

    def test_request_methods(self):
        self.assertEqual(self.strategy.request_port(), '80')
        self.assertEqual(self.strategy.request_path(), '/')
        self.assertEqual(self.strategy.request_host(), 'testserver')
        self.assertEqual(self.strategy.request_is_secure(), False)
        self.assertEqual(self.strategy.request_data(), QueryDict('x=1'))
        self.assertEqual(self.strategy.request_get(), QueryDict('x=1'))
        self.assertEqual(self.strategy.request_post(), {})
        self.request.method = 'POST'
        self.assertEqual(self.strategy.request_data(merge=False), {})

    def test_build_absolute_uri(self):
        self.assertEqual(self.strategy.build_absolute_uri('/'),
                         'http://testserver/')

    def test_settings(self):
        with self.settings(LOGIN_ERROR_URL='/'):
            self.assertEqual(self.strategy.get_setting('LOGIN_ERROR_URL'), '/')
        with self.settings(LOGIN_ERROR_URL=ugettext_lazy('/')):
            self.assertEqual(self.strategy.get_setting('LOGIN_ERROR_URL'), '/')

    def test_session_methods(self):
        self.strategy.session_set('k', 'v')
        self.assertEqual(self.strategy.session_get('k'), 'v')
        self.assertEqual(self.strategy.session_setdefault('k', 'x'), 'v')
        self.assertEqual(self.strategy.session_pop('k'), 'v')

    def test_random_string(self):
        rs1 = self.strategy.random_string()
        self.assertEqual(len(rs1), 12)
        self.assertNotEqual(rs1, self.strategy.random_string())

    def test_session_value(self):
        user_model = get_user_model()
        user = user_model.objects.create_user(username="test")
        ctype = ContentType.objects.get_for_model(user_model)

        val = self.strategy.to_session_value(val=user)
        self.assertEqual(val, {'pk': user.pk, 'ctype':  ctype.pk})

        instance = self.strategy.from_session_value(val=val)
        self.assertEqual(instance, user)

    def test_get_language(self):
        self.assertEqual(self.strategy.get_language(), 'en-us')

    def test_html(self):
        result = self.strategy.render_html(tpl='test.html')
        self.assertEqual(result, 'test')

        result = self.strategy.render_html(html='xoxo')
        self.assertEqual(result, 'xoxo')

        with self.assertRaisesMessage(
                ValueError, 'Missing template or html parameters'):
            self.strategy.render_html()

        result = self.strategy.html(content='xoxo')
        self.assertIsInstance(result, HttpResponse)
        self.assertEqual(result.content, b'xoxo')

        ctx = {'x': 1}
        result = self.strategy.tpl.render_template(tpl='test.html', context=ctx)
        self.assertEqual(result, 'test')

        result = self.strategy.tpl.render_string(html='xoxo', context=ctx)
        self.assertEqual(result, 'xoxo')

    def test_authenticate(self):
        backend = load_backend(strategy=self.strategy, name='facebook',
                               redirect_uri='/')
        user = mock.Mock()
        with mock.patch('social_core.backends.base.BaseAuth.pipeline',
                        return_value=user):
            result = self.strategy.authenticate(backend=backend,
                                                response=mock.Mock())
            self.assertEqual(result, user)
            self.assertEqual(result.backend,
                             'social_core.backends.facebook.FacebookOAuth2')

    def test_clean_authenticate_args(self):
        args, kwargs = self.strategy.clean_authenticate_args(self.request)
        self.assertEqual(args, ())
        self.assertEqual(kwargs, {'request': self.request})

    def test_clean_authenticate_args_none(self):
        # When called from continue_pipeline(), request is None. Issue #222
        args, kwargs = self.strategy.clean_authenticate_args(None)
        self.assertEqual(args, ())
        self.assertEqual(kwargs, {'request': None})
