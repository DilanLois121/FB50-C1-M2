import json
from datetime import datetime
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from .models import Inscripcion
from .serializers import ErrorValidacionInscripcion, InscripcionSerializer
from .services import (
    ErrorInscripciones,
    _obtener_animal,
    _validar_prohibicion_tenencia,
)
from .views import api_inscripciones


class InscripcionSerializerTests(SimpleTestCase):
    def test_creacion_solo_admite_ids_de_texto(self):
        datos = InscripcionSerializer.validar_creacion({
            "operativoId": "65a000000000000000000001",
            "animalId": "animal-1",
        })

        self.assertEqual(datos["operativoId"], "65a000000000000000000001")
        self.assertEqual(set(datos), {"operativoId", "animalId"})

        with self.assertRaises(ErrorValidacionInscripcion):
            InscripcionSerializer.validar_creacion({
                "operativoId": {"$ne": None},
                "animalId": "animal-1",
            })

        with self.assertRaises(ErrorValidacionInscripcion):
            InscripcionSerializer.validar_creacion({
                "operativoId": "65a000000000000000000001",
                "animalId": "animal-1",
                "rutSolicitante": "12345678-9",
            })

    def test_estado_no_permite_campos_ni_transiciones_ajenas(self):
        self.assertEqual(
            InscripcionSerializer.validar_cambio_estado({"estado": "cancelada"}),
            "cancelada"
        )
        with self.assertRaises(ErrorValidacionInscripcion):
            InscripcionSerializer.validar_cambio_estado({"estado": "atendida"})

    def test_modelo_genera_documento_minimo_y_fecha_utc(self):
        documento = Inscripcion(
            operativoId="op-1",
            animalId="animal-1",
            rutSolicitante="12345678-9",
        ).a_documento()

        self.assertEqual(
            set(documento),
            {
                "operativoId",
                "animalId",
                "rutSolicitante",
                "estado",
                "fechaCreacion",
            }
        )
        self.assertEqual(documento["estado"], "solicitada")
        fecha = datetime.fromisoformat(
            documento["fechaCreacion"].replace("Z", "+00:00")
        )
        self.assertEqual(fecha.utcoffset().total_seconds(), 0)


class InscripcionApiTests(SimpleTestCase):
    def test_listado_vecinal_filtra_por_rut_de_sesion(self):
        request = RequestFactory().get(
            "/api/operativos/inscripciones?page=1&limit=5",
            HTTP_AUTHORIZATION="Bearer token-prueba",
        )
        with (
            patch(
                "inscripciones.auth.validar_sesion_nucleo",
                return_value={"rut": "12345678-9", "perfil": "vecino"},
            ),
            patch(
                "inscripciones.views.listar_inscripciones",
                return_value=(0, []),
            ) as listar,
        ):
            respuesta = api_inscripciones(request)

        self.assertEqual(respuesta.status_code, 200)
        listar.assert_called_once_with(1, 5, "12345678-9")

    def test_token_ausente_responde_401_con_formato_comun(self):
        request = RequestFactory().get("/api/operativos/inscripciones")
        respuesta = api_inscripciones(request)

        self.assertEqual(respuesta.status_code, 401)
        self.assertEqual(
            json.loads(respuesta.content)["error"]["codigo"],
            "TOKEN_REQUERIDO"
        )


class InscripcionServiceTests(SimpleTestCase):
    @patch("inscripciones.services._consultar_json", return_value=None)
    @patch("inscripciones.services._base_url", return_value="https://m1.test")
    def test_animal_inexistente_responde_como_404(self, _consulta, _base_url):
        with self.assertRaises(ErrorInscripciones) as contexto:
            _obtener_animal("animal-inexistente", "token")

        self.assertEqual(contexto.exception.estado_http, 404)

    @patch(
        "inscripciones.services._consultar_json",
        return_value={"estado": "fallecido", "especieId": "canino"},
    )
    @patch("inscripciones.services._base_url", return_value="https://m1.test")
    def test_animal_fallecido_no_es_elegible(self, _consulta, _base_url):
        with self.assertRaises(ErrorInscripciones) as contexto:
            _obtener_animal("animal-1", "token")

        self.assertEqual(contexto.exception.codigo, "ANIMAL_NO_ELEGIBLE")

    @patch(
        "inscripciones.services._consultar_json",
        return_value={"prohibicionTenencia": True},
    )
    @patch("inscripciones.services._base_url", return_value="https://nucleo.test")
    def test_prohibicion_de_tenencia_bloquea_al_solicitante(
        self,
        _consulta,
        _base_url,
    ):
        with self.assertRaises(ErrorInscripciones) as contexto:
            _validar_prohibicion_tenencia("12345678-9", "token")

        self.assertEqual(contexto.exception.estado_http, 403)
