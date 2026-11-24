from django.test import SimpleTestCase
from unittest.mock import patch, MagicMock

from bson import ObjectId

from atenciones.services import (
    ErrorAtenciones,
    _validar_microchip,
    _validar_id,
    registrar_atencion,
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
