from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.equipe.models import Funcionario
from apps.equipe.services import lancar_pagamento_funcionario_service
from apps.financeiro.models import LancamentoFinanceiro


class EmployeePaymentPeriodIntegrityTests(TestCase):
    def setUp(self):
        self.funcionario = Funcionario.objects.create(
            nome='Funcionário Integridade',
            funcao='Marceneiro',
            periodicidade='DIARIA',
            valor_base=Decimal('100.00'),
        )

    def test_zero_period_is_rejected_without_financial_mutation(self):
        initial_count = LancamentoFinanceiro.objects.count()

        with self.assertRaises(ValidationError):
            lancar_pagamento_funcionario_service(
                self.funcionario.pk,
                quantidade_periodos=0,
            )

        self.assertEqual(LancamentoFinanceiro.objects.count(), initial_count)

    def test_numeric_zero_representations_are_rejected_without_financial_mutation(self):
        for quantity in (0, 0.0, Decimal('0')):
            with self.subTest(quantity=quantity):
                initial_count = LancamentoFinanceiro.objects.count()

                with self.assertRaises(ValidationError):
                    lancar_pagamento_funcionario_service(
                        self.funcionario.pk,
                        quantidade_periodos=quantity,
                    )

                self.assertEqual(
                    LancamentoFinanceiro.objects.count(),
                    initial_count,
                )

    def test_negative_period_is_rejected_without_financial_mutation(self):
        initial_count = LancamentoFinanceiro.objects.count()

        with self.assertRaises(ValidationError):
            lancar_pagamento_funcionario_service(
                self.funcionario.pk,
                quantidade_periodos=Decimal('-1'),
            )

        self.assertEqual(LancamentoFinanceiro.objects.count(), initial_count)

    def test_positive_integer_period_calculates_employee_payment(self):
        lancamento = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            quantidade_periodos=2,
        )

        self.assertEqual(lancamento.valor, Decimal('200.00'))
        self.assertEqual(lancamento.tipo, 'SAIDA')
        self.assertEqual(lancamento.categoria, 'FUNCIONARIO')
        self.assertEqual(lancamento.funcionario, self.funcionario)

    def test_positive_fractional_period_remains_allowed(self):
        lancamento = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            quantidade_periodos=Decimal('0.5'),
        )

        self.assertEqual(lancamento.valor, Decimal('50.00'))

    def test_custom_value_path_remains_direct(self):
        lancamento = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            valor_customizado=Decimal('37.25'),
        )

        self.assertEqual(lancamento.valor, Decimal('37.25'))

    def test_omitted_period_uses_default_of_one(self):
        lancamento = lancar_pagamento_funcionario_service(self.funcionario.pk)

        self.assertEqual(lancamento.valor, Decimal('100.00'))

    def test_arbitrary_payment_method_is_rejected_without_financial_mutation(self):
        initial_count = LancamentoFinanceiro.objects.count()

        with self.assertRaises(ValidationError):
            lancar_pagamento_funcionario_service(
                self.funcionario.pk,
                forma_pagamento='TRANSFERENCIA',
            )

        self.assertEqual(LancamentoFinanceiro.objects.count(), initial_count)

    def test_empty_payment_method_is_rejected_without_financial_mutation(self):
        initial_count = LancamentoFinanceiro.objects.count()

        with self.assertRaises(ValidationError):
            lancar_pagamento_funcionario_service(
                self.funcionario.pk,
                forma_pagamento='',
            )

        self.assertEqual(LancamentoFinanceiro.objects.count(), initial_count)

    def test_none_payment_method_is_rejected_without_financial_mutation(self):
        initial_count = LancamentoFinanceiro.objects.count()

        with self.assertRaises(ValidationError):
            lancar_pagamento_funcionario_service(
                self.funcionario.pk,
                forma_pagamento=None,
            )

        self.assertEqual(LancamentoFinanceiro.objects.count(), initial_count)

    def test_all_declared_payment_methods_remain_accepted(self):
        for payment_method, _label in LancamentoFinanceiro.FORMA_PAGAMENTO_CHOICES:
            with self.subTest(payment_method=payment_method):
                lancamento = lancar_pagamento_funcionario_service(
                    self.funcionario.pk,
                    forma_pagamento=payment_method,
                )

                self.assertEqual(lancamento.forma_pagamento, payment_method)

    def test_invalid_payment_method_with_custom_value_has_no_financial_mutation(self):
        initial_count = LancamentoFinanceiro.objects.count()

        with self.assertRaises(ValidationError):
            lancar_pagamento_funcionario_service(
                self.funcionario.pk,
                valor_customizado=Decimal('37.25'),
                forma_pagamento='TRANSFERENCIA',
            )

        self.assertEqual(LancamentoFinanceiro.objects.count(), initial_count)

    def test_invalid_payment_method_for_pending_payment_has_no_financial_mutation(self):
        initial_count = LancamentoFinanceiro.objects.count()

        with self.assertRaises(ValidationError):
            lancar_pagamento_funcionario_service(
                self.funcionario.pk,
                forma_pagamento='TRANSFERENCIA',
                pago_hoje=False,
            )

        self.assertEqual(LancamentoFinanceiro.objects.count(), initial_count)

    def test_identical_default_retry_reuses_one_row_and_reports_creation(self):
        first = lancar_pagamento_funcionario_service(self.funcionario.pk)
        second = lancar_pagamento_funcionario_service(self.funcionario.pk)

        self.assertEqual(LancamentoFinanceiro.objects.count(), 1)
        self.assertEqual(second.pk, first.pk)
        self.assertTrue(first.foi_criado)
        self.assertFalse(second.foi_criado)

    def test_identical_retry_normalizes_observation_whitespace(self):
        first = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            observacao=' bônus ',
        )
        second = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            observacao='bônus',
        )

        self.assertEqual(LancamentoFinanceiro.objects.count(), 1)
        self.assertEqual(second.pk, first.pk)

    def test_identical_pending_retry_reuses_one_row(self):
        first = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            pago_hoje=False,
        )
        second = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            pago_hoje=False,
        )

        self.assertEqual(LancamentoFinanceiro.objects.count(), 1)
        self.assertEqual(second.pk, first.pk)

    def test_identical_custom_due_date_and_non_default_method_retry_reuses_pk(self):
        kwargs = {
            'valor_customizado': Decimal('37.25'),
            'forma_pagamento': 'DINHEIRO',
            'data_vencimento': date(2026, 1, 15),
        }
        first = lancar_pagamento_funcionario_service(self.funcionario.pk, **kwargs)
        second = lancar_pagamento_funcionario_service(self.funcionario.pk, **kwargs)

        self.assertEqual(LancamentoFinanceiro.objects.count(), 1)
        self.assertEqual(second.pk, first.pk)
        self.assertTrue(first.foi_criado)
        self.assertFalse(second.foi_criado)

    def test_different_observation_allows_second_payment(self):
        first = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            observacao='bônus produção',
        )
        second = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            observacao='adiantamento especial',
        )

        self.assertEqual(LancamentoFinanceiro.objects.count(), 2)
        self.assertNotEqual(second.pk, first.pk)
        self.assertTrue(first.foi_criado)
        self.assertTrue(second.foi_criado)

    def test_empty_observation_representations_are_one_identity(self):
        results = [
            lancar_pagamento_funcionario_service(self.funcionario.pk, observacao=None),
            lancar_pagamento_funcionario_service(self.funcionario.pk, observacao=''),
            lancar_pagamento_funcionario_service(self.funcionario.pk, observacao=' '),
            lancar_pagamento_funcionario_service(self.funcionario.pk, observacao='   '),
        ]

        self.assertEqual(LancamentoFinanceiro.objects.count(), 1)
        self.assertEqual({result.pk for result in results}, {results[0].pk})
        self.assertTrue(results[0].foi_criado)
        self.assertTrue(all(not result.foi_criado for result in results[1:]))

    def test_internal_observation_whitespace_remains_distinct(self):
        first = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            observacao='bônus especial',
        )
        second = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            observacao='bônus  especial',
        )

        self.assertEqual(LancamentoFinanceiro.objects.count(), 2)
        self.assertNotEqual(second.pk, first.pk)

    def test_period_quantity_is_excluded_from_identity(self):
        first = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            quantidade_periodos=1,
        )
        second = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            quantidade_periodos=2,
            valor_customizado=Decimal('100.00'),
        )

        self.assertEqual(LancamentoFinanceiro.objects.count(), 1)
        self.assertEqual(second.pk, first.pk)
        self.assertFalse(second.foi_criado)

    def test_cancelled_payment_does_not_block_new_payment(self):
        first = lancar_pagamento_funcionario_service(self.funcionario.pk)
        first.status = 'CANCELADO'
        first.save()

        second = lancar_pagamento_funcionario_service(self.funcionario.pk)

        self.assertEqual(LancamentoFinanceiro.objects.count(), 2)
        self.assertNotEqual(second.pk, first.pk)
        self.assertEqual(first.__class__.objects.get(pk=first.pk).status, 'CANCELADO')
        self.assertEqual(second.status, 'PAGO')
        self.assertTrue(second.foi_criado)

    def test_status_is_part_of_identity(self):
        paid = lancar_pagamento_funcionario_service(self.funcionario.pk, pago_hoje=True)
        pending = lancar_pagamento_funcionario_service(self.funcionario.pk, pago_hoje=False)
        paid_retry = lancar_pagamento_funcionario_service(self.funcionario.pk, pago_hoje=True)
        pending_retry = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            pago_hoje=False,
        )

        self.assertEqual(LancamentoFinanceiro.objects.count(), 2)
        self.assertNotEqual(paid.pk, pending.pk)
        self.assertEqual(paid_retry.pk, paid.pk)
        self.assertEqual(pending_retry.pk, pending.pk)

    def test_due_date_is_part_of_identity(self):
        first = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            data_vencimento=date(2026, 1, 15),
        )
        second = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            data_vencimento=date(2026, 1, 16),
        )

        self.assertEqual(LancamentoFinanceiro.objects.count(), 2)
        self.assertNotEqual(second.pk, first.pk)

    def test_payment_method_is_part_of_identity(self):
        first = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            forma_pagamento='PIX',
        )
        second = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            forma_pagamento='DINHEIRO',
        )

        self.assertEqual(LancamentoFinanceiro.objects.count(), 2)
        self.assertNotEqual(second.pk, first.pk)

    def test_value_is_part_of_identity(self):
        first = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            valor_customizado=Decimal('100.00'),
        )
        second = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            valor_customizado=Decimal('101.00'),
        )

        self.assertEqual(LancamentoFinanceiro.objects.count(), 2)
        self.assertNotEqual(second.pk, first.pk)

    def test_employee_is_part_of_identity(self):
        other_employee = Funcionario.objects.create(
            nome='Outro Funcionário',
            funcao='Marceneiro',
            periodicidade='DIARIA',
            valor_base=Decimal('100.00'),
        )
        first = lancar_pagamento_funcionario_service(self.funcionario.pk)
        second = lancar_pagamento_funcionario_service(other_employee.pk)

        self.assertEqual(LancamentoFinanceiro.objects.count(), 2)
        self.assertNotEqual(second.pk, first.pk)
        self.assertEqual(first.funcionario_id, self.funcionario.pk)
        self.assertEqual(second.funcionario_id, other_employee.pk)

    def test_new_description_uses_normalized_observation_once(self):
        payment = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            quantidade_periodos=2,
            observacao=' bônus ',
        )

        self.assertEqual(
            payment.descricao,
            'Pagamento equipe - Funcionário Integridade (Diária) '
            '[2 Diária(s)] - bônus',
        )

        whitespace_only = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            valor_customizado=Decimal('101.00'),
            observacao='   ',
        )
        self.assertFalse(whitespace_only.descricao.endswith(' - '))

    def test_retry_preserves_persisted_fields_and_description(self):
        first = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            observacao=' bônus ',
        )
        before = LancamentoFinanceiro.objects.values().get(pk=first.pk)

        second = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            quantidade_periodos=2,
            valor_customizado=Decimal('100.00'),
            observacao='bônus',
        )
        after = LancamentoFinanceiro.objects.values().get(pk=first.pk)

        self.assertEqual(second.pk, first.pk)
        self.assertFalse(second.foi_criado)
        self.assertEqual(after, before)

    def test_manual_non_service_description_does_not_match(self):
        manual = LancamentoFinanceiro.objects.create(
            tipo='SAIDA',
            categoria='FUNCIONARIO',
            funcionario=self.funcionario,
            descricao='Pagamento manual',
            valor=Decimal('100.00'),
            forma_pagamento='PIX',
            data_vencimento=date.today(),
            data_pagamento=date.today(),
            status='PAGO',
        )

        created = lancar_pagamento_funcionario_service(self.funcionario.pk)

        self.assertEqual(LancamentoFinanceiro.objects.count(), 2)
        self.assertNotEqual(created.pk, manual.pk)
        self.assertTrue(created.foi_criado)
