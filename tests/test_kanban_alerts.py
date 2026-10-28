from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.staticfiles.finders import find
from django.template.loader import render_to_string
from django.test import TestCase

from apps.clientes_agenda.models import Cliente
from apps.core_sistema.context_processors import alertas_globais
from apps.core_sistema.models import EventoSistema
from apps.financeiro.models import LancamentoFinanceiro
from apps.kanban_projetos.models import ProjetoKanban
from apps.kanban_projetos.selectors import orcamentos_vencidos

REFERENCE_DATE = date(2026, 10, 26)


class OverdueBudgetSelectorTests(TestCase):
    def setUp(self):
        self.cliente = Cliente.objects.create(
            nome="Cliente do alerta",
            whatsapp="11999999999",
        )

    def project(self, *, title, stage="2_ORCAMENTO", deadline=None):
        return ProjetoKanban.objects.create(
            cliente=self.cliente,
            titulo_servico=title,
            etapa=stage,
            data_limite_orcamento=deadline,
        )

    def test_selector_uses_explicit_reference_and_excludes_other_stages(self):
        past = self.project(
            title="Prazo anterior",
            deadline=REFERENCE_DATE - timedelta(days=1),
        )
        same_day = self.project(
            title="Prazo igual",
            deadline=REFERENCE_DATE,
        )
        self.project(
            title="Prazo posterior",
            deadline=REFERENCE_DATE + timedelta(days=1),
        )
        self.project(
            title="Fora de orçamento",
            stage="3_APROVADO",
            deadline=REFERENCE_DATE - timedelta(days=1),
        )
        self.project(
            title="Projeto arquivado",
            stage="9_ARQUIVADO",
            deadline=REFERENCE_DATE - timedelta(days=1),
        )

        result = orcamentos_vencidos(data_referencia=REFERENCE_DATE)

        self.assertCountEqual(result.values_list("pk", flat=True), [past.pk, same_day.pk])

    def test_reference_date_changes_the_read_result(self):
        project = self.project(title="Prazo móvel", deadline=REFERENCE_DATE)

        before_deadline = orcamentos_vencidos(
            data_referencia=REFERENCE_DATE - timedelta(days=1),
        )
        on_deadline = orcamentos_vencidos(data_referencia=REFERENCE_DATE)

        self.assertFalse(before_deadline.filter(pk=project.pk).exists())
        self.assertTrue(on_deadline.filter(pk=project.pk).exists())

    def test_model_wrapper_preserves_public_interface(self):
        project = self.project(title="Wrapper", deadline=REFERENCE_DATE)

        with patch(
            "apps.kanban_projetos.models.timezone.localdate",
            return_value=REFERENCE_DATE,
        ):
            self.assertTrue(project.is_orcamento_vencido)

        project.etapa = "9_ARQUIVADO"
        self.assertFalse(project.is_orcamento_vencido)


class GlobalBudgetAlertReadTests(TestCase):
    def setUp(self):
        self.cliente = Cliente.objects.create(
            nome="Cliente global",
            whatsapp="11888888888",
        )

    def project(self, title, *, stage="2_ORCAMENTO", deadline=REFERENCE_DATE):
        return ProjetoKanban.objects.create(
            cliente=self.cliente,
            titulo_servico=title,
            etapa=stage,
            data_limite_orcamento=deadline,
        )

    @patch("apps.core_sistema.context_processors.timezone.localdate", return_value=REFERENCE_DATE)
    def test_context_processor_returns_exact_count_for_multiple_overdue_budgets(self, _today):
        self.project("Vencido 1", deadline=REFERENCE_DATE - timedelta(days=2))
        self.project("Vencido 2", deadline=REFERENCE_DATE)
        self.project("Ainda no prazo", deadline=REFERENCE_DATE + timedelta(days=1))
        self.project("Outra etapa", stage="4_PRODUCAO", deadline=REFERENCE_DATE - timedelta(days=3))
        self.project("Arquivado", stage="9_ARQUIVADO", deadline=REFERENCE_DATE - timedelta(days=4))

        contexto = alertas_globais(None)

        self.assertEqual(contexto["orcamentos_atrasados_count"], 2)
        self.assertEqual(len(contexto["orcamentos_atrasados"]), 2)

    @patch("apps.core_sistema.context_processors.timezone.localdate", return_value=REFERENCE_DATE)
    def test_context_processor_has_no_overdue_state(self, _today):
        self.project("Ainda no prazo", deadline=REFERENCE_DATE + timedelta(days=1))

        contexto = alertas_globais(None)

        self.assertEqual(contexto["orcamentos_atrasados_count"], 0)
        self.assertEqual(contexto["orcamentos_atrasados"], [])

    @patch("apps.core_sistema.context_processors.timezone.localdate", return_value=REFERENCE_DATE)
    def test_reading_global_alerts_does_not_create_financial_or_business_events(self, _today):
        project = self.project("Somente leitura", deadline=REFERENCE_DATE)
        project_before = ProjetoKanban.objects.values().get(pk=project.pk)
        financial_count_before = LancamentoFinanceiro.objects.count()
        event_count_before = EventoSistema.objects.count()

        alertas_globais(None)

        self.assertEqual(LancamentoFinanceiro.objects.count(), financial_count_before)
        self.assertEqual(EventoSistema.objects.count(), event_count_before)
        self.assertEqual(ProjetoKanban.objects.values().get(pk=project.pk), project_before)


class GlobalBudgetAlertTemplateTests(TestCase):
    def render_base(self, **context):
        return render_to_string("base.html", context)

    def test_alert_is_rendered_before_main_with_exact_count(self):
        html = self.render_base(orcamentos_atrasados_count=2)

        alert_position = html.index('class="global-budget-alert"')
        main_position = html.index("<main")

        self.assertLess(alert_position, main_position)
        self.assertIn("2 orçamentos vencidos", html)
        self.assertIn('role="alert"', html)
        self.assertIn('aria-live="polite"', html)

    def test_alert_is_absent_when_there_are_no_overdue_budgets(self):
        html = self.render_base(orcamentos_atrasados_count=0)

        self.assertNotIn("global-budget-alert", html)

    def test_dynamic_alert_value_is_escaped_and_css_is_local(self):
        malicious_count = '<script>alert("x")</script>'
        html = self.render_base(orcamentos_atrasados_count=malicious_count)

        self.assertNotIn(malicious_count, html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("core_sistema/global_alerts.css", html)
        self.assertIsNotNone(find("core_sistema/global_alerts.css"))
        self.assertNotIn("cdn", html.lower())

    def test_existing_financial_template_keeps_its_content(self):
        html = render_to_string(
            "financeiro/rentabilidade_projetos.html",
            {
                "available": False,
                "error_message": "",
                "orcamentos_atrasados_count": 0,
            },
        )

        self.assertIn("Rentabilidade por projeto", html)
        self.assertIn("Rentabilidade indisponível", html)
