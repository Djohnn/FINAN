from .models import DominioEventoSistema, EventoSistema


def _validate_limit(limit: int) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValueError('limit deve ser um inteiro.')
    if limit <= 0 or limit > 100:
        raise ValueError('limit deve estar entre 1 e 100.')
    return limit


def _validate_domain(dominio: str | None) -> str:
    valid_domains = {value for value, _label in DominioEventoSistema.choices}
    if dominio not in valid_domains:
        raise ValueError('dominio inválido.')
    return dominio


def eventos_recentes(limit: int = 50, dominio: str | None = None):
    limit = _validate_limit(limit)
    queryset = EventoSistema.objects.all()
    if dominio is not None:
        queryset = queryset.filter(dominio=_validate_domain(dominio))
    return queryset.order_by('-criado_em', '-id')[:limit]


def historico_entidade(
    dominio: str,
    entidade_tipo: str,
    entidade_id: str,
    limit: int = 50,
):
    limit = _validate_limit(limit)
    dominio = _validate_domain(dominio)
    if not isinstance(entidade_tipo, str) or not entidade_tipo.strip():
        raise ValueError('entidade_tipo não pode ser vazio.')
    if not isinstance(entidade_id, str) or not entidade_id.strip():
        raise ValueError('entidade_id não pode ser vazio.')
    return EventoSistema.objects.filter(
        dominio=dominio,
        entidade_tipo=entidade_tipo,
        entidade_id=entidade_id,
    ).order_by('-criado_em', '-id')[:limit]
