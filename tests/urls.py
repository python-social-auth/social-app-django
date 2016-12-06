# -*- coding: utf-8
from django.conf.urls import url, include

from social_django.urls import urlpatterns as social_django_urls

urlpatterns = [
    url(r'^', include(social_django_urls, namespace='social')),
]
