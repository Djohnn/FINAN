from datetime import timedelta
from decimal import Decimal

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

    def test_model_rejects_invalid_nonempty_archive_reason_on_create(self):
        """Given an invalid reason; When creating directly; Then reject without persistence."""
        before = ProjetoKanban.objects.count()

        for reason in ('INVALIDO', ' '):
            with self.subTest(reason=reason):
                with self.assertRaises(ValidationError) as caught:
                    ProjetoKanban.objects.create(
                        cliente=self.cliente,
                        titulo_servico='Projeto inválido',
                        motivo_arquivamento=reason,
                    )

                self.assertIn('motivo_arquivamento', caught.exception.message_dict)
                self.assertEqual(ProjetoKanban.objects.count(), before)

    def test_model_rejects_invalid_archive_reason_on_update_without_mutation(self):
        """Given a persisted project; When saving an invalid reason; Then preserve its state."""
        projeto = self._project(
            titulo_servico='Título persistido',
            etapa='2_ORCAMENTO',
            data_limite_orcamento=timezone.localdate(),
            observacao_arquivamento='Observação persistida',
        )
        before = ProjetoKanban.objects.values().get(pk=projeto.pk)

        for reason in ('INVALIDO_UPDATE', ' '):
            with self.subTest(reason=reason):
                projeto.motivo_arquivamento = reason
                with self.assertRaises(ValidationError) as caught:
                    projeto.save()

                self.assertIn('motivo_arquivamento', caught.exception.message_dict)
                projeto.refresh_from_db()
                self.assertEqual(
                    ProjetoKanban.objects.values().get(pk=projeto.pk),
                    before,
                )

    def test_model_accepts_every_declared_archive_reason_choice(self):
        """Given each declared reason; When creating directly; Then persist it."""
        for reason, _label in ProjetoKanban.MOTIVO_ARQUIVAMENTO_CHOICES:
            with self.subTest(reason=reason):
                projeto = ProjetoKanban.objects.create(
                    cliente=self.cliente,
                    titulo_servico='Projeto válido',
                    motivo_arquivamento=reason,
                )
                self.assertEqual(projeto.motivo_arquivamento, reason)

    def test_model_accepts_empty_archive_reason(self):
        """Given an empty reason; When creating directly; Then persist it."""
        projeto = ProjetoKanban.objects.create(
            cliente=self.cliente,
            titulo_servico='Projeto sem motivo',
            motivo_arquivamento='',
        )

        self.assertEqual(projeto.motivo_arquivamento, '')

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

    def test_numeric_negative_fraction_days_raise_without_mutation(self):
        """Given a numeric negative fraction; When archiving; Then preserve state."""
        for days in (Decimal('-0.5'), -0.5):
            with self.subTest(days=repr(days)):
                projeto = self._project()
                agenda_count = AgendaContato.objects.count()

                with self.assertRaises(ValidationError):
                    arquivar_orcamento_service(
                        projeto.id,
                        motivo_arquivamento='SEM_RETORNO',
                        dias_lembrete_retorno=days,
                    )

                self._assert_unchanged(projeto, agenda_count)

    def test_nonfinite_and_nan_days_raise_without_mutation(self):
        """Given a nonfinite number; When archiving; Then reject without mutation."""
        days_values = (
            Decimal('Infinity'),
            Decimal('-Infinity'),
            float('inf'),
            float('-inf'),
            Decimal('NaN'),
            float('nan'),
        )
        for days in days_values:
            with self.subTest(days=repr(days)):
                projeto = self._project()
                agenda_count = AgendaContato.objects.count()

                with self.assertRaises(ValidationError):
                    arquivar_orcamento_service(
                        projeto.id,
                        motivo_arquivamento='SEM_RETORNO',
                        dias_lembrete_retorno=days,
                    )

                self._assert_unchanged(projeto, agenda_count)

    def test_numeric_fractional_compatibility_is_preserved(self):
        """Given positive numeric fractions; When archiving; Then retain observed behavior."""
        cases = (
            (Decimal('0.5'), 0),
            (0.5, 0),
            (Decimal('1.5'), 1),
            (1.5, 1),
        )
        hoje = timezone.localdate()

        for days, expected_days in cases:
            with self.subTest(days=repr(days)):
                projeto = self._project()

                archived = arquivar_orcamento_service(
                    projeto.id,
                    motivo_arquivamento='OUTRO',
                    dias_lembrete_retorno=days,
                )

                self.assertEqual(archived.etapa, '9_ARQUIVADO')
                self.assertEqual(
                    AgendaContato.objects.filter(projeto=projeto).count(),
                    int(expected_days > 0),
                )
                if expected_days > 0:
                    reminder = AgendaContato.objects.get(projeto=projeto)
                    self.assertEqual(
                        reminder.data_agendada,
                        hoje + timedelta(days=expected_days),
                    )

    def test_string_and_integral_compatibility_is_preserved(self):
        """Given established inputs; When archiving; Then retain current semantics."""
        rejected_strings = ('0.5', '1.5', '-0.5')
        for days in rejected_strings:
            with self.subTest(days=days):
                projeto = self._project()
                agenda_count = AgendaContato.objects.count()

                with self.assertRaises(ValidationError):
                    arquivar_orcamento_service(
                        projeto.id,
                        motivo_arquivamento='SEM_RETORNO',
                        dias_lembrete_retorno=days,
                    )

                self._assert_unchanged(projeto, agenda_count)

        accepted_inputs = (
            (None, 0),
            (0, 0),
            (1, 1),
            (Decimal('0'), 0),
            (float(0), 0),
            (Decimal('1'), 1),
            (float(1), 1),
            (' 1 ', 1),
            ('+1', 1),
        )
        for days, expected_days in accepted_inputs:
            with self.subTest(days=repr(days)):
                projeto = self._project()

                archived = arquivar_orcamento_service(
                    projeto.id,
                    motivo_arquivamento='OUTRO',
                    dias_lembrete_retorno=days,
                )

                self.assertEqual(archived.etapa, '9_ARQUIVADO')
                self.assertEqual(
                    AgendaContato.objects.filter(projeto=projeto).count(),
                    int(expected_days > 0),
                )

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
