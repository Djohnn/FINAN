# FINANEP — Governança, autorização e protocolo anti-alucinação

**Status deste documento:** inventário e baseline documental; não autoriza implementação funcional.

**Data da inspeção:** 2026-10-19 (America/Sao_Paulo)

## 1. Escopo e evidência da inspeção

Foram inspecionados:

- `.cursorrules`;
- `docs/PRD_CONTEXT.md`, `docs/DATABASE_SCHEMA.md` e `docs/ROADMAP_PROMPTS.md`;
- `core_config/`, `apps/`, `templates/`, `tests/` e `scripts_windows/`;
- migrations, `manage.py`, `gerar_governanca.py`, settings e URLs;
- grafo existente em `graphify-out/` e consultas Graphify de arquitetura e autorização.

Não foi encontrado `AGENTS.md` no repositório. Não há `views.py`, `selectors.py`, `forms.py`, templates ou URLs de domínio na árvore inspecionada; `core_config/urls.py` expõe somente `/admin/`.

O diretório não foi reconhecido como worktree Git nesta execução: `git status`, `git rev-parse HEAD` e `git branch --show-current` falharam com “not a git repository”. Portanto branch, worktree e SHA são **BLOQUEADOS / NÃO VERIFICADOS**, não podem ser inventados nem usados como identidade de mudança.

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

### Estado confirmado

- Django `auth`, `sessions`, `AuthenticationMiddleware` e `CsrfViewMiddleware` estão habilitados em `core_config/settings.py:33-57`.
- O banco configurado é SQLite em `core_config/settings.py:83-87`.
- Existem as entidades padrão `User`, `Group` e `Permission` por migrations Django; não foram encontrados papéis de negócio, permissões customizadas, escopos por organização/filial ou filtros de queryset por usuário.
- O único endpoint exposto é `/admin/` em `core_config/urls.py:20-22`; não há endpoints HTMX implementados.
- SQLite não fornece RLS nativo. Não há middleware, backend de autorização, manager/queryset escopado ou proteção de acesso direto a registros confirmados na árvore.

### Política sem inventar privilégios

Nenhum papel de negócio é criado ou presumido nesta baseline. `is_staff`, `is_superuser`, grupos e permissões Django só podem ser usados conforme evidência e aprovação explícita; não equivalem automaticamente a um papel operacional.

Antes de expor qualquer ação web, o desenho aprovado deve definir, por ação:

1. identidade autenticada e política de sessão;
2. permissão mínima da ação;
3. escopo do queryset e validação de posse/relacionamentos;
4. proteção contra acesso direto por ID e enumeração de registros;
5. resposta de negação consistente, inclusive para requisições HTMX;
6. teste positivo e teste de negação para cada ação sensível.

Qualquer mudança que altere comportamento de autorização exige aprovação antes da implementação. A ausência de RLS em SQLite deve ser compensada por controles Django explícitos, mas isso é uma proposta de desenho, não uma prova de que o controle já existe.

### Migração futura para PostgreSQL

Uma migração futura pode adicionar PostgreSQL com RLS após decisão arquitetural aprovada, incluindo: modelo de escopo, contexto de sessão seguro, políticas `USING`/`WITH CHECK`, papel de runtime sem privilégios administrativos, cobertura de relações e testes de bypass. RLS não substitui autorização de ação nem validação de posse de ForeignKey. Nenhuma migration ou configuração PostgreSQL é autorizada por este documento.

## 5. Agentes e coordenação

Os papéis abaixo são papéis de processo, não papéis de usuário do sistema:

- **Executor:** altera somente os arquivos explicitamente autorizados, consulta Graphify antes de editar, preserva dados/migrations e para diante de escopo ambíguo, segredo exposto, divergência arquitetural ou falta de autorização.
- **Revisor independente:** reproduz a evidência a partir do estado identificado, revisa diff e critérios de aceite sem aceitar alegação do executor como prova; não altera o escopo para fazer o resultado passar.
- **Coordenador:** define escopo e gates, registra decisões, resolve divergências somente com aprovação e consolida o checkpoint. Agenda não é autorização.

Contrato mínimo de entrega: resumo; arquivos e linhas; estado antes/depois; comandos completos; saída bruta; classificação de cada resultado; decisões; pendências; riscos; próximo passo. Um teste sem saída do runner não é prova de passagem.

Proibições: modificar código funcional, dados, migrations, backups, histórico Git, permissões, credenciais ou ambiente fora do escopo; executar comandos destrutivos; mascarar falha como sucesso; imprimir ou persistir segredos; declarar integração, produção ou conformidade com base apenas em teste unitário.

## 6. Controle de alterações

Antes de qualquer alteração autorizada, registrar: caminho do repositório, branch/worktree, SHA, estado de limpeza, escopo autorizado, arquivos permitidos, banco/ambiente e comando de verificação. Depois, registrar os mesmos campos, diff, caminhos alterados e evidência dos gates.

Sem Git verificável, o estado deve ser **BLOQUEADO** para qualquer operação que dependa de branch/SHA. Não usar cópia externa, nome de pasta ou timestamp como substituto. Não executar `reset`, `checkout`, remoção recursiva, limpeza, alteração de banco, criação de migration ou restauração de backup sem autorização literal e alvo validado.

## 7. Gates de qualidade e liberação

Uma etapa só pode ser liberada quando os gates aplicáveis tiverem evidência independente:

1. revisão arquitetural e escopo;
2. segurança: autenticação, autorização por ação, escopo de queryset, negação por ID e HTMX;
3. testes Django focados e regressão;
4. `manage.py check`, migrations sem drift e execução autorizada das migrations;
5. `ruff` e `mypy` limpos no runtime declarado;
6. invariantes financeiras com `Decimal`, atomicidade, idempotência e auditoria;
7. backup SQLite, integridade e restauração testados sem alterar dados de produção;
8. conformidade com PRD e schema, com divergências registradas;
9. revisão independente do diff e do relatório.

No baseline atual, `manage.py check` passou; `makemigrations --check --dry-run` informou “No changes detected”; `manage.py test --verbosity 2` executou 7 testes e terminou `OK` em 0,113 s. `ruff` e `mypy` não foram encontrados no PATH. Esses resultados não são PASS de autorização, RLS, HTMX, release ou conformidade integral.

## 8. Checkpoint reproduzível

Cada checkpoint deve conter, em formato append-only:

`CHECKPOINT_ID`, data/hora e timezone, repositório/caminho, branch/worktree, SHA, escopo, estado antes/depois, decisões aprovadas, fontes consultadas, comandos e saídas, gates por classificação, pendências, riscos, bloqueios, `NEXT_ACTION`, `NEXT_AGENT`, autorização necessária e `STOP_CONDITION`.

O checkpoint não pode transformar “não verificado” em “passou”, nem fechar uma pendência técnica sem evidência do gate correspondente. O próximo agente deve conseguir repetir os comandos no mesmo estado ou declarar a diferença de ambiente.

## 9. Lacunas desta inspeção e próximos passos autorizáveis

Lacunas confirmadas: ausência de governança formal além de `.cursorrules`; ausência de camada web; ausência de autorização por ação e escopo; ausência de testes de negação/HTMX; ausência de `ruff`/`mypy`; ausência de identidade Git verificável; ausência de prova de RLS PostgreSQL; ausência de registro de auditoria/idempotency key nos services observados.

O próximo passo seguro é uma decisão de escopo e autorização para desenhar, em documento separado ou alteração aprovada, o modelo de usuários/ações/escopos. Não iniciar implementação de autorização, endpoints, migrations, PostgreSQL ou Passo 4 com base somente neste inventário.
