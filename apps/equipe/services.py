from decimal import Decimal
from typing import Optional

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.core_sistema.services import registrar_evento
from apps.financeiro.models import LancamentoFinanceiro
from .models import Funcionario


def _normalize_observacao(observacao: str | None) -> str:
    return (observacao or '').strip()


def _payment_description_prefix(funcionario: Funcionario) -> str:
    periodicidade = funcionario.get_periodicidade_display()
    return f"Pagamento equipe - {funcionario.nome} ({periodicidade})"


def _extract_service_observacao(
    descricao: str,
    funcionario: Funcionario,
) -> str | None:
    prefix = _payment_description_prefix(funcionario)
    if descricao == prefix:
        return ''
    if not descricao.startswith(prefix):
        return None

    suffix = descricao[len(prefix):]
    if suffix.startswith(' - '):
        observacao = suffix[3:]
        return (
            observacao
            if observacao and observacao == observacao.strip()
            else None
        )

    if not suffix.startswith(' ['):
        return None

    quantity_end = suffix.find(']')
    if quantity_end <= 2:
        return None
    quantity_annotation = suffix[2:quantity_end]
    periodicidade_display = funcionario.get_periodicidade_display()
    if not quantity_annotation.endswith(f" {periodicidade_display}(s)"):
        return None

    observation_suffix = suffix[quantity_end + 1:]
    if not observation_suffix:
        return ''
    if not observation_suffix.startswith(' - '):
        return None
    observacao = observation_suffix[3:]
    return (
        observacao
        if observacao and observacao == observacao.strip()
        else None
    )


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
        valor_final = LancamentoFinanceiro.validar_valor_monetario(valor_customizado)
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

    observacao_normalizada = _normalize_observacao(observacao)

    # 3. Monta descrição detalhada
    desc_base = _payment_description_prefix(funcionario)
    if quantidade_periodos and quantidade_periodos != 1:
        desc_base += f" [{quantidade_periodos} {funcionario.get_periodicidade_display()}(s)]"
    if observacao_normalizada:
        desc_base += f" - {observacao_normalizada}"

    existing_lancamento = (
        LancamentoFinanceiro.objects
        .filter(
            tipo='SAIDA',
            categoria='FUNCIONARIO',
            funcionario=funcionario,
            data_vencimento=vencimento,
            valor=valor_final,
            forma_pagamento=forma_pagamento,
            status=status,
            descricao__startswith=_payment_description_prefix(funcionario),
        )
        .order_by('pk')
    )
    for candidate in existing_lancamento:
        if _extract_service_observacao(candidate.descricao, funcionario) == observacao_normalizada:
            candidate.foi_criado = False
            return candidate

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
    lancamento.foi_criado = True

    registrar_evento(
        tipo='PAGAMENTO_FUNCIONARIO_CRIADO',
        dominio='EQUIPE',
        entidade_tipo='Funcionario',
        entidade_id=funcionario.pk,
        metadata={
            'lancamento_id': lancamento.pk,
            'valor': lancamento.valor,
        },
    )

    return lancamento
