"""Pruebas de la API de registro de cuidados."""

import json
from unittest.mock import patch

from bson import ObjectId
from django.test import RequestFactory, SimpleTestCase

from .services import ErrorAtenciones
from .cuidados_views import api_registrar_cuidado


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
