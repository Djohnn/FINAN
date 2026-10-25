"""Frontend contract tests for the read-only project profitability screens."""

from dataclasses import fields
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.contrib.staticfiles.finders import find
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.clientes_agenda.models import Cliente
from apps.core_sistema.models import EventoSistema
from apps.financeiro.models import LancamentoFinanceiro
from apps.financeiro.selectors import (
    CustoDiretoProjeto,
    ProjetosRentabilidade,
    RentabilidadeProjeto,
    rentabilidade_clientes,
)
from apps.financeiro.views import _money, _profitability_money
from apps.kanban_projetos.models import ProjetoKanban

D = Decimal
ROOT = Path(__file__).resolve().parent.parent
STAGES = (
    "1_CONTATO",
    "2_ORCAMENTO",
    "3_APROVADO",
    "4_PRODUCAO",
    "5_ENTREGA",
    "6_FINALIZADO",
    "9_ARQUIVADO",
)


def make_result(
    project_id=10,
    *,
    title="Armário da cozinha",
    stage="4_PRODUCAO",
    state="DISPONIVEL",
    inconsistencies=(),
    contract="18500.00",
    received="11000.00",
    pending="7500.00",
    direct_cost="8920.00",
    profit="9580.00",
    margin="51.8",
    cash_in="11000.00",
    cash_out="6200.00",
    cash_net="4800.00",
    costs=None,
):
    if costs is None:
        costs = (
            CustoDiretoProjeto("MATERIA_PRIMA", D("5500.00"), D("2000.00"), D("3500.00")),
            CustoDiretoProjeto("FUNCIONARIO", D("2600.00"), D("400.00"), D("2200.00")),
            CustoDiretoProjeto("OUTROS", D("820.00"), D("320.00"), D("500.00")),
        )
    values = {
        "projeto_id": project_id,
        "titulo_servico": title,
        "etapa": stage,
        "estado": state,
        "inconsistencias": tuple(inconsistencies),
        "valor_contratado": None if contract is None else D(contract),
        "valor_recebido": None if received is None else D(received),
        "saldo_a_receber": None if pending is None else D(pending),
        "custos_diretos_por_categoria": costs,
        "custos_diretos": None if direct_cost is None else D(direct_cost),
        "lucro_direto": None if profit is None else D(profit),
        "margem_direta_percentual": None if margin is None else D(margin),
        "entradas_realizadas": None if cash_in is None else D(cash_in),
        "saidas_realizadas": None if cash_out is None else D(cash_out),
        "caixa_liquido_realizado": None if cash_net is None else D(cash_net),
    }
    return RentabilidadeProjeto(**values)


class ProjectProfitabilityFrontendTests(TestCase):
    def setUp(self):
        self.overview_url = reverse("financeiro:rentabilidade_projetos")
        self.detail_url = reverse("financeiro:rentabilidade_projeto", kwargs={"projeto_id": 10})

    def render_overview(self, results):
        with patch(
            "apps.financeiro.views.rentabilidade_projetos",
            return_value=ProjetosRentabilidade(results),
        ) as profitability_selector, patch(
            "apps.financeiro.views.rentabilidade_clientes",
            return_value={result.projeto_id: "Cliente Real" for result in results},
        ) as customer_selector:
            response = self.client.get(self.overview_url)
        return response, (profitability_selector, customer_selector)

    def render_detail(self, result):
        with (
            patch("apps.financeiro.views.rentabilidade_projeto", return_value=result) as selector,
            patch("apps.financeiro.views.rentabilidade_clientes", return_value={result.projeto_id: "Cliente Real"}),
        ):
            response = self.client.get(
                reverse("financeiro:rentabilidade_projeto", kwargs={"projeto_id": result.projeto_id})
            )
        return response, selector

    def test_named_overview_route_renders_read_only_screen(self):
        response, _selectors = self.render_overview(())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Rentabilidade por projeto")
        self.assertContains(response, "Consulta somente leitura")
        self.assertContains(response, "Como ler o resultado")

    def test_named_detail_route_renders_read_only_screen(self):
        response, _selector = self.render_detail(make_result())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Resultado econômico direto")
        self.assertContains(response, "Caixa realizado")
        self.assertContains(response, "Voltar para todos os projetos")

    def test_existing_ar_and_admin_routes_remain_available(self):
        self.assertEqual(self.client.get(reverse("financeiro:central_contas_receber")).status_code, 200)
        self.assertIn(self.client.get("/admin/").status_code, {200, 302})

    def test_overview_uses_integrated_selector_and_presentation_lookup(self):
        result = make_result()
        response, selectors = self.render_overview((result,))

        self.assertEqual(response.status_code, 200)
        selectors[0].assert_called_once_with()
        selectors[1].assert_called_once_with(projeto_ids=(result.projeto_id,))

    def test_detail_uses_integrated_selector_for_requested_project(self):
        result = make_result(project_id=17)
        response, selector = self.render_detail(result)

        self.assertEqual(response.status_code, 200)
        selector.assert_called_once_with(projeto_id=17)

    def test_all_seven_kanban_stages_remain_visible(self):
        results = tuple(
            make_result(project_id=index + 1, title=stage, stage=stage, state="SEM_CONTRATO", contract="0.00", received="0.00", pending="0.00", direct_cost="0.00", profit="0.00", margin=None, cash_in="0.00", cash_out="0.00", cash_net="0.00")
            for index, stage in enumerate(STAGES)
        )
        response, _selectors = self.render_overview(results)

        for stage in STAGES:
            self.assertContains(response, stage)

    def test_positive_result_and_exact_brazilian_money_are_displayed(self):
        response, _selector = self.render_detail(make_result())

        self.assertContains(response, "R$ 18.500,00")
        self.assertContains(response, "R$ 8.920,00")
        self.assertContains(response, "R$ 9.580,00")
        self.assertContains(response, "51,8%")
        self.assertContains(response, "Resultado direto disponível")

    def test_shared_ar_money_formatter_and_profitability_formatter_are_separate(self):
        self.assertEqual(_money(D("3703.68")), "R$ 3.703,68")
        self.assertEqual(_money(D("0.00")), "R$ 0,00")
        self.assertEqual(_money(D("-2550.00")), "R$ -2.550,00")
        self.assertEqual(_profitability_money(None), "Não disponível")
        self.assertEqual(_profitability_money(D("18500.50")), "R$ 18.500,50")
        self.assertEqual(_profitability_money(D("-2550.00")), "− R$ 2.550,00")

    def test_overview_distinguishes_positive_zero_and_negative_profit(self):
        results = (
            make_result(project_id=21, profit="100.00", margin="0.5"),
            make_result(project_id=22, profit="0.00", margin="0.0"),
            make_result(project_id=23, profit="-100.00", margin="-0.5"),
        )
        response, _selectors = self.render_overview(results)
        labels = {
            project["result"].projeto_id: project["outcome_label"]
            for project in response.context["projects"]
        }

        self.assertEqual(labels[21], "Resultado positivo")
        self.assertEqual(labels[22], "Sem lucro nem prejuízo direto")
        self.assertEqual(labels[23], "Prejuízo direto")
        self.assertContains(response, "Sem lucro nem prejuízo direto")

    def test_overview_applies_sem_contrato_state_precedence(self):
        results = (
            make_result(
                project_id=24,
                state="SEM_CONTRATO",
                contract="0.00",
                received="0.00",
                pending="0.00",
                direct_cost="650.00",
                profit="-650.00",
                margin=None,
            ),
            make_result(
                project_id=25,
                state="SEM_CONTRATO",
                contract="0.00",
                received="0.00",
                pending="0.00",
                direct_cost="0.00",
                profit="0.00",
                margin=None,
            ),
            make_result(project_id=26, profit="-100.00", margin="-0.5"),
            make_result(
                project_id=27,
                state="INCONSISTENTE",
                inconsistencies=("PAGO_SEM_DATA_PAGAMENTO",),
                contract=None,
                received=None,
                pending=None,
                direct_cost=None,
                profit=None,
                margin=None,
                cash_in=None,
                cash_out=None,
                cash_net=None,
                costs=None,
            ),
        )
        response, _selectors = self.render_overview(results)
        rows = {project["result"].projeto_id: project for project in response.context["projects"]}

        self.assertEqual(rows[24]["outcome_label"], "Sem contrato · custos já registrados")
        self.assertNotEqual(rows[24]["outcome_label"], "Prejuízo direto")
        self.assertEqual(rows[25]["outcome_label"], "Sem contrato")
        self.assertEqual(rows[26]["outcome_label"], "Prejuízo direto")
        self.assertEqual(rows[27]["outcome_label"], "Resultado indisponível")
        self.assertEqual(rows[27]["contracted"], "Não disponível")
        self.assertEqual(rows[27]["direct_costs"], "Não disponível")
        self.assertEqual(rows[27]["profit"], "Não disponível")

    def test_pending_payment_warning_uses_neutral_lancamento_message(self):
        result = make_result(inconsistencies=("PENDENTE_COM_DATA_PAGAMENTO",))
        response, _selector = self.render_detail(result)

        self.assertContains(response, "Há um lançamento pendente com data de pagamento preenchida")
        self.assertNotContains(response, "Há um custo pendente com data de pagamento preenchida")

    def test_negative_result_is_visible_and_not_hidden_by_color(self):
        result = make_result(
            title="Cozinha planejada",
            contract="12400.00",
            received="6200.00",
            pending="6200.00",
            direct_cost="14950.00",
            profit="-2550.00",
            margin="-20.6",
            cash_in="6200.00",
            cash_out="11300.00",
            cash_net="-5100.00",
        )
        response, _selector = self.render_detail(result)

        self.assertContains(response, "− R$ 2.550,00")
        self.assertContains(response, "−20,6%")
        self.assertContains(response, "prejuízo direto")

    def test_sem_contrato_keeps_costs_and_marks_margin_unavailable(self):
        result = make_result(
            state="SEM_CONTRATO",
            contract="0.00",
            received="0.00",
            pending="0.00",
            direct_cost="650.00",
            profit="-650.00",
            margin=None,
            cash_in="0.00",
            cash_out="650.00",
            cash_net="-650.00",
            costs=(
                CustoDiretoProjeto("MATERIA_PRIMA", D("650.00"), D("0.00"), D("650.00")),
                CustoDiretoProjeto("FUNCIONARIO", D("0.00"), D("0.00"), D("0.00")),
                CustoDiretoProjeto("OUTROS", D("0.00"), D("0.00"), D("0.00")),
            ),
        )
        response, _selector = self.render_detail(result)

        self.assertContains(response, "Sem contrato")
        self.assertContains(response, "Não calculada")
        self.assertContains(response, "não representa uma margem final de projeto contratado")
        self.assertContains(response, "R$ 650,00")

    def test_inconsistent_state_hides_all_financial_values(self):
        result = make_result(
            state="INCONSISTENTE",
            inconsistencies=("PAGO_SEM_DATA_PAGAMENTO",),
            contract=None,
            received=None,
            pending=None,
            direct_cost=None,
            profit=None,
            margin=None,
            cash_in=None,
            cash_out=None,
            cash_net=None,
            costs=None,
        )
        response, _selector = self.render_detail(result)

        self.assertContains(response, "Inconsistente")
        self.assertContains(response, "Resultado indisponível por inconsistência")
        self.assertContains(response, "Não disponível")
        self.assertContains(response, "Há um lançamento pago sem data de pagamento")
        self.assertNotContains(response, "R$ 18.500,00")
        self.assertNotContains(response, "Lucro direto</span>")

    def test_fatal_inconsistency_does_not_leak_partial_financial_result(self):
        result = make_result(
            state="INCONSISTENTE",
            inconsistencies=("STATUS_INVALIDO", "VALOR_MONETARIO_INVALIDO"),
            contract=None,
            received=None,
            pending=None,
            direct_cost=None,
            profit=None,
            margin=None,
            cash_in=None,
            cash_out=None,
            cash_net=None,
            costs=None,
        )
        response, _selector = self.render_overview((result,))

        self.assertContains(response, "Resultado indisponível")
        self.assertContains(response, "Há um lançamento com status inválido")
        self.assertContains(response, "Há um valor financeiro inválido")
        self.assertNotContains(response, "R$ 18.500,00")
        self.assertNotContains(response, "R$ 9.580,00")

    def test_pending_and_paid_costs_remain_separate(self):
        response, _selector = self.render_detail(make_result())

        self.assertContains(response, "Pendente")
        self.assertContains(response, "Pago")
        self.assertContains(response, "R$ 2.000,00")
        self.assertContains(response, "R$ 3.500,00")
        self.assertContains(response, "R$ 400,00")
        self.assertContains(response, "R$ 2.200,00")

    def test_cash_and_direct_profit_are_explicitly_separated(self):
        response, _selector = self.render_detail(make_result())

        self.assertContains(response, "Resultado econômico direto")
        self.assertContains(response, "Caixa líquido realizado")
        self.assertContains(response, "R$ 9.580,00")
        self.assertContains(response, "R$ 4.800,00")

    def test_actual_selector_codes_are_translated_without_traceback(self):
        result = make_result(
            inconsistencies=("CONTRATO_DIVERGE_DO_LEDGER", "PENDENTE_COM_DATA_PAGAMENTO", "VALOR_ZERO")
        )
        response, _selector = self.render_detail(result)

        self.assertContains(response, "O contrato registrado não bate com as entradas ligadas ao projeto")
        self.assertContains(response, "Há um lançamento pendente com data de pagamento preenchida")
        self.assertContains(response, "Existe um lançamento com valor zero")
        self.assertNotContains(response, "Traceback")

    def test_empty_overview_has_understandable_empty_state(self):
        response, _selectors = self.render_overview(())

        self.assertContains(response, "Quando ainda não houver projetos")
        self.assertContains(response, "Projetos sem contrato continuam visíveis")

    def test_xss_content_is_escaped_by_template(self):
        result = make_result(title="<script>alert('x')</script>")
        response, _selector = self.render_overview((result,))

        self.assertNotContains(response, "<script>alert('x')</script>", html=True)
        self.assertContains(response, "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;")

    def test_unknown_project_is_controlled_not_found_without_traceback(self):
        with patch("apps.financeiro.views.rentabilidade_projeto", side_effect=ValueError("Projeto não encontrado.")):
            response = self.client.get(
                reverse("financeiro:rentabilidade_projeto", kwargs={"projeto_id": 999999})
            )

        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "Projeto não encontrado", status_code=404)
        self.assertNotIn(b"Traceback", response.content)

    def test_get_routes_have_no_mutation_controls_or_post_support(self):
        response, _selector = self.render_detail(make_result())

        self.assertNotContains(response, "DADOS ILUSTRATIVOS")
        self.assertNotContains(response, "method=\"post\"")
        self.assertNotContains(response, "Demonstração")
        self.assertEqual(self.client.post(self.overview_url).status_code, 405)
        self.assertEqual(self.client.post(self.detail_url).status_code, 405)

    def test_get_does_not_write_financial_project_or_history_rows(self):
        result = make_result()
        before = (
            LancamentoFinanceiro.objects.count(),
            ProjetoKanban.objects.count(),
            EventoSistema.objects.count(),
        )
        self.render_detail(result)
        after = (
            LancamentoFinanceiro.objects.count(),
            ProjetoKanban.objects.count(),
            EventoSistema.objects.count(),
        )

        self.assertEqual(before, after)

    def test_customer_name_lookup_uses_structured_relation_in_one_query(self):
        customer = Cliente.objects.create(nome="Cliente Estruturado", whatsapp="11999990000")
        project = ProjetoKanban.objects.create(
            cliente=customer,
            titulo_servico="Projeto estruturado",
            etapa="1_CONTATO",
            data_limite_orcamento=date(2026, 10, 24),
            valor_total=D("0.00"),
        )

        with CaptureQueriesContext(connection) as queries:
            names = rentabilidade_clientes(projeto_ids=(project.pk,))

        self.assertEqual(names, {project.pk: "Cliente Estruturado"})
        self.assertEqual(len(queries), 1)

    def test_frozen_profitability_dataclasses_are_not_changed(self):
        self.assertEqual(
            tuple(field.name for field in fields(RentabilidadeProjeto)),
            (
                "projeto_id", "titulo_servico", "etapa", "estado", "inconsistencias",
                "valor_contratado", "valor_recebido", "saldo_a_receber",
                "custos_diretos_por_categoria", "custos_diretos", "lucro_direto",
                "margem_direta_percentual", "entradas_realizadas", "saidas_realizadas",
                "caixa_liquido_realizado",
            ),
        )

    def test_responsive_styles_preserve_box_model_and_stack_costs(self):
        stylesheet = (ROOT / "static" / "financeiro" / "project_profitability.css").read_text(encoding="utf-8")

        self.assertIn("* { box-sizing: border-box; }", stylesheet)
        self.assertIn("@media (max-width: 680px)", stylesheet)
        self.assertIn(".cost-row { min-width: 0; grid-template-columns: repeat(2, minmax(0, 1fr));", stylesheet)
        self.assertIn(".cash-list dd { white-space: normal;", stylesheet)

    def test_project_profitability_css_is_discoverable(self):
        found = find("financeiro/project_profitability.css")

        self.assertIsNotNone(found)
        self.assertEqual(Path(found).resolve(), (ROOT / "static" / "financeiro" / "project_profitability.css").resolve())

    def test_central_ar_css_is_discoverable(self):
        found = find("financeiro/central_ar.css")

        self.assertIsNotNone(found)
        self.assertEqual(Path(found).resolve(), (ROOT / "static" / "financeiro" / "central_ar.css").resolve())

    def test_central_ar_javascript_is_discoverable(self):
        found = find("financeiro/central_ar.js")

        self.assertIsNotNone(found)
        self.assertEqual(Path(found).resolve(), (ROOT / "static" / "financeiro" / "central_ar.js").resolve())

    def test_templates_reference_expected_stylesheets(self):
        overview = (ROOT / "templates" / "financeiro" / "rentabilidade_projetos.html").read_text(encoding="utf-8")
        detail = (ROOT / "templates" / "financeiro" / "rentabilidade_projeto.html").read_text(encoding="utf-8")
        ar = (ROOT / "templates" / "financeiro" / "central_contas_receber.html").read_text(encoding="utf-8")

        self.assertIn("financeiro/project_profitability.css", overview)
        self.assertIn("financeiro/project_profitability.css", detail)
        self.assertIn("financeiro/central_ar.css", ar)
        self.assertIn("financeiro/central_ar.js", ar)
