"""111: Given current ledger, When selecting a month, Then honor frozen V1.

Fixtures and bypass SQL are restricted to Django's disposable SQLite test DB.
Each test states its Given/When/Then behavior; no production data is opened.
"""
from dataclasses import FrozenInstanceError
from datetime import date
from decimal import Decimal, ROUND_HALF_EVEN, ROUND_UP, localcontext
from pathlib import Path

from django.db import connection
from django.db.models import CharField
from django.db.models.functions import Cast
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.clientes_agenda.models import Cliente
from apps.kanban_projetos.models import ProjetoKanban
from apps.core_sistema.models import EventoSistema
from apps.equipe.models import Funcionario
from apps.financeiro.models import LancamentoFinanceiro
from apps.financeiro.selectors import (
    CustoFuncionario, EntradaPorForma, FechamentoMensal, fechamento_mensal,
)

D = Decimal
FORMS = ('PIX', 'CARTAO_CREDITO', 'CARTAO_DEBITO', 'DINHEIRO', 'BOLETO')
PREFIX = 'Fechamento mensal indisponível: '
ERRORS = {
    'date': PREFIX + 'lançamento PAGO sem data_pagamento.',
    'status': PREFIX + 'status inválido em lançamento relevante.',
    'tipo': PREFIX + 'tipo inválido em lançamento relevante.',
    'categoria': PREFIX + 'categoria inválida em lançamento relevante.',
    'forma_pagamento': PREFIX + 'forma_pagamento inválida em lançamento relevante.',
    'valor': PREFIX + 'valor monetário inválido em lançamento relevante.',
}


class MonthlyClosingTests(TestCase):
    def ledger(self, value='10.00', **overrides):
        fields = dict(tipo='ENTRADA', categoria='SERVICO_CLIENTE',
                      descricao='Fixture 111', valor=D(value), status='PAGO',
                      data_pagamento=date(2024, 2, 10),
                      data_vencimento=date(2024, 1, 1))
        fields.update(overrides)
        return LancamentoFinanceiro.objects.create(**fields)

    def employee(self, name='Ana', **overrides):
        fields = dict(nome=name, funcao='Marceneiro', periodicidade='DIARIA',
                      valor_base=D('1.00'))
        fields.update(overrides)
        return Funcionario.objects.create(**fields)

    def closing(self):
        return fechamento_mensal(ano=2024, mes=2)

    def bypass(self, row, field, value):
        # Raw SQL is test-only: bypass DecimalField preparation/quantization too.
        self.assertIn(field, {'valor', 'status', 'tipo', 'categoria',
                              'forma_pagamento', 'data_pagamento'})
        self.assert_disposable()
        table = connection.ops.quote_name(LancamentoFinanceiro._meta.db_table)
        column = connection.ops.quote_name(field)
        with connection.cursor() as cursor:
            cursor.execute(f'UPDATE {table} SET {column} = %s WHERE id = %s',
                           [value, row.pk])

    def assert_disposable(self):
        name = str(connection.settings_dict['NAME'])
        self.assertTrue(name == ':memory:' or 'mode=memory' in name)
        self.assertNotEqual(Path(name), Path('C:/desenvolvimento/FinanEP/db.sqlite3'))

    def assert_error(self, kind):
        with self.assertRaises(ValueError) as caught:
            self.closing()
        self.assertEqual(str(caught.exception), ERRORS[kind])

    def test_invalid_inputs_have_exact_order_messages_and_zero_queries(self):
        """Given invalid inputs, When selecting, Then reject before DB access."""
        cases = [
            (True, 0, 'ano deve ser um inteiro.'),
            (False, 2, 'ano deve ser um inteiro.'),
            ('2024', 2, 'ano deve ser um inteiro.'),
            (2024.0, 2, 'ano deve ser um inteiro.'),
            (None, 2, 'ano deve ser um inteiro.'),
            (0, False, 'ano deve estar entre 1 e 9999.'),
            (10000, 2, 'ano deve estar entre 1 e 9999.'),
            (-1, 2, 'ano deve estar entre 1 e 9999.'),
            (2024, True, 'mes deve ser um inteiro.'),
            (2024, False, 'mes deve ser um inteiro.'),
            (2024, '2', 'mes deve ser um inteiro.'),
            (2024, 2.0, 'mes deve ser um inteiro.'),
            (2024, None, 'mes deve ser um inteiro.'),
            (2024, 0, 'mes deve estar entre 1 e 12.'),
            (2024, 13, 'mes deve estar entre 1 e 12.'),
            (2024, -1, 'mes deve estar entre 1 e 12.'),
        ]
        for year, month, message in cases:
            with self.subTest(year=year, month=month), self.assertNumQueries(0):
                with self.assertRaises(ValueError) as caught:
                    fechamento_mensal(ano=year, mes=month)
                self.assertEqual(str(caught.exception), message)

    def test_month_bounds_leap_december_and_extreme_years(self):
        """Given supported dates, When selecting, Then use actual month bounds."""
        for year, month, last in [(2024, 2, 29), (2023, 2, 28),
                                  (2024, 12, 31), (9999, 12, 31), (1, 1, 31)]:
            with self.subTest(year=year, month=month):
                result = fechamento_mensal(ano=year, mes=month)
                self.assertEqual((result.ano, result.mes), (year, month))
                self.assertEqual(result.data_inicio, date(year, month, 1))
                self.assertEqual(result.data_fim, date(year, month, last))

    def test_realized_membership_uses_payment_inclusive_endpoints(self):
        """Given varied due/payment dates, When selecting, Then use payment only."""
        for paid in [date(2024, 2, 1), date(2024, 2, 29)]:
            self.ledger(data_pagamento=paid, data_vencimento=date(2025, 1, 1))
        self.ledger('90', data_pagamento=date(2024, 1, 31))
        self.ledger('80', data_pagamento=date(2024, 3, 1))
        self.assertEqual(self.closing().total_entradas, D('20'))

    def test_pending_and_cancelled_payment_dates_do_not_realize(self):
        """Given unpaid/cancelled rows with payment dates, Then status governs."""
        self.ledger('11', status='PENDENTE')
        self.ledger('12', status='CANCELADO')
        result = self.closing()
        self.assertEqual(result.total_entradas, D('0'))
        self.assertEqual((result.inadimplencia_total, result.inadimplencia_quantidade),
                         (D('11'), 1))

    def test_categories_partition_and_forms_reconcile(self):
        """Given every category/form, When selecting, Then partition each once."""
        for index, form in enumerate(FORMS, 1):
            self.ledger(str(index), forma_pagamento=form, categoria='OUTROS')
        for category, _ in LancamentoFinanceiro.CATEGORIA_CHOICES:
            self.ledger('2', tipo='SAIDA', categoria=category)
        result = self.closing()
        self.assertEqual(tuple(item.forma_pagamento for item in result.entradas_por_forma), FORMS)
        self.assertEqual(tuple(item.total for item in result.entradas_por_forma),
                         tuple(D(i) for i in range(1, 6)))
        self.assertEqual(result.total_entradas, D('15'))
        self.assertEqual(sum(x.total for x in result.entradas_por_forma), result.total_entradas)
        self.assertEqual(result.total_funcionarios, D('2'))
        self.assertEqual(result.outras_saidas, D('8'))
        self.assertEqual(result.total_funcionarios + result.outras_saidas, D('10'))
        self.assertEqual(result.saldo_final, D('5'))
        self.assertEqual(result.funcionarios[0].nome, 'Sem funcionário vinculado')

    def test_employee_identity_order_current_name_inactive_and_null_last(self):
        """Given duplicate/current names and SET_NULL, Then group by ID and sort."""
        employees = [self.employee('z'), self.employee('Ana'), self.employee('Ana', ativo=False),
                     self.employee('Ána'), self.employee('a')]
        for employee in employees:
            self.ledger('3', tipo='SAIDA', categoria='FUNCIONARIO', funcionario=employee)
        self.ledger('2', tipo='SAIDA', categoria='FUNCIONARIO', funcionario=employees[1])
        removed = self.employee('Removed')
        self.ledger('4', tipo='SAIDA', categoria='FUNCIONARIO', funcionario=removed)
        removed.delete()
        self.ledger('1', tipo='SAIDA', categoria='FUNCIONARIO')
        Funcionario.objects.filter(pk=employees[0].pk).update(nome='A')
        expected = sorted([(employees[0].pk, 'A'), *[(e.pk, e.nome) for e in employees[1:]]],
                          key=lambda item: (item[1], item[0]))
        result = self.closing()
        self.assertEqual([(x.funcionario_id, x.nome) for x in result.funcionarios],
                         expected + [(None, 'Sem funcionário vinculado')])
        self.assertEqual(result.total_funcionarios, D('22'))
        self.assertEqual(sum(x.total for x in result.funcionarios), result.total_funcionarios)
        self.assertEqual(result.funcionarios[-1].total, D('5'))

    def test_observed_zero_employee_bucket_is_retained(self):
        """Given a legacy zero employee output, Then retain the observed bucket."""
        employee = self.employee()
        row = self.ledger(tipo='SAIDA', categoria='FUNCIONARIO', funcionario=employee)
        self.bypass(row, 'valor', '0.00')
        result = self.closing()
        self.assertEqual(result.funcionarios, (CustoFuncionario(employee.pk, 'Ana', D('0')),))
        self.assertEqual(result.total_funcionarios, D('0'))

    def test_empty_is_deterministic_frozen_and_zero_filled(self):
        """Given no ledger, Then return immutable, deterministic zero results."""
        result = self.closing()
        self.assertEqual(result, self.closing())
        self.assertIsInstance(result, FechamentoMensal)
        self.assertEqual(result.entradas_por_forma, tuple(EntradaPorForma(f, D('0.00')) for f in FORMS))
        self.assertEqual(result.funcionarios, ())
        for field in ['total_entradas', 'total_funcionarios', 'outras_saidas',
                      'saldo_final', 'inadimplencia_total']:
            self.assertEqual(getattr(result, field), D('0.00'))
        self.assertIsNone(result.funcionarios_percentual)
        self.assertIsNone(result.margem_percentual)
        self.assertEqual(result.inadimplencia_quantidade, 0)
        self.assertEqual(result.semaforo, 'AMARELO')
        for obj, field in [(result, 'ano'), (result.entradas_por_forma[0], 'total'),
                           (CustoFuncionario(None, 'x', D('0')), 'nome')]:
            with self.assertRaises(FrozenInstanceError):
                setattr(obj, field, None)

    def test_form_zero_fill(self):
        """Given one observed form, Then other forms retain canonical zeroes."""
        self.ledger('2', forma_pagamento='BOLETO')
        self.assertEqual(tuple(x.total for x in self.closing().entradas_por_forma),
                         (D('0'), D('0'), D('0'), D('0'), D('2')))

    def test_zero_revenue_negative_balance_is_red(self):
        """Given only costs, Then negative balance overrides zero revenue."""
        self.ledger('1', tipo='SAIDA', categoria='OUTROS')
        result = self.closing()
        self.assertEqual(result.semaforo, 'VERMELHO')
        self.assertIsNone(result.margem_percentual)
        self.assertIsNone(result.funcionarios_percentual)

    def test_semaphore_threshold_and_precedence(self):
        """Given boundary/overlap cases, Then red precedes debt precedes green."""
        revenue = self.ledger('100')
        cost = self.ledger('85.00', tipo='SAIDA', categoria='OUTROS')
        self.assertEqual(self.closing().semaforo, 'VERDE')
        for amount, color in [('85.01', 'AMARELO'), ('84.99', 'VERDE'),
                              ('100', 'AMARELO'), ('101', 'VERMELHO')]:
            self.bypass(cost, 'valor', amount)
            self.assertEqual(self.closing().semaforo, color)
        self.ledger('1', status='PENDENTE', data_pagamento=None)
        self.assertEqual(self.closing().semaforo, 'VERMELHO')
        self.bypass(cost, 'valor', '1')
        self.assertEqual(self.closing().semaforo, 'AMARELO')
        self.assertEqual(revenue.valor, D('100'))

    def test_percentages_local_context_periodic_and_no_presentation_rounding(self):
        """Given 1/3 and altered caller context, Then percentages use 28/HALF_EVEN."""
        self.ledger('3')
        self.ledger('1', tipo='SAIDA', categoria='FUNCIONARIO')
        with localcontext() as expected_ctx:
            expected_ctx.prec = 28
            expected_ctx.rounding = ROUND_HALF_EVEN
            employee_percent = D('1') / D('3') * D('100')
            margin = D('2') / D('3') * D('100')
        with localcontext() as caller:
            caller.prec = 8
            caller.rounding = ROUND_UP
            result = self.closing()
            self.assertEqual((caller.prec, caller.rounding), (8, ROUND_UP))
        self.assertEqual(result.funcionarios_percentual, employee_percent)
        self.assertEqual(result.margem_percentual, margin)
        self.assertIsInstance(result.margem_percentual, D)

    def test_delinquency_old_pending_future_paid_cutoff_and_cancelled(self):
        """Given older debts/current cancellations, Then use cutoff and current ledger."""
        self.ledger('1', status='PENDENTE', data_pagamento=None, data_vencimento=date(2000, 1, 1))
        self.ledger('2', data_pagamento=date(2024, 3, 1))
        self.ledger('3', data_pagamento=date(2024, 2, 29))
        self.ledger('4', data_pagamento=date(2024, 1, 1))
        self.ledger('5', status='CANCELADO', data_pagamento=None)
        self.ledger('6', status='PENDENTE', data_pagamento=None, data_vencimento=date(2024, 3, 1))
        self.ledger('7', status='PENDENTE', data_pagamento=None, data_vencimento=date(2024, 2, 29))
        self.ledger('8', tipo='SAIDA', status='PENDENTE', data_pagamento=None)
        result = self.closing()
        self.assertEqual(result.inadimplencia_total, D('10'))
        self.assertEqual(result.inadimplencia_quantidade, 3)
        self.assertEqual(result.total_entradas, D('3'))
        self.assertEqual(result.semaforo, 'AMARELO')

    def test_month_without_realized_data_can_have_old_debt(self):
        """Given only old pending debt, Then empty cash still reports delinquency."""
        self.ledger(status='PENDENTE', data_pagamento=None)
        result = self.closing()
        self.assertEqual(result.total_entradas, D('0'))
        self.assertEqual(result.inadimplencia_total, D('10'))
        self.assertEqual(result.semaforo, 'AMARELO')

    def test_global_paid_without_date_precedes_all_anomalies(self):
        """Given ANY paid undated row, Then fail globally before other classes."""
        self.ledger(status='PENDENTE', data_pagamento=None)
        self.ledger(tipo='SAIDA', data_pagamento=None, data_vencimento=date(9999, 12, 31))
        bad = self.ledger()
        self.bypass(bad, 'status', 'INVALID')
        self.assert_error('date')
        with self.assertNumQueries(0), self.assertRaisesMessage(ValueError, 'ano deve ser um inteiro.'):
            fechamento_mensal(ano=True, mes=2)

    def test_relevant_choice_anomalies_exact_messages(self):
        """Given relevant invalid/blank choices, Then reject with exact safe errors."""
        for field in ['status', 'tipo', 'categoria', 'forma_pagamento']:
            for value in ['', 'INVALID']:
                with self.subTest(field=field, value=value):
                    row = self.ledger(tipo='SAIDA' if field == 'categoria' else 'ENTRADA')
                    self.bypass(row, field, value)
                    self.assert_error(field)
                    row.delete()

    def test_status_relevance_null_month_and_potential_debt(self):
        """Given invalid status, Then null/payment-month/potential-debt rows block."""
        cases = [dict(data_pagamento=None, tipo='SAIDA', data_vencimento=date(2025, 1, 1)),
                 dict(data_pagamento=date(2024, 2, 2), tipo='SAIDA'),
                 dict(data_pagamento=date(2024, 3, 1)),
                 dict(data_pagamento=date(2024, 1, 1))]
        for fields in cases:
            with self.subTest(fields=fields):
                row = self.ledger(**fields)
                self.bypass(row, 'status', 'INVALID')
                self.assert_error('status')
                row.delete()

    def test_invalid_type_potential_debt_is_relevant(self):
        """Given unknown type on a due pending row, Then potential revenue blocks."""
        row = self.ledger(status='PENDENTE', data_pagamento=None)
        self.bypass(row, 'tipo', '')
        self.assert_error('tipo')

    def test_irrelevant_anomalies_do_not_block(self):
        """Given proven irrelevant anomalies, Then return usable realized totals."""
        entry = self.ledger('7')
        output = self.ledger('2', tipo='SAIDA', categoria='OUTROS')
        cancelled = self.ledger('99', status='CANCELADO')
        old_output = self.ledger('99', tipo='SAIDA', data_pagamento=date(2024, 1, 1))
        future = self.ledger('99', status='PENDENTE', data_pagamento=None,
                             data_vencimento=date(2024, 3, 1))
        self.bypass(entry, 'categoria', '')
        self.bypass(output, 'forma_pagamento', '')
        for field in ['tipo', 'categoria', 'forma_pagamento', 'valor']:
            self.bypass(cancelled, field, 'INVALID')
        self.bypass(old_output, 'status', 'INVALID')
        self.bypass(old_output, 'valor', '-1')
        self.bypass(future, 'tipo', 'INVALID')
        self.bypass(future, 'valor', '-1')
        result = self.closing()
        self.assertEqual((result.total_entradas, result.outras_saidas), (D('7'), D('2')))

    def test_global_class_precedence_independent_of_row_order(self):
        """Given simultaneous classes across rows, Then field priority is global."""
        rows = []
        for field in ['valor', 'forma_pagamento', 'categoria', 'tipo', 'status']:
            row = self.ledger(tipo='SAIDA' if field == 'categoria' else 'ENTRADA')
            self.bypass(row, field, '-1' if field == 'valor' else 'INVALID')
            rows.append((field, row))
        for field, row in reversed(rows):
            self.assert_error(field)
            row.delete()

    def test_raw_overprecision_is_not_silently_quantized(self):
        """Given bypass SQL 1.234, Then detect raw value before Django rounds 1.23."""
        row = self.ledger()
        self.bypass(row, 'valor', '1.234')
        raw = LancamentoFinanceiro.objects.annotate(
            raw=Cast('valor', CharField())).values_list('raw', flat=True).get(pk=row.pk)
        self.assertEqual(D(raw), D('1.234'))
        self.assertEqual(LancamentoFinanceiro.objects.get(pk=row.pk).valor, D('1.23'))
        self.assert_error('valor')

    def test_relevant_invalid_raw_money_and_legacy_zero(self):
        """Given bypass money anomalies, Then reject negatives/nonfinite/scale/magnitude."""
        row = self.ledger()
        for raw in ['-0.01', 'NaN', 'Inf', '-Inf', 'garbage', '100000000', '0.001', '1.234']:
            with self.subTest(raw=raw):
                self.bypass(row, 'valor', raw)
                self.assert_error('valor')
        self.bypass(row, 'valor', '0.00')
        self.assertEqual(self.closing().total_entradas, D('0'))

    def test_delinquency_also_validates_raw_money(self):
        """Given corrupt old debt, Then monetary integrity blocks the closing."""
        row = self.ledger(status='PENDENTE', data_pagamento=None)
        self.bypass(row, 'valor', '1.234')
        self.assert_error('valor')

    def test_raw_valid_cents_sum_without_sqlite_float_residue(self):
        """Given many fractional cents, Then use exact Decimal accumulation."""
        for value in ['0.10', '0.20', '99999999.99']:
            self.ledger(value)
        self.assertEqual(self.closing().total_entradas, D('100000000.29'))

    def test_repeated_selector_is_read_only_and_emits_no_event(self):
        """Given business fixtures, When repeating reads, Then every table stays unchanged."""
        client = Cliente.objects.create(nome='Fixture 111', whatsapp='')
        project = ProjetoKanban.objects.create(cliente=client, titulo_servico='Fixture 111')
        self.ledger(projeto=project)
        EventoSistema.objects.create(
            tipo=EventoSistema._meta.get_field('tipo').choices[0][0],
            dominio=EventoSistema._meta.get_field('dominio').choices[0][0],
            descricao='Fixture 111', metadata={'fixture': 111},
        )
        before = list(LancamentoFinanceiro.objects.values())
        projects_before = list(ProjetoKanban.objects.order_by('pk').values())
        events_before = list(EventoSistema.objects.order_by('pk').values())
        event_count = EventoSistema.objects.count()
        with CaptureQueriesContext(connection) as queries:
            self.assertEqual(self.closing(), self.closing())
        self.assertTrue(all(q['sql'].lstrip().upper().startswith('SELECT') for q in queries))
        self.assertEqual(list(LancamentoFinanceiro.objects.values()), before)
        self.assertEqual(EventoSistema.objects.count(), event_count)
        self.assertEqual(list(ProjetoKanban.objects.order_by('pk').values()), projects_before)
        self.assertEqual(list(EventoSistema.objects.order_by('pk').values()), events_before)

    def test_employee_query_count_is_constant(self):
        """Given one then many employees, Then query count does not grow."""
        self.ledger(tipo='SAIDA', categoria='FUNCIONARIO', funcionario=self.employee())
        with CaptureQueriesContext(connection) as small:
            self.closing()
        for index in range(20):
            self.ledger(tipo='SAIDA', categoria='FUNCIONARIO',
                        funcionario=self.employee(str(index)))
        with CaptureQueriesContext(connection) as large:
            result = self.closing()
        self.assertEqual(len(result.funcionarios), 21)
        self.assertGreater(len(small), 0)
        self.assertEqual(len(small), len(large))

    def test_runtime_database_is_disposable(self):
        """Given Django runner, Then all fixture mutations target memory only."""
        self.assert_disposable()

    def test_s1_stored_numeric_integrity_beyond_lossy_cast(self):
        """Given bypass numeric anomalies, When selecting, Then reject before lossy CAST."""
        row = self.ledger()
        table = connection.ops.quote_name(LancamentoFinanceiro._meta.db_table)
        for raw, cast_text in [('1.234', '1.234'), ('1.230000000000001', '1.23'),
                               ('99999999.99000001', '99999999.99')]:
            with self.subTest(raw=raw):
                self.bypass(row, 'valor', raw)
                with connection.cursor() as cursor:
                    cursor.execute(
                        f'SELECT typeof(valor), valor = ROUND(valor, 2), '
                        f'CAST(valor AS text) FROM {table} WHERE id = %s', [row.pk])
                    evidence = cursor.fetchone()
                self.assertEqual(evidence, ('real', 0, cast_text))
                print('S1 stored numeric evidence:', raw, evidence)
                with CaptureQueriesContext(connection) as queries:
                    self.assert_error('valor')
                sql = queries[0]['sql']
                self.assertIn('CASE WHEN', sql)
                self.assertIn('ROUND(', sql)
                self.assertIn(' = ', sql)
                self.assertIn('exact_cents', sql)
                print('S1 selector generated SQL:', sql)

    def test_s1_exact_cent_equivalents_and_irrelevant_anomalies(self):
        """Given cent-equivalent values/irrelevant corruption, Then accept only relevant cents."""
        row = self.ledger()
        for raw in ['1.23', '1.230', '99999999.99', '0']:
            with self.subTest(raw=raw):
                self.bypass(row, 'valor', raw)
                self.assertEqual(self.closing().total_entradas, D(raw))
        self.bypass(row, 'valor', '1.230000000000001')
        self.bypass(row, 'status', 'CANCELADO')
        self.assertEqual(self.closing().total_entradas, D('0'))
        self.bypass(row, 'status', 'PENDENTE')
        self.assert_error('valor')

    def test_s2_large_entry_under_hostile_context(self):
        """Given low precision/ROUND_UP, Then preserve a large exact entry and caller context."""
        self.ledger('99999999.99')
        with localcontext() as ctx:
            ctx.prec = 8
            ctx.rounding = ROUND_UP
            result = self.closing()
            self.assertEqual((ctx.prec, ctx.rounding), (8, ROUND_UP))
        self.assertEqual(result.total_entradas, D('99999999.99'))
        self.assertEqual(result.entradas_por_forma[0].total, D('99999999.99'))
        self.assertEqual(result.saldo_final, D('99999999.99'))
        self.assertEqual(result.semaforo, 'VERDE')

    def test_s2_all_money_and_threshold_independent_of_context(self):
        """Given large multi-row totals, Then every money field and threshold stays exact."""
        self.ledger('99999999.99')
        self.ledger('0.02')
        employee = self.employee()
        self.ledger('10000000.01', tipo='SAIDA', categoria='FUNCIONARIO', funcionario=employee)
        self.ledger('0.02', tipo='SAIDA', categoria='FUNCIONARIO', funcionario=employee)
        self.ledger('74999999.98', tipo='SAIDA', categoria='OUTROS')
        with localcontext() as ctx:
            ctx.prec = 8
            ctx.rounding = ROUND_UP
            result = self.closing()
            self.assertEqual((ctx.prec, ctx.rounding), (8, ROUND_UP))
        self.assertEqual(result.total_entradas, D('100000000.01'))
        self.assertEqual(result.entradas_por_forma[0].total, D('100000000.01'))
        self.assertEqual(result.total_funcionarios, D('10000000.03'))
        self.assertEqual(result.funcionarios[0].total, D('10000000.03'))
        self.assertEqual(result.outras_saidas, D('74999999.98'))
        self.assertEqual(result.saldo_final, D('15000000.00'))
        self.assertEqual(result.semaforo, 'AMARELO')  # strictly below 15 percent
        self.ledger('99999999.99', status='PENDENTE', data_pagamento=None)
        self.ledger('0.02', status='PENDENTE', data_pagamento=None)
        with localcontext() as ctx:
            ctx.prec = 8
            ctx.rounding = ROUND_UP
            result = self.closing()
        self.assertEqual(result.inadimplencia_total, D('100000000.01'))
        self.assertEqual(result.semaforo, 'AMARELO')
