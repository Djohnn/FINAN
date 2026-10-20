from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.clientes_agenda.models import Cliente
from apps.kanban_projetos.models import ProjetoKanban
from apps.kanban_projetos.services import reativar_orcamento_service


class ReactivationIntegrityTests(TestCase):
    def setUp(self):
        self.cliente = Cliente.objects.create(
            nome='Integridade de Reativação',
            whatsapp='11999999999',
        )

    def _project(self, **overrides):
        fields = {
            'cliente': self.cliente,
            'titulo_servico': 'Projeto de reativação',
            'etapa': '9_ARQUIVADO',
            'data_limite_orcamento': timezone.localdate() + timedelta(days=14),
            'motivo_arquivamento': 'SEM_RETORNO',
            'observacao_arquivamento': 'observação original',
            **overrides,
        }
        return ProjetoKanban.objects.create(**fields)

    def test_nonarchived_source_is_rejected_without_mutation(self):
        """Given an active project; When reactivated; Then preserve every field."""
        projeto = self._project(
            etapa='1_CONTATO',
            motivo_arquivamento='OUTRO',
        )
        deadline = projeto.data_limite_orcamento

        with self.assertRaises(ValidationError):
            reativar_orcamento_service(projeto.pk, nova_etapa='3_APROVADO')

        projeto.refresh_from_db()
        self.assertEqual(projeto.etapa, '1_CONTATO')
        self.assertEqual(projeto.motivo_arquivamento, 'OUTRO')
        self.assertEqual(projeto.observacao_arquivamento, 'observação original')
        self.assertEqual(projeto.data_limite_orcamento, deadline)

    def test_invalid_target_is_rejected_without_mutation(self):
        """Given an archived project; When target is invalid; Then preserve state."""
        projeto = self._project()
        deadline = projeto.data_limite_orcamento

        with self.assertRaises(ValidationError):
            reativar_orcamento_service(projeto.pk, nova_etapa='INVALIDA')

        projeto.refresh_from_db()
        self.assertEqual(projeto.etapa, '9_ARQUIVADO')
        self.assertEqual(projeto.motivo_arquivamento, 'SEM_RETORNO')
        self.assertEqual(projeto.observacao_arquivamento, 'observação original')
        self.assertEqual(projeto.data_limite_orcamento, deadline)

    def test_active_reactivation_clears_reason_and_preserves_archive_data(self):
        """Given an archived project; When moved to 1_CONTATO; Then clear only reason."""
        projeto = self._project()
        deadline = projeto.data_limite_orcamento

        reactivated = reativar_orcamento_service(
            projeto.pk,
            nova_etapa='1_CONTATO',
        )

        self.assertEqual(reactivated.etapa, '1_CONTATO')
        projeto.refresh_from_db()
        self.assertEqual(projeto.etapa, '1_CONTATO')
        self.assertEqual(projeto.motivo_arquivamento, '')
        self.assertEqual(projeto.observacao_arquivamento, 'observação original')
        self.assertEqual(projeto.data_limite_orcamento, deadline)

    def test_budget_reactivation_with_deadline_succeeds(self):
        """Given an archived project with deadline; When moved to budget; Then accept."""
        projeto = self._project()
        deadline = projeto.data_limite_orcamento

        reativar_orcamento_service(projeto.pk, nova_etapa='2_ORCAMENTO')

        projeto.refresh_from_db()
        self.assertEqual(projeto.etapa, '2_ORCAMENTO')
        self.assertEqual(projeto.motivo_arquivamento, '')
        self.assertEqual(projeto.observacao_arquivamento, 'observação original')
        self.assertEqual(projeto.data_limite_orcamento, deadline)

    def test_budget_reactivation_without_deadline_rolls_back_integrally(self):
        """Given no deadline; When moved to budget; Then rollback all fields."""
        projeto = self._project(data_limite_orcamento=None)

        with self.assertRaises(ValidationError):
            reativar_orcamento_service(projeto.pk, nova_etapa='2_ORCAMENTO')

        projeto.refresh_from_db()
        self.assertEqual(projeto.etapa, '9_ARQUIVADO')
        self.assertEqual(projeto.motivo_arquivamento, 'SEM_RETORNO')
        self.assertEqual(projeto.observacao_arquivamento, 'observação original')
        self.assertIsNone(projeto.data_limite_orcamento)

    def test_repeat_after_active_reactivation_is_rejected_without_mutation(self):
        """Given an active result; When called again; Then reject and preserve state."""
        projeto = self._project()
        reativar_orcamento_service(projeto.pk, nova_etapa='1_CONTATO')

        with self.assertRaises(ValidationError):
            reativar_orcamento_service(projeto.pk, nova_etapa='1_CONTATO')

        projeto.refresh_from_db()
        self.assertEqual(projeto.etapa, '1_CONTATO')
        self.assertEqual(projeto.motivo_arquivamento, '')
        self.assertEqual(projeto.observacao_arquivamento, 'observação original')
        self.assertIsNotNone(projeto.data_limite_orcamento)

    def test_accepts_each_declared_target_without_semantic_whitelist(self):
        """Given each declared target; When reactivated; Then apply existing invariants only."""
        deadline = timezone.localdate() + timedelta(days=14)

        for etapa, _label in ProjetoKanban.ETAPA_CHOICES:
            with self.subTest(etapa=etapa):
                projeto = self._project(data_limite_orcamento=deadline)

                reativar_orcamento_service(projeto.pk, nova_etapa=etapa)

                projeto.refresh_from_db()
                self.assertEqual(projeto.etapa, etapa)
                self.assertEqual(projeto.motivo_arquivamento, '')
                self.assertEqual(
                    projeto.observacao_arquivamento,
                    'observação original',
                )
                self.assertEqual(projeto.data_limite_orcamento, deadline)
