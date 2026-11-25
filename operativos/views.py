
from datetime import timezone as datetime_timezone

from django.shortcuts import render, redirect
from django.contrib import messages
from django.utils import timezone
from pymongo.errors import PyMongoError

from .forms import OperativoForm
from .services import guardar_operativo

from common.nucleo_client import obtener_sedes, obtener_especies, iniciar_sesion_nucleo, validar_sesion_nucleo

from django.views.decorators.http import require_POST


def iniciar_sesion(request):

    if request.method == "POST":

        rut = request.POST.get("rut", "").strip()
        clave = request.POST.get("clave", "")

        if not rut or not clave:
            messages.error(request, "Debe ingresar RUT y clave.")

        else:
            try:
                token = iniciar_sesion_nucleo(rut, clave)

                if token is None:
                    messages.error(request, "RUT o clave incorrectos.")

                else:
                    usuario = validar_sesion_nucleo(token)

                    if usuario is None:
                        messages.error(request, "No fue posible validar la sesión.")

                    elif not isinstance(usuario, dict) or (
                        not isinstance(usuario.get("rut"), str)
                        or not isinstance(usuario.get("perfil"), str)
                    ):
                        messages.error(
                            request,
                            "No fue posible validar la sesión."
                        )

                    else:
                        rut_usuario = usuario["rut"].strip()
                        perfil = usuario["perfil"].strip().lower()
                        perfiles_permitidos = {
                            "funcionario",
                            "jefatura",
                            "vecino",
                            "comunitario",
                        }

                        if not rut_usuario or perfil not in perfiles_permitidos:
                            messages.error(
                                request,
                                "No tiene permisos para acceder a esta sección."
                            )
                        else:
                            request.session.cycle_key()
                            request.session["token_nucleo"] = token
                            request.session["rut_usuario"] = rut_usuario
                            request.session["perfil_usuario"] = perfil

                            if perfil in {"vecino", "comunitario"}:
                                return redirect("mis_inscripciones")
                            return redirect("crear_operativo")

            except (RuntimeError, ValueError):
                messages.error(
                    request,
                    "No fue posible comunicarse con el núcleo. Intente nuevamente."
                )

    return render(request, "operativos/login.html")

@require_POST
def cerrar_sesion(request):

    request.session.flush()

    return redirect("iniciar_sesion")



def crear_operativo(request):


    token = request.session.get("token_nucleo")

    if not token:
        return redirect("iniciar_sesion")

    try:
        usuario = validar_sesion_nucleo(token)

    except RuntimeError:
        messages.error(
            request,
            "No fue posible validar la sesión. Intente nuevamente."
        )
        return redirect("iniciar_sesion")

    if usuario is None:
        request.session.flush()
        messages.warning(
            request,
            "Su sesión ha expirado. Inicie sesión nuevamente."
        )
        return redirect("iniciar_sesion")

    if usuario["perfil"] not in ("funcionario", "jefatura"):
        request.session.flush()
        messages.error(
            request,
            "No tiene permisos para crear operativos."
        )
        return redirect("iniciar_sesion")


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
