import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, Mock, patch

from bson import ObjectId
from django.http import JsonResponse
from django.test import RequestFactory, SimpleTestCase
from django.urls import reverse
from pymongo.errors import PyMongoError
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
    _cantidad_no_asistencias,
    _consultar_animal,
    _consultar_json,
    listar_inscripciones,
    _obtener_animal,
    _validar_prohibicion_tenencia,
    cambiar_estado_inscripcion,
    crear_inscripcion,
)
from .views import api_inscripciones, pagina_mis_inscripciones


class InscripcionWebPageTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_vecino_y_comunitario_reciben_la_pagina_con_api_y_token(self):
        for perfil in ("vecino", "comunitario"):
            with self.subTest(perfil=perfil):
                request = self.factory.get(reverse("mis_inscripciones"))
                request.session = {
                    "token_nucleo": "token-prueba",
                    "perfil_usuario": perfil,
                }

                respuesta = pagina_mis_inscripciones(request)
                contenido = respuesta.content.decode()

                self.assertEqual(respuesta.status_code, 200)
                self.assertIn("/api/operativos/inscripciones", contenido)
                self.assertIn('"token-prueba"', contenido)
                self.assertIn('name="animalId"', contenido)
                self.assertIn("Authorization: `Bearer ${token}`", contenido)
                self.assertNotIn("rutSolicitante=", contenido)

    def test_sin_sesion_redirige_al_login(self):
        request = self.factory.get(reverse("mis_inscripciones"))
        request.session = {}

        respuesta = pagina_mis_inscripciones(request)

        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(respuesta.url, reverse("iniciar_sesion"))

    def test_perfil_funcionario_no_accede_a_la_pagina_vecinal(self):
        request = self.factory.get(reverse("mis_inscripciones"))
        request.session = {
            "token_nucleo": "token-prueba",
            "perfil_usuario": "funcionario",
        }

        respuesta = pagina_mis_inscripciones(request)

        self.assertEqual(respuesta.status_code, 403)


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
        listar.assert_called_once_with(1, 5, "12345678-9", None, None)

    def test_listado_comunitario_ignora_rut_enviado_por_cliente(self):
        request = RequestFactory().get(
            "/api/operativos/inscripciones?rutSolicitante=otra-persona&page=2",
            HTTP_AUTHORIZATION="Bearer token-prueba",
        )
        with (
            patch(
                "inscripciones.auth.validar_sesion_nucleo",
                return_value={
                    "rut": "98765432-1",
                    "perfil": "comunitario",
                },
            ),
            patch(
                "inscripciones.views.listar_inscripciones",
                return_value=(0, []),
            ) as listar,
        ):
            respuesta = api_inscripciones(request)

        self.assertEqual(respuesta.status_code, 200)
        listar.assert_called_once_with(2, 20, "98765432-1", None, None)

    def test_listado_pendientes_aplica_estado_y_privacidad(self):
        request = RequestFactory().get(
            "/api/operativos/inscripciones?estado=solicitada&page=2&limit=5",
            HTTP_AUTHORIZATION="Bearer token-prueba",
        )
        with (
            patch(
                "inscripciones.auth.validar_sesion_nucleo",
                return_value={
                    "rut": "12345678-9",
                    "perfil": "vecino",
                },
            ),
            patch(
                "inscripciones.views.listar_inscripciones",
                return_value=(0, []),
            ) as listar,
        ):
            respuesta = api_inscripciones(request)

        self.assertEqual(respuesta.status_code, 200)
        listar.assert_called_once_with(
            2,
            5,
            "12345678-9",
            "solicitada",
            None,
        )

    def test_listado_vecinal_combina_animal_estado_y_rut_de_sesion(self):
        request = RequestFactory().get(
            "/api/operativos/inscripciones"
            "?animalId=SIM-000006&estado=solicitada&page=1&limit=20"
            "&rutSolicitante=98765432-1",
            HTTP_AUTHORIZATION="Bearer token-prueba",
        )
        documento = {
            "_id": ObjectId("65a000000000000000000001"),
            "operativoId": "operativo-1",
            "animalId": "SIM-000006",
            "rutSolicitante": "12345678-9",
            "estado": "solicitada",
            "fechaCreacion": "2026-11-24T12:00:00Z",
        }
        with (
            patch(
                "inscripciones.auth.validar_sesion_nucleo",
                return_value={
                    "rut": "12345678-9",
                    "perfil": "vecino",
                },
            ),
            patch(
                "inscripciones.views.listar_inscripciones",
                return_value=(1, [documento]),
            ) as listar,
        ):
            respuesta = api_inscripciones(request)

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(
            json.loads(respuesta.content),
            {
                "page": 1,
                "limit": 20,
                "total": 1,
                "totalPaginas": 1,
                "datos": [{
                    "id": "65a000000000000000000001",
                    "operativoId": "operativo-1",
                    "animalId": "SIM-000006",
                    "rutSolicitante": "12345678-9",
                    "estado": "solicitada",
                    "fechaCreacion": "2026-11-24T12:00:00Z",
                }],
            },
        )
        listar.assert_called_once_with(
            1,
            20,
            "12345678-9",
            "solicitada",
            "SIM-000006",
        )

    def test_cambiar_animal_id_no_elude_el_filtro_por_rut_de_sesion(self):
        for perfil, rut in (
            ("vecino", "12345678-9"),
            ("comunitario", "98765432-1"),
        ):
            with self.subTest(perfil=perfil):
                request = RequestFactory().get(
                    "/api/operativos/inscripciones"
                    "?animalId=SIM-AJENO&rutSolicitante=11111111-1",
                    HTTP_AUTHORIZATION="Bearer token-prueba",
                )
                with (
                    patch(
                        "inscripciones.auth.validar_sesion_nucleo",
                        return_value={"rut": rut, "perfil": perfil},
                    ),
                    patch(
                        "inscripciones.views.listar_inscripciones",
                        return_value=(0, []),
                    ) as listar,
                ):
                    respuesta = api_inscripciones(request)

                self.assertEqual(respuesta.status_code, 200)
                self.assertEqual(json.loads(respuesta.content)["total"], 0)
                self.assertEqual(json.loads(respuesta.content)["datos"], [])
                listar.assert_called_once_with(
                    1,
                    20,
                    rut,
                    None,
                    "SIM-AJENO",
                )

    def test_funcionario_consulta_pendientes_sin_filtro_por_rut(self):
        request = RequestFactory().get(
            "/api/operativos/inscripciones?estado=solicitada",
            HTTP_AUTHORIZATION="Bearer token-prueba",
        )
        with (
            patch(
                "inscripciones.auth.validar_sesion_nucleo",
                return_value={
                    "rut": "12345678-9",
                    "perfil": "funcionario",
                },
            ),
            patch(
                "inscripciones.views.listar_inscripciones",
                return_value=(0, []),
            ) as listar,
        ):
            respuesta = api_inscripciones(request)

        self.assertEqual(respuesta.status_code, 200)
        listar.assert_called_once_with(
            1,
            20,
            None,
            "solicitada",
            None,
        )

    def test_estado_filtro_invalido_responde_400(self):
        request = RequestFactory().get(
            "/api/operativos/inscripciones?estado=desconocido",
            HTTP_AUTHORIZATION="Bearer token-prueba",
        )
        with patch(
            "inscripciones.auth.validar_sesion_nucleo",
            return_value={
                "rut": "12345678-9",
                "perfil": "funcionario",
            },
        ):
            respuesta = api_inscripciones(request)

        self.assertEqual(respuesta.status_code, 400)
        self.assertEqual(
            json.loads(respuesta.content)["error"]["codigo"],
            "ESTADO_FILTRO_INVALIDO",
        )

    def test_animal_id_invalido_responde_400_sin_consultar(self):
        for animal_id in ("", "%20%20", "x" * 129):
            with self.subTest(animal_id=animal_id):
                request = RequestFactory().get(
                    "/api/operativos/inscripciones?animalId=" + animal_id,
                    HTTP_AUTHORIZATION="Bearer token-prueba",
                )
                with (
                    patch(
                        "inscripciones.auth.validar_sesion_nucleo",
                        return_value={
                            "rut": "12345678-9",
                            "perfil": "funcionario",
                        },
                    ),
                    patch("inscripciones.views.listar_inscripciones") as listar,
                ):
                    respuesta = api_inscripciones(request)

                self.assertEqual(respuesta.status_code, 400)
                self.assertEqual(
                    json.loads(respuesta.content)["error"]["codigo"],
                    "CAMPO_INVALIDO",
                )
                listar.assert_not_called()

    def test_perfil_no_autorizado_recibe_403_en_listado(self):
        request = RequestFactory().get(
            "/api/operativos/inscripciones",
            HTTP_AUTHORIZATION="Bearer token-prueba",
        )
        with (
            patch(
                "inscripciones.auth.validar_sesion_nucleo",
                return_value={
                    "rut": "12345678-9",
                    "perfil": "admin",
                },
            ),
            patch("inscripciones.views.listar_inscripciones") as listar,
        ):
            respuesta = api_inscripciones(request)

        self.assertEqual(respuesta.status_code, 403)
        self.assertEqual(
            json.loads(respuesta.content),
            {
                "error": {
                    "codigo": "PERFIL_NO_AUTORIZADO",
                    "mensaje": "Su perfil no tiene permisos para este recurso.",
                },
            },
        )
        listar.assert_not_called()

    def test_listado_funcionario_no_se_filtra_por_rut_de_consulta(self):
        request = RequestFactory().get(
            "/api/operativos/inscripciones?rutSolicitante=otra-persona",
            HTTP_AUTHORIZATION="Bearer token-prueba",
        )
        with (
            patch(
                "inscripciones.auth.validar_sesion_nucleo",
                return_value={
                    "rut": "12345678-9",
                    "perfil": "funcionario",
                },
            ),
            patch(
                "inscripciones.views.listar_inscripciones",
                return_value=(0, []),
            ) as listar,
        ):
            respuesta = api_inscripciones(request)

        self.assertEqual(respuesta.status_code, 200)
        listar.assert_called_once_with(1, 20, None, None, None)

    def test_paginacion_invalida_no_consulta_inscripciones(self):
        for query in ("page=0", "page=-1", "page=abc", "limit=0", "limit=101"):
            with self.subTest(query=query):
                request = RequestFactory().get(
                    f"/api/operativos/inscripciones?{query}",
                    HTTP_AUTHORIZATION="Bearer token-prueba",
                )
                with (
                    patch(
                        "inscripciones.auth.validar_sesion_nucleo",
                        return_value={
                            "rut": "12345678-9",
                            "perfil": "vecino",
                        },
                    ),
                    patch("inscripciones.views.listar_inscripciones") as listar,
                ):
                    respuesta = api_inscripciones(request)

                self.assertEqual(respuesta.status_code, 400)
                self.assertEqual(
                    json.loads(respuesta.content)["error"]["codigo"],
                    "PAGINACION_INVALIDA"
                )
                listar.assert_not_called()

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
    @patch("inscripciones.services._coleccion")
    def test_listado_filtra_en_mongo_y_pagina_con_orden_determinista(
        self,
        coleccion_mock,
    ):
        inscripciones = MagicMock()
        cursor = MagicMock()
        cursor.sort.return_value = cursor
        cursor.skip.return_value = cursor
        cursor.limit.return_value = cursor
        cursor.__iter__.return_value = iter([])
        inscripciones.find.return_value = cursor
        inscripciones.count_documents.return_value = 0
        coleccion_mock.return_value = inscripciones

        total, documentos = listar_inscripciones(
            page=3,
            limit=10,
            rut_solicitante="12345678-9",
        )

        self.assertEqual(total, 0)
        self.assertEqual(documentos, [])
        filtro = {"rutSolicitante": "12345678-9"}
        inscripciones.count_documents.assert_called_once_with(filtro)
        inscripciones.find.assert_called_once_with(filtro)
        cursor.sort.assert_called_once_with([
            ("fechaCreacion", -1),
            ("_id", -1),
        ])
        cursor.skip.assert_called_once_with(20)
        cursor.limit.assert_called_once_with(10)

    @patch("inscripciones.services._coleccion")
    def test_listado_pendientes_aplica_estado_y_rut_al_conteo_y_consulta(
        self,
        coleccion_mock,
    ):
        inscripciones = MagicMock()
        cursor = MagicMock()
        cursor.sort.return_value = cursor
        cursor.skip.return_value = cursor
        cursor.limit.return_value = cursor
        cursor.__iter__.return_value = iter([])
        inscripciones.find.return_value = cursor
        inscripciones.count_documents.return_value = 0
        coleccion_mock.return_value = inscripciones

        total, documentos = listar_inscripciones(
            page=1,
            limit=20,
            rut_solicitante="12345678-9",
            estado="solicitada",
        )

        filtro = {
            "rutSolicitante": "12345678-9",
            "estado": "solicitada",
        }
        self.assertEqual(total, 0)
        self.assertEqual(documentos, [])
        inscripciones.count_documents.assert_called_once_with(filtro)
        inscripciones.find.assert_called_once_with(filtro)

    @patch("inscripciones.services._coleccion")
    def test_listado_por_animal_combina_filtros_y_pagina_en_mongo(
        self,
        coleccion_mock,
    ):
        inscripciones = MagicMock()
        cursor = MagicMock()
        cursor.sort.return_value = cursor
        cursor.skip.return_value = cursor
        cursor.limit.return_value = cursor
        documentos = [{"animalId": "SIM-000006"}]
        cursor.__iter__.return_value = iter(documentos)
        inscripciones.find.return_value = cursor
        inscripciones.count_documents.return_value = 3
        coleccion_mock.return_value = inscripciones

        total, resultado = listar_inscripciones(
            page=2,
            limit=2,
            rut_solicitante="12345678-9",
            estado="solicitada",
            animal_id="SIM-000006",
        )

        filtro = {
            "rutSolicitante": "12345678-9",
            "estado": "solicitada",
            "animalId": "SIM-000006",
        }
        self.assertEqual(total, 3)
        self.assertEqual(resultado, documentos)
        inscripciones.count_documents.assert_called_once_with(filtro)
        inscripciones.find.assert_called_once_with(filtro)
        cursor.skip.assert_called_once_with(2)
        cursor.limit.assert_called_once_with(2)

    def preparar_creacion(self, tipo_operativo="esterilizacion", disponibles=3):
        operativo_id = ObjectId()
        operativos = MagicMock()
        operativos.find_one.return_value = {
            "_id": operativo_id,
            "tipoOperativo": tipo_operativo,
            "cuposPorEspecie": [{
                "especieId": "canino",
                "total": 3,
                "disponibles": disponibles,
            }],
        }

        inscripciones = MagicMock()
        inscripciones.find_one.return_value = None
        inscripciones.count_documents.return_value = 0
        inscripciones.insert_one.return_value.inserted_id = ObjectId()

        atenciones = MagicMock()
        atenciones.count_documents.return_value = 0

        return {
            "operativos": operativos,
            "inscripciones": inscripciones,
            "atenciones": atenciones,
        }, str(operativo_id)

    def crear_con_dependencias(
        self,
        colecciones,
        operativo_id,
        perfil="vecino",
        animal_esterilizado=False,
        no_asistencias=0,
    ):
        with (
            patch(
                "inscripciones.services._coleccion",
                side_effect=lambda nombre: colecciones[nombre],
            ),
            patch(
                "inscripciones.services._obtener_animal",
                return_value={
                    "estado": "registrado",
                    "especieId": "canino",
                },
            ),
            patch("inscripciones.services._validar_prohibicion_tenencia"),
            patch(
                "inscripciones.services._animal_esterilizado",
                return_value=animal_esterilizado,
            ),
            patch(
                "inscripciones.services._cantidad_no_asistencias",
                return_value=no_asistencias,
            ),
        ):
            return crear_inscripcion(
                operativo_id=operativo_id,
                animal_id="animal-1",
                rut_solicitante="12345678-9",
                perfil=perfil,
                token="token-prueba",
            )

    def test_creacion_persiste_inscripcion_solicitada_con_rut_de_sesion(self):
        colecciones, operativo_id = self.preparar_creacion()

        documento = self.crear_con_dependencias(colecciones, operativo_id)

        colecciones["inscripciones"].insert_one.assert_called_once()
        guardado = colecciones["inscripciones"].insert_one.call_args.args[0]
        self.assertEqual(guardado["operativoId"], operativo_id)
        self.assertEqual(guardado["animalId"], "animal-1")
        self.assertEqual(guardado["rutSolicitante"], "12345678-9")
        self.assertEqual(guardado["estado"], "solicitada")
        self.assertIsInstance(documento["_id"], ObjectId)

    def test_operativo_inexistente_detiene_la_creacion(self):
        colecciones, operativo_id = self.preparar_creacion()
        colecciones["operativos"].find_one.return_value = None

        with self.assertRaises(ErrorInscripciones) as contexto:
            self.crear_con_dependencias(colecciones, operativo_id)

        self.assertEqual(contexto.exception.estado_http, 404)
        colecciones["inscripciones"].insert_one.assert_not_called()

    def test_cupo_agotado_no_crea_inscripcion(self):
        colecciones, operativo_id = self.preparar_creacion(disponibles=0)

        with self.assertRaises(ErrorInscripciones) as contexto:
            self.crear_con_dependencias(colecciones, operativo_id)

        self.assertEqual(contexto.exception.codigo, "CUPOS_AGOTADOS")
        colecciones["inscripciones"].insert_one.assert_not_called()

    def test_cupo_con_tipo_invalido_no_se_trata_como_disponible(self):
        colecciones, operativo_id = self.preparar_creacion(disponibles=True)

        with self.assertRaises(ErrorInscripciones) as contexto:
            self.crear_con_dependencias(colecciones, operativo_id)

        self.assertEqual(contexto.exception.codigo, "CUPOS_INVALIDOS")
        self.assertEqual(contexto.exception.estado_http, 500)

    def test_rechaza_inscripcion_activa_duplicada_para_animal_y_operativo(self):
        colecciones, operativo_id = self.preparar_creacion()
        colecciones["inscripciones"].find_one.return_value = {"_id": ObjectId()}

        with self.assertRaises(ErrorInscripciones) as contexto:
            self.crear_con_dependencias(colecciones, operativo_id)

        self.assertEqual(contexto.exception.codigo, "INSCRIPCION_DUPLICADA")
        colecciones["inscripciones"].insert_one.assert_not_called()

    def test_rechaza_la_tercera_inscripcion_activa_del_rut(self):
        colecciones, operativo_id = self.preparar_creacion()
        colecciones["inscripciones"].count_documents.return_value = 2

        with self.assertRaises(ErrorInscripciones) as contexto:
            self.crear_con_dependencias(colecciones, operativo_id)

        self.assertEqual(contexto.exception.codigo, "LIMITE_INSCRIPCIONES")
        colecciones["inscripciones"].insert_one.assert_not_called()

    def test_dos_inasistencias_bloquean_a_vecino(self):
        colecciones, operativo_id = self.preparar_creacion()

        with self.assertRaises(ErrorInscripciones) as contexto:
            self.crear_con_dependencias(
                colecciones,
                operativo_id,
                no_asistencias=2,
            )

        self.assertEqual(
            contexto.exception.codigo,
            "BLOQUEO_POR_INASISTENCIAS"
        )
        colecciones["inscripciones"].insert_one.assert_not_called()

    def test_funcionario_no_se_bloquea_por_inasistencias(self):
        colecciones, operativo_id = self.preparar_creacion()

        self.crear_con_dependencias(
            colecciones,
            operativo_id,
            perfil="funcionario",
            no_asistencias=2,
        )

        colecciones["inscripciones"].insert_one.assert_called_once()

    def test_esterilizacion_atendida_impide_nueva_inscripcion_de_esterilizacion(self):
        colecciones, operativo_id = self.preparar_creacion()

        with self.assertRaises(ErrorInscripciones) as contexto:
            self.crear_con_dependencias(
                colecciones,
                operativo_id,
                animal_esterilizado=True,
            )

        self.assertEqual(contexto.exception.codigo, "ESTERILIZACION_PREVIA")
        colecciones["inscripciones"].insert_one.assert_not_called()

    def test_esterilizacion_previa_no_bloquea_un_operativo_de_chipeo(self):
        colecciones, operativo_id = self.preparar_creacion(
            tipo_operativo="chipeo"
        )

        self.crear_con_dependencias(
            colecciones,
            operativo_id,
            animal_esterilizado=True,
        )

        colecciones["inscripciones"].insert_one.assert_called_once()

    def test_conteo_de_inasistencias_usa_seis_meses_calendario(self):
        ahora = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)
        atenciones = MagicMock()
        atenciones.count_documents.return_value = 2

        with (
            patch("inscripciones.services._coleccion", return_value=atenciones),
            patch("inscripciones.services.datetime") as fecha_mock,
        ):
            fecha_mock.now.return_value = ahora
            resultado = _cantidad_no_asistencias("12345678-9")

        self.assertEqual(resultado, 2)
        consulta = atenciones.count_documents.call_args.args[0]
        self.assertEqual(consulta["rutSolicitante"], "12345678-9")
        self.assertEqual(
            consulta["estado"],
            {"$in": ["no asistió", "no_asistio", "no asistio"]}
        )
        self.assertEqual(
            consulta["$or"][0]["fechaAtencion"]["$gte"],
            datetime(2026, 2, 28, 12, 0, tzinfo=timezone.utc)
        )

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


class InscripcionTransicionTests(SimpleTestCase):
    def preparar_transicion(self, estado="solicitada", horas_hasta_operativo=48):
        inscripcion_id = ObjectId()
        operativo_id = ObjectId()
        documento = {
            "_id": inscripcion_id,
            "operativoId": str(operativo_id),
            "animalId": "animal-1",
            "rutSolicitante": "12345678-9",
            "estado": estado,
        }
        operativo = {
            "_id": operativo_id,
            "fechaHora": datetime.now(timezone.utc)
            + timedelta(hours=horas_hasta_operativo),
        }

        inscripciones = MagicMock()
        inscripciones.find_one.return_value = documento.copy()
        inscripciones.find_one_and_update.return_value = documento.copy()
        inscripciones.update_one.return_value.matched_count = 1

        operativos = MagicMock()
        operativos.find_one.return_value = operativo
        operativos.update_one.return_value.matched_count = 1

        return {
            "inscripciones": inscripciones,
            "operativos": operativos,
        }, str(inscripcion_id), documento, operativo

    def cambiar(
        self,
        colecciones,
        inscripcion_id,
        nuevo_estado,
        perfil,
        rut="12345678-9",
    ):
        with (
            patch(
                "inscripciones.services._coleccion",
                side_effect=lambda nombre: colecciones[nombre],
            ),
            patch(
                "inscripciones.services._obtener_animal",
                return_value={
                    "estado": "registrado",
                    "especieId": "canino",
                },
            ),
            patch("inscripciones.services._consultar_animal") as consultar_animal,
        ):
            consultar_animal.return_value = {"especieId": "canino"}
            return cambiar_estado_inscripcion(
                inscripcion_id=inscripcion_id,
                nuevo_estado=nuevo_estado,
                usuario={"rut": rut},
                perfil=perfil,
                token="token-prueba",
            )

    def test_funcionario_confirma_solicitada_y_descuenta_un_cupo(self):
        colecciones, inscripcion_id, _, operativo = self.preparar_transicion()

        resultado = self.cambiar(
            colecciones,
            inscripcion_id,
            "confirmada",
            "funcionario",
        )

        self.assertEqual(resultado["estado"], "confirmada")
        operativos = colecciones["operativos"]
        operativos.update_one.assert_called_once_with(
            {
                "_id": operativo["_id"],
                "cuposPorEspecie": {
                    "$elemMatch": {
                        "especieId": "canino",
                        "disponibles": {"$gt": 0},
                    }
                },
            },
            {"$inc": {"cuposPorEspecie.$.disponibles": -1}}
        )
        colecciones["inscripciones"].update_one.assert_called_once_with(
            {"_id": ObjectId(inscripcion_id), "estado": "solicitada"},
            {"$set": {"estado": "confirmada"}}
        )

    def test_otro_perfil_no_puede_confirmar(self):
        colecciones, inscripcion_id, _, _ = self.preparar_transicion()

        with self.assertRaises(ErrorInscripciones) as contexto:
            self.cambiar(
                colecciones,
                inscripcion_id,
                "confirmada",
                "vecino",
            )

        self.assertEqual(contexto.exception.estado_http, 403)
        colecciones["operativos"].update_one.assert_not_called()

    def test_no_confirma_si_no_hay_cupo_y_no_cambia_estado(self):
        colecciones, inscripcion_id, _, _ = self.preparar_transicion()
        colecciones["operativos"].update_one.return_value.matched_count = 0

        with self.assertRaises(ErrorInscripciones) as contexto:
            self.cambiar(
                colecciones,
                inscripcion_id,
                "confirmada",
                "funcionario",
            )

        self.assertEqual(contexto.exception.codigo, "CUPOS_AGOTADOS")
        colecciones["inscripciones"].update_one.assert_not_called()

    def test_dos_confirmaciones_no_consumen_mas_que_el_ultimo_cupo(self):
        colecciones, primera_id, _, operativo = self.preparar_transicion()
        primera_reserva = MagicMock()
        primera_reserva.matched_count = 1
        segunda_reserva = MagicMock()
        segunda_reserva.matched_count = 0
        colecciones["operativos"].update_one.side_effect = [
            primera_reserva,
            segunda_reserva,
        ]

        primera = self.cambiar(
            colecciones,
            primera_id,
            "confirmada",
            "funcionario",
        )

        segunda_id = str(ObjectId())
        segunda_documento = {
            "_id": ObjectId(segunda_id),
            "operativoId": str(operativo["_id"]),
            "animalId": "animal-2",
            "rutSolicitante": "98765432-1",
            "estado": "solicitada",
        }
        colecciones["inscripciones"].find_one.return_value = segunda_documento

        with self.assertRaises(ErrorInscripciones) as contexto:
            self.cambiar(
                colecciones,
                segunda_id,
                "confirmada",
                "funcionario",
            )

        self.assertEqual(primera["estado"], "confirmada")
        self.assertEqual(contexto.exception.codigo, "CUPOS_AGOTADOS")
        self.assertEqual(colecciones["operativos"].update_one.call_count, 2)

    def test_confirmacion_y_cancelacion_no_afectan_otra_especie(self):
        colecciones, inscripcion_id, documento, operativo = (
            self.preparar_transicion(estado="confirmada")
        )

        colecciones["operativos"].update_one.return_value.matched_count = 1
        resultado = self.cambiar(
            colecciones,
            inscripcion_id,
            "cancelada",
            "funcionario",
        )

        self.assertEqual(resultado["estado"], "cancelada")
        colecciones["operativos"].update_one.assert_called_once_with(
            {
                "_id": ObjectId(documento["operativoId"]),
                "cuposPorEspecie.especieId": "canino",
            },
            {"$inc": {"cuposPorEspecie.$.disponibles": 1}}
        )
        llamada = colecciones["operativos"].update_one.call_args.args
        self.assertNotIn("felino", str(llamada))
        self.assertNotIn("felino", str(operativo))

    def test_confirma_solo_desde_estado_solicitada(self):
        colecciones, inscripcion_id, _, _ = self.preparar_transicion(
            estado="cancelada"
        )

        with self.assertRaises(ErrorInscripciones) as contexto:
            self.cambiar(
                colecciones,
                inscripcion_id,
                "confirmada",
                "funcionario",
            )

        self.assertEqual(contexto.exception.codigo, "TRANSICION_INVALIDA")
        colecciones["operativos"].update_one.assert_not_called()

    def test_fallo_al_actualizar_estado_restituye_cupo_reservado(self):
        colecciones, inscripcion_id, _, operativo = self.preparar_transicion()
        colecciones["inscripciones"].update_one.side_effect = PyMongoError(
            "Error de escritura simulado"
        )

        with self.assertRaises(PyMongoError):
            self.cambiar(
                colecciones,
                inscripcion_id,
                "confirmada",
                "funcionario",
            )

        self.assertEqual(colecciones["operativos"].update_one.call_count, 2)
        colecciones["operativos"].update_one.assert_called_with(
            {
                "_id": operativo["_id"],
                "cuposPorEspecie.especieId": "canino",
            },
            {"$inc": {"cuposPorEspecie.$.disponibles": 1}}
        )

    def test_vecino_cancela_solicitada_propia_sin_restituir_cupo(self):
        colecciones, inscripcion_id, documento, _ = self.preparar_transicion()

        resultado = self.cambiar(
            colecciones,
            inscripcion_id,
            "cancelada",
            "vecino",
        )

        self.assertEqual(resultado["estado"], "cancelada")
        colecciones["inscripciones"].find_one_and_update.assert_called_once()
        filtro = colecciones["inscripciones"].find_one_and_update.call_args.args[0]
        self.assertEqual(
            filtro,
            {
                "_id": documento["_id"],
                "estado": "solicitada",
                "rutSolicitante": "12345678-9",
            }
        )
        colecciones["operativos"].update_one.assert_not_called()

    def test_vecino_no_puede_cancelar_inscripcion_ajena(self):
        colecciones, inscripcion_id, _, _ = self.preparar_transicion()

        with self.assertRaises(ErrorInscripciones) as contexto:
            self.cambiar(
                colecciones,
                inscripcion_id,
                "cancelada",
                "vecino",
                rut="98765432-1",
            )

        self.assertEqual(contexto.exception.estado_http, 403)
        colecciones["inscripciones"].find_one_and_update.assert_not_called()

    def test_vecino_no_cancela_con_menos_de_24_horas(self):
        colecciones, inscripcion_id, _, _ = self.preparar_transicion(
            horas_hasta_operativo=23
        )

        with self.assertRaises(ErrorInscripciones) as contexto:
            self.cambiar(
                colecciones,
                inscripcion_id,
                "cancelada",
                "vecino",
            )

        self.assertEqual(
            contexto.exception.codigo,
            "PLAZO_CANCELACION_VENCIDO"
        )
        colecciones["inscripciones"].find_one_and_update.assert_not_called()

    def test_funcionario_cancela_solicitada_sin_restriccion_de_24_horas(self):
        colecciones, inscripcion_id, _, _ = self.preparar_transicion(
            estado="solicitada",
            horas_hasta_operativo=2,
        )

        resultado = self.cambiar(
            colecciones,
            inscripcion_id,
            "cancelada",
            "funcionario",
        )

        self.assertEqual(resultado["estado"], "cancelada")
        colecciones["inscripciones"].find_one_and_update.assert_called_once()
        colecciones["operativos"].update_one.assert_not_called()

    def test_cancelar_confirmada_restituye_cupo(self):
        colecciones, inscripcion_id, documento, _ = self.preparar_transicion(
            estado="confirmada",
            horas_hasta_operativo=25,
        )

        resultado = self.cambiar(
            colecciones,
            inscripcion_id,
            "cancelada",
            "comunitario",
        )

        self.assertEqual(resultado["estado"], "cancelada")
        self.assertEqual(
            resultado["operativoId"],
            documento["operativoId"]
        )
        colecciones["operativos"].update_one.assert_called_once_with(
            {
                "_id": ObjectId(documento["operativoId"]),
                "cuposPorEspecie.especieId": "canino",
            },
            {"$inc": {"cuposPorEspecie.$.disponibles": 1}}
        )

    def test_fallo_al_restituir_cupo_revierte_estado_a_confirmada(self):
        colecciones, inscripcion_id, _, _ = self.preparar_transicion(
            estado="confirmada",
            horas_hasta_operativo=25,
        )
        colecciones["operativos"].update_one.return_value.matched_count = 0

        with self.assertRaises(RuntimeError):
            self.cambiar(
                colecciones,
                inscripcion_id,
                "cancelada",
                "vecino",
            )

        colecciones["inscripciones"].update_one.assert_called_once_with(
            {
                "_id": ObjectId(inscripcion_id),
                "estado": "cancelada",
            },
            {"$set": {"estado": "confirmada"}}
        )

    def test_no_permite_cancelar_inscripcion_ya_cancelada(self):
        colecciones, inscripcion_id, _, _ = self.preparar_transicion(
            estado="cancelada"
        )

        with self.assertRaises(ErrorInscripciones) as contexto:
            self.cambiar(
                colecciones,
                inscripcion_id,
                "cancelada",
                "funcionario",
            )

        self.assertEqual(contexto.exception.codigo, "TRANSICION_INVALIDA")
        colecciones["inscripciones"].find_one_and_update.assert_not_called()
