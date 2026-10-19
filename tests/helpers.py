from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlsplit

from django.conf import settings
from django.http import HttpRequest
from django.middleware.csrf import get_token
from django.urls import reverse

if TYPE_CHECKING:
    from django.test import Client


def begin_facebook_login(client: Client) -> str:
    """Start a Facebook flow and return the state generated for this client."""
    request = HttpRequest()
    csrf_token = get_token(request)
    client.cookies[settings.CSRF_COOKIE_NAME] = request.META["CSRF_COOKIE"]
    response = client.post(
        reverse("social:begin", kwargs={"backend": "facebook"}),
        {"csrfmiddlewaretoken": csrf_token},
    )
    return parse_qs(urlsplit(response["Location"]).query)["state"][0]
