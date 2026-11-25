"""Reglas de negocio y persistencia para los cuidados veterinarios."""

# Juan Alvarez

from datetime import datetime, timezone

from common.mongo import db

from .services import ErrorAtenciones, _validar_id


def registrar_cuidado(inscripcion_id, usuario, datos):
    """Registra los cuidados de una inscripción que ya fue atendida."""
    if db is None:
        raise RuntimeError("La conexión con MongoDB no está configurada.")

    inscripcion_object_id = _validar_id(
        inscripcion_id,
        "inscripcion"
    )
    inscripcion = db["inscripciones"].find_one(
        {"_id": inscripcion_object_id}
    )

    if inscripcion is None:
        raise ErrorAtenciones(
            "INSCRIPCION_NO_ENCONTRADA",
            "No existe la inscripción indicada.",
            404
        )

    if inscripcion.get("estado") != "atendida":
        raise ErrorAtenciones(
            "INSCRIPCION_NO_ATENDIDA",
            "Solo se pueden registrar cuidados para una inscripción atendida.",
            400
        )

    documento = {
        "inscripcion_id": inscripcion_object_id,
        "veterinario_rut": usuario["rut"],
        "indicaciones": datos.get("indicaciones"),
        "medicamentos": datos.get("medicamentos"),
        "detalle_quirurgico": datos.get("detalle_quirurgico"),
        "fecha_registro": (
            datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        ),
        "notas_complementarias": [],
    }

    resultado = db["cuidados"].insert_one(documento)
    documento["_id"] = resultado.inserted_id
    return documento


def agregar_nota_complementaria(cuidado_id, usuario, texto_nota):
    """Agrega una nota sin modificar los datos originales del cuidado."""
    if db is None:
        raise RuntimeError("La conexión con MongoDB no está configurada.")

    cuidado_object_id = _validar_id(cuidado_id, "cuidado")
    cuidados = db["cuidados"]

    if cuidados.find_one({"_id": cuidado_object_id}, {"_id": 1}) is None:
        raise ErrorAtenciones(
            "CUIDADO_NO_ENCONTRADO",
            "No existe el cuidado indicado.",
            404
        )

    if not isinstance(texto_nota, str) or not texto_nota.strip():
        raise ErrorAtenciones(
            "NOTA_VACIA",
            "La nota complementaria no puede estar vacía.",
            400
        )

    nueva_nota = {
        "nota": texto_nota,
        "autor_rut": usuario["rut"],
        "fecha": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    }

    cuidados.update_one(
        {"_id": cuidado_object_id},
        {"$push": {"notas_complementarias": nueva_nota}}
    )
    return nueva_nota


def obtener_cuidado_por_inscripcion(inscripcion_id, perfil_solicitante):
    """Obtiene el cuidado asociado, ocultando detalles según el perfil."""
    if db is None:
        raise RuntimeError("La conexión con MongoDB no está configurada.")

    inscripcion_object_id = _validar_id(inscripcion_id, "inscripcion")
    cuidado = db["cuidados"].find_one({
        "inscripcion_id": inscripcion_object_id
    })

    if cuidado is None:
        raise ErrorAtenciones(
            "CUIDADO_NO_ENCONTRADO",
            "No existe un cuidado para la inscripción indicada.",
            404
        )

    cuidado_formateado = dict(cuidado)
    cuidado_formateado["_id"] = str(cuidado_formateado["_id"])
    cuidado_formateado["inscripcion_id"] = str(
        cuidado_formateado["inscripcion_id"]
    )

    if perfil_solicitante == "funcionario":
        cuidado_formateado.pop("detalle_quirurgico", None)

    return cuidado_formateado
