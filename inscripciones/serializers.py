"""Validación estricta de entradas y salidas de la API de inscripciones."""

from collections.abc import Mapping
from datetime import datetime, timezone


class ErrorValidacionInscripcion(Exception):
    """Error de validación con código y estado HTTP para la respuesta API."""

    def __init__(self, codigo: str, mensaje: str, estado_http: int = 400):
        self.codigo = codigo
        self.mensaje = mensaje
        self.estado_http = estado_http
        super().__init__(mensaje)


class ErrorSalidaInscripcion(Exception):
    """Indica que un documento interno no cumple el contrato de salida."""


class InscripcionSerializer:
    """Evita entradas ambiguas y limita la salida a campos autorizados."""

    CAMPOS_CREACION = {"operativoId", "animalId"}
    ESTADOS_EDITABLES = {"confirmada", "cancelada"}
    ESTADOS_SALIDA = {"solicitada", "confirmada", "cancelada"}
    CAMPOS_SALIDA = {
        "operativoId",
        "animalId",
        "rutSolicitante",
        "estado",
        "fechaCreacion",
    }

    @staticmethod
    def _validar_texto(valor: object, campo: str) -> str:
        if not isinstance(valor, str):
            raise ErrorValidacionInscripcion(
                "CAMPO_INVALIDO",
                f"{campo} debe ser texto."
            )

        texto = valor.strip()
        if not texto or len(texto) > 128:
            raise ErrorValidacionInscripcion(
                "CAMPO_INVALIDO",
                f"{campo} debe contener entre 1 y 128 caracteres."
            )
        return texto

    @classmethod
    def validar_creacion(cls, datos: object) -> dict[str, str]:
        if not isinstance(datos, Mapping):
            raise ErrorValidacionInscripcion(
                "DATOS_INVALIDOS",
                "El cuerpo debe ser un objeto JSON."
            )

        if set(datos) != cls.CAMPOS_CREACION:
            raise ErrorValidacionInscripcion(
                "CAMPOS_INVALIDOS",
                "Se requieren únicamente operativoId y animalId."
            )

        return {
            campo: cls._validar_texto(datos[campo], campo)
            for campo in cls.CAMPOS_CREACION
        }

    @classmethod
    def validar_cambio_estado(cls, datos: object) -> str:
        if not isinstance(datos, Mapping) or set(datos) != {"estado"}:
            raise ErrorValidacionInscripcion(
                "CAMPOS_INVALIDOS",
                "Se requiere únicamente el campo estado."
            )

        estado = datos["estado"]
        if not isinstance(estado, str) or estado not in cls.ESTADOS_EDITABLES:
            raise ErrorValidacionInscripcion(
                "ESTADO_INVALIDO",
                "El estado debe ser confirmada o cancelada."
            )

        return estado

    @classmethod
    def representar(cls, documento: object) -> dict[str, str]:
        """Serializa solo datos permitidos y normaliza la fecha a UTC."""
        if not isinstance(documento, Mapping):
            raise ErrorSalidaInscripcion(
                "El documento de inscripción debe ser un objeto."
            )

        if not cls.CAMPOS_SALIDA.issubset(documento):
            raise ErrorSalidaInscripcion(
                "El documento de inscripción no contiene todos los campos."
            )

        campos = {}
        for campo in ("operativoId", "animalId", "rutSolicitante"):
            valor = documento[campo]
            if not isinstance(valor, str) or not valor.strip():
                raise ErrorSalidaInscripcion(
                    f"El campo {campo} del documento no es válido."
                )
            campos[campo] = valor

        estado = documento["estado"]
        if not isinstance(estado, str) or estado not in cls.ESTADOS_SALIDA:
            raise ErrorSalidaInscripcion(
                "El estado del documento de inscripción no es válido."
            )

        identificador = documento.get("_id")
        if identificador is None or not str(identificador).strip():
            raise ErrorSalidaInscripcion(
                "El documento de inscripción no contiene un identificador."
            )

        fecha = documento["fechaCreacion"]
        if isinstance(fecha, datetime):
            fecha_utc = (
                fecha.replace(tzinfo=timezone.utc)
                if fecha.tzinfo is None
                else fecha.astimezone(timezone.utc)
            )
        elif isinstance(fecha, str):
            try:
                fecha_parseada = datetime.fromisoformat(
                    fecha.replace("Z", "+00:00")
                )
            except ValueError as error:
                raise ErrorSalidaInscripcion(
                    "La fecha de creación del documento no es ISO 8601."
                ) from error

            if fecha_parseada.tzinfo is None:
                raise ErrorSalidaInscripcion(
                    "La fecha de creación debe incluir zona horaria."
                )
            fecha_utc = fecha_parseada.astimezone(timezone.utc)
        else:
            raise ErrorSalidaInscripcion(
                "La fecha de creación del documento no es válida."
            )

        return {
            "id": str(identificador),
            **campos,
            "estado": estado,
            "fechaCreacion": fecha_utc.isoformat().replace("+00:00", "Z"),
        }
