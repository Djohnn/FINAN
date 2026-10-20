from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.equipe.models import Funcionario


class EmployeePeriodicityChoiceIntegrityTests(TestCase):
    def _employee_kwargs(self, **overrides):
        return {
            'nome': 'Funcionário de Integridade',
            'funcao': 'Marceneiro',
            'periodicidade': 'DIARIA',
            'valor_base': Decimal('100.00'),
            **overrides,
        }

    def test_invalid_periodicity_update_rejects_and_preserves_persisted_state(self):
        funcionario = Funcionario.objects.create(
            **self._employee_kwargs(
                nome='Funcionário Preservado',
                periodicidade='SEMANAL',
                valor_base=Decimal('123.45'),
                ativo=False,
            )
        )
        persisted_state = {
            'periodicidade': funcionario.periodicidade,
            'nome': funcionario.nome,
            'ativo': funcionario.ativo,
            'valor_base': funcionario.valor_base,
        }
        funcionario.periodicidade = 'INVALIDA'

        with self.assertRaises(ValidationError) as context:
            funcionario.save()

        self.assertIn('periodicidade', context.exception.message_dict)
        funcionario.refresh_from_db()
        self.assertEqual(
            {
                'periodicidade': funcionario.periodicidade,
                'nome': funcionario.nome,
                'ativo': funcionario.ativo,
                'valor_base': funcionario.valor_base,
            },
            persisted_state,
        )

    def test_invalid_periodicity_create_rejects_without_persistence(self):
        with self.assertRaises(ValidationError) as context:
            Funcionario.objects.create(
                **self._employee_kwargs(periodicidade='INVALIDA')
            )

        self.assertIn('periodicidade', context.exception.message_dict)
        self.assertFalse(
            Funcionario.objects.filter(
                nome='Funcionário de Integridade',
                funcao='Marceneiro',
            ).exists()
        )

    def test_declared_periodicities_are_accepted(self):
        for periodicidade, _label in Funcionario.PERIODICIDADE_CHOICES:
            with self.subTest(periodicidade=periodicidade):
                funcionario = Funcionario.objects.create(
                    **self._employee_kwargs(
                        nome=f'Funcionário {periodicidade}',
                        periodicidade=periodicidade,
                    )
                )
                self.assertEqual(funcionario.periodicidade, periodicidade)
