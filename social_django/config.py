from django.apps import AppConfig

from .utils import load_strategy


class PythonSocialAuthConfig(AppConfig):
    name = 'social'
    label = 'social_auth'
    verbose_name = 'Python Social Auth'
