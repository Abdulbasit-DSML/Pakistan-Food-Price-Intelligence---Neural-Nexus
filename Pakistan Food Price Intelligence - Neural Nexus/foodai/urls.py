from django.http import HttpResponse
from django.urls import include, path

urlpatterns = [
    path("favicon.ico", lambda r: HttpResponse(status=204)),
    path("", include("analytics.urls")),
]
