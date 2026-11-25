"""Reglas de negocio y persistencia MongoDB para las inscripciones."""

import os
from calendar import monthrange
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import requests
from bson import ObjectId
from bson.errors import InvalidId
from dotenv import load_dotenv
from pymongo import ReturnDocument
from pymongo.errors import PyMongoError

from common.mongo import db
from .models import Inscripcion


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


class ErrorInscripciones(Exception):
    """Error de negocio transportable como respuesta JSON."""

    def __init__(self, codigo: str, mensaje: str, estado_http: int):
        self.codigo = codigo
        self.mensaje = mensaje
        self.estado_http = estado_http
        super().__init__(mensaje)


def _coleccion(nombre: str):
    if db is None:
        raise RuntimeError("La conexión con MongoDB no está configurada.")
    return db[nombre]


def _id_operativo(valor: str) -> ObjectId:
    try:
        return ObjectId(valor)
    except (InvalidId, TypeError):
        raise ErrorInscripciones(
            "ID_OPERATIVO_INVALIDO",
            "El identificador del operativo no es válido.",
            400
        )


def _base_url(variable_nueva: str, variable_anterior: str | None = None) -> str:
    base_url = os.getenv(variable_nueva)
    if not base_url and variable_anterior:
        base_url = os.getenv(variable_anterior)
    if not isinstance(base_url, str) or not base_url.strip():
        raise ErrorInscripciones(
            "SERVICIO_NO_CONFIGURADO",
            f"No está configurada la variable {variable_nueva}.",
            503
        )
    return base_url.strip().rstrip("/")


def _consultar_json(url: str, token: str):
    try:
        respuesta = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=10
        )
    except requests.RequestException as error:
        raise ErrorInscripciones(
            "SERVICIO_EXTERNO_NO_DISPONIBLE",
            "No fue posible consultar un servicio externo.",
            503
        ) from error

    if respuesta.status_code == 404:
        return None
    if respuesta.status_code >= 500:
        raise ErrorInscripciones(
            "SERVICIO_EXTERNO_NO_DISPONIBLE",
            "Un servicio externo no está disponible.",
            503
        )
    if respuesta.status_code != 200:
        raise ErrorInscripciones(
            "RESPUESTA_EXTERNA_INVALIDA",
            "Un servicio externo rechazó la consulta.",
            502
        )

    try:
        datos = respuesta.json()
    except ValueError as error:
        raise ErrorInscripciones(
            "RESPUESTA_EXTERNA_INVALIDA",
            "Un servicio externo devolvió JSON inválido.",
            502
        ) from error

    if not isinstance(datos, dict):
        raise ErrorInscripciones(
            "RESPUESTA_EXTERNA_INVALIDA",
            "Un servicio externo devolvió un formato inesperado.",
            502
        )

    if isinstance(datos.get("datos"), dict):
        return datos["datos"]
    return datos


def _consultar_animal(animal_id: str, token: str) -> dict:
    base_url = _base_url("M1_BASE_URL")
    animal = _consultar_json(
        f"{base_url}/api/registro/animales/{quote(animal_id, safe='')}",
        token
    )
    if animal is None:
        raise ErrorInscripciones(
            "ANIMAL_NO_ENCONTRADO",
            "No existe un animal con el identificador indicado.",
            404
        )

    especie_id = animal.get("especieId")
    if not isinstance(especie_id, str) or not especie_id.strip():
        raise ErrorInscripciones(
            "RESPUESTA_ANIMAL_INCOMPLETA",
            "La respuesta del registro no contiene una especie válida.",
            502
        )
    animal["especieId"] = especie_id.strip()
    return animal


def _obtener_animal(animal_id: str, token: str) -> dict:
    animal = _consultar_animal(animal_id, token)
    estado = animal.get("estado")
    if not isinstance(estado, str) or not estado.strip():
        raise ErrorInscripciones(
            "RESPUESTA_ANIMAL_INCOMPLETA",
            "La respuesta del registro no contiene un estado válido.",
            502
        )
    estado = estado.strip()
    if estado not in {"registrado", "con_microchip"}:
        raise ErrorInscripciones(
            "ANIMAL_NO_ELEGIBLE",
            "El animal debe estar registrado o tener microchip, y no estar fallecido.",
            409
        )
    animal["estado"] = estado
    return animal


def _validar_prohibicion_tenencia(rut: str, token: str) -> None:
    base_url = _base_url("NUCLEO_BASE_URL", "NUCLEO_COMUN_URL")
    usuario = _consultar_json(
        f"{base_url}/api/nucleo/usuarios/{quote(rut, safe='')}",
        token
    )
    if usuario is None:
        raise ErrorInscripciones(
            "USUARIO_NO_ENCONTRADO",
            "El usuario solicitante no existe en el núcleo.",
            404
        )

    if "prohibicionTenencia" not in usuario:
        raise ErrorInscripciones(
            "RESPUESTA_USUARIO_INCOMPLETA",
            "La respuesta del núcleo no indica si existe prohibición de tenencia.",
            502
        )

    prohibicion = usuario["prohibicionTenencia"]
    if not isinstance(prohibicion, bool):
        raise ErrorInscripciones(
            "RESPUESTA_USUARIO_INCOMPLETA",
            "El campo prohibicionTenencia del núcleo debe ser booleano.",
            502
        )
    if prohibicion:
        raise ErrorInscripciones(
            "PROHIBICION_TENENCIA",
            "El solicitante tiene una prohibición vigente de tenencia.",
            403
        )


def _animal_esterilizado(animal_id: str) -> bool:
    atenciones = _coleccion("atenciones")
    registros = atenciones.find({
        "animalId": animal_id,
        "estado": "atendida",
    })
    operativos = _coleccion("operativos")

    for atencion in registros:
        tipo = (
            atencion.get("tipoOperativo")
            or atencion.get("tipoAtencion")
            or atencion.get("tipo")
        )
        if tipo == "esterilizacion":
            return True

        operativo_id = atencion.get("operativoId")
        if operativo_id is not None:
            try:
                object_id = ObjectId(str(operativo_id))
            except (InvalidId, TypeError):
                continue
            operativo = operativos.find_one({"_id": object_id}, {"tipoOperativo": 1})
            if operativo and operativo.get("tipoOperativo") == "esterilizacion":
                return True

    return False


def _cantidad_no_asistencias(rut: str) -> int:
    ahora = datetime.now(timezone.utc)
    mes = ahora.month - 6
    anio = ahora.year
    while mes <= 0:
        mes += 12
        anio -= 1
    desde = ahora.replace(
        year=anio,
        month=mes,
        day=min(ahora.day, monthrange(anio, mes)[1])
    )
    desde_iso = desde.isoformat().replace("+00:00", "Z")
    ahora_iso = ahora.isoformat().replace("+00:00", "Z")
    rangos_fecha = []

    for campo in ("fechaAtencion", "fechaHora"):
        rangos_fecha.extend([
            {campo: {"$gte": desde, "$lte": ahora}},
            {campo: {"$gte": desde_iso, "$lte": ahora_iso}},
        ])

    return _coleccion("atenciones").count_documents({
        "rutSolicitante": rut,
        "estado": {"$in": ["no asistió", "no_asistio", "no asistio"]},
        "$or": rangos_fecha,
    })


def crear_inscripcion(
    operativo_id: str,
    animal_id: str,
    rut_solicitante: str,
    perfil: str,
    token: str
) -> dict:
    object_id = _id_operativo(operativo_id)
    operativo = _coleccion("operativos").find_one({"_id": object_id})
    if operativo is None:
        raise ErrorInscripciones(
            "OPERATIVO_NO_ENCONTRADO",
            "No existe un operativo con el identificador indicado.",
            404
        )

    animal = _obtener_animal(animal_id, token)
    _validar_prohibicion_tenencia(rut_solicitante, token)

    if (
        operativo.get("tipoOperativo") == "esterilizacion"
        and _animal_esterilizado(animal_id)
    ):
        raise ErrorInscripciones(
            "ESTERILIZACION_PREVIA",
            "El animal ya tiene una esterilización atendida.",
            409
        )

    cupos = operativo.get("cuposPorEspecie")
    if not isinstance(cupos, list):
        cupos = []
    cupo = next(
        (
            elemento for elemento in cupos
            if (
                isinstance(elemento, dict)
                and elemento.get("especieId") == animal["especieId"]
            )
        ),
        None
    )
    if cupo is None:
        raise ErrorInscripciones(
            "CUPOS_AGOTADOS",
            "El operativo no tiene cupos disponibles para la especie del animal.",
            409
        )

    disponibles = cupo.get("disponibles")
    if isinstance(disponibles, bool) or not isinstance(disponibles, int):
        raise ErrorInscripciones(
            "CUPOS_INVALIDOS",
            "El operativo tiene una cantidad de cupos inválida.",
            500
        )
    if disponibles <= 0:
        raise ErrorInscripciones(
            "CUPOS_AGOTADOS",
            "El operativo no tiene cupos disponibles para la especie del animal.",
            409
        )

    inscripciones = _coleccion("inscripciones")
    activas = {"$in": ["solicitada", "confirmada"]}
    if inscripciones.find_one({
        "operativoId": operativo_id,
        "animalId": animal_id,
        "estado": activas,
    }):
        raise ErrorInscripciones(
            "INSCRIPCION_DUPLICADA",
            "El animal ya tiene una inscripción activa en este operativo.",
            409
        )

    if inscripciones.count_documents({
        "rutSolicitante": rut_solicitante,
        "estado": activas,
    }) >= 2:
        raise ErrorInscripciones(
            "LIMITE_INSCRIPCIONES",
            "El solicitante ya alcanzó el máximo de dos inscripciones activas.",
            409
        )

    if perfil != "funcionario" and _cantidad_no_asistencias(rut_solicitante) >= 2:
        raise ErrorInscripciones(
            "BLOQUEO_POR_INASISTENCIAS",
            "El solicitante registra dos inasistencias en los últimos seis meses.",
            409
        )

    documento = Inscripcion(
        operativoId=operativo_id,
        animalId=animal_id,
        rutSolicitante=rut_solicitante,
    ).a_documento()
    resultado = inscripciones.insert_one(documento)
    documento["_id"] = resultado.inserted_id
    return documento


def listar_inscripciones(
    page: int,
    limit: int,
    rut_solicitante: str | None = None,
    estado: str | None = None,
):
    consulta = {}
    if rut_solicitante is not None:
        consulta["rutSolicitante"] = rut_solicitante
    if estado is not None:
        consulta["estado"] = estado

    inscripciones = _coleccion("inscripciones")
    total = inscripciones.count_documents(consulta)
    documentos = list(
        inscripciones.find(consulta)
        .sort([("fechaCreacion", -1), ("_id", -1)])
        .skip((page - 1) * limit)
        .limit(limit)
    )
    return total, documentos


def _fecha_operativo(operativo: dict) -> datetime:
    fecha = operativo.get("fechaHora")
    if isinstance(fecha, str):
        try:
            fecha = datetime.fromisoformat(fecha.replace("Z", "+00:00"))
        except ValueError as error:
            raise ErrorInscripciones(
                "FECHA_OPERATIVO_INVALIDA",
                "El operativo tiene una fecha inválida.",
                500
            ) from error
    if not isinstance(fecha, datetime):
        raise ErrorInscripciones(
            "FECHA_OPERATIVO_INVALIDA",
            "El operativo no tiene una fecha válida.",
            500
        )
    if fecha.tzinfo is None:
        fecha = fecha.replace(tzinfo=timezone.utc)
    return fecha.astimezone(timezone.utc)


def _restituir_cupo(operativo_id: str, animal_id: str, token: str) -> None:
    animal = _consultar_animal(animal_id, token)
    resultado = _coleccion("operativos").update_one(
        {
            "_id": _id_operativo(operativo_id),
            "cuposPorEspecie.especieId": animal["especieId"],
        },
        {"$inc": {"cuposPorEspecie.$.disponibles": 1}}
    )
    if resultado.matched_count == 0:
        raise RuntimeError("No se encontró el cupo que debe ser restituido.")


def _restaurar_cupo_reservado(
    operativos,
    operativo_id: ObjectId,
    especie_id: str
) -> None:
    resultado = operativos.update_one(
        {
            "_id": operativo_id,
            "cuposPorEspecie.especieId": especie_id,
        },
        {"$inc": {"cuposPorEspecie.$.disponibles": 1}}
    )
    if resultado.matched_count == 0:
        raise RuntimeError(
            "No fue posible restaurar el cupo reservado del operativo."
        )


def cambiar_estado_inscripcion(
    inscripcion_id: str,
    nuevo_estado: str,
    usuario: dict,
    perfil: str,
    token: str
) -> dict:
    try:
        object_id = ObjectId(inscripcion_id)
    except (InvalidId, TypeError):
        raise ErrorInscripciones(
            "ID_INSCRIPCION_INVALIDO",
            "El identificador de la inscripción no es válido.",
            400
        )

    inscripciones = _coleccion("inscripciones")
    inscripcion = inscripciones.find_one({"_id": object_id})
    if inscripcion is None:
        raise ErrorInscripciones(
            "INSCRIPCION_NO_ENCONTRADA",
            "No existe una inscripción con el identificador indicado.",
            404
        )

    if perfil in {"vecino", "comunitario"}:
        if inscripcion.get("rutSolicitante") != usuario.get("rut"):
            raise ErrorInscripciones(
                "INSCRIPCION_AJENA",
                "Solo puede modificar sus propias inscripciones.",
                403
            )
        if nuevo_estado != "cancelada":
            raise ErrorInscripciones(
                "PERFIL_NO_AUTORIZADO",
                "Este perfil solo puede cancelar una inscripción.",
                403
            )

    if nuevo_estado == "confirmada":
        if perfil != "funcionario":
            raise ErrorInscripciones(
                "PERFIL_NO_AUTORIZADO",
                "Solo un funcionario puede confirmar inscripciones.",
                403
            )
        if inscripcion.get("estado") != "solicitada":
            raise ErrorInscripciones(
                "TRANSICION_INVALIDA",
                "Solo se pueden confirmar inscripciones solicitadas.",
                409
            )

        operativo_id = _id_operativo(inscripcion["operativoId"])
        animal = _obtener_animal(inscripcion["animalId"], token)
        operativos = _coleccion("operativos")
        reserva = operativos.update_one(
            {
                "_id": operativo_id,
                "cuposPorEspecie": {
                    "$elemMatch": {
                        "especieId": animal["especieId"],
                        "disponibles": {"$gt": 0},
                    }
                },
            },
            {"$inc": {"cuposPorEspecie.$.disponibles": -1}}
        )
        if reserva.matched_count == 0:
            raise ErrorInscripciones(
                "CUPOS_AGOTADOS",
                "No quedan cupos disponibles para confirmar esta inscripción.",
                409
            )

        try:
            cambio = inscripciones.update_one(
                {"_id": object_id, "estado": "solicitada"},
                {"$set": {"estado": "confirmada"}}
            )
        except PyMongoError:
            _restaurar_cupo_reservado(
                operativos,
                operativo_id,
                animal["especieId"]
            )
            raise

        if cambio.matched_count == 0:
            _restaurar_cupo_reservado(
                operativos,
                operativo_id,
                animal["especieId"]
            )
            raise ErrorInscripciones(
                "TRANSICION_INVALIDA",
                "La inscripción dejó de estar solicitada.",
                409
            )
        inscripcion["estado"] = "confirmada"
        return inscripcion

    if nuevo_estado != "cancelada":
        raise ErrorInscripciones(
            "ESTADO_INVALIDO",
            "El estado solicitado no es válido.",
            400
        )

    estado_actual = inscripcion.get("estado")
    if estado_actual not in {"solicitada", "confirmada"}:
        raise ErrorInscripciones(
            "TRANSICION_INVALIDA",
            "Solo se pueden cancelar inscripciones activas.",
            409
        )

    if perfil in {"vecino", "comunitario"}:
        operativo = _coleccion("operativos").find_one(
            {"_id": _id_operativo(inscripcion["operativoId"])}
        )
        if operativo is None:
            raise ErrorInscripciones(
                "OPERATIVO_NO_ENCONTRADO",
                "No existe el operativo asociado a la inscripción.",
                404
            )
        if _fecha_operativo(operativo) - datetime.now(timezone.utc) < timedelta(hours=24):
            raise ErrorInscripciones(
                "PLAZO_CANCELACION_VENCIDO",
                "La cancelación requiere al menos 24 horas de anticipación.",
                409
            )

    filtro = {"_id": object_id, "estado": estado_actual}
    if perfil in {"vecino", "comunitario"}:
        filtro["rutSolicitante"] = usuario.get("rut")
    cancelada = inscripciones.find_one_and_update(
        filtro,
        {"$set": {"estado": "cancelada"}},
        return_document=ReturnDocument.BEFORE
    )
    if cancelada is None:
        raise ErrorInscripciones(
            "TRANSICION_INVALIDA",
            "La inscripción cambió mientras se procesaba la cancelación.",
            409
        )

    if estado_actual == "confirmada":
        try:
            _restituir_cupo(
                cancelada["operativoId"],
                cancelada["animalId"],
                token
            )
        except (ErrorInscripciones, PyMongoError, RuntimeError):
            restauracion = inscripciones.update_one(
                {"_id": object_id, "estado": "cancelada"},
                {"$set": {"estado": "confirmada"}}
            )
            if restauracion.matched_count == 0:
                raise RuntimeError(
                    "No fue posible revertir la cancelación tras fallar "
                    "la restitución del cupo."
                )
            raise

    cancelada["estado"] = "cancelada"
    return cancelada
