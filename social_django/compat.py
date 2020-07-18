# coding=utf-8
try:
    from django.utils.deprecation import MiddlewareMixin
except ImportError:
    MiddlewareMixin = object
