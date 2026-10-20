from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.test import TestCase
from django.utils import timezone

from apps.clientes_agenda.models import Cliente
from apps.equipe.models import Funcionario
from apps.financeiro.models import LancamentoFinanceiro
from apps.financeiro.services import (
    registrar_pagamento_service,
    sincronizar_saldo_projeto,
)
from apps.kanban_projetos.models import ProjetoKanban
from apps.kanban_projetos.services import aprovar_orcamento_service


MAX_VALUE = Decimal('99999999.99')
POSITIVE_OVERFLOW = Decimal('100000000.00')
NEGATIVE_OVERFLOW = Decimal('-100000000.00')


class NonLedgerMonetaryIntegrityTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.client_record = Cliente.objects.create(
            nome='Non-ledger monetary integrity',
            whatsapp='11999999999',
        )

    def employee(self, **overrides):
        fields = {
            'nome': 'Funcionário de teste',
            'funcao': 'Marceneiro',
            'periodicidade': 'MENSAL',
            'valor_base': Decimal('123.45'),
        }
        fields.update(overrides)
        return Funcionario.objects.create(**fields)

    def project(self, **overrides):
        fields = {
            'cliente': self.client_record,
            'titulo_servico': 'Projeto de teste',
            'etapa': '1_CONTATO',
        }
        fields.update(overrides)
        return ProjetoKanban.objects.create(**fields)

    def ledger(self, project, value, **overrides):
        fields = {
            'tipo': 'ENTRADA',
            'categoria': 'SERVICO_CLIENTE',
            'projeto': project,
            'descricao': 'Lançamento de teste',
            'valor': value,
            'forma_pagamento': 'PIX',
            'data_vencimento': self.today,
            'status': 'PENDENTE',
        }
        fields.update(overrides)
        return LancamentoFinanceiro.objects.create(**fields)

    def assert_field_error(self, caught, field_name):
        self.assertTrue(hasattr(caught.exception, 'error_dict'))
        self.assertIn(field_name, caught.exception.message_dict)

    def test_funcionario_accepts_maximum_representable_magnitude(self):
        funcionario = self.employee(valor_base=MAX_VALUE)

        funcionario.refresh_from_db()
        self.assertEqual(funcionario.valor_base, MAX_VALUE)

    def test_funcionario_rejects_positive_overflow_without_persistence(self):
        before = Funcionario.objects.count()

        with self.assertRaises(ValidationError) as caught:
            self.employee(valor_base=POSITIVE_OVERFLOW)

        self.assert_field_error(caught, 'valor_base')
        self.assertEqual(Funcionario.objects.count(), before)

    def test_funcionario_rejects_negative_overflow_without_persistence(self):
        before = Funcionario.objects.count()

        with self.assertRaises(ValidationError) as caught:
            self.employee(valor_base=NEGATIVE_OVERFLOW)

        self.assert_field_error(caught, 'valor_base')
        self.assertEqual(Funcionario.objects.count(), before)

    def test_funcionario_overflow_update_preserves_all_persisted_fields(self):
        funcionario = self.employee(
            nome='Persistido',
            funcao='Montador',
            whatsapp='11988888888',
            chave_pix='pix-test',
            periodicidade='SEMANAL',
            valor_base=Decimal('321.45'),
            ativo=False,
        )
        before = Funcionario.objects.values().get(pk=funcionario.pk)

        for value in (POSITIVE_OVERFLOW, NEGATIVE_OVERFLOW):
            with self.subTest(value=value):
                funcionario.valor_base = value
                with self.assertRaises(ValidationError) as caught:
                    funcionario.save()
                self.assert_field_error(caught, 'valor_base')
                funcionario.refresh_from_db()
                self.assertEqual(
                    Funcionario.objects.values().get(pk=funcionario.pk),
                    before,
                )

    def assert_funcionario_nonfinite_rejected(self, value):
        before = Funcionario.objects.count()
        with self.assertRaises(ValidationError) as caught:
            with transaction.atomic():
                self.employee(valor_base=value)
        self.assertIsInstance(caught.exception, ValidationError)
        self.assertEqual(Funcionario.objects.count(), before)

    def test_funcionario_nan_is_controlled_validation_error(self):
        self.assert_funcionario_nonfinite_rejected(Decimal('NaN'))

    def test_funcionario_infinity_is_controlled_validation_error(self):
        self.assert_funcionario_nonfinite_rejected(Decimal('Infinity'))

    def test_funcionario_negative_infinity_is_controlled_validation_error(self):
        self.assert_funcionario_nonfinite_rejected(Decimal('-Infinity'))

    def test_funcionario_compatibility_values_are_not_rejected_by_magnitude(self):
        for value in (Decimal('0'), Decimal('-1.23'), Decimal('1.999')):
            with self.subTest(value=value):
                funcionario = self.employee(valor_base=value)
                self.assertTrue(
                    Funcionario.objects.filter(pk=funcionario.pk).exists()
                )

    def test_project_accepts_maximum_magnitude_for_each_monetary_field(self):
        for field_name in ('valor_total', 'valor_entrada', 'saldo_restante'):
            with self.subTest(field_name=field_name):
                projeto = self.project(**{field_name: MAX_VALUE})
                projeto.refresh_from_db()
                self.assertEqual(getattr(projeto, field_name), MAX_VALUE)

    def test_project_rejects_overflow_on_create_for_each_monetary_field(self):
        for field_name in ('valor_total', 'valor_entrada', 'saldo_restante'):
            for value in (POSITIVE_OVERFLOW, NEGATIVE_OVERFLOW):
                with self.subTest(field_name=field_name, value=value):
                    before = ProjetoKanban.objects.count()
                    with self.assertRaises(ValidationError) as caught:
                        with transaction.atomic():
                            self.project(**{field_name: value})
                    self.assert_field_error(caught, field_name)
                    self.assertEqual(ProjetoKanban.objects.count(), before)

    def test_project_overflow_update_preserves_state_and_exact_field_error(self):
        projeto = self.project(
            titulo_servico='Persistido',
            etapa='3_APROVADO',
            valor_total=Decimal('100.00'),
            valor_entrada=Decimal('20.00'),
            saldo_restante=Decimal('80.00'),
        )
        before = ProjetoKanban.objects.values().get(pk=projeto.pk)

        for field_name in ('valor_total', 'valor_entrada', 'saldo_restante'):
            for value in (POSITIVE_OVERFLOW, NEGATIVE_OVERFLOW):
                with self.subTest(field_name=field_name, value=value):
                    setattr(projeto, field_name, value)
                    with self.assertRaises(ValidationError) as caught:
                        projeto.save()
                    self.assert_field_error(caught, field_name)
                    projeto.refresh_from_db()
                    self.assertEqual(
                        ProjetoKanban.objects.values().get(pk=projeto.pk),
                        before,
                    )

    def assert_project_nonfinite_rejected(self, field_name):
        before = ProjetoKanban.objects.count()
        with self.assertRaises(ValidationError) as caught:
            with transaction.atomic():
                self.project(**{field_name: Decimal('NaN')})
        self.assertIsInstance(caught.exception, ValidationError)
        self.assertEqual(ProjetoKanban.objects.count(), before)

    def test_project_valor_total_nonfinite_is_controlled_and_field_specific(self):
        self.assert_project_nonfinite_rejected('valor_total')

    def test_project_valor_entrada_nonfinite_is_controlled_and_field_specific(self):
        self.assert_project_nonfinite_rejected('valor_entrada')

    def test_project_saldo_restante_nonfinite_is_controlled_and_field_specific(self):
        self.assert_project_nonfinite_rejected('saldo_restante')

    def test_project_compatibility_values_are_not_rejected_by_magnitude(self):
        for field_name in ('valor_total', 'valor_entrada', 'saldo_restante'):
            for value in (Decimal('0'), Decimal('-1.23'), Decimal('1.999')):
                with self.subTest(field_name=field_name, value=value):
                    projeto = self.project(**{field_name: value})
                    self.assertTrue(
                        ProjetoKanban.objects.filter(pk=projeto.pk).exists()
                    )

    def test_aggregate_sync_persists_representable_total(self):
        projeto = self.project(saldo_restante=Decimal('1.00'))
        self.ledger(projeto, Decimal('40.00'))
        self.ledger(projeto, Decimal('2.34'))

        result = sincronizar_saldo_projeto(projeto.pk)

        projeto.refresh_from_db()
        self.assertEqual(result, Decimal('42.34'))
        self.assertEqual(projeto.saldo_restante, Decimal('42.34'))

    def test_aggregate_overflow_rejects_before_mutating_saldo(self):
        projeto = self.project(saldo_restante=Decimal('37.00'))
        self.ledger(projeto, Decimal('60000000.00'))
        self.ledger(projeto, Decimal('60000000.00'))
        before = projeto.saldo_restante

        with self.assertRaises(ValidationError) as caught:
            sincronizar_saldo_projeto(projeto.pk)

        self.assert_field_error(caught, 'saldo_restante')
        projeto.refresh_from_db()
        self.assertEqual(projeto.saldo_restante, before)

    def test_payment_overflow_rolls_back_ledger_and_project_state(self):
        projeto = self.project(saldo_restante=Decimal('37.00'))
        rows = [self.ledger(projeto, Decimal('60000000.00')) for _ in range(3)]
        paid_attempt = rows[0]
        row_before = LancamentoFinanceiro.objects.values().get(pk=paid_attempt.pk)
        project_before = ProjetoKanban.objects.values().get(pk=projeto.pk)

        with self.assertRaises(ValidationError) as caught:
            registrar_pagamento_service(
                paid_attempt.pk,
                paid_attempt.valor,
                forma_pagamento='DINHEIRO',
            )

        self.assert_field_error(caught, 'saldo_restante')
        paid_attempt.refresh_from_db()
        projeto.refresh_from_db()
        self.assertEqual(
            LancamentoFinanceiro.objects.values().get(pk=paid_attempt.pk),
            row_before,
        )
        self.assertEqual(paid_attempt.status, 'PENDENTE')
        self.assertIsNone(paid_attempt.data_pagamento)
        self.assertEqual(paid_attempt.forma_pagamento, 'PIX')
        self.assertEqual(
            ProjetoKanban.objects.values().get(pk=projeto.pk),
            project_before,
        )
        self.assertEqual(projeto.saldo_restante, Decimal('37.00'))

    def test_approval_path_still_persists_representable_values_and_pending_balance(self):
        projeto = self.project(
            etapa='2_ORCAMENTO',
            data_limite_orcamento=self.today,
        )

        result = aprovar_orcamento_service(
            projeto_id=projeto.pk,
            valor_total=Decimal('100.00'),
            valor_entrada=Decimal('20.00'),
            forma_pagamento_entrada='PIX',
            data_inicio_producao=self.today,
            data_entrega_prevista=self.today + timedelta(days=30),
            qtd_parcelas_restante=2,
        )

        projeto.refresh_from_db()
        self.assertEqual(result.pk, projeto.pk)
        self.assertEqual(projeto.etapa, '3_APROVADO')
        self.assertEqual(projeto.valor_total, Decimal('100.00'))
        self.assertEqual(projeto.valor_entrada, Decimal('20.00'))
        self.assertEqual(projeto.saldo_restante, Decimal('80.00'))
        self.assertEqual(projeto.lancamentos.filter(status='PENDENTE').count(), 2)
