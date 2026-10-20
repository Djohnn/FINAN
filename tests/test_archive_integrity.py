from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.clientes_agenda.models import AgendaContato, Cliente
from apps.kanban_projetos.models import ProjetoKanban
from apps.kanban_projetos.services import arquivar_orcamento_service


class ArchiveInputIntegrityTests(TestCase):
    def setUp(self):
        self.cliente = Cliente.objects.create(
            nome='Cliente Arquivo',
            whatsapp='11999999999',
        )

    def _project(self, **overrides):
        fields = {
            'cliente': self.cliente,
            'titulo_servico': 'Projeto de arquivo',
            'etapa': '1_CONTATO',
            'motivo_arquivamento': 'OUTRO',
            'observacao_arquivamento': 'observacao anterior',
            **overrides,
        }
        return ProjetoKanban.objects.create(**fields)

    def _assert_unchanged(self, projeto, agenda_count):
        projeto.refresh_from_db()
        self.assertEqual(projeto.etapa, '1_CONTATO')
        self.assertEqual(projeto.motivo_arquivamento, 'OUTRO')
        self.assertEqual(projeto.observacao_arquivamento, 'observacao anterior')
        self.assertEqual(AgendaContato.objects.count(), agenda_count)

    def test_invalid_archive_reason_raises_without_mutation(self):
        """Given an active project; When reason is invalid; Then preserve state."""
        projeto = self._project()
        agenda_count = AgendaContato.objects.count()

        with self.assertRaises(ValidationError):
            arquivar_orcamento_service(
                projeto.id,
                motivo_arquivamento='INVALIDO',
                observacao='nova observacao',
            )

        self._assert_unchanged(projeto, agenda_count)

    def test_accepts_every_current_archive_reason_choice(self):
        """Given each declared reason; When archiving; Then accept the reason."""
        for reason, _label in ProjetoKanban.MOTIVO_ARQUIVAMENTO_CHOICES:
            with self.subTest(reason=reason):
                projeto = self._project()

                archived = arquivar_orcamento_service(
                    projeto.id,
                    motivo_arquivamento=reason,
                    dias_lembrete_retorno=None,
                )

                self.assertEqual(archived.etapa, '9_ARQUIVADO')
                self.assertEqual(archived.motivo_arquivamento, reason)

    def test_nonnumeric_days_raise_validation_error_without_mutation(self):
        """Given an active project; When days are nonnumeric; Then preserve state."""
        projeto = self._project()
        agenda_count = AgendaContato.objects.count()

        with self.assertRaises(ValidationError):
            arquivar_orcamento_service(
                projeto.id,
                motivo_arquivamento='SEM_RETORNO',
                dias_lembrete_retorno='abc',
            )

        self._assert_unchanged(projeto, agenda_count)

    def test_negative_integer_days_raise_without_mutation(self):
        """Given an active project; When days are negative; Then preserve state."""
        projeto = self._project()
        agenda_count = AgendaContato.objects.count()

        with self.assertRaises(ValidationError):
            arquivar_orcamento_service(
                projeto.id,
                motivo_arquivamento='SEM_RETORNO',
                dias_lembrete_retorno=-1,
            )

        self._assert_unchanged(projeto, agenda_count)

    def test_negative_string_days_raise_without_mutation(self):
        """Given an active project; When string days are negative; Then preserve state."""
        projeto = self._project()
        agenda_count = AgendaContato.objects.count()

        with self.assertRaises(ValidationError):
            arquivar_orcamento_service(
                projeto.id,
                motivo_arquivamento='SEM_RETORNO',
                dias_lembrete_retorno='-30',
            )

        self._assert_unchanged(projeto, agenda_count)

    def test_none_days_archive_without_reminder(self):
        """Given no reminder days; When archiving; Then create no reminder."""
        projeto = self._project()

        archived = arquivar_orcamento_service(
            projeto.id,
            motivo_arquivamento='PRECO_ALTO',
            observacao='sem retorno agendado',
            dias_lembrete_retorno=None,
        )

        self.assertEqual(archived.etapa, '9_ARQUIVADO')
        self.assertEqual(archived.motivo_arquivamento, 'PRECO_ALTO')
        self.assertEqual(archived.observacao_arquivamento, 'sem retorno agendado')
        self.assertFalse(AgendaContato.objects.exists())

    def test_zero_integer_days_archive_without_reminder(self):
        """Given zero integer days; When archiving; Then create no reminder."""
        projeto = self._project()

        arquivar_orcamento_service(
            projeto.id,
            motivo_arquivamento='ADIOU_OBRA',
            dias_lembrete_retorno=0,
        )

        projeto.refresh_from_db()
        self.assertEqual(projeto.etapa, '9_ARQUIVADO')
        self.assertFalse(AgendaContato.objects.exists())

    def test_zero_string_days_archive_without_reminder(self):
        """Given zero string days; When archiving; Then create no reminder."""
        projeto = self._project()

        arquivar_orcamento_service(
            projeto.id,
            motivo_arquivamento='FECHOU_CONCORRENTE',
            dias_lembrete_retorno='0',
        )

        projeto.refresh_from_db()
        self.assertEqual(projeto.etapa, '9_ARQUIVADO')
        self.assertFalse(AgendaContato.objects.exists())

    def test_positive_integer_days_create_one_reminder(self):
        """Given one reminder day; When archiving; Then schedule one return."""
        projeto = self._project()
        hoje = timezone.localdate()

        arquivar_orcamento_service(
            projeto.id,
            motivo_arquivamento='OUTRO',
            dias_lembrete_retorno=1,
        )

        reminder = AgendaContato.objects.get()
        self.assertEqual(AgendaContato.objects.count(), 1)
        self.assertEqual(reminder.cliente_id, self.cliente.id)
        self.assertEqual(reminder.projeto_id, projeto.id)
        self.assertEqual(reminder.tipo, 'RETORNO_ORCAMENTO')
        self.assertEqual(reminder.data_agendada, hoje + timedelta(days=1))
        self.assertFalse(reminder.realizado)
        self.assertEqual(reminder.nivel_satisfacao, '')
        self.assertEqual(
            reminder.feedback_cliente,
            'Lembrete de retorno para orçamento arquivado: Projeto de arquivo',
        )

    def test_positive_string_days_create_one_reminder(self):
        """Given numeric string days; When archiving; Then schedule that return."""
        projeto = self._project()
        hoje = timezone.localdate()

        arquivar_orcamento_service(
            projeto.id,
            motivo_arquivamento='OUTRO',
            dias_lembrete_retorno='30',
        )

        reminder = AgendaContato.objects.get()
        self.assertEqual(AgendaContato.objects.count(), 1)
        self.assertEqual(reminder.data_agendada, hoje + timedelta(days=30))
        self.assertEqual(reminder.tipo, 'RETORNO_ORCAMENTO')
        self.assertFalse(reminder.realizado)

    def test_archive_from_budget_stage_with_deadline_remains_compatible(self):
        """Given a budget with deadline; When archived; Then allow archive."""
        projeto = self._project(
            etapa='2_ORCAMENTO',
            data_limite_orcamento=timezone.localdate(),
        )

        archived = arquivar_orcamento_service(
            projeto.id,
            motivo_arquivamento='SEM_RETORNO',
            dias_lembrete_retorno=None,
        )

        self.assertEqual(archived.etapa, '9_ARQUIVADO')
        self.assertEqual(archived.motivo_arquivamento, 'SEM_RETORNO')
