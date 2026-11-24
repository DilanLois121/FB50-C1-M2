"""Reglas de negocio y persistencia para las atenciones veterinarias."""

import re
from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from pymongo.errors import PyMongoError

from common.mongo import db


class ErrorAtenciones(Exception):
    """Error de negocio de las atenciones."""

    def __init__(self, codigo: str, mensaje: str, estado_http: int):
        self.codigo = codigo
        self.mensaje = mensaje
        self.estado_http = estado_http
        super().__init__(mensaje)


def _coleccion(nombre: str):
    if db is None:
        raise RuntimeError("La conexión con MongoDB no está configurada.")

    return db[nombre]


def _validar_id(valor: str, nombre: str = "ID"):
    try:
        return ObjectId(valor)
    except (InvalidId, TypeError):
        raise ErrorAtenciones(
            f"{nombre.upper()}_INVALIDO",
            f"El identificador de {nombre} no es válido.",
            400
        )


def _validar_microchip(microchip: str):
    if not isinstance(microchip, str) or not re.fullmatch(
        r"\d{15}", microchip
    ):
        raise ErrorAtenciones(
            "MICROCHIP_INVALIDO",
            "El microchip debe contener exactamente 15 dígitos.",
            400
        )


def _microchip_existe(microchip: str) -> bool:
    return _coleccion("atenciones").find_one(
        {"microchip": microchip},
        {"_id": 1}
    ) is not None


def registrar_atencion(
    inscripcion_id: str,
    usuario: dict,
    perfil: str,
    microchip: str | None = None
) -> dict:
    """Registra la atención de una inscripción confirmada."""

    if perfil != "veterinario":
        raise ErrorAtenciones(
            "PERFIL_NO_AUTORIZADO",
            "Solo un veterinario puede registrar una atención.",
            403
        )

    inscripcion_object_id = _validar_id(
        inscripcion_id, "inscripcion"
    )

    inscripciones = _coleccion("inscripciones")
    operativos = _coleccion("operativos")
    atenciones = _coleccion("atenciones")

    inscripcion = inscripciones.find_one({
        "_id": inscripcion_object_id
    })

    if inscripcion is None:
        raise ErrorAtenciones(
            "INSCRIPCION_NO_ENCONTRADA",
            "No existe la inscripción indicada.",
            404
        )

    if inscripcion.get("estado") != "confirmada":
        raise ErrorAtenciones(
            "TRANSICION_INVALIDA",
            "Solo se pueden atender inscripciones confirmadas.",
            409
        )

    operativo_id = _validar_id(
        inscripcion.get("operativoId", ""),
        "operativo"
    )

    operativo = operativos.find_one({
        "_id": operativo_id
    })

    if operativo is None:
        raise ErrorAtenciones(
            "OPERATIVO_NO_ENCONTRADO",
            "No existe el operativo asociado a la inscripción.",
            404
        )

    tipo_operativo = operativo.get("tipoOperativo")

    if tipo_operativo not in {"esterilizacion", "chipeo"}:
        raise ErrorAtenciones(
            "TIPO_OPERATIVO_INVALIDO",
            "El operativo no corresponde a esterilización ni chipeo.",
            409
        )

    if tipo_operativo == "chipeo":
        _validar_microchip(microchip)

        if _microchip_existe(microchip):
            raise ErrorAtenciones(
                "MICROCHIP_DUPLICADO",
                "El microchip ya se encuentra registrado.",
                409
            )

    cambio_estado = inscripciones.update_one(
        {
            "_id": inscripcion_object_id,
            "estado": "confirmada"
        },
        {
            "$set": {
                "estado": "atendida"
            }
        }
    )

    if cambio_estado.matched_count == 0:
        raise ErrorAtenciones(
            "TRANSICION_INVALIDA",
            "La inscripción ya fue modificada.",
            409
        )

    documento_atencion = {
        "inscripcionId": str(inscripcion_object_id),
        "operativoId": inscripcion["operativoId"],
        "animalId": inscripcion["animalId"],
        "rutSolicitante": inscripcion.get("rutSolicitante"),
        "tipoOperativo": tipo_operativo,
        "estado": "atendida",
        "fechaAtencion": datetime.now(timezone.utc),
        "veterinarioRut": usuario.get("rut"),
    }

    if tipo_operativo == "chipeo":
        documento_atencion["microchip"] = microchip

    try:
        resultado = atenciones.insert_one(
            documento_atencion
        )

        documento_atencion["_id"] = resultado.inserted_id

    except PyMongoError as error:
        inscripciones.update_one(
            {
                "_id": inscripcion_object_id,
                "estado": "atendida"
            },
            {
                "$set": {
                    "estado": "confirmada"
                }
            }
        )

        raise ErrorAtenciones(
            "ERROR_REGISTRO_ATENCION",
            "No fue posible guardar la atención.",
            500
        ) from error

    return documento_atencion


def cerrar_operativo(operativo_id: str, usuario: dict, perfil: str) -> dict:
    """Cierra un operativo y registra las inscripciones no atendidas."""

    if perfil != "veterinario":
        raise ErrorAtenciones(
            "PERFIL_NO_AUTORIZADO",
            "Solo un veterinario puede cerrar un operativo.",
            403
        )

    object_id = _validar_id(operativo_id, "operativo")

    operativos = _coleccion("operativos")
    inscripciones = _coleccion("inscripciones")
    atenciones = _coleccion("atenciones")

    operativo = operativos.find_one({"_id": object_id})

    if operativo is None:
        raise ErrorAtenciones(
            "OPERATIVO_NO_ENCONTRADO",
            "No existe el operativo indicado.",
            404
        )

    if operativo.get("cerrado", False):
        raise ErrorAtenciones(
            "OPERATIVO_CERRADO",
            "El operativo ya se encuentra cerrado.",
            409
        )

    if operativo.get("cierreEnProceso", False):
        raise ErrorAtenciones(
            "CIERRE_EN_PROCESO",
            "El operativo ya está siendo cerrado.",
            409
        )

    fecha_operativo = operativo.get("fechaHora")

    if not isinstance(fecha_operativo, datetime):
        raise ErrorAtenciones(
            "FECHA_OPERATIVO_INVALIDA",
            "El operativo no tiene una fecha válida.",
            500
        )

    if fecha_operativo.tzinfo is None:
        fecha_operativo = fecha_operativo.replace(tzinfo=timezone.utc)

    if fecha_operativo > datetime.now(timezone.utc):
        raise ErrorAtenciones(
            "OPERATIVO_FUTURO",
            "No se puede cerrar un operativo que aún no ha comenzado.",
            409
        )

    bloqueo = operativos.update_one(
        {
            "_id": object_id,
            "cerrado": {"$ne": True},
            "cierreEnProceso": {"$ne": True}
        },
        {
            "$set": {
                "cierreEnProceso": True
            }
        }
    )

    if bloqueo.modified_count == 0:
        raise ErrorAtenciones(
            "CIERRE_NO_DISPONIBLE",
            "No fue posible iniciar el cierre del operativo.",
            409
        )

    cambios_realizados = []
    documentos_insertados = []

    try:
        pendientes = list(inscripciones.find({
            "operativoId": operativo_id,
            "estado": "confirmada"
        }))

        for inscripcion in pendientes:

            inscripcion_id = str(inscripcion["_id"])

            # Evita duplicar una inasistencia para una inscripción.
            existe = atenciones.find_one({
                "inscripcionId": inscripcion_id,
                "estado": "no asistió"
            })

            if existe:
                continue

            cambio = inscripciones.update_one(
                {
                    "_id": inscripcion["_id"],
                    "estado": "confirmada"
                },
                {
                    "$set": {
                        "estado": "no asistió"
                    }
                }
            )

            if cambio.modified_count == 0:
                continue

            cambios_realizados.append(inscripcion["_id"])

            documento = {
                "inscripcionId": inscripcion_id,
                "operativoId": operativo_id,
                "animalId": inscripcion["animalId"],
                "rutSolicitante": inscripcion.get("rutSolicitante"),
                "tipoOperativo": operativo.get("tipoOperativo"),
                "estado": "no asistió",
                "fechaAtencion": datetime.now(timezone.utc),
                "veterinarioRut": usuario.get("rut")
            }

            resultado = atenciones.insert_one(documento)
            documentos_insertados.append(resultado.inserted_id)

        resultado_cierre = operativos.update_one(
            {
                "_id": object_id,
                "cierreEnProceso": True,
                "cerrado": {"$ne": True}
            },
            {
                "$set": {
                    "cerrado": True,
                    "fechaCierre": datetime.now(timezone.utc),
                    "veterinarioCierre": usuario.get("rut")
                },
                "$unset": {
                    "cierreEnProceso": ""
                }
            }
        )

        if resultado_cierre.modified_count == 0:
            raise RuntimeError("No fue posible finalizar el cierre.")

        return {
            "operativoId": operativo_id,
            "inasistenciasRegistradas": len(documentos_insertados),
            "cerrado": True
        }

    except Exception as error:

        # Intentar revertir los registros creados.
        if documentos_insertados:
            atenciones.delete_many({
                "_id": {"$in": documentos_insertados}
            })

        # Restaurar las inscripciones que fueron modificadas.
        if cambios_realizados:
            inscripciones.update_many(
                {
                    "_id": {"$in": cambios_realizados},
                    "estado": "no asistió"
                },
                {
                    "$set": {
                        "estado": "confirmada"
                    }
                }
            )

        operativos.update_one(
            {"_id": object_id},
            {
                "$unset": {
                    "cierreEnProceso": ""
                }
            }
        )

        if isinstance(error, ErrorAtenciones):
            raise

        raise ErrorAtenciones(
            "ERROR_CIERRE_OPERATIVO",
            "No fue posible completar el cierre del operativo.",
            500
        ) from error
