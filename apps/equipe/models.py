from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models


class Funcionario(models.Model):
    """
    Cadastro de colaboradores e marceneiros da oficina.
    Controla periodicidade de pagamento e valor base.
    """
    PERIODICIDADE_CHOICES = [
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
        ordering = ["nome"]

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

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.nome} ({self.funcao})"
