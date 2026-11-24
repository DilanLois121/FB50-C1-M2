"""Vistas API para el registro de atenciones veterinarias."""

import json

from django.http import JsonResponse
from django.views.decorators.http import require_POST

from inscripciones.auth import requiere_perfiles
from .services import ErrorAtenciones, registrar_atencion


@require_POST
@requiere_perfiles("veterinario")
def api_registrar_atencion(request, inscripcion_id):
    try:
        datos = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse(
            {
                "error": {
                    "codigo": "JSON_INVALIDO",
                    "mensaje": "El cuerpo de la solicitud no contiene JSON válido."
                }
            },
            status=400
        )

    if not isinstance(datos, dict):
        return JsonResponse(
            {
                "error": {
                    "codigo": "DATOS_INVALIDOS",
                    "mensaje": "La solicitud debe contener un objeto JSON."
                }
            },
            status=400
        )

    microchip = datos.get("microchip")

    try:
        atencion = registrar_atencion(
            inscripcion_id=inscripcion_id,
            usuario=request.usuario,
            perfil=request.perfil,
            microchip=microchip
        )

        return JsonResponse(
            {
                "mensaje": "Atención registrada correctamente.",
                "datos": {
                    "id": str(atencion["_id"]),
                    "inscripcionId": atencion["inscripcionId"],
                    "operativoId": atencion["operativoId"],
                    "animalId": atencion["animalId"],
                    "tipoOperativo": atencion["tipoOperativo"],
                    "estado": atencion["estado"],
                    "fechaAtencion": atencion["fechaAtencion"].isoformat(),
                    "veterinarioRut": atencion["veterinarioRut"],
                    "microchip": atencion.get("microchip")
                }
            },
            status=201
        )

    except ErrorAtenciones as error:
        return JsonResponse(
            {
                "error": {
                    "codigo": error.codigo,
                    "mensaje": error.mensaje
                }
            },
            status=error.estado_http
        )
