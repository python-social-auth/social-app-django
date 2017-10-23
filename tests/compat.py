# coding=utf-8
import django
from django.conf.urls import include
from django.contrib import admin

if django.VERSION < (1, 9):
    admin_urls = include(admin.site.urls)
    base_url = 'http://testserver'
else:
    admin_urls = admin.site.urls
    base_url = ''

if django.VERSION < (1, 10):
    username_max_length = 30
else:
    username_max_length = 150
