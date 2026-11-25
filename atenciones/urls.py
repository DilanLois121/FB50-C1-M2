from django.urls import path

from .views import (
    api_registrar_atencion,
    api_cerrar_operativo
)
from .cuidados_views import api_registrar_cuidado


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
    path(
        "cuidados/<str:inscripcion_id>",
        api_registrar_cuidado,
        name="api_registrar_cuidado"
    ),
]
