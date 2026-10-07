# For backward compatibility. You should use the configuration from apps module
import warnings

from .apps import PythonSocialAuthConfig

__all__ = ["PythonSocialAuthConfig"]

warnings.warn(
    "social_django.config is deprecated; use social_django.apps instead.",
    DeprecationWarning,
    stacklevel=2,
)
