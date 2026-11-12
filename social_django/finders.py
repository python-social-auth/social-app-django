"""Expose social-core's bundled authentication icons to Django staticfiles."""

from __future__ import annotations

from importlib.resources import files

from django.contrib.staticfiles.finders import FileSystemFinder
from django.core.files.storage import FileSystemStorage


class _IconStorage(FileSystemStorage):
    """Declare the prefix used by collectstatic for bundled icons."""

    prefix: str = "social_auth/icons"


class SocialAuthIconFinder(FileSystemFinder):
    """Register after the standard finders to allow application overrides."""

    def __init__(self, *args, **kwargs):
        location = str(files("social_core").joinpath("static", "social_auth", "icons"))
        storage = _IconStorage(location=location)
        self.locations = [(storage.prefix, location)]
        self.storages = {location: storage}

    def find_location(self, root: str, path: str, prefix: str | None = None) -> str | None:
        # Static URLs use forward slashes even when the filesystem uses backslashes.
        path = path.replace("\\", "/")
        if prefix:
            prefix = prefix.replace("\\", "/").rstrip("/") + "/"
            if not path.startswith(prefix):
                return None
            path = path.removeprefix(prefix)
        return super().find_location(root, path)

    def check(self, **kwargs):
        return []
