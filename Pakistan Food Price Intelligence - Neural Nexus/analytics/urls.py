from django.urls import path
from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("api/analyze/", views.analyze, name="analyze"),
    path("api/forecast/", views.forecast_view, name="forecast"),
    path("api/outlook/", views.outlook_view, name="outlook"),
]
