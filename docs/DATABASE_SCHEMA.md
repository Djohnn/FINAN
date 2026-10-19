# ESPECIFICAÇÃO TÉCNICA DO BANCO DE DADOS (MODELS.PY)

Use esta referência exata de campos para gerar as migrations sem erros:

## 1. App `core_sistema`
### Model: `ConfiguracaoSistema` (Singleton)
- `nome_marcenaria`: CharField(max_length=100, default="Minha Marcenaria")
- `caminho_backup_pendrive`: CharField(max_length=255, default="E:\\Backups_Marcenaria")
- `dias_retencao_backup`: PositiveIntegerField(default=30)
- `ultimo_backup_em`: DateTimeField(null=True, blank=True)
- `ultimo_backup_sucesso`: BooleanField(default=False)
- `mensagem_erro_backup`: CharField(max_length=255, blank=True)

---

## 2. App `clientes_agenda`
### Model: `Cliente`
- `nome`: CharField(max_length=150)
- `whatsapp`: CharField(max_length=20)
- `endereco`: TextField(blank=True)
- `observacoes`: TextField(blank=True)
- `criado_em`: DateTimeField(auto_now_add=True)

### Model: `AgendaContato`
- `cliente`: ForeignKey(Cliente, on_delete=CASCADE, related_name="agendamentos")
- `projeto`: ForeignKey('kanban_projetos.ProjetoKanban', on_delete=SET_NULL, null=True, blank=True)
- `tipo`: CharField(choices=['POS_VENDA_30_DIAS', 'RETORNO_ORCAMENTO', 'LIGACAO_MANUAL'])
- `data_agendada`: DateField(db_index=True)
- `realizado`: BooleanField(default=False, db_index=True)
- `nivel_satisfacao`: CharField(choices=['SATISFEITO', 'AJUSTE_SOLICITADO', 'INSATISFEITO'], blank=True)
- `feedback_cliente`: TextField(blank=True)
- `realizado_em`: DateTimeField(null=True, blank=True)

---

## 3. App `kanban_projetos`
### Model: `ProjetoKanban`
- `cliente`: ForeignKey('clientes_agenda.Cliente', on_delete=CASCADE, related_name="projetos")
- `titulo_servico`: CharField(max_length=200) # Ex: Armário Cozinha Planejado
- `descricao_medidas`: TextField(blank=True)
- `etapa`: CharField(choices=['1_CONTATO', '2_ORCAMENTO', '3_APROVADO', '4_PRODUCAO', '5_ENTREGA', '6_FINALIZADO', '9_ARQUIVADO'], default='1_CONTATO', db_index=True)
- `data_limite_orcamento`: DateField(null=True, blank=True)
- `data_inicio_producao`: DateField(null=True, blank=True)
- `data_entrega_prevista`: DateField(null=True, blank=True)
- `data_entrega_realizada`: DateField(null=True, blank=True)
- `valor_total`: DecimalField(max_digits=10, decimal_places=2, default=0)
- `valor_entrada`: DecimalField(max_digits=10, decimal_places=2, default=0)
- `saldo_restante`: DecimalField(max_digits=10, decimal_places=2, default=0)
- `motivo_arquivamento`: CharField(choices=['PRECO_ALTO', 'ADIOU_OBRA', 'FECHOU_CONCORRENTE', 'SEM_RETORNO', 'OUTRO'], blank=True)
- `observacao_arquivamento`: TextField(blank=True)
- `criado_em`: DateTimeField(auto_now_add=True)
- `atualizado_em`: DateTimeField(auto_now=True)

---

## 4. App `equipe`
### Model: `Funcionario`
- `nome`: CharField(max_length=150)
- `funcao`: CharField(max_length=80) # Ex: Marceneiro, Montador, Ajudante
- `whatsapp`: CharField(max_length=20, blank=True)
- `chave_pix`: CharField(max_length=120, blank=True)
- `periodicidade`: CharField(choices=['DIARIA', 'SEMANAL', 'QUINZENAL', 'MENSAL'])
- `valor_base`: DecimalField(max_digits=10, decimal_places=2)
- `ativo`: BooleanField(default=True)

---

## 5. App `financeiro`
### Model: `LancamentoFinanceiro`
- `tipo`: CharField(choices=['ENTRADA', 'SAIDA'], db_index=True)
- `categoria`: CharField(choices=['SERVICO_CLIENTE', 'FUNCIONARIO', 'MATERIA_PRIMA', 'CUSTO_FIXO_OFICINA', 'OUTROS'], db_index=True)
- `projeto`: ForeignKey('kanban_projetos.ProjetoKanban', on_delete=SET_NULL, null=True, blank=True, related_name="lancamentos")
- `funcionario`: ForeignKey('equipe.Funcionario', on_delete=SET_NULL, null=True, blank=True, related_name="pagamentos")
- `descricao`: CharField(max_length=200)
- `valor`: DecimalField(max_digits=10, decimal_places=2)
- `forma_pagamento`: CharField(choices=['PIX', 'CARTAO_CREDITO', 'CARTAO_DEBITO', 'DINHEIRO', 'BOLETO'], default='PIX')
- `data_vencimento`: DateField(db_index=True)
- `data_pagamento`: DateField(null=True, blank=True, db_index=True)
- `status`: CharField(choices=['PENDENTE', 'PAGO', 'CANCELADO'], default='PENDENTE', db_index=True)
