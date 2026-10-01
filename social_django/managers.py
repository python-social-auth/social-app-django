from django.db import models


class UserSocialAuthManager(models.Manager):
    """Manager for the UserSocialAuth django model."""

    class Meta:
        app_label = "social_django"

    def get_social_auth(self, provider, uid, id_key=None):
        if not isinstance(uid, str):
            uid = str(uid)
        query = self.select_related("user").filter(provider=provider, uid=uid)
        if id_key is not None:
            query = query.filter(id_key=id_key)
        for social in query:
            if getattr(social, "uid", None) == uid and (id_key is None or getattr(social, "id_key", None) == id_key):
                return social
        return None
