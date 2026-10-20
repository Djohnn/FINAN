from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import models


class LancamentoFinanceiro(models.Model):
    """
    Contas a pagar e receber unificadas da marcenaria.
    Base de cálculo para o Semáforo Financeiro e Fechamento do Mês.
    """
    TIPO_CHOICES = [
        ('ENTRADA', 'Entrada'),
        ('SAIDA', 'Saída'),
    ]

    CATEGORIA_CHOICES = [
        ('SERVICO_CLIENTE', 'Serviço de Cliente'),
        ('FUNCIONARIO', 'Equipe / Funcionários'),
        ('MATERIA_PRIMA', 'Matéria-Prima'),
        ('CUSTO_FIXO_OFICINA', 'Custos Fixos da Oficina'),
        ('OUTROS', 'Outros'),
    ]

    FORMA_PAGAMENTO_CHOICES = [
        ('PIX', 'PIX'),
        ('CARTAO_CREDITO', 'Cartão de Crédito'),
        ('CARTAO_DEBITO', 'Cartão de Débito'),
        ('DINHEIRO', 'Dinheiro'),
        ('BOLETO', 'Boleto'),
    ]

    STATUS_CHOICES = [
        ('PENDENTE', 'Pendente'),
        ('PAGO', 'Pago'),
        ('CANCELADO', 'Cancelado'),
    ]

    tipo = models.CharField(
        max_length=10,
        choices=TIPO_CHOICES,
        db_index=True,
        verbose_name="Tipo de Lançamento"
    )
    categoria = models.CharField(
        max_length=30,
        choices=CATEGORIA_CHOICES,
        db_index=True,
        verbose_name="Categoria"
    )
    projeto = models.ForeignKey(
        'kanban_projetos.ProjetoKanban',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lancamentos",
        verbose_name="Projeto Relacionado"
    )
    funcionario = models.ForeignKey(
        'equipe.Funcionario',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pagamentos",
        verbose_name="Funcionário Relacionado"
    )
    descricao = models.CharField(
        max_length=200,
        verbose_name="Descrição do Lançamento"
    )
    valor = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name="Valor (R$)"
    )
    forma_pagamento = models.CharField(
        max_length=20,
        choices=FORMA_PAGAMENTO_CHOICES,
        default='PIX',
        verbose_name="Forma de Pagamento"
    )
    data_vencimento = models.DateField(
        db_index=True,
        verbose_name="Data de Vencimento"
    )
    data_pagamento = models.DateField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name="Data de Pagamento"
    )
    status = models.CharField(
        max_length=15,
        choices=STATUS_CHOICES,
        default='PENDENTE',
        db_index=True,
        verbose_name="Status"
    )

    class Meta:
        verbose_name = "Lançamento Financeiro"
        verbose_name_plural = "Lançamentos Financeiros"
        ordering = ["-data_vencimento", "-id"]

    @classmethod
    def validar_valor_monetario(cls, valor, *, permitir_zero=False) -> Decimal:
        """Valida centavos exatos, finitude, magnitude e sinal sem arredondar."""
        try:
            valor = valor if isinstance(valor, Decimal) else Decimal(str(valor))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValidationError({'valor': 'Informe um valor monetário válido.'}) from exc
        if not valor.is_finite():
            raise ValidationError({'valor': 'O valor deve ser finito.'})
        if valor < 0 or (valor == 0 and not permitir_zero):
            raise ValidationError({'valor': 'O valor deve ser positivo.'})
        if valor == 0:
            return valor

        field = cls._meta.get_field('valor')
        _sign, digits, exponent = valor.as_tuple()
        # Só dígitos não nulos além da escala exigiriam arredondamento.
        excess_places = -exponent - field.decimal_places
        if excess_places > 0 and any(digits[-excess_places:]):
            raise ValidationError({'valor': 'O valor deve ser exato em centavos.'})
        integer_digits = len(digits) + exponent
        if integer_digits > field.max_digits - field.decimal_places:
            raise ValidationError({'valor': 'O valor excede o limite do campo.'})
        return valor

    def clean(self):
        super().clean()
        choice_sources = (
            ('tipo', self.TIPO_CHOICES),
            ('categoria', self.CATEGORIA_CHOICES),
            ('forma_pagamento', self.FORMA_PAGAMENTO_CHOICES),
            ('status', self.STATUS_CHOICES),
        )
        errors = {
            field_name: 'Escolha inválida.'
            for field_name, choices in choice_sources
            if getattr(self, field_name) not in {key for key, _label in choices}
        }
        try:
            self.valor = self.validar_valor_monetario(self.valor)
        except ValidationError as exc:
            errors.update(exc.message_dict)
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"[{self.get_tipo_display()}] {self.descricao} - R$ {self.valor}"
