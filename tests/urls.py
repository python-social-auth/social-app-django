# -*- coding: utf-8
from django.conf.urls import url, include
from django.contrib import admin


urlpatterns = [
    url(r'^admin/', admin.site.urls),
    url(r'^', include('social_django.urls', namespace='social')),
]
