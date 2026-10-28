from typing import ClassVar

from django.db import migrations, models
from django.db.migrations.operations.base import Operation


class Migration(migrations.Migration):

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("kanban_projetos", "0001_initial"),
    ]

    operations: ClassVar[list[Operation]] = [
        migrations.CreateModel(
            name="ConfiguracaoEtapaKanban",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "codigo_interno",
                    models.CharField(
                        max_length=20,
                        unique=True,
                        verbose_name="Código interno da etapa",
                    ),
                ),
                (
                    "label_personalizado",
                    models.CharField(
                        blank=True,
                        default="",
                        max_length=100,
                        verbose_name="Nome visível personalizado",
                    ),
                ),
                ("atualizado_em", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Configuração de etapa do Kanban",
                "verbose_name_plural": "Configurações de etapas do Kanban",
                "ordering": ["codigo_interno"],
            },
        ),
    ]
