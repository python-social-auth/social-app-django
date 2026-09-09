from __future__ import annotations

from collections.abc import Iterable
from enum import Enum
from typing import TYPE_CHECKING
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from asgiref.sync import iscoroutinefunction, markcoroutinefunction
from django.apps import apps
from django.conf import settings
from django.contrib import messages
from django.contrib.messages.api import MessageFailure
from django.shortcuts import redirect
from django.utils.decorators import sync_and_async_middleware
from social_core.exceptions import SocialAuthBaseException
from social_core.utils import social_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from typing import ClassVar

    from django.http import HttpRequest, HttpResponse, HttpResponseRedirect


class ErrorTransport(str, Enum):
    """Transport mechanisms for delivering social auth error messages to the client."""

    MESSAGES = "messages"
    QUERY = "query"


@sync_and_async_middleware
class SocialAuthExceptionMiddleware:
    """
    Middleware that handles Social Auth AuthExceptions by providing the user
    with a message, logging an error, and redirecting to some next location.

    By default, the exception message itself is sent to the user and they are
    redirected to the location specified in the SOCIAL_AUTH_LOGIN_ERROR_URL
    setting.

    Error transport can be configured via the SOCIAL_AUTH_ERROR_TRANSPORT setting
    as a list of ErrorTransport enum values or strings:
    - ErrorTransport.MESSAGES ('messages', default): Uses django.contrib.messages framework.
    - ErrorTransport.QUERY ('query'): Encodes error message and backend into the redirect URL query parameters.

    This middleware can be extended by overriding the get_message or
    get_redirect_uri methods, which each accept request and exception.
    """

    DEFAULT_TRANSPORT: ClassVar[list[ErrorTransport]] = [ErrorTransport.MESSAGES]
    ERROR_PARAM_NAME: ClassVar[str] = "message"
    BACKEND_PARAM_NAME: ClassVar[str] = "backend"

    get_response: Callable[[HttpRequest], HttpResponse | Awaitable[HttpResponse]]

    def __init__(
        self,
        get_response: Callable[[HttpRequest], HttpResponse | Awaitable[HttpResponse]],
    ) -> None:
        """Initialize the middleware with the next response handler.

        Marks the middleware as coroutine function if get_response is async.
        """
        self.get_response = get_response

        if iscoroutinefunction(get_response):
            markcoroutinefunction(self)

    def __call__(self, request: HttpRequest) -> HttpResponse | Awaitable[HttpResponse]:
        """Process the incoming request and return the response."""
        return self.get_response(request)

    def process_exception(self, request: HttpRequest, exception: Exception) -> HttpResponseRedirect | None:
        """Process caught SocialAuthBaseException instances.

        Dispatches error messages across configured transports (messages, query parameters)
        and redirects to the error URL.
        """
        strategy = getattr(request, "social_strategy", None)
        # Guard 1: Skip if no strategy is available or if the exception should be re-raised
        if strategy is None or self.raise_exception(request, exception):
            return None

        # Guard 2: Skip if the exception is not a SocialAuthBaseException
        if not isinstance(exception, SocialAuthBaseException):
            return None

        backend = getattr(request, "backend", None)
        backend_name = getattr(backend, "name", "unknown-backend")

        message = self.get_message(request, exception)
        url = self.get_redirect_uri(request, exception)
        transports = self.get_transport_modes(request)

        url = self.dispatch_error(request, transports, url, message, backend_name)

        if url:
            return redirect(url)
        return None

    def dispatch_error(
        self,
        request: HttpRequest,
        transports: list[ErrorTransport],
        url: str | None,
        message: str,
        backend_name: str,
    ) -> str | None:
        """Dispatch the error across the configured error transport mechanisms.

        Handles Django messages and URL query parameter appending, returning
        the potentially updated redirect URL.
        """
        # 1. Handle Django Messages transport if enabled
        if ErrorTransport.MESSAGES in transports:
            if apps.is_installed("django.contrib.messages"):
                social_logger.info(message)
                try:
                    messages.error(request, message, extra_tags=f"social-auth {backend_name}")
                except MessageFailure:
                    # Fallback to query parameter if message backend storage fails
                    if ErrorTransport.QUERY not in transports:
                        url = self.append_query_params(request, url, message, backend_name)
            elif ErrorTransport.QUERY not in transports:
                social_logger.error(message)

        # 2. Handle Query Parameter transport if enabled
        if ErrorTransport.QUERY in transports:
            if ErrorTransport.MESSAGES not in transports or not apps.is_installed("django.contrib.messages"):
                social_logger.info(message)
            url = self.append_query_params(request, url, message, backend_name)

        return url

    def get_transport_modes(self, request: HttpRequest) -> list[ErrorTransport]:
        """Resolve and return the configured list of ErrorTransport modes for the request/backend.

        Checks the ERROR_TRANSPORT setting (backend-specific if available),
        normalizing single items and iterables. Falls back to DEFAULT_TRANSPORT
        if no valid modes are found.
        """
        strategy = getattr(request, "social_strategy", None)
        backend = getattr(request, "backend", None)
        if strategy is None:
            return list(self.DEFAULT_TRANSPORT)

        raw_transports = strategy.setting("ERROR_TRANSPORT", self.DEFAULT_TRANSPORT, backend=backend)
        if isinstance(raw_transports, (str, ErrorTransport)):
            candidates = [raw_transports]
        elif isinstance(raw_transports, Iterable):
            candidates = list(raw_transports)
        else:
            candidates = [raw_transports]

        transports: list[ErrorTransport] = []
        for item in candidates:
            if isinstance(item, ErrorTransport):
                mode = item
            else:
                try:
                    mode = ErrorTransport(str(item).lower().strip())
                except ValueError:
                    continue
            if mode not in transports:
                transports.append(mode)

        return transports or list(self.DEFAULT_TRANSPORT)

    def get_error_param_name(self, request: HttpRequest) -> str:
        """Return the query parameter name used for error messages."""
        strategy = getattr(request, "social_strategy", None)
        backend = getattr(request, "backend", None)
        if strategy is not None:
            return strategy.setting("ERROR_PARAM_NAME", self.ERROR_PARAM_NAME, backend=backend)
        return self.ERROR_PARAM_NAME

    def get_backend_param_name(self, request: HttpRequest) -> str:
        """Return the query parameter name used for the backend identifier."""
        strategy = getattr(request, "social_strategy", None)
        backend = getattr(request, "backend", None)
        if strategy is not None:
            return strategy.setting("BACKEND_PARAM_NAME", self.BACKEND_PARAM_NAME, backend=backend)
        return self.BACKEND_PARAM_NAME

    def append_query_params(
        self,
        request: HttpRequest,
        url: str | None,
        message: str,
        backend_name: str,
    ) -> str | None:
        """Append or update error message and backend query parameters in the redirect URL.

        Preserves any existing URL fragments and other parameters while updating
        configured error parameter names.
        """
        if not url:
            return url

        error_param = self.get_error_param_name(request)
        backend_param = self.get_backend_param_name(request)

        scheme, netloc, path, query, fragment = urlsplit(url)
        query_params = parse_qsl(query, keep_blank_values=True)

        # Overwrite existing parameters so the latest failure details from the
        # current request are passed to the redirect target rather than stale values.
        updated_params = [(k, v) for k, v in query_params if k not in (error_param, backend_param)]
        updated_params.append((error_param, message))
        updated_params.append((backend_param, backend_name))

        new_query = urlencode(updated_params, quote_via=quote)
        return urlunsplit((scheme, netloc, path, new_query, fragment))

    def raise_exception(self, request: HttpRequest, exception: Exception) -> bool | None:
        """Return True if the caught exception should be re-raised instead of caught."""
        strategy = getattr(request, "social_strategy", None)
        if strategy is not None:
            backend = getattr(request, "backend", None)
            return strategy.setting("RAISE_EXCEPTIONS", settings.DEBUG, backend=backend)
        return None

    def get_message(self, request: HttpRequest, exception: Exception) -> str:
        """Return the error message string from the caught exception."""
        return str(exception)

    def get_redirect_uri(self, request: HttpRequest, exception: Exception) -> str | None:
        """Return the redirect URL target for the exception."""
        strategy = getattr(request, "social_strategy", None)
        backend = getattr(request, "backend", None)
        if strategy is None:
            return None
        return strategy.setting("LOGIN_ERROR_URL", backend=backend)
