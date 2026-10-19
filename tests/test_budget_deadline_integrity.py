from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.clientes_agenda.models import Cliente
from apps.kanban_projetos.models import ProjetoKanban
from apps.kanban_projetos.services import reativar_orcamento_service


class BudgetDeadlineIntegrityTests(TestCase):
    def setUp(self):
        self.cliente = Cliente.objects.create(
            nome='Integridade de Prazo',
            whatsapp='11999999999',
        )

    def _project_kwargs(self, **overrides):
        return {
            'cliente': self.cliente,
            'titulo_servico': 'Projeto de teste',
            **overrides,
        }

    def test_direct_save_rejects_budget_stage_without_deadline(self):
        projeto = ProjetoKanban(
            **self._project_kwargs(
                etapa='2_ORCAMENTO',
                data_limite_orcamento=None,
            )
        )

        with self.assertRaises(ValidationError):
            projeto.save()

        self.assertFalse(ProjetoKanban.objects.filter(pk=projeto.pk).exists())

    def test_objects_create_rejects_budget_stage_without_deadline(self):
        with self.assertRaises(ValidationError):
            ProjetoKanban.objects.create(
                **self._project_kwargs(
                    etapa='2_ORCAMENTO',
                    data_limite_orcamento=None,
                )
            )

        self.assertFalse(
            ProjetoKanban.objects.filter(
                cliente=self.cliente,
                etapa='2_ORCAMENTO',
            ).exists()
        )

    def test_reactivation_rejects_missing_deadline_and_rolls_back(self):
        projeto = ProjetoKanban.objects.create(
            **self._project_kwargs(
                etapa='9_ARQUIVADO',
                data_limite_orcamento=None,
                motivo_arquivamento='SEM_RETORNO',
            )
        )

        with self.assertRaises(ValidationError):
            reativar_orcamento_service(projeto.pk)

        projeto.refresh_from_db()
        self.assertEqual(projeto.etapa, '9_ARQUIVADO')
        self.assertEqual(projeto.motivo_arquivamento, 'SEM_RETORNO')
        self.assertIsNone(projeto.data_limite_orcamento)

    def test_budget_stage_accepts_past_today_and_future_deadlines(self):
        hoje = timezone.localdate()
        for deadline in (
            hoje - timedelta(days=1),
            hoje,
            hoje + timedelta(days=1),
        ):
            with self.subTest(deadline=deadline):
                projeto = ProjetoKanban.objects.create(
                    **self._project_kwargs(
                        etapa='2_ORCAMENTO',
                        data_limite_orcamento=deadline,
                    )
                )
                self.assertEqual(projeto.data_limite_orcamento, deadline)

    def test_other_stages_allow_missing_deadline(self):
        for etapa, _ in ProjetoKanban.ETAPA_CHOICES:
            if etapa == '2_ORCAMENTO':
                continue
            with self.subTest(etapa=etapa):
                projeto = ProjetoKanban.objects.create(
                    **self._project_kwargs(
                        etapa=etapa,
                        data_limite_orcamento=None,
                    )
                )
                self.assertIsNone(projeto.data_limite_orcamento)

    def test_budget_deadline_alert_remains_true_for_past_and_today(self):
        hoje = timezone.localdate()
        for deadline in (hoje - timedelta(days=1), hoje):
            with self.subTest(deadline=deadline):
                projeto = ProjetoKanban.objects.create(
                    **self._project_kwargs(
                        etapa='2_ORCAMENTO',
                        data_limite_orcamento=deadline,
                    )
                )
                self.assertTrue(projeto.is_orcamento_vencido)
