from django.test import SimpleTestCase
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from pymongo.errors import PyMongoError

from atenciones.services import (
    ErrorAtenciones,
    _validar_microchip,
    _validar_id,
    registrar_atencion,
    cerrar_operativo,
)
from atenciones.cuidados_services import registrar_cuidado
from atenciones.cuidados_tests import (
    ApiAgregarNotaCuidadoTests,
    ApiObtenerCuidadoTests,
    ApiRegistrarCuidadoTests,
)


class RegistroCuidadoTests(SimpleTestCase):

    @patch("atenciones.cuidados_services.db")
    def test_inscripcion_inexistente_devuelve_error_404(self, mock_db):
        inscripcion_id = ObjectId()
        mock_db["inscripciones"].find_one.return_value = None

        with self.assertRaises(ErrorAtenciones) as contexto:
            registrar_cuidado(
                str(inscripcion_id),
                {"rut": "12345678-9"},
                {}
            )

        self.assertEqual(
            contexto.exception.codigo,
            "INSCRIPCION_NO_ENCONTRADA"
        )
        self.assertEqual(contexto.exception.estado_http, 404)

    @patch("atenciones.cuidados_services.db")
    def test_inscripcion_no_atendida_devuelve_error_400(self, mock_db):
        inscripcion_id = ObjectId()
        mock_db["inscripciones"].find_one.return_value = {
            "_id": inscripcion_id,
            "estado": "confirmada"
        }

        with self.assertRaises(ErrorAtenciones) as contexto:
            registrar_cuidado(
                str(inscripcion_id),
                {"rut": "12345678-9"},
                {}
            )

        self.assertEqual(
            contexto.exception.codigo,
            "INSCRIPCION_NO_ATENDIDA"
        )
        self.assertEqual(contexto.exception.estado_http, 400)
        mock_db["cuidados"].insert_one.assert_not_called()

    @patch("atenciones.cuidados_services.db")
    def test_registra_cuidado_para_inscripcion_atendida(self, mock_db):
        inscripcion_id = ObjectId()
        cuidado_id = ObjectId()
        mock_db["inscripciones"].find_one.return_value = {
            "_id": inscripcion_id,
            "estado": "atendida"
        }
        mock_db["cuidados"].insert_one.return_value.inserted_id = cuidado_id
        datos = {
            "indicaciones": "Reposo",
            "medicamentos": ["Analgesico"],
            "detalle_quirurgico": "Sin cirugía"
        }

        resultado = registrar_cuidado(
            str(inscripcion_id),
            {"rut": "12345678-9"},
            datos
        )

        mock_db["inscripciones"].find_one.assert_called_once_with(
            {"_id": inscripcion_id}
        )
        documento = mock_db["cuidados"].insert_one.call_args.args[0]
        self.assertEqual(documento["inscripcion_id"], inscripcion_id)
        self.assertEqual(documento["veterinario_rut"], "12345678-9")
        self.assertEqual(documento["indicaciones"], "Reposo")
        self.assertEqual(documento["medicamentos"], ["Analgesico"])
        self.assertEqual(documento["detalle_quirurgico"], "Sin cirugía")
        self.assertEqual(documento["notas_complementarias"], [])
        self.assertEqual(resultado["_id"], cuidado_id)
        fecha_registro = datetime.fromisoformat(
            documento["fecha_registro"].replace("Z", "+00:00")
        )
        self.assertEqual(fecha_registro.utcoffset(), timedelta(0))


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

    @patch("atenciones.services._coleccion")
    def test_microchip_duplicado_es_rechazado(self, mock_coleccion):
        inscripcion_id = ObjectId()
        operativo_id = ObjectId()

        inscripcion = {
            "_id": inscripcion_id,
            "operativoId": str(operativo_id),
            "animalId": "animal-123",
            "estado": "confirmada"
        }

        operativo = {
            "_id": operativo_id,
            "tipoOperativo": "chipeo"
        }

        inscripciones = MagicMock()
        operativos = MagicMock()
        atenciones = MagicMock()

        inscripciones.find_one.return_value = inscripcion
        operativos.find_one.return_value = operativo

        # Simular que el microchip ya existe.
        atenciones.find_one.return_value = {
            "_id": ObjectId(),
            "microchip": "123456789012345"
        }

        # Simular las llamadas a las colecciones.
        mock_coleccion.side_effect = [
            inscripciones,
            operativos,
            atenciones,
            atenciones
        ]

        with self.assertRaises(ErrorAtenciones) as contexto:
            registrar_atencion(
                inscripcion_id=str(inscripcion_id),
                usuario={"rut": "12345678-9"},
                perfil="veterinario",
                microchip="123456789012345"
            )

        self.assertEqual(
            contexto.exception.codigo,
            "MICROCHIP_DUPLICADO"
        )

        # No debe modificar la inscripción.
        inscripciones.update_one.assert_not_called()

    @patch("atenciones.services._coleccion")
    def test_registro_atencion_exitoso(self, mock_coleccion):
        inscripcion_id = ObjectId()
        operativo_id = ObjectId()

        inscripcion = {
            "_id": inscripcion_id,
            "operativoId": str(operativo_id),
            "animalId": "animal-123",
            "rutSolicitante": "12345678-9",
            "estado": "confirmada"
        }

        operativo = {
            "_id": operativo_id,
            "tipoOperativo": "esterilizacion"
        }

        inscripciones = MagicMock()
        operativos = MagicMock()
        atenciones = MagicMock()

        inscripciones.find_one.return_value = inscripcion
        operativos.find_one.return_value = operativo

        resultado_actualizacion = MagicMock()
        resultado_actualizacion.modified_count = 1
        inscripciones.update_one.return_value = resultado_actualizacion

        resultado_insercion = MagicMock()
        resultado_insercion.inserted_id = ObjectId()
        atenciones.insert_one.return_value = resultado_insercion

        mock_coleccion.side_effect = lambda nombre: {
            "inscripciones": inscripciones,
            "operativos": operativos,
            "atenciones": atenciones
        }[nombre]

        resultado = registrar_atencion(
            inscripcion_id=str(inscripcion_id),
            usuario={"rut": "12345678-9"},
            perfil="veterinario",
            microchip=None
        )

        # Verificar que se actualizó la inscripción.
        inscripciones.update_one.assert_called_once()

        # Verificar que se guardó la atención.
        atenciones.insert_one.assert_called_once()

        # Verificar que el resultado contiene la atención.
        self.assertIsNotNone(resultado)

    @patch("atenciones.services._coleccion")
    def test_falla_guardado_revierte_inscripcion(self, mock_coleccion):
        inscripcion_id = ObjectId()
        operativo_id = ObjectId()

        inscripcion = {
            "_id": inscripcion_id,
            "operativoId": str(operativo_id),
            "animalId": "animal-123",
            "rutSolicitante": "12345678-9",
            "estado": "confirmada"
        }

        operativo = {
            "_id": operativo_id,
            "tipoOperativo": "esterilizacion"
        }

        inscripciones = MagicMock()
        operativos = MagicMock()
        atenciones = MagicMock()

        inscripciones.find_one.return_value = inscripcion
        operativos.find_one.return_value = operativo

        resultado_actualizacion = MagicMock()
        resultado_actualizacion.modified_count = 1
        inscripciones.update_one.return_value = resultado_actualizacion

        # Simular un fallo al guardar la atención.
        atenciones.insert_one.side_effect = PyMongoError(
            "Error simulado de MongoDB"
        )

        mock_coleccion.side_effect = lambda nombre: {
            "inscripciones": inscripciones,
            "operativos": operativos,
            "atenciones": atenciones
        }[nombre]

        with self.assertRaises(ErrorAtenciones):
            registrar_atencion(
                inscripcion_id=str(inscripcion_id),
                usuario={"rut": "12345678-9"},
                perfil="veterinario",
                microchip=None
            )

        # Comprobar que se intentó actualizar la inscripción.
        self.assertGreaterEqual(
            inscripciones.update_one.call_count,
            2
        )

        # Comprobar que se intentó guardar la atención.
        atenciones.insert_one.assert_called_once()

    @patch("atenciones.services._coleccion")
    def test_registro_chipeo_exitoso_guarda_microchip(
        self, mock_coleccion
    ):
        inscripcion_id = ObjectId()
        operativo_id = ObjectId()

        microchip = "123456789012345"

        inscripcion = {
            "_id": inscripcion_id,
            "operativoId": str(operativo_id),
            "animalId": "animal-123",
            "rutSolicitante": "12345678-9",
            "estado": "confirmada"
        }

        operativo = {
            "_id": operativo_id,
            "tipoOperativo": "chipeo"
        }

        inscripciones = MagicMock()
        operativos = MagicMock()
        atenciones = MagicMock()

        inscripciones.find_one.return_value = inscripcion
        operativos.find_one.return_value = operativo

        resultado_actualizacion = MagicMock()
        resultado_actualizacion.modified_count = 1
        inscripciones.update_one.return_value = resultado_actualizacion

        resultado_insercion = MagicMock()
        resultado_insercion.inserted_id = ObjectId()
        atenciones.insert_one.return_value = resultado_insercion

        # Simular que el microchip no existe previamente.
        atenciones.find_one.return_value = None

        mock_coleccion.side_effect = lambda nombre: {
            "inscripciones": inscripciones,
            "operativos": operativos,
            "atenciones": atenciones
        }[nombre]

        resultado = registrar_atencion(
            inscripcion_id=str(inscripcion_id),
            usuario={"rut": "12345678-9"},
            perfil="veterinario",
            microchip=microchip
        )

        # Verificar que se actualizó la inscripción.
        inscripciones.update_one.assert_called_once()

        # Verificar que se guardó la atención.
        atenciones.insert_one.assert_called_once()

        # Obtener el documento guardado simulado.
        documento_guardado = atenciones.insert_one.call_args[0][0]

        # Comprobar que el microchip quedó guardado.
        self.assertEqual(
            documento_guardado["microchip"],
            microchip
        )

        # Comprobar que el registro corresponde a chipeo.
        self.assertEqual(
            documento_guardado["tipoOperativo"],
            "chipeo"
        )

        self.assertIsNotNone(resultado)


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