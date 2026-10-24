"""Step 5A project profitability read-model contract tests.

All fixtures use Django's disposable test database. Raw SQL is used only to
represent legacy stored corruption that model validation correctly rejects.
Each test states the relevant Given/When/Then behavior in its name/docstring.
"""

from dataclasses import FrozenInstanceError, fields
from datetime import date
from decimal import Decimal, DivisionByZero, Inexact, InvalidOperation, Overflow, ROUND_DOWN, Rounded, localcontext

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.clientes_agenda.models import Cliente
from apps.core_sistema.models import EventoSistema
from apps.financeiro.models import LancamentoFinanceiro
from apps.financeiro.selectors import (
    CustoDiretoProjeto,
    ProjetosRentabilidade,
    RentabilidadeProjeto,
    rentabilidade_projeto,
    rentabilidade_projetos,
)
from apps.kanban_projetos.models import ProjetoKanban


D = Decimal
ZERO = D('0.00')
TODAY = date(2026, 10, 24)
DIRECT_CATEGORIES = ('MATERIA_PRIMA', 'FUNCIONARIO', 'OUTROS')
KNOWN_STAGES = (
    '1_CONTATO', '2_ORCAMENTO', '3_APROVADO', '4_PRODUCAO',
    '5_ENTREGA', '6_FINALIZADO', '9_ARQUIVADO',
)
WARNINGS = (
    'CONTRATO_DIVERGE_DO_LEDGER',
    'PENDENTE_COM_DATA_PAGAMENTO',
    'VALOR_ZERO',
    'CUSTO_FIXO_OFICINA_VINCULADO_EXCLUIDO',
    'SERVICO_CLIENTE_EM_SAIDA',
    'ENTRADA_NAO_SERVICO_CLIENTE_EXCLUIDA',
)
FATALS = (
    'ETAPA_INVALIDA',
    'VALOR_CONTRATADO_INVALIDO',
    'PAGO_SEM_DATA_PAGAMENTO',
    'STATUS_INVALIDO',
    'TIPO_INVALIDO',
    'CATEGORIA_INVALIDA',
    'VALOR_MONETARIO_INVALIDO',
)


class ProjectProfitabilityTests(TestCase):
    def customer(self, name='Cliente 124'):
        return Cliente.objects.create(nome=name, whatsapp='11999990000')

    def project(self, title='Projeto 124', stage='1_CONTATO', total='0.00'):
        return ProjetoKanban.objects.create(
            cliente=self.customer(),
            titulo_servico=title,
            etapa=stage,
            data_limite_orcamento=TODAY,
            valor_total=D(total),
        )

    def ledger(self, project=None, *, kind='ENTRADA', category='SERVICO_CLIENTE',
               status='PENDENTE', value='10.00', paid=None, due=TODAY):
        return LancamentoFinanceiro.objects.create(
            projeto=project,
            tipo=kind,
            categoria=category,
            descricao='Fixture 124',
            valor=D(value),
            forma_pagamento='PIX',
            data_vencimento=due,
            data_pagamento=paid,
            status=status,
        )

    def bypass(self, model, pk, field, value):
        """Bypass model validation in the disposable test database only."""
        self.assertNotEqual(connection.settings_dict.get('NAME'), 'db.sqlite3')
        table = connection.ops.quote_name(model._meta.db_table)
        column = connection.ops.quote_name(field)
        with connection.cursor() as cursor:
            cursor.execute(
                f'UPDATE {table} SET {column} = %s WHERE id = %s',
                [value, pk],
            )

    def selected(self, project):
        return rentabilidade_projeto(projeto_id=project.pk)

    def assert_inconsistent(self, selected, *codes):
        self.assertEqual(selected.estado, 'INCONSISTENTE')
        self.assertEqual(selected.inconsistencias, codes)
        for name in (
            'valor_contratado', 'valor_recebido', 'saldo_a_receber',
            'custos_diretos_por_categoria', 'custos_diretos',
            'lucro_direto', 'margem_direta_percentual',
            'entradas_realizadas', 'saidas_realizadas',
            'caixa_liquido_realizado',
        ):
            self.assertIsNone(getattr(selected, name))

    def assert_zero_categories(self, selected):
        self.assertEqual(
            [(row.categoria, row.total, row.pendente, row.pago)
             for row in selected.custos_diretos_por_categoria],
            [(category, ZERO, ZERO, ZERO) for category in DIRECT_CATEGORIES],
        )

    def test_matrix_01_empty_database_returns_empty_tuple(self):
        result = rentabilidade_projetos()
        self.assertEqual(result, ProjetosRentabilidade(projetos=()))

    def test_matrix_02_to_08_all_known_lifecycle_stages_are_eligible(self):
        projects = [self.project(title=stage, stage=stage) for stage in KNOWN_STAGES]
        result = rentabilidade_projetos()
        self.assertEqual({row.projeto_id for row in result.projetos}, {p.pk for p in projects})
        self.assertTrue(all(row.estado == 'SEM_CONTRATO' for row in result.projetos))

    def test_matrix_09_and_10_zero_contract_can_have_no_cost_or_explicit_cost(self):
        free = self.project(title='Sem custo')
        cost = self.project(title='Com custo')
        self.ledger(cost, kind='SAIDA', category='OUTROS', status='PENDENTE', value='3.00')
        selected_free, selected_cost = (
            rentabilidade_projeto(projeto_id=free.pk),
            rentabilidade_projeto(projeto_id=cost.pk),
        )
        self.assertEqual(selected_free.estado, 'SEM_CONTRATO')
        self.assertEqual(selected_free.lucro_direto, ZERO)
        self.assertEqual(selected_cost.estado, 'SEM_CONTRATO')
        self.assertEqual(selected_cost.custos_diretos, D('3.00'))
        self.assertEqual(selected_cost.lucro_direto, D('-3.00'))

    def test_matrix_11_to_13_contract_margin_profit_and_loss(self):
        no_cost = self.project(title='Margem total', total='100.00')
        profit = self.project(title='Lucro', total='100.00')
        loss = self.project(title='Prejuizo', total='100.00')
        self.ledger(profit, kind='SAIDA', category='OUTROS', status='PAGO', value='25.00', paid=TODAY)
        self.ledger(loss, kind='SAIDA', category='OUTROS', status='PAGO', value='125.00', paid=TODAY)
        self.assertEqual(self.selected(no_cost).margem_direta_percentual, D('100'))
        self.assertEqual(self.selected(profit).lucro_direto, D('75.00'))
        self.assertEqual(self.selected(loss).lucro_direto, D('-25.00'))
        self.assertEqual(self.selected(loss).margem_direta_percentual, D('-25'))

    def test_matrix_14_contract_zero_is_sem_contrato(self):
        self.assertEqual(self.selected(self.project()).estado, 'SEM_CONTRATO')

    def test_matrix_15_zero_direct_cost_is_warning_and_does_not_change_total(self):
        project = self.project(total='10.00')
        row = self.ledger(project, kind='SAIDA', category='OUTROS', value='1.00')
        self.bypass(LancamentoFinanceiro, row.pk, 'valor', '0.00')
        selected = self.selected(project)
        self.assertIn('VALOR_ZERO', selected.inconsistencias)
        self.assertEqual(selected.custos_diretos, ZERO)

    def test_matrix_16_to_18_commercial_statuses_drive_revenue_and_cancel_is_excluded(self):
        project = self.project(total='100.00')
        self.ledger(project, status='PAGO', value='30.00', paid=TODAY)
        self.ledger(project, status='PENDENTE', value='50.00')
        self.ledger(project, status='CANCELADO', value='20.00')
        selected = self.selected(project)
        self.assertEqual(selected.valor_recebido, D('30.00'))
        self.assertEqual(selected.entradas_realizadas, D('30.00'))
        self.assertEqual(selected.saldo_a_receber, D('50.00'))
        self.assertIn('CONTRATO_DIVERGE_DO_LEDGER', selected.inconsistencias)

    def test_matrix_19_paid_relevant_without_payment_date_is_fatal(self):
        project = self.project(total='10.00')
        self.ledger(project, status='PAGO', paid=None)
        self.assert_inconsistent(self.selected(project), 'PAGO_SEM_DATA_PAGAMENTO')

    def test_matrix_20_pending_with_payment_date_warns_but_keeps_pending_classification(self):
        project = self.project(total='10.00')
        self.ledger(project, status='PENDENTE', paid=TODAY)
        selected = self.selected(project)
        self.assertEqual(selected.estado, 'DISPONIVEL')
        self.assertEqual(selected.saldo_a_receber, D('10.00'))
        self.assertIn('PENDENTE_COM_DATA_PAGAMENTO', selected.inconsistencias)

    def test_matrix_21_and_67_wrong_valid_entrada_category_is_excluded_and_not_reconciled(self):
        project = self.project(total='100.00')
        self.ledger(project, category='OUTROS', status='PAGO', value='100.00', paid=TODAY)
        selected = self.selected(project)
        self.assertEqual(selected.valor_recebido, ZERO)
        self.assertIn('ENTRADA_NAO_SERVICO_CLIENTE_EXCLUIDA', selected.inconsistencias)
        self.assertIn('CONTRATO_DIVERGE_DO_LEDGER', selected.inconsistencias)

    def test_matrix_22_to_27_each_direct_category_and_status_is_counted(self):
        project = self.project(total='42.00')
        for category in DIRECT_CATEGORIES:
            self.ledger(project, kind='SAIDA', category=category, status='PAGO', value='2.00', paid=TODAY)
            self.ledger(project, kind='SAIDA', category=category, status='PENDENTE', value='5.00')
        selected = self.selected(project)
        self.assertEqual(selected.custos_diretos, D('21.00'))
        self.assertEqual(selected.saidas_realizadas, D('6.00'))
        self.assertEqual(selected.caixa_liquido_realizado, D('-6.00'))
        self.assertEqual(
            [(row.categoria, row.pendente, row.pago) for row in selected.custos_diretos_por_categoria],
            [('MATERIA_PRIMA', D('5.00'), D('2.00')),
             ('FUNCIONARIO', D('5.00'), D('2.00')),
             ('OUTROS', D('5.00'), D('2.00'))],
        )

    def test_matrix_28_and_29_excluded_saida_categories_warn_without_cost(self):
        project = self.project(total='10.00')
        self.ledger(project, kind='SAIDA', category='CUSTO_FIXO_OFICINA', value='3.00')
        self.ledger(project, kind='SAIDA', category='SERVICO_CLIENTE', value='4.00')
        selected = self.selected(project)
        self.assertEqual(selected.custos_diretos, ZERO)
        self.assertIn('CUSTO_FIXO_OFICINA_VINCULADO_EXCLUIDO', selected.inconsistencias)
        self.assertIn('SERVICO_CLIENTE_EM_SAIDA', selected.inconsistencias)

    def test_matrix_30_unlinked_saida_is_not_allocated(self):
        project = self.project(total='10.00')
        self.ledger(None, kind='SAIDA', category='OUTROS', value='5.00')
        self.assertEqual(self.selected(project).custos_diretos, ZERO)

    def test_matrix_31_and_62_cancelled_direct_cost_is_current_state_excluded(self):
        project = self.project(total='10.00')
        row = self.ledger(project, kind='SAIDA', category='OUTROS', status='PAGO', value='5.00', paid=TODAY)
        self.bypass(LancamentoFinanceiro, row.pk, 'status', 'CANCELADO')
        selected = self.selected(project)
        self.assertEqual(selected.custos_diretos, ZERO)
        self.assertEqual(selected.inconsistencias, ('CONTRATO_DIVERGE_DO_LEDGER',))

    def test_matrix_32_and_66_reconciliation_uses_only_active_commercial_ledger(self):
        project = self.project(total='10.00')
        self.ledger(project, status='PAGO', value='3.00', paid=TODAY)
        canceled = self.ledger(project, status='PAGO', value='7.00', paid=TODAY)
        self.bypass(LancamentoFinanceiro, canceled.pk, 'status', 'CANCELADO')
        selected = self.selected(project)
        self.assertIn('CONTRATO_DIVERGE_DO_LEDGER', selected.inconsistencias)
        self.assertEqual(selected.valor_recebido, D('3.00'))

    def test_matrix_33_to_35_invalid_row_classes_are_isolated_per_project(self):
        invalid_status = self.project(title='status', total='1.00')
        status_row = self.ledger(invalid_status)
        self.bypass(LancamentoFinanceiro, status_row.pk, 'status', 'INVALIDO')
        invalid_type = self.project(title='tipo', total='1.00')
        type_row = self.ledger(invalid_type)
        self.bypass(LancamentoFinanceiro, type_row.pk, 'tipo', 'INVALIDO')
        invalid_category = self.project(title='categoria', total='1.00')
        category_row = self.ledger(invalid_category)
        self.bypass(LancamentoFinanceiro, category_row.pk, 'categoria', 'INVALIDO')
        healthy = self.project(title='saudavel', total='1.00')
        result = rentabilidade_projetos()
        by_id = {row.projeto_id: row for row in result.projetos}
        self.assert_inconsistent(by_id[invalid_status.pk], 'STATUS_INVALIDO')
        self.assert_inconsistent(by_id[invalid_type.pk], 'TIPO_INVALIDO')
        self.assert_inconsistent(by_id[invalid_category.pk], 'CATEGORIA_INVALIDA')
        self.assertEqual(by_id[healthy.pk].estado, 'DISPONIVEL')

    def test_matrix_36_to_39_invalid_money_is_fatal_without_silent_rounding(self):
        values = ('-0.01', 'NaN', '100000000.00', '1.234')
        for value in values:
            with self.subTest(value=value):
                project = self.project(title=value, total='10.00')
                row = self.ledger(project, status='PENDENTE', value='1.00')
                self.bypass(LancamentoFinanceiro, row.pk, 'valor', value)
                self.assert_inconsistent(self.selected(project), 'VALOR_MONETARIO_INVALIDO')

    def test_matrix_40_and_65_hostile_decimal_context_is_untouched(self):
        project = self.project(total='100.00')
        self.ledger(project, kind='SAIDA', category='OUTROS', status='PAGO', value='1.23', paid=TODAY)
        with localcontext() as context:
            context.prec = 1
            for signal in context.traps:
                context.traps[signal] = True
            before = (dict(context.flags), dict(context.traps))
            selected = self.selected(project)
            after = (dict(context.flags), dict(context.traps))
        self.assertEqual(before, after)
        self.assertEqual(selected.custos_diretos, D('1.23'))

    def test_hostile_nonterminating_margin_with_traps_is_context_independent(self):
        project = self.project(title='Margem não terminante', total='3.00')
        self.ledger(project, kind='SAIDA', category='OUTROS', status='PAGO', value='1.00', paid=TODAY)
        expected_margin = D('66.66666666666666666666666667')
        with localcontext() as context:
            context.prec = 1
            context.rounding = ROUND_DOWN
            context.traps[Inexact] = True
            context.traps[Rounded] = True
            context.traps[InvalidOperation] = True
            context.traps[DivisionByZero] = True
            context.traps[Overflow] = True
            before = (context.prec, context.rounding, dict(context.flags), dict(context.traps))

            individual = self.selected(project)
            listed = {
                row.projeto_id: row for row in rentabilidade_projetos().projetos
            }[project.pk]

            after = (context.prec, context.rounding, dict(context.flags), dict(context.traps))

        self.assertEqual(individual.lucro_direto, D('2.00'))
        self.assertEqual(individual.margem_direta_percentual, expected_margin)
        self.assertEqual(listed.lucro_direto, D('2.00'))
        self.assertEqual(listed.margem_direta_percentual, expected_margin)
        self.assertEqual(before, after)

    def test_matrix_41_exact_cent_values_are_accepted(self):
        project = self.project(total='1.23')
        row = self.ledger(project, status='PENDENTE', value='1.00')
        self.bypass(LancamentoFinanceiro, row.pk, 'valor', '1.230')
        self.assertEqual(self.selected(project).saldo_a_receber, D('1.23'))

    def test_matrix_42_to_43_healthy_and_inconsistent_projects_are_both_returned(self):
        healthy = self.project(title='A', total='1.00')
        bad = self.project(title='B', total='1.00')
        row = self.ledger(bad)
        self.bypass(LancamentoFinanceiro, row.pk, 'status', 'BAD')
        result = rentabilidade_projetos()
        self.assertEqual(result.projetos[0].projeto_id, healthy.pk)
        self.assertEqual(result.projetos[0].estado, 'DISPONIVEL')
        self.assertEqual(result.projetos[1].estado, 'INCONSISTENTE')

    def test_matrix_44_to_46_sorting_known_stages_titles_and_invalid_last(self):
        late = self.project(title='zeta', stage='9_ARQUIVADO')
        early = self.project(title='zeta', stage='1_CONTATO')
        alpha_upper = self.project(title='Alpha', stage='1_CONTATO')
        alpha_lower = self.project(title='alpha', stage='1_CONTATO')
        invalid = self.project(title='zero', stage='1_CONTATO')
        self.bypass(ProjetoKanban, invalid.pk, 'etapa', 'CORROMPIDA')
        result = rentabilidade_projetos()
        self.assertEqual([row.projeto_id for row in result.projetos], [alpha_upper.pk, alpha_lower.pk, early.pk, late.pk, invalid.pk])
        self.assertEqual(result.projetos[-1].inconsistencias, ('ETAPA_INVALIDA',))

    def test_matrix_47_to_50_query_ceiling_has_no_n_plus_one(self):
        with CaptureQueriesContext(connection) as empty_queries:
            rentabilidade_projetos()
        self.assertLessEqual(len([q for q in empty_queries if q['sql'].lstrip().upper().startswith('SELECT')]), 1)
        for index in range(101):
            self.project(title=f'Projeto {index}', total='1.00')
        with CaptureQueriesContext(connection) as queries:
            result = rentabilidade_projetos()
        selects = [q for q in queries if q['sql'].lstrip().upper().startswith('SELECT')]
        self.assertLessEqual(len(selects), 2)
        self.assertEqual(len(result.projetos), 101)

    def test_matrix_50_individual_selector_has_two_select_ceiling(self):
        project = self.project(total='1.00')
        with CaptureQueriesContext(connection) as queries:
            selected = self.selected(project)
        self.assertEqual(selected.projeto_id, project.pk)
        self.assertLessEqual(len([q for q in queries if q['sql'].lstrip().upper().startswith('SELECT')]), 2)

    def test_matrix_51_to_55_selector_argument_and_missing_project_contract(self):
        for value in (True, 0, -1, '1', 1.5):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'projeto_id deve ser um inteiro positivo\\.'):
                rentabilidade_projeto(projeto_id=value)
        with self.assertRaisesRegex(ValueError, 'Projeto não encontrado\\.'):
            rentabilidade_projeto(projeto_id=999999)

    def test_matrix_56_immutable_public_dataclasses_and_collections(self):
        project = self.project(total='1.00')
        result = self.selected(project)
        self.assertIsInstance(result, RentabilidadeProjeto)
        self.assertIsInstance(result.custos_diretos_por_categoria, tuple)
        self.assertIsInstance(result.custos_diretos_por_categoria[0], CustoDiretoProjeto)
        self.assertIsInstance(result.inconsistencias, tuple)
        with self.assertRaises(FrozenInstanceError):
            result.estado = 'DISPONIVEL'
        with self.assertRaises(FrozenInstanceError):
            result.custos_diretos_por_categoria[0].total = D('1')
        self.assertFalse(any(hasattr(getattr(result, field.name), '_meta') for field in fields(result)))

    def test_matrix_57_and_58_all_three_categories_are_present_in_order(self):
        selected = self.selected(self.project(total='1.00'))
        self.assert_zero_categories(selected)
        self.assertEqual([row.categoria for row in selected.custos_diretos_por_categoria], list(DIRECT_CATEGORIES))

    def test_matrix_59_to_61_reads_are_write_free_deterministic_and_event_free(self):
        project = self.project(total='10.00')
        self.ledger(project, status='PAGO', value='3.00', paid=TODAY)
        before = {
            'projects': list(ProjetoKanban.objects.values()),
            'ledger': list(LancamentoFinanceiro.objects.values()),
            'events': list(EventoSistema.objects.values()),
        }
        with CaptureQueriesContext(connection) as queries:
            first = rentabilidade_projetos()
            second = rentabilidade_projetos()
        self.assertEqual(first, second)
        self.assertTrue(all(q['sql'].lstrip().upper().startswith('SELECT') for q in queries))
        self.assertEqual(before['projects'], list(ProjetoKanban.objects.values()))
        self.assertEqual(before['ledger'], list(LancamentoFinanceiro.objects.values()))
        self.assertEqual(before['events'], list(EventoSistema.objects.values()))

    def test_matrix_63_to_64_realized_cash_separates_pending_and_paid_costs(self):
        project = self.project(total='50.00')
        self.ledger(project, kind='SAIDA', category='OUTROS', status='PENDENTE', value='7.00')
        self.ledger(project, kind='SAIDA', category='OUTROS', status='PAGO', value='3.00', paid=TODAY)
        selected = self.selected(project)
        self.assertEqual(selected.custos_diretos, D('10.00'))
        self.assertEqual(selected.saidas_realizadas, D('3.00'))
        self.assertEqual(selected.caixa_liquido_realizado, D('-3.00'))

    def test_matrix_68_warnings_are_unique_and_in_contract_order(self):
        project = self.project(total='20.00')
        zero = self.ledger(project, status='PENDENTE', value='1.00')
        self.bypass(LancamentoFinanceiro, zero.pk, 'valor', '0.00')
        self.ledger(project, status='PENDENTE', value='1.00', paid=TODAY)
        self.ledger(project, kind='SAIDA', category='CUSTO_FIXO_OFICINA', value='2.00')
        self.ledger(project, kind='SAIDA', category='SERVICO_CLIENTE', value='2.00')
        self.ledger(project, category='OUTROS', value='3.00')
        selected = self.selected(project)
        warnings = [code for code in selected.inconsistencias if code in WARNINGS]
        self.assertEqual(warnings, list(dict.fromkeys(warnings)))
        self.assertEqual(warnings, [code for code in WARNINGS if code in warnings])

    def test_matrix_69_fatal_codes_have_fixed_precedence_not_row_order(self):
        project = self.project(total='1.00')
        self.bypass(ProjetoKanban, project.pk, 'etapa', 'BAD_STAGE')
        self.bypass(ProjetoKanban, project.pk, 'valor_total', '-1.00')
        paid = self.ledger(project, status='PAGO', value='1.00', paid=None)
        invalid_status = self.ledger(project)
        self.bypass(LancamentoFinanceiro, invalid_status.pk, 'status', 'BAD')
        invalid_type = self.ledger(project)
        self.bypass(LancamentoFinanceiro, invalid_type.pk, 'tipo', 'BAD')
        invalid_category = self.ledger(project)
        self.bypass(LancamentoFinanceiro, invalid_category.pk, 'categoria', 'BAD')
        bad_money = self.ledger(project)
        self.bypass(LancamentoFinanceiro, bad_money.pk, 'valor', '-0.01')
        self.assert_inconsistent(
            self.selected(project),
            'ETAPA_INVALIDA', 'VALOR_CONTRATADO_INVALIDO',
            'PAGO_SEM_DATA_PAGAMENTO', 'STATUS_INVALIDO',
            'TIPO_INVALIDO', 'CATEGORIA_INVALIDA',
            'VALOR_MONETARIO_INVALIDO',
        )

    def test_matrix_70_inconsistent_projects_never_expose_partial_metrics(self):
        project = self.project(total='10.00')
        row = self.ledger(project, status='PAGO', paid=None)
        self.assertIsNotNone(row.pk)
        self.assert_inconsistent(self.selected(project), 'PAGO_SEM_DATA_PAGAMENTO')

    def test_contract_value_uses_valor_total_not_legacy_fields(self):
        project = self.project(total='100.00')
        ProjetoKanban.objects.filter(pk=project.pk).update(valor_entrada=D('99.00'), saldo_restante=D('1.00'))
        selected = self.selected(project)
        self.assertEqual(selected.valor_contratado, D('100.00'))

    def test_invalid_project_contract_value_is_isolated(self):
        bad = self.project(title='bad', total='1.00')
        good = self.project(title='good', total='2.00')
        self.bypass(ProjetoKanban, bad.pk, 'valor_total', '1.234')
        result = {row.projeto_id: row for row in rentabilidade_projetos().projetos}
        self.assert_inconsistent(result[bad.pk], 'VALOR_CONTRATADO_INVALIDO')
        self.assertEqual(result[good.pk].valor_contratado, D('2.00'))
