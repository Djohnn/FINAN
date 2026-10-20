from decimal import Decimal
from typing import Optional

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.financeiro.models import LancamentoFinanceiro
from .models import Funcionario


@transaction.atomic
def lancar_pagamento_funcionario_service(
    funcionario_id: int,
    quantidade_periodos: int | float | Decimal = 1,
    valor_customizado: Optional[Decimal | float | str] = None,
    forma_pagamento: str = 'PIX',
    pago_hoje: bool = True,
    data_vencimento=None,
    observacao: str = '',
) -> LancamentoFinanceiro:
    """
    Lança um pagamento para colaborador/funcionário, calculando o valor
    multiplicado pelos períodos/diárias trabalhadas ou usando um valor customizado.
    Gera um lançamento financeiro de SAÍDA na categoria FUNCIONARIO.
    """
    funcionario = Funcionario.objects.select_for_update().get(id=funcionario_id)

    valid_payment_methods = {
        value for value, _label in LancamentoFinanceiro.FORMA_PAGAMENTO_CHOICES
    }
    if forma_pagamento not in valid_payment_methods:
        raise ValidationError("Forma de pagamento inválida.")

    # 1. Determina valor a pagar
    if valor_customizado is not None:
        valor_final = Decimal(str(valor_customizado))
    else:
        qtd = Decimal(str(quantidade_periodos))
        if qtd <= 0:
            raise ValidationError("A quantidade de períodos deve ser maior que zero.")
        valor_final = (funcionario.valor_base * qtd).quantize(Decimal('0.01'))

    if valor_final <= Decimal('0.00'):
        raise ValidationError("O valor do pagamento deve ser maior que zero.")

    # 2. Determina datas e status
    hoje = timezone.localdate()
    vencimento = data_vencimento or hoje
    status = 'PAGO' if pago_hoje else 'PENDENTE'
    data_pagamento = hoje if pago_hoje else None

    # 3. Monta descrição detalhada
    desc_base = f"Pagamento equipe - {funcionario.nome} ({funcionario.get_periodicidade_display()})"
    if quantidade_periodos and quantidade_periodos != 1:
        desc_base += f" [{quantidade_periodos} {funcionario.get_periodicidade_display()}(s)]"
    if observacao and observacao.strip():
        desc_base += f" - {observacao.strip()}"

    # 4. Registra saída no financeiro
    lancamento = LancamentoFinanceiro.objects.create(
        tipo='SAIDA',
        categoria='FUNCIONARIO',
        funcionario=funcionario,
        descricao=desc_base,
        valor=valor_final,
        forma_pagamento=forma_pagamento,
        data_vencimento=vencimento,
        data_pagamento=data_pagamento,
        status=status,
    )

    return lancamento
