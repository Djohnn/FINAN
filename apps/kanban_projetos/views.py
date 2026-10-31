from datetime import date
from typing import NotRequired, TypedDict, cast

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.functional import SimpleLazyObject
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST

from .models import ProjetoKanban
from .selectors import (
    ARCHIVED_STAGE_CODE,
    KanbanStageLabel,
    get_kanban_stage_defaults,
    get_kanban_stage_labels,
)
from .services import salvar_label_etapa_service, salvar_ordem_etapas_service


class _StageLabelResolver:
    """Lê todos os overrides no primeiro uso e reutiliza o resultado no request."""

    def __init__(self, defaults: tuple[KanbanStageLabel, ...]):
        self._defaults = {stage.codigo_interno: stage for stage in defaults}
        self._resolved: dict[str, KanbanStageLabel] | None = None

    def resolve(self, codigo_interno: str) -> KanbanStageLabel:
        if self._resolved is None:
            self._resolved = {
                stage.codigo_interno: stage
                for stage in get_kanban_stage_labels()
            }
        return self._resolved.get(codigo_interno, self._defaults[codigo_interno])

    def order_columns(self, columns):
        self.resolve(ARCHIVED_STAGE_CODE)
        by_code = {column["code"]: column for column in columns}
        ordered = [by_code[code] for code in self._resolved if code in by_code]
        codes = [column["code"] for column in ordered]
        for index, column in enumerate(ordered):
            for direction, offset in (("order_before", -1), ("order_after", 1)):
                target = index + offset
                permutation = codes.copy()
                if 0 <= target < len(codes):
                    permutation[index], permutation[target] = permutation[target], permutation[index]
                    column[direction] = permutation
                else:
                    column[direction] = []
        return tuple(ordered)


class _StageLabelProxy:
    """Valor lazy para não adicionar query quando a resposta é somente montada."""

    def __init__(self, resolver: _StageLabelResolver, default: KanbanStageLabel):
        self._resolver = resolver
        self._default = default

    @property
    def codigo_interno(self) -> str:
        return self._default.codigo_interno

    @property
    def label_padrao(self) -> str:
        return self._default.label_padrao

    @property
    def label_exibido(self) -> str:
        return self._resolver.resolve(self.codigo_interno).label_exibido

    def __str__(self) -> str:
        return self.label_exibido


class _StageEditorContext(TypedDict, total=False):
    code: str
    value: str
    error: str


class _KanbanCardContext(TypedDict):
    project: ProjetoKanban
    is_overdue: bool
    stage_label: _StageLabelProxy


class _KanbanColumnContext(TypedDict):
    code: str
    label: _StageLabelProxy
    default_label: str
    order_before: NotRequired[list[str]]
    order_after: NotRequired[list[str]]
    projects: tuple[_KanbanCardContext, ...]


class _KanbanContext(TypedDict):
    columns: tuple[_KanbanColumnContext, ...]
    archived_column: _KanbanColumnContext
    column_counts: dict[str, int]
    archived_count: int
    data_referencia: date
    stage_editor: _StageEditorContext | None
    orcamentos_atrasados_count: int


def _card_context(
    project: ProjetoKanban,
    stage_label: _StageLabelProxy,
) -> _KanbanCardContext:
    return {
        "project": project,
        "is_overdue": project.is_orcamento_vencido,
        "stage_label": stage_label,
    }


def _kanban_context(
    *,
    stage_editor: _StageEditorContext | None = None,
) -> _KanbanContext:
    today = timezone.localdate()
    stage_defaults = get_kanban_stage_defaults()
    stage_resolver = _StageLabelResolver(stage_defaults)
    stage_by_code = {
        stage.codigo_interno: _StageLabelProxy(stage_resolver, stage)
        for stage in stage_defaults
    }
    projects = list(
        ProjetoKanban.objects
        .select_related("cliente")
        .order_by("etapa", "-atualizado_em", "-pk")
    )
    projects_by_stage: dict[str, list[_KanbanCardContext]] = {
        stage.codigo_interno: []
        for stage in stage_defaults
        if stage.codigo_interno != ARCHIVED_STAGE_CODE
    }
    archived_projects: list[_KanbanCardContext] = []
    for project in projects:
        card = _card_context(project, stage_by_code[project.etapa])
        if project.etapa == ARCHIVED_STAGE_CODE:
            archived_projects.append(card)
        elif project.etapa in projects_by_stage:
            projects_by_stage[project.etapa].append(card)

    columns: tuple[_KanbanColumnContext, ...] = tuple(
        {
            "code": stage.codigo_interno,
            "label": stage_by_code[stage.codigo_interno],
            "default_label": stage.label_padrao,
            "projects": tuple(projects_by_stage[stage.codigo_interno]),
        }
        for stage in stage_defaults
        if stage.codigo_interno != ARCHIVED_STAGE_CODE
    )
    archived_stage = stage_by_code[ARCHIVED_STAGE_CODE]
    archived_column: _KanbanColumnContext = {
        "code": archived_stage.codigo_interno,
        "label": archived_stage,
        "default_label": archived_stage.label_padrao,
        "projects": tuple(archived_projects),
    }
    return {
        "columns": cast(
            tuple[_KanbanColumnContext, ...],
            SimpleLazyObject(lambda: stage_resolver.order_columns(columns)),
        ),
        "archived_column": archived_column,
        "column_counts": {
            column["code"]: len(column["projects"]) for column in columns
        },
        "archived_count": len(archived_column["projects"]),
        "data_referencia": today,
        "stage_editor": stage_editor,
        "orcamentos_atrasados_count": sum(
            project["is_overdue"]
            for column in columns
            for project in column["projects"]
        ),
    }


@require_GET
def kanban_readonly_view(request):
    """Renderiza a consulta intermediária do Kanban legado sem operações de escrita."""
    return render(
        request,
        "kanban_projetos/kanban_readonly.html",
        _kanban_context(),
    )


@require_POST
@csrf_protect
def stage_label_update(request: HttpRequest, codigo_interno: str) -> HttpResponse:
    """Atualiza somente a configuração visual de uma etapa legada."""
    label = request.POST.get("label")
    restore_default = request.POST.get("reset") == "1"
    try:
        salvar_label_etapa_service(
            codigo_interno=codigo_interno,
            label=label,
            restaurar_padrao=restore_default,
        )
    except ValidationError as exc:
        messages.error(request, "Não foi possível salvar o nome da etapa.")
        error_message = " ".join(exc.messages)
        return render(
            request,
            "kanban_projetos/kanban_readonly.html",
            _kanban_context(stage_editor={
                "code": codigo_interno,
                "value": label or "",
                "error": error_message,
            }),
            status=400,
        )

    messages.success(request, "Nome visível da etapa salvo.")
    return redirect("kanban_projetos:kanban_readonly")


@require_POST
@csrf_protect
def stage_order_update(request: HttpRequest) -> HttpResponse:
    """Change only visual order; accept a complete server-validated permutation."""
    try:
        salvar_ordem_etapas_service(
            codigos=request.POST.getlist("ordem"),
            restaurar_padrao=request.POST.get("reset") == "1",
        )
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
        return render(request, "kanban_projetos/kanban_readonly.html", _kanban_context(), status=400)
    messages.success(request, "Ordem das etapas salva.")
    return redirect("kanban_projetos:kanban_readonly")
