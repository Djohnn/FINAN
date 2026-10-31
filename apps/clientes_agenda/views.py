from __future__ import annotations

from decimal import Decimal

from django.http import Http404, HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET

from apps.kanban_projetos.models import ProjetoKanban

from .models import AgendaContato
from .selectors import (
    Cliente360,
    Cliente360NotFound,
    ClienteIndexRow,
    ContatoCliente360,
    InvalidHistoryPage,
    ProjetoCliente360,
    cliente_360,
    clientes_index,
)


def _money(value: Decimal | None) -> str:
    if value is None:
        return ""
    formatted = f"{value:,.2f}"
    return f"R$ {formatted.replace(',', '_').replace('.', ',').replace('_', '.') }"


def _page_from_request(request: HttpRequest) -> int:
    raw = request.GET.get("pagina")
    if raw is None:
        return 1
    try:
        page = int(raw)
    except (TypeError, ValueError) as exc:
        raise InvalidHistoryPage from exc
    return page


def _index_row_context(row: ClienteIndexRow) -> dict:
    return {
        "row": row,
        "next_contact_date": row.proximo_contato_data,
        "next_contact_label": row.proximo_contato_tipo_label,
    }


def _financial_context(financial) -> dict:
    return {
        "state": financial.estado,
        "contracted": _money(financial.total_contratado),
        "received": _money(financial.total_recebido),
        "receivable": _money(financial.saldo_a_receber),
        "warnings": financial.warnings,
    }


def _project_context(project: ProjetoCliente360) -> dict:
    financial = project.financeiro
    return {
        "project": project,
        "contracted": _money(financial.valor_contratado),
        "received": _money(financial.valor_recebido),
        "receivable": _money(financial.saldo_a_receber),
        "financial_available": financial.estado != "INCONSISTENTE",
    }


def _contact_context(contact: ContatoCliente360) -> dict:
    return {"contact": contact}


def _detail_context(customer: Cliente360) -> dict:
    history_url = reverse(
        "clientes_agenda:cliente_history",
        kwargs={"cliente_id": customer.cliente_id},
    )
    return {
        "customer": customer,
        "financial": _financial_context(customer.financeiro),
        "projects": tuple(_project_context(project) for project in customer.projetos),
        "overdue_contacts": tuple(_contact_context(contact) for contact in customer.agenda_overdue_or_today),
        "future_contacts": tuple(_contact_context(contact) for contact in customer.agenda_future),
        "completed_contacts": tuple(_contact_context(contact) for contact in customer.agenda_completed),
        "history_url": history_url,
    }


@csrf_exempt
@require_GET
def clientes_index_view(request: HttpRequest) -> HttpResponse:
    data_referencia = timezone.localdate()
    index = clientes_index(
        query=request.GET.get("q", ""),
        data_referencia=data_referencia,
    )
    return render(
        request,
        "clientes_agenda/clientes.html",
        {
            "index": index,
            "rows": tuple(_index_row_context(row) for row in index.rows),
            "has_clients": bool(index.total_cadastrados),
        },
    )


@csrf_exempt
@require_GET
def cliente_360_view(request: HttpRequest, cliente_id: int) -> HttpResponse:
    try:
        customer = cliente_360(
            cliente_id=cliente_id,
            data_referencia=timezone.localdate(),
            history_page=_page_from_request(request),
        )
    except Cliente360NotFound as exc:
        raise Http404("Cliente não encontrado.") from exc
    except InvalidHistoryPage:
        return HttpResponseBadRequest("Página de histórico inválida.")
    return render(request, "clientes_agenda/cliente_360.html", _detail_context(customer))


@csrf_exempt
@require_GET
def cliente_history_view(request: HttpRequest, cliente_id: int) -> HttpResponse:
    try:
        customer = cliente_360(
            cliente_id=cliente_id,
            data_referencia=timezone.localdate(),
            history_page=_page_from_request(request),
        )
    except Cliente360NotFound as exc:
        raise Http404("Cliente não encontrado.") from exc
    except InvalidHistoryPage:
        return HttpResponseBadRequest("Página de histórico inválida.")
    return render(
        request,
        "clientes_agenda/_historico.html",
        {"customer": customer, "history_url": request.path},
    )


@csrf_exempt
@require_GET
def cliente_project_whatsapp_view(
    request: HttpRequest,
    cliente_id: int,
    projeto_id: int,
) -> HttpResponse:
    project = ProjetoKanban.objects.filter(
        pk=projeto_id,
        cliente_id=cliente_id,
    ).select_related("cliente").first()
    if project is None:
        raise Http404("Projeto não encontrado para este cliente.")
    url = project.get_whatsapp_url()
    if not url:
        return HttpResponse("WhatsApp indisponível para este projeto.", status=404)
    return redirect(url)


@csrf_exempt
@require_GET
def cliente_contact_whatsapp_view(
    request: HttpRequest,
    cliente_id: int,
    contato_id: int,
) -> HttpResponse:
    contact = AgendaContato.objects.filter(
        pk=contato_id,
        cliente_id=cliente_id,
    ).select_related("cliente", "projeto").first()
    if contact is None:
        raise Http404("Contato não encontrado para este cliente.")
    url = contact.get_whatsapp_url()
    if not url:
        return HttpResponse("WhatsApp indisponível para este contato.", status=404)
    return redirect(url)
