# PRD & CONTEXTO MESTRE: Sistema de Gestão para Marcenaria (Local-First)

## 1. Visão Geral do Produto
Sistema web local para gerenciamento financeiro, operacional (Kanban) e comercial (Pós-venda e Orçamentos) de uma marcenaria. Deve rodar localmente no Windows e fazer backup diário automático em um pendrive configurado pelo usuário.

---

## 2. Módulos e Estrutura de Apps (Django)
O projeto deve conter 5 apps modulares dentro da pasta `apps/`:
1. `core_sistema`: Configurações locais, rotina de backup no pendrive, alertas globais no topo (`context_processors.py`).
2. `clientes_agenda`: Cadastro de clientes, Calendário Integrado (FullCalendar) e controle de Pós-Venda com trava de feedback.
3. `kanban_projetos`: Quadro Kanban de 6 etapas + Arquivo ("Geladeira") de orçamentos não fechados.
4. `equipe`: Cadastro de funcionários (Diária, Semanal, Quinzenal, Mensal) e lançamento simplificado de pagamentos.
5. `financeiro`: Contas a Pagar/Receber unificadas e Relatório de Fechamento do Mês ("Semáforo para Leigos").

---

## 3. Regras de Negócio Detalhadas

### REGRA 1: Fluxo do Kanban e Gatilhos Automáticos
As colunas do Kanban são:
- `1_CONTATO` (Novo Contato)
- `2_ORCAMENTO` (Em Orçamento)
- `3_APROVADO` (Aprovado / Aguardando Produção)
- `4_PRODUCAO` (Em Produção)
- `5_ENTREGA` (Pronto para Entrega)
- `6_FINALIZADO` (Entregue / Finalizado)
- `9_ARQUIVADO` (Fora do quadro principal - Aba "Geladeira / Potenciais Clientes")

**Gatilhos Obrigatórios por Coluna:**
* **Em Orçamento (`2_ORCAMENTO`):** Exige `data_limite_orcamento`. Se `hoje >= data_limite_orcamento`, exibe alerta visual vermelho no card e no topo do sistema.
* **Arquivar Orçamento (`9_ARQUIVADO`):** Botão "Não Fechou / Arquivar". Abre modal exigindo `motivo_arquivamento` (Achou caro, Adiou obra, Concorrente, Sem retorno) e opção de agendar lembrete de retorno no calendário (ex: +30 ou +60 dias). Pode ser reativado com 1 clique mantendo todo o histórico.
* **Aprovar Serviço (`3_APROVADO`):** Ao mover para Aprovado, interceptar e abrir Modal Obrigatório de Fechamento pedindo:
  1. `valor_total` do serviço.
  2. `valor_entrada` pago pelo cliente e `forma_pagamento_entrada` (PIX, CARTAO_CREDITO, CARTAO_DEBITO, DINHEIRO, BOLETO).
  3. Como será pago o `saldo_restante` (`valor_total - valor_entrada`) e quantas parcelas.
  4. `data_inicio_producao` e `data_entrega_prevista`.
  - **Ação no Banco:** Cria imediatamente um `LancamentoFinanceiro` (ENTRADA, status=PAGO, data_pagamento=hoje) referente à entrada, e cria o(s) lançamento(s) de `saldo_restante` (status=PENDENTE) com vencimento na data de entrega ou parcelas.
* **Finalizar Serviço (`6_FINALIZADO`):**
  - Registra `data_entrega_realizada = hoje`.
  - Verifica se há saldo pendente deste projeto e pergunta se o cliente quitou na entrega.
  - **Gatilho de Pós-Venda:** Cria automaticamente um registro em `AgendaContato` para `hoje + 30 dias` do tipo `POS_VENDA_30_DIAS`.

### REGRA 2: Integração WhatsApp (1 Clique)
- Não utilizar API paga. Criar método dinâmico no model `ProjetoKanban` que limpa os caracteres do telefone e gera URL `https://wa.me/55{whatsapp}?text={texto_url_encoded}` com mensagem personalizada para a etapa atual do card.

### REGRA 3: Calendário Integrado e Trava de Pós-Venda
1. O Calendário exibe eventos coloridos:
   - Azul (`#2563eb`): Início de Produção (`data_inicio_producao`)
   - Verde (`#16a34a`): Entrega Prevista (`data_entrega_prevista`)
   - Roxo (`#9333ea`): Ligação de Pós-Venda 30 dias (`AgendaContato`)
   - Laranja (`#ea580c`): Retorno de Orçamento Arquivado / Ligação Manual (`AgendaContato`)
2. **Alerta Fixo e Trava de Conclusão:**
   - Toda ligação agendada com `realizado=False` e `data_agendada <= hoje` gera um aviso fixo no topo do sistema (`base.html`).
   - O aviso NÃO pode ser fechado sem preencher o Modal de Conclusão de Pós-Venda.
   - O service `concluir_contato_pos_venda` deve bloquear a gravação se `feedback_cliente` tiver menos de 10 caracteres ou se `nivel_satisfacao` estiver vazio.

### REGRA 4: Gestão de Funcionários
- Cadastro com `periodicidade` (`DIARIA`, `SEMANAL`, `QUINZENAL`, `MENSAL`) e `valor_base`.
- Botão rápido para lançar pagamento (se for diarista, multiplica `dias_trabalhados * valor_base`).
- Gera saída financeira na categoria `FUNCIONARIO`, vinculada ao `funcionario_id`.

### REGRA 5: Fechamento do Mês ("Semáforo para Leigos")
Considera lançamentos com `status='PAGO'` dentro do mês/ano filtrado:
- `Total Entradas` (detalhado por Pix, Cartão, Dinheiro, Boleto).
- `Total Funcionários` (soma da categoria `FUNCIONARIO` + percentual que representa sobre as Entradas e listagem nominal de quanto cada funcionário custou no mês).
- `Outras Saídas` (Matéria-prima, contas fixas da oficina).
- `Saldo Final` = `Total Entradas - (Total Funcionários + Outras Saídas)`.
- **Lógica do Semáforo:**
  - `VERDE`: `Saldo Final > 0` e margem líquida `>= 15%`.
  - `AMARELO`: `Saldo Final >= 0` e margem líquida `< 15%` (ou se houver inadimplência no mês).
  - `VERMELHO`: `Saldo Final < 0` (Prejuízo).

### REGRA 6: Backup Automático no Pendrive (Anti-Falha de SSD)
- Model `ConfiguracaoSistema` guarda `caminho_backup_pendrive` (ex: `E:\Backups_Marcenaria`), `ultimo_backup_em`, `ultimo_backup_sucesso` e `mensagem_erro_backup`, conforme `DATABASE_SCHEMA.md`.
- Rotina diária usa `sqlite3.connect().backup()` salvando `backup_marcenaria_YYYY-MM-DD.sqlite3` e apagando arquivos com mais de 30 dias.
- Se o caminho do pendrive não existir no momento do backup (pendrive desconectado), exibir alerta vermelho urgente no topo do `base.html`: "PENDRIVE DE BACKUP DESCONECTADO! Conecte o pendrive para proteger os dados de hoje."

> Referência oficial de configuração: `ConfiguracaoSistema`, com `caminho_backup_pendrive`, `dias_retencao_backup`, `ultimo_backup_em`, `ultimo_backup_sucesso` e `mensagem_erro_backup`, conforme `DATABASE_SCHEMA.md`.
