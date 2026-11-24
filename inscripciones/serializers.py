"""Validación y representación de los datos de la API de inscripciones."""


class ErrorValidacionInscripcion(Exception):
    """Error de entrada con código y mensaje aptos para la respuesta API."""

    def __init__(self, codigo: str, mensaje: str):
        self.codigo = codigo
        self.mensaje = mensaje
        super().__init__(mensaje)


class InscripcionSerializer:
    """Valida estrictamente los campos que el cliente puede enviar."""

    CAMPOS_CREACION = {"operativoId", "animalId"}
    ESTADOS_EDITABLES = {"confirmada", "cancelada"}

    @classmethod
    def validar_creacion(cls, datos: object) -> dict[str, str]:
        if not isinstance(datos, dict):
            raise ErrorValidacionInscripcion(
                "DATOS_INVALIDOS",
                "El cuerpo debe ser un objeto JSON."
            )

        if set(datos) != cls.CAMPOS_CREACION:
            raise ErrorValidacionInscripcion(
                "CAMPOS_INVALIDOS",
                "Se requieren únicamente operativoId y animalId."
            )

        resultado = {}
        for campo in cls.CAMPOS_CREACION:
            valor = datos[campo]
            if (
                not isinstance(valor, str)
                or not valor.strip()
                or len(valor.strip()) > 128
            ):
                raise ErrorValidacionInscripcion(
                    "CAMPO_INVALIDO",
                    f"{campo} debe ser un texto no vacío de hasta 128 caracteres."
                )
            resultado[campo] = valor.strip()

        return resultado

    @classmethod
    def validar_cambio_estado(cls, datos: object) -> str:
        if not isinstance(datos, dict) or set(datos) != {"estado"}:
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

    @staticmethod
    def representar(documento: dict) -> dict[str, str]:
        """Expone solo los campos del recurso y su identificador público."""
        fecha = documento.get("fechaCreacion")
        if hasattr(fecha, "isoformat"):
            fecha = fecha.isoformat()
            if fecha.endswith("+00:00"):
                fecha = fecha[:-6] + "Z"

        return {
            "id": str(documento["_id"]),
            "operativoId": documento["operativoId"],
            "animalId": documento["animalId"],
            "rutSolicitante": documento["rutSolicitante"],
            "estado": documento["estado"],
            "fechaCreacion": fecha,
        }
