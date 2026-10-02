from urllib.parse import quote

from django.conf import settings
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.http.multipartparser import MultiPartParserError
from django.utils.functional import SimpleLazyObject, empty
from social_core.backends.utils import load_backends, user_backends_data

from .utils import Storage


class LazyDict(SimpleLazyObject):
    """Lazy dict initialization."""

    def __getitem__(self, name):
        if self._wrapped is empty:
            self._setup()
        return self._wrapped[name]

    def __setitem__(self, name, value):
        if self._wrapped is empty:
            self._setup()
        self._wrapped[name] = value


def backends(request):
    """
    Load Social Auth current user data to context under the key 'backends'.
    Return user_backends_data plus display titles and icon paths in metadata.
    """

    def get_data():
        data = user_backends_data(request.user, settings.AUTHENTICATION_BACKENDS, Storage)
        data["metadata"] = {
            name: {
                "title": backend.title or name,
                "icon": f"social_auth/icons/{backend.icon}" if backend.icon else None,
            }
            for name, backend in load_backends(settings.AUTHENTICATION_BACKENDS).items()
        }
        return data

    return {"backends": LazyDict(get_data)}


def login_redirect(request):
    """Load current redirect to context."""
    try:
        value = (request.method == "POST" and request.POST.get(REDIRECT_FIELD_NAME)) or request.GET.get(
            REDIRECT_FIELD_NAME
        )
    except MultiPartParserError:
        # request POST may be malformed
        value = None
    if value:
        value = quote(value)
        querystring = REDIRECT_FIELD_NAME + "=" + value
    else:
        querystring = ""

    return {
        "REDIRECT_FIELD_NAME": REDIRECT_FIELD_NAME,
        "REDIRECT_FIELD_VALUE": value,
        "REDIRECT_QUERYSTRING": querystring,
    }
