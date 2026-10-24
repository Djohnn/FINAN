from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.clientes_agenda.models import Cliente
from apps.core_sistema.models import EventoSistema
from apps.equipe.models import Funcionario
from apps.equipe.services import lancar_pagamento_funcionario_service
from apps.financeiro.models import LancamentoFinanceiro
from apps.kanban_projetos.models import ProjetoKanban


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


class EmployeePaymentProjectAttributionTests(TestCase):
    def setUp(self):
        self.funcionario = Funcionario.objects.create(
            nome='Funcionário Projeto',
            funcao='Marceneiro',
            periodicidade='DIARIA',
            valor_base=Decimal('100.00'),
        )
        self.cliente = Cliente.objects.create(
            nome='Cliente Projeto',
            whatsapp='',
        )
        self.project_a = self._create_project('1_CONTATO', 'Projeto A')
        self.project_b = self._create_project('4_PRODUCAO', 'Projeto B')

    def _create_project(self, etapa, titulo):
        fields = {
            'cliente': self.cliente,
            'titulo_servico': titulo,
            'etapa': etapa,
        }
        if etapa == '2_ORCAMENTO':
            fields['data_limite_orcamento'] = timezone.localdate()
        return ProjetoKanban.objects.create(**fields)

    def test_omitted_project_creates_none_without_text_inference(self):
        payment = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            observacao='Projeto A / Cliente Projeto / ProjetoKanban',
        )

        self.assertIsNone(payment.projeto_id)

    def test_supplied_project_persists_exact_fk(self):
        payment = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            projeto_id=self.project_a.pk,
        )

        self.assertEqual(payment.projeto_id, self.project_a.pk)

    def test_all_kanban_lifecycle_stages_are_accepted(self):
        stages = (
            '1_CONTATO',
            '2_ORCAMENTO',
            '3_APROVADO',
            '4_PRODUCAO',
            '5_ENTREGA',
            '6_FINALIZADO',
            '9_ARQUIVADO',
        )
        projects = [
            self._create_project(stage, f'Projeto {stage}')
            for stage in stages
        ]

        payments = [
            lancar_pagamento_funcionario_service(
                self.funcionario.pk,
                projeto_id=project.pk,
                observacao=stage,
            )
            for stage, project in zip(stages, projects)
        ]

        self.assertEqual(
            {payment.projeto_id for payment in payments},
            {project.pk for project in projects},
        )

    def test_same_project_identity_reuses_row_and_preserves_creation_marker(self):
        first = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            projeto_id=self.project_a.pk,
        )
        retry = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            projeto_id=self.project_a.pk,
        )

        self.assertEqual(retry.pk, first.pk)
        self.assertTrue(first.foi_criado)
        self.assertFalse(retry.foi_criado)
        self.assertEqual(LancamentoFinanceiro.objects.count(), 1)

    def test_project_a_and_project_b_are_distinct_identities(self):
        first = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            projeto_id=self.project_a.pk,
        )
        second = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            projeto_id=self.project_b.pk,
        )

        self.assertNotEqual(second.pk, first.pk)
        self.assertEqual(LancamentoFinanceiro.objects.count(), 2)

    def test_project_a_and_none_are_distinct_in_both_orders(self):
        project_first = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            projeto_id=self.project_a.pk,
        )
        none_second = lancar_pagamento_funcionario_service(self.funcionario.pk)

        self.assertNotEqual(project_first.pk, none_second.pk)
        self.assertIsNone(none_second.projeto_id)

        reverse_project = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            projeto_id=self.project_b.pk,
            observacao='ordem reversa projeto',
        )
        reverse_none = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            observacao='ordem reversa projeto',
        )

        self.assertNotEqual(reverse_project.pk, reverse_none.pk)
        self.assertEqual(LancamentoFinanceiro.objects.count(), 4)

    def test_legacy_none_row_is_reusable_by_none_retry(self):
        legacy = LancamentoFinanceiro.objects.create(
            tipo='SAIDA',
            categoria='FUNCIONARIO',
            funcionario=self.funcionario,
            descricao='Pagamento equipe - Funcionário Projeto (Diária)',
            valor=Decimal('100.00'),
            forma_pagamento='PIX',
            data_vencimento=timezone.localdate(),
            data_pagamento=timezone.localdate(),
            status='PAGO',
        )

        retry = lancar_pagamento_funcionario_service(self.funcionario.pk)

        self.assertEqual(retry.pk, legacy.pk)
        self.assertFalse(retry.foi_criado)
        self.assertEqual(LancamentoFinanceiro.objects.count(), 1)
        self.assertEqual(EventoSistema.objects.count(), 0)

    def test_legacy_none_row_is_not_reusable_by_project_a(self):
        legacy = LancamentoFinanceiro.objects.create(
            tipo='SAIDA',
            categoria='FUNCIONARIO',
            funcionario=self.funcionario,
            descricao='Pagamento equipe - Funcionário Projeto (Diária)',
            valor=Decimal('100.00'),
            forma_pagamento='PIX',
            data_vencimento=timezone.localdate(),
            data_pagamento=timezone.localdate(),
            status='PAGO',
        )

        project_payment = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            projeto_id=self.project_a.pk,
        )

        self.assertNotEqual(project_payment.pk, legacy.pk)
        self.assertEqual(project_payment.projeto_id, self.project_a.pk)
        self.assertEqual(LancamentoFinanceiro.objects.count(), 2)

    def test_project_a_row_is_not_reusable_by_none_retry(self):
        project_payment = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            projeto_id=self.project_a.pk,
        )

        none_payment = lancar_pagamento_funcionario_service(self.funcionario.pk)

        self.assertNotEqual(none_payment.pk, project_payment.pk)
        self.assertIsNone(none_payment.projeto_id)
        self.assertEqual(LancamentoFinanceiro.objects.count(), 2)

    def test_cancelled_project_a_does_not_block_new_project_a_payment(self):
        cancelled = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            projeto_id=self.project_a.pk,
        )
        cancelled.status = 'CANCELADO'
        cancelled.save(update_fields=['status'])

        replacement = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            projeto_id=self.project_a.pk,
        )

        self.assertNotEqual(replacement.pk, cancelled.pk)
        self.assertEqual(replacement.projeto_id, self.project_a.pk)
        self.assertEqual(
            LancamentoFinanceiro.objects.get(pk=cancelled.pk).status,
            'CANCELADO',
        )

    def test_cancelled_none_does_not_block_new_none_payment(self):
        cancelled = lancar_pagamento_funcionario_service(self.funcionario.pk)
        cancelled.status = 'CANCELADO'
        cancelled.save(update_fields=['status'])

        replacement = lancar_pagamento_funcionario_service(self.funcionario.pk)

        self.assertNotEqual(replacement.pk, cancelled.pk)
        self.assertIsNone(replacement.projeto_id)
        self.assertEqual(
            LancamentoFinanceiro.objects.get(pk=cancelled.pk).status,
            'CANCELADO',
        )

    def test_observation_identity_is_normalized_with_project(self):
        payments = [
            lancar_pagamento_funcionario_service(
                self.funcionario.pk,
                projeto_id=self.project_a.pk,
                observacao=observation,
            )
            for observation in (None, '', ' ', '   ')
        ]

        self.assertEqual(LancamentoFinanceiro.objects.count(), 1)
        self.assertEqual({payment.pk for payment in payments}, {payments[0].pk})

    def test_internal_observation_whitespace_remains_distinct_with_project(self):
        first = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            projeto_id=self.project_a.pk,
            observacao='bônus especial',
        )
        second = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            projeto_id=self.project_a.pk,
            observacao='bônus  especial',
        )

        self.assertNotEqual(second.pk, first.pk)
        self.assertEqual(LancamentoFinanceiro.objects.count(), 2)

    def test_quantity_period_is_excluded_from_identity_with_same_project(self):
        first = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            projeto_id=self.project_a.pk,
            quantidade_periodos=1,
        )
        retry = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            projeto_id=self.project_a.pk,
            quantidade_periodos=2,
            valor_customizado=Decimal('100.00'),
        )

        self.assertEqual(retry.pk, first.pk)
        self.assertFalse(retry.foi_criado)
        self.assertEqual(LancamentoFinanceiro.objects.count(), 1)

    def test_quantity_period_does_not_cross_project_identity(self):
        first = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            projeto_id=self.project_a.pk,
            quantidade_periodos=1,
        )
        second = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            projeto_id=self.project_b.pk,
            quantidade_periodos=2,
            valor_customizado=Decimal('100.00'),
        )

        self.assertNotEqual(second.pk, first.pk)
        self.assertEqual(LancamentoFinanceiro.objects.count(), 2)

    def test_due_date_is_part_of_identity_with_project(self):
        first = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            projeto_id=self.project_a.pk,
            data_vencimento=date(2026, 1, 15),
        )
        second = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            projeto_id=self.project_a.pk,
            data_vencimento=date(2026, 1, 16),
        )

        self.assertNotEqual(second.pk, first.pk)

    def test_value_is_part_of_identity_with_project(self):
        first = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            projeto_id=self.project_a.pk,
            valor_customizado=Decimal('100.00'),
        )
        second = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            projeto_id=self.project_a.pk,
            valor_customizado=Decimal('101.00'),
        )

        self.assertNotEqual(second.pk, first.pk)

    def test_payment_method_is_part_of_identity_with_project(self):
        first = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            projeto_id=self.project_a.pk,
            forma_pagamento='PIX',
        )
        second = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            projeto_id=self.project_a.pk,
            forma_pagamento='DINHEIRO',
        )

        self.assertNotEqual(second.pk, first.pk)

    def test_status_is_part_of_identity_with_project(self):
        paid = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            projeto_id=self.project_a.pk,
            pago_hoje=True,
        )
        pending = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            projeto_id=self.project_a.pk,
            pago_hoje=False,
        )

        self.assertNotEqual(pending.pk, paid.pk)
        self.assertEqual(pending.status, 'PENDENTE')

    def test_employee_is_part_of_identity_with_project(self):
        other_employee = Funcionario.objects.create(
            nome='Outro Funcionário Projeto',
            funcao='Marceneiro',
            periodicidade='DIARIA',
            valor_base=Decimal('100.00'),
        )
        first = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            projeto_id=self.project_a.pk,
        )
        second = lancar_pagamento_funcionario_service(
            other_employee.pk,
            projeto_id=self.project_a.pk,
        )

        self.assertNotEqual(second.pk, first.pk)
        self.assertEqual(second.funcionario_id, other_employee.pk)

    def test_invalid_project_ids_are_rejected_atomically(self):
        invalid_project_ids = (0, -1, True, '1', object(), 999999)

        for invalid_project_id in invalid_project_ids:
            with self.subTest(invalid_project_id=repr(invalid_project_id)):
                initial_financial_count = LancamentoFinanceiro.objects.count()
                initial_event_count = EventoSistema.objects.count()

                with self.assertRaises(ValidationError) as raised:
                    lancar_pagamento_funcionario_service(
                        self.funcionario.pk,
                        projeto_id=invalid_project_id,
                    )

                self.assertEqual(raised.exception.message, 'Projeto inválido.')
                self.assertEqual(
                    LancamentoFinanceiro.objects.count(),
                    initial_financial_count,
                )
                self.assertEqual(
                    EventoSistema.objects.count(),
                    initial_event_count,
                )

    def test_project_creation_records_one_event_with_existing_contract(self):
        payment = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            projeto_id=self.project_a.pk,
        )

        event = EventoSistema.objects.get(tipo='PAGAMENTO_FUNCIONARIO_CRIADO')
        self.assertEqual(EventoSistema.objects.count(), 1)
        self.assertEqual(event.dominio, 'EQUIPE')
        self.assertEqual(event.entidade_tipo, 'Funcionario')
        self.assertEqual(event.entidade_id, str(self.funcionario.pk))
        self.assertEqual(event.metadata['lancamento_id'], str(payment.pk))
        self.assertEqual(event.metadata['valor'], '100.00')

    def test_project_retry_creates_no_duplicate_event(self):
        first = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            projeto_id=self.project_a.pk,
        )
        retry = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            projeto_id=self.project_a.pk,
        )

        self.assertEqual(retry.pk, first.pk)
        self.assertEqual(
            EventoSistema.objects.filter(
                tipo='PAGAMENTO_FUNCIONARIO_CRIADO',
            ).count(),
            1,
        )

    def test_distinct_project_creations_record_one_event_each(self):
        first = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            projeto_id=self.project_a.pk,
        )
        second = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            projeto_id=self.project_b.pk,
        )

        events = EventoSistema.objects.filter(
            tipo='PAGAMENTO_FUNCIONARIO_CRIADO',
        )
        self.assertEqual(events.count(), 2)
        self.assertEqual(
            {event.metadata['lancamento_id'] for event in events},
            {str(first.pk), str(second.pk)},
        )

    def test_none_and_project_creations_record_one_event_each(self):
        none_payment = lancar_pagamento_funcionario_service(self.funcionario.pk)
        project_payment = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            projeto_id=self.project_a.pk,
        )

        events = EventoSistema.objects.filter(
            tipo='PAGAMENTO_FUNCIONARIO_CRIADO',
        )
        self.assertEqual(events.count(), 2)
        self.assertEqual(
            {event.metadata['lancamento_id'] for event in events},
            {str(none_payment.pk), str(project_payment.pk)},
        )

    def test_project_retry_preserves_persisted_project_description_and_fields(self):
        first = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            projeto_id=self.project_a.pk,
            quantidade_periodos=2,
            valor_customizado=Decimal('100.00'),
            forma_pagamento='DINHEIRO',
            pago_hoje=False,
            data_vencimento=date(2026, 2, 3),
            observacao=' bônus ',
        )
        before = LancamentoFinanceiro.objects.values().get(pk=first.pk)

        retry = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            projeto_id=self.project_a.pk,
            quantidade_periodos=1,
            valor_customizado=Decimal('100.00'),
            forma_pagamento='DINHEIRO',
            pago_hoje=False,
            data_vencimento=date(2026, 2, 3),
            observacao='bônus',
        )
        after = LancamentoFinanceiro.objects.values().get(pk=first.pk)

        self.assertEqual(retry.pk, first.pk)
        self.assertFalse(retry.foi_criado)
        self.assertEqual(after, before)
        self.assertEqual(retry.projeto_id, self.project_a.pk)

    def test_pending_and_paid_project_payments_persist_project(self):
        pending = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            projeto_id=self.project_a.pk,
            pago_hoje=False,
            observacao='pendente',
        )
        paid = lancar_pagamento_funcionario_service(
            self.funcionario.pk,
            projeto_id=self.project_a.pk,
            pago_hoje=True,
            observacao='pago',
        )

        self.assertEqual(pending.status, 'PENDENTE')
        self.assertEqual(pending.projeto_id, self.project_a.pk)
        self.assertEqual(paid.status, 'PAGO')
        self.assertEqual(paid.projeto_id, self.project_a.pk)

    def test_event_failure_rolls_back_project_financial_creation(self):
        with patch(
            'apps.equipe.services.registrar_evento',
            side_effect=RuntimeError('event failure'),
        ):
            with self.assertRaises(RuntimeError):
                lancar_pagamento_funcionario_service(
                    self.funcionario.pk,
                    projeto_id=self.project_a.pk,
                )

        self.assertEqual(LancamentoFinanceiro.objects.count(), 0)
        self.assertEqual(EventoSistema.objects.count(), 0)

    def test_financial_value_validation_remains_unchanged_with_project(self):
        for invalid_value in (Decimal('0.00'), Decimal('-1.00')):
            with self.subTest(invalid_value=invalid_value):
                with self.assertRaises(ValidationError):
                    lancar_pagamento_funcionario_service(
                        self.funcionario.pk,
                        projeto_id=self.project_a.pk,
                        valor_customizado=invalid_value,
                    )

                self.assertEqual(LancamentoFinanceiro.objects.count(), 0)
                self.assertEqual(EventoSistema.objects.count(), 0)
