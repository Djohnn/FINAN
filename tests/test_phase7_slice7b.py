from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.financeiro import services as financeiro_services
from apps.financeiro.models import DespesaRecorrente, LancamentoFinanceiro

SAO_PAULO = ZoneInfo('America/Sao_Paulo')
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


class MonthlyRecurringGeneratorTests(TestCase):
    def _service(self, name: str) -> Callable[..., Any]:
        service = getattr(financeiro_services, name, None)
        if service is None:
            self.fail(f'O service {name} ainda não existe.')
        return service

    def _generate(self, recorrencia: DespesaRecorrente, competencia: object):
        return self._service('gerar_lancamento_recorrente_competencia_service')(
            recorrencia.pk,
            competencia,
        )

    def _creation_data(self, **overrides):
        return {
            'descricao': 'Plano de internet',
            'categoria': 'CUSTO_FIXO_OFICINA',
            'valor': Decimal('89.90'),
            'forma_pagamento': 'BOLETO',
            'dia_vencimento': 10,
            'data_inicio': date(2026, 10, 1),
            **overrides,
        }

    def test_creates_pending_snapshot_for_explicit_competence(self):
        recorrencia = create_recorrencia()
        lancamento = self._generate(recorrencia, date(2026, 11, 1))

        self.assertTrue(lancamento.foi_criado)
        self.assertEqual(lancamento.recorrencia_id, recorrencia.pk)
        self.assertEqual(lancamento.competencia, date(2026, 11, 1))
        self.assertEqual(lancamento.tipo, 'SAIDA')
        self.assertIsNone(lancamento.projeto_id)
        self.assertIsNone(lancamento.funcionario_id)
        self.assertEqual(lancamento.status, 'PENDENTE')
        self.assertIsNone(lancamento.data_pagamento)
        self.assertEqual(lancamento.valor, Decimal('149.90'))
        self.assertEqual(lancamento.categoria, 'CUSTO_FIXO_OFICINA')
        self.assertEqual(lancamento.forma_pagamento, 'PIX')
        self.assertEqual(lancamento.descricao, 'Internet da oficina')
        self.assertEqual(lancamento.data_vencimento, date(2026, 11, 10))

    def test_retry_returns_same_primary_key_without_rewriting_row(self):
        recorrencia = create_recorrencia()
        first = self._generate(recorrencia, date(2026, 11, 1))
        original = LancamentoFinanceiro.objects.get(pk=first.pk)

        recorrencia.descricao = 'Descrição revisada'
        recorrencia.categoria = 'OUTROS'
        recorrencia.valor = Decimal('220.00')
        recorrencia.forma_pagamento = 'DINHEIRO'
        recorrencia.dia_vencimento = 31
        recorrencia.save()
        retry = self._generate(recorrencia, date(2026, 11, 1))
        retry.refresh_from_db()

        self.assertFalse(retry.foi_criado)
        self.assertEqual(retry.pk, first.pk)
        self.assertEqual(retry.descricao, original.descricao)
        self.assertEqual(retry.categoria, original.categoria)
        self.assertEqual(retry.valor, original.valor)
        self.assertEqual(retry.forma_pagamento, original.forma_pagamento)
        self.assertEqual(retry.data_vencimento, original.data_vencimento)
        self.assertEqual(LancamentoFinanceiro.objects.count(), 1)

    def test_paid_row_is_returned_unchanged_on_retry(self):
        recorrencia = create_recorrencia()
        row = self._generate(recorrencia, date(2026, 11, 1))
        row.status = 'PAGO'
        row.data_pagamento = date(2026, 11, 11)
        row.save(update_fields=['status', 'data_pagamento'])
        original = LancamentoFinanceiro.objects.get(pk=row.pk)

        recorrencia.valor = Decimal('400.00')
        recorrencia.save()
        retry = self._generate(recorrencia, date(2026, 11, 1))
        retry.refresh_from_db()

        self.assertFalse(retry.foi_criado)
        self.assertEqual(retry.pk, original.pk)
        self.assertEqual(retry.status, 'PAGO')
        self.assertEqual(retry.data_pagamento, date(2026, 11, 11))
        self.assertEqual(retry.valor, original.valor)

    def test_cancelled_row_is_not_regenerated(self):
        recorrencia = create_recorrencia()
        row = self._generate(recorrencia, date(2026, 11, 1))
        row.status = 'CANCELADO'
        row.save(update_fields=['status'])
        original = LancamentoFinanceiro.objects.get(pk=row.pk)

        recorrencia.valor = Decimal('400.00')
        recorrencia.dia_vencimento = 31
        recorrencia.save()

        retry = self._generate(recorrencia, date(2026, 11, 1))

        self.assertFalse(retry.foi_criado)
        self.assertEqual(retry.pk, original.pk)
        self.assertEqual(retry.status, 'CANCELADO')
        self.assertEqual(retry.valor, original.valor)
        self.assertEqual(retry.data_vencimento, original.data_vencimento)
        self.assertEqual(LancamentoFinanceiro.objects.count(), 1)

    def test_edited_recurrence_only_affects_future_competences(self):
        recorrencia = create_recorrencia()
        november = self._generate(recorrencia, date(2026, 11, 1))

        recorrencia.descricao = 'Energia revisada'
        recorrencia.categoria = 'OUTROS'
        recorrencia.valor = Decimal('310.25')
        recorrencia.forma_pagamento = 'PIX'
        recorrencia.dia_vencimento = 31
        recorrencia.save()
        november.refresh_from_db()
        december = self._generate(recorrencia, date(2026, 12, 1))

        self.assertEqual(november.descricao, 'Internet da oficina')
        self.assertEqual(november.valor, Decimal('149.90'))
        self.assertEqual(november.data_vencimento, date(2026, 11, 10))
        self.assertEqual(december.descricao, 'Energia revisada')
        self.assertEqual(december.categoria, 'OUTROS')
        self.assertEqual(december.valor, Decimal('310.25'))
        self.assertEqual(december.data_vencimento, date(2026, 12, 31))

    def test_clamps_days_29_30_and_31_to_month_end(self):
        cases = (
            (29, date(2027, 2, 1), date(2027, 2, 28)),
            (29, date(2028, 2, 1), date(2028, 2, 29)),
            (30, date(2027, 2, 1), date(2027, 2, 28)),
            (30, date(2028, 2, 1), date(2028, 2, 29)),
            (31, date(2027, 2, 1), date(2027, 2, 28)),
            (31, date(2028, 2, 1), date(2028, 2, 29)),
            (29, date(2027, 4, 1), date(2027, 4, 29)),
            (30, date(2027, 4, 1), date(2027, 4, 30)),
            (31, date(2027, 4, 1), date(2027, 4, 30)),
            (29, date(2027, 1, 1), date(2027, 1, 29)),
            (30, date(2027, 1, 1), date(2027, 1, 30)),
            (31, date(2027, 1, 1), date(2027, 1, 31)),
        )
        for due_day, competencia, expected_due in cases:
            with self.subTest(due_day=due_day, competencia=competencia):
                recorrencia = create_recorrencia(dia_vencimento=due_day)

                lancamento = self._generate(recorrencia, competencia)

                self.assertEqual(lancamento.data_vencimento, expected_due)

    def test_preserves_a_valid_due_day(self):
        recorrencia = create_recorrencia(dia_vencimento=17)

        lancamento = self._generate(recorrencia, date(2027, 4, 1))

        self.assertEqual(lancamento.data_vencimento, date(2027, 4, 17))

    def test_rejects_competence_that_is_not_first_day(self):
        recorrencia = create_recorrencia()
        for competencia in (
            date(2026, 11, 2),
            datetime(2026, 11, 1, 0, tzinfo=SAO_PAULO),
            '2026-11-01',
        ):
            with self.subTest(competencia=competencia), self.assertRaises(
                ValidationError
            ):
                self._generate(recorrencia, competencia)

    def test_explicit_generation_creates_only_requested_competence(self):
        recorrencia = create_recorrencia()

        self._generate(recorrencia, date(2026, 11, 1))

        self.assertEqual(
            list(
                LancamentoFinanceiro.objects.filter(recorrencia=recorrencia)
                .values_list('competencia', flat=True)
            ),
            [date(2026, 11, 1)],
        )

    def test_inactive_recurrence_is_not_generated(self):
        recorrencia = create_recorrencia(ativo=False)

        result = self._generate(recorrencia, date(2026, 11, 1))

        self.assertIsNone(result)
        self.assertFalse(
            LancamentoFinanceiro.objects.filter(recorrencia=recorrencia).exists()
        )

    def test_start_date_after_competence_does_not_generate(self):
        recorrencia = create_recorrencia(data_inicio=date(2026, 12, 1))

        result = self._generate(recorrencia, date(2026, 11, 1))

        self.assertIsNone(result)
        self.assertFalse(
            LancamentoFinanceiro.objects.filter(recorrencia=recorrencia).exists()
        )

    def test_due_date_before_start_date_in_same_month_skips_generation(self):
        recorrencia = create_recorrencia(
            dia_vencimento=5,
            data_inicio=date(2026, 11, 10),
        )

        result = self._generate(recorrencia, date(2026, 11, 1))

        self.assertIsNone(result)
        self.assertFalse(
            LancamentoFinanceiro.objects.filter(recorrencia=recorrencia).exists()
        )

    def test_next_competence_after_start_month_can_generate(self):
        recorrencia = create_recorrencia(
            dia_vencimento=10,
            data_inicio=date(2026, 11, 20),
        )

        initial = self._generate(recorrencia, date(2026, 11, 1))
        following = self._generate(recorrencia, date(2026, 12, 1))

        self.assertIsNone(initial)
        self.assertTrue(following.foi_criado)
        self.assertEqual(following.data_vencimento, date(2026, 12, 10))

    def test_start_date_day_equal_to_due_date_generates_initial_competence(self):
        recorrencia = create_recorrencia(
            dia_vencimento=10,
            data_inicio=date(2026, 11, 10),
        )

        result = self._generate(recorrencia, date(2026, 11, 1))

        self.assertTrue(result.foi_criado)
        self.assertEqual(result.data_vencimento, date(2026, 11, 10))

    def test_start_date_day_before_due_date_generates_initial_competence(self):
        recorrencia = create_recorrencia(
            dia_vencimento=20,
            data_inicio=date(2026, 11, 10),
        )

        result = self._generate(recorrencia, date(2026, 11, 1))

        self.assertTrue(result.foi_criado)
        self.assertEqual(result.data_vencimento, date(2026, 11, 20))

    def test_competence_after_end_month_does_not_generate(self):
        recorrencia = create_recorrencia(data_fim=date(2026, 10, 31))

        result = self._generate(recorrencia, date(2026, 11, 1))

        self.assertIsNone(result)
        self.assertFalse(
            LancamentoFinanceiro.objects.filter(recorrencia=recorrencia).exists()
        )

    def test_due_date_on_or_before_end_date_generates_final_competence(self):
        recorrencia = create_recorrencia(
            dia_vencimento=10,
            data_fim=date(2026, 11, 15),
        )

        result = self._generate(recorrencia, date(2026, 11, 1))

        self.assertTrue(result.foi_criado)
        self.assertEqual(result.data_vencimento, date(2026, 11, 10))

    def test_due_date_after_end_date_skips_final_competence(self):
        recorrencia = create_recorrencia(
            dia_vencimento=20,
            data_fim=date(2026, 11, 15),
        )

        result = self._generate(recorrencia, date(2026, 11, 1))

        self.assertIsNone(result)
        self.assertFalse(
            LancamentoFinanceiro.objects.filter(recorrencia=recorrencia).exists()
        )

    def test_competence_before_end_month_still_generates(self):
        recorrencia = create_recorrencia(
            dia_vencimento=20,
            data_fim=date(2026, 11, 15),
        )

        result = self._generate(recorrencia, date(2026, 10, 1))

        self.assertTrue(result.foi_criado)
        self.assertEqual(result.data_vencimento, date(2026, 10, 20))

    def test_generation_failure_leaves_no_partial_ledger_row(self):
        recorrencia = create_recorrencia()

        with (
            patch(
                'apps.financeiro.services.LancamentoFinanceiro.objects.get_or_create',
                side_effect=RuntimeError('falha simulada'),
            ),
            self.assertRaises(RuntimeError),
        ):
            self._generate(recorrencia, date(2026, 11, 1))

        self.assertFalse(
            LancamentoFinanceiro.objects.filter(recorrencia=recorrencia).exists()
        )

    def test_create_service_generates_current_month_immediately(self):
        create_service = self._service('criar_despesa_recorrente_service')
        created_at = datetime(2026, 11, 3, 12, tzinfo=SAO_PAULO)
        with (
            patch('apps.financeiro.services.timezone.localdate', return_value=date(2026, 11, 3)),
            patch('django.utils.timezone.now', return_value=created_at),
        ):
            recorrencia = create_service(**self._creation_data())

        lancamento = LancamentoFinanceiro.objects.get(recorrencia=recorrencia)
        self.assertEqual(lancamento.competencia, date(2026, 11, 1))
        self.assertEqual(lancamento.status, 'PENDENTE')
        retry = self._generate(recorrencia, date(2026, 11, 1))
        self.assertFalse(retry.foi_criado)
        self.assertEqual(LancamentoFinanceiro.objects.count(), 1)

    def test_create_service_rolls_back_recurrence_when_generation_fails(self):
        create_service = self._service('criar_despesa_recorrente_service')
        created_at = datetime(2026, 11, 3, 12, tzinfo=SAO_PAULO)
        with (
            patch('apps.financeiro.services.timezone.localdate', return_value=date(2026, 11, 3)),
            patch('django.utils.timezone.now', return_value=created_at),
            patch(
                'apps.financeiro.services.gerar_lancamento_recorrente_competencia_service',
                side_effect=ValidationError('falha simulada'),
            ),
            self.assertRaises(ValidationError),
        ):
            create_service(**self._creation_data())

        self.assertEqual(DespesaRecorrente.objects.count(), 0)
        self.assertEqual(LancamentoFinanceiro.objects.count(), 0)

    def test_create_service_validates_before_persisting(self):
        create_service = self._service('criar_despesa_recorrente_service')
        with self.assertRaises(ValidationError):
            create_service(**self._creation_data(valor=Decimal('1.234')))

        self.assertEqual(DespesaRecorrente.objects.count(), 0)

    def test_monthly_service_processes_only_active_current_competence(self):
        current = create_recorrencia(descricao='Ativa')
        inactive = create_recorrencia(descricao='Inativa', ativo=False)
        monthly_service = self._service(
            'gerar_despesas_recorrentes_mes_atual_service'
        )

        with patch(
            'apps.financeiro.services.timezone.localdate',
            return_value=date(2026, 11, 3),
        ):
            first_run = monthly_service()
            second_run = monthly_service()

        self.assertEqual(len(first_run), 1)
        self.assertTrue(first_run[0].foi_criado)
        self.assertEqual(first_run[0].recorrencia_id, current.pk)
        self.assertEqual(len(second_run), 1)
        self.assertFalse(second_run[0].foi_criado)
        self.assertEqual(second_run[0].pk, first_run[0].pk)
        self.assertFalse(
            LancamentoFinanceiro.objects.filter(recorrencia=inactive).exists()
        )
        self.assertEqual(LancamentoFinanceiro.objects.count(), 1)
        self.assertEqual(
            LancamentoFinanceiro.objects.get().competencia,
            date(2026, 11, 1),
        )

    def test_monthly_service_continues_after_ineligible_recurrence(self):
        ineligible = create_recorrencia(
            descricao='Ainda não iniciada',
            dia_vencimento=10,
            data_inicio=date(2026, 11, 20),
        )
        eligible = create_recorrencia(descricao='Elegível')
        monthly_service = self._service(
            'gerar_despesas_recorrentes_mes_atual_service'
        )

        with patch(
            'apps.financeiro.services.timezone.localdate',
            return_value=date(2026, 11, 3),
        ):
            first_run = monthly_service()
            second_run = monthly_service()

        self.assertEqual(len(first_run), 1)
        self.assertTrue(first_run[0].foi_criado)
        self.assertEqual(first_run[0].recorrencia_id, eligible.pk)
        self.assertEqual(first_run[0].competencia, date(2026, 11, 1))
        self.assertEqual(first_run[0].status, 'PENDENTE')
        self.assertFalse(
            LancamentoFinanceiro.objects.filter(recorrencia=ineligible).exists()
        )
        self.assertEqual(
            LancamentoFinanceiro.objects.filter(recorrencia=eligible).count(),
            1,
        )
        self.assertEqual(len(second_run), 1)
        self.assertFalse(second_run[0].foi_criado)
        self.assertEqual(second_run[0].pk, first_run[0].pk)
        self.assertEqual(LancamentoFinanceiro.objects.count(), 1)

    def test_monthly_service_rolls_back_when_second_generation_fails(self):
        first = create_recorrencia(descricao='Primeira')
        second = create_recorrencia(descricao='Segunda')
        preexisting_recurrencia = create_recorrencia(descricao='Preexistente')
        preexisting = self._generate(
            preexisting_recurrencia,
            date(2026, 11, 1),
        )
        preexisting.status = 'PAGO'
        preexisting.data_pagamento = date(2026, 11, 11)
        preexisting.save(update_fields=['status', 'data_pagamento'])
        preexisting_snapshot = (
            preexisting.pk,
            preexisting.status,
            preexisting.data_pagamento,
            preexisting.valor,
            preexisting.data_vencimento,
        )
        monthly_service = self._service(
            'gerar_despesas_recorrentes_mes_atual_service'
        )
        original_get_or_create = LancamentoFinanceiro.objects.get_or_create
        calls = 0

        def fail_on_second_generation(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError('falha na segunda recorrência')
            return original_get_or_create(*args, **kwargs)

        with (
            patch(
                'apps.financeiro.services.timezone.localdate',
                return_value=date(2026, 11, 3),
            ),
            patch(
                'apps.financeiro.services.LancamentoFinanceiro.objects.get_or_create',
                side_effect=fail_on_second_generation,
            ),
            self.assertRaises(RuntimeError),
        ):
            monthly_service()

        self.assertEqual(calls, 2)
        self.assertFalse(
            LancamentoFinanceiro.objects.filter(recorrencia=first).exists()
        )
        self.assertFalse(
            LancamentoFinanceiro.objects.filter(recorrencia=second).exists()
        )
        self.assertEqual(LancamentoFinanceiro.objects.count(), 1)
        preexisting.refresh_from_db()
        self.assertEqual(
            (
                preexisting.pk,
                preexisting.status,
                preexisting.data_pagamento,
                preexisting.valor,
                preexisting.data_vencimento,
            ),
            preexisting_snapshot,
        )

    def test_monthly_service_skips_future_start_and_expired_recurrence(self):
        future = create_recorrencia(data_inicio=date(2026, 12, 1))
        expired = create_recorrencia(
            descricao='Encerrada',
            data_fim=date(2026, 10, 31),
        )
        monthly_service = self._service(
            'gerar_despesas_recorrentes_mes_atual_service'
        )

        with patch(
            'apps.financeiro.services.timezone.localdate',
            return_value=date(2026, 11, 3),
        ):
            result = monthly_service()

        self.assertEqual(result, [])
        self.assertFalse(
            LancamentoFinanceiro.objects.filter(
                recorrencia__in=[future, expired]
            ).exists()
        )

    def test_monthly_service_skips_due_date_after_end_date(self):
        recorrencia = create_recorrencia(
            dia_vencimento=20,
            data_fim=date(2026, 11, 15),
        )
        monthly_service = self._service(
            'gerar_despesas_recorrentes_mes_atual_service'
        )

        with patch(
            'apps.financeiro.services.timezone.localdate',
            return_value=date(2026, 11, 3),
        ):
            result = monthly_service()

        self.assertEqual(result, [])
        self.assertFalse(
            LancamentoFinanceiro.objects.filter(recorrencia=recorrencia).exists()
        )

    def test_create_service_does_not_backfill_previous_competences(self):
        create_service = self._service('criar_despesa_recorrente_service')
        with (
            patch(
                'apps.financeiro.services.timezone.localdate',
                return_value=date(2026, 11, 20),
            ),
            patch('django.utils.timezone.now', return_value=FIXED_CREATED_AT),
        ):
            recorrencia = create_service(
                **self._creation_data(
                    dia_vencimento=10,
                    data_inicio=date(2026, 9, 20),
                )
            )

        self.assertEqual(
            list(
                LancamentoFinanceiro.objects.filter(recorrencia=recorrencia)
                .values_list('competencia', flat=True)
            ),
            [date(2026, 11, 1)],
        )
