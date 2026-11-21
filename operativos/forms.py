from django import forms

class OperativoForm(forms.Form):

    tipo_operativo = forms.ChoiceField(
    label="Tipo de operativo",
    choices=[
        ("", "Seleccione el tipo de operativo"),
        ("esterilizacion", "Esterilización"),
        ("chipeo", "Chipeo"),
        ]
    )

    fecha_hora = forms.DateTimeField(
        label="Fecha y hora del operativo",
        widget=forms.DateTimeInput(
            attrs={"type": "datetime-local"},
            format="%Y-%m-%dT%H:%M"
        ),
        input_formats=["%Y-%m-%dT%H:%M"]
    )
    sede_id = forms.ChoiceField(
        label="Sede vecinal",
        choices=(),
    )
    def __init__(self, *args, sedes=None, especies=None, **kwargs):
        super().__init__(*args, **kwargs)

        opciones_sedes = [
            (sede["id"], sede["nombre"])
            for sede in (sedes or [])
        ]

        self.fields["sede_id"].choices = [
            ("", "Seleccione una sede")
        ] + opciones_sedes

        for especie in especies or []:
            self.fields[f"cupos_{especie['id']}"] = forms.IntegerField(
                label=f"Cupos para {especie['nombre']}",
                min_value=0,
                initial=0
            )