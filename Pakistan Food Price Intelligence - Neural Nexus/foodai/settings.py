import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Set SECRET_KEY in Vercel env vars for production.
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-insecure-key-change-me")
DEBUG = os.environ.get("DEBUG", "0") == "1"

_extra = [h.strip() for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h.strip()]
ALLOWED_HOSTS = ["localhost", "127.0.0.1", ".vercel.app"] + _extra
CSRF_TRUSTED_ORIGINS = ["https://*.vercel.app"] + [f"https://{h}" for h in _extra]

INSTALLED_APPS = ["analytics"]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
]
ROOT_URLCONF = "foodai.urls"
WSGI_APPLICATION = "foodai.wsgi.application"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": []},
}]
DATABASES = {}  # no database needed: data is read from the bundled CSV
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
