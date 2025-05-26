"""
This is legacy code used only in the database migrations.
"""

from django.conf import settings
from django.db import models
from social_core.utils import setting_name

POSTGRES_JSONFIELD = getattr(settings, setting_name("POSTGRES_JSONFIELD"), False)

JSONFIELD_ENABLED = True if POSTGRES_JSONFIELD else getattr(settings, setting_name("JSONFIELD_ENABLED"), False)

if JSONFIELD_ENABLED:
    JSONFIELD_CUSTOM = getattr(settings, setting_name("JSONFIELD_CUSTOM"), None)

    if JSONFIELD_CUSTOM is not None:
        from django.utils.module_loading import import_string

        JSONField = import_string(JSONFIELD_CUSTOM)
    else:
        from django.db.models import JSONField
else:
    JSONField = models.TextField
