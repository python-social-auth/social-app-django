# coding=utf-8
import django
from django.conf.urls import include
from django.contrib import admin

if django.VERSION < (1, 9):
    admin_urls = include(admin.site.urls)
else:
    admin_urls = admin.site.urls
