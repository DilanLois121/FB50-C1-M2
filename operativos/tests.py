from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse


class LoginPageTests(TestCase):
    def test_vecino_y_comunitario_son_enviados_a_mis_inscripciones(self):
        for perfil, rut in (
            ("vecino", "12345678-9"),
            ("comunitario", "98765432-1"),
        ):
            with self.subTest(perfil=perfil):
                with (
                    patch(
                        "operativos.views.iniciar_sesion_nucleo",
                        return_value="token-prueba",
                    ),
                    patch(
                        "operativos.views.validar_sesion_nucleo",
                        return_value={"rut": rut, "perfil": perfil},
                    ),
                ):
                    respuesta = self.client.post(
                        reverse("iniciar_sesion"),
                        {"rut": rut, "clave": "clave-prueba"},
                    )

                self.assertEqual(respuesta.status_code, 302)
                self.assertEqual(
                    respuesta.url,
                    reverse("mis_inscripciones"),
                )
                self.assertEqual(
                    self.client.session["token_nucleo"],
                    "token-prueba",
                )
                self.assertEqual(
                    self.client.session["rut_usuario"],
                    rut,
                )
                self.assertEqual(
                    self.client.session["perfil_usuario"],
                    perfil,
                )

    def test_funcionario_conserva_su_destino_actual(self):
        with (
            patch(
                "operativos.views.iniciar_sesion_nucleo",
                return_value="token-prueba",
            ),
            patch(
                "operativos.views.validar_sesion_nucleo",
                return_value={
                    "rut": "12345678-9",
                    "perfil": " Funcionario ",
                },
            ),
        ):
            respuesta = self.client.post(
                reverse("iniciar_sesion"),
                {"rut": "12345678-9", "clave": "clave-prueba"},
            )

        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(respuesta.url, reverse("crear_operativo"))
        self.assertEqual(
            self.client.session["perfil_usuario"],
            "funcionario",
        )
