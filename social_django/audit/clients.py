class AbstractBaseAuditLogger(object):

    @classmethod
    def log_login_event(cls, source, user_id, request=None, **kwargs):
        raise NotImplementedError('Implement in subclass')

    @classmethod
    def log_delete_account_event(cls, source, user_id, request=None, **kwargs):
        raise NotImplementedError('Implement in subclass')

    @classmethod
    def log_request_token_event(cls, source, user_id, token, **kwargs):
        raise NotImplementedError('Implement in subclass')

    @classmethod
    def log_revoke_token_event(cls, source, user_id, token, **kwargs):
        raise NotImplementedError('Implement in subclass')

    @classmethod
    def log_encrypt_token_event(cls, source, user_id, token, **kwargs):
        raise NotImplementedError('Implement in subclass')

    @classmethod
    def log_decrypt_token_event(cls, source, user_id, token, **kwargs):
        raise NotImplementedError('Implement in subclass')


class DummyAuditLogger(AbstractBaseAuditLogger):

    @classmethod
    def log_login_event(cls, source, user_id, request=None, **kwargs):
        pass

    @classmethod
    def log_delete_account_event(cls, source, user_id, request=None, **kwargs):
        pass

    @classmethod
    def log_request_token_event(cls, source, user_id, token, **kwargs):
        pass

    @classmethod
    def log_revoke_token_event(cls, source, user_id, token, **kwargs):
        pass

    @classmethod
    def log_encrypt_token_event(cls, source, user_id, token, **kwargs):
        pass

    @classmethod
    def log_decrypt_token_event(cls, source, user_id, token, **kwargs):
        pass
