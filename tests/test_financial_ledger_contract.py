from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.financeiro.models import LancamentoFinanceiro


class FinancialLedgerChoiceIntegrityTests(TestCase):
    def _ledger_kwargs(self, **overrides):
        return {
            'tipo': LancamentoFinanceiro.TIPO_CHOICES[0][0],
            'categoria': LancamentoFinanceiro.CATEGORIA_CHOICES[0][0],
            'descricao': 'Lançamento de integridade',
            'valor': Decimal('10.00'),
            'forma_pagamento': LancamentoFinanceiro.FORMA_PAGAMENTO_CHOICES[0][0],
            'data_vencimento': date(2026, 10, 20),
            'status': LancamentoFinanceiro.STATUS_CHOICES[0][0],
            **overrides,
        }

    def test_invalid_tipo_create_rejects_without_persistence(self):
        with self.assertRaises(ValidationError) as context:
            LancamentoFinanceiro.objects.create(
                **self._ledger_kwargs(tipo='TIPO_INVALIDO')
            )

        self.assertIn('tipo', context.exception.message_dict)
        self.assertFalse(
            LancamentoFinanceiro.objects.filter(
                descricao='Lançamento de integridade',
                tipo='TIPO_INVALIDO',
            ).exists()
        )

    def test_invalid_categoria_create_rejects_without_persistence(self):
        with self.assertRaises(ValidationError) as context:
            LancamentoFinanceiro.objects.create(
                **self._ledger_kwargs(categoria='CATEGORIA_INVALIDA')
            )

        self.assertIn('categoria', context.exception.message_dict)
        self.assertFalse(
            LancamentoFinanceiro.objects.filter(
                descricao='Lançamento de integridade',
                categoria='CATEGORIA_INVALIDA',
            ).exists()
        )

    def test_invalid_forma_pagamento_create_rejects_without_persistence(self):
        with self.assertRaises(ValidationError) as context:
            LancamentoFinanceiro.objects.create(
                **self._ledger_kwargs(forma_pagamento='FORMA_INVALIDA')
            )

        self.assertIn('forma_pagamento', context.exception.message_dict)
        self.assertFalse(
            LancamentoFinanceiro.objects.filter(
                descricao='Lançamento de integridade',
                forma_pagamento='FORMA_INVALIDA',
            ).exists()
        )

    def test_invalid_status_create_rejects_without_persistence(self):
        with self.assertRaises(ValidationError) as context:
            LancamentoFinanceiro.objects.create(
                **self._ledger_kwargs(status='STATUS_INVALIDO')
            )

        self.assertIn('status', context.exception.message_dict)
        self.assertFalse(
            LancamentoFinanceiro.objects.filter(
                descricao='Lançamento de integridade',
                status='STATUS_INVALIDO',
            ).exists()
        )

    def test_invalid_tipo_update_rejects_and_preserves_persisted_state(self):
        lancamento = LancamentoFinanceiro.objects.create(
            **self._ledger_kwargs(
                tipo=LancamentoFinanceiro.TIPO_CHOICES[1][0],
                descricao='Tipo preservado',
            )
        )
        persisted_state = LancamentoFinanceiro.objects.values().get(pk=lancamento.pk)
        lancamento.tipo = 'TIPO_INVALIDO'

        with self.assertRaises(ValidationError) as context:
            lancamento.save()

        self.assertIn('tipo', context.exception.message_dict)
        lancamento.refresh_from_db()
        self.assertEqual(
            LancamentoFinanceiro.objects.values().get(pk=lancamento.pk),
            persisted_state,
        )

    def test_invalid_categoria_update_rejects_and_preserves_persisted_state(self):
        lancamento = LancamentoFinanceiro.objects.create(
            **self._ledger_kwargs(
                categoria=LancamentoFinanceiro.CATEGORIA_CHOICES[1][0],
                descricao='Categoria preservada',
            )
        )
        persisted_state = LancamentoFinanceiro.objects.values().get(pk=lancamento.pk)
        lancamento.categoria = 'CATEGORIA_INVALIDA'

        with self.assertRaises(ValidationError) as context:
            lancamento.save()

        self.assertIn('categoria', context.exception.message_dict)
        lancamento.refresh_from_db()
        self.assertEqual(
            LancamentoFinanceiro.objects.values().get(pk=lancamento.pk),
            persisted_state,
        )

    def test_invalid_forma_pagamento_update_rejects_and_preserves_persisted_state(self):
        lancamento = LancamentoFinanceiro.objects.create(
            **self._ledger_kwargs(
                forma_pagamento=LancamentoFinanceiro.FORMA_PAGAMENTO_CHOICES[1][0],
                descricao='Forma preservada',
            )
        )
        persisted_state = LancamentoFinanceiro.objects.values().get(pk=lancamento.pk)
        lancamento.forma_pagamento = 'FORMA_INVALIDA'

        with self.assertRaises(ValidationError) as context:
            lancamento.save()

        self.assertIn('forma_pagamento', context.exception.message_dict)
        lancamento.refresh_from_db()
        self.assertEqual(
            LancamentoFinanceiro.objects.values().get(pk=lancamento.pk),
            persisted_state,
        )

    def test_invalid_status_update_rejects_and_preserves_persisted_state(self):
        lancamento = LancamentoFinanceiro.objects.create(
            **self._ledger_kwargs(
                status=LancamentoFinanceiro.STATUS_CHOICES[1][0],
                descricao='Status preservado',
            )
        )
        persisted_state = LancamentoFinanceiro.objects.values().get(pk=lancamento.pk)
        lancamento.status = 'STATUS_INVALIDO'

        with self.assertRaises(ValidationError) as context:
            lancamento.save()

        self.assertIn('status', context.exception.message_dict)
        lancamento.refresh_from_db()
        self.assertEqual(
            LancamentoFinanceiro.objects.values().get(pk=lancamento.pk),
            persisted_state,
        )

    def test_all_declared_tipo_choices_are_accepted(self):
        for tipo, _label in LancamentoFinanceiro.TIPO_CHOICES:
            with self.subTest(tipo=tipo):
                lancamento = LancamentoFinanceiro.objects.create(
                    **self._ledger_kwargs(tipo=tipo, descricao=f'Tipo {tipo}')
                )
                self.assertEqual(lancamento.tipo, tipo)

    def test_all_declared_categoria_choices_are_accepted(self):
        for categoria, _label in LancamentoFinanceiro.CATEGORIA_CHOICES:
            with self.subTest(categoria=categoria):
                lancamento = LancamentoFinanceiro.objects.create(
                    **self._ledger_kwargs(
                        categoria=categoria,
                        descricao=f'Categoria {categoria}',
                    )
                )
                self.assertEqual(lancamento.categoria, categoria)

    def test_all_declared_forma_pagamento_choices_are_accepted(self):
        for forma_pagamento, _label in LancamentoFinanceiro.FORMA_PAGAMENTO_CHOICES:
            with self.subTest(forma_pagamento=forma_pagamento):
                lancamento = LancamentoFinanceiro.objects.create(
                    **self._ledger_kwargs(
                        forma_pagamento=forma_pagamento,
                        descricao=f'Forma {forma_pagamento}',
                    )
                )
                self.assertEqual(lancamento.forma_pagamento, forma_pagamento)

    def test_all_declared_status_choices_are_accepted(self):
        for status, _label in LancamentoFinanceiro.STATUS_CHOICES:
            with self.subTest(status=status):
                lancamento = LancamentoFinanceiro.objects.create(
                    **self._ledger_kwargs(status=status, descricao=f'Status {status}')
                )
                self.assertEqual(lancamento.status, status)
