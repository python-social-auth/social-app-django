# -*- coding: utf-8
import django
from django.conf.urls import url, include
from django.contrib import admin

from social_django.urls import urlpatterns as social_django_urls

if django.VERSION < (1, 9):
    admin_urls = include(admin.site.urls)
else:
    admin_urls = admin.site.urls

urlpatterns = [
    url(r'^admin/', admin_urls),
    url(r'^', include(social_django_urls, namespace='social')),
]
