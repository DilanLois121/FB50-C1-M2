from django.urls import path

from .views import (
    api_registrar_atencion,
    api_cerrar_operativo
)


urlpatterns = [
    path(
        "atenciones/<str:inscripcion_id>",
        api_registrar_atencion,
        name="api_registrar_atencion"
    ),
    path(
        "operativos/<str:operativo_id>/cerrar",
        api_cerrar_operativo,
        name="api_cerrar_operativo"
    ),
]
