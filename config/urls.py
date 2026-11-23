from django.contrib import admin
from django.urls import path
from operativos import views
from operativos import api_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('operativos/crear/', views.crear_operativo, name='crear_operativo'),
    path('api/operativos', api_views.crear_operativo_api, name='api_crear_operativo'),
    path('api/operativos/<str:id_operativo>', api_views.actualizar_operativo_api, name='api_actualizar_operativo'),
]
