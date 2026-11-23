import json
from datetime import datetime, timezone as datetime_timezone
from pymongo.errors import PyMongoError
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from common.nucleo_client import (validar_sesion_nucleo, obtener_sedes, obtener_especies)
from .services import guardar_operativo, listar_operativos, actualizar_operativo, CuposReservadosError




def respuesta_error(codigo, mensaje, status):
    return JsonResponse(
        {
            "error": {
                "codigo": codigo,
                "mensaje": mensaje
            }
        },
        status=status
    )


@csrf_exempt
def crear_operativo_api(request):

    if request.method == "GET":
        return listar_operativos_api(request)

    if request.method != "POST":
        return respuesta_error(
            "METODO_NO_PERMITIDO",
            "Este endpoint solamente acepta POST.",
            405
        )

    authorization = request.headers.get("Authorization", "")

    esquema, separador, token = authorization.partition(" ")

    if esquema.lower() != "bearer" or not separador or not token.strip():
        return respuesta_error(
            "TOKEN_REQUERIDO",
            "Debe proporcionar un token de autenticación.",
            401
        )

    try:
        usuario = validar_sesion_nucleo(token.strip())

    except RuntimeError:
        return respuesta_error(
            "NUCLEO_NO_DISPONIBLE",
            "No fue posible validar la sesión.",
            503
        )

    except ValueError:
        return respuesta_error(
            "RESPUESTA_NUCLEO_INVALIDA",
            "No fue posible procesar la respuesta del núcleo.",
            502
        )

    if usuario is None:
        return respuesta_error(
            "TOKEN_INVALIDO",
            "El token no es válido o ha expirado.",
            401
        )

    perfil = str(usuario.get("perfil", "")).strip().lower()

    if perfil not in ["funcionario", "jefatura"]:
        return respuesta_error(
            "PERFIL_NO_AUTORIZADO",
            "No tiene permisos para crear operativos.",
            403
        )


    try:
        datos = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return respuesta_error(
            "JSON_INVALIDO",
            "El cuerpo de la petición debe contener JSON válido.",
            400
        )

    if not isinstance(datos, dict):
        return respuesta_error(
            "DATOS_INVALIDOS",
            "Se esperaba un objeto JSON.",
            400
        )

    tipo = datos.get("tipoOperativo")

    if tipo not in ["esterilizacion", "chipeo"]:
        return respuesta_error(
            "TIPO_INVALIDO",
            "El tipo de operativo no es válido.",
            400
        )

    fecha_texto = datos.get("fechaHora")

    if not isinstance(fecha_texto, str):
        return respuesta_error(
            "FECHA_INVALIDA",
            "Debe proporcionar una fecha y hora ISO 8601.",
            400
        )

    try:
        fecha = datetime.fromisoformat(
            fecha_texto.replace("Z", "+00:00")
        )

        if fecha.tzinfo is None or fecha.utcoffset() is None:
            raise ValueError("La fecha debe incluir zona horaria.")

        fecha = fecha.astimezone(datetime_timezone.utc)

    except ValueError:
        return respuesta_error(
            "FECHA_INVALIDA",
            "La fecha debe tener formato ISO 8601 e incluir zona horaria.",
            400
        )

    sede_id = datos.get("sedeId")
    cupos = datos.get("cuposPorEspecie")

    if not isinstance(sede_id, str) or not sede_id:
        return respuesta_error(
            "SEDE_INVALIDA",
            "Debe proporcionar un identificador de sede.",
            400
        )

    if not isinstance(cupos, list) or not cupos:
        return respuesta_error(
            "CUPOS_INVALIDOS",
            "Debe proporcionar los cupos por especie.",
            400
        )

    try:
        sedes = obtener_sedes()
        especies = obtener_especies()

    except (RuntimeError, ValueError):
        return respuesta_error(
            "NUCLEO_NO_DISPONIBLE",
            "No fue posible consultar los catálogos del núcleo.",
            503
        )

    if sede_id not in [sede["id"] for sede in sedes]:
        return respuesta_error(
            "SEDE_NO_EXISTE",
            "La sede seleccionada no existe.",
            400
        )

    especies_validas = {especie["id"] for especie in especies}
    cupos_guardar = []
    especies_recibidas = set()

    for cupo in cupos:

        if not isinstance(cupo, dict):
            return respuesta_error(
                "CUPOS_INVALIDOS",
                "Cada cupo debe contener un objeto válido.",
                400
            )

        especie_id = cupo.get("especieId")
        cantidad = cupo.get("total")

        if especie_id not in especies_validas:
            return respuesta_error(
                "ESPECIE_INVALIDA",
                "Una de las especies indicadas no existe.",
                400
            )

        if especie_id in especies_recibidas:
            return respuesta_error(
                "ESPECIE_DUPLICADA",
                "No puede repetir una especie en los cupos.",
                400
            )

        if isinstance(cantidad, bool) or not isinstance(cantidad, int) or cantidad < 0:
            return respuesta_error(
                "CANTIDAD_INVALIDA",
                "Los cupos deben ser números enteros mayores o iguales a cero.",
                400
            )

        especies_recibidas.add(especie_id)

        cupos_guardar.append({
            "especieId": especie_id,
            "total": cantidad,
            "disponibles": cantidad
        })

    datos_operativo = {
        "tipoOperativo": tipo,
        "fechaHora": fecha,
        "sedeId": sede_id,
        "cuposPorEspecie": cupos_guardar
    }

    try:
        operativo_id = guardar_operativo(datos_operativo)

    except (RuntimeError, PyMongoError):
        return respuesta_error(
            "ERROR_BASE_DATOS",
            "No fue posible guardar el operativo.",
            500
        )

    return JsonResponse(
        {
            "mensaje": "Operativo registrado correctamente.",
            "id": operativo_id
        },
        status=201
)


def listar_operativos_api(request):

    authorization = request.headers.get("Authorization", "")
    esquema, separador, token = authorization.partition(" ")

    if esquema.lower() != "bearer" or not separador or not token.strip():
        return respuesta_error(
            "TOKEN_REQUERIDO",
            "Debe proporcionar un token de autenticación.",
            401
        )

    try:
        usuario = validar_sesion_nucleo(token.strip())

    except RuntimeError:
        return respuesta_error(
            "NUCLEO_NO_DISPONIBLE",
            "No fue posible validar la sesión.",
            503
        )

    except ValueError:
        return respuesta_error(
            "RESPUESTA_NUCLEO_INVALIDA",
            "No fue posible procesar la respuesta del núcleo.",
            502
        )

    if usuario is None:
        return respuesta_error(
            "TOKEN_INVALIDO",
            "El token no es válido o ha expirado.",
            401
        )

    perfil = str(usuario.get("perfil", "")).strip().lower()

    perfiles_permitidos = [
        "vecino",
        "funcionario",
        "veterinario",
        "jefatura"
    ]

    if perfil not in perfiles_permitidos:
        return respuesta_error(
            "PERFIL_NO_AUTORIZADO",
            "No tiene permisos para consultar los operativos.",
            403
        )

    try:
        page = int(request.GET.get("page", "1"))
        limit = int(request.GET.get("limit", "20"))

    except (TypeError, ValueError):
        return respuesta_error(
            "PAGINACION_INVALIDA",
            "Los parámetros page y limit deben ser números enteros.",
            400
        )

    if page < 1 or limit < 1 or limit > 100:
        return respuesta_error(
            "PAGINACION_INVALIDA",
            "page debe ser mayor que cero y limit debe estar entre 1 y 100.",
            400
        )

    try:
        total, documentos = listar_operativos(page, limit)

    except (RuntimeError, PyMongoError):
        return respuesta_error(
            "ERROR_BASE_DATOS",
            "No fue posible consultar los operativos.",
            500
        )

    datos = []

    for documento in documentos:

        fecha = documento["fechaHora"]

        if fecha.tzinfo is None:
            fecha = fecha.replace(tzinfo=datetime_timezone.utc)
        else:
            fecha = fecha.astimezone(datetime_timezone.utc)

        datos.append({
            "id": str(documento["_id"]),
            "tipoOperativo": documento["tipoOperativo"],
            "fechaHora": fecha.isoformat().replace("+00:00", "Z"),
            "sedeId": documento["sedeId"],
            "cuposPorEspecie": documento["cuposPorEspecie"]
        })

    total_paginas = (total + limit - 1) // limit

    return JsonResponse({
        "page": page,
        "limit": limit,
        "total": total,
        "totalPaginas": total_paginas,
        "datos": datos
    }, status=200)


@csrf_exempt
def actualizar_operativo_api(request, id_operativo):

    if request.method != "PATCH":
        return respuesta_error(
            "METODO_NO_PERMITIDO",
            "Este endpoint solamente acepta PATCH.",
            405
        )

    authorization = request.headers.get("Authorization", "")
    esquema, separador, token = authorization.partition(" ")

    if esquema.lower() != "bearer" or not separador or not token.strip():
        return respuesta_error(
            "TOKEN_REQUERIDO",
            "Debe proporcionar un token de autenticación.",
            401
        )

    try:
        usuario = validar_sesion_nucleo(token.strip())

    except RuntimeError:
        return respuesta_error(
            "NUCLEO_NO_DISPONIBLE",
            "No fue posible validar la sesión.",
            503
        )

    except ValueError:
        return respuesta_error(
            "RESPUESTA_NUCLEO_INVALIDA",
            "No fue posible procesar la respuesta del núcleo.",
            502
        )

    if usuario is None:
        return respuesta_error(
            "TOKEN_INVALIDO",
            "El token no es válido o ha expirado.",
            401
        )

    perfil = str(usuario.get("perfil", "")).strip().lower()

    if perfil not in ["funcionario", "jefatura"]:
        return respuesta_error(
            "PERFIL_NO_AUTORIZADO",
            "No tiene permisos para actualizar operativos.",
            403
        )

    try:
        datos = json.loads(request.body)

    except (json.JSONDecodeError, UnicodeDecodeError):
        return respuesta_error(
            "JSON_INVALIDO",
            "El cuerpo de la petición debe contener JSON válido.",
            400
        )

    if not isinstance(datos, dict) or not datos:
        return respuesta_error(
            "DATOS_INVALIDOS",
            "Debe proporcionar un objeto JSON con campos para actualizar.",
            400
        )

    campos_permitidos = {
        "tipoOperativo",
        "fechaHora",
        "sedeId",
        "cuposPorEspecie"
    }

    if not set(datos).issubset(campos_permitidos):
        return respuesta_error(
            "CAMPOS_NO_PERMITIDOS",
            "La petición contiene campos no permitidos.",
            400
        )

    cambios = {}

    if "tipoOperativo" in datos:
        tipo = datos["tipoOperativo"]

        if tipo not in ["esterilizacion", "chipeo"]:
            return respuesta_error(
                "TIPO_INVALIDO",
                "El tipo de operativo no es válido.",
                400
            )

        cambios["tipoOperativo"] = tipo

    if "fechaHora" in datos:
        fecha_texto = datos["fechaHora"]

        if not isinstance(fecha_texto, str):
            return respuesta_error(
                "FECHA_INVALIDA",
                "La fecha debe ser un texto ISO 8601.",
                400
            )

        try:
            fecha = datetime.fromisoformat(
                fecha_texto.replace("Z", "+00:00")
            )

            if fecha.tzinfo is None or fecha.utcoffset() is None:
                raise ValueError()

            cambios["fechaHora"] = fecha.astimezone(datetime_timezone.utc)

        except ValueError:
            return respuesta_error(
                "FECHA_INVALIDA",
                "La fecha debe incluir zona horaria y formato ISO 8601.",
                400
            )

    if "sedeId" in datos or "cuposPorEspecie" in datos:
        try:
            sedes = obtener_sedes()
            especies = obtener_especies()

        except (RuntimeError, ValueError):
            return respuesta_error(
                "NUCLEO_NO_DISPONIBLE",
                "No fue posible consultar los catálogos del núcleo.",
                503
            )

        if "sedeId" in datos:
            sede_id = datos["sedeId"]

            if not isinstance(sede_id, str) or sede_id not in [
                sede["id"] for sede in sedes
            ]:
                return respuesta_error(
                    "SEDE_NO_EXISTE",
                    "La sede seleccionada no existe.",
                    400
                )

            cambios["sedeId"] = sede_id

        if "cuposPorEspecie" in datos:
            cupos = datos["cuposPorEspecie"]

            if not isinstance(cupos, list) or not cupos:
                return respuesta_error(
                    "CUPOS_INVALIDOS",
                    "Debe proporcionar una lista válida de cupos.",
                    400
                )

            especies_validas = {
                especie["id"] for especie in especies
            }

            especies_recibidas = set()
            cupos_guardar = []

            for cupo in cupos:

                if not isinstance(cupo, dict):
                    return respuesta_error(
                        "CUPOS_INVALIDOS",
                        "Cada cupo debe ser un objeto válido.",
                        400
                    )

                especie_id = cupo.get("especieId")
                cantidad = cupo.get("total")

                if especie_id not in especies_validas:
                    return respuesta_error(
                        "ESPECIE_INVALIDA",
                        "Una de las especies indicadas no existe.",
                        400
                    )

                if especie_id in especies_recibidas:
                    return respuesta_error(
                        "ESPECIE_DUPLICADA",
                        "No puede repetir una especie.",
                        400
                    )

                if (
                    isinstance(cantidad, bool)
                    or not isinstance(cantidad, int)
                    or cantidad < 0
                ):
                    return respuesta_error(
                        "CANTIDAD_INVALIDA",
                        "Los cupos deben ser enteros mayores o iguales a cero.",
                        400
                    )

                especies_recibidas.add(especie_id)

                cupos_guardar.append({
                    "especieId": especie_id,
                    "total": cantidad
                })

            cambios["cuposPorEspecie"] = cupos_guardar

    try:
        actualizado = actualizar_operativo(id_operativo, cambios)

    except CuposReservadosError:
        return respuesta_error(
            "CUPOS_RESERVADOS",
            "No se pueden reducir ni eliminar cupos que ya están reservados.",
            400
        )

    except ValueError:
        return respuesta_error(
            "ID_INVALIDO",
            "El identificador del operativo no es válido.",
            400
        )

    except (RuntimeError, PyMongoError):
        return respuesta_error(
            "ERROR_BASE_DATOS",
            "No fue posible actualizar el operativo.",
            500
        )

    if not actualizado:
        return respuesta_error(
            "OPERATIVO_NO_ENCONTRADO",
            "No existe un operativo con el identificador indicado.",
            404
        )

    return JsonResponse(
        {
            "mensaje": "Operativo actualizado correctamente.",
            "id": id_operativo
        },
        status=200
    )
