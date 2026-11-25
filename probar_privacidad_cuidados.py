import os
import unittest
from unittest.mock import patch, MagicMock

# Evitar intento de DNS a MongoDB en pruebas
with patch('pymongo.MongoClient', MagicMock()):
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    import django
    django.setup()

    from atenciones.tests import RegistroCuidadoTests
    from atenciones.cuidados_tests import (
        ApiRegistrarCuidadoTests,
        ApiAgregarNotaCuidadoTests,
        ApiObtenerCuidadoTests,
    )

    loader = unittest.TestLoader()
    suite = unittest.TestSuite([
        loader.loadTestsFromTestCase(RegistroCuidadoTests),
        loader.loadTestsFromTestCase(ApiRegistrarCuidadoTests),
        loader.loadTestsFromTestCase(ApiAgregarNotaCuidadoTests),
        loader.loadTestsFromTestCase(ApiObtenerCuidadoTests),
    ])

    print("\n" + "="*68)
    print("EJECUTANDO PRUEBAS DE HU-05 (PRIVACIDAD Y DETALLE QUIRÚRGICO)")
    print("="*68 + "\n")
    resultado = unittest.TextTestRunner(verbosity=2).run(suite)
    print("\n" + "="*68)
    if resultado.wasSuccessful():
        print("RESULTADO: TODAS LAS PRUEBAS APROBADAS (OK)")
    else:
        print("RESULTADO: HUBO FALLOS EN LAS PRUEBAS")
    print("="*68 + "\n")
