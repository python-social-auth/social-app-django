"""Expose social-core's bundled authentication icons to Django staticfiles."""

from importlib.resources import files

from django.contrib.staticfiles.finders import FileSystemFinder
from django.core.files.storage import FileSystemStorage


class SocialAuthIconFinder(FileSystemFinder):
    """Register after the standard finders to allow application overrides."""

    def __init__(self, *args, **kwargs):
        location = str(files("social_core").joinpath("static", "social_auth", "icons"))
        prefix = "social_auth/icons"
        self.locations = [(prefix, location)]
        storage = FileSystemStorage(location=location)
        storage.prefix = prefix
        self.storages = {location: storage}

    def find_location(self, root, path, prefix=None):
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
