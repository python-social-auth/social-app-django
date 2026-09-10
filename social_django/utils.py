from collections.abc import Container
from enum import Enum
from functools import wraps
from typing import Any, Final
from urllib.parse import urlencode, urlsplit

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.http import Http404, HttpRequest, HttpResponse
from django.urls import reverse
from social_core.exceptions import MissingBackend
from social_core.utils import get_strategy, module_member, setting_name, social_logger

STRATEGY = getattr(settings, setting_name("STRATEGY"), "social_django.strategy.DjangoStrategy")
STORAGE = getattr(settings, setting_name("STORAGE"), "social_django.models.DjangoStorage")

Strategy = module_member(STRATEGY)
Storage = module_member(STORAGE)


def load_strategy(request=None):
    return get_strategy(STRATEGY, STORAGE, request)


def load_backend(strategy, name, redirect_uri):
    return strategy.get_backend(name, redirect_uri=redirect_uri)


def psa(redirect_uri=None, load_strategy=load_strategy):
    def decorator(func):
        @wraps(func)
        def wrapper(request, backend, *args, **kwargs):
            uri = redirect_uri
            if uri and not uri.startswith("/"):
                uri = reverse(redirect_uri, args=(backend,))
            request.social_strategy = load_strategy(request)
            # backward compatibility in attribute name, only if not already
            # defined
            if not hasattr(request, "strategy"):
                request.strategy = request.social_strategy

            try:
                request.backend = load_backend(request.social_strategy, backend, redirect_uri=uri)
            except MissingBackend as error:
                msg = "Backend not found"
                raise Http404(msg) from error
            return func(request, backend, *args, **kwargs)

        return wrapper

    return decorator


#
# Launch & Fetch Metadata Utilities
#
#: Expected Sec-Fetch-Dest header for top-level document navigation
SEC_FETCH_DEST_DOCUMENT: Final[str] = "document"
#: Expected Sec-Fetch-Site header for app-initiated same-origin requests
SEC_FETCH_SITE_SAME_ORIGIN: Final[str] = "same-origin"
#: Blocked Sec-Fetch-Mode headers that indicate framing or embedding
BLOCKED_SEC_FETCH_MODES: Final[tuple[str, ...]] = ("iframe", "frame", "embed")


class RedirectParamName(str, Enum):
    """Query parameter names used for redirect targets across launch views."""

    NEXT = "next"
    TARGET_LINK_URI = "target_link_uri"


def build_url(base_url: str, query_params: dict | None = None) -> str:
    """
    Utility function to build a URL with query parameters.

    Args:
        base_url: The base URL to which query parameters will be appended.
        query_params: A dictionary of query parameters to include in the URL.

    Returns:
        The complete URL with encoded query parameters.
    """
    if query_params:
        return f"{base_url}?{urlencode(query_params)}"
    return base_url


def is_safe_url(
    url: str | None,
    allowed_hosts: Container[str] | None = None,
    require_https: bool = False,  # noqa: FBT001
) -> bool:
    """
    Check if a URL is safe for redirection.

    A URL is considered safe if:
    - It is a relative path (e.g. '/dashboard')
    - Or its host is present in `allowed_hosts`
    - It does not use unsafe schemes (javascript:, data:, etc.)
    - It does not contain backslashes or protocol-relative trickery without allowed hosts.

    Args:
        url: The URL string to validate.
        allowed_hosts: Set/container of allowed hostnames.
        require_https: If True, requires HTTPS scheme for absolute URLs.

    Returns:
        True if safe for redirection, False otherwise.
    """
    if not url or not isinstance(url, str) or "\\" in url:
        return False

    url = url.strip()

    try:
        parsed = urlsplit(url)
    except ValueError:
        return False

    # Disallow schemes other than http and https
    if parsed.scheme and (parsed.scheme not in ("http", "https") or (require_https and parsed.scheme != "https")):
        return False

    # Netloc indicates an absolute or protocol-relative URL
    if parsed.netloc:
        if not allowed_hosts:
            return False
        hostname = parsed.hostname or ""
        if parsed.netloc not in allowed_hosts and hostname not in allowed_hosts:
            return False

    return True


def is_valid_https_url(url: str | None) -> bool:
    """Validates input is a RFC-compliant URL using HTTPS."""
    if not url:
        return False

    validator = URLValidator(schemes=["https"])
    try:
        validator(url)
    except ValidationError:
        return False
    else:
        return True


def get_backend_issuer(backend_obj: Any, backend_name: str) -> tuple[list[str] | None, str | None]:
    """
    Retrieves and validates the configured ID token issuer(s) for an OpenID Connect backend.

    Supports `backend_obj.id_token_issuer()` or `backend_obj.setting("ID_TOKEN_ISSUER")`
    returning a single RFC-compliant HTTPS URL string or a sequence of HTTPS URL strings.

    Args:
        backend_obj: Instantiated backend instance.
        backend_name: Name of the backend.

    Returns:
        A tuple of (list_of_valid_issuers, error_message).
    """
    raw_issuer = None
    if callable(getattr(backend_obj, "id_token_issuer", None)):
        raw_issuer = backend_obj.id_token_issuer()
    elif hasattr(backend_obj, "setting"):
        raw_issuer = backend_obj.setting("ID_TOKEN_ISSUER", None)

    if not raw_issuer:
        return None, f"Backend `{backend_name}` does not support ID token issuer validation"

    if isinstance(raw_issuer, str):
        issuers = [raw_issuer]
    elif isinstance(raw_issuer, (list, tuple, set)):
        issuers = list(raw_issuer)
    else:
        return None, f"Configured ID token issuer for backend `{backend_name}` must be a string or list of strings"

    if not issuers:
        return None, f"Backend `{backend_name}` does not support ID token issuer validation"

    for issuer in issuers:
        if not is_valid_https_url(issuer):
            return None, (
                f"Configured ID token issuer `{issuer}` for backend `{backend_name}` "
                "is not a valid RFC-compliant HTTPS URL"
            )

    return issuers, None


def validate_idp_issuer(
    backend_obj: Any,
    backend_name: str,
    iss: str | None,
) -> tuple[str | None, str | None]:
    """
    Validates that the provided `iss` parameter matches the backend's configured issuer(s)
    or an allowed issuer from the ALLOWED_ID_TOKEN_ISSUERS setting.

    Args:
        backend_obj: Instantiated backend instance.
        backend_name: Name of the backend.
        iss: The issuer URL supplied in the query string.

    Returns:
        A tuple of (validated_iss, error_message).
    """
    if not iss:
        return None, "idp_launch: Missing required `iss` query parameter"

    if not is_valid_https_url(iss):
        return None, f"idp_launch: `iss` parameter `{iss}` is not a valid RFC-compliant HTTPS URL"

    configured_issuers, issuer_error = get_backend_issuer(backend_obj, backend_name)
    if issuer_error or not configured_issuers:
        return None, f"idp_launch: {issuer_error}"

    allowed_issuers: list[str] = []
    if hasattr(backend_obj, "setting"):
        allowed = backend_obj.setting("ALLOWED_ID_TOKEN_ISSUERS", [])
        if isinstance(allowed, str):
            allowed_issuers = [allowed]
        elif isinstance(allowed, (list, tuple, set)):
            allowed_issuers = list(allowed)

    valid_issuers = list(configured_issuers) + [i for i in allowed_issuers if is_valid_https_url(i)]
    if iss not in valid_issuers:
        expected = configured_issuers[0] if len(configured_issuers) == 1 else configured_issuers
        return None, f"idp_launch: Invalid `iss` parameter. Expected: `{expected}`, Got: `{iss}`"

    return iss, None


def resolve_redirect_uri(
    request: HttpRequest,
    raw_uri: str | None,
    param_name: RedirectParamName | str,
    view_name: str,
) -> str | None:
    """
    Resolves and validates a redirect URI against allowed hosts to prevent open redirects.

    Args:
        request: The incoming HttpRequest.
        raw_uri: Untrusted redirect URI from query string.
        param_name: Parameter name (for logging).
        view_name: View name (for logging).

    Returns:
        Validated redirect URI, or None if invalid or unsafe.
    """
    if not raw_uri:
        return None

    allowed_hosts = {request.get_host()}
    if is_safe_url(raw_uri, allowed_hosts=allowed_hosts, require_https=request.is_secure()):
        social_logger.info(
            "%s: Using valid `%s` redirect parameter: %s",
            view_name,
            str(param_name),
            raw_uri,
        )
        return raw_uri

    social_logger.warning(
        "%s: Discarded unsafe `%s` parameter: %s",
        view_name,
        str(param_name),
        raw_uri,
    )
    return None


def check_fetch_metadata(request: HttpRequest, view_name: str) -> tuple[bool, list[str]]:
    """
    Evaluates Sec-Fetch-* metadata headers to protect against framing and CSRF bypass.

    Args:
        request: The incoming HttpRequest.
        view_name: View name (for logging).

    Returns:
        A tuple of (auto_submit, warnings_list).
    """
    warnings: list[str] = []
    auto_submit: bool = True

    sec_fetch_dest = request.headers.get("Sec-Fetch-Dest")
    if sec_fetch_dest and sec_fetch_dest != SEC_FETCH_DEST_DOCUMENT:
        auto_submit = False
        message = (
            f"{view_name}: Unexpected Sec-Fetch-Dest `{sec_fetch_dest}`, "
            "disabling auto-submit (fallback to manual submit)"
        )
        warnings.append(message)
        social_logger.warning(message)

    sec_fetch_mode = request.headers.get("Sec-Fetch-Mode")
    if sec_fetch_mode and sec_fetch_mode in BLOCKED_SEC_FETCH_MODES:
        auto_submit = False
        message = (
            f"{view_name}: Framed/embedded Sec-Fetch-Mode `{sec_fetch_mode}`, "
            "disabling auto-submit (fallback to manual submit)"
        )
        warnings.append(message)
        social_logger.warning(message)

    return auto_submit, warnings


def validate_app_launch_origin(request: HttpRequest) -> tuple[bool, str | None]:
    """
    Validates origin indicators (Sec-Fetch-Site and Referer) for application-initiated launch.

    Args:
        request: The incoming HttpRequest.

    Returns:
        A tuple of (is_valid, error_message).
    """
    # Guard 1: Reject cross-site launches based on Sec-Fetch-Site header
    sec_fetch_site: str | None = request.headers.get("Sec-Fetch-Site")
    if sec_fetch_site and sec_fetch_site != SEC_FETCH_SITE_SAME_ORIGIN:
        return False, f"app_launch: Cross-site launch rejected (Sec-Fetch-Site: {sec_fetch_site})"

    # Guard 2: Reject untrusted Referer origins if provided
    referer: str | None = request.headers.get("Referer")
    if referer:
        allowed_hosts = {request.get_host()}
        if not is_safe_url(referer, allowed_hosts=allowed_hosts, require_https=request.is_secure()):
            return False, f"app_launch: Untrusted Referer origin rejected: {referer}"

    # Guard 3: Require at least one same-origin indicator (Sec-Fetch-Site or Referer)
    if not sec_fetch_site and not referer:
        return (
            False,
            "app_launch: Missing same-origin indicator (neither Sec-Fetch-Site nor Referer header provided)",
        )

    # Validation passed
    return True, None


def apply_framing_protection(response: HttpResponse) -> HttpResponse:
    """
    Applies CSP frame-ancestors 'none' framing protection to the response.

    Args:
        response: The HttpResponse object.

    Returns:
        The HttpResponse with CSP framing protection header set.
    """
    csp = response.headers.get("Content-Security-Policy")
    if not csp:
        response["Content-Security-Policy"] = "frame-ancestors 'none'"
    elif "frame-ancestors" not in csp:
        response["Content-Security-Policy"] = f"{csp}; frame-ancestors 'none'"
    return response
