from dataclasses import dataclass
from datetime import date

from django.core.exceptions import ValidationError

ARCHIVED_STAGE_CODE = "9_ARQUIVADO"
ARCHIVED_STAGE_DEFAULT_LABEL = "Geladeira"


@dataclass(frozen=True)
class KanbanStageLabel:
    codigo_interno: str
    label_padrao: str
    label_exibido: str


def get_kanban_stage_defaults() -> tuple[KanbanStageLabel, ...]:
    from .models import ProjetoKanban

    labels = dict(ProjetoKanban.ETAPA_CHOICES)
    labels[ARCHIVED_STAGE_CODE] = ARCHIVED_STAGE_DEFAULT_LABEL
    return tuple(
        KanbanStageLabel(
            codigo_interno=code,
            label_padrao=labels[code],
            label_exibido=labels[code],
        )
        for code, _label in ProjetoKanban.ETAPA_CHOICES
    )


def get_kanban_stage_labels() -> tuple[KanbanStageLabel, ...]:
    """Resolve every legacy stage once, including its safe default fallback."""
    from .models import ConfiguracaoEtapaKanban

    defaults = get_kanban_stage_defaults()
    configurations = list(
        ConfiguracaoEtapaKanban.objects.filter(
            codigo_interno__in=[stage.codigo_interno for stage in defaults],
        ).values_list("codigo_interno", "label_personalizado", "posicao_visual")
    )
    overrides = {code: label for code, label, _position in configurations}
    flow_defaults = [stage for stage in defaults if stage.codigo_interno != ARCHIVED_STAGE_CODE]
    positions = {code: position for code, _label, position in configurations if code != ARCHIVED_STAGE_CODE}
    # Only a complete permutation is trusted; legacy/partial/corrupt data uses defaults.
    if (
        set(positions) == {stage.codigo_interno for stage in flow_defaults}
        and set(positions.values()) == set(range(len(flow_defaults)))
    ):
        defaults = tuple(sorted(flow_defaults, key=lambda stage: positions[stage.codigo_interno])) + tuple(
            stage for stage in defaults if stage.codigo_interno == ARCHIVED_STAGE_CODE
        )
    return tuple(
        KanbanStageLabel(
            codigo_interno=stage.codigo_interno,
            label_padrao=stage.label_padrao,
            label_exibido=(overrides.get(stage.codigo_interno) or stage.label_padrao),
        )
        for stage in defaults
    )


def get_kanban_stage_label(codigo_interno: str) -> KanbanStageLabel:
    """Return one resolved stage label, rejecting unknown technical identities."""
    for stage in get_kanban_stage_labels():
        if stage.codigo_interno == codigo_interno:
            return stage
    raise ValidationError("Etapa legada inválida.")


def _orcamento_vencido(
    *,
    etapa: str,
    data_limite_orcamento: date | None,
    data_referencia: date,
) -> bool:
    return (
        etapa == "2_ORCAMENTO"
        and data_limite_orcamento is not None
        and data_limite_orcamento <= data_referencia
    )


def orcamentos_vencidos(*, data_referencia: date):
    """Retorna orçamentos vencidos na data de referência informada."""
    from .models import ProjetoKanban

    return ProjetoKanban.objects.filter(
        etapa="2_ORCAMENTO",
        data_limite_orcamento__lte=data_referencia,
    )
