from typing import Any
from common.mongo import db
from bson import ObjectId
from bson.errors import InvalidId

class CuposReservadosError(Exception):
    pass

def guardar_operativo(datos: dict[str, Any]) -> str:

    if db is None:
        raise RuntimeError("La conexion con MongoDB no esta configurada.")

    resultado = db["operativos"].insert_one(datos)
    return str(resultado.inserted_id)


def listar_operativos(page=1, limit=20):

    if db is None:
        raise RuntimeError("La conexión con MongoDB no está configurada.")

    coleccion = db["operativos"]

    total = coleccion.count_documents({})

    saltar = (page - 1) * limit

    documentos = list(
        coleccion.find()
        .sort("fechaHora", 1)
        .skip(saltar)
        .limit(limit)
    )

    return total, documentos



def actualizar_operativo(id_operativo, datos):

    if db is None:
        raise RuntimeError(
            "La conexión con MongoDB no está configurada."
        )

    try:
        object_id = ObjectId(id_operativo)

    except (InvalidId, TypeError):
        raise ValueError("Identificador inválido.")

    coleccion = db["operativos"]

    operativo = coleccion.find_one({"_id": object_id})

    if operativo is None:
        return False

    cambios = dict(datos)

    if "cuposPorEspecie" in cambios:

        cupos_actuales = {
            c["especieId"]: c
            for c in operativo.get("cuposPorEspecie", [])
        }

        cupos_nuevos = cambios["cuposPorEspecie"]
        especies_recibidas = set()
        cupos_actualizados = []

        for cupo in cupos_nuevos:

            especie_id = cupo["especieId"]
            total_nuevo = cupo["total"]

            anterior = cupos_actuales.get(especie_id)

            reservados = 0

            if anterior:
                reservados = (
                    anterior["total"] - anterior["disponibles"]
                )

            if total_nuevo < reservados:
                raise CuposReservadosError(
                    "Los nuevos cupos no pueden ser menores "
                    "que la cantidad de cupos reservados."
                )

            especies_recibidas.add(especie_id)

            cupos_actualizados.append({
                "especieId": especie_id,
                "total": total_nuevo,
                "disponibles": total_nuevo - reservados
            })

        for especie_id, anterior in cupos_actuales.items():

            reservados = (
                anterior["total"] - anterior["disponibles"]
            )

            if reservados > 0 and especie_id not in especies_recibidas:
                raise CuposReservadosError(
                    "No se puede eliminar una especie que tenga "
                    "cupos reservados."
                )

        cambios["cuposPorEspecie"] = cupos_actualizados

    resultado = coleccion.update_one(
        {"_id": object_id},
        {"$set": cambios}
    )

    return resultado.matched_count > 0
