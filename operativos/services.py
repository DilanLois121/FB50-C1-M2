from typing import Any
from common.mongo import db

def guardar_operativo(datos: dict[str, Any]) -> str:

    if db is None:
        raise RuntimeError("La conexion con MongoDB no esta configurada.")

    resultado = db["operativos"].insert_one(datos)
    return str(resultado.inserted_id)


def listar_operativos(page=1, limit=20):

    if db is None:
        raise RuntimeError("La conexión con MongoDB no está configurada.")

    # Obtener la colección de operativos
    coleccion = db["operativos"]

    # Calcular la cantidad total de documentos
    total = coleccion.count_documents({})

    # Calcular cuántos documentos debemos saltar
    saltar = (page - 1) * limit

    # Consultar los operativos con paginación
    documentos = list(
        coleccion.find()
        .sort("fechaHora", 1)
        .skip(saltar)
        .limit(limit)
    )

    return total, documentos
