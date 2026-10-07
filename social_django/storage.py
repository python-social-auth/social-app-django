"""Django ORM models for Social Auth"""

from __future__ import annotations

import base64
import re
import sqlite3
import time
from datetime import timedelta
from datetime import timezone as datetime_timezone
from typing import TYPE_CHECKING, cast

from django.conf import settings
from django.core.exceptions import FieldDoesNotExist
from django.db import router, transaction
from django.db.backends.utils import names_digest
from django.db.models import BigIntegerField, CharField, F, Field, Q, UniqueConstraint
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast
from django.db.utils import IntegrityError
from django.utils import timezone
from social_core.exceptions import AuthAssociationError
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
        secret: str
        issued: int
        lifetime: int
        assoc_type: str

        def __str__(self) -> str: ...

    class _DjangoSocialAuth(Model):
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

    def set_extra_data(self, extra_data=None):
        if super().set_extra_data(extra_data):
            self.save()

    @classmethod
    def allowed_to_disconnect(cls, user, backend_name, association_id=None):
        if association_id is not None:
            qs = cls._manager().exclude(id=association_id)
        else:
            qs = cls._manager().exclude(provider=backend_name)
        qs = qs.filter(user=user)

        valid_password = user.has_usable_password() if hasattr(user, "has_usable_password") else True
        return valid_password or qs.exists()

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
        manager = model._default_manager
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
        return cls.filter_active_users(**{f"{email_field}__iexact": email})

    @classmethod
    def get_social_auth(cls, provider, uid, id_key=None):
        if not isinstance(uid, str):
            uid = str(uid)
        query = cls._manager().filter(provider=provider, uid=uid)
        if id_key is not None:
            query = query.filter(id_key=id_key)
        for social in query:
            if social.uid == uid and (id_key is None or social.id_key == id_key):
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

        if id:
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
    def migrate_social_auth(cls, social, uid, id_key):
        manager = cls._manager()
        uid = str(uid)
        verified_extra_data = id_key in social.extra_data and str(social.extra_data[id_key]) == uid
        using = router.db_for_write(manager.model, instance=social)
        with transaction.atomic(using=using):
            query = manager.using(using)
            locked = query.select_for_update().get(pk=social.pk)
            if locked.uid != social.uid or locked.id_key != social.id_key:
                msg = "Social-auth association changed during identifier migration"
                raise IntegrityError(msg)
            if verified_extra_data and (id_key not in locked.extra_data or str(locked.extra_data[id_key]) != uid):
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

    @classmethod
    def use(cls, server_url, timestamp, salt):
        return cls.objects.get_or_create(server_url=server_url, timestamp=timestamp, salt=salt)[1]

    @classmethod
    def get(cls, server_url, salt):
        return cls.objects.get(
            server_url=server_url,
            salt=salt,
        )

    @classmethod
    def delete(cls, nonce):
        nonce.delete()


class DjangoAssociationMixin(AssociationMixin):
    @classmethod
    def cleanup_expired(cls, now: int | None = None) -> int:
        """Delete expired OpenID associations and OIDC nonces."""
        if now is None:
            now = int(time.time())
        expired = cls.objects.alias(expires=Cast("issued", BigIntegerField()) + F("lifetime")).filter(
            Q(lifetime__lte=0) | Q(expires__lte=now)
        )
        count, _ = expired.delete()
        return count

    objects: ClassVar[Manager[_DjangoAssociation]]
    DoesNotExist: ClassVar[type[ObjectDoesNotExist]]

    @classmethod
    def store(cls, server_url, association):
        # Don't use get_or_create because issued cannot be null
        try:
            assoc = cls.objects.get(
                server_url=server_url,
                handle=association.handle,
            )
        except cls.DoesNotExist:
            assoc = cls.objects.model(server_url=server_url, handle=association.handle)

        assoc.secret = base64.encodebytes(association.secret).decode()
        assoc.issued = association.issued
        assoc.lifetime = association.lifetime
        assoc.assoc_type = association.assoc_type
        assoc.save()

    @classmethod
    def get(cls, *args, **kwargs):
        return cls.objects.filter(*args, **kwargs)

    @classmethod
    def remove(cls, ids_to_delete):
        cls.objects.filter(pk__in=ids_to_delete).delete()


class DjangoCodeMixin(CodeMixin):
    objects: ClassVar[Manager[Model]]
    DoesNotExist: ClassVar[type[ObjectDoesNotExist]]

    def is_expired(self, seconds: int) -> bool:
        """Check expiry using Django's timezone for naive database timestamps."""
        if self.timestamp is None:
            return True
        timestamp = self.timestamp
        now = timezone.now()
        if timezone.is_naive(timestamp):
            timestamp = timezone.make_aware(timestamp, timezone.get_default_timezone())
        if timezone.is_naive(now):
            now = timezone.make_aware(now, timezone.get_default_timezone())
        timestamp = timestamp.astimezone(datetime_timezone.utc)
        return now.astimezone(datetime_timezone.utc) >= timestamp + timedelta(seconds=seconds)

    @classmethod
    def get_code(cls, code):
        try:
            return cls.objects.get(code=code)
        except cls.DoesNotExist:
            return None


class DjangoPartialMixin(PartialMixin):
    objects: ClassVar[Manager[Model]]
    DoesNotExist: ClassVar[type[ObjectDoesNotExist]]

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
