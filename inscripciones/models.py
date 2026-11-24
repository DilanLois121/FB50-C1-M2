"""Contrato del documento de inscripción almacenado en MongoDB."""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone


def _fecha_utc_iso() -> str:
    """Devuelve la fecha actual como ISO 8601 UTC, terminada en Z."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class Inscripcion:
    """Representa únicamente los campos autorizados de una inscripción."""

    operativoId: str
    animalId: str
    rutSolicitante: str
    estado: str = "solicitada"
    fechaCreacion: str = field(default_factory=_fecha_utc_iso)

    def a_documento(self) -> dict[str, str]:
        """Genera el documento Mongo sin añadir datos personales extra."""
        return asdict(self)
