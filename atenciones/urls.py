from django.urls import path

from .views import api_registrar_atencion


urlpatterns = [
    path(
        "atenciones/<str:inscripcion_id>",
        api_registrar_atencion,
        name="api_registrar_atencion"
    ),
]
