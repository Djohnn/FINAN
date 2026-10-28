from typing import ClassVar

from django.db import migrations, models
from django.db.migrations.operations.base import Operation


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [("kanban_projetos", "0002_configuracaoetapakanban")]

    operations: ClassVar[list[Operation]] = [
        migrations.AddField(
            model_name="configuracaoetapakanban",
            name="posicao_visual",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
    ]
