"""075: Given monetary input, When saving/servicing, Then preserve A1/B1.

All persistence uses Django's disposable test database. Snapshots include every
persisted column, so rejection must preserve business state as well as counts.
"""
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.test import TestCase
from django.utils import timezone

from apps.clientes_agenda.models import Cliente
from apps.equipe.models import Funcionario
from apps.equipe.services import lancar_pagamento_funcionario_service
from apps.financeiro.models import LancamentoFinanceiro
from apps.financeiro.services import registrar_pagamento_service
from apps.kanban_projetos.models import ProjetoKanban
from apps.kanban_projetos.services import aprovar_orcamento_service


class FinancialValueIntegrityTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.client_record = Cliente.objects.create(nome='Fixture 075', whatsapp='11999999999')
        self.employee = Funcionario.objects.create(
            nome='Fixture 075', funcao='Marceneiro', periodicidade='DIARIA',
            valor_base=Decimal('1.23'),
        )

    def ledger(self, value, **overrides):
        fields = {
            'tipo': 'ENTRADA', 'categoria': 'SERVICO_CLIENTE', 'descricao': 'Fixture 075',
            'valor': value, 'data_vencimento': self.today,
        }
        fields.update(overrides)
        return LancamentoFinanceiro.objects.create(**fields)

    def project(self):
        return ProjetoKanban.objects.create(
            cliente=self.client_record, titulo_servico='Fixture 075',
            etapa='2_ORCAMENTO', data_limite_orcamento=self.today,
        )

    def snapshot(self, project):
        return (
            ProjetoKanban.objects.values().get(pk=project.pk),
            list(LancamentoFinanceiro.objects.filter(projeto=project).order_by('pk').values()),
        )

    def approval_kwargs(self, project, **overrides):
        fields = {
            'projeto_id': project.pk, 'valor_total': Decimal('100.00'),
            'valor_entrada': Decimal('10.00'), 'forma_pagamento_entrada': 'PIX',
            'data_inicio_producao': self.today,
            'data_entrega_prevista': self.today + timedelta(days=30),
            'qtd_parcelas_restante': 3,
        }
        fields.update(overrides)
        return fields

    def assert_invalid_create(self, value):
        before = LancamentoFinanceiro.objects.count()
        with self.assertRaises(ValidationError) as caught, transaction.atomic():
            self.ledger(value)
        self.assertTrue(hasattr(caught.exception, 'error_dict'))
        self.assertIn('valor', caught.exception.message_dict)
        self.assertEqual(LancamentoFinanceiro.objects.count(), before)

    def test_model_create_rejects_overprecision(self):
        self.assert_invalid_create(Decimal('1.234'))

    def test_model_create_rejects_subcent(self):
        self.assert_invalid_create(Decimal('0.001'))

    def test_model_create_rejects_zero(self):
        self.assert_invalid_create(Decimal(0))

    def test_model_create_rejects_scaled_zero(self):
        self.assert_invalid_create(Decimal('0.00'))

    def test_model_create_rejects_signed_zero(self):
        self.assert_invalid_create(Decimal('-0.00'))

    def test_model_create_rejects_negative_cent(self):
        self.assert_invalid_create(Decimal('-0.01'))

    def test_model_create_rejects_negative_unit(self):
        self.assert_invalid_create(Decimal('-1.00'))

    def test_model_create_rejects_nan(self):
        self.assert_invalid_create(Decimal('NaN'))

    def test_model_create_rejects_infinity(self):
        self.assert_invalid_create(Decimal('Infinity'))

    def test_model_create_rejects_negative_infinity(self):
        self.assert_invalid_create(Decimal('-Infinity'))

    def test_model_create_rejects_overflow(self):
        self.assert_invalid_create(Decimal('100000000.00'))

    def test_model_create_rejects_conversion_failures(self):
        for value in ('invalid', '', None, object()):
            with self.subTest(value_type=type(value).__name__):
                self.assert_invalid_create(value)

    def test_model_accepts_exact_values_for_both_directions(self):
        for direction in ('ENTRADA', 'SAIDA'):
            for value in ('1', '1.0', '1.00', '1.000', '1.23', '1.230', '0.01', '99999999.99'):
                with self.subTest(direction=direction, value=value):
                    row = self.ledger(Decimal(value), tipo=direction)
                    row.refresh_from_db()
                    self.assertEqual(row.valor, Decimal(value))

    def test_model_supports_string_float_and_direct_instance_save(self):
        for value in ('1.230', 1.23, 0.1, 1):
            with self.subTest(value=value):
                row = self.ledger(Decimal('2.00'))
                row.valor = value
                row.save()
                row.refresh_from_db()
                self.assertEqual(row.valor, Decimal(str(value)))

    def test_model_invalid_updates_preserve_all_columns(self):
        row = self.ledger(Decimal('2.00'))
        before = LancamentoFinanceiro.objects.values().get(pk=row.pk)
        for value in ('1.234', '0', '-1', 'NaN', 'Infinity', '100000000.00'):
            with self.subTest(value=value):
                row.valor = Decimal(value)
                row.descricao = 'Must not persist'
                with self.assertRaises(ValidationError) as caught, transaction.atomic():
                        row.save()
                self.assertTrue(hasattr(caught.exception, 'error_dict'))
                self.assertIn('valor', caught.exception.message_dict)
                row.refresh_from_db()
                self.assertEqual(LancamentoFinanceiro.objects.values().get(pk=row.pk), before)

    def assert_payment_rejected(self, value, due='2.00'):
        project = self.project()
        row = self.ledger(Decimal(due), projeto=project)
        before = self.snapshot(project)
        with self.assertRaises(ValidationError):
            registrar_pagamento_service(row.pk, value, forma_pagamento='DINHEIRO')
        row.refresh_from_db()
        self.assertEqual(self.snapshot(project), before)

    def test_payment_1_999_cannot_round_to_due_2(self):
        self.assert_payment_rejected(Decimal('1.999'))

    def test_payment_rejects_invalid_inputs_without_mutation(self):
        for value in (Decimal('1.234'), '1.234', 1.234, 0, -1, 'NaN',
                      'Infinity', '-Infinity', '100000000.00', 'invalid', None):
            with self.subTest(value=value):
                self.assert_payment_rejected(value)

    def test_payment_accepts_exact_decimal_string_float(self):
        for value in (Decimal('1.230'), '1.230', 1.23, 0.1, Decimal('2.000')):
            with self.subTest(value=value):
                row = self.ledger(Decimal(str(value)))
                registrar_pagamento_service(row.pk, value)
                row.refresh_from_db()
                self.assertEqual(row.status, 'PAGO')
                self.assertEqual(row.valor, Decimal(str(value)))

    def test_payment_still_requires_full_amount(self):
        self.assert_payment_rejected(Decimal('1.23'))

    def test_employee_custom_rejects_overprecision(self):
        before = LancamentoFinanceiro.objects.count()
        with self.assertRaises(ValidationError):
            lancar_pagamento_funcionario_service(self.employee.pk, valor_customizado=Decimal('1.234'))
        self.assertEqual(LancamentoFinanceiro.objects.count(), before)

    def test_employee_custom_invalid_inputs_create_no_rows(self):
        for value in ('1.234', 1.234, 0, -1, 'NaN', 'Infinity', '-Infinity',
                      '100000000.00', 'invalid'):
            with self.subTest(value=value):
                before = LancamentoFinanceiro.objects.count()
                with self.assertRaises(ValidationError):
                    lancar_pagamento_funcionario_service(self.employee.pk, valor_customizado=value)
                self.assertEqual(LancamentoFinanceiro.objects.count(), before)

    def test_employee_custom_accepts_exact_decimal_string_float(self):
        for value in (Decimal('1.23'), Decimal('1.230'), '1.23', '1.230', 1.23, 0.1):
            with self.subTest(value=value):
                row = lancar_pagamento_funcionario_service(self.employee.pk, valor_customizado=value)
                row.refresh_from_db()
                self.assertEqual(row.valor, Decimal(str(value)))
                self.assertEqual(row.tipo, 'SAIDA')

    def test_employee_internal_arithmetic_retains_cent_rounding(self):
        row = lancar_pagamento_funcionario_service(self.employee.pk, quantidade_periodos=Decimal('0.5'))
        row.refresh_from_db()
        self.assertEqual(row.valor, Decimal('0.62'))

    def assert_approval_rejected(self, **overrides):
        project = self.project()
        self.ledger(Decimal('3.00'), projeto=project, categoria='OUTROS')
        before = self.snapshot(project)
        with self.assertRaises(ValidationError):
            aprovar_orcamento_service(**self.approval_kwargs(project, **overrides))
        project.refresh_from_db()
        self.assertEqual(self.snapshot(project), before)

    def test_approval_overprecise_total_preserves_project_and_ledger(self):
        self.assert_approval_rejected(valor_total=Decimal('100.001'))

    def test_approval_overprecise_entry_preserves_project_and_ledger(self):
        self.assert_approval_rejected(valor_entrada=Decimal('10.001'))

    def test_approval_invalid_boundaries_preserve_project_and_ledger(self):
        for field in ('valor_total', 'valor_entrada'):
            for value in ('1.234', 1.234, '-1', 'NaN', 'Infinity', '-Infinity',
                          '100000000.00', 'invalid', None):
                with self.subTest(field=field, value=value):
                    self.assert_approval_rejected(**{field: value})
        self.assert_approval_rejected(valor_total=0)

    def test_approval_exact_zero_entry_creates_only_positive_installments(self):
        project = self.project()
        kwargs = self.approval_kwargs(project, valor_total=Decimal('1.230'), valor_entrada=Decimal('0.000'))
        aprovar_orcamento_service(**kwargs)
        rows = list(project.lancamentos.order_by('pk'))
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(row.valor > 0 and row.status == 'PENDENTE' for row in rows))
        self.assertEqual(sum((row.valor for row in rows), Decimal(0)), Decimal('1.23'))
        before = self.snapshot(project)
        aprovar_orcamento_service(**kwargs)
        self.assertEqual(self.snapshot(project), before)

    def test_approval_exact_decimal_string_float_preserves_residual_cents(self):
        for total, entry in ((Decimal('1.230'), Decimal('0.100')), ('1.230', '0.100'), (1.23, 0.1)):
            with self.subTest(total=total, entry=entry):
                project = self.project()
                aprovar_orcamento_service(**self.approval_kwargs(project, valor_total=total, valor_entrada=entry))
                rows = list(project.lancamentos.order_by('pk'))
                self.assertEqual([row.valor for row in rows], [Decimal(x) for x in ('0.10', '0.38', '0.38', '0.37')])
                self.assertEqual(sum((row.valor for row in rows), Decimal(0)), Decimal('1.23'))
