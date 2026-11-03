import sqlite3
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.models.deletion import ProtectedError
from django.test import Client, RequestFactory, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from apps.clientes_agenda.models import Cliente
from apps.equipe.models import Funcionario
from apps.financeiro.admin import LancamentoFinanceiroAdmin
from apps.financeiro.models import DespesaRecorrente, LancamentoFinanceiro
from apps.kanban_projetos.models import ProjetoKanban

SAO_PAULO = ZoneInfo('America/Sao_Paulo')
UTC = ZoneInfo('UTC')
FIXED_CREATED_AT = datetime(2026, 10, 15, 12, tzinfo=SAO_PAULO)


def create_recorrencia(**overrides):
    created_at = overrides.pop('_created_at', FIXED_CREATED_AT)
    data = {
        'descricao': 'Internet da oficina',
        'categoria': 'CUSTO_FIXO_OFICINA',
        'valor': Decimal('149.90'),
        'forma_pagamento': 'PIX',
        'dia_vencimento': 10,
        'data_inicio': date(2026, 10, 1),
        **overrides,
    }
    with patch('django.utils.timezone.now', return_value=created_at):
        return DespesaRecorrente.objects.create(**data)

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
        self.assertIn(
            'financeiro_lanc_recorrencia_invariants',
            {constraint.name for constraint in LancamentoFinanceiro._meta.constraints},
        )

        recorrencia = create_recorrencia()
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
            1.23,
            True,
            False,
            Decimal(0),
            Decimal('-0.01'),
            Decimal('1.234'),
            Decimal('NaN'),
            Decimal('Infinity'),
            Decimal('100000000.00'),
        ):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                DespesaRecorrente.objects.create(**self._kwargs(valor=value))

    def test_accepts_decimal_and_valid_decimal_string_money(self):
        decimal_value = create_recorrencia(valor=Decimal('199.90'))
        string_value = create_recorrencia(
            descricao='Telefone da oficina',
            valor='89.90',
        )
        self.assertEqual(decimal_value.valor, Decimal('199.90'))
        self.assertEqual(string_value.valor, Decimal('89.90'))

    def test_legacy_ledger_float_path_remains_compatible(self):
        legacy = LancamentoFinanceiro.objects.create(
            tipo='SAIDA',
            categoria='OUTROS',
            descricao='Legado float 7A',
            valor=1.23,
            forma_pagamento='PIX',
            data_vencimento=date(2026, 10, 10),
            status='PENDENTE',
        )
        self.assertEqual(legacy.valor, Decimal('1.23'))

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
        recorrencia = create_recorrencia(**self._kwargs())
        criado_em = recorrencia.criado_em
        recorrencia.criado_em = criado_em - timedelta(days=1)

        with self.assertRaises(ValidationError):
            recorrencia.save()

        recorrencia.refresh_from_db()
        self.assertEqual(recorrencia.criado_em, criado_em)
        self.assertEqual(
            DespesaRecorrente.objects.filter(pk=recorrencia.pk).update(
                criado_em=criado_em,
            ),
            1,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            DespesaRecorrente.objects.filter(pk=recorrencia.pk).update(
                criado_em=criado_em - timedelta(days=1),
            )
        recorrencia.refresh_from_db()
        self.assertEqual(recorrencia.criado_em, criado_em)

        raw = connection.connection
        table = connection.ops.quote_name(DespesaRecorrente._meta.db_table)
        with self.assertRaises(sqlite3.IntegrityError):
            raw.execute(
                f'UPDATE {table} SET criado_em = ? WHERE id = ?',
                ('2026-10-14 15:00:00', recorrencia.pk),
            )
        self.assertEqual(
            raw.execute(
                f'SELECT criado_em FROM {table} WHERE id = ?',
                (recorrencia.pk,),
            ).fetchone()[0],
            criado_em.astimezone(UTC).replace(tzinfo=None),
        )


class LedgerRecurrenceModelTests(TestCase):
    def setUp(self):
        self.recorrencia = create_recorrencia()

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

    def test_recurring_origin_has_approved_initial_invariants(self):
        cliente = Cliente.objects.create(nome='Cliente origem 7A', whatsapp='11911111111')
        projeto = ProjetoKanban.objects.create(
            cliente=cliente,
            titulo_servico='Projeto origem 7A',
            etapa='1_CONTATO',
        )
        funcionario = Funcionario.objects.create(
            nome='Funcionário origem 7A',
            funcao='Montador',
            periodicidade='MENSAL',
            valor_base=Decimal('100.00'),
        )
        invalid_origins = (
            {'tipo': 'ENTRADA'},
            {'status': 'PAGO'},
            {'projeto': projeto},
            {'funcionario': funcionario},
            {'data_pagamento': date(2026, 10, 10)},
        )
        for overrides in invalid_origins:
            with self.subTest(overrides=overrides), self.assertRaises(ValidationError):
                LancamentoFinanceiro.objects.create(
                    **self._kwargs(
                        recorrencia=self.recorrencia,
                        competencia=date(2026, 10, 1),
                        **overrides,
                    )
                )

        row = LancamentoFinanceiro.objects.create(
            **self._kwargs(
                recorrencia=self.recorrencia,
                competencia=date(2026, 10, 1),
            )
        )
        self.assertEqual(row.tipo, 'SAIDA')
        self.assertEqual(row.status, 'PENDENTE')
        self.assertIsNone(row.projeto_id)
        self.assertIsNone(row.funcionario_id)
        self.assertIsNone(row.data_pagamento)

    def test_recurring_invariants_apply_to_existing_model_updates(self):
        cliente = Cliente.objects.create(nome='Cliente update 7A', whatsapp='11922222222')
        projeto = ProjetoKanban.objects.create(
            cliente=cliente,
            titulo_servico='Projeto update 7A',
            etapa='1_CONTATO',
        )
        funcionario = Funcionario.objects.create(
            nome='Funcionário update 7A',
            funcao='Montador',
            periodicidade='MENSAL',
            valor_base=Decimal('100.00'),
        )
        row = LancamentoFinanceiro.objects.create(
            **self._kwargs(
                competencia=date(2026, 10, 1),
                recorrencia=self.recorrencia,
            )
        )
        for field_name, value in (
            ('tipo', 'ENTRADA'),
            ('projeto', projeto),
            ('funcionario', funcionario),
        ):
            with self.subTest(field_name=field_name), self.assertRaises(ValidationError):
                setattr(row, field_name, value)
                row.save()
            row.refresh_from_db()

    def test_recurring_invariants_reject_queryset_updates(self):
        cliente = Cliente.objects.create(nome='Cliente queryset 7A', whatsapp='11933333333')
        projeto = ProjetoKanban.objects.create(
            cliente=cliente,
            titulo_servico='Projeto queryset 7A',
            etapa='1_CONTATO',
        )
        funcionario = Funcionario.objects.create(
            nome='Funcionário queryset 7A',
            funcao='Montador',
            periodicidade='MENSAL',
            valor_base=Decimal('100.00'),
        )
        row = LancamentoFinanceiro.objects.create(
            **self._kwargs(
                competencia=date(2026, 10, 1),
                recorrencia=self.recorrencia,
            )
        )
        updates = (
            {'tipo': 'ENTRADA'},
            {'projeto': projeto},
            {'funcionario': funcionario},
        )
        for values in updates:
            with (
                self.subTest(values=values),
                self.assertRaises(IntegrityError),
                transaction.atomic(),
            ):
                LancamentoFinanceiro.objects.filter(pk=row.pk).update(**values)
            row.refresh_from_db()

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
        cutoff = timezone.localtime(
            self.recorrencia.criado_em,
            SAO_PAULO,
        ).date().replace(day=1)
        previous_month_cutoff = (cutoff - timedelta(days=1)).replace(day=1)
        with self.assertRaises(ValidationError):
            LancamentoFinanceiro.objects.create(
                **self._kwargs(
                    competencia=previous_month_cutoff,
                    recorrencia=self.recorrencia,
                )
            )
        same_month = LancamentoFinanceiro.objects.create(
            **self._kwargs(
                descricao='Internet mês de cadastro',
                competencia=cutoff,
                recorrencia=self.recorrencia,
            )
        )
        forgotten = LancamentoFinanceiro.objects.create(
            **self._kwargs(
                descricao='Internet competência esquecida',
                competencia=date(2027, 3, 1),
                data_vencimento=date(2027, 3, 10),
                recorrencia=self.recorrencia,
            )
        )
        self.assertEqual(same_month.competencia, cutoff)
        self.assertEqual(forgotten.competencia, date(2027, 3, 1))

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
                competencia=date(2026, 10, 1),
                recorrencia=self.recorrencia,
            )
        )

        row.status = 'PAGO'
        row.data_pagamento = date(2026, 10, 10)
        row.forma_pagamento = 'BOLETO'
        row.save(update_fields=['status', 'data_pagamento', 'forma_pagamento'])
        row.refresh_from_db()
        self.assertEqual(row.status, 'PAGO')
        self.assertEqual(row.data_pagamento, date(2026, 10, 10))
        self.assertEqual(row.forma_pagamento, 'BOLETO')

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

        legacy = LancamentoFinanceiro.objects.create(
            **self._kwargs(
                descricao='Lançamento legado com vínculos removíveis',
                projeto=projeto,
                funcionario=funcionario,
            )
        )
        projeto.delete()
        funcionario.delete()
        legacy.refresh_from_db()
        self.assertIsNone(legacy.projeto_id)
        self.assertIsNone(legacy.funcionario_id)

    def test_model_and_queryset_delete_cannot_remove_recurring_ledger(self):
        row = LancamentoFinanceiro.objects.create(
            **self._kwargs(
                competencia=date(2026, 10, 1),
                recorrencia=self.recorrencia,
            )
        )
        row.status = 'CANCELADO'
        row.save(update_fields=['status'])
        with self.assertRaises(ValidationError):
            row.delete()
        with self.assertRaises(IntegrityError), transaction.atomic():
            LancamentoFinanceiro.objects.filter(pk=row.pk).delete()
        self.assertTrue(LancamentoFinanceiro.objects.filter(pk=row.pk).exists())

        with self.assertRaises(IntegrityError), transaction.atomic():
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


class RecurrenceCutoffTimezoneTests(TestCase):
    def _ledger_kwargs(self, **overrides):
        return {
            'tipo': 'SAIDA',
            'categoria': 'CUSTO_FIXO_OFICINA',
            'descricao': 'Competência temporal 7A',
            'valor': Decimal('149.90'),
            'forma_pagamento': 'PIX',
            'data_vencimento': date(2027, 1, 10),
            'status': 'PENDENTE',
            **overrides,
        }

    def test_cutoff_uses_sao_paulo_when_utc_crosses_month_boundary(self):
        before_local_midnight = datetime(2027, 1, 1, 2, 59, tzinfo=UTC)
        after_local_midnight = datetime(2027, 1, 1, 3, 0, tzinfo=UTC)

        with timezone.override('UTC'):
            before_local = create_recorrencia(
                descricao='Cadastro ainda em dezembro local',
                _created_at=before_local_midnight,
            )
            after_local = create_recorrencia(
                descricao='Cadastro já em janeiro local',
                _created_at=after_local_midnight,
            )

        valid_before = LancamentoFinanceiro.objects.create(
            **self._ledger_kwargs(
                descricao='Dezembro local válido',
                competencia=date(2026, 12, 1),
                recorrencia=before_local,
            )
        )
        self.assertEqual(valid_before.competencia, date(2026, 12, 1))
        with self.assertRaises(ValidationError):
            LancamentoFinanceiro.objects.create(
                **self._ledger_kwargs(
                    descricao='Novembro local inválido',
                    competencia=date(2026, 11, 1),
                    recorrencia=before_local,
                )
            )

        valid_after = LancamentoFinanceiro.objects.create(
            **self._ledger_kwargs(
                descricao='Janeiro local válido',
                competencia=date(2027, 1, 1),
                recorrencia=after_local,
            )
        )
        self.assertEqual(valid_after.competencia, date(2027, 1, 1))
        with self.assertRaises(ValidationError):
            LancamentoFinanceiro.objects.create(
                **self._ledger_kwargs(
                    descricao='Dezembro local inválido',
                    competencia=date(2026, 12, 1),
                    recorrencia=after_local,
                )
            )


class RawSQLitePhase7IntegrityTests(TestCase):
    def _recorrencia(self):
        return create_recorrencia(
            descricao='Energia 7A',
            valor=Decimal('250.00'),
            forma_pagamento='BOLETO',
        )

    def _raw_insert(
        self,
        *,
        recorrencia_id=None,
        competencia=None,
        descricao='raw',
        tipo='SAIDA',
        status='PENDENTE',
        data_pagamento=None,
        projeto_id=None,
        funcionario_id=None,
    ):
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
                tipo, 'CUSTO_FIXO_OFICINA', descricao, '250.00', 'PIX',
                '2026-10-10', data_pagamento, status, projeto_id, funcionario_id,
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
        with self.assertRaises(sqlite3.IntegrityError):
            self._raw_insert(
                recorrencia_id=recurrence.pk,
                competencia='2026-10-01',
                tipo='ENTRADA',
                descricao='origem-invalida',
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self._raw_insert(
                recorrencia_id=recurrence.pk,
                competencia='2026-10-01',
                status='PAGO',
                descricao='status-invalido',
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self._raw_insert(
                recorrencia_id=recurrence.pk,
                competencia='2026-10-01',
                data_pagamento='2026-10-10',
                descricao='quitacao-invalida',
            )

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
        cliente = Cliente.objects.create(nome='Cliente SQL 7A', whatsapp='11944444444')
        projeto = ProjetoKanban.objects.create(
            cliente=cliente,
            titulo_servico='Projeto SQL 7A',
            etapa='1_CONTATO',
        )
        funcionario = Funcionario.objects.create(
            nome='Funcionário SQL 7A',
            funcao='Montador',
            periodicidade='MENSAL',
            valor_base=Decimal('100.00'),
        )
        linked_id = raw.execute(
            f'SELECT id FROM {connection.ops.quote_name(LancamentoFinanceiro._meta.db_table)} '
            'WHERE recorrencia_id = ? AND competencia = ?',
            (recurrence.pk, '2026-10-01'),
        ).fetchone()[0]
        with self.assertRaises(sqlite3.IntegrityError):
            raw.execute(
                f'UPDATE {connection.ops.quote_name(LancamentoFinanceiro._meta.db_table)} '
                'SET tipo = ? WHERE id = ?',
                ('ENTRADA', linked_id),
            )
        with self.assertRaises(sqlite3.IntegrityError):
            raw.execute(
                f'UPDATE {connection.ops.quote_name(LancamentoFinanceiro._meta.db_table)} '
                'SET projeto_id = ? WHERE id = ?',
                (projeto.pk, linked_id),
            )
        with self.assertRaises(sqlite3.IntegrityError):
            raw.execute(
                f'UPDATE {connection.ops.quote_name(LancamentoFinanceiro._meta.db_table)} '
                'SET funcionario_id = ? WHERE id = ?',
                (funcionario.pk, linked_id),
            )
        with self.assertRaises(sqlite3.IntegrityError):
            raw.execute(
                f'DELETE FROM {connection.ops.quote_name(LancamentoFinanceiro._meta.db_table)} '
                'WHERE id = ?',
                (linked_id,),
            )
        legacy_id = raw.execute(
            f'SELECT id FROM {connection.ops.quote_name(LancamentoFinanceiro._meta.db_table)} '
            "WHERE descricao = 'legacy-1'",
        ).fetchone()[0]
        raw.execute(
            f'DELETE FROM {connection.ops.quote_name(LancamentoFinanceiro._meta.db_table)} '
            'WHERE id = ?',
            (legacy_id,),
        )
        self.assertFalse(
            LancamentoFinanceiro.objects.filter(pk=legacy_id).exists()
        )
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
        self.client = Client()
        self.request = RequestFactory().get('/admin/financeiro/lancamentofinanceiro/')
        self.request.user = get_user_model().objects.create_superuser(
            username='admin-7a',
            email='admin-7a@example.com',
            password='test-password',
        )
        self.recorrencia = create_recorrencia(descricao='Admin 7A', valor=Decimal('250.00'))
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
        self.client.force_login(self.request.user)

    def test_admin_hides_identity_on_change_and_denies_delete_paths(self):
        readonly = self.model_admin.get_readonly_fields(self.request, self.row)
        self.assertIn('recorrencia', readonly)
        self.assertIn('competencia', readonly)
        self.assertIn('tipo', readonly)
        self.assertIn('projeto', readonly)
        self.assertIn('funcionario', readonly)
        self.assertFalse(self.model_admin.has_delete_permission(self.request, self.row))
        with self.assertRaises(ValidationError):
            self.model_admin.delete_model(self.request, self.row)
        with self.assertRaises(ValidationError):
            self.model_admin.delete_queryset(
                self.request,
                LancamentoFinanceiro.objects.filter(pk=self.row.pk),
            )

    def test_admin_rejects_recurring_structural_changes_but_allows_status(self):
        for field_name, value in (
            ('tipo', 'ENTRADA'),
            ('projeto', None),
            ('funcionario', None),
        ):
            if field_name == 'projeto':
                value = ProjetoKanban.objects.create(
                    cliente=Cliente.objects.create(
                        nome='Cliente admin guard 7A',
                        whatsapp='11955555555',
                    ),
                    titulo_servico='Projeto admin guard 7A',
                    etapa='1_CONTATO',
                )
            if field_name == 'funcionario':
                value = Funcionario.objects.create(
                    nome='Funcionário admin guard 7A',
                    funcao='Montador',
                    periodicidade='MENSAL',
                    valor_base=Decimal('100.00'),
                )
            setattr(self.row, field_name, value)
            with self.subTest(field_name=field_name), self.assertRaises(ValidationError):
                self.model_admin.save_model(self.request, self.row, form=None, change=True)
            self.row.refresh_from_db()

        self.row.status = 'PAGO'
        self.model_admin.save_model(self.request, self.row, form=None, change=True)
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, 'PAGO')

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

    def test_admin_hides_recurring_crud_and_add_linkage(self):
        add_form = self.model_admin.get_form(self.request)()
        self.assertNotIn('recorrencia', add_form.fields)
        self.assertNotIn('competencia', add_form.fields)
        self.assertNotIn(DespesaRecorrente, admin.site._registry)

        new_row = LancamentoFinanceiro(
            tipo='SAIDA',
            categoria='CUSTO_FIXO_OFICINA',
            descricao='Admin origem recorrente',
            valor=Decimal('250.00'),
            forma_pagamento='PIX',
            data_vencimento=date(2026, 10, 10),
            status='PENDENTE',
            recorrencia=self.recorrencia,
            competencia=date(2026, 10, 1),
        )
        with self.assertRaises(ValidationError):
            self.model_admin.save_model(self.request, new_row, form=None, change=False)

    def test_admin_http_individual_delete_is_forbidden_without_500(self):
        url = reverse(
            'admin:financeiro_lancamentofinanceiro_delete',
            kwargs={'object_id': self.row.pk},
        )
        response = self.client.post(url, {'post': 'yes'})
        self.assertEqual(response.status_code, 403)
        self.assertTrue(
            LancamentoFinanceiro.objects.filter(pk=self.row.pk).exists()
        )

    def test_admin_http_batch_delete_refuses_recurring_row_with_message(self):
        url = reverse('admin:financeiro_lancamentofinanceiro_changelist')
        selection = {
            'action': 'delete_selected',
            '_selected_action': str(self.row.pk),
            'index': '0',
        }
        response = self.client.post(
            url,
            {**selection, 'post': 'yes'},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'seleção contém lançamento recorrente')
        self.assertTrue(
            LancamentoFinanceiro.objects.filter(pk=self.row.pk).exists()
        )

    def test_admin_http_legacy_delete_remains_allowed(self):
        legacy = LancamentoFinanceiro.objects.create(
            tipo='SAIDA',
            categoria='OUTROS',
            descricao='Admin legacy HTTP',
            valor=Decimal('10.00'),
            forma_pagamento='PIX',
            data_vencimento=date(2026, 10, 10),
            status='PENDENTE',
        )
        url = reverse(
            'admin:financeiro_lancamentofinanceiro_delete',
            kwargs={'object_id': legacy.pk},
        )
        response = self.client.post(url, {'post': 'yes'})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(LancamentoFinanceiro.objects.filter(pk=legacy.pk).exists())

    def test_admin_delete_selected_action_uses_guarded_queryset_path(self):
        actions = self.model_admin.get_actions(self.request)
        self.assertIn('delete_selected', actions)


class Phase7MigrationTests(TransactionTestCase):
    MIGRATION_BASE = '0002_lancamentofinanceiro_competencia_despesarecorrente_and_more'
    MIGRATION_NAME = '0003_lancamentofinanceiro_recorrencia_invariants'

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
            executor.migrate([('financeiro', self.MIGRATION_BASE)])
            executor = MigrationExecutor(connection)
            executor.migrate([('financeiro', self.MIGRATION_NAME)])
            with connection.cursor() as cursor:
                cursor.execute(
                    f'SELECT recorrencia_id, competencia FROM {table}'
                )
                self.assertEqual(cursor.fetchall(), [(None, None)])
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='trigger'"
                )
                trigger_names = {row[0] for row in cursor.fetchall()}
                self.assertTrue(
                    {
                        'financeiro_despesa_rec_criado_em_guard',
                        'financeiro_lanc_recorrente_origin_guard',
                        'financeiro_lanc_competencia_insert_guard',
                        'financeiro_lanc_competencia_update_guard',
                        'financeiro_lanc_identity_guard',
                        'financeiro_lanc_recorrente_delete_guard',
                    }.issubset(trigger_names)
                )
                cursor.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                    (LancamentoFinanceiro._meta.db_table,),
                )
                self.assertEqual(
                    cursor.fetchone()[0].count('financeiro_lanc_recorrencia_invariants'),
                    1,
                )

            executor = MigrationExecutor(connection)
            executor.migrate([('financeiro', self.MIGRATION_BASE)])
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='trigger'"
                )
                rolled_back_trigger_names = {row[0] for row in cursor.fetchall()}
            self.assertTrue(
                {
                    'financeiro_despesa_rec_criado_em_guard',
                    'financeiro_lanc_recorrente_origin_guard',
                    'financeiro_lanc_competencia_insert_guard',
                    'financeiro_lanc_competencia_update_guard',
                    'financeiro_lanc_identity_guard',
                    'financeiro_lanc_recorrente_delete_guard',
                }.issubset(rolled_back_trigger_names)
            )
            executor = MigrationExecutor(connection)
            executor.migrate([('financeiro', self.MIGRATION_NAME)])
            with connection.cursor() as cursor:
                cursor.execute(f'PRAGMA table_info({table})')
                columns = {row[1] for row in cursor.fetchall()}
            self.assertTrue({'recorrencia_id', 'competencia'}.issubset(columns))
        finally:
            MigrationExecutor(connection).migrate(latest)
