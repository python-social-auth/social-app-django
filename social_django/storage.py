"""Django ORM models for Social Auth"""
import base64
import six
import sys
from django.core.exceptions import FieldDoesNotExist
from django.db import transaction, router
from django.db.utils import IntegrityError
from django.core.exceptions import ImproperlyConfigured

from social_core.storage import UserMixin, AssociationMixin, NonceMixin, \
    CodeMixin, PartialMixin, BaseStorage

from django.conf import settings
from social_core.utils import setting_name, module_member

import hashlib

from .audit.clients import AbstractBaseAuditLogger
AUDIT_LOGGER = getattr(settings, setting_name('AUDIT_LOGGER'), None)
if AUDIT_LOGGER is None:
    raise ImproperlyConfigured('Please provide an Audit Logger')
AuditLogger = module_member(AUDIT_LOGGER)
if not isinstance(AuditLogger(), AbstractBaseAuditLogger):
    raise ImproperlyConfigured('Provided Audit Logger is not an instance of django_social.audit.clients.AbstractBaseAuditLogger')



class DjangoUserMixin(UserMixin):
    """Social Auth association model"""

    @classmethod
    def changed(cls, user):
        user.save()

    def set_extra_data(self, extra_data=None):
        if super(DjangoUserMixin, self).set_extra_data(extra_data):
            self.save()

    @classmethod
    def allowed_to_disconnect(cls, user, backend_name, association_id=None):
        if association_id is not None:
            qs = cls.objects.exclude(id=association_id)
        else:
            qs = cls.objects.exclude(provider=backend_name)
        qs = qs.filter(user=user)

        if hasattr(user, 'has_usable_password'):
            valid_password = user.has_usable_password()
        else:
            valid_password = True
        return valid_password or qs.count() > 0

    @classmethod
    def disconnect(cls, entry):
        entry.delete()

    @classmethod
    def username_field(cls):
        return getattr(cls.user_model(), 'USERNAME_FIELD', 'username')

    @classmethod
    def user_exists(cls, *args, **kwargs):
        """
        Return True/False if a User instance exists with the given arguments.
        Arguments are directly passed to filter() manager method.
        """
        if 'username' in kwargs:
            kwargs[cls.username_field()] = kwargs.pop('username')
        return cls.user_model().objects.filter(*args, **kwargs).count() > 0

    @classmethod
    def get_username(cls, user):
        return getattr(user, cls.username_field(), None)

    @classmethod
    def create_user(cls, *args, **kwargs):
        username_field = cls.username_field()
        if 'username' in kwargs:
            if username_field not in kwargs:
                kwargs[username_field] = kwargs.pop('username')
            else:
                # If username_field is 'email' and there is no field named "username"
                # then latest should be removed from kwargs.
                try:
                    cls.user_model()._meta.get_field('username')
                except FieldDoesNotExist:
                    kwargs.pop('username')
        try:
            if hasattr(transaction, 'atomic'):
                # In Django versions that have an "atomic" transaction decorator / context
                # manager, there's a transaction wrapped around this call.
                # If the create fails below due to an IntegrityError, ensure that the transaction
                # stays undamaged by wrapping the create in an atomic.
                using = router.db_for_write(cls.user_model())
                with transaction.atomic(using=using):
                    user = cls.user_model().objects.create_user(*args, **kwargs)
            else:
                user = cls.user_model().objects.create_user(*args, **kwargs)
        except IntegrityError:
            # User might have been created on a different thread, try and find them.
            # If we don't, re-raise the IntegrityError.
            exc_info = sys.exc_info()
            # If email comes in as None it won't get found in the get
            if kwargs.get('email', True) is None:
                kwargs['email'] = ''
            try:
                user = cls.user_model().objects.get(*args, **kwargs)
            except cls.user_model().DoesNotExist:
                six.reraise(*exc_info)
        return user

    @classmethod
    def get_user(cls, pk=None, **kwargs):
        if pk:
            kwargs = {'pk': pk}
        try:
            return cls.user_model().objects.get(**kwargs)
        except cls.user_model().DoesNotExist:
            return None

    @classmethod
    def get_users_by_email(cls, email):
        user_model = cls.user_model()
        email_field = getattr(user_model, 'EMAIL_FIELD', 'email')
        return user_model.objects.filter(**{email_field + '__iexact': email})

    @classmethod
    def get_social_auth(cls, provider, uid):
        if not isinstance(uid, six.string_types):
            uid = str(uid)
        try:
            return cls.objects.get(provider=provider, uid=uid)
        except cls.DoesNotExist:
            return None

    @classmethod
    def get_social_auth_for_user(cls, user, provider=None, id=None):
        qs = cls.objects.filter(user=user)

        if provider:
            qs = qs.filter(provider=provider)

        if id:
            qs = qs.filter(id=id)
        return qs

    @classmethod
    def create_social_auth(cls, user, uid, provider):
        if not isinstance(uid, six.string_types):
            uid = str(uid)
        if hasattr(transaction, 'atomic'):
            # In Django versions that have an "atomic" transaction decorator / context
            # manager, there's a transaction wrapped around this call.
            # If the create fails below due to an IntegrityError, ensure that the transaction
            # stays undamaged by wrapping the create in an atomic.
            using = router.db_for_write(cls)
            with transaction.atomic(using=using):
                social_auth = cls.objects.create(user=user, uid=uid, provider=provider)
        else:
            social_auth = cls.objects.create(user=user, uid=uid, provider=provider)
        return social_auth


class CompliantDjangoUserMixin(DjangoUserMixin):
    @property
    def access_token(self):
        """Override method in UserMixin as we've broken it out of extra_data"""
        AuditLogger.log_decrypt_token_event(self.provider, self.user.id, self.actual_access_token)
        return self.actual_access_token

    def get_actual_refresh_token(self):
        """Helper function so that we can log the DecryptToken event"""
        if self.actual_refresh_token != '' and self.actual_refresh_token is not None:
            AuditLogger.log_decrypt_token_event(self.provider, self.user.id, self.actual_refresh_token)
        return self.actual_refresh_token

    def refresh_token(self, strategy, *args, **kwargs):
        """Override method in UserMixin as tokens are in their own fields now"""
        backend = self.get_backend_instance(strategy)
        token = self.actual_refresh_token or self.actual_access_token
        AuditLogger.log_decrypt_token_event(backend.name, self.user.id, token)
        if token and backend and hasattr(backend, 'refresh_token'):
            response = backend.refresh_token(token, user_id=self.user.id, *args, **kwargs)
            extra_data = backend.extra_data(self,
                                            self.uid,
                                            response,
                                            self.extra_data)
            # break the access token and refresh token out of the extra data
            self.actual_access_token = extra_data.pop('access_token', None)
            self.actual_refresh_token = extra_data.pop('refresh_token', None)
            if self.set_extra_data(extra_data):
                self.save()

    def set_extra_data(self, extra_data=None):
        """
        Making sure we never store the tokens in extra data
        """

        if extra_data:
            access_token = extra_data.pop('access_token', None)
            refresh_token = extra_data.pop('refresh_token', None)
            if access_token is not None:
                AuditLogger.log_encrypt_token_event(self.provider, self.user.id,
                                                    access_token)
                self.actual_access_token = access_token
                self.save()
            if refresh_token is not None:
                AuditLogger.log_encrypt_token_event(self.provider, self.user.id,
                                                    refresh_token)
                self.actual_refresh_token = refresh_token
                self.save()

            if self.extra_data != extra_data:
                if self.extra_data and not isinstance(
                        self.extra_data, six.string_types):
                    self.extra_data.update(extra_data)
                else:
                    self.extra_data = extra_data
                self.save()
                return True


class DjangoNonceMixin(NonceMixin):
    @classmethod
    def use(cls, server_url, timestamp, salt):
        return cls.objects.get_or_create(server_url=server_url,
                                         timestamp=timestamp,
                                         salt=salt)[1]

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
    def store(cls, server_url, association):
        # Don't use get_or_create because issued cannot be null
        try:
            assoc = cls.objects.get(server_url=server_url,
                                    handle=association.handle)
        except cls.DoesNotExist:
            assoc = cls(server_url=server_url,
                        handle=association.handle)

        try:
            assoc.secret = base64.encodebytes(association.secret).decode()
        except AttributeError:
            assoc.secret = base64.encodestring(association.secret).decode()
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
    @classmethod
    def get_code(cls, code):
        try:
            return cls.objects.get(code=code)
        except cls.DoesNotExist:
            return None


class DjangoPartialMixin(PartialMixin):
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
    user = CompliantDjangoUserMixin
    nonce = DjangoNonceMixin
    association = DjangoAssociationMixin
    code = DjangoCodeMixin
