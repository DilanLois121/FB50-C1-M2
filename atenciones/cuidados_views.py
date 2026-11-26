"""Vistas API para el registro de cuidados veterinarios."""

import json
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from inscripciones.auth import requiere_perfiles

from .services import ErrorAtenciones
from .cuidados_services import (
    agregar_nota_complementaria,
    obtener_cuidado_por_inscripcion,
    registrar_cuidado,
)

@csrf_exempt
@require_POST
@requiere_perfiles("veterinario")
def api_registrar_cuidado(request, inscripcion_id):
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

    try:
        cuidado = registrar_cuidado(
            inscripcion_id=inscripcion_id,
            usuario=request.usuario,
            datos=datos
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

    return JsonResponse(
        {
            "mensaje": "Cuidado registrado correctamente.",
            "datos": {
                "id": str(cuidado["_id"]),
                "inscripcion_id": str(cuidado["inscripcion_id"]),
                "veterinario_rut": cuidado["veterinario_rut"],
                "indicaciones": cuidado["indicaciones"],
                "medicamentos": cuidado["medicamentos"],
                "detalle_quirurgico": cuidado["detalle_quirurgico"],
                "fecha_registro": cuidado["fecha_registro"],
                "notas_complementarias": cuidado["notas_complementarias"],
            }
        },
        status=201
    )


@csrf_exempt
@require_POST
@requiere_perfiles("veterinario")
def api_agregar_nota_cuidado(request, cuidado_id):
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

    try:
        nota = agregar_nota_complementaria(
            cuidado_id=cuidado_id,
            usuario=request.usuario,
            texto_nota=datos.get("nota")
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

    return JsonResponse(
        {
            "mensaje": "Nota complementaria agregada exitosamente.",
            "datos": nota
        },
        status=201
    )


@require_GET
@requiere_perfiles(
    "veterinario",
    "funcionario"
)
def api_obtener_cuidado(request, inscripcion_id):
    try:
        cuidado = obtener_cuidado_por_inscripcion(
            inscripcion_id,
            request.perfil,
            request.usuario
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

    return JsonResponse(
        {
            "mensaje": "Cuidado obtenido.",
            "datos": cuidado
        },
        status=200
    )
