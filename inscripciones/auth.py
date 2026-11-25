"""Autenticación Bearer y autorización por perfil para la API."""

from functools import wraps

from django.http import JsonResponse

from common.nucleo_client import validar_sesion_nucleo


def _respuesta_error(codigo: str, mensaje: str, estado: int) -> JsonResponse:
    return JsonResponse(
        {"error": {"codigo": codigo, "mensaje": mensaje}},
        status=estado
    )


def requiere_perfiles(*perfiles_permitidos: str):
    """Valida la sesión con Núcleo y limita el acceso a perfiles explícitos."""

    def decorar(vista):
        @wraps(vista)
        def envolver(request, *args, **kwargs):
            authorization = request.headers.get("Authorization", "")
            partes = authorization.split()
            if (
                len(partes) != 2
                or partes[0].lower() != "bearer"
                or not partes[1]
            ):
                return _respuesta_error(
                    "TOKEN_REQUERIDO",
                    "Debe proporcionar un token Bearer válido.",
                    401
                )

            try:
                usuario = validar_sesion_nucleo(partes[1])
            except RuntimeError:
                return _respuesta_error(
                    "NUCLEO_NO_DISPONIBLE",
                    "No fue posible validar la sesión.",
                    503
                )
            except ValueError:
                return _respuesta_error(
                    "RESPUESTA_NUCLEO_INVALIDA",
                    "No fue posible procesar la respuesta del núcleo.",
                    502
                )

            if usuario is None:
                return _respuesta_error(
                    "TOKEN_INVALIDO",
                    "El token no es válido o ha expirado.",
                    401
                )

            if (
                not isinstance(usuario, dict)
                or not isinstance(usuario.get("rut"), str)
                or not usuario["rut"].strip()
                or not isinstance(usuario.get("perfil"), str)
                or not usuario["perfil"].strip()
            ):
                return _respuesta_error(
                    "RESPUESTA_NUCLEO_INVALIDA",
                    "La respuesta del núcleo no contiene un usuario y perfil válidos.",
                    502
                )

            perfil = usuario["perfil"].strip().lower()
            if perfil not in perfiles_permitidos:
                return _respuesta_error(
                    "PERFIL_NO_AUTORIZADO",
                    "Su perfil no tiene permisos para este recurso.",
                    403
                )

            request.usuario = {**usuario, "rut": usuario["rut"].strip()}
            request.perfil = perfil
            request.token_bearer = partes[1]
            return vista(request, *args, **kwargs)

        return envolver

    return decorar
