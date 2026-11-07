# FINANPE — PRD MESTRE V1+ E CHECKLIST DE EXECUÇÃO

**Tipo:** Product Requirements Document (PRD) consolidado e rastreável  
**Versão:** 1.0 — inventário de 06/11/2026 (America/Sao_Paulo)  
**Produto:** FinanPE — gestão financeira, comercial e operacional de marcenaria  
**Responsável por decisões de produto e aceite:** Founder  
**Coordenação:** Coordenador FinanPE  
**Natureza do documento:** PRD consolidado para avaliação do Founder; **não é uma autorização de implementação, publicação ou promoção**, nem substitui o checkpoint canônico.  
**Status editorial:** RASCUNHO CONSOLIDADO — aprovação deste novo documento ainda não registrada.

> **Importante:** esta versão reúne requisitos e estado da implementação; não reescreve silenciosamente o `PRD_CONTEXT.md` original nem `docs/PROJECT_STATE.md`. O último é escrito exclusivamente pelo Agente 012. Antes de integrar o PRD ao GitHub, validar o conteúdo e autorizar a publicação pela governança do projeto.

---

## 1. Como ler e atualizar o checklist

Usar **exatamente** a notação operacional solicitada:

- **`[ X ]` — CONCLUÍDO:** entrega identificada, implementada e integrada no *destino expressamente indicado*. Quando o destino for somente `main-validation`, isso será informado; **não** equivale a release em `main`.
- **`[ ... ]` — EM ANDAMENTO:** existe trabalho parcial, candidato local, validação/auditoria pendente, protótipo em elaboração ou implementação ainda incompleta.
- **`[   ]` — NÃO IMPLEMENTADO:** sem código funcional correspondente no `main`/`main-validation` no inventário; pode haver requisito, especificação ou proposta documental. Não confundir *contrato aprovado* com *código pronto*.

**Regras de manutenção:**

1. Cada subetapa concluída deve receber `[ X ]`, com evidência de código, auditoria e branch. Uma fase-mãe permanece `[ ... ]` enquanto tiver entregas essenciais pendentes.
2. Quando o escopo de uma fase é especificamente **backend** e está integrado, o backend pode receber `[ X ]`; a interface correspondente deve aparecer como uma subetapa separada `[   ]`.
3. Nunca alterar um item para `[ X ]` apenas porque um implementador informou `PASS`. Exigir os gates aplicáveis (`TECHNICAL_PASS`, auditor independente, validação do Coordenador, integração e, para interface/release, aprovação do Founder).
4. Registrar **data, SHA, branch e evidência** em cada alteração de status. Se houver dúvida, preservar `[ ... ]` ou `[   ]` e anotar `NOT_VERIFIED`.
5. `main-validation` é integração intermediária; `main` recebe apenas o SHA exato aprovado no FinanQA pelo Founder.
6. Não editar `docs/PROJECT_STATE.md` neste fluxo. Somente `FINANPE-CHECKPOINT-SCHEDULER-012` mantém o checkpoint canônico.

**Tipos de aprovação:** `CONTRATO_APROVADO`, `PROTÓTIPO_APROVADO`, `CÓDIGO_IMPLEMENTADO`, `AUDITORIA_PASS`, `INTEGRADO_MAIN_VALIDATION`, `FOUNDER_LIVE_QA_PASS`, `PROMOVIDO_MAIN`. Esses estados nunca são intercambiáveis.

---

## 2. Visão, público e princípios de produto

**Problema:** administrar em uma única ferramenta local o atendimento de clientes, projetos, cobranças, pagamentos, resultados e pós-venda de uma marcenaria, evitando perda de dados e decisões financeiras baseadas em informação incompleta.

**Usuário primário:** proprietário/gestor de uma marcenaria, em operação local Windows com um único usuário de negócio na V1.

**Proposta de valor:** transformar cadastro e lançamentos em ações claras — quem contatar, o que cobrar, quanto cada projeto rende, quais custos vencem, quando entregar e quando realizar backup.

### 2.1 Premissas e decisões já definidas

- [ X ] V1 `SINGLE_TENANT_LOCAL_SINGLE_USER`, aplicação Django e SQLite local.
- [ X ] V1 sem login obrigatório, sem camada multiusuário, sem PostgreSQL/RLS preventivo.
- [ X ] Organização modular nos apps `core_sistema`, `clientes_agenda`, `kanban_projetos`, `equipe`, `financeiro`.
- [ X ] Regras de negócio mutáveis em services; selectors e dashboards de leitura sem efeitos colaterais.
- [ X ] Integridade monetária com `Decimal`, validação e proteção dos lançamentos.
- [ X ] Protocolo de trabalho por SHA exato, worktree isolada, revisão independente e checkpoint exclusivo do Agente 012 documentado.
- [   ] Evolução futura multiusuário, permissões, nuvem/SaaS, PostgreSQL e RLS — fora da V1 atual, dependente de decisão específica.

### 2.2 Gates obrigatórios para novas interfaces e releases

- [ X ] Regra normativa: protótipo visual antes de qualquer frontend novo ou alteração visual relevante.
- [ X ] Regra normativa: aprovação visual explícita do Founder, comparação tela implementada vs. protótipo e auditoria.
- [ X ] Regra normativa: `main-validation` antes de `main`, FinanQA Django real na porta local `5500` com banco descartável separado do banco real.
- [   ] Gates de QA da **Fase 7 completa** — ainda não realizados para o módulo completo.
- [   ] Autorização de promoção da **Fase 7** para `main` — ainda não concedida.

---

## 3. Estado congelado desta revisão (fotografia, não promessa de tempo real)

| Identificador | Evidência / valor | Interpretação |
|---|---|---|
| Repositório | `Djohnn/FINAN` | Confirmado pelo conector GitHub |
| `main` | `ba210df99e6f1fd5c25b5c7f131f1703764e1b92` | Release existente das fases anteriores |
| `main-validation` | `6d4decb04cd1ed10940c4bfdb7a4f874104bee13` | Estrutura 7A, gerador 7B e decisões das bordas |
| Checkpoint remoto | `PSC-2026-11-04-047` | Último checkpoint visível nesta revisão |
| 7A integrado | `56277f0ee3cc682eecb32f4113a78dcec0c409cf` | Integrado apenas em `main-validation` |
| 7B integrado | `863b5a3895f2b029ebc342c48248ac9c97cd645f` | Integrado apenas em `main-validation` |
| Correção de bordas, candidato local | `3cb55b8324846449e6f18733452b22ab039261d5` | Implementação reportada; auditoria anterior teve `BLOCKED` ambiental |
| Remediação de dois testes, candidato local | `3bbcceb403d8f4aabd30efd43f581f4ffae29ce7` | **Agente 199-R1 em reauditoria**; não publicado |
| Testes registrados no checkpoint remoto | `701 PASS` | Baseline **reportado/documentado**, não reexecutado nesta revisão |
| Testes do candidato local | `709 PASS` | Reportados pelo implementador, ainda aguardam reauditoria do Agente 199 |

**Referências históricas da revisão documental:**

```text
MAIN_VALIDATION_HEAD_SHA=6d4decb04cd1ed10940c4bfdb7a4f874104bee13
MAIN_VALIDATION_PRODUCT_SHA=863b5a3895f2b029ebc342c48248ac9c97cd645f
```

`MAIN_VALIDATION_HEAD_SHA` é o HEAD histórico de `main-validation` e inclui checkpoints documentais posteriores. `MAIN_VALIDATION_PRODUCT_SHA` corresponde ao gerador 7B integrado. Ambos são referências históricas desta revisão; nenhum representa promoção da Fase 7 para `main`.

**Limites de evidência:** a revisão confirmou arquivos, código, rotas, estrutura de commits e documentação remotos. Não executou o aplicativo no Windows, não inspecionou banco real e não presume que candidatos locais tenham sido enviados ao GitHub.

---

## 4. Painel executivo de fases

| Fase / frente | Checklist | Contrato / decisão | Evidência de implementação | Situação de entrega |
|---|---|---|---|---|
| 0. Integridade e funcionários | `[ X ]` | Aprovado | Services + testes | Núcleo integrado em `main`; tela de equipe pendente como extensão |
| 1. Backup e restauração | `[ X ]` | Aprovado | Services, comandos e scripts Windows | Código integrado em `main`; interface amigável é pendência separada |
| 2. Histórico de ações | `[ X ]` | Aprovado | `EventoSistema` e eventos | Núcleo integrado em `main`; painel próprio é extensão não entregue |
| 3. Fechamento mensal | `[ X ]` | Aprovado | Selector e testes | **Backend** concluído em `main`; **tela** ainda pendente |
| 4. Central de contas a receber | `[ X ]` | Aprovado | Selector, view, HTML/CSS/JS | Consulta operacional integrada em `main`; não é tela de quitação |
| 5. Rentabilidade por projeto | `[ X ]` | Aprovado | Selectors, serviço da equipe, views e templates | 5A, 5B, 5C integradas em `main` |
| 6. Cliente 360° | `[ X ]` | Aprovado | Selector, views, HTML/CSS/JS | Visão integrada em `main` |
| 7. Despesas recorrentes | `[ ... ]` | `REC-V1-01..07` e três políticas de borda aprovadas | 7A/7B integradas em `main-validation`; correções locais em reauditoria | Sem frontend/scheduler ou promoção para `main` |
| 8. Orçamento/proposta | `[   ]` | Escopo aprovado no roadmap; decisões específicas pendentes | Sem gerador de proposta/PDF no código | Não implementado |
| 9. Exportação Excel/contador | `[   ]` | Direção de produto aprovada no roadmap | Sem exportador operacional encontrado | Não implementado |
| 10. Tela operacional “Hoje” | `[   ]` | Direção de produto aprovada no roadmap | Sem view/template próprio encontrado | Não implementado |
| Extensão documental — contratos/adendos | `[   ]` | Proposta funcional documental **não aprovada visualmente** | Sem models, services, views ou PDF próprios | Não implementada |
| Completar a interface do núcleo legado | `[ ... ]` | PRD original contém requisitos de UX | Backend e componentes parciais | Backlog transversal; detalhado na seção 16 |

> Um `[ X ]` de fase histórica significa **escopo que foi implementado e integrado**. Itens adicionais de interface não entregues continuam desmarcados nas seções próprias, sem reabrir falsamente a auditoria do backend já fechado.

---

## 5. Fase 0 — Núcleo financeiro, integridade e equipe `[ X ]`

**Objetivo:** garantir consistência financeira, impedir pagamentos duplicados e vincular despesas de funcionários ao ledger.

**Contrato:** aprovado e integrado.

### Checklist de entrega

- [ X ] Model `Funcionario` com periodicidades diária, semanal, quinzenal e mensal e valor-base.
- [ X ] Model `LancamentoFinanceiro` com entrada/saída, status, valor, datas, forma de pagamento e vínculos opcionais.
- [ X ] Cadastro técnico de funcionários pelo Django Admin.
- [ X ] Service `lancar_pagamento_funcionario_service()`; cálculo conforme periodicidade/dias aplicáveis.
- [ X ] Tratamento de retry/idempotência de pagamentos de funcionários conforme decisões 1A/2A/3A.
- [ X ] Registro de saída financeira com vínculo ao funcionário, sem inferir dados por texto livre.
- [ X ] Validações monetárias, de integridade e testes automatizados do núcleo.
- [ X ] Atribuição **opcional** ao projeto na fase 5B, mantendo custo geral quando omitida.
- [   ] Tela dedicada de equipe e botão rápido de lançamento de pagamento fora do Admin.

**Evidência:** `apps/equipe/models.py`, `apps/equipe/services.py`, `apps/equipe/admin.py`, `apps/financeiro/models.py`, testes de integridade financeira e de pagamentos.

**Critério para marcar a extensão da tela com `[ X ]`:** protótipo aprovado, ações de pagamento seguras, testes, auditoria e integração, mantendo o service atual como fonte de verdade.

---

## 6. Fase 1 — Backup e restauração segura `[ X ]`

**Objetivo:** proteger o SQLite local de perda por falha de disco, pendrive desconectado ou corrupção, com recuperação controlada.

**Contrato:** aprovado e integrado; restauração `CLOSED_INTEGRATED`.

### Checklist

- [ X ] `ConfiguracaoSistema` com caminho do backup, retenção, data e resultado da última operação.
- [ X ] Rotina de backup para pendrive, com cópia SQLite, tratamento de falhas e integridade.
- [ X ] Comandos Django `realizar_backup` e `restaurar_backup`.
- [ X ] Restauração segura com validação prévia, bloqueios de risco, cópia verificada e tratamento de rollback.
- [ X ] Scripts Windows de inicialização, backup e instalação da tarefa de backup.
- [ X ] Proteções/testes para banco ausente, falhas de disco, concorrência, restauração e integridade.
- [ X ] Registro documental de backup operacional na instalação histórica auditada.
- [   ] Tela dedicada para configurar backup, visualizar detalhes e iniciar restauração guiada sem usar Admin/terminal.
- [   ] Verificação operacional **atual** da tarefa Windows/pendrive nesta data (não executada neste levantamento).

**Evidência:** `apps/core_sistema/services.py`, `apps/core_sistema/management/commands/`, `scripts_windows/`, `tests/test_backup_automation.py`, `tests/test_backup_restoration.py`.

---

## 7. Fase 2 — Histórico de ações importantes `[ X ]`

**Objetivo:** rastrear eventos de negócio que mudam a situação dos projetos e das finanças.

### Checklist

- [ X ] Model `EventoSistema` e migration correspondente.
- [ X ] Emissão de eventos em aprovação, arquivamento, reativação, finalização, pagamento, pós-venda, backup e restauração conforme o escopo V1.
- [ X ] Administração técnica do histórico em modo somente leitura no Django Admin.
- [ X ] Integração de eventos relevantes à leitura do Cliente 360°.
- [ X ] Proteção contra eventos duplicados em retries compatíveis e testes de auditoria.
- [   ] Painel operacional autônomo de histórico, com busca e filtros próprios além do Admin/Cliente 360°.

**Evidência:** `apps/core_sistema/models.py`, `apps/core_sistema/services.py`, `apps/core_sistema/admin.py`, testes do histórico.

---

## 8. Fase 3 — Fechamento mensal / semáforo `[ X ]` (backend)

**Objetivo:** responder de forma simples se o mês foi lucrativo, equilibrado ou deficitário.

### Checklist do núcleo aprovado

- [ X ] Selector `fechamento_mensal(*, ano, mes)` com datas determinísticas.
- [ X ] Total de entradas realizadas por forma de pagamento.
- [ X ] Total e detalhamento de despesas com funcionários, outras saídas e saldo.
- [ X ] Margem e semáforo VERDE/AMARELO/VERMELHO conforme decisões integradas.
- [ X ] Inadimplência e integridade de valores considerando o estado correto do ledger.
- [ X ] Consultas somente leitura, integridade monetária e testes de casos-limite.
- [   ] Tela própria do fechamento mensal com seletor mês/ano, cards, tabelas, explicação simples e semáforo visual.
- [   ] Acesso à tela pelo menu principal quando implementada.

**Evidência:** `apps/financeiro/selectors.py` (`fechamento_mensal`), `tests/test_monthly_closing.py`. Não existe rota própria do fechamento em `apps/financeiro/urls.py` na fotografia atual.

---

## 9. Fase 4 — Central de contas a receber `[ X ]`

**Objetivo:** oferecer uma fila de cobrança para valores pendentes.

### Checklist

- [ X ] Contrato de leitura `LancamentoFinanceiro` com `tipo=ENTRADA` e `status=PENDENTE`.
- [ X ] Selector `central_contas_receber(*, data_referencia)`.
- [ X ] Indicadores: total a receber, total vencido, clientes em atraso, maior atraso em dias.
- [ X ] Classificação de atrasadas, hoje, próximos sete dias e próximos trinta dias.
- [ X ] Exibição controlada de lançamentos não vinculados ou legados de valor zero.
- [ X ] Protótipo e aprovação visual registrados no checkpoint.
- [ X ] Template, CSS, JavaScript e rota `/financeiro/contas-a-receber/`.
- [ X ] Filtros por busca, cliente, projeto e período.
- [ X ] Ação de WhatsApp condicionada ao clique explícito, sem envio externo automático.
- [ X ] Testes de leitura, integridade, privacidade e interface registrados.
- [   ] Quitação, alteração de vencimento ou cancelamento **pela própria Central**, caso o Founder decida expandir o contrato — **não pertencem ao escopo read-only já entregue**.

**Evidência:** `apps/financeiro/selectors.py`, `apps/financeiro/views.py`, `templates/financeiro/central_contas_receber.html`, `static/financeiro/central_ar.*`, testes `test_central_contas_receber*`.

---

## 10. Fase 5 — Lucro/margem por projeto `[ X ]`

**Objetivo:** responder “quanto este projeto efetivamente rendeu?” sem alocar custos gerais arbitrariamente.

### Checklist

- [ X ] **5A** — Selector/read model por projeto: contratado, recebido, a receber, custos diretos, lucro, margem e caixa realizado.
- [ X ] **5B** — Vínculo opcional do pagamento de funcionário ao projeto; ausência de projeto mantém custo geral.
- [ X ] **5C** — Protótipo aprovado e frontend de visão geral e detalhe de rentabilidade.
- [ X ] Segregação entre resultado econômico e caixa realizado.
- [ X ] Proteção contra divisão por zero, vazamento de custos entre projetos e rateio implícito.
- [ X ] Rotas `/financeiro/rentabilidade-projetos/` e `/financeiro/rentabilidade-projetos/<id>/`.
- [ X ] Auditorias/integração da fase registradas no checkpoint.

**Evidência:** `apps/financeiro/selectors.py`, `apps/equipe/services.py`, `apps/financeiro/views.py`, templates de rentabilidade e testes `test_project_profitability*`.

---

## 11. Fase 6 — Cliente 360° `[ X ]`

**Objetivo:** transformar o cadastro do cliente em memória comercial centralizada.

### Checklist

- [ X ] Relação estruturada de cliente, projetos, contatos e financeiro.
- [ X ] Selector de índice de clientes com pesquisa.
- [ X ] Selector `cliente_360()` com projetos, financeiro, agenda, histórico e contatos.
- [ X ] Visualização do cliente e listagem em templates reais.
- [ X ] Histórico paginado e correções de navegação/compatibilidade HTTP.
- [ X ] CSS/JS dedicados e correções mobile.
- [ X ] Ações contextualizadas de WhatsApp conforme restrições de privacidade.
- [ X ] Testes e encerramento da Fase 6 registrados no checkpoint.
- [   ] Criação/edição de clientes e contatos por uma **experiência integral fora do Admin**, como extensão de UX; a visualização 360° já existe.

**Evidência:** `apps/clientes_agenda/selectors.py`, `views.py`, templates `clientes.html`/`cliente_360.html`, assets e `tests/test_customer360.py`.

---

## 12. Fase 7 — Despesas recorrentes `[ ... ]`

**Objetivo:** reduzir esquecimentos de aluguel, energia, internet, contador, manutenção, assinaturas e outras despesas previsíveis.

**Status de contrato:** `REC-V1-01..07` aprovados; três decisões complementares de casos-limite aprovadas no PSC-047.

### 12.1 Escopo funcional aprovado

- [ X ] Contrato para despesa recorrente com descrição, categoria, valor, forma, dia de vencimento, início, fim opcional, ativo e observações.
- [ X ] Contrato: uma recorrência produz no máximo um lançamento por competência.
- [ X ] Contrato: cálculo do vencimento com *clamp* ao último dia do mês.
- [ X ] Contrato: mês atual gerado imediatamente na criação quando elegível.
- [ X ] Contrato: sem backfill automático, sem alocação automática de projeto/funcionário.
- [ X ] Contrato: meses já gerados são snapshots históricos, inclusive PENDENTE, PAGO e CANCELADO.
- [ X ] Decisão: se vencimento do mês inicial anteceder `data_inicio`, **não gerar** a competência inicial.
- [ X ] Decisão: mês final elegível apenas se vencimento calculado for menor ou igual a `data_fim`.
- [ X ] Decisão: mudança na recorrência não altera lançamentos existentes.

### 12.2 Entregas de backend

- [ X ] **7A — Model `DespesaRecorrente` e vínculos no ledger**, migrations e unicidade recorrência/competência; integrado em `main-validation` (`56277f0`).
- [ X ] **7B — Gerador mensal transacional**, `get_or_create`, idempotência, mês atual e *clamp*; integrado em `main-validation` (`863b5a3`).
- [ X ] Services de criação e geração mensal existentes em `apps/financeiro/services.py` na validação.
- [ X ] **Implementação local das políticas de borda** pelo Agente 198 no candidato `3cb55b8` (status **implementado localmente, não integrado**).
- [ X ] **Dois testes adicionais** locais pelo Agente 198-R1 no candidato `3bbcceb` (status **implementado localmente, não integrado**).
- [ ... ] Auditoria independente 199-R1 do SHA `3bbcceb403d8f4aabd30efd43f581f4ffae29ce7` (relatório final ainda não recebido nesta revisão).
- [   ] Validação final do Coordenador sobre o relatório independente da 199-R1.
- [   ] Autorização explícita do Founder para integrar candidato exato a `main-validation`.
- [   ] Integração controlada e verificação pós-publicação em `main-validation`.
- [   ] Checkpoint complementar pelo Agente 012, após evidência da integração.

**Nota sobre os itens locais `[ X ]`:** o `X` indica que os arquivos **foram produzidos e commitados localmente segundo os relatórios recebidos**. Não equivale a `AUDIT_PASS`, `INTEGRADO_MAIN_VALIDATION` ou `PROMOVIDO_MAIN`. A fase-mãe permanece `[ ... ]`.

### 12.3 Interface operacional da recorrência

- [   ] Levantamento dos fluxos de criar, editar, ativar, desativar, listar e visualizar despesas recorrentes.
- [   ] Protótipo visual da gestão de despesas recorrentes.
- [   ] Aprovação visual explícita do Founder.
- [   ] Frontend Django e integração aos services aprovados.
- [   ] Testes de acessibilidade, validação, idempotência e segurança em operações POST/GET.
- [   ] Comparação tela real versus protótipo e auditoria independente.

### 12.4 Automação, QA e release

- [ X ] Rotina de serviço que processa as recorrências ativas do mês atual.
- [   ] Invocador/agendamento Windows específico da Fase 7; **instalação não autorizada e não realizada**.
- [   ] Contrato técnico para invocação da rotina sem gerar efeitos colaterais no GET.
- [   ] Integração backend + frontend + automação em `main-validation`, quando autorizada.
- [   ] FinanQA da Fase 7 completa usando banco descartável e SHA exato.
- [   ] `FOUNDER_LIVE_QA_PASS` da Fase 7 completa.
- [   ] `FOUNDER_PROMOTION_APPROVAL` da Fase 7 completa.
- [   ] Promoção estrita, sem force-push, para `main` e checkpoint final.

**Critérios de aceite:** nenhuma duplicação, nenhum backfill, idempotência, sem reescrita automática do histórico, datas de início/fim respeitadas, tests/auditoria PASS, tela fiel ao protótipo, tarefa Windows segura quando autorizada, FinanQA e promoção aprovados.

**Evidência:** `apps/financeiro/models.py`, migrations `0002`/`0003`, `apps/financeiro/services.py`, testes `test_phase7_slice7a.py` e `test_phase7_slice7b.py`, PSC-046 e PSC-047.

---

## 13. Fase 8 — Gerador de orçamento e proposta `[   ]`

**Objetivo:** emitir proposta comercial profissional para o cliente sem redigitar dados de projeto, com documento local para impressão/PDF.

**Estado:** escopo de produto descrito no plano de evolução; **contrato técnico específico ainda incompleto**.

### Checklist

- [ X ] Objetivo e conteúdo conceitual documentados no plano de evolução V1+.
- [   ] Decisão explícita sobre **valor proposto antes da aprovação** versus `ProjetoKanban.valor_total` (valor contratado).
- [   ] Definição da fonte estruturada dos itens de orçamento e respectivas medidas/descrições.
- [   ] Contrato de campos e versões da proposta, validade, condições de pagamento e anexos.
- [   ] Contrato de geração de PDF/impressão local, sem exigir cloud.
- [   ] Protótipo visual do fluxo de proposta e aprovação do Founder.
- [   ] Implementação de persistência própria apenas se autorizada e necessária.
- [   ] Implementação do gerador/template de proposta (PDF/imprimível).
- [   ] Garantia: gerar ou imprimir **não** aprova projeto nem cria recebíveis.
- [   ] Auditoria independente e testes de integridade monetária e dados.
- [   ] FinanQA, aprovação final e promoção para `main`.

**Não confundir:** `aprovar_orcamento_service()` existe, mas aprovar um negócio e gerar um **documento de proposta** são capacidades distintas.

---

## 14. Fase 9 — Exportação Excel / contador `[   ]`

**Objetivo:** permitir análise externa e envio de dados contábeis sem acesso manual ao SQLite.

### Checklist

- [ X ] Objetivo e grupos de dados previstos no roadmap.
- [   ] Especificação final dos campos, filtros, formato monetário e privacidade.
- [   ] Exportação financeira por período em CSV.
- [   ] Exportação financeira por período em XLSX.
- [   ] Exportação do resumo de fechamento mensal (formas de entrada, funcionários, saídas, saldo, semáforo).
- [   ] Tratamento correto de datas, acentuação, zeros, `Decimal` e dados não vinculados.
- [   ] Garantia de consulta read-only, sem eventos ou alteração de status.
- [   ] Protótipo/aprovação de interface para acesso às exportações, se necessário.
- [   ] Testes de reconciliação de totais, auditoria e FinanQA.
- [   ] Integração/promoção autorizada.

---

## 15. Fase 10 — Painel operacional “Hoje” `[   ]`

**Objetivo:** reunir em uma tela inicial as ações prioritárias do dia, sem criar um segundo banco de dados ou recalcular regras paralelas.

### Checklist

- [ X ] Conteúdo conceitual e princípio de agregação de selectors descritos no plano V1+.
- [   ] Contrato final de prioridade de alertas, fontes e ações.
- [   ] Quadro de orçamentos no prazo e vencidos.
- [   ] Quadro de produção, entregas previstas e projetos prontos para entrega.
- [   ] Quadro de contatos e pós-venda pendentes.
- [   ] Quadro de valores a receber, atrasados e vencendo hoje.
- [   ] Resumo do fechamento mensal e semáforo.
- [   ] Status do backup e último backup bem-sucedido.
- [   ] Histórico de ações recentes e atalhos para módulos de origem.
- [   ] Protótipo visual aprovado pelo Founder.
- [   ] Implementação da página e navegação principal.
- [   ] Testes de reconciliação, ausência de efeitos colaterais, desempenho e interface responsiva.
- [   ] FinanQA, auditoria e promoção.

---

## 16. Backlog transversal — fechar fluxos da V1 original `[ ... ]`

Esta seção evita apresentar um backend integrado como se todas as ações do usuário já estivessem disponíveis na interface. Os itens abaixo não reabrem automaticamente fases técnicas já fechadas: são *lacunas de experiência operacional* a priorizar e contratar com o Founder.

### 16.1 Kanban e projetos

- [ X ] Quadro de consulta dos projetos, alertas de orçamento vencido e filtros/estrutura de apresentação existentes.
- [ X ] Personalização de nomes das etapas e persistência da ordenação visual.
- [ X ] Services de aprovação, arquivamento, reativação e finalização.
- [   ] Mover cards entre etapas com fluxo operacional e confirmação de ações críticas.
- [   ] Modal de aprovação com entrada, parcelas, forma de pagamento e datas.
- [   ] Interface da “Geladeira” para orçamentos arquivados e reativação.
- [   ] Modal de arquivamento com motivo e agendamento de retorno.
- [   ] Modal de finalização com saldo pendente e pós-venda programado.
- [   ] Criação livre de novas etapas e arquivamento/restauração de etapas (não aprovado por inferência; depende de decisão específica).

### 16.2 Agenda e pós-venda

- [ X ] `AgendaContato` com vínculos, datas, status e feedback.
- [ X ] Service de conclusão exige feedback útil e satisfação válida.
- [ X ] Dados de contatos disponíveis em Cliente 360° e alertas globais no backend.
- [   ] Calendário integrado tipo FullCalendar do PRD original, com produção, entrega, pós-venda e retorno.
- [   ] Criação, edição e conclusão de contatos por modal operacional fora do Admin.
- [   ] Alerta persistente de contato pendente e bloqueio visual de encerramento sem feedback, conforme contrato original, após desenho e revisão de UX.

### 16.3 Financeiro e equipe

- [ X ] Cadastro e edição técnica de lançamentos via Admin.
- [ X ] Service de quitação integral e integração financeira com projeto.
- [ X ] Pagamentos a funcionários por service, com idempotência e projeto opcional.
- [ X ] Central de contas a receber read-only e rentabilidade por projeto.
- [   ] Tela operacional de contas a pagar, vencimentos e ações de pagamento.
- [   ] Tela para executar quitação sem recorrer ao Admin, preservando escopo e regras financeiras.
- [   ] Tela de fechamento mensal/semáforo.
- [   ] Tela de pagamentos da equipe, com cálculo e contexto seguro do projeto.

### 16.4 Segurança e navegação

- [ X ] Cabeçalho global e links para Clientes, Projetos, A receber e Rentabilidade.
- [ X ] Backend de alertas para orçamento vencido, contato pendente e backup.
- [ X ] Alerta visual de orçamento vencido integrado no layout base.
- [   ] Apresentar integralmente alertas de contatos e backup no cabeçalho/área própria.
- [   ] Tela/configuração amigável de backup e restauração guiada.
- [   ] Melhorar o acesso cotidiano aos cinco apps sem depender de Admin em ações principais.

**Observação de rastreabilidade:** a existência do backend não demonstra que a UI correspondente foi aprovada ou implementada. Cada frontend novo segue o gate de protótipo e aprovação visual.

---

## 17. Extensão documental — contratos originais e adendos `[   ]`

**Objetivo:** documentos comerciais vinculados a cliente, projeto, proposta e financeiro, sem confundir proposta, contrato original e adendo.

**Status do contrato:** proposta funcional documental de 25/10/2026, `DOCUMENT_ONLY=YES`, **aguardando aprovação visual explícita do Founder**. Portanto não classificar como contrato de implementação aprovado.

### Checklist documental e de produto

- [ X ] Proposta funcional textual elaborada e disponibilizada no contexto do projeto.
- [   ] Aprovação visual da experiência de contrato original e adendo.
- [   ] Decisão sobre estrutura de itens importados do orçamento.
- [   ] Decisão sobre vínculo entre orçamento, contrato, versão, adendo e recebível.
- [   ] Critérios e limites jurídicos/assinatura e campos obrigatórios, se forem requisitos futuros.

### Checklist de implementação

- [   ] Biblioteca de modelos reutilizáveis de contrato.
- [   ] Editor por seções e cláusulas editáveis individualmente.
- [   ] Preenchimento seguro de dados do cliente/projeto e itens estruturados do orçamento.
- [   ] Condições comerciais, prazos, garantias, testemunhas e anexos.
- [   ] Rascunhos recuperáveis e versões finalizadas imutáveis.
- [   ] Editor de adendo vinculado ao original, sem sobrescrever versão anterior.
- [   ] Pré-visualização de impacto financeiro e de datas.
- [   ] PDF e impressão local/offline.
- [   ] Integração financeira explícita e idempotente, **sem criar lançamentos só por salvar/finalizar/aditar documentos**.
- [   ] Auditoria, FinanQA e promoção.

**Não implementar por inferência:** assinatura eletrônica, comunicação cloud automática, autorização multiusuário, modelos/migrations ou alteração automática de valores do projeto ao salvar um documento.

**Proveniência do documento externo (evidência fornecida pelo Coordenador):**

```text
SOURCE_DOCUMENT=FINANPE_CONTRATOS_PROPOSTA_FUNCIONAL.md
SOURCE_SHA256=191284dd6445f9e2cd1589bbdcce9be23599d09a1ad9b3369178807e914f1ca2
SOURCE_ORIGIN=Documento fornecido pelo Founder ao contexto FinanPE.
SOURCE_APPROVAL=DOCUMENT_ONLY; FOUNDER_VISUAL_APPROVAL_PENDING.
LOCAL_BYTE_VERIFICATION=NOT_VERIFIED
```

O hash acima é preservado como evidência fornecida pelo Coordenador. A verificação local dos bytes do documento externo no Windows permanece `NOT_VERIFIED`. Este registro não afirma que o documento externo esteja versionado no GitHub nem que tenha sido auditado independentemente.

---

## 18. Exclusões expressas do escopo atual

Os seguintes recursos não devem entrar no percentual ou nas pendências obrigatórias da V1 sem aprovação específica:

- [   ] Estoque completo de MDF, ferragens e insumos (ERP de materiais).
- [   ] Compras, fornecedores, ordens de compra e MRP completo.
- [   ] Emissão fiscal NF-e/NFS-e e folha de pagamento legal completa.
- [   ] Multiusuário, papéis/permissões empresariais, tenant e arquitetura SaaS.
- [   ] Migração para PostgreSQL e RLS.
- [   ] Integrações pagas/automáticas de WhatsApp ou envio externo não solicitado.
- [   ] Assinatura jurídica/eletrônica automática de contratos.

> Itens acima estão desmarcados **por decisão de não escopo**, e não são obrigações atrasadas. Manter essa categoria separada dos requisitos da V1.

---

## 19. Critérios globais de aceite da V1 operacional

- [ X ] Núcleo histórico das fases 0–6 integrado em `main`, segundo commits e checkpoints examinados.
- [ ... ] Despesas recorrentes: backend integrado na validação; correções em auditoria local; frontend e release pendentes.
- [   ] Fluxos principais de cliente, agenda, projeto, financeiro e equipe utilizáveis pela interface, sem dependência operacional excessiva do Admin.
- [   ] Fechamento mensal acessível por interface e reconciliado com o ledger.
- [   ] Fase 8 — proposta comercial aprovada e entregue.
- [   ] Fase 9 — exportação para Excel/contador aprovada e entregue.
- [   ] Fase 10 — painel “Hoje” aprovado e entregue.
- [   ] Proteção do banco real e recuperação validadas em gates finais de versão.
- [   ] FinanQA final do SHA da V1 completa, com dados descartáveis e QA manual do Founder.
- [   ] Aprovação final de promoção e publicação em `main`, sem force-push.

**O status de “V1 concluída” só poderá ser `[ X ]` quando as entregas definidas para a versão e os gates finais tiverem evidências válidas.** Não calcular porcentagem de conclusão simplesmente dividindo fases `[ X ]` por total de fases: os tamanhos e riscos são muito diferentes.

---

## 20. Prioridades e dependências operacionais

| Ordem | Entrega | Condição para avançar |
|---|---|---|
| 1 | Reauditoria 199-R1 do candidato 7C | Auditoria independente sobre `3bbcceb` com gates completos |
| 2 | Validação do Coordenador da correção | Relatório, SHA/parent, diff, banco e testes verificados |
| 3 | Publicação controlada na `main-validation` | **Autorização explícita do Founder para SHA exato**, HEAD remoto inalterado e integridade validada |
| 4 | Checkpoint da integração | Registro exclusivo pelo Agente 012; histórico append-only |
| 5 | Protótipo da interface de recorrências | Requisitos/fluxos documentados e revisão do Founder |
| 6 | Implementação frontend e auditoria | Somente após aprovação visual explícita |
| 7 | Automação Windows da Fase 7 | Contrato e autorização de instalação separados; sem scheduler por inferência |
| 8 | FinanQA e release da Fase 7 | Código integrado, banco descartável, QA real e autorização de promoção |
| 9 | Fechar lacunas de UX do núcleo original | Priorização e contrato de cada interface pelo Founder |
| 10 | Gerador de propostas / contratos vinculados | Decisões de proposta e rastreabilidade financeira antes de models/PDF |
| 11 | Exportação e painel “Hoje” | Selectors estabilizados e protótipos aprovados |

**Fluxo de uma entrega nova:** contrato/decisão → (protótipo visual + aprovação, quando houver frontend) → implementação em worktree isolada → testes → auditoria independente → validação do Coordenador → autorização de integração → `main-validation` → FinanQA no SHA exato → QA do Founder → autorização de promoção → `main` → checkpoint.

---

## 21. Como atualizar este PRD a cada conclusão

Registrar um bloco no final para **cada evolução aprovada**, sem apagar eventos anteriores:

```text
DATA=AAAA-MM-DD
ETAPA=F7.3-POLITICAS_DE_BORDA
STATUS_ANTERIOR=[ ... ]
STATUS_NOVO=[ X ]
BRANCH_DESTINO=main-validation
SHA_EXATO=<SHA completo>
EVIDENCIA_TESTES=<comando + resultado>
AUDITORIA_INDEPENDENTE=<agente + veredito + SHA>
COORDENADOR_VALIDOU=YES|NO
FOUNDER_AUTORIZOU_INTEGRACAO=YES|NO
FOUNDER_APROVOU_QA=YES|NO|NAO_APLICAVEL
FOUNDER_AUTORIZOU_RELEASE=YES|NO
CHECKPOINT_CANONICO=<PSC ID, quando registrado>
OBSERVACOES=<limitações e próximos gates>
```

**Política de atualização:** este PRD é um painel de execução e requisitos; **não muda automaticamente regras de produto**. A atualização deve reproduzir evidências reais de Git/testes/auditoria e decisões explícitas. O responsável pela edição do PRD deverá estar autorizado, e não poderá editar o checkpoint canônico reservado ao Agente 012.

---

## 22. Fontes, classificação e divergências de documentação

### Fontes de produto

1. `docs/PRD_CONTEXT.md` — PRD original, metas e regras da V1 local.
2. `docs/FINANPE_PLANO_EVOLUCAO_PRODUTO_V1.md` — plano V1+ e Fases 0–10.
3. `docs/GOVERNANCE_FINANPE.md` e `AGENTS.md` — precedência normativa, gates e promoção.
4. `docs/DATABASE_SCHEMA.md` — contratos de dados.
5. `docs/ROADMAP_PROMPTS.md` — continuidade do roadmap.
6. `FINANPE_CONTRATOS_PROPOSTA_FUNCIONAL.md` — proposta documental fornecida ao projeto, ainda sem aprovação visual.

### Evidências do código GitHub (`Djohnn/FINAN`)

- `main`: `ba210df99e6f1fd5c25b5c7f131f1703764e1b92`.
- `main-validation`: `6d4decb04cd1ed10940c4bfdb7a4f874104bee13`.
- `docs/PROJECT_STATE.md` checkpoint `PSC-2026-11-04-047`.
- Apps, models, services, selectors, urls, views, templates, assets, scripts Windows e testes acessíveis no commit de validação.
- Relatórios locais recebidos das Missões 198, 199 e 198-R1; a reauditoria 199-R1 ainda estava pendente no momento desta versão.

### Divergência relevante e critério de reconciliação

O rodapé/status consolidado de `FINANPE_PLANO_EVOLUCAO_PRODUTO_V1.md` contém classificações antigas, como Central A/R frontend não implementado, rentabilidade e Cliente 360° apenas planejados. Esses rótulos foram **superados** por commits, templates e checkpoints posteriores. Este PRD usa:

1. a decisão explícita do Founder e a governança para definir o **que deve ser feito**;
2. `PROJECT_STATE.md` e os commits mais recentes para identificar **o que foi registrado como entregue**;
3. a presença de código/rotas/templates para identificar **o que de fato existe**;
4. relatórios locais apenas como **evidência reportada**, nunca como promoção remota confirmada.

---

## 23. Registro de mudanças do PRD

| Data | Versão | Alteração | Publicação no GitHub |
|---|---|---|---|
| 06/11/2026 | 1.0 | Consolidação integral das fases, status com `[ X ]`, `[ ... ]`, `[   ]`, lacunas de interface, contratos e gates | **Não realizada**; documento entregue ao Founder para análise |

**Fim do PRD consolidado — nenhuma alteração automática em `main`, `main-validation` ou `docs/PROJECT_STATE.md`.**
