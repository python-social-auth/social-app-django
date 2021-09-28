from django.conf import settings
"""
To avoid circular imports from using utils.py in models.py
"""


def get_kms_key():
    return settings.KMS_FIELD_KEY
