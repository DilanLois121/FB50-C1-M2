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
