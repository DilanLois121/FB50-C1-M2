"""Rutas HTTP del recurso Inscripciones."""

from django.urls import path

from . import views


urlpatterns = [
    path("inscripciones", views.api_inscripciones, name="api_inscripciones"),
    path(
        "inscripciones/<str:inscripcion_id>/estado",
        views.api_inscripcion_estado,
        name="api_inscripcion_estado",
    ),
]
