"""Frontend contract tests for the read-only Central A/R screen."""

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from apps.core_sistema.models import EventoSistema
from apps.financeiro.models import LancamentoFinanceiro
from apps.financeiro.selectors import (
    CentralContasReceber,
    ClassificacaoRecebivel,
    InconsistenciaRecebivel,
    RecebivelCentral,
)
from apps.kanban_projetos.models import ProjetoKanban

REF = date(2026, 10, 23)
ROOT = Path(__file__).resolve().parent.parent


def make_row(
    row_id: int,
    *,
    due: date,
    value: str = "1234.56",
    customer_id: int | None = 10,
    customer_name: str | None = "Ana Carvalho",
    phone: str | None = "(11) 99999-0000",
    project_id: int | None = 20,
    project_title: str | None = "Cozinha planejada",
    description: str = "Parcela 1 de 2",
    form: str | None = "PIX",
    category: str | None = "SERVICO_CLIENTE",
    classification: ClassificacaoRecebivel | None = None,
    days_late: int | None = None,
    inconsistencies: tuple[InconsistenciaRecebivel, ...] = (),
    eligible: bool | None = None,
) -> RecebivelCentral:
    delta = (due - REF).days
    classification = classification or (
        "ATRASADO" if delta < 0 else "VENCE_HOJE" if delta == 0 else "A_VENCER"
    )
    eligible = (
        eligible
        if eligible is not None
        else value != "0.00"
        and customer_id is not None
        and project_id is not None
        and bool(phone)
    )
    return RecebivelCentral(
        lancamento_id=row_id,
        projeto_id=project_id,
        projeto_titulo=project_title,
        cliente_id=customer_id,
        cliente_nome=customer_name,
        cliente_whatsapp=phone,
        sem_projeto_vinculado=project_id is None,
        sem_cliente_vinculado=customer_id is None,
        descricao=description,
        categoria=category,
        valor=Decimal(value),
        forma_pagamento=form,
        data_vencimento=due,
        classificacao=classification,
        dias_atraso=days_late if days_late is not None else (-delta if delta < 0 else None),
        nos_proximos_7_dias=1 <= delta <= 7,
        nos_proximos_30_dias=1 <= delta <= 30,
        inconsistencias=inconsistencies,
        whatsapp_elegivel=eligible,
    )


def make_portfolio(*rows: RecebivelCentral) -> CentralContasReceber:
    positive = [row for row in rows if row.valor > 0]
    overdue = [row for row in positive if row.classificacao == "ATRASADO"]
    customers = {row.cliente_id for row in overdue if row.cliente_id is not None}
    return CentralContasReceber(
        data_referencia=REF,
        total_a_receber=sum((row.valor for row in positive), Decimal("0.00")),
        total_vencido=sum(
            (row.valor for row in overdue), Decimal("0.00")
        ),
        clientes_em_atraso=len(customers),
        maior_atraso_dias=max(
            (row.dias_atraso or 0 for row in overdue), default=None
        ),
        recebiveis=tuple(rows),
    )


class CentralContasReceberFrontendTests(TestCase):
    def setUp(self):
        self.url = reverse("financeiro:central_contas_receber")
        self.overdue = make_row(
            1,
            due=REF - timedelta(days=5),
            days_late=5,
            description="Parcela atrasada",
        )
        self.today = make_row(2, due=REF, description="Parcela de hoje")
        self.future = make_row(
            3,
            due=REF + timedelta(days=7),
            customer_id=11,
            customer_name="Bruno Lima",
            project_id=21,
            project_title="Quarto planejado",
            description="Parcela futura",
        )
        self.portfolio = make_portfolio(self.overdue, self.today, self.future)

    def get_with_portfolio(self, **params):
        with patch(
            "apps.financeiro.views.central_contas_receber",
            return_value=self.portfolio,
        ) as selector:
            response = self.client.get(self.url, params)
        return response, selector

    def test_named_route_and_admin_route_remain_available(self):
        self.assertEqual(self.url, "/financeiro/contas-a-receber/")
        admin_response = self.client.get("/admin/")
        self.assertIn(admin_response.status_code, {200, 302})

    @patch("apps.financeiro.views.timezone.localdate", return_value=REF)
    @patch("apps.financeiro.views.central_contas_receber")
    def test_get_passes_explicit_reference_date_to_integrated_selector(
        self, selector, localdate
    ):
        selector.return_value = self.portfolio

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(localdate.call_count, 1)
        selector.assert_called_once_with(data_referencia=REF)

    def test_get_returns_success_and_renders_four_kpis_from_complete_portfolio(self):
        response, _selector = self.get_with_portfolio()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.count(b'class="kpi-card"'), 4)
        for label in (
            "Total a receber",
            "Total vencido",
            "Clientes em atraso",
            "Maior atraso",
        ):
            self.assertContains(response, label)
        self.assertContains(response, "R$ 3.703,68")
        self.assertContains(response, "R$ 1.234,56")
        self.assertContains(response, "5 dias")

    def test_table_filters_do_not_shrink_canonical_kpis(self):
        response, _selector = self.get_with_portfolio(q="futura")

        self.assertEqual(response.context["filtered_count"], 1)
        self.assertEqual(response.context["kpis"]["total_a_receber"], Decimal("3703.68"))
        self.assertEqual(response.context["kpis"]["total_vencido"], Decimal("1234.56"))

    def test_active_rows_remain_distinct_and_show_temporal_states(self):
        response, _selector = self.get_with_portfolio()

        self.assertEqual(response.context["filtered_count"], 3)
        self.assertContains(response, "Parcela atrasada")
        self.assertContains(response, "Parcela de hoje")
        self.assertContains(response, "Parcela futura")
        self.assertContains(response, "Atrasado")
        self.assertContains(response, "Vence hoje")
        self.assertContains(response, "A vencer")
        self.assertContains(response, "23/10/2026")

    def test_search_is_case_insensitive_and_uses_presentation_text(self):
        response, _selector = self.get_with_portfolio(q="QUARTO")

        self.assertEqual(response.context["filtered_count"], 1)
        self.assertContains(response, "Quarto planejado")
        self.assertEqual(response.context["rows"][0]["row"].projeto_titulo, "Quarto planejado")

    def test_structured_customer_and_project_filters(self):
        customer_response, _selector = self.get_with_portfolio(cliente="11")
        project_response, _selector = self.get_with_portfolio(projeto="20")

        self.assertEqual(customer_response.context["filtered_count"], 1)
        self.assertEqual(customer_response.context["rows"][0]["row"].cliente_id, 11)
        self.assertEqual(project_response.context["filtered_count"], 2)
        self.assertTrue(all(row["row"].projeto_id == 20 for row in project_response.context["rows"]))

    def test_temporal_filters_and_invalid_values_are_safe(self):
        overdue, _selector = self.get_with_portfolio(periodo="atrasados")
        today, _selector = self.get_with_portfolio(periodo="hoje")
        seven, _selector = self.get_with_portfolio(periodo="proximos_7")
        thirty, _selector = self.get_with_portfolio(periodo="proximos_30")
        invalid, _selector = self.get_with_portfolio(periodo="unknown")

        self.assertEqual(overdue.context["filtered_count"], 1)
        self.assertEqual(today.context["filtered_count"], 1)
        self.assertEqual(seven.context["filtered_count"], 1)
        self.assertEqual(thirty.context["filtered_count"], 1)
        self.assertEqual(invalid.status_code, 200)
        self.assertEqual(invalid.context["filtered_count"], 3)

    def test_invalid_structured_ids_fall_back_without_crashing(self):
        response, _selector = self.get_with_portfolio(cliente="not-an-id", projeto="-3")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["filtered_count"], 3)
        self.assertEqual(set(response.context["invalid_filters"]), {"cliente", "projeto"})

    def test_unlinked_rows_are_retained_with_neutral_labels_and_no_action(self):
        row = make_row(
            10,
            due=REF - timedelta(days=1),
            customer_id=None,
            customer_name=None,
            phone=None,
            project_id=None,
            project_title=None,
            eligible=False,
        )
        response, _selector = self.get_with_portfolio()
        with patch("apps.financeiro.views.central_contas_receber", return_value=make_portfolio(row)):
            response = self.client.get(self.url)

        self.assertEqual(response.context["filtered_count"], 1)
        self.assertContains(response, "Sem cliente vinculado")
        self.assertContains(response, "Sem projeto vinculado")
        self.assertNotContains(response, "Cobrar no WhatsApp")

    def test_zero_legacy_row_preserves_temporal_state_and_has_no_action(self):
        row = make_row(
            11,
            due=REF - timedelta(days=2),
            value="0.00",
            inconsistencies=("VALOR_ZERO",),
            eligible=False,
        )
        with patch("apps.financeiro.views.central_contas_receber", return_value=make_portfolio(row)):
            response = self.client.get(self.url)

        self.assertContains(response, "R$ 0,00")
        self.assertContains(response, "Atrasado")
        self.assertContains(response, "Valor zero")
        self.assertContains(response, "Inconsistência de dados")
        self.assertNotContains(response, "Cobrar no WhatsApp")

    def test_pending_payment_date_warning_is_not_paid_state(self):
        row = make_row(
            12,
            due=REF,
            inconsistencies=("PENDENTE_COM_DATA_PAGAMENTO",),
        )
        with patch("apps.financeiro.views.central_contas_receber", return_value=make_portfolio(row)):
            response = self.client.get(self.url)

        self.assertContains(response, "PENDENTE · data de pagamento preenchida")
        self.assertNotContains(response, "Pago")

    def test_invalid_form_uses_controlled_fallback_and_keeps_debt_visible(self):
        row = make_row(13, due=REF, form="INVALIDA", inconsistencies=("FORMA_PAGAMENTO_INVALIDA",))
        with patch("apps.financeiro.views.central_contas_receber", return_value=make_portfolio(row)):
            response = self.client.get(self.url)

        self.assertContains(response, "Não informado")
        self.assertContains(response, "R$ 1.234,56")
        self.assertNotContains(response, "INVALIDA")

    def test_selector_value_error_is_controlled_unavailable_state(self):
        with patch(
            "apps.financeiro.views.central_contas_receber",
            side_effect=ValueError("row 999 secret free text"),
        ):
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Central indisponível")
        self.assertNotContains(response, "row 999")
        self.assertNotContains(response, "secret free text")

    def test_whatsapp_markup_contains_eligible_controls_and_modal_contract(self):
        response, _selector = self.get_with_portfolio()

        self.assertContains(response, "Cobrar no WhatsApp")
        self.assertContains(response, "Abrir no WhatsApp")
        self.assertContains(response, "Voltar")
        self.assertContains(response, "Cancelar")
        self.assertContains(response, "textarea")
        self.assertContains(response, 'role="dialog"')
        self.assertContains(response, 'aria-modal="true"')
        self.assertContains(response, "data-cliente=")
        self.assertNotContains(response, "PROPOSED_COPY_NOT_YET_FOUNDER_APPROVED")

    def test_no_mutation_controls_are_present(self):
        response, _selector = self.get_with_portfolio()

        for forbidden in (
            "Marcar como pago",
            "Quitar",
            "Receber",
            "Cancelar lançamento",
            "Editar vencimento",
            "Pagamento parcial",
        ):
            self.assertNotContains(response, forbidden)
        self.assertNotContains(response, "method=\"post\"")

    def test_get_does_not_change_financial_project_or_history_counts(self):
        before = (
            LancamentoFinanceiro.objects.count(),
            ProjetoKanban.objects.count(),
            EventoSistema.objects.count(),
        )
        with patch("apps.financeiro.views.central_contas_receber", return_value=self.portfolio):
            response = self.client.get(self.url)

        after = (
            LancamentoFinanceiro.objects.count(),
            ProjetoKanban.objects.count(),
            EventoSistema.objects.count(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(before, after)

    def test_static_contract_is_local_and_javascript_is_safe(self):
        template = (ROOT / "templates/financeiro/central_contas_receber.html").read_text(encoding="utf-8")
        javascript = (ROOT / "static/financeiro/central_ar.js").read_text(encoding="utf-8")

        self.assertIn("financeiro/central_ar.css", template)
        self.assertIn("financeiro/central_ar.js", template)
        self.assertIn("encodeURIComponent", javascript)
        self.assertIn('replace(/\\D/g, "")', javascript)
        self.assertIn("Olá, ${firstName(payload.cliente)}! Tudo bem?", javascript)
        self.assertIn("window.location.assign(`https://wa.me/", javascript)
        self.assertLess(
            javascript.index("modal.showModal()"),
            javascript.index("window.location.assign(`https://wa.me/"),
        )
        self.assertIn('openWhatsApp.addEventListener("click"', javascript)
        self.assertNotIn("data-lancamento", template)
        self.assertNotIn("innerHTML", javascript)
        self.assertNotIn("fetch(", javascript)
        self.assertNotIn("XMLHttpRequest", javascript)
        for artifact in (template, javascript):
            self.assertNotRegex(artifact, r"(?i)(cdnjs|unpkg|jsdelivr|fonts\.googleapis|react|vue|next|vite|npm)")

    def test_get_only_view_rejects_post(self):
        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 405)
