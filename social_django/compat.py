# coding=utf-8
import six
import django
from django.db import models

if django.VERSION >= (2, 0):
    from django.urls import reverse
else:
    from django.core.urlresolvers import reverse

assert reverse


def get_rel_model(field):
    if django.VERSION >= (2, 0):
        return field.model

    user_model = field.rel.to
    if isinstance(user_model, six.string_types):
        app_label, model_name = user_model.split('.')
        return models.get_model(app_label, model_name)

    return user_model
