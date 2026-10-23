# FinanPE — Plano de Evolução de Produto V1+

**Status do documento:** Plano de evolução de produto aprovado pelo Founder; capacidades futuras permanecem planejadas
**Data-base:** 2026-10-22
**Modo do produto:** local-first, Windows, SQLite, single-user, sem login na V1
**Base canônica no momento da redação:** `f370fdac09c5ef9d58869f619fecaafff25e3774`
**Baseline canônico no momento da redação:** 307 testes PASS
**Documento complementar a:** `docs/PRD_CONTEXT.md`, `docs/DATABASE_SCHEMA.md`, `docs/ROADMAP_PROMPTS.md`

---

## 1. Objetivo

Este documento amplia a visão do FinanPE sem substituir o PRD original.

O objetivo é levar o sistema de um gerenciador operacional/financeiro para uma ferramenta que responda, de forma simples, às perguntas mais importantes do dono da marcenaria:

1. **O que preciso fazer hoje?**
2. **Quem está me devendo?**
3. **Quais trabalhos estão atrasados?**
4. **Quanto ganhei este mês?**
5. **Em quais projetos eu realmente ganhei dinheiro?**
6. **Se o computador falhar, consigo recuperar a operação com segurança?**

A expansão deve preservar os princípios já definidos:

- local-first;
- SQLite na V1;
- single-user;
- sem autenticação preventiva;
- sem multi-tenant/SaaS preventivo;
- mutações de negócio em services;
- dinheiro com `Decimal` e contratos de integridade já fechados;
- frontend somente depois de protótipo visual e aprovação explícita do Founder;
- testes e auditoria independente proporcionais ao risco;
- sem transformar a V1 em um ERP amplo.

---

## 2. Escopo desta expansão

Entram no plano todas as melhorias adicionais aprovadas pelo Founder:

1. restauração de backup testada;
2. central de contas a receber e cobrança;
3. lucro/margem por projeto;
4. visão 360° do cliente;
5. gerador de orçamento/proposta;
6. exportação para contador/Excel;
7. despesas recorrentes;
8. histórico de ações importantes;
9. tela operacional “Hoje”.

O **Fechamento Mensal / Semáforo**, apesar de já existir no PRD original, também aparece na sequência abaixo porque é uma dependência importante para relatórios e para a tela “Hoje”.

A idempotência de pagamento de funcionário (`1A,2A,3A`) está integrada e não permanece como frente futura desta expansão.

---

## 3. Prioridade de produto x ordem de execução

A prioridade de negócio e a ordem técnica não são exatamente iguais.

O histórico de ações, por exemplo, é prioridade média para o usuário, mas deve entrar relativamente cedo para que as funcionalidades implementadas depois já nasçam registrando eventos importantes, evitando retrofit.

| Ordem | Frente | Prioridade de produto | Motivo da posição |
|---|---|---|---|
| 0 | Idempotência de pagamento de funcionário | Núcleo concluído | Risco financeiro integrado e auditado |
| 1 | Restauração de backup / recuperação | **Crítica — concluída** | Evita perda definitiva da empresa em falha de disco/DB |
| 2 | Histórico de ações importantes | Integrada | Evita retrofit nas próximas frentes |
| 3 | Fechamento Mensal / Semáforo | **Integrada / CLOSED_INTEGRATED** | Fecha o núcleo financeiro e alimenta indicadores |
| 4 | Central de contas a receber / cobrança | **Muito alta — próxima frente de descoberta/contrato** | Impacto direto em caixa e inadimplência |
| 5 | Lucro/margem por projeto | **Muito alta** | Mostra quais serviços realmente geram resultado |
| 6 | Visão 360° do cliente | Alta | Concentra memória comercial e operacional |
| 7 | Despesas recorrentes | Média/Alta | Reduz esquecimentos e melhora previsibilidade mensal |
| 8 | Gerador de orçamento/proposta | Alta | Conecta operação comercial ao sistema |
| 9 | Exportação contador/Excel | Média/Alta | Evita ilhas de dados e trabalho manual externo |
| 10 | Tela “Hoje” | Alta em uso diário | Deve ser construída por último porque agrega as fontes anteriores |

---

# 4. FASE 0 — Fechar o núcleo atual

## 4.1 Idempotência de pagamento de funcionário

**Estado:** INTEGRADA — decisões 1A/2A/3A fechadas, implementação e auditoria concluídas.

### Contrato aprovado

Identidade de retry:

- funcionário;
- data de vencimento;
- valor;
- forma de pagamento;
- status esperado;
- observação normalizada.

Regras:

- `None`, vazio e somente espaços são a mesma observação;
- observações diferentes permitem pagamentos legítimos separados;
- `CANCELADO` não bloqueia novo pagamento idêntico;
- retry idêntico reutiliza o lançamento existente;
- retorno preserva `LancamentoFinanceiro` e informa `foi_criado=True/False` de forma transitória.

### Gate para avançar

Somente abrir a primeira nova frente mutável após:

- implementação PASS;
- auditoria independente PASS;
- integração autorizada pelo Founder;
- GitHub confirmado;
- cleanup do ambiente encerrado.

---

# 5. FASE 1 — Recuperação de backup / Disaster Recovery

**Prioridade:** CRÍTICA
**Estado:** INTEGRADA / CLOSED_INTEGRATED
**Objetivo:** garantir não apenas que existe backup, mas que os dados podem ser recuperados com segurança.

## 5.1 Problema

O FinanPE já possui estratégia de backup diário no pendrive. Isso protege contra parte do risco, mas um backup só é confiável quando existe um procedimento testado para:

- validar o arquivo;
- restaurá-lo;
- preservar o banco atual antes da restauração;
- confirmar que o banco restaurado é íntegro.

## 5.2 Escopo backend recomendado

Criar fluxo de restauração com as seguintes garantias:

1. selecionar explicitamente um arquivo de backup;
2. exigir que o arquivo exista e seja SQLite válido;
3. abrir o backup em modo somente leitura para `PRAGMA integrity_check`;
4. recusar restauração se integridade não retornar `ok`;
5. antes de substituir o banco atual, criar uma **cópia de segurança pré-restauração**;
6. realizar restauração somente com confirmação explícita;
7. evitar restauração enquanto o servidor estiver gravando no banco;
8. substituir o arquivo de banco de forma controlada;
9. validar o banco restaurado depois da operação;
10. registrar resultado no histórico operacional;
11. nunca apagar automaticamente o backup de origem.

## 5.3 Estratégia V1 recomendada

Na V1, priorizar:

- service seguro;
- management command;
- script Windows de recuperação guiada;
- interface gráfica somente depois do protótipo aprovado.

Não criar restauração automática em background.

## 5.4 Critérios de aceite

- backup íntegro restaura com sucesso;
- backup corrompido é rejeitado;
- arquivo inexistente é rejeitado;
- banco atual recebe cópia de segurança antes da substituição;
- falha intermediária não deixa o banco sem uma versão recuperável;
- `PRAGMA integrity_check` é `ok` após restauração;
- testes não usam o banco real de negócio;
- procedimento de recuperação é documentado e reproduzível.

**Resultado V1:** a restauração segura foi implementada, auditada e integrada.
A persistência de eventos de restauração no histórico operacional foi
deliberadamente deferida para a FASE 2, sem caracterizar falha desta frente.

## 5.5 Decisões de produto futuras

Antes da UI de restauração, Founder deve aprovar:

- localização do botão de recuperação;
- texto e nível de confirmação destrutiva;
- se restauração ficará disponível na interface ou apenas em ferramenta administrativa V1.

---

# 6. FASE 2 — Histórico de ações importantes

**Prioridade de produto:** MÉDIA
**Prioridade técnica:** ALTA por dependência
**Estado:** INTEGRADA / CLOSED_INTEGRATED

## 6.1 Contrato V1 integrado

O FinanPE registra ações importantes em `apps.core_sistema.EventoSistema`.
O histórico V1 é append-only, somente leitura no Admin técnico e limitado a
seletores bounded.

Os 11 tipos de evento integrados são:

- `ORCAMENTO_APROVADO`;
- `ORCAMENTO_ARQUIVADO`;
- `ORCAMENTO_REATIVADO`;
- `PROJETO_FINALIZADO`;
- `PAGAMENTO_FUNCIONARIO_CRIADO`;
- `LANCAMENTO_QUITADO`;
- `CONTATO_CONCLUIDO`;
- `BACKUP_CONCLUIDO`;
- `BACKUP_FALHOU`;
- `RESTAURACAO_CONCLUIDA`;
- `RESTAURACAO_FALHOU_ROLLBACK_OK`.

Os domínios V1 são `KANBAN`, `EQUIPE`, `FINANCEIRO`, `AGENDA`, `BACKUP`
e `RESTAURACAO`.

## 6.2 Semântica integrada

Eventos de negócio são criados na mesma transação atômica da mutação.
Falha na escrita do histórico faz rollback da mutação de negócio. Retries
idempotentes e transições sem mudança não criam eventos duplicados.

Um pagamento de funcionário recém-criado gera evento; retry idêntico que
reutiliza a linha existente não gera novo evento. Não há evento genérico de
mudança de etapa além dos 11 tipos congelados.

Falha de histórico em manutenção não destrói backup válido, não desfaz
restauração válida e não invalida rollback verificado; a falha é exposta por
aviso controlado.

Metadados monetários usam strings canônicas com duas casas decimais e IDs de
entidade usam strings decimais ASCII positivas. Não são aceitos secrets ou
free-text sensível arbitrário.

## 6.3 Migração e recuperação

O modelo foi integrado pela migration `core_sistema.0002_eventosistema`.
Backups anteriores sem essa migration permanecem legados e incompatíveis;
não há auto-migração ou conversão de backups antigos.

## 6.4 Precisão do contrato

O histórico integrado cobre as ações V1 definidas acima. Novas ações,
incluindo o fechamento mensal, entram com contrato próprio e decisão Founder
quando aplicável. O fechamento mensal V1 está agora integrado e fechado.

---

# 7. FASE 3 — Fechamento Mensal / Semáforo

**Prioridade:** MUITO ALTA
**Origem:** requisito já existente no PRD.
**Estado:** INTEGRADA / CLOSED_INTEGRATED
**Implementação:** `0169a6439fbabb820e0fd11282c415a1207edfc9`
**Auditoria independente:** `FINANPE-MONTHLY-CLOSING-AUDITOR-113` — PASS
**Evidência:** 31 testes focados, 163 relacionados, 338 testes completos e 65/65 probes independentes.

## 7.1 Objetivo

Responder de forma simples:

- quanto entrou;
- quanto saiu;
- quanto funcionários custaram;
- saldo final;
- margem;
- inadimplência;
- classificação verde/amarela/vermelha.

## 7.2 Contrato-base existente

Considerar lançamentos `PAGO` dentro do mês/ano selecionado.

Calcular:

- total de entradas;
- entradas por forma de pagamento;
- total de funcionários;
- custo nominal por funcionário;
- outras saídas;
- saldo final;
- margem líquida;
- semáforo.

## 7.3 Decisões Founder integradas

As decisões 1A a 7A estão fechadas e fazem parte do contrato V1:

1. Django Admin permanece técnico/manutenção; o fechamento mensal não é uma
   funcionalidade operacional do Admin.
2. Categoria `OUTROS` entra em “outras saídas”; toda `SAIDA` realizada,
   exceto `FUNCIONARIO`, contribui para esse total.
3. Com receita zero, `margem_percentual` é `None`; saldo zero é amarelo e
   saldo negativo é vermelho.
4. A inadimplência usa `data_vencimento <=` o fim do mês selecionado e
   considera `PENDENTE` ou `PAGO` com `data_pagamento` após o corte, sem
   limite inferior de origem.
5. `FUNCIONARIO` realizado sem funcionário é incluído no custo e agrupado
   como `Sem funcionário vinculado`.
6. A precedência do semáforo é: saldo negativo vermelho; depois qualquer
   inadimplência amarelo; depois receita e saldo positivos com margem exata
   de pelo menos 15% verde; caso contrário amarelo.
7. O V1 usa o estado atual do ledger: `CANCELADO` atual fica fora da
   inadimplência, sem reconstrução de timestamp de cancelamento ou histórico
   pré-cancelamento.

## 7.4 Contrato técnico V1 integrado

O seletor público é `apps/financeiro/selectors.py`:

```python
fechamento_mensal(*, ano: int, mes: int) -> FechamentoMensal
```

Os modelos de leitura são `EntradaPorForma`, `CustoFuncionario` e
`FechamentoMensal`, em dataclasses imutáveis com coleções baseadas em tupla.
Não há persistência de fechamento, snapshot mensal, modelo novo ou migration.

Qualquer lançamento `PAGO` sem `data_pagamento` torna o fechamento
indisponível com o erro exato:

`Fechamento mensal indisponível: lançamento PAGO sem data_pagamento.`

Não há fallback para `data_vencimento`, inferência de data ou resultado
parcial. O mês realizado usa `status='PAGO'` e `data_pagamento` dentro do
mês selecionado, com entradas por forma na ordem `PIX`, `CARTAO_CREDITO`,
`CARTAO_DEBITO`, `DINHEIRO`, `BOLETO`, preenchendo ausências com zero.

O saldo é entradas menos custo de funcionários menos outras saídas. A
acumulação monetária usa centavos inteiros após validação, sem float como
fonte de verdade e sem dependência do contexto Decimal do chamador. A
validação rejeita verdadeira sobreprecisão monetária antes da agregação,
inclusive valores como `1.234`, `1.230000000000001` e `99999999.99000001`.

As anomalias relevantes seguem a precedência: validação de entrada, `PAGO`
sem data, `status`, `tipo`, `categoria`, `forma_pagamento` e `valor`, com
mensagens controladas por campo. O fluxo é somente leitura, não emite
`EventoSistema`, não chama serviço de mutação e não faz uma consulta por
funcionário; a auditoria mediu uma consulta nos fixtures pequeno e de 101
funcionários.

## 7.5 Limitação histórica aceita

O fechamento não reconstrói cancelamentos retroativos. A inadimplência é
calculada sobre o estado corrente do ledger, e não existe snapshot,
schema de histórico ou trilha de status pré-cancelamento nesta frente.

---

# 8. FASE 4 — Central de contas a receber e cobrança

**Prioridade:** MUITO ALTA

## 8.1 Objetivo

Transformar lançamentos pendentes em uma fila operacional de cobrança.

## 8.2 Fonte de verdade

Usar `LancamentoFinanceiro` existente.

Considerar contas a receber:

- `tipo='ENTRADA'`;
- `status='PENDENTE'`.

Classificações recomendadas:

- **Vencido:** `data_vencimento < hoje`;
- **Vence hoje:** `data_vencimento == hoje`;
- **Próximos 7 dias**;
- **Próximos 30 dias**.

`PAGO` e `CANCELADO` não entram na cobrança ativa.

## 8.3 Informações por cobrança

Exibir:

- cliente;
- projeto;
- descrição;
- vencimento;
- dias em atraso;
- valor;
- forma prevista;
- WhatsApp;
- ação rápida de cobrança.

## 8.4 Indicadores

Exibir no topo:

- total a receber;
- total vencido;
- quantidade de clientes em atraso;
- maior atraso em dias.

## 8.5 WhatsApp

Gerar mensagem de cobrança sem API paga, usando `wa.me`, preservando o padrão atual do produto.

A mensagem deve ser editável pelo usuário antes do envio.

## 8.6 Critérios de aceite

- nenhuma cobrança inclui `SAIDA`;
- nenhuma cobrança inclui `PAGO`/`CANCELADO`;
- datas limítrofes classificadas corretamente;
- totalizadores batem com a soma das linhas;
- lançamento quitado desaparece da lista ativa;
- botão WhatsApp não realiza mutação financeira.

---

# 9. FASE 5 — Lucro e margem por projeto

**Prioridade:** MUITO ALTA

## 9.1 Objetivo

Responder:

> “Este serviço deu dinheiro ou prejuízo?”

## 9.2 Métricas recomendadas

Para cada projeto, exibir separadamente:

### Comercial

- valor contratado (`ProjetoKanban.valor_total`);
- valor recebido;
- saldo a receber.

### Custos diretos

Somar saídas ligadas ao projeto:

- matéria-prima;
- funcionário, quando diretamente atribuído ao projeto;
- outros custos diretamente atribuídos ao projeto.

### Resultado

- lucro direto = valor contratado − custos diretos;
- margem direta % = lucro direto / valor contratado;
- caixa recebido = entradas pagas ligadas ao projeto;
- caixa líquido realizado = entradas pagas − saídas pagas diretamente ligadas ao projeto.

## 9.3 Regra importante

Custos sem `projeto_id` **não podem ser atribuídos automaticamente** a um projeto.

Eles continuam aparecendo no fechamento mensal como custos gerais.

Isso evita inventar rateios que o usuário não autorizou.

## 9.4 Gap de dados identificado

O model financeiro já possui `projeto` opcional, portanto material/outros custos podem ser vinculados diretamente.

O fluxo atual de pagamento de funcionário vincula `funcionario`, mas não exige projeto.

Antes de implementar margem com mão de obra por projeto, deve-se definir se a V1 permitirá:

- informar projeto opcional ao lançar pagamento de funcionário; ou
- lançar uma saída específica de mão de obra vinculada ao projeto.

### Recomendação

Adicionar **projeto opcional** no fluxo de pagamento de funcionário, sem torná-lo obrigatório.

Se não informado, permanece custo geral da empresa.

## 9.5 Critérios de aceite

- receita e custos não são misturados;
- custos gerais sem projeto não contaminam margem individual;
- projeto sem receita não causa divisão por zero;
- projeto sem custos mostra margem coerente;
- totais financeiros preservam `Decimal` e regras monetárias existentes.

---

# 10. FASE 6 — Visão 360° do cliente

**Prioridade:** ALTA

## 10.1 Objetivo

Transformar o cadastro de cliente em memória comercial da marcenaria.

## 10.2 Tela conceitual

Ao abrir um cliente, apresentar:

- dados cadastrais;
- WhatsApp;
- endereço e observações;
- todos os projetos;
- etapa atual de cada projeto;
- orçamentos arquivados e motivo;
- total contratado;
- total recebido;
- saldo a receber;
- agenda futura;
- contatos concluídos;
- feedback/pós-venda;
- histórico de eventos relevantes.

## 10.3 Implementação recomendada

Priorizar selectors/read models.

Evitar duplicar dados já existentes em novos campos.

## 10.4 Critérios de aceite

- um cliente com múltiplos projetos aparece corretamente;
- nenhum dado é regravado para montar a visão;
- valores agregados reconciliam com financeiro;
- links para projeto/cobrança/WhatsApp preservam contexto.

---

# 11. FASE 7 — Despesas recorrentes

**Prioridade:** MÉDIA/ALTA

## 11.1 Objetivo

Evitar esquecer custos fixos como:

- aluguel;
- energia;
- internet;
- contador;
- manutenção;
- assinaturas;
- outras despesas previsíveis.

## 11.2 Modelo conceitual recomendado

Nova entidade, por exemplo `DespesaRecorrente`, com:

- descrição;
- categoria financeira;
- valor;
- forma de pagamento;
- dia de vencimento;
- ativo/inativo;
- início da recorrência;
- fim opcional;
- observação.

## 11.3 Geração de lançamentos

O gerador mensal deve ser idempotente.

Uma recorrência não pode criar duas cobranças para o mesmo período por retry.

Lançamentos gerados entram inicialmente como `PENDENTE`.

## 11.4 Casos de calendário

Para vencimentos em dias inexistentes no mês, recomendar último dia válido do mês.

Exemplo:

- dia configurado = 31;
- fevereiro → último dia de fevereiro.

## 11.5 Critérios de aceite

- geração repetida não duplica lançamento;
- desativar recorrência não apaga histórico;
- alteração futura não reescreve meses passados;
- geração respeita `Decimal` e choices financeiros.

---

# 12. FASE 8 — Gerador de orçamento / proposta

**Prioridade:** ALTA

## 12.1 Objetivo

Permitir transformar o projeto em uma proposta profissional para o cliente sem reescrever os dados em Word/WhatsApp.

## 12.2 Conteúdo mínimo

- nome da marcenaria;
- cliente;
- WhatsApp/endereço quando aplicável;
- nome do serviço;
- descrição/medidas;
- valor do orçamento;
- entrada;
- saldo;
- forma/condições de pagamento;
- prazo/validade;
- previsão de execução/entrega quando definida;
- observações comerciais.

## 12.3 Gap identificado

Hoje o valor financeiro definitivo é consolidado no fluxo de aprovação.

Para gerar proposta antes da aprovação, será necessário decidir como persistir um **valor de orçamento ainda não aprovado** sem confundi-lo com contrato fechado.

### Recomendação

Não reutilizar silenciosamente o significado de `valor_total` se isso puder representar tanto cotação quanto contrato.

Antes da implementação, auditar o uso atual do campo e decidir entre:

- permitir `valor_total` como valor proposto antes da aprovação, com semântica documentada; ou
- criar campos/entidade específica de proposta/orçamento.

Essa decisão precisa ser tomada antes de gerar PDF oficial.

## 12.4 Saída

Gerar formato imprimível/PDF local.

Não exigir serviço cloud.

## 12.5 Critérios de aceite

- proposta não aprova projeto automaticamente;
- gerar novamente é read-only;
- valores exibidos são exatamente os persistidos;
- documento identifica claramente que é orçamento/proposta quando ainda não aprovado.

---

# 13. FASE 9 — Exportação para contador / Excel

**Prioridade:** MÉDIA/ALTA

## 13.1 Objetivo

Permitir uso dos dados fora do FinanPE sem acesso manual ao SQLite.

## 13.2 Formatos recomendados

V1:

- CSV universal;
- XLSX amigável;
- relatório imprimível opcional.

## 13.3 Exportações mínimas

### Financeiro por período

- tipo;
- categoria;
- cliente/projeto quando houver;
- funcionário quando houver;
- descrição;
- valor;
- forma;
- vencimento;
- pagamento;
- status.

### Fechamento mensal

- resumo;
- entradas por forma;
- funcionários;
- outras saídas;
- saldo;
- margem;
- semáforo.

## 13.4 Segurança

Exportação é leitura.

Não deve modificar banco ou marcar itens como processados.

## 13.5 Critérios de aceite

- soma exportada reconcilia com selector financeiro;
- filtros de mês/ano são determinísticos;
- caracteres portugueses são preservados;
- valores monetários não viram floats imprecisos.

---

# 14. FASE 10 — Tela operacional “Hoje”

**Prioridade:** ALTA para experiência diária
**Ordem técnica:** última, por depender de várias fontes consolidadas.

## 14.1 Objetivo

Ao abrir o sistema, o proprietário deve saber em segundos onde precisa agir.

## 14.2 Blocos recomendados

### Hoje / atrasados

- orçamentos no prazo limite ou atrasados;
- entregas previstas hoje/próximas;
- contatos/pós-venda pendentes;
- cobranças vencidas;
- cobranças vencendo hoje.

### Financeiro rápido

- a receber;
- vencido;
- saldo do mês;
- semáforo atual.

### Operação

- projetos em produção;
- projetos prontos para entrega;
- ações recentes importantes.

### Segurança

- backup de hoje: OK/PENDENTE/FALHA;
- último backup bem-sucedido;
- alerta de pendrive quando aplicável.

## 14.3 Regra de design

A tela “Hoje” não deve virar um novo banco de dados.

Ela agrega selectors das fontes existentes.

## 14.4 Critérios de aceite

- nenhum card da tela gera side-effect apenas por ser exibido;
- totais reconciliam com módulos de origem;
- não repetir alertas de forma contraditória;
- cada alerta tem ação clara: abrir projeto, cliente, cobrança, agenda ou backup.

---

# 15. Regras transversais para todas as novas frentes

## 15.1 Dados e dinheiro

Preservar todos os contratos monetários já fechados.

Nenhuma frente nova pode reintroduzir:

- float como fonte de verdade;
- arredondamento silencioso de entrada inválida;
- valores monetários fora de escala;
- sinais incompatíveis com o contrato do campo.

## 15.2 Mutações

Toda mudança de negócio relevante deve ocorrer em service transacional.

Selectors e dashboards devem ser read-only.

## 15.3 Idempotência

Rotinas sujeitas a repetição devem ter contrato explícito de retry, especialmente:

- restauração;
- despesas recorrentes;
- geração de cobrança/evento;
- pagamentos;
- geração de documentos quando existir persistência associada.

## 15.4 Cancelamento

`CANCELADO` deve ser tratado como encerrado/inativo nos fluxos em que um lançamento cancelado não deve bloquear uma nova operação legítima.

Nunca inventar `ESTORNADO` sem decisão e alteração formal de schema.

## 15.5 Banco real

Missões mutáveis devem manter a regra operacional vigente:

- hash SHA-256 imediatamente antes/depois quando a missão não deve tocar dados reais;
- igualdade exigida;
- `PRAGMA integrity_check` quando pertinente;
- sem usar hash histórico congelado como gate.

## 15.6 Testes

Para toda nova regra:

- RED objetivo no comportamento antigo quando aplicável;
- GREEN focado;
- regressões relacionadas;
- suíte completa;
- migration drift check;
- auditor independente em mudanças financeiras, recuperação de dados ou contratos relevantes.

## 15.7 Frontend

Nenhuma tela nova deve ser implementada antes de:

1. definição funcional/backend suficiente;
2. protótipo visual;
3. aprovação explícita do Founder;
4. implementação;
5. comparação da tela final contra o protótipo aprovado.

---

# 16. O que continua fora da V1 desta expansão

Para manter o FinanPE pequeno e confiável, não incluir agora:

- estoque completo de chapas, ferragens e insumos;
- compras/fornecedores como ERP completo;
- NF-e/emissão fiscal;
- folha/ponto/RH completo;
- login e permissões multiusuário;
- SaaS/multi-tenant;
- PostgreSQL/RLS preventivos;
- sincronização cloud obrigatória;
- integrações pagas de WhatsApp;
- armazenamento pesado de fotos/desenhos/anexos como requisito central.

Esses temas podem ser revisados depois de a operação V1 estar estabilizada.

---

# 17. Definição de “V1 operacionalmente pronta”

O FinanPE pode ser considerado operacionalmente pronto para uso diário quando, no mínimo:

- núcleo Kanban/financeiro/agenda/equipe estiver integrado e auditado;
- idempotência financeira crítica estiver fechada;
- fechamento mensal estiver definido e funcionando;
- backup automático estiver funcionando;
- restauração de backup estiver testada e documentada;
- cobranças pendentes estiverem visíveis de forma confiável;
- regressão completa estiver verde;
- banco real passar integridade;
- frontend essencial tiver protótipo aprovado e validação final do Founder.

Lucro por projeto, cliente 360°, recorrências, proposta, exportação e tela “Hoje” elevam o FinanPE de “pronto para operar” para **produto operacional completo e gerencialmente útil**.

---

# 18. Estratégia de entrega recomendada

Não implementar todas as frentes em paralelo.

Manter a regra de até duas frentes simultâneas, preferindo:

- uma implementação mutável;
- uma auditoria/descoberta read-only independente.

Promoções continuam seriais.

### Sequência de marcos

**Marco A — Segurança financeira e recuperação**
Idempotência de funcionário → restauração de backup → histórico básico.

**Marco B — Gestão financeira gerencial**
Fechamento mensal → central de cobrança → lucro por projeto.

**Marco C — Inteligência comercial**
Cliente 360° → proposta/orçamento.

**Marco D — Automação administrativa**
Despesas recorrentes → exportação contador/Excel.

**Marco E — Experiência operacional**
Tela “Hoje” + integração visual dos módulos já estabilizados.

---

# 19. Próxima ação recomendada

1. descobrir o contrato read-only da Central de contas a receber / cobrança;
2. fechar seu escopo e suas decisões antes de qualquer implementação;
3. implementar e auditar a frente somente após autorização explícita;
4. seguir a sequência deste documento.

O histórico de ações importantes já está integrado e deve ser usado pelas
próximas frentes quando novos eventos forem contratados.

---

# 20. Status das frentes propostas

| Frente | Status atual |
|---|---|
| Idempotência pagamento funcionário | INTEGRADA |
| Restauração de backup | INTEGRADA / CLOSED_INTEGRATED |
| Histórico de ações | INTEGRADA / CLOSED_INTEGRATED |
| Fechamento mensal | INTEGRADA / CLOSED_INTEGRATED |
| Central de cobrança | PLANEJADA — NEXT DISCOVERY / CONTRACT |
| Lucro por projeto | PLANEJADA — há decisão futura sobre mão de obra/projeto |
| Cliente 360° | PLANEJADA |
| Despesas recorrentes | PLANEJADA |
| Gerador de proposta | PLANEJADA — exige fechar semântica do valor de orçamento |
| Exportação contador/Excel | PLANEJADA |
| Tela “Hoje” | PLANEJADA — agregadora final |

---

## Nota de governança

Este documento registra **planejamento de produto**, não comprovação de implementação.

Uma frente só muda de `PLANEJADA` para `INTEGRADA` após evidência técnica, testes, auditoria proporcional ao risco, autorização do Founder quando necessária, promoção ao `main` e verificação do estado canônico.
