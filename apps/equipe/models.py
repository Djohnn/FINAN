from decimal import Decimal, InvalidOperation
from typing import ClassVar

from django.core.exceptions import ValidationError
from django.db import models


class Funcionario(models.Model):
    """
    Cadastro de colaboradores e marceneiros da oficina.
    Controla periodicidade de pagamento e valor base.
    """
    PERIODICIDADE_CHOICES: ClassVar[list[tuple[str, str]]] = [
        ('DIARIA', 'Diária'),
        ('SEMANAL', 'Semanal'),
        ('QUINZENAL', 'Quinzenal'),
        ('MENSAL', 'Mensal'),
    ]

    nome = models.CharField(
        max_length=150,
        verbose_name="Nome Completo"
    )
    funcao = models.CharField(
        max_length=80,
        verbose_name="Função / Cargo"
    )
    whatsapp = models.CharField(
        max_length=20,
        blank=True,
        verbose_name="WhatsApp"
    )
    chave_pix = models.CharField(
        max_length=120,
        blank=True,
        verbose_name="Chave PIX"
    )
    periodicidade = models.CharField(
        max_length=20,
        choices=PERIODICIDADE_CHOICES,
        verbose_name="Periodicidade de Pagamento"
    )
    valor_base = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name="Valor Base (R$)"
    )
    ativo = models.BooleanField(
        default=True,
        verbose_name="Ativo"
    )

    class Meta:
        verbose_name = "Funcionário"
        verbose_name_plural = "Funcionários"
        ordering: ClassVar[list[str]] = ["nome"]

    def clean(self):
        valid_periodicidades = {
            value for value, _label in self.PERIODICIDADE_CHOICES
        }
        if self.periodicidade not in valid_periodicidades:
            raise ValidationError(
                {
                    'periodicidade': 'Selecione uma periodicidade válida.',
                }
            )
        self.validate_monetary_magnitude('valor_base', self.valor_base)

    @classmethod
    def validate_monetary_magnitude(cls, field_name, value) -> Decimal:
        field = cls._meta.get_field(field_name)
        assert isinstance(field, models.DecimalField)
        try:
            decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValidationError(
                {field_name: 'Informe um valor monetário válido.'}
            ) from exc

        if not decimal_value.is_finite():
            raise ValidationError({field_name: 'O valor deve ser finito.'})

        maximum = (
            Decimal(10) ** (field.max_digits - field.decimal_places)
            - Decimal(10) ** (-field.decimal_places)
        )
        if abs(decimal_value) > maximum:
            raise ValidationError({field_name: 'O valor excede o limite do campo.'})

        quantum = Decimal(1).scaleb(-field.decimal_places)
        if decimal_value.quantize(quantum) != decimal_value:
            raise ValidationError({
                field_name: 'O valor deve ter no máximo duas casas decimais.',
            })

        if decimal_value < 0:
            raise ValidationError({
                field_name: 'O valor não pode ser negativo.',
            })

        return decimal_value

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.nome} ({self.funcao})"
