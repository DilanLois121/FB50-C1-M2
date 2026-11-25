import os
import unittest
from unittest.mock import patch, MagicMock

# Evitar intento de DNS a MongoDB en pruebas
with patch('pymongo.MongoClient', MagicMock()):
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    import django
    django.setup()

    from atenciones.tests import RegistroCuidadoTests
    from atenciones.cuidados_tests import ApiRegistrarCuidadoTests, ApiAgregarNotaCuidadoTests

    loader = unittest.TestLoader()
    suite = unittest.TestSuite([
        loader.loadTestsFromTestCase(RegistroCuidadoTests),
        loader.loadTestsFromTestCase(ApiRegistrarCuidadoTests),
        loader.loadTestsFromTestCase(ApiAgregarNotaCuidadoTests),
    ])

    print("\n" + "="*65)
    print("EJECUTANDO PRUEBAS DE HU-05 (TAREA 2: INMUTABILIDAD Y NOTAS)")
    print("="*65 + "\n")
    resultado = unittest.TextTestRunner(verbosity=2).run(suite)
    print("\n" + "="*65)
    if resultado.wasSuccessful():
        print("RESULTADO: TODAS LAS PRUEBAS APROBADAS (OK)")
    else:
        print("RESULTADO: HUBO FALLOS EN LAS PRUEBAS")
    print("="*65 + "\n")
