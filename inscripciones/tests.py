import json
from datetime import datetime
from unittest.mock import Mock, patch

from django.http import JsonResponse
from django.test import RequestFactory, SimpleTestCase
from requests import Timeout

from .auth import requiere_perfiles
from .models import Inscripcion
from .serializers import (
    ErrorSalidaInscripcion,
    ErrorValidacionInscripcion,
    InscripcionSerializer,
)
from .services import (
    ErrorInscripciones,
    _consultar_animal,
    _consultar_json,
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
    @patch("inscripciones.services.requests.get")
    def test_cliente_http_envia_bearer_y_timeout(self, get):
        respuesta = Mock(status_code=200)
        respuesta.json.return_value = {"id": "animal-1"}
        get.return_value = respuesta

        datos = _consultar_json("https://m1.test/recurso", "token-prueba")

        self.assertEqual(datos, {"id": "animal-1"})
        get.assert_called_once_with(
            "https://m1.test/recurso",
            headers={"Authorization": "Bearer token-prueba"},
            timeout=10,
        )

    @patch("inscripciones.services.requests.get")
    def test_respuesta_http_404_se_representa_como_no_encontrado(self, get):
        get.return_value = Mock(status_code=404)

        self.assertIsNone(_consultar_json("https://m1.test/recurso", "token"))

    @patch("inscripciones.services.requests.get")
    def test_error_http_5xx_se_expone_como_servicio_no_disponible(self, get):
        get.return_value = Mock(status_code=503)

        with self.assertRaises(ErrorInscripciones) as contexto:
            _consultar_json("https://m1.test/recurso", "token")

        self.assertEqual(contexto.exception.estado_http, 503)
        self.assertEqual(
            contexto.exception.codigo,
            "SERVICIO_EXTERNO_NO_DISPONIBLE"
        )

    @patch("inscripciones.services.requests.get", side_effect=Timeout)
    def test_timeout_externo_se_expone_como_servicio_no_disponible(self, _get):
        with self.assertRaises(ErrorInscripciones) as contexto:
            _consultar_json("https://m1.test/recurso", "token")

        self.assertEqual(contexto.exception.estado_http, 503)

    @patch("inscripciones.services.requests.get")
    def test_error_http_no_404_del_servicio_se_expone_como_502(self, get):
        get.return_value = Mock(status_code=403)

        with self.assertRaises(ErrorInscripciones) as contexto:
            _consultar_json("https://m1.test/recurso", "token")

        self.assertEqual(contexto.exception.estado_http, 502)
        self.assertEqual(
            contexto.exception.codigo,
            "RESPUESTA_EXTERNA_INVALIDA"
        )

    @patch("inscripciones.services.requests.get")
    def test_json_invalido_o_no_objeto_se_rechaza(self, get):
        respuesta = Mock(status_code=200)
        respuesta.json.side_effect = ValueError("JSON inválido")
        get.return_value = respuesta

        with self.assertRaises(ErrorInscripciones) as json_invalido:
            _consultar_json("https://m1.test/recurso", "token")
        self.assertEqual(json_invalido.exception.estado_http, 502)

        respuesta.json.side_effect = None
        respuesta.json.return_value = ["no", "es", "un", "objeto"]
        with self.assertRaises(ErrorInscripciones) as formato_invalido:
            _consultar_json("https://m1.test/recurso", "token")
        self.assertEqual(formato_invalido.exception.estado_http, 502)

    @patch.dict("os.environ", {"M1_BASE_URL": " https://m1.test/ "})
    @patch("inscripciones.services.requests.get")
    def test_consulta_animal_codifica_id_y_acepta_envoltura_datos(self, get):
        respuesta = Mock(status_code=200)
        respuesta.json.return_value = {
            "datos": {
                "estado": "registrado",
                "especieId": "canino",
            }
        }
        get.return_value = respuesta

        animal = _consultar_animal("animal/uno", "token-prueba")

        self.assertEqual(animal["estado"], "registrado")
        self.assertEqual(animal["especieId"], "canino")
        get.assert_called_once_with(
            "https://m1.test/api/registro/animales/animal%2Funo",
            headers={"Authorization": "Bearer token-prueba"},
            timeout=10,
        )

    @patch(
        "inscripciones.services._consultar_json",
        return_value={"especieId": "canino"},
    )
    @patch("inscripciones.services._base_url", return_value="https://m1.test")
    def test_estado_ausente_en_animal_es_respuesta_malformada(
        self,
        _base_url,
        _consulta,
    ):
        with self.assertRaises(ErrorInscripciones) as contexto:
            _obtener_animal("animal-1", "token")

        self.assertEqual(contexto.exception.estado_http, 502)
        self.assertEqual(
            contexto.exception.codigo,
            "RESPUESTA_ANIMAL_INCOMPLETA"
        )

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

    @patch(
        "inscripciones.services._consultar_json",
        return_value={"prohibicionTenencia": False},
    )
    @patch("inscripciones.services._base_url", return_value="https://nucleo.test")
    def test_usuario_sin_prohibicion_puede_continuar(
        self,
        _base_url,
        _consulta,
    ):
        _validar_prohibicion_tenencia("12345678-9", "token")

    @patch(
        "inscripciones.services._consultar_json",
        return_value={"prohibicionTenencia": "false"},
    )
    @patch("inscripciones.services._base_url", return_value="https://nucleo.test")
    def test_prohibicion_de_tenencia_debe_ser_booleano(
        self,
        _base_url,
        _consulta,
    ):
        with self.assertRaises(ErrorInscripciones) as contexto:
            _validar_prohibicion_tenencia("12345678-9", "token")

        self.assertEqual(contexto.exception.estado_http, 502)
        self.assertEqual(
            contexto.exception.codigo,
            "RESPUESTA_USUARIO_INCOMPLETA"
        )
