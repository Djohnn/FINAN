from django.contrib import admin, messages
from django.contrib.admin.actions import delete_selected as django_delete_selected
from django.core.exceptions import ValidationError
from django.http import HttpResponseRedirect

from .models import LancamentoFinanceiro


@admin.register(LancamentoFinanceiro)
class LancamentoFinanceiroAdmin(admin.ModelAdmin):
    list_display = (
        'descricao',
        'tipo',
        'categoria',
        'valor',
        'forma_pagamento',
        'status',
        'data_vencimento',
        'data_pagamento',
    )
    list_filter = (
        'tipo',
        'categoria',
        'status',
        'forma_pagamento',
        'data_vencimento',
    )
    search_fields = (
        'descricao',
        'projeto__titulo_servico',
        'funcionario__nome',
    )
    date_hierarchy = 'data_vencimento'
    actions = ('delete_selected',)

    def get_exclude(self, request, obj=None):
        exclude = list(super().get_exclude(request, obj) or ())
        if obj is None:
            exclude.extend(('recorrencia', 'competencia'))
        return tuple(dict.fromkeys(exclude))

    def get_readonly_fields(self, request, obj=None):
        readonly_fields = list(super().get_readonly_fields(request, obj))
        if obj is not None and obj.recorrencia_id is not None:
            readonly_fields.extend(('recorrencia', 'competencia'))
            readonly_fields.extend(('tipo', 'projeto', 'funcionario'))
        return tuple(dict.fromkeys(readonly_fields))

    @staticmethod
    def _ensure_identity_unchanged(obj):
        if not obj.pk:
            return
        persisted = LancamentoFinanceiro.objects.filter(pk=obj.pk).values(
            'recorrencia_id',
            'competencia',
        ).first()
        if persisted and (
            persisted['recorrencia_id'] != obj.recorrencia_id
            or persisted['competencia'] != obj.competencia
        ):
            raise ValidationError(
                'A identidade de recorrência e competência não pode ser alterada.'
            )

    @staticmethod
    def _ensure_recurring_structure_unchanged(obj):
        if not obj.pk or obj.recorrencia_id is None:
            return
        persisted = LancamentoFinanceiro.objects.filter(pk=obj.pk).values(
            'tipo',
            'projeto_id',
            'funcionario_id',
        ).first()
        current = {
            'tipo': obj.tipo,
            'projeto_id': obj.projeto_id,
            'funcionario_id': obj.funcionario_id,
        }
        if persisted and any(
            persisted[field_name] != current[field_name]
            for field_name in ('tipo', 'projeto_id', 'funcionario_id')
        ):
            raise ValidationError(
                'Tipo, projeto e funcionário são imutáveis em lançamentos recorrentes.'
            )

    def save_model(self, request, obj, form, change):
        if not obj.pk and obj.recorrencia_id is not None:
            raise ValidationError(
                'A criação manual de lançamentos recorrentes não é permitida.'
            )
        self._ensure_identity_unchanged(obj)
        self._ensure_recurring_structure_unchanged(obj)
        super().save_model(request, obj, form, change)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.recorrencia_id is not None:
            return False
        return super().has_delete_permission(request, obj)

    def delete_model(self, request, obj):
        if obj.recorrencia_id is not None:
            raise ValidationError(
                'Lançamentos recorrentes não podem ser excluídos.'
            )
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        if queryset.filter(recorrencia_id__isnull=False).exists():
            raise ValidationError(
                'A seleção contém lançamento recorrente e não pode ser excluída.'
            )
        super().delete_queryset(request, queryset)

    @admin.action(description='Excluir lançamentos selecionados')
    def delete_selected(self, request, queryset):
        if queryset.filter(recorrencia_id__isnull=False).exists():
            self.message_user(
                request,
                'A seleção contém lançamento recorrente e não pode ser excluída.',
                messages.ERROR,
            )
            return HttpResponseRedirect(request.get_full_path())
        return django_delete_selected(self, request, queryset)
