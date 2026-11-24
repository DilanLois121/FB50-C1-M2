from django.test import SimpleTestCase
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta, timezone

from bson import ObjectId

from atenciones.services import (
    ErrorAtenciones,
    _validar_microchip,
    _validar_id,
    registrar_atencion,
    cerrar_operativo,
)


class ValidacionMicrochipTests(SimpleTestCase):

    def test_microchip_de_15_digitos_es_valido(self):
        _validar_microchip("123456789012345")

    def test_microchip_con_menos_digitos_es_rechazado(self):
        with self.assertRaises(ErrorAtenciones):
            _validar_microchip("12345678901234")

    def test_microchip_con_mas_digitos_es_rechazado(self):
        with self.assertRaises(ErrorAtenciones):
            _validar_microchip("1234567890123456")

    def test_microchip_con_letras_es_rechazado(self):
        with self.assertRaises(ErrorAtenciones):
            _validar_microchip("12345678901234A")

    def test_microchip_vacio_es_rechazado(self):
        with self.assertRaises(ErrorAtenciones):
            _validar_microchip("")


class ValidacionIdentificadoresTests(SimpleTestCase):

    def test_id_valido_se_convierte_a_objectid(self):
        resultado = _validar_id(str(ObjectId()))

        self.assertIsInstance(resultado, ObjectId)

    def test_id_invalido_es_rechazado(self):
        with self.assertRaises(ErrorAtenciones):
            _validar_id("identificador-invalido")


class RegistroAtencionTests(SimpleTestCase):

    def test_perfil_no_veterinario_es_rechazado(self):
        with self.assertRaises(ErrorAtenciones):
            registrar_atencion(
                inscripcion_id=str(ObjectId()),
                usuario={"rut": "12345678-9"},
                perfil="funcionario",
                microchip=None
            )


class CierreOperativoTests(SimpleTestCase):

    def preparar_cierre(self, fecha=None, cerrado=False):
        operativo_id = str(ObjectId())

        operativo = {
            "_id": ObjectId(operativo_id),
            "fechaHora": fecha or datetime.now(timezone.utc)
                - timedelta(hours=1),
            "tipoOperativo": "esterilizacion",
            "cerrado": cerrado
        }

        operativos = MagicMock()
        inscripciones = MagicMock()
        atenciones = MagicMock()

        operativos.find_one.return_value = operativo

        return operativo_id, operativo, operativos, inscripciones, atenciones

    def test_perfil_no_veterinario_es_rechazado(self):
        with self.assertRaises(ErrorAtenciones):
            cerrar_operativo(
                str(ObjectId()),
                {"rut": "12345678-9"},
                "funcionario"
            )

    @patch("atenciones.services._coleccion")
    def test_operativo_futuro_no_se_puede_cerrar(self, mock_coleccion):
        futuro = datetime.now(timezone.utc) + timedelta(days=1)

        operativo_id, _, operativos, _, _ = self.preparar_cierre(
            fecha=futuro
        )

        mock_coleccion.side_effect = [
            operativos,
            MagicMock(),
            MagicMock()
        ]

        with self.assertRaises(ErrorAtenciones) as contexto:
            cerrar_operativo(
                operativo_id,
                {"rut": "12345678-9"},
                "veterinario"
            )

        self.assertEqual(
            contexto.exception.codigo,
            "OPERATIVO_FUTURO"
        )

    @patch("atenciones.services._coleccion")
    def test_operativo_ya_cerrado_es_rechazado(self, mock_coleccion):
        operativo_id, _, operativos, _, _ = self.preparar_cierre(
            cerrado=True
        )

        mock_coleccion.side_effect = [
            operativos,
            MagicMock(),
            MagicMock()
        ]

        with self.assertRaises(ErrorAtenciones) as contexto:
            cerrar_operativo(
                operativo_id,
                {"rut": "12345678-9"},
                "veterinario"
            )

        self.assertEqual(
            contexto.exception.codigo,
            "OPERATIVO_CERRADO"
        )

    @patch("atenciones.services._coleccion")
    def test_cierre_exitoso_sin_inscripciones_pendientes(
        self, mock_coleccion
    ):
        operativo_id, _, operativos, inscripciones, atenciones = (
            self.preparar_cierre()
        )

        resultado_bloqueo = MagicMock()
        resultado_bloqueo.modified_count = 1

        resultado_final = MagicMock()
        resultado_final.modified_count = 1

        operativos.update_one.side_effect = [
            resultado_bloqueo,
            resultado_final
        ]

        inscripciones.find.return_value = []

        mock_coleccion.side_effect = [
            operativos,
            inscripciones,
            atenciones
        ]

        resultado = cerrar_operativo(
            operativo_id,
            {"rut": "12345678-9"},
            "veterinario"
        )

        self.assertTrue(resultado["cerrado"])
        self.assertEqual(
            resultado["inasistenciasRegistradas"],
            0
        )

    @patch("atenciones.services._coleccion")
    def test_cierre_registra_una_inasistencia(
        self, mock_coleccion
    ):
        operativo_id, operativo, operativos, inscripciones, atenciones = (
            self.preparar_cierre()
        )

        inscripcion = {
            "_id": ObjectId(),
            "animalId": "animal-123",
            "rutSolicitante": "12345678-9"
        }

        inscripciones.find.return_value = [inscripcion]

        resultado_bloqueo = MagicMock()
        resultado_bloqueo.modified_count = 1

        resultado_final = MagicMock()
        resultado_final.modified_count = 1

        operativos.update_one.side_effect = [
            resultado_bloqueo,
            resultado_final
        ]

        atenciones.find_one.return_value = None

        resultado_insert = MagicMock()
        resultado_insert.inserted_id = ObjectId()
        atenciones.insert_one.return_value = resultado_insert

        resultado_inscripcion = MagicMock()
        resultado_inscripcion.modified_count = 1
        inscripciones.update_one.return_value = resultado_inscripcion

        mock_coleccion.side_effect = [
            operativos,
            inscripciones,
            atenciones
        ]

        resultado = cerrar_operativo(
            operativo_id,
            {"rut": "12345678-9"},
            "veterinario"
        )

        self.assertEqual(
            resultado["inasistenciasRegistradas"],
            1
        )
        self.assertTrue(resultado["cerrado"])
        atenciones.insert_one.assert_called_once()
