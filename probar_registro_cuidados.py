import os
import unittest
from unittest.mock import patch, MagicMock

# Evitar conexión real a MongoDB durante pruebas
with patch('pymongo.MongoClient', MagicMock()):
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    import django
    django.setup()

    from atenciones.tests import RegistroCuidadoTests
    from atenciones.cuidados_tests import ApiRegistrarCuidadoTests

    loader = unittest.TestLoader()
    suite = unittest.TestSuite([
        loader.loadTestsFromTestCase(RegistroCuidadoTests),
        loader.loadTestsFromTestCase(ApiRegistrarCuidadoTests)
    ])

    print("\n" + "="*60)
    print("EJECUTANDO PRUEBAS DE HU-05 (REGISTRO DE CUIDADOS)")
    print("="*60 + "\n")
    resultado = unittest.TextTestRunner(verbosity=2).run(suite)
    print("\n" + "="*60)
    if resultado.wasSuccessful():
        print("RESULTADO: TODAS LAS PRUEBAS APROBADAS (OK)")
    else:
        print("RESULTADO: HUBO FALLOS EN LAS PRUEBAS")
    print("="*60 + "\n")
