"""URLs module"""
from django.conf import settings


from social_core.utils import setting_name
from . import views
from .compat import re_path


extra = getattr(settings, setting_name('TRAILING_SLASH'), True) and '/' or ''

app_name = 'social'

urlpatterns = [
    # authentication / association
    re_path(r'^login/(?P<backend>[^/]+){0}$'.format(extra), views.auth,
            name='begin'),
    re_path(r'^complete/(?P<backend>[^/]+){0}$'.format(extra), views.complete,
            name='complete'),
    # disconnection
    re_path(r'^disconnect/(?P<backend>[^/]+){0}$'.format(extra), views.disconnect,
            name='disconnect'),
    re_path(r'^disconnect/(?P<backend>[^/]+)/(?P<association_id>\d+){0}$'
            .format(extra), views.disconnect, name='disconnect_individual'),
]
