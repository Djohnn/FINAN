from calendar import monthrange
from datetime import date, datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.core_sistema.services import registrar_evento

from .models import DespesaRecorrente, LancamentoFinanceiro


@transaction.atomic
def gerar_lancamento_recorrente_competencia_service(
    recorrencia_id: int,
    competencia: date,
) -> LancamentoFinanceiro | None:
    """Cria, no máximo, o lançamento da competência explicitamente informada."""
    if (
        not isinstance(competencia, date)
        or isinstance(competencia, datetime)
        or competencia.day != 1
    ):
        raise ValidationError(
            {'competencia': 'A competência deve ser o primeiro dia do mês.'}
        )

    recorrencia = DespesaRecorrente.objects.select_for_update().get(
        pk=recorrencia_id
    )
    lancamento_existente = LancamentoFinanceiro.objects.filter(
        recorrencia=recorrencia,
        competencia=competencia,
    ).first()
    if lancamento_existente is not None:
        lancamento_existente.foi_criado = False
        return lancamento_existente

    ultimo_dia = monthrange(competencia.year, competencia.month)[1]
    data_vencimento = date(
        competencia.year,
        competencia.month,
        min(recorrencia.dia_vencimento, ultimo_dia),
    )
    if not _recorrencia_elegivel_para_competencia(
        recorrencia,
        competencia,
        data_vencimento,
    ):
        return None

    lancamento, criado = LancamentoFinanceiro.objects.get_or_create(
        recorrencia=recorrencia,
        competencia=competencia,
        defaults={
            'tipo': 'SAIDA',
            'categoria': recorrencia.categoria,
            'projeto': None,
            'funcionario': None,
            'descricao': recorrencia.descricao,
            'valor': recorrencia.valor,
            'forma_pagamento': recorrencia.forma_pagamento,
            'data_vencimento': data_vencimento,
            'data_pagamento': None,
            'status': 'PENDENTE',
        },
    )
    lancamento.foi_criado = criado
    return lancamento


def _recorrencia_elegivel_para_competencia(
    recorrencia: DespesaRecorrente,
    competencia: date,
    data_vencimento: date,
) -> bool:
    """Aplica limites de mês e bloqueia as duas fronteiras ainda sem política."""
    if not recorrencia.ativo:
        return False

    inicio_competencia = recorrencia.data_inicio.replace(day=1)
    if competencia < inicio_competencia:
        return False
    if competencia == inicio_competencia and data_vencimento < recorrencia.data_inicio:
        raise ValidationError(
            {
                'competencia': (
                    'A política para vencimento anterior à data de início '
                    'no mesmo mês ainda não foi definida.'
                )
            }
        )

    if recorrencia.data_fim is None:
        return True

    fim_competencia = recorrencia.data_fim.replace(day=1)
    if competencia > fim_competencia:
        return False
    if competencia == fim_competencia:
        ultimo_dia = monthrange(competencia.year, competencia.month)[1]
        if recorrencia.data_fim.day != ultimo_dia:
            raise ValidationError(
                {
                    'competencia': (
                        'A política para competência no mês de uma data de fim '
                        'intermediária ainda não foi definida.'
                    )
                }
            )
    return True


@transaction.atomic
def criar_despesa_recorrente_service(
    *,
    descricao: str,
    categoria: str,
    valor: Decimal | str | int,
    forma_pagamento: str,
    dia_vencimento: int,
    data_inicio: date,
    data_fim: date | None = None,
    ativo: bool = True,
    observacao: str = '',
) -> DespesaRecorrente:
    """Valida e cria a recorrência, gerando o mês local atual na mesma transação."""
    recorrencia = DespesaRecorrente(
        descricao=descricao,
        categoria=categoria,
        valor=valor,
        forma_pagamento=forma_pagamento,
        dia_vencimento=dia_vencimento,
        data_inicio=data_inicio,
        data_fim=data_fim,
        ativo=ativo,
        observacao=observacao,
    )
    recorrencia.full_clean()
    recorrencia.save()

    competencia_atual = timezone.localdate().replace(day=1)
    gerar_lancamento_recorrente_competencia_service(
        recorrencia.pk,
        competencia_atual,
    )
    return recorrencia


@transaction.atomic
def gerar_despesas_recorrentes_mes_atual_service() -> list[LancamentoFinanceiro]:
    """Processa somente recorrências ativas para o mês local atual."""
    competencia_atual = timezone.localdate().replace(day=1)
    lancamentos: list[LancamentoFinanceiro] = []
    recorrencias = DespesaRecorrente.objects.filter(ativo=True).order_by('pk')
    for recorrencia in recorrencias:
        lancamento = gerar_lancamento_recorrente_competencia_service(
            recorrencia.pk,
            competencia_atual,
        )
        if lancamento is not None:
            lancamentos.append(lancamento)
    return lancamentos


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
