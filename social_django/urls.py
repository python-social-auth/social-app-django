"""URLs module"""

from django.conf import settings
from django.urls import path
from social_core.utils import setting_name

from . import views

extra = (getattr(settings, setting_name("TRAILING_SLASH"), True) and "/") or ""

app_name = "social"

urlpatterns = [
    # authentication / association
    path(f"login/<str:backend>{extra}", views.auth, name="begin"),
    path(f"complete/<str:backend>{extra}", views.complete, name="complete"),
    # launch endpoints
    path(f"idp-launch/<str:backend>{extra}", views.idp_launch, name="idp_launch"),
    path(f"app-launch/<str:backend>{extra}", views.app_launch, name="app_launch"),
    # disconnection
    path(f"disconnect/<str:backend>{extra}", views.disconnect, name="disconnect"),
    path(
        f"disconnect/<str:backend>/<int:association_id>{extra}",
        views.disconnect,
        name="disconnect_individual",
    ),
]
