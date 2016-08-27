from django.apps import AppConfig

from social_core.utils import set_current_strategy_getter
from .utils import load_strategy


class PythonSocialAuthConfig(AppConfig):
    name = 'social'
    label = 'social_auth'
    verbose_name = 'Python Social Auth'

    def ready(self):
        """Set strategy loader method to workaround current strategy getter
        needed on get_user() method on authentication backends when working
        with Django"""
        set_current_strategy_getter(load_strategy)
