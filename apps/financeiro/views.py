import re
from collections.abc import Iterable
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext

from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from .selectors import (
    CentralContasReceber,
    ProjetosRentabilidade,
    RecebivelCentral,
    RentabilidadeProjeto,
    central_contas_receber,
    rentabilidade_clientes,
    rentabilidade_projeto,
    rentabilidade_projetos,
)

PERIODS = {
    "todos": "Todos",
    "atrasados": "Atrasados",
    "hoje": "Vence hoje",
    "proximos_7": "Próximos 7 dias",
    "proximos_30": "Próximos 30 dias",
}
FORM_LABELS = {
    "PIX": "PIX",
    "CARTAO_CREDITO": "Cartão de crédito",
    "CARTAO_DEBITO": "Cartão de débito",
    "DINHEIRO": "Dinheiro",
    "BOLETO": "Boleto",
}
MONTHS = (
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
)
CLASSIFICATION_LABELS = {
    "ATRASADO": ("Atrasado", "status-overdue"),
    "VENCE_HOJE": ("Vence hoje", "status-today"),
    "A_VENCER": ("A vencer", "status-future"),
}

PROFITABILITY_STAGE_LABELS = {
    "1_CONTATO": "Novo contato",
    "2_ORCAMENTO": "Em orçamento",
    "3_APROVADO": "Aprovado",
    "4_PRODUCAO": "Em produção",
    "5_ENTREGA": "Pronto para entrega",
    "6_FINALIZADO": "Entregue / finalizado",
    "9_ARQUIVADO": "Arquivado",
}
PROFITABILITY_STATE_LABELS = {
    "DISPONIVEL": ("Disponível", "state-tag--available"),
    "SEM_CONTRATO": ("Sem contrato", "state-tag--no-contract"),
    "INCONSISTENTE": ("Inconsistente", "state-tag--inconsistent"),
}
PROFITABILITY_CATEGORY_LABELS = {
    "MATERIA_PRIMA": "Matéria-prima",
    "FUNCIONARIO": "Funcionário",
    "OUTROS": "Outros",
}
PROFITABILITY_MESSAGES = {
    "CONTRATO_DIVERGE_DO_LEDGER": (
        "O contrato registrado não bate com as entradas ligadas ao projeto."
    ),
    "PENDENTE_COM_DATA_PAGAMENTO": (
        "Há um lançamento pendente com data de pagamento preenchida."
    ),
    "VALOR_ZERO": "Existe um lançamento com valor zero; ele foi mantido como está.",
    "CUSTO_FIXO_OFICINA_VINCULADO_EXCLUIDO": (
        "Um custo fixo da oficina foi excluído do custo direto do projeto."
    ),
    "SERVICO_CLIENTE_EM_SAIDA": (
        "Um lançamento de serviço foi ignorado porque está registrado como saída."
    ),
    "ENTRADA_NAO_SERVICO_CLIENTE_EXCLUIDA": (
        "Uma entrada que não é de serviço foi excluída do resultado do projeto."
    ),
    "ETAPA_INVALIDA": "A etapa atual do projeto é inválida.",
    "VALOR_CONTRATADO_INVALIDO": "O valor contratado está inválido.",
    "PAGO_SEM_DATA_PAGAMENTO": (
        "Há um lançamento pago sem data de pagamento."
    ),
    "STATUS_INVALIDO": "Há um lançamento com status inválido.",
    "TIPO_INVALIDO": "Há um lançamento com tipo inválido.",
    "CATEGORIA_INVALIDA": "Há um lançamento com categoria inválida.",
    "VALOR_MONETARIO_INVALIDO": "Há um valor financeiro inválido.",
}


def _money(value: Decimal) -> str:
    formatted = format(value, ",.2f")
    return f"R$ {formatted.replace(',', 'X').replace('.', ',').replace('X', '.')}"


def _profitability_money(value: Decimal | None) -> str:
    if value is None:
        return "Não disponível"
    formatted = format(abs(value), ",.2f")
    rendered = f"R$ {formatted.replace(',', 'X').replace('.', ',').replace('X', '.')}"
    return f"− {rendered}" if value < 0 else rendered


def _profitability_percent(value: Decimal | None) -> str:
    if value is None:
        return "Não calculada"
    with localcontext(Context(prec=28, rounding=ROUND_HALF_EVEN)):
        rendered = value.quantize(Decimal("0.1"))
    formatted = format(abs(rendered), ",.1f").replace(",", "X").replace(".", ",").replace("X", ".")
    return f"−{formatted}%" if rendered < 0 else f"{formatted}%"


def _profitability_messages(result: RentabilidadeProjeto) -> tuple[str, ...]:
    return tuple(
        PROFITABILITY_MESSAGES.get(code, "Há uma inconsistência nos dados do projeto.")
        for code in result.inconsistencias
    )


def _profitability_notice(result: RentabilidadeProjeto) -> tuple[str, str, str, str]:
    messages = _profitability_messages(result)
    if result.estado == "INCONSISTENTE":
        return (
            "warning",
            "!",
            "Resultado indisponível por inconsistência",
            " ".join(messages) or "Os valores ficam ocultos para evitar um resultado parcial.",
        )
    if result.estado == "SEM_CONTRATO":
        return (
            "neutral",
            "i",
            "Ainda não há valor contratado",
            (
                "Os custos diretos já lançados aparecem abaixo. A margem não é calculada; "
                "o resultado negativo não representa uma margem final de projeto contratado."
            ),
        )
    if result.lucro_direto is not None and result.lucro_direto == Decimal("0.00"):
        return (
            "neutral",
            "i",
            "Sem lucro nem prejuízo direto",
            "O valor contratado corresponde aos custos diretamente ligados ao projeto.",
        )
    if result.lucro_direto is not None and result.lucro_direto < 0:
        return (
            "negative",
            "−",
            "Este projeto está com prejuízo direto",
            (
                "Os custos diretamente ligados ao projeto estão acima do valor contratado. "
                "A margem negativa aparece sem esconder o resultado."
            ),
        )
    return (
        "positive",
        "✓",
        "Resultado direto disponível",
        (
            "O lucro direto considera o valor contratado e todos os custos diretamente "
            "ligados ao projeto, pagos ou pendentes."
        ) + (f" {' '.join(messages)}" if messages else ""),
    )


def _profitability_row(result: RentabilidadeProjeto, customer_name: str | None) -> dict:
    state_label, state_class = PROFITABILITY_STATE_LABELS[result.estado]
    notice_class, _mark, _title, _copy = _profitability_notice(result)
    inconsistent = result.estado == "INCONSISTENTE"
    return {
        "result": result,
        "customer_name": customer_name or "Cliente não disponível",
        "project_meta": f"{customer_name or 'Cliente não disponível'} · Projeto #{result.projeto_id}",
        "stage_label": PROFITABILITY_STAGE_LABELS.get(result.etapa, result.etapa),
        "state_label": state_label,
        "state_class": state_class,
        "inconsistent": inconsistent,
        "warning_messages": _profitability_messages(result),
        "warning_codes": result.inconsistencias,
        "contracted": _profitability_money(result.valor_contratado),
        "direct_costs": _profitability_money(result.custos_diretos),
        "profit": _profitability_money(result.lucro_direto),
        "margin": _profitability_percent(result.margem_direta_percentual),
        "profit_negative": result.lucro_direto is not None and result.lucro_direto < 0,
        "notice_class": notice_class,
        "outcome_label": (
            "Resultado indisponível"
            if inconsistent
            else "Prejuízo direto"
            if result.lucro_direto is not None and result.lucro_direto < 0
            else "Sem contrato · custos já registrados"
            if result.estado == "SEM_CONTRATO"
            else "Sem lucro nem prejuízo direto"
            if result.lucro_direto is not None and result.lucro_direto == Decimal("0.00")
            else "Resultado positivo"
        ),
    }


def _profitability_detail_context(result: RentabilidadeProjeto, customer_name: str | None) -> dict:
    row = _profitability_row(result, customer_name)
    notice_class, notice_mark, notice_title, notice_copy = _profitability_notice(result)
    cost_rows = tuple(
        {
            "label": PROFITABILITY_CATEGORY_LABELS.get(cost.categoria, cost.categoria),
            "total": _profitability_money(cost.total),
            "pending": _profitability_money(cost.pendente),
            "paid": _profitability_money(cost.pago),
        }
        for cost in (result.custos_diretos_por_categoria or ())
    )
    row.update(
        {
            "notice_class": notice_class,
            "notice_mark": notice_mark,
            "notice_title": notice_title,
            "notice_copy": notice_copy,
            "cost_rows": cost_rows,
            "received": _profitability_money(result.valor_recebido),
            "remaining": _profitability_money(result.saldo_a_receber),
            "cash_in": _profitability_money(result.entradas_realizadas),
            "cash_out": _profitability_money(result.saidas_realizadas),
            "cash_net": _profitability_money(result.caixa_liquido_realizado),
            "profit_explanation": (
                "Resultado direto = valor contratado de R$ 0,00 menos custos diretos já registrados. "
                "Como não há contrato, este valor não deve ser lido como margem final de projeto contratado."
                if result.estado == "SEM_CONTRATO"
                else "Valor contratado menos os custos diretamente ligados ao projeto."
            ),
        }
    )
    return row


def _date(value) -> str:
    return value.strftime("%d/%m/%Y")


def _long_date(value) -> str:
    return f"{value.day} de {MONTHS[value.month - 1]} de {value.year}"


def _parse_positive_id(value: str) -> int | None:
    if not value or not re.fullmatch(r"[1-9][0-9]*", value):
        return None
    return int(value)


def _choices(rows: Iterable[RecebivelCentral], field_id: str, field_name: str):
    values = {
        (getattr(row, field_id), getattr(row, field_name))
        for row in rows
        if getattr(row, field_id) is not None and getattr(row, field_name) is not None
    }
    return tuple(
        {"id": item_id, "name": name}
        for item_id, name in sorted(values, key=lambda item: (item[1].casefold(), item[0]))
    )


def _integrity_labels(row: RecebivelCentral) -> tuple[str, ...]:
    labels = []
    if row.inconsistencias:
        labels.append("Inconsistência de dados")
    if "VALOR_ZERO" in row.inconsistencias:
        labels.append("Valor zero")
    if "PENDENTE_COM_DATA_PAGAMENTO" in row.inconsistencias:
        labels.append("PENDENTE · data de pagamento preenchida")
    if "CATEGORIA_INVALIDA" in row.inconsistencias:
        labels.append("Categoria inválida")
    return tuple(labels)


def _present_row(row: RecebivelCentral) -> dict:
    state_label, state_class = CLASSIFICATION_LABELS[row.classificacao]
    return {
        "row": row,
        "cliente_label": row.cliente_nome or "Sem cliente vinculado",
        "projeto_label": row.projeto_titulo or "Sem projeto vinculado",
        "vencimento": _date(row.data_vencimento),
        "valor": _money(row.valor),
        "forma": FORM_LABELS.get(row.forma_pagamento, "Não informado"),
        "situacao": state_label,
        "situacao_class": state_class,
        "integridade": _integrity_labels(row),
        "atraso_contexto": (
            f"{row.dias_atraso} dias em atraso" if row.dias_atraso else state_label
        ),
    }


def _matches_period(row: RecebivelCentral, period: str) -> bool:
    return {
        "todos": True,
        "atrasados": row.classificacao == "ATRASADO",
        "hoje": row.classificacao == "VENCE_HOJE",
        "proximos_7": row.nos_proximos_7_dias,
        "proximos_30": row.nos_proximos_30_dias,
    }[period]


def _filter_rows(
    portfolio: CentralContasReceber,
    *,
    query: str,
    client_id: int | None,
    project_id: int | None,
    period: str,
) -> tuple[RecebivelCentral, ...]:
    normalized_query = query.casefold()
    rows = [
        row
        for row in portfolio.recebiveis
        if (not normalized_query or any(
            normalized_query in (value or "").casefold()
            for value in (row.cliente_nome, row.projeto_titulo, row.descricao)
        ))
        and (client_id is None or row.cliente_id == client_id)
        and (project_id is None or row.projeto_id == project_id)
        and _matches_period(row, period)
    ]
    rank = {"ATRASADO": 0, "VENCE_HOJE": 1, "A_VENCER": 2}
    rows.sort(key=lambda row: (rank[row.classificacao], row.data_vencimento, row.lancamento_id))
    return tuple(rows)


def _quick_filters(rows: Iterable[RecebivelCentral]) -> tuple[dict, ...]:
    rows = tuple(rows)
    return tuple(
        {
            "value": value,
            "label": label,
            "count": sum(_matches_period(row, value) for row in rows),
        }
        for value, label in PERIODS.items()
    )


@require_GET
def central_contas_receber_view(request):
    data_referencia = timezone.localdate()
    try:
        portfolio = central_contas_receber(data_referencia=data_referencia)
    except ValueError:
        return render(
            request,
            "financeiro/central_contas_receber.html",
            {
                "available": False,
                "reference_date_label": _long_date(data_referencia),
                "error_message": (
                    "A Central não pode ser exibida com segurança porque há "
                    "uma inconsistência nos dados financeiros."
                ),
            },
        )

    requested_period = request.GET.get("periodo", "todos")
    invalid_filters = []
    period = requested_period if requested_period in PERIODS else "todos"
    if period != requested_period:
        invalid_filters.append("periodo")

    available_client_ids = {row.cliente_id for row in portfolio.recebiveis}
    available_project_ids = {row.projeto_id for row in portfolio.recebiveis}
    client_value = request.GET.get("cliente", "")
    project_value = request.GET.get("projeto", "")
    client_id = _parse_positive_id(client_value)
    project_id = _parse_positive_id(project_value)
    if client_value and (client_id is None or client_id not in available_client_ids):
        client_id = None
        invalid_filters.append("cliente")
    if project_value and (project_id is None or project_id not in available_project_ids):
        project_id = None
        invalid_filters.append("projeto")

    query = request.GET.get("q", "").strip()
    filtered = _filter_rows(
        portfolio,
        query=query,
        client_id=client_id,
        project_id=project_id,
        period=period,
    )
    kpis = {
        "total_a_receber": portfolio.total_a_receber,
        "total_vencido": portfolio.total_vencido,
        "clientes_em_atraso": portfolio.clientes_em_atraso,
        "maior_atraso_dias": portfolio.maior_atraso_dias,
    }
    kpi_cards = (
        {"label": "Total a receber", "value": _money(portfolio.total_a_receber)},
        {"label": "Total vencido", "value": _money(portfolio.total_vencido)},
        {"label": "Clientes em atraso", "value": str(portfolio.clientes_em_atraso)},
        {
            "label": "Maior atraso",
            "value": (
                f"{portfolio.maior_atraso_dias} dias"
                if portfolio.maior_atraso_dias is not None
                else "Nenhum"
            ),
        },
    )
    return render(
        request,
        "financeiro/central_contas_receber.html",
        {
            "available": True,
            "data_referencia": data_referencia,
            "reference_date_label": _long_date(data_referencia),
            "kpis": kpis,
            "kpi_cards": kpi_cards,
            "rows": tuple(_present_row(row) for row in filtered),
            "filtered_count": len(filtered),
            "total_count": len(portfolio.recebiveis),
            "quick_filters": _quick_filters(portfolio.recebiveis),
            "selected_period": period,
            "selected_client_id": client_id,
            "selected_project_id": project_id,
            "query": query,
            "client_options": _choices(portfolio.recebiveis, "cliente_id", "cliente_nome"),
            "project_options": _choices(portfolio.recebiveis, "projeto_id", "projeto_titulo"),
            "invalid_filters": tuple(invalid_filters),
        },
    )


@require_GET
def rentabilidade_projetos_view(request):
    """Render the current read-only profitability overview."""
    try:
        portfolio: ProjetosRentabilidade = rentabilidade_projetos()
    except ValueError:
        return render(
            request,
            "financeiro/rentabilidade_projetos.html",
            {
                "available": False,
                "error_message": (
                    "A rentabilidade não pode ser exibida com segurança porque "
                    "há uma inconsistência nos dados financeiros."
                ),
            },
        )

    project_ids = tuple(result.projeto_id for result in portfolio.projetos)
    customer_names = rentabilidade_clientes(projeto_ids=project_ids)
    projects = tuple(
        _profitability_row(result, customer_names.get(result.projeto_id))
        for result in portfolio.projetos
    )
    return render(
        request,
        "financeiro/rentabilidade_projetos.html",
        {
            "available": True,
            "projects": projects,
            "has_projects": bool(projects),
        },
    )


@require_GET
def rentabilidade_projeto_view(request, projeto_id: int):
    """Render one current read-only profitability result."""
    try:
        result = rentabilidade_projeto(projeto_id=projeto_id)
    except ValueError:
        return render(
            request,
            "financeiro/rentabilidade_projeto.html",
            {
                "available": False,
                "not_found": True,
                "error_message": "Projeto não encontrado.",
            },
            status=404,
        )

    customer_names = rentabilidade_clientes(projeto_ids=(result.projeto_id,))
    return render(
        request,
        "financeiro/rentabilidade_projeto.html",
        {
            "available": True,
            "project": _profitability_detail_context(
                result,
                customer_names.get(result.projeto_id),
            ),
        },
    )
