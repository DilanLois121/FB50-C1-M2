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
