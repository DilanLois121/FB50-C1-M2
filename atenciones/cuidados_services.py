"""Reglas de negocio y persistencia para los cuidados veterinarios."""

# Responsable: Juan Álvarez.

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
