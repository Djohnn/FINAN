from django.contrib import admin
from .models import Funcionario


@admin.register(Funcionario)
class FuncionarioAdmin(admin.ModelAdmin):
    list_display = (
        'nome',
        'funcao',
        'periodicidade',
        'valor_base',
        'whatsapp',
        'ativo',
    )
    list_filter = ('ativo', 'periodicidade', 'funcao')
    search_fields = ('nome', 'funcao', 'chave_pix', 'whatsapp')
