"""Django ORM models for Social Auth"""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.exceptions import FieldDoesNotExist
from django.db import router, transaction
from django.db.utils import IntegrityError
from social_core.exceptions import AuthAlreadyAssociated
from social_core.storage import (
    AssociationMixin,
    BaseStorage,
    CodeMixin,
    NonceMixin,
    PartialMixin,
    UserMixin,
)
from social_core.utils import setting_name

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

    class _DjangoAssociation(Model):
        secret: str
        issued: int
        lifetime: int
        assoc_type: str


class DjangoUserMixin(UserMixin):
    """Social Auth association model"""

    objects: ClassVar[Manager[Model]]
    DoesNotExist: ClassVar[type[ObjectDoesNotExist]]

    @classmethod
    def user_model(cls) -> type[_DjangoUser]:
        """Return the Django user model."""
        raise NotImplementedError

    @classmethod
    def _manager(cls) -> Manager[Model]:
        return cls.objects

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
        manager = model._default_manager  # noqa: SLF001
        if "username" in kwargs:
            if username_field not in kwargs:
                kwargs[username_field] = kwargs.pop("username")
            else:
                # If username_field is 'email' and there is no field named "username"
                # then latest should be removed from kwargs.
                try:
                    model._meta.get_field("username")  # noqa: SLF001
                except FieldDoesNotExist:
                    kwargs.pop("username")

        # If the create fails below due to an IntegrityError, ensure that the transaction
        # stays undamaged by wrapping the create in an atomic.
        using = router.db_for_write(model)
        try:
            with transaction.atomic(using=using):
                return manager.create_user(*args, **kwargs)
        except IntegrityError as exc:
            raise AuthAlreadyAssociated(None) from exc  # type: ignore[arg-type]

    @classmethod
    def filter_users(cls, *args, **kwargs) -> QuerySet:
        model = cls.user_model()
        manager = model._default_manager  # noqa: SLF001
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
    def get_social_auth(cls, provider, uid):
        if not isinstance(uid, str):
            uid = str(uid)
        try:
            return cls._manager().get(provider=provider, uid=uid)
        except cls.DoesNotExist:
            return None

    @classmethod
    def get_social_auth_for_user(cls, user, provider=None, id=None):  # noqa: A002
        qs = cls._manager().filter(user=user)

        if provider:
            qs = qs.filter(provider=provider)

        if id:
            qs = qs.filter(id=id)
        return qs

    @classmethod
    def create_social_auth(cls, user, uid, provider):
        if not isinstance(uid, str):
            uid = str(uid)
        # If the create fails below due to an IntegrityError, ensure that the transaction
        # stays undamaged by wrapping the create in an atomic.
        manager = cls._manager()
        using = router.db_for_write(manager.model)
        with transaction.atomic(using=using):
            return manager.create(user=user, uid=uid, provider=provider)


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
