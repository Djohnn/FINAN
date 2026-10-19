# FINANEP — Governança, autorização e protocolo anti-alucinação

**Status deste documento:** inventário histórico e política operacional vigente; não autoriza implementação funcional por si só.

**Data da inspeção:** 2026-10-19 (America/Sao_Paulo)

## 1. Escopo e evidência da inspeção

### HISTORICAL_INSPECTION_STATE

Os achados abaixo sobre `AGENTS.md`, Git, branch, worktree e SHA pertencem à inspeção original e devem ser preservados como histórico. Eles não descrevem o estado operacional atual desta worktree.

Foram inspecionados:

- `.cursorrules`;
- `docs/PRD_CONTEXT.md`, `docs/DATABASE_SCHEMA.md` e `docs/ROADMAP_PROMPTS.md`;
- `core_config/`, `apps/`, `templates/`, `tests/` e `scripts_windows/`;
- migrations, `manage.py`, `gerar_governanca.py`, settings e URLs;
- grafo existente em `graphify-out/` e consultas Graphify de arquitetura e autorização.

Não foi encontrado `AGENTS.md` no repositório. Não há `views.py`, `selectors.py`, `forms.py`, templates ou URLs de domínio na árvore inspecionada; `core_config/urls.py` expõe somente `/admin/`.

O diretório não foi reconhecido como worktree Git nesta execução: `git status`, `git rev-parse HEAD` e `git branch --show-current` falharam com “not a git repository”. Portanto branch, worktree e SHA são **BLOQUEADOS / NÃO VERIFICADOS**, não podem ser inventados nem usados como identidade de mudança.

### CURRENT_OPERATIONAL_STATE

O estado operacional posterior à inspeção original, confirmado novamente na composição documental a partir de `2b34afbce433e3806daa23bef95a5725450c4a90`, é:

- `GIT_INITIALIZED=YES`;
- `MAIN_BRANCH=main`;
- `REMOTE_REPOSITORY=Djohnn/FINAN`;
- `AGENTS_MD_PRESENT=YES`;
- `WORKTREE_GOVERNANCE_AVAILABLE=YES`.

As afirmações históricas acima sobre ausência de `AGENTS.md` e Git não verificável permanecem como registro da inspeção original; não são bloqueios do estado atual.

### Classificações obrigatórias

- **CONFIRMADO:** demonstrado por arquivo, símbolo, linha, saída de comando ou teste reproduzível.
- **INFERIDO:** conclusão derivada de evidência parcial; nunca tratar como fato executável.
- **NÃO VERIFICADO:** não houve evidência suficiente nesta inspeção.
- **BLOQUEADO:** a verificação exige autorização, ambiente ou artefato indisponível.

Toda conclusão técnica deve usar uma dessas classificações e apontar caminho, símbolo/linha ou saída bruta. Ausência de evidência não é evidência de ausência; quando a árvore foi inspecionada e o item não apareceu, registrar “não encontrado na árvore inspecionada”.

## 2. Fontes de verdade e divergências

1. O **código executável e as migrations aplicadas** são a fonte de verdade do comportamento atualmente existente.
2. `docs/DATABASE_SCHEMA.md` é a especificação estrutural declarada.
3. `docs/PRD_CONTEXT.md` é a fonte normativa de produto e regras de negócio.
4. `.cursorrules` é a política de engenharia já existente.
5. `docs/ROADMAP_PROMPTS.md` é roteiro de construção, não prova de implementação.

Quando as fontes divergirem, registrar a divergência com as duas referências, impacto, decisão aprovada, responsável e data. É proibido escolher silenciosamente o PRD, o schema ou o código. Este documento não resolve divergências funcionais; apenas as torna explícitas.

## 3. Arquitetura observada

O PRD define cinco apps (`docs/PRD_CONTEXT.md:8-14`) e o settings registra os cinco em `core_config/settings.py:33-47`:

| App | Responsabilidade declarada | Implementação confirmada | Dependências observadas |
|---|---|---|---|
| `core_sistema` | configuração local, backup, alertas | `ConfiguracaoSistema`, `executar_backup_pendrive`, `alertas_globais`, comando de backup | settings/SQLite; alerta consulta `clientes_agenda` e `kanban_projetos` |
| `clientes_agenda` | clientes e pós-venda | `Cliente`, `AgendaContato`, `concluir_pos_venda_service` | FK para `kanban_projetos`; consulta configuração no WhatsApp |
| `kanban_projetos` | orçamento/Kanban | `ProjetoKanban` e services de aprovação, arquivamento, reativação e finalização | `clientes_agenda` e `financeiro` |
| `equipe` | funcionários e pagamentos | `Funcionario` e `lancar_pagamento_funcionario_service` | service cria lançamento em `financeiro` |
| `financeiro` | lançamentos e quitação | `LancamentoFinanceiro`, `registrar_pagamento_service`, saldo | consulta/atualiza projeto de `kanban_projetos` |

Limites obrigatórios:

- **models:** estrutura, invariantes locais e métodos puros; não devem orquestrar fluxos entre apps.
- **services:** toda escrita relevante, transação, regra de negócio e integração entre apps; devem receber autorização e, quando aplicável, idempotency key e motivo obrigatório.
- **selectors:** consultas e agregações de leitura; a camada ainda não existe e deve ser criada antes de endpoints de consulta complexa.
- **views/URLs:** transporte, autenticação/autorização de ação, validação de entrada e chamada de service/selector; não devem conter regra financeira ou mutação direta.
- **templates/HTMX:** apresentação e transporte de eventos; nunca devem decidir autorização.

O código atual viola ou ainda não consegue cumprir alguns limites apenas porque a superfície web não foi implementada: não há views, selectors, URLs de domínio ou templates para auditar. Isso é uma lacuna de implementação, não autorização para criá-los nesta etapa.

## 4. Autenticação, autorização e RLS

### Estado confirmado na inspeção histórica

- Django `auth`, `sessions`, `AuthenticationMiddleware` e `CsrfViewMiddleware` estão habilitados em `core_config/settings.py:33-57`.
- O banco configurado é SQLite em `core_config/settings.py:83-87`.
- Existem as entidades padrão `User`, `Group` e `Permission` por migrations Django; não foram encontrados papéis de negócio, permissões customizadas, escopos por organização/filial ou filtros de queryset por usuário.
- O único endpoint exposto é `/admin/` em `core_config/urls.py:20-22`; não há endpoints HTMX implementados.
- SQLite não fornece RLS nativo. Não há middleware, backend de autorização, manager/queryset escopado ou proteção de acesso direto a registros confirmados na árvore.

### Aplicabilidade atual da V1

Por decisão explícita do Founder, `V1_PRODUCT_MODE=SINGLE_TENANT_LOCAL_SINGLE_USER`, `LOGIN_REQUIRED=NO`, `CURRENT_MULTI_TENANT_SCOPE=NO` e `CURRENT_DATABASE=SQLITE`. Portanto, `AUTHORIZATION_LAYER_REQUIRED_IN_V1=NO`. A ausência de camada de autorização inventariada historicamente não constitui, por si só, bloqueio da V1 local de usuário único. Isso não remove as proteções de dados aplicáveis nem significa que autorização nunca será necessária.

Não implementar preventivamente tenant, `tenant_id`, `Organization`, PostgreSQL, RLS, autenticação obrigatória ou roles/permissões pela possibilidade futura de SaaS. `FUTURE_MULTI_USER_ALLOWED=YES` e `FUTURE_MULTI_TENANT_SAAS_ALLOWED=YES` são direção futura, sujeita a desenho, implementação e validação próprios; não há promessa de migração sem esforço.

### Política sem inventar privilégios

Nenhum papel de negócio é criado ou presumido nesta baseline. `is_staff`, `is_superuser`, grupos e permissões Django só podem ser usados conforme evidência e aprovação explícita; não equivalem automaticamente a um papel operacional.

A prescrição histórica abaixo passa a ser exigida antes da exposição correspondente em futura evolução multiusuário/multi-tenant; não impõe login nem camada de autorização à V1 aprovada. Nesse desenho futuro, definir por ação:

1. identidade autenticada e política de sessão;
2. permissão mínima da ação;
3. escopo do queryset e validação de posse/relacionamentos;
4. proteção contra acesso direto por ID e enumeração de registros;
5. resposta de negação consistente, inclusive para requisições HTMX;
6. teste positivo e teste de negação para cada ação sensível.

Qualquer mudança que altere comportamento de autorização exige aprovação antes da implementação. No desenho futuro que exigir isolamento, a ausência de RLS em SQLite exige controles explícitos na aplicação, sem inventar RLS nativo para SQLite. Isso é requisito de desenho futuro, não prova de controle existente nem exigência preventiva para a V1.

### Migração futura para PostgreSQL

Uma migração futura pode adicionar PostgreSQL com RLS após decisão arquitetural aprovada, incluindo: modelo de escopo, contexto de sessão seguro, políticas `USING`/`WITH CHECK`, papel de runtime sem privilégios administrativos, cobertura de relações e testes de bypass. RLS não substitui autorização de ação nem validação de posse de ForeignKey. Nenhuma migration ou configuração PostgreSQL é autorizada por este documento.

## 5. Agentes e coordenação

Os papéis abaixo são papéis de processo, não papéis de usuário do sistema:

- **Executor:** altera somente os arquivos explicitamente autorizados, consulta Graphify antes de editar, preserva dados/migrations e para diante de escopo ambíguo, segredo exposto, divergência arquitetural ou falta de autorização.
- **Revisor independente:** reproduz a evidência a partir do estado identificado, revisa diff e critérios de aceite sem aceitar alegação do executor como prova; não altera o escopo para fazer o resultado passar.
- **COORDINATOR (Coordenador):** define escopo e gates, revisa criticamente o relatório do auditor, decide `AUDIT_VALIDATED=YES/NO`, decide a promoção ou não do estado e a próxima ação técnica. Registra decisões e resolve divergências de regra de negócio somente com aprovação do Founder; não substitui a persistência exclusiva pelo Scheduler. Agenda não é autorização.
- **AUDITOR (Revisor independente):** produz evidência independente; não promove candidato sozinho e não escreve checkpoint canônico.
- **CHECKPOINT_SCHEDULER:** inspeciona o estado real, reconcilia o histórico e escreve exclusivamente `docs/PROJECT_STATE.md`; não implementa, não corrige, não audita produto, não decide regra de negócio e não integra branches.
- **IMPLEMENTERS e demais agentes:** não editam `docs/PROJECT_STATE.md`.

Contrato mínimo de entrega: resumo; arquivos e linhas; estado antes/depois; comandos completos; saída bruta; classificação de cada resultado; decisões; pendências; riscos; próximo passo. Um teste sem saída do runner não é prova de passagem.

Proibições: modificar código funcional, dados, migrations, backups, histórico Git, permissões, credenciais ou ambiente fora do escopo; executar comandos destrutivos; mascarar falha como sucesso; imprimir ou persistir segredos; declarar integração, produção ou conformidade com base apenas em teste unitário.

## 6. Controle de alterações

Antes de qualquer alteração autorizada, registrar: caminho do repositório, branch/worktree, SHA, estado de limpeza, escopo autorizado, arquivos permitidos, banco/ambiente e comando de verificação. Depois, registrar os mesmos campos, diff, caminhos alterados e evidência dos gates.

Sem Git verificável, o estado deve ser **BLOQUEADO** para qualquer operação que dependa de branch/SHA. Não usar cópia externa, nome de pasta ou timestamp como substituto. Não executar `reset`, `checkout`, remoção recursiva, limpeza, alteração de banco, criação de migration ou restauração de backup sem autorização literal e alvo validado.

## 7. Gates de qualidade e liberação

Uma etapa só pode ser liberada quando os gates aplicáveis tiverem evidência independente:

1. revisão arquitetural e escopo;
2. segurança conforme o modo aprovado: na evolução multiusuário/multi-tenant, autenticação, autorização por ação, escopo de queryset, negação por ID e HTMX; sem exigir camada de autorização ou login na V1 local de usuário único;
3. testes Django focados e regressão;
4. `manage.py check`, migrations sem drift e execução autorizada das migrations;
5. `ruff` e `mypy` limpos no runtime declarado;
6. invariantes financeiras com `Decimal`, atomicidade, idempotência e auditoria;
7. backup SQLite, integridade e restauração testados sem alterar dados de produção;
8. conformidade com PRD e schema, com divergências registradas;
9. revisão independente do diff e do relatório.

No baseline da inspeção histórica, `manage.py check` passou; `makemigrations --check --dry-run` informou “No changes detected”; `manage.py test --verbosity 2` executou 7 testes e terminou `OK` em 0,113 s. `ruff` e `mypy` não foram encontrados no PATH. Esses resultados não são PASS de autorização, RLS, HTMX, release ou conformidade integral.

## 8. Política canônica de checkpoint

- `CHECKPOINT_FILE=docs/PROJECT_STATE.md`;
- `CHECKPOINT_WRITER_COUNT=1`;
- `CANONICAL_CHECKPOINT_WRITER=FINANPE-CHECKPOINT-SCHEDULER-012`;
- `CHECKPOINT_BLOCKS_PROGRESS=NO`;
- `CHECKPOINT_REMAINS_MANDATORY=YES`.

**O Coordenador decide o estado; o auditor produz evidência; o Scheduler persiste o estado. Nenhum substitui o outro.**

### Target canônico e candidato

`LAST_CANONICAL_INDEPENDENTLY_AUDITED_SHA` é diferente de `CURRENT_CANDIDATE_SHA`: o primeiro identifica o último target canônico auditado independentemente; o segundo identifica o candidato atual. Implementação sozinha não promove target. Quando auditoria independente for gate obrigatório, candidato somente vira canônico após `INDEPENDENT_AUDIT` → `COORDINATOR_VALIDATION`. `IMPLEMENTER=PASS` não equivale a `CANONICAL_TARGET`.

### Histórico e reconciliação

`CHECKPOINT HISTORY` é append-only: IDs únicos e sequenciais; não renumerar histórico, não apagar FAIL antigo após PASS posterior e não reescrever o passado. Ausência de checkpoint exige reconciliação pelo Scheduler, criando somente checkpoints faltantes, sem duplicação.

Prompt enviado não prova execução; relatório recebido não prova persistência. Git continua sendo prova de código/target; checkpoint não substitui Git nem auditoria.

Cada checkpoint deve conter: `CHECKPOINT_ID`, data/hora e timezone, repositório/caminho, branch/worktree, SHA, escopo, estado antes/depois, decisões aprovadas, fontes consultadas, comandos e saídas, gates por classificação, pendências, riscos, bloqueios, `NEXT_ACTION`, `NEXT_AGENT`, autorização necessária e `STOP_CONDITION`.

O checkpoint não pode transformar “não verificado” em “passou”, nem fechar uma pendência técnica sem evidência do gate correspondente. O próximo agente deve conseguir repetir os comandos no mesmo estado ou declarar a diferença de ambiente.

### Contradição objetiva

`CONTRADICTION=YES` somente quando houver incompatibilidade objetiva de estado, por exemplo: SHA real diferente do registrado; PASS registrado onde a auditoria validada foi FAIL; decisão do Founder invertida; candidato não auditado promovido a canônico; checkpoint duplicado incompatível.

Não usar `CONTRADICTION` para estilo, warning, formatação, nomenclatura ou diferença descritiva sem impacto de estado. Contradição real pode interromper progressão e exigir reconciliação antes da continuidade.

### Checkpoint obrigatório e não bloqueante

Após auditoria validada, o fluxo é:

```text
AUDITORIA VALIDADA
├── Scheduler registra checkpoint
└── Coordenador libera próximo gate técnico
```

Essas ações podem ocorrer em paralelo. O checkpoint permanece obrigatório, mas não deve criar espera burocrática. Somente `CONTRADICTION` real de estado pode exigir reconciliação antes da continuidade; a falta isolada de persistência não bloqueia o próximo gate técnico.

### Gate visual obrigatório

Para qualquer frontend novo ou mudança visual relevante: `FRONTEND_PROTOTYPE_REQUIRED=YES`, `FOUNDER_VISUAL_APPROVAL_REQUIRED=YES` e `FRONTEND_IMPLEMENTATION_BEFORE_APPROVAL=PROHIBITED`.

Fluxo obrigatório: `REQUIREMENT` → `VISUAL_PROTOTYPE` → `FOUNDER_REVIEW` → `FOUNDER_EXPLICIT_APPROVAL` → `IMPLEMENTATION` → `IMPLEMENTED_VS_APPROVED_PROTOTYPE_COMPARISON` → `TESTS / AUDIT`.

Silêncio do Founder não significa aprovação. Depois da implementação, `IMPLEMENTED_VS_APPROVED_PROTOTYPE_COMPARISON=REQUIRED`.

## 9. Lacunas desta inspeção e próximos passos autorizáveis

Lacunas confirmadas na inspeção histórica: ausência de governança formal além de `.cursorrules`; ausência de camada web; ausência de autorização por ação e escopo; ausência de testes de negação/HTMX; ausência de `ruff`/`mypy`; ausência de identidade Git verificável naquele ambiente; ausência de prova de RLS PostgreSQL; ausência de registro de auditoria/idempotency key nos services observados.

A recomendação da inspeção original era obter decisão de escopo e autorização para desenhar o modelo de usuários/ações/escopos. A decisão posterior do Founder aprovou a V1 local de usuário único sem login; esse desenho de autorização fica condicionado à evolução futura correspondente e não bloqueia, por si só, a V1. O inventário histórico não autoriza implementar endpoints, migrations, PostgreSQL ou Passo 4; qualquer frontend novo ou mudança visual relevante depende do gate visual acima. O estado operacional e os checkpoints faltantes serão reconciliados exclusivamente pelo Scheduler, sem edição de `docs/PROJECT_STATE.md` nesta composição.
