from pathlib import Path
import os

try:
    from decouple import config
except ImportError:
    config = os.environ.get

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Secret key and debug
SECRET_KEY = os.getenv('SECRET_KEY', 'your-default-secret-key')
DEBUG = os.getenv('DEBUG', 'True') == 'True'
DOMAIN = 'http://localhost:8000'

ALLOWED_HOSTS = ['*']

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'channels',
    'downloader',
    'django_celery_results',
    'django_celery_beat',
    'storages'
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'youtube_downloader.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'youtube_downloader.wsgi.application'
ASGI_APPLICATION = 'youtube_downloader.asgi.application'

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [(os.getenv('REDIS_HOST', 'localhost'), int(os.getenv('REDIS_PORT', 6379)))],
        },
    },
}

# Celery Configuration
CELERY_BROKER_URL = f"redis://{os.getenv('REDIS_HOST', 'localhost')}:{os.getenv('REDIS_PORT', 6379)}/0"
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'UTC'
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True

# URL Expiry
URL_EXPIRY_SECONDS = 3600

# Database configuration
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv('POSTGRES_DB'),
        'USER': os.getenv('POSTGRES_USER'),
        'PASSWORD': os.getenv('POSTGRES_PASSWORD'),
        'HOST': os.getenv('POSTGRES_HOST', 'localhost'),
        'PORT': os.getenv('POSTGRES_PORT', '5432'),
    }
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True


CLOUDFLARE_R2_CONFIG_OPTIONS = {
    "bucket_name": config("CLOUDFLARE_R2_BUCKET"),
    "default_acl": "public-read",  # or "private"
    "signature_version": "s3v4",
    "endpoint_url": config("CLOUDFLARE_R2_BUCKET_ENDPOINT"),
    "access_key": config("CLOUDFLARE_R2_ACCESS_KEY"),
    "secret_key": config("CLOUDFLARE_R2_SECRET_KEY"),
    "region_name": "auto"
}

# CLOUDFLARE_R2_CONFIG_OPTIONS = {
#     "bucket_name": "digitalocean",
#     "default_acl": "public-read",  # or "private"
#     "signature_version": "s3v4",
#     "endpoint_url": "https://d3e89dc166edc0c2c8ab4c138097dfd7.r2.cloudflarestorage.com",
#     "access_key": "9957947f4180a5e3d98c15eb75a37779",
#     "secret_key": "f896d0c8ac50df859cef4f22a3db97208be0e7ca0eeee577eb5968632a38718a",
#     "region_name": "auto"
# }

# Introduced in Django 4.2
STORAGES = {
    "default": {
        "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
        "OPTIONS": CLOUDFLARE_R2_CONFIG_OPTIONS,
    },
    "staticfiles": {
        "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
        "OPTIONS": CLOUDFLARE_R2_CONFIG_OPTIONS,
    },
}

# Static files (CSS, JavaScript, Images)
STATIC_URL = 'static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
