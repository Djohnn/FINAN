from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

RECORRENCIA_CUTOFF_TIMEZONE = ZoneInfo('America/Sao_Paulo')


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
    recorrencia = models.ForeignKey(
        'DespesaRecorrente',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='lancamentos',
        verbose_name="Despesa Recorrente",
    )  # type: ignore[var-annotated]
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
    competencia = models.DateField(
        null=True,
        blank=True,
        verbose_name="Competência",
    )  # type: ignore[var-annotated]

    class Meta:
        verbose_name = "Lançamento Financeiro"
        verbose_name_plural = "Lançamentos Financeiros"
        ordering = ["-data_vencimento", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=('recorrencia', 'competencia'),
                name='financeiro_lanc_recorrencia_competencia_uniq',
            ),
            models.CheckConstraint(
                condition=(
                    Q(recorrencia__isnull=True, competencia__isnull=True)
                    | Q(recorrencia__isnull=False, competencia__isnull=False)
                ),
                name='financeiro_lanc_recorrencia_competencia_pair',
            ),
        ]

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
        has_recorrencia = self.recorrencia_id is not None
        has_competencia = self.competencia is not None
        if has_recorrencia != has_competencia:
            errors['competencia'] = (
                'Recorrência e competência devem ser informadas juntas.'
            )
        elif has_competencia:
            try:
                self.competencia = self._meta.get_field('competencia').to_python(
                    self.competencia
                )
            except ValidationError as exc:
                errors['competencia'] = exc.messages
            else:
                if self.competencia is None or self.competencia.day != 1:
                    errors['competencia'] = (
                        'A competência deve ser o primeiro dia do mês.'
                    )
                elif self.recorrencia_id is not None:
                    criado_em = self.recorrencia.criado_em
                    if timezone.is_aware(criado_em):
                        data_local = timezone.localtime(
                            criado_em,
                            RECORRENCIA_CUTOFF_TIMEZONE,
                        ).date()
                    else:
                        data_local = criado_em.date()
                    corte = data_local.replace(day=1)
                    if self.competencia < corte:
                        errors['competencia'] = (
                            'A competência não pode anteceder o mês de criação '
                            'da recorrência.'
                        )
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk:
            persisted = type(self).objects.filter(pk=self.pk).values(
                'recorrencia_id', 'competencia',
            ).first()
            if persisted and (
                persisted['recorrencia_id'] != self.recorrencia_id
                or persisted['competencia'] != self.competencia
            ):
                raise ValidationError(
                    'A identidade de recorrência e competência não pode ser alterada.'
                )
        self.clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"[{self.get_tipo_display()}] {self.descricao} - R$ {self.valor}"


class DespesaRecorrente(models.Model):
    CATEGORIA_CHOICES = LancamentoFinanceiro.CATEGORIA_CHOICES
    FORMA_PAGAMENTO_CHOICES = LancamentoFinanceiro.FORMA_PAGAMENTO_CHOICES

    descricao = models.CharField(
        max_length=200,
        verbose_name="Descrição",
    )  # type: ignore[var-annotated]
    categoria = models.CharField(
        max_length=30,
        choices=CATEGORIA_CHOICES,
        verbose_name="Categoria",
    )  # type: ignore[var-annotated]
    valor = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name="Valor (R$)",
    )  # type: ignore[var-annotated]
    forma_pagamento = models.CharField(
        max_length=20,
        choices=FORMA_PAGAMENTO_CHOICES,
        default='PIX',
        verbose_name="Forma de Pagamento",
    )  # type: ignore[var-annotated]
    dia_vencimento = models.PositiveSmallIntegerField(
        verbose_name="Dia de Vencimento",
    )  # type: ignore[var-annotated]
    data_inicio = models.DateField(
        verbose_name="Data de Início",
    )  # type: ignore[var-annotated]
    data_fim = models.DateField(
        null=True,
        blank=True,
        verbose_name="Data de Fim",
    )  # type: ignore[var-annotated]
    ativo = models.BooleanField(
        default=True,
        verbose_name="Ativa",
    )  # type: ignore[var-annotated]
    observacao = models.TextField(
        blank=True,
        verbose_name="Observação",
    )  # type: ignore[var-annotated]
    criado_em = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Criada em",
    )  # type: ignore[var-annotated]

    class Meta:
        verbose_name = "Despesa Recorrente"
        verbose_name_plural = "Despesas Recorrentes"
        ordering = ['-ativo', 'dia_vencimento', 'descricao', 'id']
        constraints = [
            models.CheckConstraint(
                condition=Q(valor__gt=0),
                name='financeiro_despesa_rec_valor_positivo',
            ),
            models.CheckConstraint(
                condition=Q(dia_vencimento__gte=1, dia_vencimento__lte=31),
                name='financeiro_despesa_rec_dia_1_31',
            ),
            models.CheckConstraint(
                condition=Q(data_fim__isnull=True) | Q(data_fim__gte=F('data_inicio')),
                name='financeiro_despesa_rec_datas_coerentes',
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.categoria not in {key for key, _label in self.CATEGORIA_CHOICES}:
            errors['categoria'] = 'Escolha inválida.'
        if self.forma_pagamento not in {
            key for key, _label in self.FORMA_PAGAMENTO_CHOICES
        }:
            errors['forma_pagamento'] = 'Escolha inválida.'
        try:
            self.valor = LancamentoFinanceiro.validar_valor_monetario(self.valor)
        except ValidationError as exc:
            errors.update(exc.message_dict)

        try:
            inicio = self._meta.get_field('data_inicio').to_python(self.data_inicio)
        except ValidationError as exc:
            errors['data_inicio'] = exc.messages
            inicio = None
        try:
            fim = self._meta.get_field('data_fim').to_python(self.data_fim)
        except ValidationError as exc:
            errors['data_fim'] = exc.messages
            fim = None
        if self.data_inicio is None:
            errors['data_inicio'] = 'Informe a data de início.'
        if self.dia_vencimento is None or not 1 <= self.dia_vencimento <= 31:
            errors['dia_vencimento'] = 'O dia de vencimento deve estar entre 1 e 31.'
        if fim is not None and inicio is not None and fim < inicio:
            errors['data_fim'] = 'A data de fim deve ser posterior ou igual à data de início.'
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk:
            persisted = type(self).objects.filter(pk=self.pk).values('criado_em').first()
            if persisted and persisted['criado_em'] != self.criado_em:
                raise ValidationError(
                    {'criado_em': 'A data de criação não pode ser alterada.'}
                )
        self.clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.descricao} — R$ {self.valor}"
