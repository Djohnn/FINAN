import sqlite3
from datetime import date, timedelta
from decimal import Decimal

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.models.deletion import ProtectedError
from django.db.migrations.executor import MigrationExecutor
from django.test import RequestFactory, TestCase, TransactionTestCase
from django.utils import timezone

from apps.clientes_agenda.models import Cliente
from apps.equipe.models import Funcionario
from apps.financeiro.admin import LancamentoFinanceiroAdmin
from apps.financeiro.models import DespesaRecorrente, LancamentoFinanceiro
from apps.kanban_projetos.models import ProjetoKanban


class DespesaRecorrenteModelTests(TestCase):
    def test_model_declares_required_fields_and_financial_choices(self):
        field_names = {
            field.name
            for field in DespesaRecorrente._meta.get_fields()
            if getattr(field, 'concrete', False)
        }

        self.assertTrue(
            {
                'descricao',
                'categoria',
                'valor',
                'forma_pagamento',
                'dia_vencimento',
                'data_inicio',
                'data_fim',
                'ativo',
                'observacao',
                'criado_em',
            }.issubset(field_names)
        )
        self.assertEqual(
            dict(DespesaRecorrente._meta.get_field('categoria').choices),
            dict(DespesaRecorrente.CATEGORIA_CHOICES),
        )
        self.assertEqual(
            dict(DespesaRecorrente._meta.get_field('forma_pagamento').choices),
            dict(DespesaRecorrente.FORMA_PAGAMENTO_CHOICES),
        )

        recorrencia = DespesaRecorrente.objects.create(
            descricao='Internet da oficina',
            categoria='CUSTO_FIXO_OFICINA',
            valor=Decimal('149.90'),
            forma_pagamento='PIX',
            dia_vencimento=10,
            data_inicio=date(2026, 10, 1),
        )
        self.assertTrue(recorrencia.ativo)
        self.assertIsNotNone(recorrencia.criado_em)

    def _kwargs(self, **overrides):
        return {
            'descricao': 'Energia da oficina',
            'categoria': 'CUSTO_FIXO_OFICINA',
            'valor': Decimal('250.00'),
            'forma_pagamento': 'BOLETO',
            'dia_vencimento': 10,
            'data_inicio': date(2026, 10, 1),
            **overrides,
        }

    def test_rejects_invalid_money_without_rounding(self):
        for value in (
            Decimal('0'),
            Decimal('-0.01'),
            Decimal('1.234'),
            Decimal('NaN'),
            Decimal('Infinity'),
            Decimal('100000000.00'),
        ):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                DespesaRecorrente.objects.create(**self._kwargs(valor=value))

    def test_rejects_invalid_choice_day_and_date_range(self):
        cases = (
            {'categoria': 'INVALIDA'},
            {'forma_pagamento': 'INVALIDA'},
            {'dia_vencimento': 0},
            {'dia_vencimento': 32},
            {'data_fim': date(2026, 9, 30)},
            {'data_fim': 'not-a-date'},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides), self.assertRaises(ValidationError):
                DespesaRecorrente.objects.create(**self._kwargs(**overrides))

    def test_criado_em_is_immutable_after_creation(self):
        recorrencia = DespesaRecorrente.objects.create(**self._kwargs())
        criado_em = recorrencia.criado_em
        recorrencia.criado_em = criado_em - timedelta(days=1)

        with self.assertRaises(ValidationError):
            recorrencia.save()

        recorrencia.refresh_from_db()
        self.assertEqual(recorrencia.criado_em, criado_em)


class LedgerRecurrenceModelTests(TestCase):
    def setUp(self):
        self.recorrencia = DespesaRecorrente.objects.create(
            descricao='Internet da oficina',
            categoria='CUSTO_FIXO_OFICINA',
            valor=Decimal('149.90'),
            forma_pagamento='PIX',
            dia_vencimento=10,
            data_inicio=date(2026, 10, 1),
        )

    def _kwargs(self, **overrides):
        return {
            'tipo': 'SAIDA',
            'categoria': 'CUSTO_FIXO_OFICINA',
            'descricao': 'Internet outubro',
            'valor': Decimal('149.90'),
            'forma_pagamento': 'PIX',
            'data_vencimento': date(2026, 10, 10),
            'status': 'PENDENTE',
            **overrides,
        }

    def test_legacy_rows_keep_both_recurrence_fields_null(self):
        rows = [
            LancamentoFinanceiro.objects.create(**self._kwargs()),
            LancamentoFinanceiro.objects.create(**self._kwargs(descricao='Outra linha')),
        ]
        self.assertEqual(
            list(
                LancamentoFinanceiro.objects.filter(pk__in=[row.pk for row in rows])
                .values_list('recorrencia_id', 'competencia')
            ),
            [(None, None), (None, None)],
        )

    def test_recurrence_requires_competence_and_competence_requires_recurrence(self):
        with self.assertRaises(ValidationError):
            LancamentoFinanceiro.objects.create(
                **self._kwargs(recorrencia=self.recorrencia)
            )
        with self.assertRaises(ValidationError):
            LancamentoFinanceiro.objects.create(
                **self._kwargs(competencia=date(2026, 10, 1))
            )

    def test_competence_must_be_first_day_and_february_is_valid(self):
        with self.assertRaises(ValidationError):
            LancamentoFinanceiro.objects.create(
                **self._kwargs(competencia=date(2026, 10, 2), recorrencia=self.recorrencia)
            )

        row = LancamentoFinanceiro.objects.create(
            **self._kwargs(
                descricao='Internet fevereiro',
                data_vencimento=date(2027, 2, 10),
                competencia=date(2027, 2, 1),
                recorrencia=self.recorrencia,
            )
        )
        self.assertEqual(row.competencia, date(2027, 2, 1))

    def test_competence_cannot_precede_recurrence_creation_month_cutoff(self):
        cutoff = timezone.localtime(self.recorrencia.criado_em).date().replace(day=1)
        previous_month_cutoff = (cutoff - timedelta(days=1)).replace(day=1)
        with self.assertRaises(ValidationError):
            LancamentoFinanceiro.objects.create(
                **self._kwargs(
                    competencia=previous_month_cutoff,
                    recorrencia=self.recorrencia,
                )
            )

    def test_recurrence_and_competence_pair_is_unique(self):
        kwargs = self._kwargs(
            competencia=date(2026, 10, 1),
            recorrencia=self.recorrencia,
        )
        LancamentoFinanceiro.objects.create(**kwargs)
        with self.assertRaises(IntegrityError):
            LancamentoFinanceiro.objects.create(**kwargs)

    def test_identity_is_immutable_but_status_and_set_null_updates_remain_allowed(self):
        cliente = Cliente.objects.create(nome='Cliente 7A', whatsapp='11999999999')
        projeto = ProjetoKanban.objects.create(
            cliente=cliente,
            titulo_servico='Projeto 7A',
            etapa='1_CONTATO',
        )
        funcionario = Funcionario.objects.create(
            nome='Funcionário 7A',
            funcao='Montador',
            periodicidade='MENSAL',
            valor_base=Decimal('100.00'),
        )
        row = LancamentoFinanceiro.objects.create(
            **self._kwargs(
                projeto=projeto,
                funcionario=funcionario,
                competencia=date(2026, 10, 1),
                recorrencia=self.recorrencia,
            )
        )

        row.status = 'PAGO'
        row.data_pagamento = date(2026, 10, 10)
        row.save(update_fields=['status', 'data_pagamento'])
        row.refresh_from_db()
        self.assertEqual(row.status, 'PAGO')
        self.assertEqual(row.data_pagamento, date(2026, 10, 10))

        with self.assertRaises(ValidationError):
            row.competencia = date(2026, 11, 1)
            row.save()

        row.refresh_from_db()
        LancamentoFinanceiro.objects.filter(pk=row.pk).update(
            recorrencia=self.recorrencia,
            competencia=date(2026, 10, 1),
        )
        LancamentoFinanceiro.objects.filter(pk=row.pk).update(status='CANCELADO')
        row.refresh_from_db()
        self.assertEqual(row.status, 'CANCELADO')

        projeto.delete()
        funcionario.delete()
        row.refresh_from_db()
        self.assertIsNone(row.projeto_id)
        self.assertIsNone(row.funcionario_id)

    def test_model_and_queryset_delete_cannot_remove_recurring_ledger(self):
        row = LancamentoFinanceiro.objects.create(
            **self._kwargs(
                competencia=date(2026, 10, 1),
                recorrencia=self.recorrencia,
            )
        )
        row.status = 'CANCELADO'
        row.save(update_fields=['status'])
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                row.delete()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                LancamentoFinanceiro.objects.filter(pk=row.pk).delete()
        self.assertTrue(LancamentoFinanceiro.objects.filter(pk=row.pk).exists())

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                LancamentoFinanceiro.objects.filter(pk=row.pk).update(
                    recorrencia=None,
                    competencia=None,
                )

    def test_legacy_ledger_can_be_deleted_and_recurrence_is_protected(self):
        legacy = LancamentoFinanceiro.objects.create(**self._kwargs())
        legacy.delete()
        self.assertFalse(LancamentoFinanceiro.objects.filter(pk=legacy.pk).exists())

        linked = LancamentoFinanceiro.objects.create(
            **self._kwargs(
                competencia=date(2026, 10, 1),
                recorrencia=self.recorrencia,
            )
        )
        with self.assertRaises(ProtectedError):
            self.recorrencia.delete()
        self.assertTrue(LancamentoFinanceiro.objects.filter(pk=linked.pk).exists())


class RawSQLitePhase7IntegrityTests(TestCase):
    def _recorrencia(self):
        return DespesaRecorrente.objects.create(
            descricao='Energia 7A',
            categoria='CUSTO_FIXO_OFICINA',
            valor=Decimal('250.00'),
            forma_pagamento='BOLETO',
            dia_vencimento=10,
            data_inicio=date(2026, 10, 1),
        )

    def _raw_insert(self, *, recorrencia_id=None, competencia=None, descricao='raw'):
        table = connection.ops.quote_name(LancamentoFinanceiro._meta.db_table)
        raw = connection.connection
        raw.execute(
            f'''
            INSERT INTO {table}
                (tipo, categoria, descricao, valor, forma_pagamento,
                 data_vencimento, data_pagamento, status, projeto_id,
                 funcionario_id, recorrencia_id, competencia)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                'SAIDA', 'CUSTO_FIXO_OFICINA', descricao, '250.00', 'PIX',
                '2026-10-10', None, 'PENDENTE', None, None,
                recorrencia_id, competencia,
            ),
        )

    def test_raw_sql_proves_null_legacy_pair_unique_and_canonical_dates(self):
        recurrence = self._recorrencia()
        self._raw_insert(descricao='legacy-1')
        self._raw_insert(descricao='legacy-2')
        self.assertEqual(
            LancamentoFinanceiro.objects.filter(recorrencia__isnull=True).count(),
            2,
        )

        with self.assertRaises(sqlite3.IntegrityError):
            self._raw_insert(recorrencia_id=recurrence.pk, competencia=None)
        with self.assertRaises(sqlite3.IntegrityError):
            self._raw_insert(recorrencia_id=None, competencia='2026-10-01')

        self._raw_insert(recorrencia_id=recurrence.pk, competencia='2026-10-01')
        with self.assertRaises(sqlite3.IntegrityError):
            self._raw_insert(recorrencia_id=recurrence.pk, competencia='2026-10-01')

        self._raw_insert(
            recorrencia_id=recurrence.pk,
            competencia='2027-02-01',
            descricao='fevereiro',
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self._raw_insert(
                recorrencia_id=recurrence.pk,
                competencia='2027-02-02',
                descricao='dia-incorreto',
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self._raw_insert(
                recorrencia_id=recurrence.pk,
                competencia='0000-01-01',
                descricao='ano-invalido',
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self._raw_insert(
                recorrencia_id=recurrence.pk,
                competencia='2027/02/01',
                descricao='data-malformada',
            )

        raw = connection.connection
        integrity_check = raw.execute('PRAGMA integrity_check').fetchone()[0]
        foreign_key_check = raw.execute('PRAGMA foreign_key_check').fetchall()
        print(f'PRAGMA integrity_check={integrity_check!r}')
        print(f'PRAGMA foreign_key_check={foreign_key_check!r}')
        self.assertEqual(integrity_check, 'ok')
        self.assertEqual(foreign_key_check, [])


class LancamentoFinanceiroAdminTests(TestCase):
    def setUp(self):
        self.model_admin = LancamentoFinanceiroAdmin(
            LancamentoFinanceiro,
            admin.site,
        )
        self.request = RequestFactory().get('/admin/financeiro/lancamentofinanceiro/')
        self.request.user = get_user_model().objects.create_superuser(
            username='admin-7a',
            email='admin-7a@example.com',
            password='test-password',
        )
        self.recorrencia = DespesaRecorrente.objects.create(
            descricao='Admin 7A',
            categoria='CUSTO_FIXO_OFICINA',
            valor=Decimal('250.00'),
            forma_pagamento='PIX',
            dia_vencimento=10,
            data_inicio=date(2026, 10, 1),
        )
        self.row = LancamentoFinanceiro.objects.create(
            tipo='SAIDA',
            categoria='CUSTO_FIXO_OFICINA',
            descricao='Admin ledger',
            valor=Decimal('250.00'),
            forma_pagamento='PIX',
            data_vencimento=date(2026, 10, 10),
            status='PENDENTE',
            recorrencia=self.recorrencia,
            competencia=date(2026, 10, 1),
        )

    def test_admin_hides_identity_on_change_and_denies_delete_paths(self):
        readonly = self.model_admin.get_readonly_fields(self.request, self.row)
        self.assertIn('recorrencia', readonly)
        self.assertIn('competencia', readonly)
        self.assertFalse(self.model_admin.has_delete_permission(self.request, self.row))
        with self.assertRaises(ValidationError):
            self.model_admin.delete_model(self.request, self.row)
        with self.assertRaises(ValidationError):
            self.model_admin.delete_queryset(
                self.request,
                LancamentoFinanceiro.objects.filter(pk=self.row.pk),
            )

    def test_admin_rejects_identity_change_but_allows_legacy_delete(self):
        self.row.competencia = date(2026, 11, 1)
        with self.assertRaises(ValidationError):
            self.model_admin.save_model(self.request, self.row, form=None, change=True)

        legacy = LancamentoFinanceiro.objects.create(
            tipo='SAIDA',
            categoria='OUTROS',
            descricao='Admin legacy',
            valor=Decimal('10.00'),
            forma_pagamento='PIX',
            data_vencimento=date(2026, 10, 10),
            status='PENDENTE',
        )
        self.assertTrue(self.model_admin.has_delete_permission(self.request, legacy))
        self.model_admin.delete_queryset(
            self.request,
            LancamentoFinanceiro.objects.filter(pk=legacy.pk),
        )
        self.assertFalse(LancamentoFinanceiro.objects.filter(pk=legacy.pk).exists())

    def test_admin_delete_selected_action_uses_guarded_queryset_path(self):
        actions = self.model_admin.get_actions(self.request)
        self.assertIn('delete_selected', actions)


class Phase7MigrationTests(TransactionTestCase):
    MIGRATION_NAME = '0002_lancamentofinanceiro_competencia_despesarecorrente_and_more'

    def test_schema_advances_rolls_back_reapplies_and_preserves_legacy_nulls(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        table = connection.ops.quote_name(LancamentoFinanceiro._meta.db_table)
        try:
            executor.migrate([('financeiro', '0001_initial')])
            with connection.cursor() as cursor:
                cursor.execute(
                    f'''
                    INSERT INTO {table}
                        (tipo, categoria, descricao, valor, forma_pagamento,
                         data_vencimento, data_pagamento, status,
                         projeto_id, funcionario_id)
                    VALUES ('SAIDA', 'OUTROS', 'legado migration', '10.00', 'PIX',
                            '2026-10-10', NULL, 'PENDENTE', NULL, NULL)
                    '''
                )

            executor = MigrationExecutor(connection)
            executor.migrate([('financeiro', self.MIGRATION_NAME)])
            with connection.cursor() as cursor:
                cursor.execute(
                    f'SELECT recorrencia_id, competencia FROM {table}'
                )
                self.assertEqual(cursor.fetchall(), [(None, None)])
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='trigger' "
                    "AND name='financeiro_lanc_identity_guard'"
                )
                self.assertEqual(cursor.fetchone()[0], 'financeiro_lanc_identity_guard')

            executor = MigrationExecutor(connection)
            executor.migrate([('financeiro', '0001_initial')])
            executor = MigrationExecutor(connection)
            executor.migrate([('financeiro', self.MIGRATION_NAME)])
            with connection.cursor() as cursor:
                cursor.execute(f'PRAGMA table_info({table})')
                columns = {row[1] for row in cursor.fetchall()}
            self.assertTrue({'recorrencia_id', 'competencia'}.issubset(columns))
        finally:
            MigrationExecutor(connection).migrate(latest)
