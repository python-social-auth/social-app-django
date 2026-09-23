from enum import Enum
from typing import Final

# Expected Sec-Fetch-Dest header for top-level document navigation
SEC_FETCH_DEST_DOCUMENT: Final[str] = "document"
# Expected Sec-Fetch-Site header for app-initiated same-origin requests
SEC_FETCH_SITE_SAME_ORIGIN: Final[str] = "same-origin"
# Blocked Sec-Fetch-Mode headers that indicate framing or embedding
BLOCKED_SEC_FETCH_MODES: Final[tuple[str, ...]] = ("iframe", "frame", "embed")


class RedirectParamName(str, Enum):
    """Query parameter names used for redirect targets across launch views."""

    NEXT = "next"
    TARGET_LINK_URI = "target_link_uri"


class LaunchBridge(str, Enum):
    """Launch bridges that can be enabled via SOCIAL_AUTH_ENABLE_LAUNCH_BRIDGES."""

    APP = "app_launch"
    IDP = "idp_launch"
