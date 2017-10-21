# -*- coding: utf-8
from django.conf.urls import url, include
from .compat import admin_urls


urlpatterns = [
    url(r'^admin/', admin_urls),
    url(r'^', include('social_django.urls', namespace='social')),
]
