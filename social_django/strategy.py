from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any, cast

from django.conf import settings
from django.contrib.auth import authenticate, get_user
from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from django.db import router, transaction
from django.db.models import Model
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render, resolve_url
from django.template import TemplateDoesNotExist, engines, loader
from django.utils.crypto import get_random_string
from django.utils.datastructures import MultiValueDict
from django.utils.encoding import force_str
from django.utils.functional import Promise
from django.utils.translation import get_language
from social_core.exceptions import AuthConfigurationError, AuthSessionError
from social_core.groups import group_sync_targets
from social_core.strategy import BaseStrategy, BaseTemplateStrategy
from social_core.utils import PARTIAL_TOKEN_PENDING_CONFIRMATION_SESSION_NAME, user_is_authenticated

if TYPE_CHECKING:
    from django.contrib.sessions.backends.base import SessionBase
    from social_core.backends.base import BaseAuth
    from social_core.storage import PartialMixin


PARTIAL_PIPELINE_CONFIRMATION_NONCE_PARAMETER = "partial_pipeline_confirm_nonce"
_SESSION_VALUE_MARKER = "__social_django_session_value__"


def _is_model_reference(value: Any) -> bool:
    return isinstance(value, dict) and value.keys() == {"pk", "ctype"} and type(value["ctype"]) is int


def render_template_string(request, html, context=None):
    """
    Take a template in the form of a string and render it for the
    given context
    """
    template = engines["django"].from_string(html)
    return template.render(context=context, request=request)


class DjangoTemplateStrategy(BaseTemplateStrategy):
    def render_template(self, tpl, context):
        template = loader.get_template(tpl)
        return template.render(context=context, request=self.strategy.request)

    def render_string(self, html, context):
        return render_template_string(self.strategy.request, html, context)


def create_session(session_key: str | None = None) -> SessionBase:
    engine = import_module(settings.SESSION_ENGINE)
    return engine.SessionStore(session_key)


class DjangoStrategy(BaseStrategy):
    DEFAULT_TEMPLATE_STRATEGY = DjangoTemplateStrategy
    _session: SessionBase

    def __init__(self, storage, request: HttpRequest | None = None, tpl=None):
        self.request = request
        if request:
            self.session = request.session
        super().__init__(storage, tpl)

    def _require_request(self) -> HttpRequest:
        if self.request is None:
            msg = "This strategy operation requires an HTTP request"
            raise RuntimeError(msg)
        return self.request

    def sync_user_groups(self, user, groups, *, backend, response, **kwargs) -> None:
        """Synchronize existing standard Django groups selected by name."""
        desired, managed = group_sync_targets(backend, groups, response)
        if not managed:
            return
        if any(not isinstance(target, str) for target in managed) or (
            not hasattr(user, "groups") or user.groups.model is not Group or not user.groups.through._meta.auto_created
        ):
            raise AuthConfigurationError(
                backend,
                code="invalid_setting",
                parameter="GROUPS_MAP",
                stage="pipeline",
            )
        using = router.db_for_write(user.groups.through, instance=user)
        desired_names = cast("set[str]", desired)
        managed_names = cast("set[str]", managed)
        with transaction.atomic(using=using):
            targets = dict(Group.objects.using(using).filter(name__in=managed_names).values_list("name", "pk"))
            if set(targets) != managed_names:
                raise AuthConfigurationError(
                    backend,
                    "A mapped Django group does not exist",
                    code="invalid_setting",
                    parameter="GROUPS_MAP",
                    stage="pipeline",
                )
            current = set(user.groups.using(using).values_list("name", flat=True))
            user.groups.remove(*(targets[name] for name in (current & managed_names) - desired_names))
            user.groups.add(*(targets[name] for name in desired_names - current))
        for cache in ("_perm_cache", "_group_perm_cache", "_user_perm_cache"):
            if hasattr(user, cache):
                delattr(user, cache)

    @property
    def session(self) -> SessionBase:
        try:
            return self._session
        except AttributeError:
            self._session = create_session()
            return self._session

    @session.setter
    def session(self, value: SessionBase) -> None:
        self._session = value

    def get_setting(self, name):
        value = getattr(settings, name)
        # Force text on URL named settings that are instance of Promise
        if name.endswith("_URL") and value:
            if isinstance(value, Promise):
                value = force_str(value)
            value = resolve_url(value)
        return value

    def get_request_data(self, merge=True):
        if not self.request:
            return {}
        if merge:
            data = self.request.GET.copy()
            data.update(self.request.POST)
        elif self.request.method == "POST":
            data = self.request.POST
        else:
            data = self.request.GET
        return data

    def request_host(self):
        if self.request:
            return self.request.get_host()
        return None

    def request_is_secure(self):
        """Is the request using HTTPS?"""
        return self._require_request().is_secure()

    def request_path(self):
        """Path of the current request"""
        return self._require_request().path

    def request_port(self):
        """Port in use for this request"""
        return self._require_request().get_port()

    def request_get(self):
        """Request GET data"""
        return self._require_request().GET.copy()

    def request_post(self):
        """Request POST data"""
        return self._require_request().POST.copy()

    def redirect(self, url):
        return redirect(url)

    def html(self, content):
        return HttpResponse(content, content_type="text/html;charset=UTF-8")

    def partial_pipeline_external_resume_confirmation(  # type: ignore[override]
        self,
        backend: BaseAuth,
        partial: PartialMixin,
        request_data: dict[str, Any],
    ) -> HttpResponse | None:
        if not self.request:
            return None

        nonce = self.random_string(32)
        self.session_set(PARTIAL_TOKEN_PENDING_CONFIRMATION_SESSION_NAME, nonce)
        confirmation_parameter = backend.setting(
            "PARTIAL_PIPELINE_EXTERNAL_RESUME_CONFIRMATION_PARAMETER",
            "partial_pipeline_confirm",
        )
        return render(
            self.request,
            "social_django/partial_pipeline_external_resume.html",
            {
                "action_url": self.request.path,
                "backend": backend,
                "backend_name": backend.name,
                "confirmation_parameter": confirmation_parameter,
                "confirmation_value": "1",
                "confirmation_nonce_parameter": (PARTIAL_PIPELINE_CONFIRMATION_NONCE_PARAMETER),
                "confirmation_nonce": nonce,
                "partial": partial,
            },
        )

    def partial_pipeline_external_resume_confirmed(
        self,
        backend: BaseAuth,
        request_data: dict[str, Any],
    ) -> bool:
        if not self.request or self.request.method != "POST":
            return False

        confirmation_parameter = backend.setting(
            "PARTIAL_PIPELINE_EXTERNAL_RESUME_CONFIRMATION_PARAMETER",
            "partial_pipeline_confirm",
        )
        if not confirmation_parameter or confirmation_parameter not in request_data:
            return False

        expected_nonce = self.session_get(PARTIAL_TOKEN_PENDING_CONFIRMATION_SESSION_NAME)
        submitted_nonce = request_data.get(PARTIAL_PIPELINE_CONFIRMATION_NONCE_PARAMETER)
        return bool(expected_nonce) and submitted_nonce == expected_nonce

    def render_html(self, tpl=None, html=None, context=None):
        if not tpl and not html:
            msg = "Missing template or html parameters"
            raise ValueError(msg)
        context = context or {}
        try:
            template = loader.get_template(tpl)
            return template.render(context=context, request=self.request)
        except (TypeError, TemplateDoesNotExist):
            return render_template_string(self.request, html, context)

    def authenticate(self, backend, **kwargs):
        kwargs["strategy"] = self
        kwargs["storage"] = self.storage
        kwargs["backend"] = backend
        kwargs.pop("request", None)
        return authenticate(self.request, **kwargs)

    def clean_authenticate_args(self, request, *args, **kwargs):
        # pipelines don't want a positional request argument
        kwargs.pop("request", None)
        return args, kwargs

    def session_get(self, name, default=None):
        return self.session.get(name, default)

    def session_set(self, name, value):
        self.session[name] = value
        if hasattr(self.session, "modified"):
            self.session.modified = True

    def session_pop(self, name):
        return self.session.pop(name, None)

    def session_setdefault(self, name, value):
        return self.session.setdefault(name, value)

    def build_absolute_uri(self, path=None):
        if self.request:
            return self.request.build_absolute_uri(path)
        return path

    def random_string(self, length=12, chars=BaseStrategy.ALLOWED_CHARS):
        return get_random_string(length, chars)

    def to_session_value(self, val: Any) -> Any:
        """Encode model references and escape dictionaries that resemble encoded values."""
        if isinstance(val, MultiValueDict):
            val = val.dict()
        if isinstance(val, Model):
            return {
                _SESSION_VALUE_MARKER: 1,
                "kind": "model",
                "value": {"pk": val.pk, "ctype": ContentType.objects.get_for_model(val).pk},
            }
        if isinstance(val, dict) and (_SESSION_VALUE_MARKER in val or {"pk", "ctype"} <= val.keys()):
            return {_SESSION_VALUE_MARKER: 1, "kind": "plain", "value": val}
        return val

    def from_session_value(self, val: Any) -> Any:
        """Decode one saved value, including model references from older partials."""
        if isinstance(val, dict) and _SESSION_VALUE_MARKER in val:
            if (
                val.keys() != {_SESSION_VALUE_MARKER, "kind", "value"}
                or type(val[_SESSION_VALUE_MARKER]) is not int
                or val[_SESSION_VALUE_MARKER] != 1
            ):
                return val
            payload = val["value"]
            if val["kind"] == "plain" and isinstance(payload, dict):
                # Do not decode again: the payload may itself resemble a reference.
                return payload
            if val["kind"] != "model" or not _is_model_reference(payload):
                return val
            val = payload
        elif not _is_model_reference(val):
            return val

        ctype = ContentType.objects.get_for_id(val["ctype"])
        model_class = ctype.model_class()
        if model_class is None:
            msg = f"Content type {ctype.pk} does not reference a model"
            raise TypeError(msg)
        return model_class._default_manager.get(pk=val["pk"])

    def get_language(self):
        """Return current language"""
        return get_language()

    def get_session_id(self) -> str | None:
        if self.session.session_key is None:
            self.session.create()
        return self.session.session_key

    def restore_session(self, session_id: str, kwargs: dict[str, Any]) -> None:
        request = self._require_request()
        restored_session = create_session(session_id)
        restored_request = HttpRequest()
        restored_request.session = restored_session
        restored_user = get_user(restored_request)
        incoming_user = kwargs.get("user")
        if user_is_authenticated(incoming_user) and (
            not restored_user.is_authenticated or incoming_user != restored_user
        ):
            raise AuthSessionError(code="user_mismatch", stage="callback")

        request.session = self.session = restored_session
        request.user = restored_user
        if "user" in kwargs:
            kwargs["user"] = restored_user if restored_user.is_authenticated else None
        # Rotate session key to avoid reuse
        self.session.cycle_key()
