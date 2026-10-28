from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import RequestFactory, TestCase
from django.urls import reverse

from apps.clientes_agenda.models import Cliente
from apps.core_sistema.models import EventoSistema
from apps.financeiro.models import LancamentoFinanceiro
from apps.kanban_projetos.models import ProjetoKanban
from apps.kanban_projetos.views import kanban_readonly_view

REFERENCE_DATE = date(2026, 10, 26)
LEGACY_STAGES = (
    "1_CONTATO",
    "2_ORCAMENTO",
    "3_APROVADO",
    "4_PRODUCAO",
    "5_ENTREGA",
    "6_FINALIZADO",
)


class KanbanReadonlyTests(TestCase):
    def setUp(self):
        self.client_record = Cliente.objects.create(
            nome="Cliente de teste",
            whatsapp="11999999999",
        )

    def project(
        self,
        title,
        *,
        stage="1_CONTATO",
        budget_deadline=None,
        delivery_deadline=None,
        total=Decimal("0.00"),
        client=None,
    ):
        return ProjetoKanban.objects.create(
            cliente=client or self.client_record,
            titulo_servico=title,
            etapa=stage,
            data_limite_orcamento=budget_deadline,
            data_entrega_prevista=delivery_deadline,
            valor_total=total,
        )

    def get_kanban(self):
        with patch("django.utils.timezone.localdate", return_value=REFERENCE_DATE):
            return self.client.get(reverse("kanban_projetos:kanban_readonly"))

    def test_get_returns_200_with_six_legacy_columns_and_separate_geladeira(self):
        response = self.get_kanban()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [column["code"] for column in response.context["columns"]],
            list(LEGACY_STAGES),
        )
        self.assertEqual(response.context["archived_column"]["code"], "9_ARQUIVADO")
        self.assertContains(response, "Consulta intermediária")
        self.assertContains(response, "Geladeira")
        for _code, label in ProjetoKanban.ETAPA_CHOICES:
            if _code != "9_ARQUIVADO":
                self.assertContains(response, label)

    def test_project_is_rendered_in_its_legacy_column_with_existing_fields(self):
        project = self.project(
            "Cozinha planejada",
            stage="5_ENTREGA",
            delivery_deadline=REFERENCE_DATE + timedelta(days=4),
            total=Decimal("12345.67"),
        )

        response = self.get_kanban()

        columns = {
            column["code"]: column["projects"]
            for column in response.context["columns"]
        }
        self.assertEqual(
            [item["project"].pk for item in columns["5_ENTREGA"]],
            [project.pk],
        )
        self.assertContains(response, "Cozinha planejada")
        self.assertContains(response, "Cliente de teste")
        self.assertContains(response, "Pronto para Entrega")
        self.assertContains(response, "30/10/2026")
        self.assertContains(response, "R$ 12345,67")

    def test_yesterday_and_today_are_overdue_but_tomorrow_is_normal(self):
        yesterday = self.project(
            "Orçamento de ontem",
            stage="2_ORCAMENTO",
            budget_deadline=REFERENCE_DATE - timedelta(days=1),
        )
        today = self.project(
            "Orçamento de hoje",
            stage="2_ORCAMENTO",
            budget_deadline=REFERENCE_DATE,
        )
        tomorrow = self.project(
            "Orçamento de amanhã",
            stage="2_ORCAMENTO",
            budget_deadline=REFERENCE_DATE + timedelta(days=1),
        )

        response = self.get_kanban()
        html = response.content.decode()

        for project in (yesterday, today):
            marker = 'class="kanban-card kanban-card--overdue"'
            project_position = html.index(f'data-project-id="{project.pk}"')
            card_start = html.rfind(marker, 0, project_position)
            self.assertGreater(card_start, -1)
            card_end = html.index("</article>", project_position)
            self.assertIn("Orçamento vencido", html[card_start:card_end])
        tomorrow_marker = f'data-project-id="{tomorrow.pk}"'
        self.assertIn(tomorrow_marker, html)
        tomorrow_start = html.index(tomorrow_marker)
        tomorrow_card_start = html.rfind('<article', 0, tomorrow_start)
        tomorrow_card = html[tomorrow_card_start: html.index("</article>", tomorrow_start)]
        self.assertNotIn("kanban-card--overdue", tomorrow_card)
        self.assertIn("Prazo do orçamento", tomorrow_card)
        self.assertIn("27/10/2026", tomorrow_card)

    def test_multiple_overdue_budgets_keep_exact_global_count(self):
        self.project(
            "Vencido 1",
            stage="2_ORCAMENTO",
            budget_deadline=REFERENCE_DATE - timedelta(days=2),
        )
        self.project(
            "Vencido 2",
            stage="2_ORCAMENTO",
            budget_deadline=REFERENCE_DATE,
        )
        self.project(
            "No prazo",
            stage="2_ORCAMENTO",
            budget_deadline=REFERENCE_DATE + timedelta(days=1),
        )

        response = self.get_kanban()

        self.assertEqual(response.context["orcamentos_atrasados_count"], 2)
        self.assertContains(response, "2 orçamentos vencidos")
        self.assertEqual(response.context["column_counts"]["2_ORCAMENTO"], 3)

    def test_no_overdue_budgets_preserves_projects_and_shows_discreet_state(self):
        project = self.project(
            "Orçamento normal",
            stage="2_ORCAMENTO",
            budget_deadline=REFERENCE_DATE + timedelta(days=1),
        )
        self.project("Em produção", stage="4_PRODUCAO")

        response = self.get_kanban()

        self.assertEqual(response.context["orcamentos_atrasados_count"], 0)
        self.assertNotContains(response, "global-budget-alert")
        self.assertContains(response, "Nenhum orçamento vencido")
        self.assertContains(response, project.titulo_servico)
        self.assertEqual(response.context["column_counts"]["2_ORCAMENTO"], 1)
        self.assertEqual(response.context["column_counts"]["4_PRODUCAO"], 1)

    def test_empty_board_returns_200_with_empty_states(self):
        response = self.get_kanban()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Nenhum projeto nesta etapa.", count=6)
        self.assertContains(response, "A Geladeira está vazia.")

    def test_user_content_is_escaped(self):
        self.client_record.nome = '<script>alert("cliente")</script>'
        self.client_record.save(update_fields=["nome"])
        project = self.project('<script>alert("projeto")</script>')

        response = self.get_kanban()

        self.assertNotContains(response, '<script>alert("projeto")</script>')
        self.assertNotContains(response, '<script>alert("cliente")</script>')
        self.assertContains(response, "&lt;script&gt;alert(&quot;projeto&quot;)&lt;/script&gt;")
        self.assertContains(response, "&lt;script&gt;alert(&quot;cliente&quot;)&lt;/script&gt;")
        self.assertContains(response, f'data-project-id="{project.pk}"')

    def test_get_does_not_mutate_projects_financial_records_or_business_events(self):
        project = self.project(
            "Somente leitura",
            stage="2_ORCAMENTO",
            budget_deadline=REFERENCE_DATE,
            total=Decimal("400.00"),
        )
        project_before = ProjetoKanban.objects.values().get(pk=project.pk)
        financial_count_before = LancamentoFinanceiro.objects.count()
        event_count_before = EventoSistema.objects.count()

        response = self.get_kanban()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            ProjetoKanban.objects.values().get(pk=project.pk),
            project_before,
        )
        self.assertEqual(LancamentoFinanceiro.objects.count(), financial_count_before)
        self.assertEqual(EventoSistema.objects.count(), event_count_before)

    def test_post_is_not_an_authorized_kanban_operation(self):
        before = ProjetoKanban.objects.count()

        response = self.client.post(reverse("kanban_projetos:kanban_readonly"))

        self.assertEqual(response.status_code, 405)
        self.assertEqual(ProjetoKanban.objects.count(), before)

    def test_view_fetches_projects_and_clients_with_one_query(self):
        self.project("Consulta eficiente")
        request = RequestFactory().get(reverse("kanban_projetos:kanban_readonly"))

        with patch("apps.kanban_projetos.views.render") as render, self.assertNumQueries(1):
            response = kanban_readonly_view(request)

        self.assertIs(response, render.return_value)
        context = render.call_args.args[2]
        self.assertEqual(
            context["columns"][0]["projects"][0]["project"].cliente,
            self.client_record,
        )

    def test_financial_pages_remain_accessible(self):
        central = self.client.get(reverse("financeiro:central_contas_receber"))
        profitability = self.client.get(reverse("financeiro:rentabilidade_projetos"))

        self.assertEqual(central.status_code, 200)
        self.assertContains(central, "Central de contas a receber")
        self.assertEqual(profitability.status_code, 200)
        self.assertContains(profitability, "Rentabilidade por projeto")
