"""Focused contracts for the Customer 360 read-only surface."""

from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.clientes_agenda.models import AgendaContato, Cliente
from apps.clientes_agenda.selectors import clientes_index, cliente_360
from apps.core_sistema.models import EventoSistema
from apps.financeiro.models import LancamentoFinanceiro
from apps.kanban_projetos.models import ProjetoKanban


D = Decimal
REFERENCE = date(2026, 10, 29)


class Customer360FixturesMixin:
    def make_customer(self, name="Mariana Alves", phone="8190000101", **kwargs):
        return Cliente.objects.create(nome=name, whatsapp=phone, **kwargs)

    def make_project(
        self,
        customer,
        title="Cozinha planejada",
        stage="1_CONTATO",
        contract="0.00",
        **kwargs,
    ):
        if stage == "2_ORCAMENTO" and "data_limite_orcamento" not in kwargs:
            kwargs["data_limite_orcamento"] = REFERENCE
        return ProjetoKanban.objects.create(
            cliente=customer,
            titulo_servico=title,
            etapa=stage,
            valor_total=D(contract),
            **kwargs,
        )

    def make_ledger(
        self,
        project=None,
        value="100.00",
        status="PAGO",
        payment_date=REFERENCE,
        category="SERVICO_CLIENTE",
        description="Recebimento comercial",
    ):
        return LancamentoFinanceiro.objects.create(
            tipo="ENTRADA", categoria=category, projeto=project,
            descricao=description, valor=D(value), forma_pagamento="PIX",
            data_vencimento=REFERENCE, data_pagamento=payment_date, status=status,
        )

    def make_event(
        self, event_type, domain, entity_type=None, entity_id=None,
        metadata=None, description="Evento de teste",
    ):
        return EventoSistema.objects.create(
            tipo=event_type, dominio=domain, entidade_tipo=entity_type,
            entidade_id=None if entity_id is None else str(entity_id),
            descricao=description, metadata=metadata or {},
        )


class Customer360SelectorTests(Customer360FixturesMixin, TestCase):
    def test_index_includes_customer_without_projects(self):
        customer = self.make_customer("Cliente sem projeto")
        result = clientes_index(query="", data_referencia=REFERENCE)
        self.assertEqual(result.total_cadastrados, 1)
        self.assertEqual(result.rows[0].cliente_id, customer.pk)
        self.assertEqual(result.rows[0].projetos_count, 0)

    def test_index_searches_by_name_and_phone(self):
        self.make_customer("Mariana Alves", "8190000101")
        self.make_customer("Rafael Nogueira", "8190000102")
        self.assertEqual(
            [row.nome for row in clientes_index(query="Mariana", data_referencia=REFERENCE).rows],
            ["Mariana Alves"],
        )
        self.assertEqual(
            [row.nome for row in clientes_index(query="90000102", data_referencia=REFERENCE).rows],
            ["Rafael Nogueira"],
        )

    def test_index_reports_filtered_empty_distinct_from_empty_database(self):
        self.make_customer("Mariana Alves")
        self.make_customer("Rafael Nogueira")
        result = clientes_index(query="inexistente", data_referencia=REFERENCE)
        self.assertEqual(result.rows, ())
        self.assertEqual(result.total_cadastrados, 2)

    def test_detail_customer_without_projects_has_empty_collections(self):
        customer = self.make_customer("Cliente sem projeto")
        result = cliente_360(cliente_id=customer.pk, data_referencia=REFERENCE)
        self.assertEqual(result.projetos, ())
        self.assertEqual(result.agenda_overdue_or_today, ())
        self.assertEqual(result.agenda_future, ())
        self.assertEqual(result.agenda_completed, ())
        self.assertEqual(result.financeiro.total_contratado, D("0.00"))
        self.assertEqual(result.financeiro.total_recebido, D("0.00"))
        self.assertEqual(result.financeiro.saldo_a_receber, D("0.00"))

    def test_detail_aggregates_multiple_projects_using_project_profitability_contract(self):
        customer = self.make_customer()
        first = self.make_project(customer, "Cozinha", "4_PRODUCAO", "1000.00")
        second = self.make_project(customer, "Painel", "9_ARQUIVADO", "2000.00")
        self.make_ledger(first, "400.00", "PAGO")
        self.make_ledger(first, "600.00", "PENDENTE", None)
        self.make_ledger(second, "1000.00", "PAGO")
        self.make_ledger(second, "1000.00", "PENDENTE", None)
        result = cliente_360(cliente_id=customer.pk, data_referencia=REFERENCE)
        self.assertEqual(len(result.projetos), 2)
        self.assertEqual(result.financeiro.estado, "DISPONIVEL")
        self.assertEqual(result.financeiro.total_contratado, D("3000.00"))
        self.assertEqual(result.financeiro.total_recebido, D("1400.00"))
        self.assertEqual(result.financeiro.saldo_a_receber, D("1600.00"))

    def test_detail_keeps_all_stages_archived_reason_and_no_contract_visible(self):
        customer = self.make_customer()
        for stage in (
            "1_CONTATO", "2_ORCAMENTO", "3_APROVADO", "4_PRODUCAO",
            "5_ENTREGA", "6_FINALIZADO", "9_ARQUIVADO",
        ):
            self.make_project(
                customer, title=stage, stage=stage,
                contract="0.00" if stage in {"1_CONTATO", "2_ORCAMENTO"} else "100.00",
                motivo_arquivamento="ADIOU_OBRA" if stage == "9_ARQUIVADO" else "",
                observacao_arquivamento="Cliente pediu retorno depois" if stage == "9_ARQUIVADO" else "",
            )
        result = cliente_360(cliente_id=customer.pk, data_referencia=REFERENCE)
        self.assertEqual({project.etapa for project in result.projetos}, {
            "1_CONTATO", "2_ORCAMENTO", "3_APROVADO", "4_PRODUCAO",
            "5_ENTREGA", "6_FINALIZADO", "9_ARQUIVADO",
        })
        archived = next(project for project in result.projetos if project.etapa == "9_ARQUIVADO")
        no_contract = next(project for project in result.projetos if project.etapa == "1_CONTATO")
        self.assertEqual(archived.motivo_arquivamento_label, "Adiou obra")
        self.assertEqual(archived.observacao_arquivamento, "Cliente pediu retorno depois")
        self.assertEqual(no_contract.financeiro.estado, "SEM_CONTRATO")

    def test_inconsistent_project_hides_entire_customer_financial_summary(self):
        customer = self.make_customer()
        project = self.make_project(customer, contract="100.00")
        self.make_ledger(project, "100.00", "PAGO", payment_date=None)
        result = cliente_360(cliente_id=customer.pk, data_referencia=REFERENCE)
        self.assertEqual(result.financeiro.estado, "INCONSISTENTE")
        self.assertIsNone(result.financeiro.total_contratado)
        self.assertIsNone(result.financeiro.total_recebido)
        self.assertIsNone(result.financeiro.saldo_a_receber)
        self.assertTrue(result.financeiro.warnings)

    def test_non_fatal_financial_warnings_remain_visible(self):
        customer = self.make_customer()
        project = self.make_project(customer, contract="100.00")
        self.make_ledger(project, "40.00", "PENDENTE", payment_date=REFERENCE)
        result = cliente_360(cliente_id=customer.pk, data_referencia=REFERENCE)
        self.assertEqual(result.financeiro.estado, "DISPONIVEL")
        self.assertIn("CONTRATO_DIVERGE_DO_LEDGER", result.financeiro.warning_codes)
        self.assertIn("PENDENTE_COM_DATA_PAGAMENTO", result.financeiro.warning_codes)

    def test_agenda_separates_overdue_today_future_and_completed(self):
        customer = self.make_customer()
        project = self.make_project(customer)
        overdue = AgendaContato.objects.create(
            cliente=customer, projeto=project, tipo="LIGACAO_MANUAL",
            data_agendada=date(2026, 10, 27), realizado=False,
        )
        today = AgendaContato.objects.create(
            cliente=customer, projeto=project, tipo="RETORNO_ORCAMENTO",
            data_agendada=REFERENCE, realizado=False,
        )
        future = AgendaContato.objects.create(
            cliente=customer, projeto=project, tipo="POS_VENDA_30_DIAS",
            data_agendada=date(2026, 11, 5), realizado=False,
        )
        completed = AgendaContato.objects.create(
            cliente=customer, projeto=project, tipo="POS_VENDA_30_DIAS",
            data_agendada=date(2026, 10, 1), realizado=True,
            nivel_satisfacao="SATISFEITO", feedback_cliente="Cliente muito satisfeito",
        )
        result = cliente_360(cliente_id=customer.pk, data_referencia=REFERENCE)
        self.assertEqual([item.contato_id for item in result.agenda_overdue_or_today], [overdue.pk, today.pk])
        self.assertEqual([item.contato_id for item in result.agenda_future], [future.pk])
        self.assertEqual([item.contato_id for item in result.agenda_completed], [completed.pk])
        self.assertEqual(result.agenda_completed[0].nivel_satisfacao_label, "Satisfeito")
        self.assertEqual(result.agenda_completed[0].feedback_cliente, "Cliente muito satisfeito")

    def test_history_maps_project_agenda_and_structured_financial_events(self):
        customer = self.make_customer()
        project = self.make_project(customer, contract="100.00")
        contact = AgendaContato.objects.create(
            cliente=customer, projeto=project, tipo="LIGACAO_MANUAL",
            data_agendada=REFERENCE, realizado=True,
            feedback_cliente="Cliente respondeu com detalhes",
        )
        ledger = self.make_ledger(project, "100.00")
        self.make_event("ORCAMENTO_APROVADO", "KANBAN", "ProjetoKanban", project.pk)
        self.make_event("CONTATO_CONCLUIDO", "AGENDA", "AgendaContato", contact.pk)
        self.make_event("LANCAMENTO_QUITADO", "FINANCEIRO", "LancamentoFinanceiro", ledger.pk, {"valor": "100.00"})
        self.make_event("PAGAMENTO_FUNCIONARIO_CRIADO", "EQUIPE", "Funcionario", 1, {"lancamento_id": str(ledger.pk), "valor": "30.00"})
        unrelated = self.make_project(self.make_customer("Outro cliente"), contract="50.00")
        unrelated_ledger = self.make_ledger(unrelated, "50.00")
        self.make_event("PAGAMENTO_FUNCIONARIO_CRIADO", "EQUIPE", "Funcionario", 2, {"lancamento_id": str(unrelated_ledger.pk), "valor": "20.00"})
        self.make_event("BACKUP_CONCLUIDO", "BACKUP", metadata={})
        self.make_event("RESTAURACAO_CONCLUIDA", "RESTAURACAO", metadata={})
        result = cliente_360(cliente_id=customer.pk, data_referencia=REFERENCE)
        event_types = {event.tipo for event in result.eventos}
        self.assertIn("ORCAMENTO_APROVADO", event_types)
        self.assertIn("CONTATO_CONCLUIDO", event_types)
        self.assertIn("LANCAMENTO_QUITADO", event_types)
        self.assertIn("PAGAMENTO_FUNCIONARIO_CRIADO", event_types)
        self.assertNotIn("BACKUP_CONCLUIDO", event_types)
        self.assertNotIn("RESTAURACAO_CONCLUIDA", event_types)
        payment_event = next(event for event in result.eventos if event.tipo == "PAGAMENTO_FUNCIONARIO_CRIADO")
        self.assertEqual(payment_event.projeto_id, project.pk)

    def test_history_initial_page_is_bounded_and_continuation_is_bounded(self):
        customer = self.make_customer()
        project = self.make_project(customer)
        for _index in range(55):
            self.make_event("PROJETO_FINALIZADO", "KANBAN", "ProjetoKanban", project.pk)
        first = cliente_360(cliente_id=customer.pk, data_referencia=REFERENCE, history_page=1)
        second = cliente_360(cliente_id=customer.pk, data_referencia=REFERENCE, history_page=2)
        self.assertEqual(len(first.eventos), 50)
        self.assertTrue(first.history_has_more)
        self.assertEqual(first.history_next_page, 2)
        self.assertEqual(len(second.eventos), 5)
        self.assertFalse(second.history_has_more)

    def test_detail_query_count_does_not_grow_linearly_with_project_count(self):
        small_customer = self.make_customer("Cliente pequeno")
        self.make_project(small_customer, contract="10.00")
        with CaptureQueriesContext(connection) as small_queries:
            cliente_360(cliente_id=small_customer.pk, data_referencia=REFERENCE)
        large_customer = self.make_customer("Cliente grande")
        for index in range(31):
            self.make_project(large_customer, title=f"Projeto {index}", contract="10.00")
        with CaptureQueriesContext(connection) as large_queries:
            cliente_360(cliente_id=large_customer.pk, data_referencia=REFERENCE)
        self.assertLessEqual(len(large_queries), len(small_queries) + 3)

    def test_contract_without_ledger_shows_divergence_warning(self):
        customer = self.make_customer()
        project = self.make_project(customer, contract="500.00")

        result = cliente_360(cliente_id=customer.pk, data_referencia=REFERENCE)

        project_result = result.projetos[0].financeiro
        self.assertEqual(project_result.estado, "DISPONIVEL")
        self.assertIn("CONTRATO_DIVERGE_DO_LEDGER", project_result.warning_codes)

    def test_archived_project_with_value_stays_in_customer_total(self):
        customer = self.make_customer()
        project = self.make_project(customer, stage="9_ARQUIVADO", contract="750.00", motivo_arquivamento="SEM_RETORNO")

        result = cliente_360(cliente_id=customer.pk, data_referencia=REFERENCE)

        self.assertEqual(result.financeiro.total_contratado, D("750.00"))
        self.assertEqual(result.projetos[0].projeto_id, project.pk)

    def test_completed_contact_exposes_human_satisfaction_and_feedback(self):
        customer = self.make_customer()
        contact = AgendaContato.objects.create(
            cliente=customer, tipo="POS_VENDA_30_DIAS", data_agendada=REFERENCE,
            realizado=True, nivel_satisfacao="AJUSTE_SOLICITADO",
            feedback_cliente="Solicitou ajuste no acabamento",
        )

        result = cliente_360(cliente_id=customer.pk, data_referencia=REFERENCE)

        self.assertEqual(result.agenda_completed[0].contato_id, contact.pk)
        self.assertEqual(result.agenda_completed[0].nivel_satisfacao_label, "Ajuste Solicitado")
        self.assertEqual(result.agenda_completed[0].feedback_cliente, "Solicitou ajuste no acabamento")

    def test_project_event_maps_by_structured_project_identity(self):
        customer = self.make_customer()
        project = self.make_project(customer)
        self.make_event("PROJETO_FINALIZADO", "KANBAN", "ProjetoKanban", project.pk)

        result = cliente_360(cliente_id=customer.pk, data_referencia=REFERENCE)

        self.assertEqual(result.eventos[0].projeto_id, project.pk)
        self.assertEqual(result.eventos[0].tipo, "PROJETO_FINALIZADO")

    def test_agenda_event_maps_by_structured_contact_identity(self):
        customer = self.make_customer()
        contact = AgendaContato.objects.create(
            cliente=customer, tipo="LIGACAO_MANUAL", data_agendada=REFERENCE,
            realizado=True, feedback_cliente="Cliente respondeu com detalhes",
        )
        self.make_event("CONTATO_CONCLUIDO", "AGENDA", "AgendaContato", contact.pk)

        result = cliente_360(cliente_id=customer.pk, data_referencia=REFERENCE)

        self.assertEqual(result.eventos[0].contato_id, contact.pk)
        self.assertIsNone(result.eventos[0].projeto_id)

    def test_financial_event_maps_through_lancamento_to_project(self):
        customer = self.make_customer()
        project = self.make_project(customer, contract="100.00")
        ledger = self.make_ledger(project, "100.00")
        self.make_event("LANCAMENTO_QUITADO", "FINANCEIRO", "LancamentoFinanceiro", ledger.pk, {"valor": "100.00"})

        result = cliente_360(cliente_id=customer.pk, data_referencia=REFERENCE)

        self.assertEqual(result.eventos[0].projeto_id, project.pk)
        self.assertEqual(result.eventos[0].tipo, "LANCAMENTO_QUITADO")

    def test_unmapped_financial_event_is_excluded(self):
        customer = self.make_customer()
        project = self.make_project(customer, contract="100.00")
        other = self.make_project(self.make_customer("Outro cliente"), contract="100.00")
        ledger = self.make_ledger(other, "100.00")
        self.make_event("LANCAMENTO_QUITADO", "FINANCEIRO", "LancamentoFinanceiro", ledger.pk, {"valor": "100.00"})

        result = cliente_360(cliente_id=customer.pk, data_referencia=REFERENCE)

        self.assertEqual(result.eventos, ())
        self.assertEqual(result.projetos[0].projeto_id, project.pk)

    def test_backup_and_restoration_events_are_excluded(self):
        customer = self.make_customer()
        self.make_event("BACKUP_CONCLUIDO", "BACKUP", metadata={})
        self.make_event("RESTAURACAO_CONCLUIDA", "RESTAURACAO", metadata={})

        result = cliente_360(cliente_id=customer.pk, data_referencia=REFERENCE)

        self.assertEqual(result.eventos, ())

    def test_history_initial_request_never_returns_more_than_fifty_events(self):
        customer = self.make_customer()
        project = self.make_project(customer)
        for _index in range(51):
            self.make_event("PROJETO_FINALIZADO", "KANBAN", "ProjetoKanban", project.pk)

        result = cliente_360(cliente_id=customer.pk, data_referencia=REFERENCE)

        self.assertLessEqual(len(result.eventos), 50)
        self.assertTrue(result.history_has_more)


class Customer360FrontendTests(Customer360FixturesMixin, TestCase):
    def test_missing_customer_is_404(self):
        response = self.client.get(reverse("clientes_agenda:cliente_360", kwargs={"cliente_id": 9999}))
        self.assertEqual(response.status_code, 404)

    def test_index_and_detail_are_get_only(self):
        customer = self.make_customer()
        index_response = self.client.post(reverse("clientes_agenda:clientes"))
        detail_response = self.client.post(reverse("clientes_agenda:cliente_360", kwargs={"cliente_id": customer.pk}))
        self.assertEqual(index_response.status_code, 405)
        self.assertEqual(detail_response.status_code, 405)

    def test_index_empty_database_and_filtered_empty_state_are_distinct(self):
        empty_response = self.client.get(reverse("clientes_agenda:clientes"))
        self.assertContains(empty_response, "Nenhum cliente cadastrado")
        self.make_customer("Mariana Alves")
        filtered_response = self.client.get(reverse("clientes_agenda:clientes"), {"q": "Rafael"})
        self.assertContains(filtered_response, "Nenhum cliente encontrado")
        self.assertContains(filtered_response, "1 cliente no cadastro")
        self.assertNotContains(filtered_response, "Nenhum cliente cadastrado")

    def test_index_searches_by_name_and_phone(self):
        self.make_customer("Mariana Alves", "8190000101")
        self.make_customer("Rafael Nogueira", "8190000102")
        response = self.client.get(reverse("clientes_agenda:clientes"), {"q": "90000102"})
        self.assertContains(response, "Rafael Nogueira")
        self.assertNotIn(">Mariana Alves<", response.content.decode())

    def test_detail_renders_financial_hierarchy_and_project_links(self):
        customer = self.make_customer()
        project = self.make_project(customer, contract="100.00")
        self.make_ledger(project, "100.00")
        response = self.client.get(reverse("clientes_agenda:cliente_360", kwargs={"cliente_id": customer.pk}))
        content = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Somente consulta")
        self.assertContains(response, "Abrir cobrança")
        self.assertContains(response, "Ver rentabilidade")
        self.assertContains(response, f"#projeto-{project.pk}")
        self.assertLess(content.index("Saldo a receber"), content.index("Total recebido"))
        self.assertLess(content.index("Total recebido"), content.index("Total contratado"))
        self.assertNotContains(response, "WhatsApp do cliente")

    def test_archived_and_no_contract_projects_render(self):
        customer = self.make_customer()
        self.make_project(customer, title="Closet arquivado", stage="9_ARQUIVADO", contract="500.00", motivo_arquivamento="ADIOU_OBRA")
        self.make_project(customer, title="Orçamento sem contrato", stage="2_ORCAMENTO", contract="0.00")
        response = self.client.get(reverse("clientes_agenda:cliente_360", kwargs={"cliente_id": customer.pk}))
        self.assertContains(response, "Closet arquivado")
        self.assertContains(response, "Adiou obra")
        self.assertContains(response, "Orçamento sem contrato")
        self.assertContains(response, "Sem contrato")

    def test_inconsistent_summary_hides_subtotals_and_shows_safe_message(self):
        customer = self.make_customer()
        project = self.make_project(customer, contract="100.00")
        self.make_ledger(project, "100.00", "PAGO", payment_date=None)
        response = self.client.get(reverse("clientes_agenda:cliente_360", kwargs={"cliente_id": customer.pk}))
        self.assertContains(response, "Resumo financeiro indisponível")
        self.assertNotContains(response, "R$ 100,00")
        self.assertContains(response, "Projeto")

    def test_xss_content_is_autoescaped(self):
        customer = self.make_customer("><script>alert(1)</script>", "8190000101", observacoes="<b>não seguro</b>")
        project = self.make_project(customer, contract="0.00")
        AgendaContato.objects.create(
            cliente=customer, projeto=project, tipo="LIGACAO_MANUAL", data_agendada=REFERENCE,
            realizado=True, feedback_cliente="<script>alert('x')</script>",
        )
        response = self.client.get(reverse("clientes_agenda:cliente_360", kwargs={"cliente_id": customer.pk}))
        self.assertContains(response, "&lt;script&gt;alert(1)&lt;/script&gt;")
        self.assertNotContains(response, "><script>alert(1)</script>")
        self.assertNotContains(response, "<b>não seguro</b>")

    def test_whatsapp_url_is_generated_only_after_explicit_contextual_click(self):
        customer = self.make_customer()
        project = self.make_project(customer)
        with patch.object(ProjetoKanban, "get_whatsapp_url", return_value="https://wa.me/558190000101") as getter:
            response = self.client.get(reverse("clientes_agenda:cliente_360", kwargs={"cliente_id": customer.pk}))
            self.assertEqual(response.status_code, 200)
            getter.assert_not_called()
            redirect_response = self.client.get(reverse("clientes_agenda:cliente_project_whatsapp", kwargs={"cliente_id": customer.pk, "projeto_id": project.pk}))
            self.assertEqual(redirect_response.status_code, 302)
            getter.assert_called_once_with()

    def test_whatsapp_empty_url_is_safe_and_relationship_is_validated(self):
        customer = self.make_customer()
        project = self.make_project(customer)
        other = self.make_customer("Outro cliente")
        with patch.object(ProjetoKanban, "get_whatsapp_url", return_value=""):
            response = self.client.get(reverse("clientes_agenda:cliente_project_whatsapp", kwargs={"cliente_id": customer.pk, "projeto_id": project.pk}))
        invalid_relation = self.client.get(reverse("clientes_agenda:cliente_project_whatsapp", kwargs={"cliente_id": other.pk, "projeto_id": project.pk}))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(invalid_relation.status_code, 404)

    def test_get_detail_does_not_mutate_business_or_audit_models(self):
        customer = self.make_customer()
        project = self.make_project(customer)
        contact = AgendaContato.objects.create(cliente=customer, projeto=project, tipo="LIGACAO_MANUAL", data_agendada=REFERENCE, realizado=False)
        self.make_ledger(project, "10.00", "PENDENTE", None)
        before = {
            "cliente": list(Cliente.objects.values()), "projeto": list(ProjetoKanban.objects.values()),
            "agenda": list(AgendaContato.objects.values()), "financeiro": list(LancamentoFinanceiro.objects.values()),
            "eventos": list(EventoSistema.objects.values()),
        }
        response = self.client.get(reverse("clientes_agenda:cliente_360", kwargs={"cliente_id": customer.pk}))
        after = {
            "cliente": list(Cliente.objects.values()), "projeto": list(ProjetoKanban.objects.values()),
            "agenda": list(AgendaContato.objects.values()), "financeiro": list(LancamentoFinanceiro.objects.values()),
            "eventos": list(EventoSistema.objects.values()),
        }
        self.assertEqual(response.status_code, 200)
        self.assertEqual(before, after)
        self.assertTrue(AgendaContato.objects.filter(pk=contact.pk, realizado=False).exists())

    def test_history_continuation_returns_only_bounded_next_page(self):
        customer = self.make_customer()
        project = self.make_project(customer)
        for _index in range(51):
            self.make_event("PROJETO_FINALIZADO", "KANBAN", "ProjetoKanban", project.pk)
        response = self.client.get(reverse("clientes_agenda:cliente_history", kwargs={"cliente_id": customer.pk}), {"pagina": 2})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Projeto finalizado")
        self.assertLessEqual(response.content.decode().count("data-history-event"), 50)

    def test_index_post_is_405(self):
        self.assertEqual(self.client.post(reverse("clientes_agenda:clientes")).status_code, 405)

    def test_detail_post_is_405(self):
        customer = self.make_customer()
        self.assertEqual(
            self.client.post(reverse("clientes_agenda:cliente_360", kwargs={"cliente_id": customer.pk})).status_code,
            405,
        )

    def test_detail_renders_split_agenda_and_feedback_without_generic_whatsapp(self):
        customer = self.make_customer()
        overdue = AgendaContato.objects.create(
            cliente=customer, tipo="LIGACAO_MANUAL", data_agendada=date(2026, 10, 28), realizado=False,
        )
        future = AgendaContato.objects.create(
            cliente=customer, tipo="POS_VENDA_30_DIAS", data_agendada=date(2026, 11, 5), realizado=False,
        )
        AgendaContato.objects.create(
            cliente=customer, tipo="POS_VENDA_30_DIAS", data_agendada=REFERENCE, realizado=True,
            nivel_satisfacao="INSATISFEITO", feedback_cliente="Cliente relatou demora no retorno",
        )

        response = self.client.get(reverse("clientes_agenda:cliente_360", kwargs={"cliente_id": customer.pk}))

        self.assertContains(response, "Pendentes vencidos / hoje")
        self.assertContains(response, "Próximos contatos")
        self.assertContains(response, "Insatisfeito")
        self.assertContains(response, f"contatos/{overdue.pk}/whatsapp")
        self.assertContains(response, f"contatos/{future.pk}/whatsapp")
        self.assertNotContains(response, "WhatsApp do cliente")


__all__ = ["Customer360SelectorTests", "Customer360FrontendTests"]
