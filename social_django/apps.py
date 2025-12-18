from django.apps import AppConfig
from social_core.registry import REGISTRY


class PythonSocialAuthConfig(AppConfig):
    # Explicitly set default auto field type to avoid migrations in Django 3.2+
    default_auto_field = "django.db.models.BigAutoField"
    # Full Python path to the application eg. 'django.contrib.admin'.
    name = "social_django"
    # Last component of the Python path to the application eg. 'admin'.
    label = "social_django"
    # Human-readable name for the application eg. "Admin".
    verbose_name = "Python Social Auth"

    def ready(self) -> None:
        from .utils import load_strategy  # noqa: PLC0415

        super().ready()

        # django.contrib.auth.load_backend() will import and instantiate the
        # authentication backend ignoring the possibility that it might
        # require more arguments. Here we set a default strategy for that case.
        REGISTRY.default_strategy = load_strategy()
