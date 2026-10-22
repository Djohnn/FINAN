from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.clientes_agenda.models import AgendaContato, Cliente
from apps.clientes_agenda.services import concluir_pos_venda_service
from apps.core_sistema import services as core_services
from apps.core_sistema.admin import EventoSistemaAdmin
from apps.core_sistema.models import (
    DominioEventoSistema,
    EventoSistema,
    TipoEventoSistema,
)
from apps.core_sistema.selectors import eventos_recentes, historico_entidade
from apps.equipe.models import Funcionario
from apps.equipe.services import lancar_pagamento_funcionario_service
from apps.financeiro.models import LancamentoFinanceiro
from apps.financeiro.services import registrar_pagamento_service
from apps.kanban_projetos.models import ProjetoKanban
from apps.kanban_projetos.services import (
    aprovar_orcamento_service,
    arquivar_orcamento_service,
    finalizar_projeto_service,
    reativar_orcamento_service,
)

class ImportantActionHistoryModelTests(TestCase):
    def test_evento_sistema_metadata_defaults_to_a_fresh_empty_dict(self):
        evento = EventoSistema.objects.create(
            tipo='ORCAMENTO_APROVADO',
            dominio='KANBAN',
            entidade_tipo='ProjetoKanban',
            entidade_id='42',
            descricao='Orçamento aprovado (ProjetoKanban #42)',
        )

        self.assertEqual(evento.metadata, {})

    def test_choices_are_closed_to_the_frozen_contract(self):
        self.assertEqual(
            {value for value, _label in TipoEventoSistema.choices},
            {
                'ORCAMENTO_APROVADO',
                'ORCAMENTO_ARQUIVADO',
                'ORCAMENTO_REATIVADO',
                'PROJETO_FINALIZADO',
                'PAGAMENTO_FUNCIONARIO_CRIADO',
                'LANCAMENTO_QUITADO',
                'CONTATO_CONCLUIDO',
                'BACKUP_CONCLUIDO',
                'BACKUP_FALHOU',
                'RESTAURACAO_CONCLUIDA',
                'RESTAURACAO_FALHOU_ROLLBACK_OK',
            },
        )
        self.assertEqual(
            {value for value, _label in DominioEventoSistema.choices},
            {'KANBAN', 'EQUIPE', 'FINANCEIRO', 'AGENDA', 'BACKUP', 'RESTAURACAO'},
        )

    def test_metadata_default_isolated_between_instances(self):
        first = EventoSistema.objects.create(
            tipo='BACKUP_CONCLUIDO',
            dominio='BACKUP',
            descricao='Backup concluído',
        )
        first.metadata['mutated'] = True
        second = EventoSistema.objects.create(
            tipo='BACKUP_CONCLUIDO',
            dominio='BACKUP',
            descricao='Backup concluído',
        )

        self.assertEqual(second.metadata, {})


class RegistrarEventoTests(TestCase):
    def test_all_valid_type_domain_pairs_are_accepted(self):
        contracts = {
            'ORCAMENTO_APROVADO': ('KANBAN', 'ProjetoKanban', '1'),
            'ORCAMENTO_ARQUIVADO': ('KANBAN', 'ProjetoKanban', '2'),
            'ORCAMENTO_REATIVADO': ('KANBAN', 'ProjetoKanban', '3'),
            'PROJETO_FINALIZADO': ('KANBAN', 'ProjetoKanban', '4'),
            'PAGAMENTO_FUNCIONARIO_CRIADO': ('EQUIPE', 'Funcionario', '5'),
            'LANCAMENTO_QUITADO': ('FINANCEIRO', 'LancamentoFinanceiro', '6'),
            'CONTATO_CONCLUIDO': ('AGENDA', 'AgendaContato', '7'),
            'BACKUP_CONCLUIDO': ('BACKUP', None, None),
            'BACKUP_FALHOU': ('BACKUP', None, None),
            'RESTAURACAO_CONCLUIDA': ('RESTAURACAO', None, None),
            'RESTAURACAO_FALHOU_ROLLBACK_OK': ('RESTAURACAO', None, None),
        }

        for tipo, (dominio, entidade_tipo, entidade_id) in contracts.items():
            with self.subTest(tipo=tipo):
                evento = core_services.registrar_evento(
                    tipo=tipo,
                    dominio=dominio,
                    entidade_tipo=entidade_tipo,
                    entidade_id=entidade_id,
                    metadata=(
                        {'motivo_codigo': 'PRECO_ALTO'}
                        if tipo == 'ORCAMENTO_ARQUIVADO'
                        else {'categoria': 'ERRO_SQLITE_BACKUP'}
                        if tipo == 'BACKUP_FALHOU'
                        else {'valor': Decimal('12.3')}
                        if tipo == 'LANCAMENTO_QUITADO'
                        else {'lancamento_id': 8, 'valor': 12}
                        if tipo == 'PAGAMENTO_FUNCIONARIO_CRIADO'
                        else None
                    ),
                )
                self.assertEqual(evento.tipo, tipo)

        self.assertEqual(EventoSistema.objects.count(), len(contracts))

    def test_invalid_type_domain_pair_is_rejected(self):
        with self.assertRaises(ValidationError):
            core_services.registrar_evento(
                tipo='ORCAMENTO_APROVADO',
                dominio='FINANCEIRO',
                entidade_tipo='ProjetoKanban',
                entidade_id=1,
            )

    def test_unhashable_tipo_is_rejected_with_validation_error(self):
        with self.assertRaises(ValidationError):
            core_services.registrar_evento(
                tipo=[],
                dominio='KANBAN',
                entidade_tipo='ProjetoKanban',
                entidade_id=1,
            )

    def test_unhashable_dominio_is_rejected_with_validation_error(self):
        with self.assertRaises(ValidationError):
            core_services.registrar_evento(
                tipo='ORCAMENTO_APROVADO',
                dominio=[],
                entidade_tipo='ProjetoKanban',
                entidade_id=1,
            )

    def test_unicode_entity_id_is_not_canonical(self):
        with self.assertRaises(ValidationError):
            core_services.registrar_evento(
                tipo='ORCAMENTO_APROVADO',
                dominio='KANBAN',
                entidade_tipo='ProjetoKanban',
                entidade_id='١٢',
            )

    def test_entity_contract_rejects_half_present_and_wrong_entity(self):
        cases = (
            {'entidade_tipo': 'ProjetoKanban'},
            {'entidade_id': 1},
            {'entidade_tipo': 'Funcionario', 'entidade_id': 1},
        )
        for extra in cases:
            with self.subTest(extra=extra), self.assertRaises(ValidationError):
                core_services.registrar_evento(
                    tipo='ORCAMENTO_APROVADO',
                    dominio='KANBAN',
                    **extra,
                )

    def test_system_event_requires_nullable_entity(self):
        with self.assertRaises(ValidationError):
            core_services.registrar_evento(
                tipo='BACKUP_CONCLUIDO',
                dominio='BACKUP',
                entidade_id=1,
            )

        evento = core_services.registrar_evento(
            tipo='BACKUP_CONCLUIDO',
            dominio='BACKUP',
        )
        self.assertIsNone(evento.entidade_tipo)
        self.assertIsNone(evento.entidade_id)

    def test_metadata_whitelist_rejects_extra_keys(self):
        with self.assertRaises(ValidationError):
            core_services.registrar_evento(
                tipo='ORCAMENTO_APROVADO',
                dominio='KANBAN',
                entidade_tipo='ProjetoKanban',
                entidade_id=1,
                metadata={'observacao': 'não deve ser persistida'},
            )

    def test_metadata_whitelist_normalizes_allowed_values(self):
        evento = core_services.registrar_evento(
            tipo='ORCAMENTO_ARQUIVADO',
            dominio='KANBAN',
            entidade_tipo='ProjetoKanban',
            entidade_id='42',
            metadata={'motivo_codigo': ' PRECO_ALTO '},
        )
        self.assertEqual(evento.metadata, {'motivo_codigo': 'PRECO_ALTO'})

    def test_monetary_metadata_is_canonical_and_float_is_rejected(self):
        evento = core_services.registrar_evento(
            tipo='LANCAMENTO_QUITADO',
            dominio='FINANCEIRO',
            entidade_tipo='LancamentoFinanceiro',
            entidade_id=42,
            metadata={'valor': Decimal('123.4')},
        )
        self.assertEqual(evento.metadata, {'valor': '123.40'})

        with self.assertRaises(ValidationError):
            core_services.registrar_evento(
                tipo='LANCAMENTO_QUITADO',
                dominio='FINANCEIRO',
                entidade_tipo='LancamentoFinanceiro',
                entidade_id=42,
                metadata={'valor': 1.25},
            )

    def test_descriptions_are_deterministic_and_do_not_accept_caller_text(self):
        evento = core_services.registrar_evento(
            tipo='PAGAMENTO_FUNCIONARIO_CRIADO',
            dominio='EQUIPE',
            entidade_tipo='Funcionario',
            entidade_id='8',
            metadata={'lancamento_id': '9', 'valor': '1.00'},
        )
        self.assertEqual(
            evento.descricao,
            'Pagamento de funcionário criado (Funcionario #8)',
        )
        self.assertNotIn('metadata', evento.descricao)


class SelectorAndAdminTests(TestCase):
    def setUp(self):
        for index in range(3):
            core_services.registrar_evento(
                tipo='BACKUP_CONCLUIDO',
                dominio='BACKUP',
            )
        core_services.registrar_evento(
            tipo='ORCAMENTO_APROVADO',
            dominio='KANBAN',
            entidade_tipo='ProjetoKanban',
            entidade_id='1',
        )

    def test_selectors_filter_and_order_history(self):
        recent = list(eventos_recentes(limit=2))
        self.assertEqual(len(recent), 2)
        self.assertEqual(recent, sorted(recent, key=lambda item: (item.criado_em, item.id), reverse=True))
        self.assertEqual(eventos_recentes(dominio='KANBAN').count(), 1)
        self.assertEqual(
            historico_entidade('KANBAN', 'ProjetoKanban', '1').count(),
            1,
        )

    def test_selector_limits_and_inputs_are_validated(self):
        for value in (True, False, 0, 101, '2', None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                eventos_recentes(limit=value)
        with self.assertRaises(ValueError):
            eventos_recentes(dominio='INVALIDO')
        with self.assertRaises(ValueError):
            historico_entidade('INVALIDO', 'ProjetoKanban', '1')
        with self.assertRaises(ValueError):
            historico_entidade('KANBAN', ' ', '1')
        with self.assertRaises(ValueError):
            historico_entidade('KANBAN', 'ProjetoKanban', '')

    def test_admin_is_read_only_and_searchable(self):
        model_admin = EventoSistemaAdmin(EventoSistema, admin.site)
        request = object()
        self.assertFalse(model_admin.has_add_permission(request))
        self.assertFalse(model_admin.has_change_permission(request))
        self.assertFalse(model_admin.has_delete_permission(request))
        self.assertEqual(model_admin.list_filter, ('tipo', 'dominio'))
        self.assertEqual(model_admin.search_fields, ('descricao', 'entidade_id'))
        self.assertEqual(model_admin.ordering, ('-criado_em', '-id'))
        self.assertEqual(set(model_admin.readonly_fields), {
            'tipo', 'dominio', 'entidade_tipo', 'entidade_id',
            'descricao', 'metadata', 'criado_em',
        })

    def test_related_deletion_does_not_delete_history(self):
        cliente = Cliente.objects.create(nome='Cliente', whatsapp='11999999999')
        projeto = ProjetoKanban.objects.create(
            cliente=cliente,
            titulo_servico='Projeto',
        )
        evento = core_services.registrar_evento(
            tipo='ORCAMENTO_APROVADO',
            dominio='KANBAN',
            entidade_tipo='ProjetoKanban',
            entidade_id=projeto.pk,
        )
        projeto.delete()
        self.assertTrue(EventoSistema.objects.filter(pk=evento.pk).exists())


class BusinessHistoryTests(TestCase):
    def setUp(self):
        self.cliente = Cliente.objects.create(nome='Cliente', whatsapp='11999999999')
        self.projeto = ProjetoKanban.objects.create(
            cliente=self.cliente,
            titulo_servico='Cozinha planejada',
            etapa='2_ORCAMENTO',
            data_limite_orcamento=date(2026, 10, 31),
        )
        self.funcionario = Funcionario.objects.create(
            nome='João',
            funcao='Marceneiro',
            periodicidade='MENSAL',
            valor_base=Decimal('100.00'),
        )

    def _approve(self):
        return aprovar_orcamento_service(
            self.projeto.pk,
            Decimal('1000.00'),
            Decimal('200.00'),
            'PIX',
            date(2026, 11, 1),
            date(2026, 12, 1),
        )

    def test_approval_creates_one_event_after_transition(self):
        self._approve()
        evento = EventoSistema.objects.get(tipo='ORCAMENTO_APROVADO')
        self.assertEqual(evento.entidade_id, str(self.projeto.pk))
        self.assertEqual(evento.metadata, {})

    def test_approval_idempotent_retry_does_not_duplicate_event(self):
        self._approve()
        self._approve()
        self.assertEqual(EventoSistema.objects.filter(tipo='ORCAMENTO_APROVADO').count(), 1)

    def test_archive_event_only_on_actual_transition(self):
        arquivar_orcamento_service(self.projeto.pk, 'PRECO_ALTO', 'observação')
        arquivar_orcamento_service(self.projeto.pk, 'PRECO_ALTO', 'nova observação')
        eventos = EventoSistema.objects.filter(tipo='ORCAMENTO_ARQUIVADO')
        self.assertEqual(eventos.count(), 1)
        self.assertEqual(eventos.get().metadata, {'motivo_codigo': 'PRECO_ALTO'})

    def test_reactivation_creates_event(self):
        arquivar_orcamento_service(self.projeto.pk, 'SEM_RETORNO')
        reativar_orcamento_service(self.projeto.pk)
        self.assertEqual(EventoSistema.objects.filter(tipo='ORCAMENTO_REATIVADO').count(), 1)

    def test_finalization_creates_event_only_for_delivery_transition(self):
        self.projeto.etapa = '5_ENTREGA'
        self.projeto.save(update_fields=['etapa', 'atualizado_em'])
        finalizar_projeto_service(self.projeto.pk)
        self.assertEqual(EventoSistema.objects.filter(tipo='PROJETO_FINALIZADO').count(), 1)

    def test_employee_payment_creation_and_retry_history(self):
        first = lancar_pagamento_funcionario_service(self.funcionario.pk)
        second = lancar_pagamento_funcionario_service(self.funcionario.pk)
        self.assertTrue(first.foi_criado)
        self.assertFalse(second.foi_criado)
        self.assertEqual(
            EventoSistema.objects.filter(tipo='PAGAMENTO_FUNCIONARIO_CRIADO').count(),
            1,
        )
        self.assertEqual(
            EventoSistema.objects.get(tipo='PAGAMENTO_FUNCIONARIO_CRIADO').metadata,
            {'lancamento_id': str(first.pk), 'valor': '100.00'},
        )

    def test_cancelled_payment_does_not_block_new_history_event(self):
        first = lancar_pagamento_funcionario_service(self.funcionario.pk)
        first.status = 'CANCELADO'
        first.save(update_fields=['status'])
        second = lancar_pagamento_funcionario_service(self.funcionario.pk)
        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(
            EventoSistema.objects.filter(tipo='PAGAMENTO_FUNCIONARIO_CRIADO').count(),
            2,
        )

    def test_settlement_event_follows_saldo_synchronization(self):
        lancamento = LancamentoFinanceiro.objects.create(
            tipo='ENTRADA',
            categoria='SERVICO_CLIENTE',
            projeto=self.projeto,
            descricao='Parcela',
            valor=Decimal('100.00'),
            data_vencimento=date(2026, 10, 22),
            status='PENDENTE',
        )
        registrar_pagamento_service(lancamento.pk, Decimal('100.00'))
        evento = EventoSistema.objects.get(tipo='LANCAMENTO_QUITADO')
        self.assertEqual(evento.metadata, {'valor': '100.00'})

    def test_contact_completion_and_repeat_create_one_event(self):
        agenda = AgendaContato.objects.create(
            cliente=self.cliente,
            data_agendada=date(2026, 10, 22),
            tipo='LIGACAO_MANUAL',
        )
        concluir_pos_venda_service(agenda.pk, 'feedback válido', 'SATISFEITO')
        concluir_pos_venda_service(agenda.pk, 'outro feedback válido', 'SATISFEITO')
        self.assertEqual(EventoSistema.objects.filter(tipo='CONTATO_CONCLUIDO').count(), 1)

    def test_approval_event_failure_rolls_back_project_and_finance(self):
        with patch(
            'apps.kanban_projetos.services.registrar_evento',
            side_effect=ValidationError('history unavailable'),
        ):
            with self.assertRaises(ValidationError):
                self._approve()
        self.projeto.refresh_from_db()
        self.assertEqual(self.projeto.etapa, '2_ORCAMENTO')
        self.assertEqual(LancamentoFinanceiro.objects.count(), 0)

    def test_employee_event_failure_rolls_back_payment(self):
        with patch(
            'apps.equipe.services.registrar_evento',
            side_effect=ValidationError('history unavailable'),
        ):
            with self.assertRaises(ValidationError):
                lancar_pagamento_funcionario_service(self.funcionario.pk)
        self.assertEqual(LancamentoFinanceiro.objects.count(), 0)

    def test_settlement_event_failure_rolls_back_settlement(self):
        lancamento = LancamentoFinanceiro.objects.create(
            tipo='ENTRADA',
            categoria='SERVICO_CLIENTE',
            projeto=self.projeto,
            descricao='Parcela',
            valor=Decimal('100.00'),
            data_vencimento=date(2026, 10, 22),
            status='PENDENTE',
        )
        with patch(
            'apps.financeiro.services.registrar_evento',
            side_effect=ValidationError('history unavailable'),
        ):
            with self.assertRaises(ValidationError):
                registrar_pagamento_service(lancamento.pk, Decimal('100.00'))
        lancamento.refresh_from_db()
        self.assertEqual(lancamento.status, 'PENDENTE')

    def test_contact_event_failure_rolls_back_completion(self):
        agenda = AgendaContato.objects.create(
            cliente=self.cliente,
            data_agendada=date(2026, 10, 22),
            tipo='LIGACAO_MANUAL',
        )
        with patch(
            'apps.clientes_agenda.services.registrar_evento',
            side_effect=ValidationError('history unavailable'),
        ):
            with self.assertRaises(ValidationError):
                concluir_pos_venda_service(agenda.pk, 'feedback válido', 'SATISFEITO')
        agenda.refresh_from_db()
        self.assertFalse(agenda.realizado)
