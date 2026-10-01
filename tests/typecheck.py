"""Static regression checks, run alongside the library's mypy checks."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from typing_extensions import assert_type

    from social_django.models import AbstractUserSocialAuth, UserSocialAuth

    class CustomSocialAuth(AbstractUserSocialAuth):
        pass

    def check_manager_types() -> None:
        assert_type(UserSocialAuth.objects.create(), UserSocialAuth)
        assert_type(UserSocialAuth.objects.get(), UserSocialAuth)
        assert_type(UserSocialAuth.objects.all(), QuerySet[UserSocialAuth, UserSocialAuth])
        assert_type(CustomSocialAuth.objects.create(), CustomSocialAuth)
        assert_type(CustomSocialAuth.objects.all(), QuerySet[CustomSocialAuth, CustomSocialAuth])
