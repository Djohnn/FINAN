from datetime import UTC, date, datetime, timezone
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.clientes_agenda.models import AgendaContato, Cliente
from apps.kanban_projetos.models import ProjetoKanban


class ProjetoKanbanChoiceIntegrityTests(TestCase):
    def setUp(self):
        self.cliente = Cliente.objects.create(
            nome='Cliente de Integridade',
            whatsapp='11999999999',
        )

    def _project_kwargs(self, **overrides):
        return {
            'cliente': self.cliente,
            'titulo_servico': 'Projeto de escolha',
            **overrides,
        }

    def test_invalid_stage_update_rejects_and_preserves_persisted_state(self):
        projeto = ProjetoKanban.objects.create(
            **self._project_kwargs(
                etapa='3_APROVADO',
                data_limite_orcamento=date(2026, 10, 30),
                data_inicio_producao=date(2026, 10, 21),
                data_entrega_prevista=date(2026, 11, 21),
                data_entrega_realizada=date(2026, 11, 22),
                valor_total=Decimal('12345.67'),
                valor_entrada=Decimal('2345.67'),
                saldo_restante=Decimal('10000.00'),
                motivo_arquivamento='SEM_RETORNO',
                observacao_arquivamento='Estado arquivado preservado',
            )
        )
        projeto.etapa = 'INVALIDA'

        with self.assertRaises(ValidationError) as context:
            projeto.save()

        self.assertIn('etapa', context.exception.message_dict)
        projeto.refresh_from_db()
        self.assertEqual(projeto.etapa, '3_APROVADO')
        self.assertEqual(projeto.data_limite_orcamento, date(2026, 10, 30))
        self.assertEqual(projeto.data_inicio_producao, date(2026, 10, 21))
        self.assertEqual(projeto.data_entrega_prevista, date(2026, 11, 21))
        self.assertEqual(projeto.data_entrega_realizada, date(2026, 11, 22))
        self.assertEqual(projeto.valor_total, Decimal('12345.67'))
        self.assertEqual(projeto.valor_entrada, Decimal('2345.67'))
        self.assertEqual(projeto.saldo_restante, Decimal('10000.00'))
        self.assertEqual(projeto.motivo_arquivamento, 'SEM_RETORNO')
        self.assertEqual(projeto.observacao_arquivamento, 'Estado arquivado preservado')

    def test_invalid_stage_create_rejects_without_persistence(self):
        with self.assertRaises(ValidationError) as context:
            ProjetoKanban.objects.create(
                **self._project_kwargs(etapa='INVALIDA')
            )

        self.assertIn('etapa', context.exception.message_dict)
        self.assertFalse(
            ProjetoKanban.objects.filter(
                cliente=self.cliente,
                titulo_servico='Projeto de escolha',
            ).exists()
        )

    def test_declared_project_stages_are_accepted(self):
        for etapa, _label in ProjetoKanban.ETAPA_CHOICES:
            with self.subTest(etapa=etapa):
                projeto = ProjetoKanban.objects.create(
                    **self._project_kwargs(
                        etapa=etapa,
                        data_limite_orcamento=(
                            date(2026, 10, 31)
                            if etapa == '2_ORCAMENTO'
                            else None
                        ),
                    )
                )
                self.assertEqual(projeto.etapa, etapa)

    def test_budget_stage_still_requires_deadline(self):
        with self.assertRaises(ValidationError) as context:
            ProjetoKanban.objects.create(
                **self._project_kwargs(
                    etapa='2_ORCAMENTO',
                    data_limite_orcamento=None,
                )
            )

        self.assertIn('data_limite_orcamento', context.exception.message_dict)


class AgendaContatoChoiceIntegrityTests(TestCase):
    def setUp(self):
        self.cliente = Cliente.objects.create(
            nome='Cliente de Agenda',
            whatsapp='11888888888',
        )

    def _agenda_kwargs(self, **overrides):
        return {
            'cliente': self.cliente,
            'tipo': 'LIGACAO_MANUAL',
            'data_agendada': date(2026, 10, 20),
            **overrides,
        }

    def test_invalid_type_update_rejects_and_preserves_persisted_state(self):
        realizado_em = datetime(2026, 10, 20, 12, 30, tzinfo=UTC)
        agenda = AgendaContato.objects.create(
            **self._agenda_kwargs(
                tipo='RETORNO_ORCAMENTO',
                realizado=True,
                feedback_cliente='Feedback válido preservado',
                nivel_satisfacao='AJUSTE_SOLICITADO',
                realizado_em=realizado_em,
            )
        )
        agenda.tipo = 'INVALIDO'

        with self.assertRaises(ValidationError) as context:
            agenda.save()

        self.assertIn('tipo', context.exception.message_dict)
        agenda.refresh_from_db()
        self.assertEqual(agenda.tipo, 'RETORNO_ORCAMENTO')
        self.assertTrue(agenda.realizado)
        self.assertEqual(agenda.feedback_cliente, 'Feedback válido preservado')
        self.assertEqual(agenda.nivel_satisfacao, 'AJUSTE_SOLICITADO')
        self.assertEqual(agenda.realizado_em, realizado_em)

    def test_invalid_type_create_rejects_without_persistence(self):
        with self.assertRaises(ValidationError) as context:
            AgendaContato.objects.create(
                **self._agenda_kwargs(tipo='INVALIDO')
            )

        self.assertIn('tipo', context.exception.message_dict)
        self.assertFalse(
            AgendaContato.objects.filter(
                cliente=self.cliente,
                data_agendada=date(2026, 10, 20),
            ).exists()
        )

    def test_declared_agenda_types_are_accepted(self):
        for tipo, _label in AgendaContato.TIPO_CHOICES:
            with self.subTest(tipo=tipo):
                agenda = AgendaContato.objects.create(
                    **self._agenda_kwargs(tipo=tipo)
                )
                self.assertEqual(agenda.tipo, tipo)
