from collections.abc import Iterable
from decimal import Decimal
import re

from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from .selectors import CentralContasReceber, RecebivelCentral, central_contas_receber


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


def _money(value: Decimal) -> str:
    formatted = format(value, ",.2f")
    return f"R$ {formatted.replace(',', 'X').replace('.', ',').replace('X', '.')}"


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
