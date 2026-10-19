from django.contrib import admin
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
