# coding=utf-8
import six
import django
from django.db import models

if django.VERSION >= (2, 0):
    from django.urls import reverse
else:
    from django.core.urlresolvers import reverse

if django.VERSION >= (1, 10):
    from django.utils.deprecation import MiddlewareMixin
else:
    MiddlewareMixin = object


def get_rel_model(field):
    if django.VERSION >= (2, 0):
        return field.remote_field.model

    user_model = field.rel.to
    if isinstance(user_model, six.string_types):
        app_label, model_name = user_model.split('.')
        user_model = models.get_model(app_label, model_name)
    return user_model


def get_request_port(request):
    if django.VERSION >= (1, 9):
        return request.get_port()

    host_parts = request.get_host().partition(':')
    return host_parts[2] or request.META['SERVER_PORT']
