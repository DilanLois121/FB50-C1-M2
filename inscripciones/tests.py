import json
from datetime import datetime
from unittest.mock import patch

from django.http import JsonResponse
from django.test import RequestFactory, SimpleTestCase

from .auth import requiere_perfiles
from .models import Inscripcion
from .serializers import (
    ErrorSalidaInscripcion,
    ErrorValidacionInscripcion,
    InscripcionSerializer,
)
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

    def test_salida_solo_expone_campos_permitidos_y_normaliza_fecha(self):
        representacion = InscripcionSerializer.representar({
            "_id": "inscripcion-1",
            "operativoId": "operativo-1",
            "animalId": "animal-1",
            "rutSolicitante": "12345678-9",
            "estado": "solicitada",
            "fechaCreacion": "2026-11-24T12:00:00-03:00",
            "nombreSolicitante": "Dato que no debe exponerse",
        })

        self.assertEqual(
            set(representacion),
            {
                "id",
                "operativoId",
                "animalId",
                "rutSolicitante",
                "estado",
                "fechaCreacion",
            }
        )
        self.assertEqual(
            representacion["fechaCreacion"],
            "2026-11-24T15:00:00Z"
        )

    def test_salida_invalida_se_rechaza(self):
        documento = {
            "_id": "inscripcion-1",
            "operativoId": "operativo-1",
            "animalId": "animal-1",
            "rutSolicitante": "12345678-9",
            "estado": "solicitada",
            "fechaCreacion": "no-es-una-fecha",
        }

        with self.assertRaises(ErrorSalidaInscripcion):
            InscripcionSerializer.representar(documento)

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

    def test_post_rechaza_tipo_de_contenido_incorrecto(self):
        request = RequestFactory().post(
            "/api/operativos/inscripciones",
            data="{}",
            content_type="text/plain",
            HTTP_AUTHORIZATION="Bearer token-prueba",
        )
        with patch(
            "inscripciones.auth.validar_sesion_nucleo",
            return_value={"rut": "12345678-9", "perfil": "vecino"},
        ):
            respuesta = api_inscripciones(request)

        self.assertEqual(respuesta.status_code, 415)
        self.assertEqual(
            json.loads(respuesta.content)["error"]["codigo"],
            "TIPO_CONTENIDO_INVALIDO"
        )

    def test_post_rechaza_constantes_json_no_estandar(self):
        request = RequestFactory().post(
            "/api/operativos/inscripciones",
            data='{"operativoId":"op-1","animalId":NaN}',
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer token-prueba",
        )
        with patch(
            "inscripciones.auth.validar_sesion_nucleo",
            return_value={"rut": "12345678-9", "perfil": "vecino"},
        ):
            respuesta = api_inscripciones(request)

        self.assertEqual(respuesta.status_code, 400)
        self.assertEqual(
            json.loads(respuesta.content)["error"]["codigo"],
            "JSON_INVALIDO"
        )


class AutenticacionInscripcionTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @staticmethod
    @requiere_perfiles("funcionario")
    def vista_protegida(request):
        return JsonResponse({
            "perfil": request.perfil,
            "rut": request.usuario["rut"],
            "token": request.token_bearer,
        })

    def test_sin_token_responde_401_y_no_consulta_nucleo(self):
        request = self.factory.get("/protegido")
        with patch("inscripciones.auth.validar_sesion_nucleo") as validar:
            respuesta = self.vista_protegida(request)

        self.assertEqual(respuesta.status_code, 401)
        self.assertEqual(
            json.loads(respuesta.content)["error"]["codigo"],
            "TOKEN_REQUERIDO"
        )
        validar.assert_not_called()

    def test_formato_bearer_invalido_responde_401(self):
        request = self.factory.get(
            "/protegido",
            HTTP_AUTHORIZATION="Basic token-prueba",
        )
        respuesta = self.vista_protegida(request)

        self.assertEqual(respuesta.status_code, 401)

    def test_token_rechazado_por_nucleo_responde_401(self):
        request = self.factory.get(
            "/protegido",
            HTTP_AUTHORIZATION="Bearer token-caducado",
        )
        with patch(
            "inscripciones.auth.validar_sesion_nucleo",
            return_value=None,
        ):
            respuesta = self.vista_protegida(request)

        self.assertEqual(respuesta.status_code, 401)
        self.assertEqual(
            json.loads(respuesta.content)["error"]["codigo"],
            "TOKEN_INVALIDO"
        )

    def test_error_de_conectividad_con_nucleo_responde_503(self):
        request = self.factory.get(
            "/protegido",
            HTTP_AUTHORIZATION="Bearer token-prueba",
        )
        with patch(
            "inscripciones.auth.validar_sesion_nucleo",
            side_effect=RuntimeError("fallo de conexión"),
        ):
            respuesta = self.vista_protegida(request)

        self.assertEqual(respuesta.status_code, 503)

    def test_respuesta_json_invalida_de_nucleo_responde_502(self):
        request = self.factory.get(
            "/protegido",
            HTTP_AUTHORIZATION="Bearer token-prueba",
        )
        with patch(
            "inscripciones.auth.validar_sesion_nucleo",
            side_effect=ValueError("respuesta no válida"),
        ):
            respuesta = self.vista_protegida(request)

        self.assertEqual(respuesta.status_code, 502)
        self.assertEqual(
            json.loads(respuesta.content)["error"]["codigo"],
            "RESPUESTA_NUCLEO_INVALIDA"
        )

    def test_respuesta_incompleta_de_nucleo_responde_502(self):
        request = self.factory.get(
            "/protegido",
            HTTP_AUTHORIZATION="Bearer token-prueba",
        )
        with patch(
            "inscripciones.auth.validar_sesion_nucleo",
            return_value={"rut": "12345678-9"},
        ):
            respuesta = self.vista_protegida(request)

        self.assertEqual(respuesta.status_code, 502)
        self.assertEqual(
            json.loads(respuesta.content)["error"]["codigo"],
            "RESPUESTA_NUCLEO_INVALIDA"
        )

    def test_perfil_no_autorizado_responde_403_y_no_ejecuta_vista(self):
        request = self.factory.get(
            "/protegido",
            HTTP_AUTHORIZATION="Bearer token-prueba",
        )
        with patch(
            "inscripciones.auth.validar_sesion_nucleo",
            return_value={
                "rut": "12345678-9",
                "perfil": "vecino",
            },
        ):
            respuesta = self.vista_protegida(request)

        self.assertEqual(respuesta.status_code, 403)

    def test_perfil_valido_se_normaliza_y_llega_a_la_vista(self):
        request = self.factory.get(
            "/protegido",
            HTTP_AUTHORIZATION="bEaReR token-prueba",
        )
        with patch(
            "inscripciones.auth.validar_sesion_nucleo",
            return_value={
                "rut": " 12345678-9 ",
                "perfil": " Funcionario ",
            },
        ) as validar:
            respuesta = self.vista_protegida(request)

        validar.assert_called_once_with("token-prueba")
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(
            json.loads(respuesta.content),
            {
                "perfil": "funcionario",
                "rut": "12345678-9",
                "token": "token-prueba",
            }
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
