"""Static regression checks, run alongside the library's mypy checks."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Never, assert_type

    from django.db.models import QuerySet
    from django.http import HttpResponse
    from social_core.actions import do_auth, do_complete, do_disconnect
    from social_core.backends.base import BaseAuth
    from social_core.backends.github import GithubOAuth2
    from social_core.pipeline.partial import PartialStep, partial
    from social_core.storage import PartialMixin, UserProtocol

    from social_django.models import AbstractUserSocialAuth, UserSocialAuth
    from social_django.strategy import DjangoStrategy

    @partial
    def html_pipeline_step(strategy: DjangoStrategy, **kwargs: Any) -> HttpResponse:
        return strategy.html("<form></form>")

    @partial
    def response_free_step(**kwargs: Any) -> None:
        return None

    def check_response_types(strategy: DjangoStrategy, user: UserProtocol, saved_partial: PartialMixin) -> None:
        backend = GithubOAuth2(strategy)
        assert_type(backend, GithubOAuth2[HttpResponse])
        assert_type(strategy.html("<form></form>"), HttpResponse)
        assert_type(strategy.redirect("/"), HttpResponse)
        assert_type(strategy.html_with_headers("<form></form>", {"Cache-Control": "no-store"}), HttpResponse)
        assert_type(strategy.get_backend("github"), BaseAuth[HttpResponse])
        assert_type(backend.start(), HttpResponse)
        assert_type(backend.complete(), UserProtocol | HttpResponse | None)
        assert_type(strategy.authenticate(backend), UserProtocol | HttpResponse | None)
        assert_type(do_auth(backend), HttpResponse)
        assert_type(do_complete(backend, login=print), HttpResponse)
        assert_type(do_disconnect(backend, user), HttpResponse)
        assert_type(
            strategy.partial_pipeline_external_resume_confirmation(backend, saved_partial, {}), HttpResponse | None
        )
        assert_type(html_pipeline_step, PartialStep[HttpResponse])
        assert_type(html_pipeline_step(strategy, backend, 0), dict[str, Any] | HttpResponse)
        assert_type(response_free_step, PartialStep[Never])
        assert_type(response_free_step(strategy, backend, 0), dict[str, Any])

    class CustomSocialAuth(AbstractUserSocialAuth):
        pass

    def check_manager_types() -> None:
        assert_type(UserSocialAuth.objects.create(), UserSocialAuth)
        assert_type(UserSocialAuth.objects.get(), UserSocialAuth)
        assert_type(UserSocialAuth.objects.all(), QuerySet[UserSocialAuth, UserSocialAuth])
        assert_type(CustomSocialAuth.objects.create(), CustomSocialAuth)
        assert_type(CustomSocialAuth.objects.all(), QuerySet[CustomSocialAuth, CustomSocialAuth])
