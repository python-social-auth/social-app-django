import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DEBUG = True
USE_TZ = True

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

ROOT_URLCONF = "tests.urls"

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.sites",
    "django.contrib.messages",
    "django.contrib.admin",
    "social_django",

    "casdoor_auth",  # pip install django-casdoor-auth
]

SITE_ID = 1

MIDDLEWARE = (
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "social_django.middleware.SocialAuthExceptionMiddleware",
)

AUTHENTICATION_BACKENDS = (
    "social_core.backends.facebook.FacebookOAuth2",
    "django.contrib.auth.backends.ModelBackend",
)

CASDOOR_CONFIG = {
    'endpoint': 'http://localhost:8000',
    'client_id': '<client-id>',
    'client_secret': '<client-secret>',
    'certificate': '''<certificate>''',
    'org_name': 'built-in',
    'application_name': 'app-built-in'
}

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "DIRS": [os.path.join(BASE_DIR, "templates")],
        "OPTIONS": {
            "context_processors": [
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "django.template.context_processors.request",
                "social_django.context_processors.backends",
                "social_django.context_processors.login_redirect",
            ],
        },
    },
]

# Page to go after successfull login
REDIRECT_URI = 'http://127.0.0.1:8000/casdoor/callback/'
LOGIN_REDIRECT_URL = '/'

SECRET_KEY = "6p%gef2(6kvjsgl*7!51a7z8c3=u4uc&6ulpua0g1^&sthiifp"

STATIC_URL = "/static/"
