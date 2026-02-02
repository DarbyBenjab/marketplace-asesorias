"""
Django settings for marketplace_backend project.
"""

from pathlib import Path
import os
from decouple import config
import dj_database_url 

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = 'django-insecure-(k0jdfhklz$g0zmt+1cb*nxi__(87zpo0724b_!cja#(o!^$zf'

DEBUG = config('DEBUG', default=True, cast=bool)

# Permitimos todo por ahora para facilitar el despliegue
ALLOWED_HOSTS = ["*"]

CSRF_TRUSTED_ORIGINS = [
    'https://marketplace-asesorias.onrender.com', 
]

# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    
    # --- TUS APPS ---
    'core',

    # --- APPS PARA LOGIN CON GOOGLE 
    'django.contrib.sites', 
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.google',
]

SITE_ID = 1 # <--- NECESARIO PARA GOOGLE LOGIN

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    
    # --- WHITENOISE (CRUCIAL PARA QUE SE VEA EL CSS EN INTERNET) ---
    'whitenoise.middleware.WhiteNoiseMiddleware', 
    
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    
    # --- MIDDLEWARE DE ALLAUTH (NECESARIO PARA GOOGLE) ---
    "allauth.account.middleware.AccountMiddleware",
]

ROOT_URLCONF = 'marketplace_backend.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

# --- CONFIGURACIÓN DE LOGIN (LOGIN CON GOOGLE) ---
AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
]

# Google Settings
SOCIALACCOUNT_PROVIDERS = {
    'google': {
        'APP': {
            'client_id': config('GOOGLE_CLIENT_ID'),
            'secret': config('GOOGLE_CLIENT_SECRET'),
            'key': ''
        },
        # --------------------
        'SCOPE': [
            'profile',
            'email',
        ],
        'AUTH_PARAMS': {
            'access_type': 'online',
        }
    }
}

WSGI_APPLICATION = 'marketplace_backend.wsgi.application'


# Database
# https://docs.djangoproject.com/en/6.0/ref/settings/#databases

# --- CONFIGURACIÓN INTELIGENTE DE BASE DE DATOS ---
# Esto hace lo siguiente:
# 1. Si estamos en la Nube (Render/Railway), usa la base de datos de allá automáticamente.
# 2. Si estamos en tu PC, usa la configuración local que pusiste tú.

DATABASES = {
    'default': dj_database_url.config(
        default='postgres://postgres:DARBYbeltran2001@localhost:5432/marketplace_db',
        conn_max_age=600
    )
}


# Password validation
AUTH_PASSWORD_VALIDATORS = [
    { 'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator', },
    { 'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', },
    { 'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator', },
    { 'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator', },
]


# Internationalization
LANGUAGE_CODE = 'es-cl'
TIME_ZONE = 'America/Santiago'
USE_I18N = True
USE_TZ = True
USE_L10N = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = 'static/'

# --- ESTO ES OBLIGATORIO PARA LA NUBE ---
# Es donde Django juntará todos los archivos CSS para que la web funcione
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

# Habilita compresión y caché de archivos estáticos
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'


# Configuración de usuario
AUTH_USER_MODEL = 'core.User'
LOGIN_REDIRECT_URL = 'lobby'
LOGOUT_REDIRECT_URL = 'inicio'
LOGIN_URL = 'login'

# Login con Google: No pedir username, solo email
ACCOUNT_EMAIL_REQUIRED = True
ACCOUNT_USERNAME_REQUIRED = False
SOCIALACCOUNT_QUERY_EMAIL = True
ACCOUNT_AUTHENTICATION_METHOD = 'username_email' 
ACCOUNT_EMAIL_VERIFICATION = 'none'              
ACCOUNT_SESSION_REMEMBER = True

# Archivos multimedia (CVs, Fotos)
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# Configuración de Correo (Gmail)
# NOTA: Para producción real, lo ideal es mover la contraseña al .env también,
# pero funcionará así por ahora.
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = 'darbybenjamin000@gmail.com' 
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD')
DEFAULT_FROM_EMAIL = 'Marketplace Asesores <darbybenjamin000@gmail.com>'

# CONFIGURACIÓN MERCADO PAGO
# Leemos el token del archivo .env.
MERCADO_PAGO_TOKEN = config('MP_ACCESS_TOKEN')

