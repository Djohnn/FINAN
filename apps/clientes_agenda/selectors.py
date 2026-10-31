"""Immutable, read-only projections for the Customer 360 surfaces."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from django.db.models import Count, OuterRef, Q, Subquery

from apps.core_sistema.models import EventoSistema
from apps.financeiro.models import LancamentoFinanceiro
from apps.financeiro.selectors import RentabilidadeProjeto, rentabilidade_projetos
from apps.kanban_projetos.models import ProjetoKanban

from .models import AgendaContato, Cliente

HistoryState = Literal["DISPONIVEL", "INCONSISTENTE", "SEM_CONTRATO"]

_HISTORY_PAGE_SIZE = 50
_ZERO = Decimal("0.00")

_STAGE_LABELS = dict(ProjetoKanban.ETAPA_CHOICES)
_ARCHIVE_REASON_LABELS = {
    "PRECO_ALTO": "Achou caro",
    "ADIOU_OBRA": "Adiou obra",
    "FECHOU_CONCORRENTE": "Fechou com concorrente",
    "SEM_RETORNO": "Sem retorno",
    "OUTRO": "Outro",
}
_CONTACT_TYPE_LABELS = dict(AgendaContato.TIPO_CHOICES)
_SATISFACTION_LABELS = dict(AgendaContato.SATISFACAO_CHOICES)

_EVENT_TYPES = {
    "ORCAMENTO_APROVADO",
    "ORCAMENTO_ARQUIVADO",
    "ORCAMENTO_REATIVADO",
    "PROJETO_FINALIZADO",
    "CONTATO_CONCLUIDO",
    "LANCAMENTO_QUITADO",
    "PAGAMENTO_FUNCIONARIO_CRIADO",
}
_EVENT_LABELS = {
    "ORCAMENTO_APROVADO": "Orçamento aprovado",
    "ORCAMENTO_ARQUIVADO": "Orçamento arquivado",
    "ORCAMENTO_REATIVADO": "Orçamento reativado",
    "PROJETO_FINALIZADO": "Projeto finalizado",
    "CONTATO_CONCLUIDO": "Contato concluído",
    "LANCAMENTO_QUITADO": "Lançamento quitado",
    "PAGAMENTO_FUNCIONARIO_CRIADO": "Pagamento de funcionário criado",
}
_WARNING_LABELS = {
    "CONTRATO_DIVERGE_DO_LEDGER": "O contrato não fecha com os lançamentos comerciais.",
    "PENDENTE_COM_DATA_PAGAMENTO": "Há recebimento pendente com data de pagamento preenchida.",
    "VALOR_ZERO": "Há lançamento comercial com valor zero.",
    "ENTRADA_NAO_SERVICO_CLIENTE_EXCLUIDA": "Uma entrada não comercial foi excluída do resumo.",
    "CUSTO_FIXO_OFICINA_VINCULADO_EXCLUIDO": "Um custo fixo vinculado foi excluído da rentabilidade.",
    "SERVICO_CLIENTE_EM_SAIDA": "Uma saída marcada como serviço de cliente foi excluída.",
    "ETAPA_INVALIDA": "A etapa do projeto não pôde ser validada.",
    "VALOR_CONTRATADO_INVALIDO": "O valor contratado não pôde ser validado.",
    "PAGO_SEM_DATA_PAGAMENTO": "Há recebimento pago sem data de pagamento.",
    "STATUS_INVALIDO": "Há lançamento com status inválido.",
    "TIPO_INVALIDO": "Há lançamento com tipo inválido.",
    "CATEGORIA_INVALIDA": "Há lançamento com categoria inválida.",
    "VALOR_MONETARIO_INVALIDO": "Há lançamento com valor monetário inválido.",
    "PROJETO_SEM_RESULTADO": "O resultado financeiro do projeto não está disponível.",
}


class Cliente360NotFound(ValueError):
    """Raised when a requested customer cannot be resolved by primary key."""


class InvalidHistoryPage(ValueError):
    """Raised when a history continuation page is outside the input contract."""


@dataclass(frozen=True)
class FinanceiroProjetoCliente360:
    estado: HistoryState
    valor_contratado: Decimal | None
    valor_recebido: Decimal | None
    saldo_a_receber: Decimal | None
    warning_codes: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class ResumoFinanceiroCliente:
    estado: HistoryState
    total_contratado: Decimal | None
    total_recebido: Decimal | None
    saldo_a_receber: Decimal | None
    warning_codes: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class ProjetoCliente360:
    projeto_id: int
    titulo: str
    etapa: str
    etapa_label: str
    data_limite_orcamento: date | None
    data_inicio_producao: date | None
    data_entrega_prevista: date | None
    data_entrega_realizada: date | None
    arquivado: bool
    motivo_arquivamento: str
    motivo_arquivamento_label: str
    observacao_arquivamento: str
    financeiro: FinanceiroProjetoCliente360


@dataclass(frozen=True)
class ContatoCliente360:
    contato_id: int
    tipo: str
    tipo_label: str
    projeto_id: int | None
    projeto_titulo: str | None
    data_agendada: date
    realizado: bool
    nivel_satisfacao: str
    nivel_satisfacao_label: str
    feedback_cliente: str
    realizado_em: datetime | None


@dataclass(frozen=True)
class EventoCliente360:
    evento_id: int
    tipo: str
    tipo_label: str
    criado_em: datetime
    projeto_id: int | None
    projeto_titulo: str | None
    contato_id: int | None
    descricao: str


@dataclass(frozen=True)
class Cliente360:
    cliente_id: int
    nome: str
    whatsapp: str
    endereco: str
    observacoes: str
    criado_em: datetime
    projetos: tuple[ProjetoCliente360, ...]
    agenda_overdue_or_today: tuple[ContatoCliente360, ...]
    agenda_future: tuple[ContatoCliente360, ...]
    agenda_completed: tuple[ContatoCliente360, ...]
    eventos: tuple[EventoCliente360, ...]
    financeiro: ResumoFinanceiroCliente
    history_page: int
    history_has_more: bool
    history_next_page: int | None


@dataclass(frozen=True)
class ClienteIndexRow:
    cliente_id: int
    nome: str
    whatsapp: str
    projetos_count: int
    proximo_contato_data: date | None
    proximo_contato_tipo: str | None
    proximo_contato_tipo_label: str | None
    proximo_contato_atrasado_ou_hoje: bool


@dataclass(frozen=True)
class ClientesIndex:
    rows: tuple[ClienteIndexRow, ...]
    total_cadastrados: int
    clientes_com_contato_pendente: int
    query: str
    data_referencia: date


def _validate_reference_date(data_referencia: date) -> date:
    if type(data_referencia) is not date:
        raise ValueError("data_referencia deve ser uma data válida sem horário.")
    return data_referencia


def _validate_query(query: str) -> str:
    if not isinstance(query, str):
        raise TypeError("query deve ser texto.")
    return query.strip()


def _validate_history_page(history_page: int) -> int:
    if isinstance(history_page, bool) or not isinstance(history_page, int) or history_page <= 0:
        raise InvalidHistoryPage("history_page deve ser um inteiro positivo.")
    if history_page > 1000:
        raise InvalidHistoryPage("history_page excede o limite permitido.")
    return history_page


def _warning_messages(codes: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(_WARNING_LABELS.get(code, "Há um aviso financeiro neste projeto.") for code in codes)


def _project_financial(result: RentabilidadeProjeto | None) -> FinanceiroProjetoCliente360:
    if result is None:
        missing_codes = ("PROJETO_SEM_RESULTADO",)
        return FinanceiroProjetoCliente360(
            estado="INCONSISTENTE",
            valor_contratado=None,
            valor_recebido=None,
            saldo_a_receber=None,
            warning_codes=missing_codes,
            warnings=_warning_messages(missing_codes),
        )
    codes: tuple[str, ...] = tuple(result.inconsistencias)
    return FinanceiroProjetoCliente360(
        estado=result.estado,
        valor_contratado=result.valor_contratado,
        valor_recebido=result.valor_recebido,
        saldo_a_receber=result.saldo_a_receber,
        warning_codes=codes,
        warnings=_warning_messages(codes),
    )


def _aggregate_financial(project_financials: tuple[FinanceiroProjetoCliente360, ...]) -> ResumoFinanceiroCliente:
    warning_codes = tuple(dict.fromkeys(code for item in project_financials for code in item.warning_codes))
    warnings = _warning_messages(warning_codes)
    if any(item.estado == "INCONSISTENTE" for item in project_financials):
        return ResumoFinanceiroCliente(
            estado="INCONSISTENTE",
            total_contratado=None,
            total_recebido=None,
            saldo_a_receber=None,
            warning_codes=warning_codes,
            warnings=warnings,
        )
    return ResumoFinanceiroCliente(
        estado="DISPONIVEL",
        total_contratado=sum((item.valor_contratado or _ZERO for item in project_financials), _ZERO),
        total_recebido=sum((item.valor_recebido or _ZERO for item in project_financials), _ZERO),
        saldo_a_receber=sum((item.saldo_a_receber or _ZERO for item in project_financials), _ZERO),
        warning_codes=warning_codes,
        warnings=warnings,
    )


def clientes_index(*, query: str, data_referencia: date) -> ClientesIndex:
    """Return all matching customers, including customers without projects."""
    data_referencia = _validate_reference_date(data_referencia)
    query = _validate_query(query)
    pending_contacts = AgendaContato.objects.filter(
        cliente_id=OuterRef("pk"), realizado=False,
    ).order_by("data_agendada", "pk")
    queryset = Cliente.objects.annotate(
        projetos_count=Count("projetos", distinct=True),
        proximo_contato_data=Subquery(pending_contacts.values("data_agendada")[:1]),
        proximo_contato_tipo=Subquery(pending_contacts.values("tipo")[:1]),
    )
    if query:
        queryset = queryset.filter(Q(nome__icontains=query) | Q(whatsapp__icontains=query))
    rows = tuple(
        ClienteIndexRow(
            cliente_id=row["pk"],
            nome=row["nome"],
            whatsapp=row["whatsapp"],
            projetos_count=row["projetos_count"],
            proximo_contato_data=row["proximo_contato_data"],
            proximo_contato_tipo=row["proximo_contato_tipo"],
            proximo_contato_tipo_label=(
                _CONTACT_TYPE_LABELS.get(row["proximo_contato_tipo"])
                if row["proximo_contato_tipo"] else None
            ),
            proximo_contato_atrasado_ou_hoje=(
                row["proximo_contato_data"] is not None
                and row["proximo_contato_data"] <= data_referencia
            ),
        )
        for row in queryset.order_by("nome", "pk").values(
            "pk", "nome", "whatsapp", "projetos_count",
            "proximo_contato_data", "proximo_contato_tipo",
        )
    )
    return ClientesIndex(
        rows=rows,
        total_cadastrados=Cliente.objects.count(),
        clientes_com_contato_pendente=AgendaContato.objects.filter(
            realizado=False,
        ).values("cliente_id").distinct().count(),
        query=query,
        data_referencia=data_referencia,
    )


def _contact_context(row: dict) -> ContatoCliente360:
    return ContatoCliente360(
        contato_id=row["id"],
        tipo=row["tipo"],
        tipo_label=_CONTACT_TYPE_LABELS.get(row["tipo"], row["tipo"]),
        projeto_id=row["projeto_id"],
        projeto_titulo=row["projeto__titulo_servico"],
        data_agendada=row["data_agendada"],
        realizado=row["realizado"],
        nivel_satisfacao=row["nivel_satisfacao"],
        nivel_satisfacao_label=(
            _SATISFACTION_LABELS.get(row["nivel_satisfacao"], row["nivel_satisfacao"])
            if row["nivel_satisfacao"] else ""
        ),
        feedback_cliente=row["feedback_cliente"],
        realizado_em=row["realizado_em"],
    )


def _completed_sort_key(contact: ContatoCliente360):
    if contact.realizado_em is not None:
        return (1, contact.realizado_em, contact.contato_id)
    return (0, contact.data_agendada, contact.contato_id)


def _event_project_id(
    row: dict,
    contact_project_ids: dict[int, int | None],
    ledger_project_ids: dict[int, int],
) -> int | None:
    if row["entidade_tipo"] == "ProjetoKanban":
        return int(row["entidade_id"])
    if row["entidade_tipo"] == "AgendaContato":
        return contact_project_ids.get(int(row["entidade_id"]))
    if row["entidade_tipo"] == "LancamentoFinanceiro":
        return ledger_project_ids.get(int(row["entidade_id"]))
    if row["tipo"] == "PAGAMENTO_FUNCIONARIO_CRIADO":
        try:
            return ledger_project_ids.get(int(row["metadata"].get("lancamento_id")))
        except (AttributeError, TypeError, ValueError):
            return None
    return None


def _event_description(row: dict, project_title: str | None) -> str:
    project_title = project_title or "Contato do cliente"
    if row["tipo"] == "ORCAMENTO_ARQUIVADO":
        reason = row["metadata"].get("motivo_codigo")
        return f"{project_title} · motivo: {_ARCHIVE_REASON_LABELS.get(reason, reason or 'não informado')}"
    if row["tipo"] in {"LANCAMENTO_QUITADO", "PAGAMENTO_FUNCIONARIO_CRIADO"}:
        value = row["metadata"].get("valor")
        return f"{project_title} · valor registrado: R$ {value}" if value else project_title
    return project_title


def _load_events(
    *,
    project_ids: tuple[int, ...],
    contact_project_ids: dict[int, int | None],
    history_page: int,
) -> tuple[tuple[EventoCliente360, ...], bool]:
    contact_ids = tuple(contact_project_ids)
    ledger_rows = list(
        LancamentoFinanceiro.objects.filter(projeto_id__in=project_ids).values_list("pk", "projeto_id")
    ) if project_ids else []
    ledger_ids = tuple(row[0] for row in ledger_rows)
    ledger_project_ids = {row[0]: row[1] for row in ledger_rows}
    event_query = Q()
    if project_ids:
        event_query |= Q(
            dominio="KANBAN", entidade_tipo="ProjetoKanban",
            entidade_id__in=[str(value) for value in project_ids],
            tipo__in=("ORCAMENTO_APROVADO", "ORCAMENTO_ARQUIVADO", "ORCAMENTO_REATIVADO", "PROJETO_FINALIZADO"),
        )
    if contact_ids:
        event_query |= Q(
            dominio="AGENDA", entidade_tipo="AgendaContato",
            entidade_id__in=[str(value) for value in contact_ids], tipo="CONTATO_CONCLUIDO",
        )
    if ledger_ids:
        string_ids = [str(value) for value in ledger_ids]
        event_query |= Q(
            dominio="FINANCEIRO", entidade_tipo="LancamentoFinanceiro",
            entidade_id__in=string_ids, tipo="LANCAMENTO_QUITADO",
        )
        event_query |= Q(
            dominio="EQUIPE", tipo="PAGAMENTO_FUNCIONARIO_CRIADO",
            metadata__lancamento_id__in=string_ids,
        )
    if not event_query:
        return (), False
    offset = (history_page - 1) * _HISTORY_PAGE_SIZE
    rows = list(
        EventoSistema.objects.filter(event_query)
        .order_by("-criado_em", "-id")
        .values("id", "tipo", "criado_em", "entidade_tipo", "entidade_id", "metadata")
        [offset:offset + _HISTORY_PAGE_SIZE + 1]
    )
    has_more = len(rows) > _HISTORY_PAGE_SIZE
    rows = rows[:_HISTORY_PAGE_SIZE]
    project_titles = dict(
        ProjetoKanban.objects.filter(pk__in=project_ids).values_list("pk", "titulo_servico")
    ) if project_ids else {}
    events = []
    for row in rows:
        project_id = _event_project_id(row, contact_project_ids, ledger_project_ids)
        if row["entidade_tipo"] == "AgendaContato":
            contact_id = int(row["entidade_id"])
            if contact_id not in contact_project_ids:
                continue
        elif project_id is None or project_id not in project_titles:
            continue
        events.append(EventoCliente360(
            evento_id=row["id"],
            tipo=row["tipo"],
            tipo_label=_EVENT_LABELS[row["tipo"]],
            criado_em=row["criado_em"],
            projeto_id=project_id,
            projeto_titulo=project_titles.get(project_id),
            contato_id=(int(row["entidade_id"]) if row["entidade_tipo"] == "AgendaContato" else None),
            descricao=_event_description(row, project_titles.get(project_id)),
        ))
    return tuple(events), has_more


def cliente_360(*, cliente_id: int, data_referencia: date, history_page: int = 1) -> Cliente360:
    """Build one immutable Customer 360 projection with bounded history."""
    data_referencia = _validate_reference_date(data_referencia)
    if isinstance(cliente_id, bool) or not isinstance(cliente_id, int) or cliente_id <= 0:
        raise ValueError("cliente_id deve ser um inteiro positivo.")
    history_page = _validate_history_page(history_page)
    try:
        customer = Cliente.objects.only(
            "pk", "nome", "whatsapp", "endereco", "observacoes", "criado_em",
        ).get(pk=cliente_id)
    except Cliente.DoesNotExist as exc:
        raise Cliente360NotFound("Cliente não encontrado.") from exc

    project_rows = list(
        ProjetoKanban.objects.filter(cliente_id=cliente_id)
        .order_by("etapa", "titulo_servico", "pk")
        .values(
            "id", "titulo_servico", "etapa", "data_limite_orcamento",
            "data_inicio_producao", "data_entrega_prevista", "data_entrega_realizada",
            "motivo_arquivamento", "observacao_arquivamento",
        )
    )
    project_ids = tuple(row["id"] for row in project_rows)
    contacts_rows = list(
        AgendaContato.objects.filter(cliente_id=cliente_id)
        .order_by("data_agendada", "pk")
        .values(
            "id", "tipo", "projeto_id", "projeto__titulo_servico", "data_agendada",
            "realizado", "nivel_satisfacao", "feedback_cliente", "realizado_em",
        )
    )
    contacts = tuple(_contact_context(row) for row in contacts_rows)
    contact_project_ids = {contact.contato_id: contact.projeto_id for contact in contacts}
    all_financial = {
        result.projeto_id: result
        for result in rentabilidade_projetos().projetos
        if result.projeto_id in project_ids
    }
    project_financials = tuple(
        _project_financial(all_financial.get(project_id)) for project_id in project_ids
    )
    projects = tuple(
        ProjetoCliente360(
            projeto_id=row["id"],
            titulo=row["titulo_servico"],
            etapa=row["etapa"],
            etapa_label=_STAGE_LABELS.get(row["etapa"], row["etapa"]),
            data_limite_orcamento=row["data_limite_orcamento"],
            data_inicio_producao=row["data_inicio_producao"],
            data_entrega_prevista=row["data_entrega_prevista"],
            data_entrega_realizada=row["data_entrega_realizada"],
            arquivado=row["etapa"] == "9_ARQUIVADO",
            motivo_arquivamento=row["motivo_arquivamento"],
            motivo_arquivamento_label=_ARCHIVE_REASON_LABELS.get(row["motivo_arquivamento"], ""),
            observacao_arquivamento=row["observacao_arquivamento"],
            financeiro=financial,
        )
        for row, financial in zip(project_rows, project_financials)
    )
    events, history_has_more = _load_events(
        project_ids=project_ids,
        contact_project_ids=contact_project_ids,
        history_page=history_page,
    )
    return Cliente360(
        cliente_id=customer.pk,
        nome=customer.nome,
        whatsapp=customer.whatsapp,
        endereco=customer.endereco,
        observacoes=customer.observacoes,
        criado_em=customer.criado_em,
        projetos=projects,
        agenda_overdue_or_today=tuple(
            sorted((item for item in contacts if not item.realizado and item.data_agendada <= data_referencia), key=lambda item: (item.data_agendada, item.contato_id))
        ),
        agenda_future=tuple(
            sorted((item for item in contacts if not item.realizado and item.data_agendada > data_referencia), key=lambda item: (item.data_agendada, item.contato_id))
        ),
        agenda_completed=tuple(
            sorted((item for item in contacts if item.realizado), key=_completed_sort_key, reverse=True)
        ),
        eventos=events,
        financeiro=_aggregate_financial(project_financials),
        history_page=history_page,
        history_has_more=history_has_more,
        history_next_page=history_page + 1 if history_has_more else None,
    )
