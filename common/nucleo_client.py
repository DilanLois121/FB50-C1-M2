import os
from pathlib import Path
import requests
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
NUCLEO_COMUN_URL = os.getenv("NUCLEO_COMUN_URL")


def obtener_sedes(page=1, limit=20):

    if not NUCLEO_COMUN_URL:
        raise RuntimeError(
            "No se configuro NUCLEO_COMUN_URL en el archivo .env"
        )

    url = f"{NUCLEO_COMUN_URL.rstrip('/')}/api/nucleo/catalogos/sedes"

    try:
        respuesta = requests.get(
            url,
            params={"page": page, "limit": limit},
            timeout=10
        )

        respuesta.raise_for_status()
        datos_respuesta = respuesta.json()

    except requests.RequestException as error:
        raise RuntimeError(
            f"No fue posible consultar las sedes: {error}"
        ) from error

    except ValueError as error:
        raise RuntimeError(
            "El nucleo devolvio una respuesta que no es JSON valido."
        ) from error

    if not isinstance(datos_respuesta, dict):
        raise ValueError("La respuesta del nucleo no tiene el formato esperado.")

    sedes = datos_respuesta.get("datos")

    if not isinstance(sedes, list):
        raise ValueError("La respuesta no contiene una lista valida de sedes.")

    return sedes

def obtener_especies(page=1, limit=20):
    if not NUCLEO_COMUN_URL:
        raise RuntimeError("No se configuró NUCLEO_COMUN_URL en el archivo .env")

    url = f"{NUCLEO_COMUN_URL.rstrip('/')}/api/nucleo/catalogos/especies"

    try:
        respuesta = requests.get(
            url,
            params={"page": page, "limit": limit},
            timeout=10
        )
        respuesta.raise_for_status()
        datos_respuesta = respuesta.json()

    except requests.RequestException as error:
        raise RuntimeError(
            f"No fue posible consultar las especies: {error}"
        ) from error

    except ValueError as error:
        raise RuntimeError(
            "El núcleo devolvió una respuesta que no es JSON válido."
        ) from error

    if not isinstance(datos_respuesta, dict):
        raise ValueError("La respuesta del núcleo no tiene el formato esperado.")

    especies = datos_respuesta.get("datos")

    if not isinstance(especies, list):
        raise ValueError("La respuesta no contiene una lista válida de especies.")

    return especies