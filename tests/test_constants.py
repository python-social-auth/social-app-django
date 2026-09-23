import subprocess
import sys

from django.test import TestCase

from social_django.constants import (
    BLOCKED_SEC_FETCH_MODES,
    SEC_FETCH_DEST_DOCUMENT,
    SEC_FETCH_SITE_SAME_ORIGIN,
    LaunchBridge,
    RedirectParamName,
)
from social_django.utils import (
    BLOCKED_SEC_FETCH_MODES as UTILS_BLOCKED_MODES,
)
from social_django.utils import (
    SEC_FETCH_DEST_DOCUMENT as UTILS_DEST_DOC,
)
from social_django.utils import (
    SEC_FETCH_SITE_SAME_ORIGIN as UTILS_SITE_ORIGIN,
)
from social_django.utils import (
    LaunchBridge as UtilsLaunchBridge,
)
from social_django.utils import (
    RedirectParamName as UtilsRedirectParamName,
)


class TestConstants(TestCase):
    def test_launch_bridge_enum_values(self):
        self.assertEqual(LaunchBridge.APP, "app_launch")
        self.assertEqual(LaunchBridge.IDP, "idp_launch")
        self.assertEqual(LaunchBridge.APP.value, "app_launch")
        self.assertEqual(LaunchBridge.IDP.value, "idp_launch")

    def test_redirect_param_name_enum_values(self):
        self.assertEqual(RedirectParamName.NEXT, "next")
        self.assertEqual(RedirectParamName.TARGET_LINK_URI, "target_link_uri")

    def test_fetch_metadata_constants(self):
        self.assertEqual(SEC_FETCH_DEST_DOCUMENT, "document")
        self.assertEqual(SEC_FETCH_SITE_SAME_ORIGIN, "same-origin")
        self.assertEqual(BLOCKED_SEC_FETCH_MODES, ("iframe", "frame", "embed"))

    def test_utils_reexports_match_constants(self):
        self.assertIs(UtilsLaunchBridge, LaunchBridge)
        self.assertIs(UtilsRedirectParamName, RedirectParamName)
        self.assertIs(UTILS_DEST_DOC, SEC_FETCH_DEST_DOCUMENT)
        self.assertIs(UTILS_SITE_ORIGIN, SEC_FETCH_SITE_SAME_ORIGIN)
        self.assertIs(UTILS_BLOCKED_MODES, BLOCKED_SEC_FETCH_MODES)

    def test_constants_importable_before_django_setup(self):
        """Verifies that social_django.constants can be imported in settings.py without AppRegistryNotReady."""
        code = (
            "import os\n"
            "os.environ['DJANGO_SETTINGS_MODULE'] = 'tests.settings'\n"
            "from social_django.constants import LaunchBridge\n"
            "assert LaunchBridge.APP == 'app_launch'\n"
        )
        result = subprocess.run(  # noqa: S603
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
