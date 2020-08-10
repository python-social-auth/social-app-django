"""URLs module"""
from django.conf import settings
from django.urls import path

from social_core.utils import setting_name
from . import views


extra = getattr(settings, setting_name('TRAILING_SLASH'), True) and '/' or ''

app_name = 'social'

urlpatterns = [
    # authentication / association
    path('login/<str:backend>{0}'.format(extra), views.auth,
        name='begin'),
    path('complete/<str:backend>{0}'.format(extra), views.complete,
        name='complete'),
    # disconnection
    path('disconnect/<str:backend>{0}'.format(extra), views.disconnect,
        name='disconnect'),
    path('disconnect/<str:backend>/<int:association_id>{0}'
        .format(extra), views.disconnect, name='disconnect_individual'),
]
