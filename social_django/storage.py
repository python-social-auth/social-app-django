"""Django ORM models for Social Auth"""

from __future__ import annotations

import base64
import re
import sqlite3
from datetime import UTC, timedelta
from time import time as _time
from typing import TYPE_CHECKING, cast

from django.conf import settings
from django.core.exceptions import FieldDoesNotExist
from django.db import DatabaseError, router, transaction
from django.db.backends.utils import names_digest
from django.db.models import BigIntegerField, CharField, F, Field, ImageField, Q, UniqueConstraint
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast
from django.db.utils import IntegrityError
from django.utils import timezone
from social_core.backends.utils import load_backends
from social_core.exceptions import AuthAssociationError, AuthCredentialError
from social_core.identifiers import identifier_matches
from social_core.storage import (
    AssociationMixin,
    BaseStorage,
    CodeMixin,
    NonceMixin,
    PartialMixin,
    UserMixin,
)
from social_core.utils import setting_name

# sqlite3 exposes extended result constants and exception codes on Python 3.11+.
SQLITE_UNIQUE_ERROR_CODE = getattr(sqlite3, "SQLITE_CONSTRAINT_UNIQUE", 2067)
SQLITE_PRIMARY_KEY_ERROR_CODE = getattr(sqlite3, "SQLITE_CONSTRAINT_PRIMARYKEY", 1555)
MYSQL_DUPLICATE_KEY_ERROR_CODE = 1062

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime
    from typing import ClassVar

    from django.core.exceptions import ObjectDoesNotExist
    from django.db.models import Manager, Model, QuerySet

    # These model/manager intersections must stay type-only. Defining them at
    # runtime would register additional models with Django.
    class _DjangoUserManager(Manager["_DjangoUser"]):
        def create_user(self, *args, **kwargs) -> _DjangoUser: ...

    class _DjangoUser(Model):
        _default_manager: ClassVar[_DjangoUserManager]
        USERNAME_FIELD: ClassVar[str]
        EMAIL_FIELD: ClassVar[str]
        id: int
        username: str
        is_active: bool | Callable[[], bool]
        is_authenticated: bool | Callable[[], bool]

        def __str__(self) -> str: ...

    class _DjangoAssociation(Model):
        server_url: str
        handle: str
        secret: str
        issued: int
        lifetime: int
        assoc_type: str

        def __str__(self) -> str: ...

    class _DjangoPartial(Model):
        def __str__(self) -> str: ...

        def is_expired(self, seconds: int) -> bool: ...

    class _DjangoSocialAuth(Model):
        user: _DjangoUser
        provider: str
        uid: str
        id_key: str
        extra_data: dict

        def __str__(self) -> str: ...

    class _DjangoSocialAuthManager(Manager[_DjangoSocialAuth]):
        """Manager whose querysets contain social-auth associations."""


class DjangoUserMixin(UserMixin):
    """Social Auth association model"""

    objects: ClassVar[Manager[Model]]
    DoesNotExist: ClassVar[type[ObjectDoesNotExist]]

    @classmethod
    def user_model(cls) -> type[_DjangoUser]:
        """Return the Django user model."""
        raise NotImplementedError

    @classmethod
    def _manager(cls) -> _DjangoSocialAuthManager:
        return cast("_DjangoSocialAuthManager", cls.objects)

    @classmethod
    def changed(cls, user):
        user.save()

    @classmethod
    def changed_fields(cls, user, fields: set[str]) -> None:
        if getattr(cls.changed, "__func__", cls.changed) is not getattr(
            DjangoUserMixin.changed, "__func__", DjangoUserMixin.changed
        ):
            # Custom storage classes may use changed() for additional work.
            cls.changed(user)
            return
        concrete = {
            name: field
            for field in user._meta.concrete_fields
            if not field.primary_key
            for name in (field.name, field.attname)
        }
        if not fields <= concrete.keys():
            # Properties can update arbitrary model fields; preserve the
            # existing storage contract when the assigned field is not known.
            cls.changed(user)
            return
        update_fields = {concrete[name].name for name in fields}
        for name in fields:
            field = concrete[name]
            if isinstance(field, ImageField):
                dimensions = (getattr(field, "width_field", None), getattr(field, "height_field", None))
                update_fields.update(name for name in dimensions if name)
        update_fields.update(field.name for field in user._meta.concrete_fields if getattr(field, "auto_now", False))
        user.save(update_fields=update_fields)

    def set_extra_data(self, extra_data=None):
        if not super().set_extra_data(extra_data):
            return
        social = cast("_DjangoSocialAuth", self)
        if social._state.adding:
            social.save()
            return
        using = router.db_for_write(type(social), instance=social)
        update_fields = ["extra_data"] + [
            field.name for field in social._meta.concrete_fields if getattr(field, "auto_now", False)
        ]
        try:
            with transaction.atomic(using=using):
                social.save(using=using, update_fields=update_fields)
        except DatabaseError as error:
            if type(social)._default_manager.using(using).filter(pk=social.pk).exists():
                raise
            raise AuthCredentialError(code="reauthentication_required", stage="pipeline") from error

    @classmethod
    def allowed_to_disconnect(cls, user, backend_name, association_id=None):
        if association_id is not None:
            qs = cls._manager().exclude(id=association_id)
        else:
            qs = cls._manager().exclude(provider=backend_name)
        qs = qs.filter(user=user)

        valid_password = user.has_usable_password() if hasattr(user, "has_usable_password") else True
        if valid_password:
            return True
        # Association-only backends link provider access to an already
        # authenticated user; they never log anyone in, so they are no fallback.
        login_backends = {
            name
            for name, backend in load_backends(settings.AUTHENTICATION_BACKENDS).items()
            if not getattr(backend, "ASSOCIATION_ONLY", False)
        }
        providers = qs.values_list("provider", flat=True)
        return any(provider in login_backends for provider in providers)

    @classmethod
    def disconnect(cls, entry):
        entry.delete()

    @classmethod
    def username_field(cls):
        return getattr(cls.user_model(), "USERNAME_FIELD", "username")

    @classmethod
    def user_exists(cls, *args, **kwargs):
        """
        Return True/False if a User instance exists with the given arguments.
        Arguments are directly passed to filter() manager method.
        """
        if "username" in kwargs:
            kwargs[cls.username_field()] = kwargs.pop("username")
        return cls.filter_users(*args, **kwargs).exists()

    @classmethod
    def get_username(cls, user):
        return getattr(user, cls.username_field(), None)

    @classmethod
    def create_user(cls, *args, **kwargs):
        username_field = cls.username_field()
        model = cls.user_model()
        manager = cast("_DjangoUserManager", model._default_manager)
        if "username" in kwargs:
            if username_field not in kwargs:
                kwargs[username_field] = kwargs.pop("username")
            else:
                # If username_field is 'email' and there is no field named "username"
                # then latest should be removed from kwargs.
                try:
                    model._meta.get_field("username")
                except FieldDoesNotExist:
                    kwargs.pop("username")

        # If the create fails below due to an IntegrityError, ensure that the transaction
        # stays undamaged by wrapping the create in an atomic.
        using = router.db_for_write(model)
        try:
            with transaction.atomic(using=using):
                return manager.create_user(*args, **kwargs)
        except IntegrityError as exc:
            code = cls._user_creation_conflict(exc)
            if code is not None:
                raise AuthAssociationError(code=code, stage="pipeline") from exc
            raise

    @staticmethod
    def _unique_constraint_name(error: IntegrityError) -> tuple[str, str] | None:
        """Recognize common PostgreSQL and MySQL duplicate-key diagnostics."""
        cause = error.__cause__
        if getattr(cause, "sqlstate", None) == "23505" or getattr(cause, "pgcode", None) == "23505":
            name = getattr(getattr(cause, "diag", None), "constraint_name", None)
            return ("postgresql", name) if name else None
        args: tuple[object, ...] = getattr(cause, "args", ())
        if len(args) > 1 and args[0] == MYSQL_DUPLICATE_KEY_ERROR_CODE and isinstance(args[1], str):
            match = re.search(r" for key ['`]([^'`]+)['`]$", args[1])
            if match:
                return "mysql", match[1].rsplit(".", 1)[-1]
        return None

    @staticmethod
    def _identifier_constraint_names(field: Field, vendor: str) -> set[str]:
        """Known single-column names, without database introspection or SQL parsing."""
        meta = field.model._meta
        names = {
            constraint.name
            for constraint in meta.constraints
            if isinstance(constraint, UniqueConstraint) and constraint.fields == (field.name,)
        }
        generated = set()
        if field.unique and field.column is not None:
            generated.add(field.column if vendor == "mysql" else f"{meta.db_table}_{field.column}_key")
        if field.column is not None and (field.unique or (field.name,) in meta.unique_together):
            # Recognize the common, untruncated migration name using Django's digest.
            digest = names_digest(meta.db_table, field.column, length=8)
            generated.add(f"{meta.db_table}_{field.column}_{digest}_uniq")
        if field.primary_key:
            generated.add("PRIMARY" if vendor == "mysql" else f"{meta.db_table}_pkey")
        # Explicit constraints with these names take precedence over defaults.
        return names | (generated - {constraint.name for constraint in meta.constraints})

    @classmethod
    def _user_creation_conflict(cls, error: IntegrityError) -> str | None:
        """Translate only identifier conflicts recognizable from cheap diagnostics."""
        model = cls.user_model()
        cause = error.__cause__
        constraint = cls._unique_constraint_name(error)
        sqlite_unique = isinstance(cause, sqlite3.IntegrityError) and getattr(
            cause, "sqlite_errorcode", SQLITE_UNIQUE_ERROR_CODE
        ) in (SQLITE_UNIQUE_ERROR_CODE, SQLITE_PRIMARY_KEY_ERROR_CODE)
        email_field = getattr(model, "EMAIL_FIELD", "email")
        for name, code in ((cls.username_field(), "username_in_use"), (email_field, "email_in_use")):
            try:
                field = model._meta.get_field(name)
            except FieldDoesNotExist:
                continue
            if not isinstance(field, Field) or field.column is None:
                continue
            table = field.model._meta.db_table
            # Exact single-column SQLite diagnostics also work on Python 3.10.
            if sqlite_unique and str(cause) == f"UNIQUE constraint failed: {table}.{field.column}":
                return code
            if constraint and constraint[1] in cls._identifier_constraint_names(field, constraint[0]):
                return code
        return None

    @classmethod
    def filter_users(cls, *args, **kwargs) -> QuerySet:
        model = cls.user_model()
        manager = model._default_manager
        return manager.filter(*args, **kwargs)

    @classmethod
    def filter_active_users(cls, *args, **kwargs) -> QuerySet:
        active_filter = getattr(settings, setting_name("ACTIVE_USERS_FILTER"), {"is_active": True})
        kwargs.update(active_filter)
        return cls.filter_users(*args, **kwargs)

    @classmethod
    def get_user(cls, pk=None, **kwargs):
        if pk:
            kwargs = {"pk": pk}
        users = cls.filter_active_users(**kwargs)
        if len(users) != 1:
            return None
        return users[0]

    @classmethod
    def get_users_by_email(cls, email):
        user_model = cls.user_model()
        email_field = getattr(user_model, "EMAIL_FIELD", "email")
        users = cls.filter_active_users(**{f"{email_field}__iexact": email})
        # What iexact matches is up to the database (collation, UPPER(), LIKE),
        # so compare again in Python and keep only the addresses that differ
        # from the requested one in nothing but letter case.
        matching = [
            pk
            for pk, value in users.values_list("pk", email_field)
            if value.lower() == email.lower() and value.upper() == email.upper()
        ]
        return users.filter(pk__in=matching)

    @classmethod
    def get_social_auth(cls, provider, uid, id_key=None):
        if not isinstance(uid, str):
            uid = str(uid)
        query = cls._manager().filter(provider=provider, uid=uid)
        if id_key is not None:
            query = query.filter(id_key=id_key)
        for social in query:
            if social.provider == provider and social.uid == uid and (id_key is None or social.id_key == id_key):
                return social
        return None

    @classmethod
    def get_social_auth_by_extra_data(cls, provider, key, value, id_key=""):
        matches = []
        query = (
            cls
            ._manager()
            .filter(provider=provider, id_key=id_key)
            .annotate(_social_auth_identifier=Cast(KeyTextTransform(key, "extra_data"), CharField()))
            .filter(_social_auth_identifier=str(value))
        )
        for social in query:
            if (
                social.provider == provider
                and social.id_key == id_key
                and key in social.extra_data
                and str(social.extra_data[key]) == str(value)
            ):
                matches.append(social)
                if len(matches) > 1:
                    msg = "Multiple social-auth associations matched extra data"
                    raise ValueError(msg)
        return matches[0] if matches else None

    @classmethod
    def get_social_auth_for_user(cls, user, provider=None, id=None):  # ruff: ignore[builtin-argument-shadowing]
        qs = cls._manager().filter(user=user)

        if provider:
            qs = qs.filter(provider=provider)

        if id is not None:
            qs = qs.filter(id=id)
        return qs

    @classmethod
    def create_social_auth(cls, user, uid, provider, id_key=""):
        if not isinstance(uid, str):
            uid = str(uid)
        # If the create fails below due to an IntegrityError, ensure that the transaction
        # stays undamaged by wrapping the create in an atomic.
        manager = cls._manager()
        using = router.db_for_write(manager.model)
        with transaction.atomic(using=using):
            return manager.create(user=user, uid=uid, provider=provider, id_key=id_key)

    @classmethod
    def migrate_social_auth(cls, social, uid, id_key, *, evidence_key=None):
        manager = cls._manager()
        uid = str(uid)
        # Preserve evidence checks for callers using the original interface.
        if evidence_key is None and identifier_matches(social.extra_data.get(id_key), uid):
            evidence_key = id_key
        if evidence_key is not None and not identifier_matches(social.extra_data.get(evidence_key), uid):
            msg = "Social-auth identifier evidence changed during migration"
            raise IntegrityError(msg)
        using = router.db_for_write(manager.model, instance=social)
        with transaction.atomic(using=using):
            query = manager.using(using)
            locked = query.select_for_update().get(pk=social.pk)
            if locked.uid != social.uid or locked.id_key != social.id_key:
                msg = "Social-auth association changed during identifier migration"
                raise IntegrityError(msg)
            if locked.extra_data != social.extra_data:
                msg = "Social-auth identifier evidence changed during migration"
                raise IntegrityError(msg)
            if evidence_key is not None and not identifier_matches(locked.extra_data.get(evidence_key), uid):
                msg = "Social-auth identifier evidence changed during migration"
                raise IntegrityError(msg)
            conflict = query.filter(provider=locked.provider, uid=uid).exclude(pk=locked.pk)
            if conflict.exists():
                msg = "Social-auth identifier migration conflict"
                raise IntegrityError(msg)
            locked.uid = uid
            locked.id_key = id_key
            locked.save(update_fields=["uid", "id_key", "modified"])
        return locked


class DjangoNonceMixin(NonceMixin):
    objects: ClassVar[Manager[Model]]
    DoesNotExist: ClassVar[type[ObjectDoesNotExist]]

    @classmethod
    def use(cls, server_url, timestamp, salt):
        return cls.objects.get_or_create(server_url=server_url, timestamp=timestamp, salt=salt)[1]

    @classmethod
    def get(cls, server_url: str, salt: str) -> Model | None:
        try:
            return cls.objects.get(server_url=server_url, salt=salt)
        except cls.DoesNotExist:
            return None

    @classmethod
    def delete(cls, nonce):
        nonce.delete()

    @classmethod
    def consume(cls, server_url: str, timestamp: int, salt: str) -> bool:
        deleted, _ = cls.objects.filter(server_url=server_url, timestamp=timestamp, salt=salt).delete()
        return deleted == 1


class DjangoAssociationMixin(AssociationMixin):
    @classmethod
    def cleanup_expired(cls, now: int | None = None) -> int:
        """Delete expired OpenID associations and OIDC nonces."""
        if now is None:
            now = int(_time())
        expired = cls.objects.alias(expires=Cast("issued", BigIntegerField()) + F("lifetime")).filter(
            Q(lifetime__lte=0) | Q(expires__lte=now)
        )
        count, _ = expired.delete()
        return count

    objects: ClassVar[Manager[_DjangoAssociation]]
    DoesNotExist: ClassVar[type[ObjectDoesNotExist]]

    @staticmethod
    def _is_unique_conflict(error: IntegrityError) -> bool:
        cause = error.__cause__
        if isinstance(cause, sqlite3.IntegrityError):
            return getattr(cause, "sqlite_errorcode", SQLITE_UNIQUE_ERROR_CODE) in (
                SQLITE_UNIQUE_ERROR_CODE,
                SQLITE_PRIMARY_KEY_ERROR_CODE,
            )
        if getattr(cause, "sqlstate", None) == "23505" or getattr(cause, "pgcode", None) == "23505":
            return True
        args: tuple[object, ...] = getattr(cause, "args", ())
        return bool(args) and (args[0] == MYSQL_DUPLICATE_KEY_ERROR_CODE or getattr(args[0], "code", None) == 1)

    @classmethod
    def store(cls, server_url, association):
        # A collation may equate distinct URLs or handles under the database
        # uniqueness constraint. Never overwrite the other provider's secret.
        using = router.db_for_write(cls.objects.model)
        values = {
            "server_url": server_url,
            "handle": association.handle,
            "secret": base64.encodebytes(association.secret).decode(),
            "issued": association.issued,
            "lifetime": association.lifetime,
            "assoc_type": association.assoc_type,
        }
        try:
            # Write first. A read before the write makes concurrent stores fail
            # while upgrading SQLite's deferred transaction to a write lock.
            with transaction.atomic(using=using):
                cls.objects.using(using).create(**values)
        except IntegrityError as error:
            existing = None
            with transaction.atomic(using=using):
                try:
                    existing = (
                        cls.objects
                        .using(using)
                        .select_for_update()
                        .get(server_url=server_url, handle=association.handle)
                    )
                except cls.DoesNotExist:
                    # A uniqueness constraint may use a broader collation than
                    # the exact lookup. Find that conflict before re-raising.
                    try:
                        existing = (
                            cls.objects
                            .using(using)
                            .select_for_update()
                            .get(server_url__iexact=server_url, handle__iexact=association.handle)
                        )
                    except cls.DoesNotExist:
                        existing = None
                if existing is not None:
                    if existing.server_url != server_url or existing.handle != association.handle:
                        raise AuthAssociationError(
                            code="openid_association_collision",
                            source="storage",
                            stage="callback",
                            recovery="contact_administrator",
                        ) from error
                    for name, value in values.items():
                        setattr(existing, name, value)
                    existing.save(using=using, update_fields=values)
                    return
            if not cls._is_unique_conflict(error):
                raise error from None
            # Cleanup may have removed the conflicting row after the failed
            # insert. Retry from a fresh transaction to avoid SQLite upgrades.
            with transaction.atomic(using=using):
                cls.objects.using(using).create(**values)
        else:
            return

    @classmethod
    def get(cls, *args, **kwargs):
        query = cls.objects.filter(*args, **kwargs)
        # We need to compare to filter out case- and accent-insensitive
        # lookups in some databases (MySQL/MariaDB): a secret negotiated
        # with one server must never verify assertions for another.
        exact = {name: kwargs[name] for name in ("server_url", "handle") if name in kwargs}
        if not exact:
            return query
        return query.filter(
            pk__in=[assoc.pk for assoc in query if all(getattr(assoc, name) == value for name, value in exact.items())]
        )

    @classmethod
    def remove(cls, ids_to_delete):
        cls.objects.filter(pk__in=ids_to_delete).delete()


def _is_expired(timestamp: datetime | None, seconds: int) -> bool:
    """Check expiry using Django's timezone for naive database timestamps."""
    if timestamp is None:
        return True
    now = timezone.now()
    if timezone.is_naive(timestamp):
        timestamp = timezone.make_aware(timestamp, timezone.get_default_timezone())
    if timezone.is_naive(now):
        now = timezone.make_aware(now, timezone.get_default_timezone())
    timestamp = timestamp.astimezone(UTC)
    return now.astimezone(UTC) >= timestamp + timedelta(seconds=seconds)


class DjangoCodeMixin(CodeMixin):
    objects: ClassVar[Manager[Model]]
    DoesNotExist: ClassVar[type[ObjectDoesNotExist]]

    def is_expired(self, seconds: int) -> bool:
        """Check expiry using Django's timezone for naive database timestamps."""
        return _is_expired(self.timestamp, seconds)

    def verify(self) -> None:
        """Claim the code with a conditional update so that only one request can spend it."""
        code = cast("Model", self)
        using = router.db_for_write(type(code), instance=code)
        claimed = type(self).objects.using(using).filter(pk=code.pk, verified=False).update(verified=True)
        if not claimed:
            raise AuthCredentialError(code="email_verification_rejected", stage="pipeline")
        self.verified = True

    @classmethod
    def get_code(cls, code):
        try:
            return cls.objects.get(code=code)
        except cls.DoesNotExist:
            return None


class DjangoPartialMixin(PartialMixin):
    timestamp: datetime | None = None

    objects: ClassVar[Manager[_DjangoPartial]]
    DoesNotExist: ClassVar[type[ObjectDoesNotExist]]

    def is_expired(self, seconds: int) -> bool:
        """Return whether the partial has reached its lifetime, or has no timestamp."""
        return _is_expired(self.timestamp, seconds)

    @classmethod
    def load(cls, token):
        try:
            return cls.objects.get(token=token)
        except cls.DoesNotExist:
            return None

    @classmethod
    def destroy(cls, token):
        partial = cls.load(token)
        if partial:
            partial.delete()


class BaseDjangoStorage(BaseStorage):
    user = DjangoUserMixin
    nonce = DjangoNonceMixin
    association = DjangoAssociationMixin
    code = DjangoCodeMixin
