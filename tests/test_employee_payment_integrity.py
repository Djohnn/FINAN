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
