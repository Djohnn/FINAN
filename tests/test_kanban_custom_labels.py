from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.clientes_agenda.models import Cliente
from apps.core_sistema.models import EventoSistema
from apps.financeiro.models import LancamentoFinanceiro
from apps.kanban_projetos.models import (
    ConfiguracaoEtapaKanban,
    ProjetoKanban,
)
from apps.kanban_projetos.selectors import (
    get_kanban_stage_label,
    get_kanban_stage_labels,
)
from apps.kanban_projetos.services import (
    aprovar_orcamento_service,
    salvar_label_etapa_service,
)

LEGACY_IDENTITIES = (
    "1_CONTATO",
    "2_ORCAMENTO",
    "3_APROVADO",
    "4_PRODUCAO",
    "5_ENTREGA",
    "6_FINALIZADO",
    "9_ARQUIVADO",
)


class KanbanCustomLabelPersistenceTests(TestCase):
    def setUp(self):
        self.cliente = Cliente.objects.create(
            nome="Cliente do label",
            whatsapp="11999999999",
        )

    def test_default_labels_are_returned_without_configuration(self):
        labels = get_kanban_stage_labels()

        self.assertEqual(
            [label.codigo_interno for label in labels],
            list(LEGACY_IDENTITIES),
        )
        self.assertEqual(
            get_kanban_stage_label("2_ORCAMENTO").label_padrao,
            "Em Orçamento",
        )
        self.assertEqual(
            get_kanban_stage_label("2_ORCAMENTO").label_exibido,
            "Em Orçamento",
        )
        self.assertEqual(
            get_kanban_stage_label("9_ARQUIVADO").label_exibido,
            "Geladeira",
        )

    def test_rename_persists_and_keeps_stable_identity(self):
        salvar_label_etapa_service(
            codigo_interno="2_ORCAMENTO",
            label="Preparar Proposta",
        )

        self.assertEqual(
            ConfiguracaoEtapaKanban.objects.get().codigo_interno,
            "2_ORCAMENTO",
        )
        self.assertEqual(
            get_kanban_stage_label("2_ORCAMENTO").label_exibido,
            "Preparar Proposta",
        )
        self.assertEqual(
            get_kanban_stage_label("2_ORCAMENTO").label_padrao,
            "Em Orçamento",
        )

    def test_renaming_again_updates_same_identity_and_survives_fresh_read(self):
        salvar_label_etapa_service(
            codigo_interno="2_ORCAMENTO",
            label="Preparar Proposta",
        )
        salvar_label_etapa_service(
            codigo_interno="2_ORCAMENTO",
            label="Enviar Orçamento",
        )

        self.assertEqual(ConfiguracaoEtapaKanban.objects.count(), 1)
        self.assertEqual(
            get_kanban_stage_label("2_ORCAMENTO").label_exibido,
            "Enviar Orçamento",
        )

    def test_reset_restores_default_without_deleting_identity_contract(self):
        salvar_label_etapa_service(
            codigo_interno="2_ORCAMENTO",
            label="Preparar Proposta",
        )

        salvar_label_etapa_service(
            codigo_interno="2_ORCAMENTO",
            restaurar_padrao=True,
        )

        configuration = ConfiguracaoEtapaKanban.objects.get()
        self.assertEqual(configuration.codigo_interno, "2_ORCAMENTO")
        self.assertEqual(configuration.label_personalizado, "")
        self.assertEqual(
            get_kanban_stage_label("2_ORCAMENTO").label_exibido,
            "Em Orçamento",
        )

    def test_duplicate_visible_names_are_allowed_without_identity_collision(self):
        salvar_label_etapa_service(
            codigo_interno="1_CONTATO",
            label="Em andamento",
        )
        salvar_label_etapa_service(
            codigo_interno="2_ORCAMENTO",
            label="Em andamento",
        )

        self.assertEqual(ConfiguracaoEtapaKanban.objects.count(), 2)
        self.assertEqual(
            get_kanban_stage_label("1_CONTATO").codigo_interno,
            "1_CONTATO",
        )
        self.assertEqual(
            get_kanban_stage_label("2_ORCAMENTO").codigo_interno,
            "2_ORCAMENTO",
        )

    def test_invalid_identity_is_rejected_without_persistence(self):
        with self.assertRaises(ValidationError):
            salvar_label_etapa_service(
                codigo_interno="3_NOVA_ETAPA",
                label="Não permitido",
            )

        self.assertFalse(ConfiguracaoEtapaKanban.objects.exists())

    def test_empty_and_whitespace_labels_are_rejected(self):
        for label in ("", "   ", "\t\n"):
            with self.subTest(label=repr(label)), self.assertRaises(ValidationError):
                salvar_label_etapa_service(
                    codigo_interno="2_ORCAMENTO",
                    label=label,
                )

        self.assertFalse(ConfiguracaoEtapaKanban.objects.exists())

    def test_labels_are_trimmed_and_unicode_is_preserved(self):
        salvar_label_etapa_service(
            codigo_interno="2_ORCAMENTO",
            label="  Proposta – João & ação  ",
        )

        self.assertEqual(
            ConfiguracaoEtapaKanban.objects.get().label_personalizado,
            "Proposta – João & ação",
        )

    def test_html_is_stored_as_text_and_not_marked_safe(self):
        salvar_label_etapa_service(
            codigo_interno="2_ORCAMENTO",
            label='<script>alert("x")</script>',
        )

        self.assertEqual(
            get_kanban_stage_label("2_ORCAMENTO").label_exibido,
            '<script>alert("x")</script>',
        )

    def test_maximum_length_is_enforced(self):
        with self.assertRaises(ValidationError):
            salvar_label_etapa_service(
                codigo_interno="2_ORCAMENTO",
                label="x" * 101,
            )


class KanbanCustomLabelEndpointTests(TestCase):
    def setUp(self):
        self.client_record = Cliente.objects.create(
            nome="Cliente endpoint",
            whatsapp="11999999999",
        )
        self.project = ProjetoKanban.objects.create(
            cliente=self.client_record,
            titulo_servico="Cozinha",
            etapa="2_ORCAMENTO",
            data_limite_orcamento=date(2026, 10, 26),
            valor_total=Decimal("400.00"),
        )

    def test_post_renames_only_configuration_and_redirects(self):
        project_before = ProjetoKanban.objects.values().get(pk=self.project.pk)
        financial_before = LancamentoFinanceiro.objects.count()
        events_before = EventoSistema.objects.count()

        response = self.client.post(
            reverse(
                "kanban_projetos:stage_label_update",
                kwargs={"codigo_interno": "2_ORCAMENTO"},
            ),
            {"label": "Preparar Proposta"},
        )

        self.assertRedirects(response, reverse("kanban_projetos:kanban_readonly"))
        self.assertEqual(
            get_kanban_stage_label("2_ORCAMENTO").label_exibido,
            "Preparar Proposta",
        )
        self.assertEqual(
            ProjetoKanban.objects.values().get(pk=self.project.pk),
            project_before,
        )
        self.assertEqual(LancamentoFinanceiro.objects.count(), financial_before)
        self.assertEqual(EventoSistema.objects.count(), events_before)

    def test_successful_post_returns_accessible_saved_feedback(self):
        response = self.client.post(
            reverse(
                "kanban_projetos:stage_label_update",
                kwargs={"codigo_interno": "2_ORCAMENTO"},
            ),
            {"label": "Preparar Proposta"},
            follow=True,
        )

        self.assertContains(response, "Nome visível da etapa salvo.")
        self.assertContains(response, 'role="status"')

    def test_get_exposes_edit_save_cancel_reset_and_csrf_controls(self):
        response = self.client.get(reverse("kanban_projetos:kanban_readonly"))

        self.assertContains(response, "Renomear etapa Em Orçamento")
        self.assertContains(response, 'data-stage-edit')
        self.assertContains(response, "Salvar")
        self.assertContains(response, "Cancelar")
        self.assertContains(response, "Restaurar padrão")
        self.assertContains(response, 'name="csrfmiddlewaretoken"')

    def test_board_renders_label_protection_guidance_near_customization(self):
        response = self.client.get(reverse("kanban_projetos:kanban_readonly"))

        self.assertContains(response, '<aside class="kanban-label-guidance"')
        self.assertContains(
            response,
            "Você pode alterar o nome. A regra de negócio permanece protegida.",
        )
        self.assertContains(
            response,
            "Renomear a coluna não altera a etapa interna do projeto.",
        )

    def test_post_reset_restores_default(self):
        salvar_label_etapa_service(
            codigo_interno="2_ORCAMENTO",
            label="Preparar Proposta",
        )

        response = self.client.post(
            reverse(
                "kanban_projetos:stage_label_update",
                kwargs={"codigo_interno": "2_ORCAMENTO"},
            ),
            {"reset": "1"},
        )

        self.assertRedirects(response, reverse("kanban_projetos:kanban_readonly"))
        self.assertEqual(
            get_kanban_stage_label("2_ORCAMENTO").label_exibido,
            "Em Orçamento",
        )

    def test_cancel_does_not_save(self):
        response = self.client.get(reverse("kanban_projetos:kanban_readonly"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cancelar")
        self.assertFalse(ConfiguracaoEtapaKanban.objects.exists())

    def test_invalid_post_does_not_persist_and_explains_error(self):
        response = self.client.post(
            reverse(
                "kanban_projetos:stage_label_update",
                kwargs={"codigo_interno": "2_ORCAMENTO"},
            ),
            {"label": "   "},
        )

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Informe um nome visível", status_code=400)
        self.assertFalse(ConfiguracaoEtapaKanban.objects.exists())

    def test_invalid_identity_does_not_persist(self):
        response = self.client.post(
            reverse(
                "kanban_projetos:stage_label_update",
                kwargs={"codigo_interno": "INVALIDO"},
            ),
            {"label": "Não permitido"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Etapa legada inválida", status_code=400)
        self.assertFalse(ConfiguracaoEtapaKanban.objects.exists())

    def test_get_never_mutates_configuration(self):
        response = self.client.get(
            reverse(
                "kanban_projetos:stage_label_update",
                kwargs={"codigo_interno": "2_ORCAMENTO"},
            ),
        )

        self.assertEqual(response.status_code, 405)
        self.assertFalse(ConfiguracaoEtapaKanban.objects.exists())

    def test_csrf_is_required_for_post(self):
        csrf_client = Client(enforce_csrf_checks=True)

        response = csrf_client.post(
            reverse(
                "kanban_projetos:stage_label_update",
                kwargs={"codigo_interno": "2_ORCAMENTO"},
            ),
            {"label": "Sem CSRF"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(ConfiguracaoEtapaKanban.objects.exists())

    def test_board_renders_custom_label_and_keeps_project_identity_and_order(self):
        second_project = ProjetoKanban.objects.create(
            cliente=self.client_record,
            titulo_servico="Banheiro",
            etapa="2_ORCAMENTO",
            data_limite_orcamento=date(2026, 10, 27),
        )
        salvar_label_etapa_service(
            codigo_interno="2_ORCAMENTO",
            label="Preparar Proposta",
        )

        response = self.client.get(reverse("kanban_projetos:kanban_readonly"))
        column = next(
            column
            for column in response.context["columns"]
            if column["code"] == "2_ORCAMENTO"
        )

        self.assertContains(response, "Preparar Proposta")
        self.assertNotContains(response, "2_ORCAMENTO</h3>")
        self.assertEqual(
            [card["project"].pk for card in column["projects"]],
            [second_project.pk, self.project.pk],
        )
        self.assertEqual(
            ProjetoKanban.objects.get(pk=self.project.pk).etapa,
            "2_ORCAMENTO",
        )

    def test_board_escapes_custom_html_label(self):
        salvar_label_etapa_service(
            codigo_interno="2_ORCAMENTO",
            label='<script>alert("label")</script>',
        )

        response = self.client.get(reverse("kanban_projetos:kanban_readonly"))

        self.assertNotContains(response, '<script>alert("label")</script>')
        self.assertContains(response, "&lt;script&gt;alert(&quot;label&quot;)&lt;/script&gt;")

    def test_overdue_budget_stays_active_after_label_rename(self):
        salvar_label_etapa_service(
            codigo_interno="2_ORCAMENTO",
            label="Preparar Proposta",
        )

        self.project.data_limite_orcamento = date(2026, 10, 1)
        self.project.save(update_fields=["data_limite_orcamento", "atualizado_em"])

        with override_settings(USE_TZ=True):
            response = self.client.get(reverse("kanban_projetos:kanban_readonly"))

        self.assertEqual(response.context["columns"][1]["code"], "2_ORCAMENTO")
        self.assertTrue(response.context["columns"][1]["projects"][0]["is_overdue"])

    def test_financial_approval_still_uses_internal_identity_after_rename(self):
        salvar_label_etapa_service(
            codigo_interno="2_ORCAMENTO",
            label="Preparar Proposta",
        )

        approved = aprovar_orcamento_service(
            projeto_id=self.project.pk,
            valor_total=Decimal("400.00"),
            valor_entrada=Decimal("100.00"),
            forma_pagamento_entrada="PIX",
            data_inicio_producao=date(2026, 11, 1),
            data_entrega_prevista=date(2026, 11, 15),
        )

        self.assertEqual(approved.etapa, "3_APROVADO")
        self.assertEqual(
            list(
                LancamentoFinanceiro.objects.filter(
                    projeto=approved,
                    status="PAGO",
                ).values_list("valor", flat=True)
            ),
            [Decimal("100.00")],
        )
