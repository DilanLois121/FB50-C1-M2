"""Vistas HTTP del recurso Inscripciones."""

import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from pymongo.errors import PyMongoError

from .auth import requiere_perfiles
from .serializers import (
    ErrorSalidaInscripcion,
    ErrorValidacionInscripcion,
    InscripcionSerializer,
)
from .services import (
    ErrorInscripciones,
    cambiar_estado_inscripcion,
    crear_inscripcion,
    listar_inscripciones,
)


PERFILES_INSCRIPCIONES = ("funcionario", "vecino", "comunitario")


def _respuesta_error(codigo: str, mensaje: str, estado: int) -> JsonResponse:
    return JsonResponse(
        {"error": {"codigo": codigo, "mensaje": mensaje}},
        status=estado
    )


def _rechazar_constante_json(valor: str):
    raise ValueError(f"Constante JSON no permitida: {valor}")


def _leer_json(request):
    if request.content_type != "application/json":
        raise ErrorValidacionInscripcion(
            "TIPO_CONTENIDO_INVALIDO",
            "El tipo de contenido debe ser application/json.",
            415
        )

    try:
        return json.loads(request.body, parse_constant=_rechazar_constante_json)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        raise ErrorValidacionInscripcion(
            "JSON_INVALIDO",
            "El cuerpo de la petición debe contener JSON válido."
        )


@csrf_exempt
@requiere_perfiles(*PERFILES_INSCRIPCIONES)
def api_inscripciones(request):
    if request.method == "POST":
        try:
            datos = InscripcionSerializer.validar_creacion(_leer_json(request))
            documento = crear_inscripcion(
                operativo_id=datos["operativoId"],
                animal_id=datos["animalId"],
                rut_solicitante=request.usuario["rut"],
                perfil=request.perfil,
                token=request.token_bearer,
            )
        except ErrorValidacionInscripcion as error:
            return _respuesta_error(
                error.codigo,
                error.mensaje,
                error.estado_http
            )
        except ErrorInscripciones as error:
            return _respuesta_error(
                error.codigo,
                error.mensaje,
                error.estado_http
            )
        except (PyMongoError, RuntimeError):
            return _respuesta_error(
                "ERROR_BASE_DATOS",
                "No fue posible guardar la inscripción.",
                500
            )

        try:
            datos_salida = InscripcionSerializer.representar(documento)
        except ErrorSalidaInscripcion:
            return _respuesta_error(
                "ERROR_RESPUESTA",
                "No fue posible representar la inscripción guardada.",
                500
            )
        return JsonResponse({"datos": datos_salida}, status=201)

    if request.method == "GET":
        try:
            page = int(request.GET.get("page", "1"))
            limit = int(request.GET.get("limit", "20"))
        except (TypeError, ValueError):
            return _respuesta_error(
                "PAGINACION_INVALIDA",
                "page y limit deben ser números enteros.",
                400
            )

        if page < 1 or limit < 1 or limit > 100:
            return _respuesta_error(
                "PAGINACION_INVALIDA",
                "page debe ser mayor que cero y limit debe estar entre 1 y 100.",
                400
            )

        rut = (
            request.usuario["rut"]
            if request.perfil in {"vecino", "comunitario"}
            else None
        )
        try:
            total, documentos = listar_inscripciones(page, limit, rut)
        except (PyMongoError, RuntimeError):
            return _respuesta_error(
                "ERROR_BASE_DATOS",
                "No fue posible consultar las inscripciones.",
                500
            )

        try:
            datos = [
                InscripcionSerializer.representar(documento)
                for documento in documentos
            ]
        except ErrorSalidaInscripcion:
            return _respuesta_error(
                "ERROR_RESPUESTA",
                "No fue posible representar las inscripciones.",
                500
            )

        return JsonResponse({
            "page": page,
            "limit": limit,
            "total": total,
            "totalPaginas": (total + limit - 1) // limit,
            "datos": datos,
        })

    return _respuesta_error(
        "METODO_NO_PERMITIDO",
        "Este endpoint solamente acepta GET y POST.",
        405
    )


@csrf_exempt
@requiere_perfiles(*PERFILES_INSCRIPCIONES)
def api_inscripcion_estado(request, inscripcion_id: str):
    if request.method != "PATCH":
        return _respuesta_error(
            "METODO_NO_PERMITIDO",
            "Este endpoint solamente acepta PATCH.",
            405
        )

    try:
        estado = InscripcionSerializer.validar_cambio_estado(_leer_json(request))
        documento = cambiar_estado_inscripcion(
            inscripcion_id=inscripcion_id,
            nuevo_estado=estado,
            usuario=request.usuario,
            perfil=request.perfil,
            token=request.token_bearer,
        )
    except ErrorValidacionInscripcion as error:
        return _respuesta_error(
            error.codigo,
            error.mensaje,
            error.estado_http
        )
    except ErrorInscripciones as error:
        return _respuesta_error(error.codigo, error.mensaje, error.estado_http)
    except (PyMongoError, RuntimeError):
        return _respuesta_error(
            "ERROR_BASE_DATOS",
            "No fue posible actualizar la inscripción.",
            500
        )

    try:
        datos_salida = InscripcionSerializer.representar(documento)
    except ErrorSalidaInscripcion:
        return _respuesta_error(
            "ERROR_RESPUESTA",
            "No fue posible representar la inscripción actualizada.",
            500
        )
    return JsonResponse({"datos": datos_salida}, status=200)
