"""Read-only monthly closing over the current ledger (frozen V1 contract)."""
from calendar import monthrange
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_EVEN, localcontext
from typing import Literal

from django.core.exceptions import ValidationError
from django.db.models import BooleanField, Case, CharField, F, Value, When
from django.db.models.functions import Cast, Round

from apps.financeiro.models import LancamentoFinanceiro


@dataclass(frozen=True)
class EntradaPorForma:
    forma_pagamento: str
    total: Decimal


@dataclass(frozen=True)
class CustoFuncionario:
    funcionario_id: int | None
    nome: str
    total: Decimal


@dataclass(frozen=True)
class FechamentoMensal:
    ano: int
    mes: int
    data_inicio: date
    data_fim: date
    total_entradas: Decimal
    entradas_por_forma: tuple[EntradaPorForma, ...]
    total_funcionarios: Decimal
    funcionarios_percentual: Decimal | None
    funcionarios: tuple[CustoFuncionario, ...]
    outras_saidas: Decimal
    saldo_final: Decimal
    margem_percentual: Decimal | None
    semaforo: Literal['VERDE', 'AMARELO', 'VERMELHO']
    inadimplencia_total: Decimal
    inadimplencia_quantidade: int


_ZERO = Decimal('0.00')
_FORMS = ('PIX', 'CARTAO_CREDITO', 'CARTAO_DEBITO', 'DINHEIRO', 'BOLETO')
_PREFIX = 'Fechamento mensal indisponível: '


def _invalid(field: str) -> ValueError:
    label = 'valor monetário' if field == 'valor' else field
    gender = 'inválida' if field in {'categoria', 'forma_pagamento'} else 'inválido'
    return ValueError(f'{_PREFIX}{label} {gender} em lançamento relevante.')


def _money(cents: int) -> Decimal:
    """Build a scale-two Decimal exactly, without caller-context arithmetic."""
    digits = tuple(int(digit) for digit in str(abs(cents)))
    return Decimal((int(cents < 0), digits, -2))


def _percent(numerator: Decimal, revenue: Decimal) -> Decimal | None:
    if revenue <= _ZERO:
        return None
    with localcontext() as context:
        context.prec = 28
        context.rounding = ROUND_HALF_EVEN
        return numerator / revenue * Decimal('100')


def fechamento_mensal(*, ano: int, mes: int) -> FechamentoMensal:
    """Select cash by payment date and debt by cutoff, without writing history.

    Check stored cents inside the DB before text/Decimal conversion can hide
    corrupt legacy precision. Validate whole anomaly classes before accumulating,
    so error precedence is independent of row ordering. One joined projection
    supplies employee identity/name without per-employee queries.
    """
    if isinstance(ano, bool) or not isinstance(ano, int):
        raise ValueError('ano deve ser um inteiro.')
    if not 1 <= ano <= 9999:
        raise ValueError('ano deve estar entre 1 e 9999.')
    if isinstance(mes, bool) or not isinstance(mes, int):
        raise ValueError('mes deve ser um inteiro.')
    if not 1 <= mes <= 12:
        raise ValueError('mes deve estar entre 1 e 12.')

    start = date(ano, mes, 1)
    end = date(ano, mes, monthrange(ano, mes)[1])
    rows = list(LancamentoFinanceiro.objects.order_by().annotate(
        raw_valor=Cast('valor', CharField()),
        exact_cents=Case(
            When(valor=Round(F('valor'), precision=2), then=Value(True)),
            default=Value(False), output_field=BooleanField(),
        ),
    ).values('status', 'tipo', 'categoria', 'forma_pagamento',
             'data_pagamento', 'data_vencimento', 'raw_valor', 'exact_cents',
             'funcionario_id', 'funcionario__nome'))

    if any(r['status'] == 'PAGO' and r['data_pagamento'] is None for r in rows):
        raise ValueError(_PREFIX + 'lançamento PAGO sem data_pagamento.')

    statuses = {key for key, _ in LancamentoFinanceiro.STATUS_CHOICES}
    types = {key for key, _ in LancamentoFinanceiro.TIPO_CHOICES}
    categories = {key for key, _ in LancamentoFinanceiro.CATEGORIA_CHOICES}
    for row in rows:
        paid = row['data_pagamento']
        if row['status'] not in statuses and (
            paid is None or start <= paid <= end
            or (row['data_vencimento'] <= end and row['tipo'] != 'SAIDA')
        ):
            raise _invalid('status')

    # Relevant unknown types could represent revenue due at the cutoff.
    realized = []
    debts = []
    for row in rows:
        status = row['status']
        paid = row['data_pagamento']
        cash = status == 'PAGO' and start <= paid <= end
        unpaid = row['data_vencimento'] <= end and (
            status == 'PENDENTE' or (status == 'PAGO' and paid > end)
        )
        if row['tipo'] not in types and (cash or unpaid):
            raise _invalid('tipo')
        if cash:
            realized.append(row)
        if unpaid and row['tipo'] == 'ENTRADA':
            debts.append(row)

    if any(r['tipo'] == 'SAIDA' and r['categoria'] not in categories for r in realized):
        raise _invalid('categoria')
    if any(r['tipo'] == 'ENTRADA' and r['forma_pagamento'] not in _FORMS for r in realized):
        raise _invalid('forma_pagamento')

    # A paid-later debt cannot also be realized in this month.
    for row in realized + debts:
        if not row['exact_cents']:
            raise _invalid('valor')
        try:
            amount = LancamentoFinanceiro.validar_valor_monetario(
                row['raw_valor'], permitir_zero=True,
            )
        except ValidationError:
            raise _invalid('valor') from None
        # Integer ratios avoid multiplication/scaling under the caller context.
        numerator, denominator = amount.as_integer_ratio()
        cents, remainder = divmod(numerator * 100, denominator)
        if remainder:
            raise _invalid('valor')
        row['amount'] = cents

    by_form = dict.fromkeys(_FORMS, 0)
    employee_totals: dict[int | None, int] = {}
    employee_names: dict[int | None, str] = {}
    other = 0
    for row in realized:
        amount = row['amount']
        if row['tipo'] == 'ENTRADA':
            by_form[row['forma_pagamento']] += amount
        elif row['categoria'] == 'FUNCIONARIO':
            employee_id = row['funcionario_id']
            employee_totals[employee_id] = employee_totals.get(employee_id, 0) + amount
            employee_names[employee_id] = (
                row['funcionario__nome'] if employee_id is not None
                else 'Sem funcionário vinculado'
            )
        else:
            other += amount

    employees = tuple(sorted(
        (CustoFuncionario(key, employee_names[key], _money(total))
         for key, total in employee_totals.items()),
        key=lambda item: (item.funcionario_id is None, item.nome,
                          item.funcionario_id if item.funcionario_id is not None else 0),
    ))
    revenue = sum(by_form.values())
    employee_total = sum(employee_totals.values())
    balance = revenue - employee_total - other
    debt_total = sum(row['amount'] for row in debts)
    color: Literal['VERDE', 'AMARELO', 'VERMELHO'] = 'AMARELO'
    if balance < 0:
        color = 'VERMELHO'
    elif debts:
        color = 'AMARELO'
    elif revenue > 0 and balance > 0 and balance * 100 >= revenue * 15:
        color = 'VERDE'

    return FechamentoMensal(
        ano=ano, mes=mes, data_inicio=start, data_fim=end,
        total_entradas=_money(revenue),
        entradas_por_forma=tuple(EntradaPorForma(form, _money(by_form[form])) for form in _FORMS),
        total_funcionarios=_money(employee_total),
        funcionarios_percentual=_percent(_money(employee_total), _money(revenue)), funcionarios=employees,
        outras_saidas=_money(other), saldo_final=_money(balance),
        margem_percentual=_percent(_money(balance), _money(revenue)), semaforo=color,
        inadimplencia_total=_money(debt_total), inadimplencia_quantidade=len(debts),
    )
