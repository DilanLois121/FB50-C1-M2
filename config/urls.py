from django.contrib import admin
from django.urls import path
from operativos import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('operativos/crear/', views.crear_operativo, name='crear_operativo'),
]
