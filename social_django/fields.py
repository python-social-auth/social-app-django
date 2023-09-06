"""
This is legacy code used only in the database migrations.
"""

from django.conf import settings
from django.db import models
from social_core.utils import setting_name

POSTGRES_JSONFIELD = getattr(settings, setting_name("POSTGRES_JSONFIELD"), False)

if POSTGRES_JSONFIELD:
    JSONFIELD_ENABLED = True
else:
    JSONFIELD_ENABLED = getattr(settings, setting_name("JSONFIELD_ENABLED"), False)

if JSONFIELD_ENABLED:
    JSONFIELD_CUSTOM = getattr(settings, setting_name("JSONFIELD_CUSTOM"), None)

    if JSONFIELD_CUSTOM is not None:
        try:
            from django.utils.module_loading import import_string
        except ImportError:
            from importlib import import_module as import_string
        JSONField = import_string(JSONFIELD_CUSTOM)
    else:
        try:
            from django.db.models import JSONField
        except ImportError:
            from django.contrib.postgres.fields import JSONField
else:
    JSONField = models.TextField
