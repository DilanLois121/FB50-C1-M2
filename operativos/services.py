from typing import Any
from common.mongo import db

def guardar_operativo(datos: dict[str, Any]) -> str:

    if db is None:
        raise RuntimeError("La conexion con MongoDB no esta configurada.")

    resultado = db["operativos"].insert_one(datos)
    return str(resultado.inserted_id)
