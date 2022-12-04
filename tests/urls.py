from casdoor_auth import views
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("social_django.urls", namespace="social")),
    path("login/", views.toLogin, name="casdoor_sso"),
    path("callback/", views.callback, name="callback"),
    path("casdoor/", include("casdoor_auth.urls")),
]
