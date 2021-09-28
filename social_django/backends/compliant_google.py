from social_core.backends.google import GoogleOAuth2
from ..storage import AuditLogger
import hashlib

from social_core.utils import handle_http_errors


class CompliantGoogleOAuth2(GoogleOAuth2):

    def request(self, url, method='GET', *args, **kwargs):
        return super(CompliantGoogleOAuth2, self).request(url, method, *args, **kwargs)

    def request_access_token(self, *args, **kwargs):
        json = super().request_access_token(*args, **kwargs)
        AuditLogger.log_request_token_event(self.name, None, json['access_token'])
        return json

    def refresh_token(self, token, *args, **kwargs):
        AuditLogger.log_request_token_event(self.name, kwargs.get('user_id', None), token)
        return super().refresh_token(self, token, *args, **kwargs)

    def revoke_token(self, token, uid, user_id=None):
        if self.REVOKE_TOKEN_URL:
            url = self.revoke_token_url(token, uid)
            params = self.revoke_token_params(token, uid)
            headers = self.revoke_token_headers(token, uid)
            data = urlencode(params) if self.REVOKE_TOKEN_METHOD != 'GET' \
                else None

            response = self.request(url, params=params, headers=headers,
                                    data=data, method=self.REVOKE_TOKEN_METHOD)
            revoke_token_successful = self.process_revoke_token_response(response)
            if revoke_token_successful:
                AuditLogger.log_revoke_token_event(self.name, user_id, token)
            return revoke_token_response
