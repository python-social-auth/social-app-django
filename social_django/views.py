from django.conf import settings
from django.contrib.auth import REDIRECT_FIELD_NAME, login
from django.contrib.auth.decorators import login_not_required, login_required
from django.core.exceptions import BadRequest
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.clickjacking import xframe_options_deny
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.views.decorators.http import require_GET, require_POST
from social_core.actions import do_auth, do_complete, do_disconnect
from social_core.utils import setting_name, social_logger

from .utils import (
    RedirectParamName,
    apply_framing_protection,
    check_fetch_metadata,
    get_backend_issuer,
    psa,
    resolve_redirect_uri,
    validate_app_launch_origin,
    validate_idp_issuer,
)

NAMESPACE = getattr(settings, setting_name("URL_NAMESPACE"), None) or "social"

# Calling `session.set_expiry(None)` results in a session lifetime equal to
# platform default session lifetime.
DEFAULT_SESSION_TIMEOUT = None


@never_cache
@login_not_required
@require_POST
@psa(f"{NAMESPACE}:complete")
def auth(request, backend):
    return do_auth(request.backend, redirect_name=REDIRECT_FIELD_NAME)


@never_cache
@login_not_required
@require_GET
@xframe_options_deny  # Layer 1: Framing protection
@psa()
def idp_launch(request, backend):
    """
    Bridge IdP-initiated GET redirects to the CSRF-protected `social:begin` POST flow.

    Provides a layered security approach:
    1. Framing protection: Applies X-Frame-Options: DENY and CSP frame-ancestors 'none'.
    2. Open redirect prevention: Validates target_link_uri parameter using `is_safe_url`,
       logging and dropping invalid external URLs.
    3. Parameter whitelisting: Strictly accepts only `iss` and `target_link_uri` per OIDC spec.
    4. Authenticated session bypass: Immediately redirects authenticated users to
       `safe_target_link_uri` or `settings.LOGIN_REDIRECT_URL`, skipping the backend roundtrip.
    5. Fetch Metadata validation: Inspects `Sec-Fetch-*` headers to detect embedding or non-document requests.
    6. Manual confirmation fallback: Disables automatic JavaScript submission if Fetch Metadata indicates
       a framed or non-top-level navigation context.
    7. CSRF protection: Form POSTs to `social:begin` with a valid Django CSRF token.

    Args:
        request: The HttpRequest object.
        backend: The social backend to initiate authentication for.

    Returns:
        An HttpResponse rendering the launch form template with appropriate security headers, or
        redirecting authenticated users.

    Raises:
        BadRequest: If the ID token issuer URL is invalid.
        BadRequest: If the `iss` parameter doesn't match the configured ID token issuer(s).
    """
    backend_obj = request.backend
    iss = request.GET.get("iss")

    # Layer 3: Parameter whitelisting — Verify the 'iss' query parameter against backend ID token issuer(s)
    validated_iss, issuer_error = validate_idp_issuer(backend_obj, backend, iss)
    if issuer_error:
        social_logger.error(issuer_error)
        raise BadRequest(issuer_error)

    # Layer 2: Open redirect prevention — Validate target_link_uri against allowed hosts
    # before setting redirect parameter
    raw_target_link_uri = request.GET.get(RedirectParamName.TARGET_LINK_URI.value)
    safe_target_link_uri = resolve_redirect_uri(
        request,
        raw_target_link_uri,
        RedirectParamName.TARGET_LINK_URI,
        "idp_launch",
    )

    # Layer 4: Authenticated session bypass — Skip authentication roundtrip if session is already authenticated
    user = getattr(request, "user", None)
    if user and user.is_authenticated:
        redirect_to = safe_target_link_uri or getattr(settings, "LOGIN_REDIRECT_URL", "/accounts/profile/")
        social_logger.info(
            "idp_launch: User `%s` already authenticated, redirecting to `%s`",
            user,
            redirect_to,
        )
        return redirect(redirect_to)

    # Layers 5 & 6: Fetch Metadata validation & Manual confirmation fallback — Inspect Sec-Fetch-* headers
    auto_submit, _ = check_fetch_metadata(request, "idp_launch")

    # Whitelist parameters passed to social:begin
    params = {"iss": validated_iss}
    if safe_target_link_uri:
        params[REDIRECT_FIELD_NAME] = safe_target_link_uri

    # Layer 7: CSRF protection — Render launch template targeting social:begin with CSRF token
    response = render(
        request,
        "social_django/launch.html",
        {
            "action_url": reverse(f"{NAMESPACE}:begin", args=[backend]),
            "params": params,
            "auto_submit": auto_submit,
        },
    )

    # Layer 1: Framing protection — Enforce CSP frame-ancestors 'none' (X-Frame-Options: DENY applied via decorator)
    return apply_framing_protection(response)


@never_cache
@login_not_required
@require_GET
@xframe_options_deny  # Layer 3: Framing protection
@psa()
def app_launch(request, backend):
    """
    Bridge app-initiated (e.g., SPA) GET redirects to the CSRF-protected `social:begin` POST flow.

    Provides a layered security approach for app-initiated requests:
    1. Origin validation: Requires Sec-Fetch-Site header to be 'same-origin' when present.
    2. Referer validation: Verifies Referer header against allowed hosts when present.
    3. Framing protection: Applies X-Frame-Options: DENY and CSP frame-ancestors 'none'.
    4. Open redirect prevention: Validates next parameter using `is_safe_url`.
    5. Authenticated session bypass: Immediately redirects authenticated users to
       `safe_next_url` or `settings.LOGIN_REDIRECT_URL`, skipping the backend roundtrip.
    6. Fetch Metadata validation: Inspects `Sec-Fetch-*` headers to detect embedding or non-document requests.
    7. Manual confirmation fallback: Disables automatic JavaScript submission if Fetch Metadata indicates
       a framed or non-top-level navigation context.
    8. CSRF protection: Form POSTs to `social:begin` with a valid Django CSRF token.

    Args:
        request: The HttpRequest object.
        backend: The social backend to initiate authentication for.

    Returns:
        An HttpResponse rendering the launch form template with appropriate security headers, or
        redirecting authenticated users.

    Raises:
        BadRequest: If origin or referer validation fails.
        BadRequest: If the backend does not support ID token issuer validation or the requested issuer is invalid.
    """
    # Layer 1 & 2: Origin and Referer validation — Verify same-origin Sec-Fetch-Site and allowed Referer
    is_valid_origin, origin_error = validate_app_launch_origin(request)
    if not is_valid_origin:
        social_logger.error(origin_error)
        raise BadRequest(origin_error)

    backend_obj = request.backend
    configured_issuers, issuer_error = get_backend_issuer(backend_obj, backend)
    if issuer_error or not configured_issuers:
        message = f"app_launch: {issuer_error}"
        social_logger.error(message)
        raise BadRequest(message)

    # Layer 4: Open redirect prevention — Validate 'next' parameter against allowed hosts
    raw_next_url = request.GET.get(RedirectParamName.NEXT.value)
    safe_next_url = resolve_redirect_uri(
        request,
        raw_next_url,
        RedirectParamName.NEXT,
        "app_launch",
    )

    # Layer 5: Authenticated session bypass — Skip authentication roundtrip if session is already authenticated
    user = getattr(request, "user", None)
    if user and user.is_authenticated:
        redirect_to = safe_next_url or getattr(settings, "LOGIN_REDIRECT_URL", "/accounts/profile/")
        social_logger.info(
            "app_launch: User `%s` already authenticated, redirecting to `%s`",
            user,
            redirect_to,
        )
        return redirect(redirect_to)

    # Layers 6 & 7: Fetch Metadata validation & Manual confirmation fallback — Inspect Sec-Fetch-* headers
    auto_submit, _ = check_fetch_metadata(request, "app_launch")

    # Select issuer (defaults to primary configured issuer or validated optional query param)
    selected_issuer = configured_issuers[0]
    requested_iss = request.GET.get("iss")
    if requested_iss:
        validated_iss, iss_err = validate_idp_issuer(backend_obj, backend, requested_iss)
        if iss_err:
            social_logger.error("app_launch: %s", iss_err)
            raise BadRequest(iss_err)
        selected_issuer = validated_iss

    # Whitelist parameters passed to social:begin
    params = {"iss": selected_issuer}
    if safe_next_url:
        params[REDIRECT_FIELD_NAME] = safe_next_url

    # Layer 8: CSRF protection — Render launch template targeting social:begin with CSRF token
    response = render(
        request,
        "social_django/launch.html",
        {
            "action_url": reverse(f"{NAMESPACE}:begin", args=[backend]),
            "params": params,
            "auto_submit": auto_submit,
        },
    )

    # Layer 3: Framing protection — Enforce CSP frame-ancestors 'none' (X-Frame-Options: DENY applied via decorator)
    return apply_framing_protection(response)


@never_cache
@login_not_required
@csrf_exempt
@psa(f"{NAMESPACE}:complete")
def complete(request, backend, *args, **kwargs):
    """Authentication complete view"""
    kwargs.update(
        user=request.user,
        redirect_name=REDIRECT_FIELD_NAME,
        request=request,
    )
    return do_complete(request.backend, _do_login, *args, **kwargs)


@never_cache
@login_required
@psa()
@require_POST
@csrf_protect
def disconnect(request, backend, association_id=None):
    """Disconnects given backend from current logged in user."""
    return do_disconnect(request.backend, request.user, association_id, redirect_name=REDIRECT_FIELD_NAME)


def get_session_timeout(social_user, enable_session_expiration=False, max_session_length=None):
    if enable_session_expiration:
        # Retrieve an expiration date from the social user who just finished
        # logging in; this value was set by the social auth backend, and was
        # typically received from the server.
        expiration = social_user.expiration_datetime()

        # We've enabled session expiration. Check to see if we got
        # a specific expiration time from the provider for this user;
        # if not, use the platform default expiration.
        received_expiration_time = expiration.total_seconds() if expiration else DEFAULT_SESSION_TIMEOUT

        # Check to see if the backend set a value as a maximum length
        # that a session may be; if they did, then we should use the minimum
        # of that and the received session expiration time, if any, to
        # set the session length.
        if received_expiration_time is None and max_session_length is None:
            # We neither received an expiration length, nor have a maximum
            # session length. Use the platform default.
            session_expiry = DEFAULT_SESSION_TIMEOUT
        elif received_expiration_time is None and max_session_length is not None:
            # We only have a maximum session length; use that.
            session_expiry = max_session_length
        elif received_expiration_time is not None and max_session_length is None:
            # We only have an expiration time received by the backend
            # from the provider, with no set maximum. Use that.
            session_expiry = received_expiration_time
        else:
            # We received an expiration time from the backend, and we also
            # have a set maximum session length. Use the smaller of the two.
            session_expiry = min(received_expiration_time, max_session_length)
    # If there's an explicitly-set maximum session length, use that
    # even if we don't want to retrieve session expiry times from
    # the backend. If there isn't, then use the platform default.
    elif max_session_length is None:
        session_expiry = DEFAULT_SESSION_TIMEOUT
    else:
        session_expiry = max_session_length

    return session_expiry


def _do_login(backend, user, social_user):
    user.backend = f"{backend.__module__}.{backend.__class__.__name__}"
    # Get these details early to avoid any issues involved in the
    # session switch that happens when we call login().
    enable_session_expiration = backend.setting("SESSION_EXPIRATION", False)
    max_session_length_setting = backend.setting("MAX_SESSION_LENGTH", None)

    # Log the user in, creating a new session.
    login(backend.strategy.request, user)

    # Make sure that the max_session_length value is either an integer or
    # None. Because we get this as a setting from the backend, it can be set
    # to whatever the backend creator wants; we want to be resilient against
    # unexpected types being presented to us.
    try:
        max_session_length = int(max_session_length_setting)
    except (TypeError, ValueError):
        # We got a response that doesn't look like a number; use the default.
        max_session_length = None

    # Get the session expiration length based on the maximum session length
    # setting, combined with any session length received from the backend.
    session_expiry = get_session_timeout(
        social_user,
        enable_session_expiration=enable_session_expiration,
        max_session_length=max_session_length,
    )

    try:
        # Set the session length to our previously determined expiry length.
        backend.strategy.request.session.set_expiry(session_expiry)
    except OverflowError:
        # The timestamp we used wasn't in the range of values supported by
        # Django for session length; use the platform default. We tried.
        backend.strategy.request.session.set_expiry(DEFAULT_SESSION_TIMEOUT)
