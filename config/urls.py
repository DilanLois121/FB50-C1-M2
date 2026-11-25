from django.contrib import admin
from django.urls import include, path
from inscripciones import views as inscripciones_views
from operativos import views
from operativos import api_views


urlpatterns = [
    path('admin/', admin.site.urls),
    path('login/', views.iniciar_sesion, name='iniciar_sesion'),
    path('cerrar-sesion/', views.cerrar_sesion, name='cerrar_sesion'),
    path(
        'mis-inscripciones/',
        inscripciones_views.pagina_mis_inscripciones,
        name='mis_inscripciones',
    ),
    path('operativos/crear/', views.crear_operativo, name='crear_operativo'),
    path('api/operativos', api_views.crear_operativo_api, name='api_crear_operativo'),
    path('api/operativos/', include('inscripciones.urls')),
    path('api/operativos/', include('atenciones.urls')),
    path('api/operativos/<str:id_operativo>', api_views.actualizar_operativo_api, name='api_actualizar_operativo'),
]
