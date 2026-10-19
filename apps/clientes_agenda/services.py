from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import AgendaContato


@transaction.atomic
def concluir_pos_venda_service(
    agenda_id: int,
    feedback_cliente: str,
    nivel_satisfacao: str = 'SATISFEITO',
) -> AgendaContato:
    """
    Conclui um contato de pós-venda na agenda com trava de segurança obrigatória:
    - O feedback deve conter no mínimo 10 caracteres úteis (sem espaços).
    - O nível de satisfação é obrigatório.
    """
    agenda = AgendaContato.objects.select_for_update().get(id=agenda_id)

    texto_util = "".join((feedback_cliente or "").split())
    if len(texto_util) < 10:
        raise ValidationError({
            'feedback_cliente': "O feedback do cliente deve conter no mínimo 10 caracteres úteis (sem contar espaços)."
        })

    if not nivel_satisfacao or not str(nivel_satisfacao).strip():
        raise ValidationError({
            'nivel_satisfacao': "O nível de satisfação é obrigatório para concluir o pós-venda."
        })

    agenda.realizado = True
    agenda.realizado_em = timezone.now()
    agenda.feedback_cliente = feedback_cliente.strip()
    agenda.nivel_satisfacao = str(nivel_satisfacao).strip()
    agenda.save()

    return agenda


# Alias de compatibilidade com PRD
concluir_contato_pos_venda = concluir_pos_venda_service
