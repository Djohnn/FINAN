# ROTEIRO DE PROMPTS PARA CONSTRUÇÃO ASSISTIDA POR IA

Use um prompt por vez no seu assistente de IA (Cursor, Copilot, Claude ou ChatGPT) para construir o sistema de forma sólida:

---

## PROMPT 1: Setup Inicial, Models e Sistema de Backup no Pendrive
> "Leia os arquivos `.cursorrules`, `docs/PRD_CONTEXT.md` e `docs/DATABASE_SCHEMA.md`.
> 1. Crie os arquivos `models.py` completos para os 5 apps (`core_sistema`, `clientes_agenda`, `kanban_projetos`, `equipe`, `financeiro`).
> 2. Em `core_sistema/services.py`, implemente a função `executar_backup_pendrive()` usando `sqlite3.connect().backup()`, criando arquivos `backup_marcenaria_YYYY-MM-DD.sqlite3` na pasta configurada, limpando arquivos mais antigos que `dias_retencao_backup` e capturando erros caso o pendrive esteja desconectado.
> 3. Crie o management command `python manage.py realizar_backup`."

---

## PROMPT 2: Regras de Negócio e Gatilhos Automáticos (`services.py`)
> "Com base em `docs/PRD_CONTEXT.md`, crie os arquivos `services.py` para `kanban_projetos`, `clientes_agenda` e `equipe` usando `@transaction.atomic`:
> 1. `aprovar_orcamento_service()`: exige valor total, valor de entrada, forma de pagamento, data de início e entrega. Muda card para `3_APROVADO`, cria `LancamentoFinanceiro` PAGO para a entrada hoje e cria o(s) lançamento(s) PENDENTE(s) para o saldo restante.
> 2. `arquivar_orcamento_service()`: move card para `9_ARQUIVADO`, salva motivo e, se informado `dias_retorno`, agenda em `AgendaContato`.
> 3. `finalizar_projeto_service()`: muda card para `6_FINALIZADO`, grava `data_entrega_realizada=hoje` e cria automaticamente o `AgendaContato` de `POS_VENDA_30_DIAS` para `hoje + 30 dias`.
> 4. `concluir_pos_venda_service()`: valida obrigatoriamente se `feedback_cliente` tem pelo menos 10 caracteres e nota preenchida antes de marcar `realizado=True`.
> 5. `lancar_pagamento_funcionario_service()`: calcula valor (incluindo multiplicador de diárias) e gera saída na categoria `FUNCIONARIO`."

---

## PROMPT 3: Context Processor de Alertas + Layout Base (`base.html`)
> "1. Crie um `context_processors.py` em `core_sistema` que:
>    - Tenta rodar o backup diário silenciosamente se ainda não rodou hoje.
>    - Retorna alertas globais: se o pendrive de backup está desconectado (`ultimo_backup_sucesso=False`), quantos orçamentos estão vencendo hoje/atrasados, e a lista de ligações de Pós-Venda/Retorno pendentes (`realizado=False` e `data_agendada <= hoje`).
> 2. Crie o template `templates/base.html` usando TailwindCSS, HTMX e Alpine.js com menu simples (Kanban, Calendário, Financeiro/Fechamento, Equipe, Geladeira de Orçamentos, Backup) e barras de alerta fixas no topo para o Pendrive e para as Ligações de Pós-Venda pendentes."

---

## PROMPT 4: Quadro Kanban Interativo + Modais HTMX + WhatsApp
> "Crie as views, urls e templates do app `kanban_projetos`:
> 1. Quadro Kanban com SortableJS e HTMX mostrando cards com indicador de prazo de orçamento/entrega e botão direto do WhatsApp com mensagem dinâmica da etapa.
> 2. Ao mover para `3_APROVADO`, abrir Modal HTMX perguntando quanto o cliente deu de entrada, forma de pagamento, como pagará o restante e datas de início/entrega.
> 3. Modal HTMX de 'Arquivar Orçamento' e tela da 'Geladeira de Clientes' com botão 'Reativar para o Kanban'."

---

## PROMPT 5: Calendário FullCalendar + Fechamento Mensal ("Semáforo")
> "1. Crie a tela do Calendário (`clientes_agenda`) com FullCalendar.js exibindo os 4 eventos por cor (Início Azul, Entrega Verde, Pós-Venda Roxo, Retorno Laranja) e o Modal de Concluir Ligação que trava o botão de salvar até preencher o feedback do cliente.
> 2. Crie `financeiro/selectors.py` e a tela de Fechamento do Mês com o Semáforo Visual (Verde, Amarelo, Vermelho), detalhamento de Entradas por Pix/Cartão/Dinheiro, bloco exclusivo mostrando quanto custou cada funcionário no mês (% da receita) e saldo líquido final em linguagem simples para leigos."

> A configuração oficial é o modelo `ConfiguracaoSistema`, conforme `docs/DATABASE_SCHEMA.md`.
