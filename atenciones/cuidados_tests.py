"""Pruebas de la API de registro de cuidados."""

import json
from datetime import datetime, timedelta
from unittest.mock import patch

from bson import ObjectId
from django.test import RequestFactory, SimpleTestCase

from .services import ErrorAtenciones
from .cuidados_views import (
    api_agregar_nota_cuidado,
    api_obtener_cuidado,
    api_registrar_cuidado,
)


class ApiRegistrarCuidadoTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.inscripcion_id = str(ObjectId())

    def crear_request(self):
        return self.factory.post(
            f"/api/operativos/cuidados/{self.inscripcion_id}",
            data=json.dumps({
                "indicaciones": "Reposo",
                "medicamentos": ["Analgesico"],
                "detalle_quirurgico": "Sin cirugía"
            }),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer token-prueba"
        )

    @patch(
        "inscripciones.auth.validar_sesion_nucleo",
        return_value={"rut": "12345678-9", "perfil": "veterinario"}
    )
    @patch("atenciones.cuidados_views.registrar_cuidado")
    def test_inscripcion_no_atendida_responde_400(
        self,
        mock_registrar,
        _mock_validar_sesion
    ):
        mock_registrar.side_effect = ErrorAtenciones(
            "INSCRIPCION_NO_ATENDIDA",
            "Solo se pueden registrar cuidados para una inscripción atendida.",
            400
        )

        respuesta = api_registrar_cuidado(
            self.crear_request(),
            self.inscripcion_id
        )

        self.assertEqual(respuesta.status_code, 400)
        self.assertEqual(
            json.loads(respuesta.content)["error"]["codigo"],
            "INSCRIPCION_NO_ATENDIDA"
        )

    @patch(
        "inscripciones.auth.validar_sesion_nucleo",
        return_value={"rut": "12345678-9", "perfil": "vecino"}
    )
    @patch("atenciones.cuidados_views.registrar_cuidado")
    def test_perfil_no_veterinario_responde_403(
        self,
        mock_registrar,
        _mock_validar_sesion
    ):
        respuesta = api_registrar_cuidado(
            self.crear_request(),
            self.inscripcion_id
        )

        self.assertEqual(respuesta.status_code, 403)
        self.assertEqual(
            json.loads(respuesta.content)["error"]["codigo"],
            "PERFIL_NO_AUTORIZADO"
        )
        mock_registrar.assert_not_called()

    @patch(
        "inscripciones.auth.validar_sesion_nucleo",
        return_value={"rut": "12345678-9", "perfil": "veterinario"}
    )
    @patch("atenciones.cuidados_views.registrar_cuidado")
    def test_registro_exitoso_responde_201(
        self,
        mock_registrar,
        _mock_validar_sesion
    ):
        cuidado_id = ObjectId()
        inscripcion_object_id = ObjectId(self.inscripcion_id)
        mock_registrar.return_value = {
            "_id": cuidado_id,
            "inscripcion_id": inscripcion_object_id,
            "veterinario_rut": "12345678-9",
            "indicaciones": "Reposo",
            "medicamentos": ["Analgesico"],
            "detalle_quirurgico": "Sin cirugía",
            "fecha_registro": "2026-11-25T00:00:00Z",
            "notas_complementarias": []
        }

        respuesta = api_registrar_cuidado(
            self.crear_request(),
            self.inscripcion_id
        )

        self.assertEqual(respuesta.status_code, 201)
        cuerpo = json.loads(respuesta.content)
        self.assertEqual(cuerpo["datos"]["id"], str(cuidado_id))
        self.assertEqual(
            cuerpo["datos"]["inscripcion_id"],
            self.inscripcion_id
        )
        mock_registrar.assert_called_once_with(
            inscripcion_id=self.inscripcion_id,
            usuario={"rut": "12345678-9", "perfil": "veterinario"},
            datos={
                "indicaciones": "Reposo",
                "medicamentos": ["Analgesico"],
                "detalle_quirurgico": "Sin cirugía"
            }
        )


class ApiAgregarNotaCuidadoTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.cuidado_id = str(ObjectId())

    def crear_request(self, method="post", nota="Control realizado"):
        request_method = getattr(self.factory, method)
        return request_method(
            f"/api/operativos/cuidados/{self.cuidado_id}/notas",
            data=json.dumps({"nota": nota}),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer token-prueba"
        )

    @patch(
        "inscripciones.auth.validar_sesion_nucleo",
        return_value={"rut": "12345678-9", "perfil": "veterinario"}
    )
    @patch("atenciones.cuidados_services.db")
    def test_agrega_nota_y_responde_201_con_autor_y_fecha_utc(
        self,
        mock_db,
        _mock_validar_sesion
    ):
        cuidado_id = ObjectId(self.cuidado_id)
        mock_db["cuidados"].find_one.return_value = {"_id": cuidado_id}

        respuesta = api_agregar_nota_cuidado(
            self.crear_request(),
            self.cuidado_id
        )

        self.assertEqual(respuesta.status_code, 201)
        cuerpo = json.loads(respuesta.content)
        self.assertEqual(
            cuerpo["mensaje"],
            "Nota complementaria agregada exitosamente."
        )
        nota = cuerpo["datos"]
        self.assertEqual(nota["nota"], "Control realizado")
        self.assertEqual(nota["autor_rut"], "12345678-9")
        fecha = datetime.fromisoformat(nota["fecha"].replace("Z", "+00:00"))
        self.assertEqual(fecha.utcoffset(), timedelta(0))
        mock_db["cuidados"].update_one.assert_called_once_with(
            {"_id": cuidado_id},
            {"$push": {"notas_complementarias": nota}}
        )

    @patch(
        "inscripciones.auth.validar_sesion_nucleo",
        return_value={"rut": "12345678-9", "perfil": "veterinario"}
    )
    @patch("atenciones.cuidados_services.db")
    def test_cuidado_inexistente_responde_404(
        self,
        mock_db,
        _mock_validar_sesion
    ):
        mock_db["cuidados"].find_one.return_value = None

        respuesta = api_agregar_nota_cuidado(
            self.crear_request(),
            self.cuidado_id
        )

        self.assertEqual(respuesta.status_code, 404)
        self.assertEqual(
            json.loads(respuesta.content)["error"]["codigo"],
            "CUIDADO_NO_ENCONTRADO"
        )
        mock_db["cuidados"].update_one.assert_not_called()

    @patch(
        "inscripciones.auth.validar_sesion_nucleo",
        return_value={"rut": "12345678-9", "perfil": "veterinario"}
    )
    @patch("atenciones.cuidados_services.db")
    def test_nota_vacia_responde_400(
        self,
        mock_db,
        _mock_validar_sesion
    ):
        mock_db["cuidados"].find_one.return_value = {
            "_id": ObjectId(self.cuidado_id)
        }

        respuesta = api_agregar_nota_cuidado(
            self.crear_request(nota="  "),
            self.cuidado_id
        )

        self.assertEqual(respuesta.status_code, 400)
        self.assertEqual(
            json.loads(respuesta.content)["error"]["codigo"],
            "NOTA_VACIA"
        )
        mock_db["cuidados"].update_one.assert_not_called()

    @patch(
        "inscripciones.auth.validar_sesion_nucleo",
        return_value={"rut": "12345678-9", "perfil": "vecino"}
    )
    @patch("atenciones.cuidados_services.db")
    def test_perfil_no_veterinario_responde_403(
        self,
        mock_db,
        _mock_validar_sesion
    ):
        respuesta = api_agregar_nota_cuidado(
            self.crear_request(),
            self.cuidado_id
        )

        self.assertEqual(respuesta.status_code, 403)
        self.assertEqual(
            json.loads(respuesta.content)["error"]["codigo"],
            "PERFIL_NO_AUTORIZADO"
        )
        mock_db["cuidados"].find_one.assert_not_called()

    def test_put_y_delete_no_son_permitidos(self):
        for metodo in ("put", "delete"):
            with self.subTest(metodo=metodo):
                respuesta = api_agregar_nota_cuidado(
                    self.crear_request(method=metodo),
                    self.cuidado_id
                )
                self.assertEqual(respuesta.status_code, 405)


class ApiObtenerCuidadoTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.inscripcion_id = str(ObjectId())

    def crear_request(self):
        return self.factory.get(
            f"/api/operativos/cuidados/inscripcion/{self.inscripcion_id}",
            HTTP_AUTHORIZATION="Bearer token-prueba"
        )

    def mock_cuidado(self):
        return {
            "_id": ObjectId(),
            "inscripcion_id": ObjectId(self.inscripcion_id),
            "veterinario_rut": "12345678-9",
            "indicaciones": "Reposo",
            "medicamentos": ["Analgesico"],
            "detalle_quirurgico": "Detalle confidencial",
            "notas_complementarias": [],
        }

    @patch(
        "inscripciones.auth.validar_sesion_nucleo",
        return_value={"rut": "12345678-9", "perfil": "funcionario"}
    )
    @patch("atenciones.cuidados_services.db")
    def test_funcionario_no_recibe_detalle_quirurgico(
        self,
        mock_db,
        _mock_validar_sesion
    ):
        mock_db["cuidados"].find_one.return_value = self.mock_cuidado()

        respuesta = api_obtener_cuidado(
            self.crear_request(),
            self.inscripcion_id
        )

        self.assertEqual(respuesta.status_code, 200)
        datos = json.loads(respuesta.content)["datos"]
        self.assertNotIn("detalle_quirurgico", datos)
        self.assertEqual(datos["inscripcion_id"], self.inscripcion_id)
        self.assertIsInstance(datos["_id"], str)

    @patch(
        "inscripciones.auth.validar_sesion_nucleo",
        return_value={"rut": "12345678-9", "perfil": "veterinario"}
    )
    @patch("atenciones.cuidados_services.db")
    def test_veterinario_recibe_detalle_quirurgico(
        self,
        mock_db,
        _mock_validar_sesion
    ):
        mock_db["cuidados"].find_one.return_value = self.mock_cuidado()

        respuesta = api_obtener_cuidado(
            self.crear_request(),
            self.inscripcion_id
        )

        self.assertEqual(respuesta.status_code, 200)
        datos = json.loads(respuesta.content)["datos"]
        self.assertEqual(datos["detalle_quirurgico"], "Detalle confidencial")
        self.assertEqual(datos["inscripcion_id"], self.inscripcion_id)
        self.assertIsInstance(datos["_id"], str)

    @patch(
        "inscripciones.auth.validar_sesion_nucleo",
        return_value={"rut": "12345678-9", "perfil": "vecino"}
    )
    @patch("atenciones.cuidados_services.db")
    def test_vecino_no_puede_consultar_cuidado(
        self,
        mock_db,
        _mock_validar_sesion
    ):
        respuesta = api_obtener_cuidado(
            self.crear_request(),
            self.inscripcion_id
        )

        self.assertEqual(respuesta.status_code, 403)
        self.assertEqual(
            json.loads(respuesta.content)["error"]["codigo"],
            "PERFIL_NO_AUTORIZADO"
        )
        mock_db["cuidados"].find_one.assert_not_called()
