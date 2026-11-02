from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.core_sistema.services import registrar_evento

from .models import LancamentoFinanceiro


@transaction.atomic
def registrar_pagamento_service(
    lancamento_id: int,
    valor: Decimal | str | int,
    forma_pagamento: str | None = None,
) -> LancamentoFinanceiro:
    """Registra uma quitação integral e sincroniza o saldo do projeto.

    Pagamentos parciais não fazem parte do schema atual; aceitar um valor menor
    sem um modelo de pagamentos separado perderia a rastreabilidade.
    """
    lancamento = LancamentoFinanceiro.objects.select_for_update().select_related('projeto').get(
        id=lancamento_id
    )
    if lancamento.status != 'PENDENTE':
        raise ValidationError("Somente lançamentos pendentes podem ser quitados.")
    valor_pago = LancamentoFinanceiro.validar_valor_monetario(valor).quantize(Decimal('0.01'))
    if valor_pago != lancamento.valor:
        raise ValidationError("O schema atual suporta apenas quitação integral do lançamento.")
    if forma_pagamento:
        formas_validas = {value for value, _ in LancamentoFinanceiro.FORMA_PAGAMENTO_CHOICES}
        if forma_pagamento not in formas_validas:
            raise ValidationError("A forma de pagamento é inválida.")
        lancamento.forma_pagamento = forma_pagamento
    lancamento.status = 'PAGO'
    lancamento.data_pagamento = timezone.localdate()
    lancamento.save(update_fields=['status', 'data_pagamento', 'forma_pagamento'])
    sincronizar_saldo_projeto(lancamento.projeto_id)
    registrar_evento(
        tipo='LANCAMENTO_QUITADO',
        dominio='FINANCEIRO',
        entidade_tipo='LancamentoFinanceiro',
        entidade_id=lancamento.pk,
        metadata={'valor': lancamento.valor},
    )
    return lancamento


def sincronizar_saldo_projeto(projeto_id: int | None) -> Decimal:
    """Atualiza o campo legado com a soma dos lançamentos pendentes."""
    if not projeto_id:
        return Decimal('0.00')
    total = LancamentoFinanceiro.objects.filter(
        projeto_id=projeto_id,
        tipo='ENTRADA',
        status='PENDENTE',
    ).aggregate(total=Sum('valor'))['total'] or Decimal('0.00')
    from apps.kanban_projetos.models import ProjetoKanban

    ProjetoKanban.validate_monetary_magnitude('saldo_restante', total)
    ProjetoKanban.objects.filter(id=projeto_id).update(saldo_restante=total)
    return total
