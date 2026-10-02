from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.staticfiles import finders
from django.contrib.staticfiles.storage import staticfiles_storage
from django.core.exceptions import SuspiciousFileOperation
from django.core.management import call_command
from django.test import SimpleTestCase, override_settings

from social_django.finders import SocialAuthIconFinder


@override_settings(
    STATICFILES_FINDERS=[
        "django.contrib.staticfiles.finders.FileSystemFinder",
        "django.contrib.staticfiles.finders.AppDirectoriesFinder",
        "social_django.finders.SocialAuthIconFinder",
    ]
)
class TestIconFinder(SimpleTestCase):
    def test_find_and_list(self):
        finder = SocialAuthIconFinder()
        self.assertTrue(Path(finder.find("social_auth/icons/github.svg")).is_file())
        self.assertEqual(finder.find("social_auth/icons/missing.svg"), [])
        self.assertEqual(finder.find("other/github.svg"), [])
        self.assertEqual(len(finder.find("social_auth/icons/github.svg", True)), 1)
        files = dict(finder.list([]))
        self.assertIn("github.svg", files)
        self.assertEqual(files["github.svg"].prefix, "social_auth/icons")
        self.assertNotIn("github.svg", dict(finder.list(["github.svg"])))

    def test_find_normalizes_separators(self):
        finder = SocialAuthIconFinder()
        expected = finder.find("social_auth/icons/github.svg")
        for separator in ("/", "\\"):
            with patch("django.contrib.staticfiles.finders.os.sep", separator):
                for path in (
                    "social_auth/icons/github.svg",
                    r"social_auth\icons\github.svg",
                    r"social_auth/icons\github.svg",
                    r"social_auth\icons/github.svg",
                ):
                    with self.subTest(separator=separator, path=path):
                        self.assertEqual(finder.find(path), expected)
                        self.assertEqual(finder.find(path, True), [expected])
                for path in (
                    "social_auth/icons-extra/github.svg",
                    r"social_auth\icons-extra\github.svg",
                ):
                    with self.subTest(separator=separator, path=path):
                        self.assertEqual(finder.find(path), [])

    def test_windows_prefix_and_path_traversal(self):
        finder = SocialAuthIconFinder()
        expected = finder.find("social_auth/icons/github.svg")
        root = finder.locations[0][1]
        finder.locations = [(r"social_auth\icons", root)]
        self.assertEqual(finder.find("social_auth/icons/github.svg"), expected)
        for path in (
            "social_auth/icons/../NOTICE",
            r"social_auth\icons\..\NOTICE",
        ):
            with self.subTest(path=path), self.assertRaises(SuspiciousFileOperation):
                finder.find(path)

    def test_application_override(self):
        with TemporaryDirectory() as directory:
            asset = Path(directory) / "social_auth/icons/github.svg"
            asset.parent.mkdir(parents=True)
            asset.write_text("custom")
            with override_settings(STATICFILES_DIRS=[directory]):
                self.assertEqual(finders.find("social_auth/icons/github.svg"), str(asset))

    def test_collectstatic_with_manifest(self):
        with (
            TemporaryDirectory() as directory,
            override_settings(
                INSTALLED_APPS=["django.contrib.staticfiles", "social_django"],
                STATIC_ROOT=directory,
                DEBUG=False,
                STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.ManifestStaticFilesStorage"}},
            ),
        ):
            call_command("collectstatic", interactive=False, verbosity=0)
            self.assertTrue((Path(directory) / "social_auth/icons/github.svg").is_file())
            url = staticfiles_storage.url("social_auth/icons/github.svg")
            self.assertRegex(url, r"/static/social_auth/icons/github\.[a-f0-9]+\.svg$")
            self.assertTrue((Path(directory) / "staticfiles.json").is_file())
