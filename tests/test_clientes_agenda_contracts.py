from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.clientes_agenda.models import AgendaContato, Cliente
from apps.clientes_agenda.services import concluir_pos_venda_service
from apps.core_sistema.context_processors import alertas_globais


class SatisfactionContractTests(TestCase):
    def setUp(self):
        self.cliente = Cliente.objects.create(
            nome='Cliente Agenda',
            whatsapp='11999999999',
        )

    def _agenda(self, **overrides):
        return AgendaContato.objects.create(
            cliente=self.cliente,
            tipo='POS_VENDA_30_DIAS',
            data_agendada=timezone.localdate(),
            **overrides,
        )

    def test_direct_save_rejects_invalid_satisfaction_without_persisting(self):
        """Given an unsatisfied agenda; When saved with an invalid choice; Then reject it."""
        agenda = AgendaContato(
            cliente=self.cliente,
            tipo='POS_VENDA_30_DIAS',
            data_agendada=timezone.localdate(),
            nivel_satisfacao='INVALIDA',
        )

        with self.assertRaises(ValidationError):
            agenda.save()

        self.assertFalse(AgendaContato.objects.filter(pk=agenda.pk).exists())

    def test_service_rejects_invalid_satisfaction_without_mutating_completion_state(self):
        """Given a pending agenda; When completed with an invalid choice; Then preserve state."""
        agenda = self._agenda(
            feedback_cliente='feedback anterior',
            nivel_satisfacao='SATISFEITO',
        )
        realizado_em_antes = agenda.realizado_em

        with self.assertRaises(ValidationError):
            concluir_pos_venda_service(
                agenda.id,
                feedback_cliente='feedback novo válido',
                nivel_satisfacao='INVALIDA',
            )

        agenda.refresh_from_db()
        self.assertFalse(agenda.realizado)
        self.assertEqual(agenda.realizado_em, realizado_em_antes)
        self.assertEqual(agenda.feedback_cliente, 'feedback anterior')
        self.assertEqual(agenda.nivel_satisfacao, 'SATISFEITO')

    def test_service_accepts_every_current_satisfaction_choice(self):
        """Given each declared choice; When completing an agenda; Then accept the choice."""
        for choice, _label in AgendaContato.SATISFACAO_CHOICES:
            with self.subTest(choice=choice):
                agenda = self._agenda()

                concluida = concluir_pos_venda_service(
                    agenda.id,
                    feedback_cliente='feedback válido com dez caracteres',
                    nivel_satisfacao=choice,
                )

                self.assertTrue(concluida.realizado)
                self.assertEqual(concluida.nivel_satisfacao, choice)

    def test_service_default_satisfaction_remains_satisfeito(self):
        """Given a pending agenda; When completed without satisfaction; Then default to SATISFEITO."""
        agenda = self._agenda()

        concluida = concluir_pos_venda_service(
            agenda.id,
            feedback_cliente='feedback válido com dez caracteres',
        )

        self.assertEqual(concluida.nivel_satisfacao, 'SATISFEITO')


class GlobalAgendaAlertContractTests(TestCase):
    def setUp(self):
        self.cliente = Cliente.objects.create(
            nome='Cliente Alertas',
            whatsapp='11888888888',
        )
        self.hoje = timezone.localdate()

    def _contato(self, tipo='LIGACAO_MANUAL', **overrides):
        fields = {
            'data_agendada': self.hoje,
            'realizado': False,
            **overrides,
        }
        return AgendaContato.objects.create(
            cliente=self.cliente,
            tipo=tipo,
            **fields,
        )

    def test_due_manual_contact_is_in_pending_global_alerts(self):
        """Given a due manual contact; When global alerts are read; Then include it."""
        contato = self._contato(data_agendada=self.hoje - timedelta(days=1))

        contexto = alertas_globais(None)

        self.assertIn(contato, contexto['contatos_pendentes'])

    def test_future_manual_contact_is_excluded_from_pending_global_alerts(self):
        """Given a future manual contact; When global alerts are read; Then exclude it."""
        contato = self._contato(data_agendada=self.hoje + timedelta(days=1))

        contexto = alertas_globais(None)

        self.assertNotIn(contato, contexto['contatos_pendentes'])

    def test_completed_manual_contact_is_excluded_from_pending_global_alerts(self):
        """Given a completed manual contact; When global alerts are read; Then exclude it."""
        contato = self._contato(
            realizado=True,
            feedback_cliente='feedback realizado válido',
        )

        contexto = alertas_globais(None)

        self.assertNotIn(contato, contexto['contatos_pendentes'])

    def test_due_post_sale_and_budget_return_contacts_remain_in_alerts(self):
        """Given due post-sale and budget-return contacts; Then both remain included."""
        pos_venda = self._contato(tipo='POS_VENDA_30_DIAS')
        retorno = self._contato(tipo='RETORNO_ORCAMENTO')

        contexto = alertas_globais(None)

        self.assertIn(pos_venda, contexto['contatos_pendentes'])
        self.assertIn(retorno, contexto['contatos_pendentes'])
