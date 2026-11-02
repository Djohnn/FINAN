"""Given disposable ledger fixtures, When selecting Central A/R, Then honor V1.

Every corruption fixture asserts an in-memory Django test connection first.
"""
from dataclasses import FrozenInstanceError, fields
from datetime import date, datetime, timedelta
from decimal import ROUND_UP, Decimal, localcontext
from pathlib import Path
from unittest.mock import patch

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.clientes_agenda.models import Cliente
from apps.core_sistema.models import EventoSistema
from apps.financeiro import selectors
from apps.financeiro.models import LancamentoFinanceiro
from apps.kanban_projetos.models import ProjetoKanban

D = Decimal
REF = date(2024, 2, 29)
PREFIX = 'Central de contas a receber indisponível: '
ERRORS = {k: PREFIX + v + ' inválido em lançamento relevante.' for k, v in
          [('status', 'status'), ('tipo', 'tipo'), ('valor', 'valor monetário')]}


class CentralContasReceberTests(TestCase):
    def setUp(self):
        self.assert_disposable()

    def assert_disposable(self):
        name = str(connection.settings_dict['NAME'])
        self.assertTrue(name == ':memory:' or 'mode=memory' in name)
        self.assertNotEqual(Path(name), Path('C:/desenvolvimento/FinanEP/db.sqlite3'))

    def ledger(self, value='10.00', **overrides):
        data = {'tipo': 'ENTRADA', 'categoria': 'SERVICO_CLIENTE', 'descricao': 'Same text',
                    'valor': D(value), 'status': 'PENDENTE', 'data_vencimento': REF}
        data.update(overrides)
        return LancamentoFinanceiro.objects.create(**data)

    def project(self, customer=None):
        if customer is None:
            customer = Cliente.objects.create(nome='Same name', whatsapp='(11) 99999-0000')
        return ProjetoKanban.objects.create(cliente=customer, titulo_servico='Same title')

    def bypass(self, row, field, value):
        self.assert_disposable()
        self.assertIn(field, {'valor', 'status', 'tipo', 'categoria', 'forma_pagamento'})
        table = connection.ops.quote_name(LancamentoFinanceiro._meta.db_table)
        column = connection.ops.quote_name(field)
        with connection.cursor() as cursor:
            cursor.execute(f'UPDATE {table} SET {column} = %s WHERE id = %s', [value, row.pk])

    def central(self, reference=REF):
        return selectors.central_contas_receber(data_referencia=reference)

    def error(self, kind):
        with self.assertNumQueries(1), self.assertRaises(ValueError) as caught:
            self.central()
        self.assertEqual(str(caught.exception), ERRORS[kind])

    def test_public_api_exists(self):
        """Given frozen API, When importing, Then all public symbols exist."""
        for name in ('central_contas_receber', 'CentralContasReceber',
                     'RecebivelCentral', 'ClassificacaoRecebivel', 'InconsistenciaRecebivel'):
            self.assertTrue(hasattr(selectors, name), name)

    def test_input_exact_type_and_message_before_queries(self):
        """Given invalid dates, When selecting, Then reject with zero queries."""
        class DateSubclass(date):
            pass
        for value in (datetime(2024, 2, 29), '2024-02-29', True, False, None,
                      1, object(), DateSubclass(2024, 2, 29)):
            with self.subTest(value=value), self.assertNumQueries(0):
                with self.assertRaises(ValueError) as caught:
                    self.central(value)
                self.assertEqual(str(caught.exception),
                                 'data_referencia deve ser uma data válida sem horário.')
        with self.assertRaises(TypeError):
            selectors.central_contas_receber()

    def test_empty_one_query_and_exact_public_fields(self):
        """Given no rows, When selecting, Then return four zero indicators."""
        with self.assertNumQueries(1):
            result = self.central()
        self.assertEqual([f.name for f in fields(result)], ['data_referencia',
                         'total_a_receber', 'total_vencido', 'clientes_em_atraso',
                         'maior_atraso_dias', 'recebiveis'])
        self.assertEqual(result.data_referencia, REF)
        self.assertEqual((result.total_a_receber, result.total_vencido,
                          result.clientes_em_atraso, result.maior_atraso_dias,
                          result.recebiveis), (D('0.00'), D('0.00'), 0, None, ()))
        self.assertEqual(result.total_a_receber.as_tuple().exponent, -2)

    def test_active_membership_all_categories(self):
        """Given status/type/category combinations, Then only active input remains."""
        ids = [self.ledger(categoria=c).pk for c, _ in LancamentoFinanceiro.CATEGORIA_CHOICES]
        for status in ('PAGO', 'CANCELADO'):
            self.ledger(status=status, data_pagamento=None)
        self.ledger(tipo='SAIDA')
        result = self.central()
        self.assertEqual([r.lancamento_id for r in result.recebiveis], ids)
        self.assertEqual(result.total_a_receber, D('50.00'))

    def test_dates_windows_and_sorting(self):
        """Given mixed due dates, Then sort by class/date/id with exact windows."""
        offsets = [31, 8, 0, -1, 30, 1, 7, -10, 0]
        rows = {self.ledger(data_vencimento=REF + timedelta(days=n)).pk: n for n in offsets}
        result = self.central()
        self.assertEqual([r.lancamento_id for r in result.recebiveis],
                         sorted(rows, key=lambda pk: (rows[pk], pk)))
        for row in result.recebiveis:
            delta = rows[row.lancamento_id]
            self.assertEqual(row.classificacao, 'ATRASADO' if delta < 0 else
                             'VENCE_HOJE' if delta == 0 else 'A_VENCER')
            self.assertEqual(row.dias_atraso, -delta if delta < 0 else None)
            self.assertEqual(row.nos_proximos_7_dias, 1 <= delta <= 7)
            self.assertEqual(row.nos_proximos_30_dias, 1 <= delta <= 30)

    def test_extreme_dates_year_transition_and_leap(self):
        """Given date endpoints and calendar transitions, Then no overflow occurs."""
        row = self.ledger()
        for reference, due, delta in [(date.min, date.min, 0), (date.max, date.max, 0),
                                     (date.max, date.min, -3652058),
                                     (date.min, date.max, 3652058),
                                     (date(2023, 12, 31), date(2024, 1, 1), 1),
                                     (date(2024, 2, 28), REF, 1)]:
            LancamentoFinanceiro.objects.filter(pk=row.pk).update(data_vencimento=due)
            selected = self.central(reference).recebiveis[0]
            self.assertEqual(selected.dias_atraso, -delta if delta < 0 else None)
            self.assertEqual(selected.nos_proximos_7_dias, 1 <= delta <= 7)

    def test_explicit_reference_ignores_clock_and_timezone(self):
        """Given changing global clocks, Then explicit date alone determines output."""
        self.ledger()
        baseline = self.central()
        with timezone.override('Pacific/Kiritimati'), patch(
                'django.utils.timezone.localdate', side_effect=AssertionError('clock lookup')):
            self.assertEqual(self.central(), baseline)

    def test_identity_installments_homonyms_and_distinct_customers(self):
        """Given homonyms and installments, Then retain rows and count customer IDs."""
        first = self.project()
        second = self.project(first.cliente)
        third = self.project()
        for project in (first, first, second, third):
            self.ledger(projeto=project, data_vencimento=REF - timedelta(days=2))
        result = self.central()
        self.assertEqual(len(result.recebiveis), 4)
        self.assertEqual(result.clientes_em_atraso, 2)
        self.assertEqual(result.total_vencido, D('40.00'))
        self.assertEqual([r.projeto_id for r in result.recebiveis],
                         [first.pk, first.pk, second.pk, third.pk])
        self.assertEqual([r.cliente_id for r in result.recebiveis],
                         [first.cliente_id] * 3 + [third.cliente_id])

    def test_founder_4a_unlinked_totals_and_no_text_recovery(self):
        """Given unlinked text matching known names, Then never recover identity."""
        project = self.project()
        self.ledger('7', projeto=project, data_vencimento=REF - timedelta(days=1))
        self.ledger('13', descricao='Same name Same title',
                    data_vencimento=REF - timedelta(days=20))
        result = self.central()
        row = result.recebiveis[0]
        self.assertEqual((row.projeto_id, row.projeto_titulo, row.cliente_id,
                          row.cliente_nome, row.cliente_whatsapp), (None,) * 5)
        self.assertTrue(row.sem_projeto_vinculado)
        self.assertTrue(row.sem_cliente_vinculado)
        self.assertFalse(row.whatsapp_elegivel)
        self.assertEqual((result.total_a_receber, result.total_vencido,
                          result.clientes_em_atraso, result.maior_atraso_dias),
                         (D('20.00'), D('20.00'), 1, 20))

    def test_missing_customer_context_with_resolved_project(self):
        """Given a dangling legacy customer FK, Then preserve project and debt."""
        project = self.project()
        self.ledger(projeto=project)
        # SQLite FK checks are deferred by TestCase; restore before constraint teardown.
        table = connection.ops.quote_name(ProjetoKanban._meta.db_table)
        try:
            with connection.cursor() as cursor:
                cursor.execute(f'UPDATE {table} SET cliente_id = %s WHERE id = %s',
                               [99999999, project.pk])
            row = self.central().recebiveis[0]
            self.assertEqual(row.projeto_id, project.pk)
            self.assertFalse(row.sem_projeto_vinculado)
            self.assertTrue(row.sem_cliente_vinculado)
            self.assertIsNone(row.cliente_id)
            self.assertIsNone(row.cliente_nome)
            self.assertIsNone(row.cliente_whatsapp)
            self.assertFalse(row.whatsapp_elegivel)
        finally:
            with connection.cursor() as cursor:
                cursor.execute(f'UPDATE {table} SET cliente_id = %s WHERE id = %s',
                               [project.cliente_id, project.pk])

    def test_zero_a_b_c_d_and_positive_only_indicators(self):
        """Given ZERO-A/B/C/D legacy rows, Then retain but exclude positive indicators."""
        project = self.project()
        for delta in (-100, 0, 1, 30):
            row = self.ledger(projeto=project, data_vencimento=REF + timedelta(days=delta))
            self.bypass(row, 'valor', '0.00')
        result = self.central()
        self.assertEqual(len(result.recebiveis), 4)
        self.assertEqual((result.total_a_receber, result.total_vencido,
                          result.clientes_em_atraso, result.maior_atraso_dias),
                         (D('0.00'), D('0.00'), 0, None))
        for row in result.recebiveis:
            self.assertEqual(row.valor.as_tuple(), D('0.00').as_tuple())
            self.assertEqual(row.inconsistencias, ('VALOR_ZERO',))
            self.assertFalse(row.whatsapp_elegivel)
        self.assertEqual(result.recebiveis[0].dias_atraso, 100)
        self.ledger('5', data_vencimento=REF - timedelta(days=2))
        self.assertEqual(self.central().maior_atraso_dias, 2)

    def test_no_positive_overdue_means_no_maximum(self):
        """Given only today/future positive debt, Then no overdue maximum exists."""
        self.ledger()
        self.ledger(data_vencimento=REF + timedelta(days=1))
        self.assertIsNone(self.central().maior_atraso_dias)

    def test_nonfatal_inconsistencies_fixed_order(self):
        """Given all controlled inconsistencies, Then retain debt in fixed code order."""
        row = self.ledger(data_pagamento=REF)
        self.bypass(row, 'valor', '0')
        self.bypass(row, 'categoria', 'BAD')
        self.bypass(row, 'forma_pagamento', 'BAD')
        selected = self.central().recebiveis[0]
        self.assertEqual(selected.inconsistencias, ('VALOR_ZERO',
                         'PENDENTE_COM_DATA_PAGAMENTO', 'CATEGORIA_INVALIDA',
                         'FORMA_PAGAMENTO_INVALIDA'))
        self.assertIsNone(selected.categoria)
        self.assertIsNone(selected.forma_pagamento)
        self.bypass(row, 'valor', '12.34')
        self.assertEqual(self.central().total_a_receber, D('12.34'))
        self.assertEqual(self.central().recebiveis[0].inconsistencias,
                         selected.inconsistencias[1:])

    def test_invalid_money_stored_distinctly_rejected(self):
        """Given raw corrupt stored money, Then reject without lossy conversion."""
        row = self.ledger()
        for value in ('-0.01', 'NaN', 'Inf', '-Inf', 'not money', '100000000',
                      '1.234', '1.230000000000001', '99999999.99000001'):
            with self.subTest(value=value):
                self.bypass(row, 'valor', value)
                self.error('valor')

    def test_exact_cents_trailing_zero_and_large_sum(self):
        """Given exact cents including field maximum, Then sum above field magnitude."""
        values = ('0.01', '0.10', '0.29', '1.23', '1.230', '99999999.99', '99999999.99')
        for value in values:
            row = self.ledger()
            self.bypass(row, 'valor', value)
        result = self.central()
        self.assertEqual([r.valor for r in result.recebiveis], [D(v) for v in values])
        self.assertEqual(result.total_a_receber, D('200000002.84'))
        self.assertTrue(all(r.valor.as_tuple().exponent == -2 for r in result.recebiveis))

    def test_decimal_context_fully_preserved(self):
        """Given hostile caller context, Then exact results leave every context field unchanged."""
        self.ledger('99999999.99', data_vencimento=REF - timedelta(days=1))
        self.ledger('0.01')
        expected = self.central()
        for precision in (1, 2, 6):
            with self.subTest(precision=precision), localcontext() as ctx:
                ctx.prec = precision
                ctx.rounding = ROUND_UP
                ctx.Emin = -1
                ctx.Emax = 1
                for signal in ctx.traps:
                    ctx.traps[signal] = True
                # Existing flags must remain unchanged too.
                for index, signal in enumerate(ctx.flags):
                    ctx.flags[signal] = bool(index % 2)
                before = (str(ctx), dict(ctx.flags), dict(ctx.traps))
                self.assertEqual(self.central(), expected)
                self.assertEqual((str(ctx), dict(ctx.flags), dict(ctx.traps)), before)

    def test_anomaly_precedence_independent_of_insertion_order(self):
        """Given simultaneous anomalies in either order, Then status precedes type/money."""
        for order in (('valor', 'tipo', 'status'), ('status', 'tipo', 'valor')):
            created = []
            for field in order:
                row = self.ledger(data_vencimento=date.max)
                self.bypass(row, field, 'BAD' if field != 'valor' else '-1')
                created.append((row, field))
            self.error('status')
            for row, field in created:
                if field == 'status':
                    self.bypass(row, field, 'PAGO')
            self.error('tipo')
            for row, field in created:
                if field == 'tipo':
                    self.bypass(row, field, 'SAIDA')
            self.error('valor')
            for row, field in created:
                if field == 'valor':
                    self.bypass(row, 'status', 'CANCELADO')

    def test_excluded_anomalies_do_not_globally_block(self):
        """Given valid exclusion status/type, Then other invalid fields are irrelevant."""
        for status, kind in (('PENDENTE', 'SAIDA'), ('PAGO', 'BAD'), ('CANCELADO', 'BAD')):
            row = self.ledger(status=status)
            for field, value in [('tipo', kind), ('valor', 'NaN'),
                                 ('categoria', 'BAD'), ('forma_pagamento', 'BAD')]:
                self.bypass(row, field, value)
        row = self.ledger(tipo='SAIDA')
        self.bypass(row, 'status', 'BAD')
        self.assertEqual(self.central().recebiveis, ())

    def test_whatsapp_semantics_without_length_rule(self):
        """Given varied phones, Then only digits and structured positive debt enable collection."""
        project = self.project()
        self.ledger(projeto=project)
        for phone, eligible in [('(11) 99999-0000', True), ('1', True), ('', False),
                                ('   ', False), ('()+-abc', False)]:
            Cliente.objects.filter(pk=project.cliente_id).update(whatsapp=phone)
            with self.subTest(phone=phone), self.assertNumQueries(1):
                selected = self.central().recebiveis[0]
                self.assertEqual(selected.cliente_whatsapp, phone)
                self.assertEqual(selected.whatsapp_elegivel, eligible)
        self.assertNotIn('url', [f.name for f in fields(selected)])

    def test_immutability_no_orm_objects(self):
        """Given returned dataclasses, Then collections and fields are immutable."""
        self.ledger()
        result = self.central()
        self.assertIsInstance(result, selectors.CentralContasReceber)
        self.assertIsInstance(result.recebiveis, tuple)
        row = result.recebiveis[0]
        self.assertIsInstance(row, selectors.RecebivelCentral)
        self.assertIsInstance(row.inconsistencias, tuple)
        for obj, field in ((result, 'data_referencia'), (row, 'valor')):
            with self.assertRaises(FrozenInstanceError):
                setattr(obj, field, None)
        self.assertTrue(all(not hasattr(getattr(row, f.name), '_meta') for f in fields(row)))

    def test_small_and_large_are_one_select_without_config_or_balance_lookup(self):
        """Given growing independent projects/debts, Then query count stays exactly one."""
        for size in (1, 160):
            for _ in range(size):
                self.ledger(projeto=self.project())
            with patch.object(ProjetoKanban, 'saldo_em_aberto',
                              new_callable=property, fget=lambda _: self.fail('balance lookup')), CaptureQueriesContext(connection) as queries:
                    result = self.central()
            self.assertEqual(len(queries), 1)
            sql = queries[0]['sql'].upper()
            self.assertTrue(sql.startswith('SELECT'))
            self.assertNotIn('CONFIGURACAO', sql)
            self.assertIn('LEFT OUTER JOIN', sql)
            self.assertEqual(len(result.recebiveis), 1 if size == 1 else 161)

    def test_read_only_deterministic_no_events_or_state_changes(self):
        """Given a ledger/project snapshot, Then repeated selection emits SELECT only."""
        self.ledger(projeto=self.project())
        models = (LancamentoFinanceiro, ProjetoKanban, EventoSistema)
        before = [list(model.objects.values()) for model in models]
        with CaptureQueriesContext(connection) as queries:
            first, second = self.central(), self.central()
        self.assertEqual(first, second)
        self.assertEqual(len(queries), 2)
        self.assertTrue(all(q['sql'].lstrip().upper().startswith('SELECT') for q in queries))
        self.assertEqual([list(model.objects.values()) for model in models], before)

    def test_missing_project_target_is_not_a_resolved_identity(self):
        """Given a dangling legacy project FK, Then return unlinked debt and null context."""
        row = self.ledger()
        table = connection.ops.quote_name(LancamentoFinanceiro._meta.db_table)
        try:
            with connection.cursor() as cursor:
                cursor.execute(f'UPDATE {table} SET projeto_id = %s WHERE id = %s',
                               [99999999, row.pk])
            result = self.central()
            selected = result.recebiveis[0]
            self.assertTrue(selected.sem_projeto_vinculado)
            self.assertTrue(selected.sem_cliente_vinculado)
            self.assertIsNone(selected.projeto_id)
            self.assertIsNone(selected.projeto_titulo)
            self.assertIsNone(selected.cliente_id)
            self.assertFalse(selected.whatsapp_elegivel)
            self.assertEqual(result.total_a_receber, D('10.00'))
        finally:
            with connection.cursor() as cursor:
                cursor.execute(f'UPDATE {table} SET projeto_id = NULL WHERE id = %s', [row.pk])

    def test_sqlite_collapsed_literal_is_not_claimed_recoverable(self):
        """Given a literal SQLite stores as exact cents, Then honor stored numeric truth."""
        row = self.ledger()
        self.bypass(row, 'valor', '1.23000000000000000000000000000000000001')
        table = connection.ops.quote_name(LancamentoFinanceiro._meta.db_table)
        with connection.cursor() as cursor:
            cursor.execute(f'SELECT valor = ROUND(valor, 2) FROM {table} WHERE id = %s', [row.pk])
            self.assertEqual(cursor.fetchone()[0], 1)
        self.assertEqual(self.central().recebiveis[0].valor, D('1.23'))

    def test_nonfatal_category_and_form_are_independent(self):
        """Given one invalid code at a time, Then keep positive debt and valid code."""
        row = self.ledger()
        self.bypass(row, 'categoria', 'BAD')
        selected = self.central().recebiveis[0]
        self.assertIsNone(selected.categoria)
        self.assertEqual(selected.forma_pagamento, 'PIX')
        self.assertEqual(selected.inconsistencias, ('CATEGORIA_INVALIDA',))
        self.bypass(row, 'categoria', 'OUTROS')
        self.bypass(row, 'forma_pagamento', 'BAD')
        selected = self.central().recebiveis[0]
        self.assertEqual(selected.categoria, 'OUTROS')
        self.assertIsNone(selected.forma_pagamento)
        self.assertEqual(selected.inconsistencias, ('FORMA_PAGAMENTO_INVALIDA',))
        self.assertEqual(self.central().total_a_receber, D('10.00'))

    def test_row_public_shape_and_all_valid_payment_codes(self):
        """Given every valid payment code, Then preserve codes and exact immutable shape."""
        for form, _ in LancamentoFinanceiro.FORMA_PAGAMENTO_CHOICES:
            self.ledger(forma_pagamento=form)
        result = self.central()
        self.assertEqual([r.forma_pagamento for r in result.recebiveis],
                         [f for f, _ in LancamentoFinanceiro.FORMA_PAGAMENTO_CHOICES])
        self.assertEqual([f.name for f in fields(result.recebiveis[0])], [
            'lancamento_id', 'projeto_id', 'projeto_titulo', 'cliente_id', 'cliente_nome',
            'cliente_whatsapp', 'sem_projeto_vinculado', 'sem_cliente_vinculado',
            'descricao', 'categoria', 'valor', 'forma_pagamento', 'data_vencimento',
            'classificacao', 'dias_atraso', 'nos_proximos_7_dias', 'nos_proximos_30_dias',
            'inconsistencias', 'whatsapp_elegivel'])

    def test_invalid_money_also_preserves_caller_context(self):
        """Given corrupt money and hostile context, Then reject without changing flags."""
        row = self.ledger()
        self.bypass(row, 'valor', 'NaN')
        with localcontext() as ctx:
            ctx.prec = 1
            for signal in ctx.traps:
                ctx.traps[signal] = True
            before = (str(ctx), dict(ctx.flags), dict(ctx.traps))
            self.error('valor')
            self.assertEqual((str(ctx), dict(ctx.flags), dict(ctx.traps)), before)
