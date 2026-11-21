
from datetime import timezone as datetime_timezone

from django.shortcuts import render, redirect
from django.contrib import messages
from django.utils import timezone
from pymongo.errors import PyMongoError

from .forms import OperativoForm
from .services import guardar_operativo

from common.nucleo_client import obtener_sedes, obtener_especies


def crear_operativo(request):

    error = None

    try:
        sedes = obtener_sedes()
        especies = obtener_especies()

    except (RuntimeError, ValueError):
        sedes = []
        especies = []
        error = "No fue posible cargar los catálogos. Intente nuevamente."

    if request.method == "POST":

        formulario = OperativoForm(
            request.POST,
            sedes=sedes,
            especies=especies
        )

        if formulario.is_valid() and error is None:

            fecha_hora = formulario.cleaned_data["fecha_hora"]

            if timezone.is_naive(fecha_hora):
                fecha_hora = timezone.make_aware(
                    fecha_hora,
                    timezone.get_current_timezone()
                )

            fecha_hora_utc = fecha_hora.astimezone(datetime_timezone.utc)

            cupos_por_especie = []

            for especie in especies:

                cantidad = formulario.cleaned_data[
                    f"cupos_{especie['id']}"
                ]

                cupos_por_especie.append({
                    "especieId": especie["id"],
                    "total": cantidad,
                    "disponibles": cantidad
                })

            datos_operativo = {
                "tipoOperativo": formulario.cleaned_data["tipo_operativo"],
                "fechaHora": fecha_hora_utc,
                "sedeId": formulario.cleaned_data["sede_id"],
                "cuposPorEspecie": cupos_por_especie
            }

            try:
                guardar_operativo(datos_operativo)

            except (RuntimeError, PyMongoError):
                error = "No fue posible guardar el operativo. Intente nuevamente."

            else:
                messages.success(
                    request,
                    "¡Operativo registrado correctamente!"
                )

                return redirect("crear_operativo")

    else:
        formulario = OperativoForm(
            sedes=sedes,
            especies=especies
        )

    return render(
        request,
        "operativos/crear.html",
        {
            "formulario": formulario,
            "error": error
        }
    )
