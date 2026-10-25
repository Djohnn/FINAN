# Contrato operacional do FinanPE

Este arquivo é um índice compacto e obrigatório. As regras detalhadas e o contexto canônico permanecem em `docs/GOVERNANCE_FINANPE.md`, `docs/PRD_CONTEXT.md`, `docs/DATABASE_SCHEMA.md`, `docs/ROADMAP_PROMPTS.md` e `.cursorrules`.

## Fontes e escopo

Para decisões normativas, a hierarquia é: **decisões do Founder > GOVERNANCE_FINANPE > PRD / DATABASE_SCHEMA / ROADMAP > AGENTS.md / .cursorrules > código executável > prompts de tarefa > ferramentas/Skills**. O código é evidência do comportamento atualmente implementado; não substitui uma decisão normativa nem autoriza inventar comportamento ausente. Contradições de regra de negócio devem ser registradas e interromper a mudança até decisão autorizada.

Antes de editar, leia a governança e os documentos canônicos aplicáveis. Não invente regras de negócio, papéis, permissões, contratos, campos ou integrações. Trabalhe somente na worktree e no SHA fornecidos; use escopo mínimo, sem push automático. Missões relevantes devem usar worktree isolada e SHA completo. Não faça merge, rebase, cherry-pick, reset, clean, stash ou alteração destrutiva sem autorização explícita.

## Implementação segura

- Mutações de negócio passam por `services`; views/URLs transportam e validam entrada.
- Use `Decimal` para dinheiro e migrations seguras; não altere banco real em testes.
- Proteja dados, credenciais e parâmetros sensíveis; nunca os imprima ou persista.
- Não implemente autorização, usuários, papéis ou RLS por inferência. O estado atual é `AUTHORIZATION_LAYER_IMPLEMENTED=NO` e `NATIVE_RLS_AVAILABLE=NO_FOR_SQLITE`; SQLite não possui RLS nativo equivalente ao PostgreSQL. Qualquer autorização futura deve definir ação, identidade, escopo de queryset e proteção de registros; migração para PostgreSQL/RLS exige decisão arquitetural autorizada.
- Quando o prompt proibir delegação, subagentes são proibidos. Sugestões de ferramenta ou Skill não ampliam escopo nem autorização.

## Fluxo canônico de validação (efetivo em 2026-10-25)

- `main-validation` é a branch intermediária para trabalho auditado e integração; pode conter backend antes do frontend e módulos incompletos. É a fonte do FinanQA, não é produção nem a versão final aprovada.
- `main` é a branch final de release: não recebe desenvolvimento direto, feature não aprovada, force-push ou auto-merge. Só recebe o SHA exato aprovado pelo Founder.
- Gates separados: `TECHNICAL_PASS`, `INTEGRATION_VALIDATION_PASS`, `FOUNDER_LIVE_QA_PASS` e `FOUNDER_PROMOTION_APPROVAL`. Testes backend passando não autorizam promoção.
- Fluxo backend-first: worktree isolada → testes/auditoria independente → autorização e publicação em `main-validation` → frontend separado e auditado → integração → aplicação real no SHA exato → FinanQA → QA manual do Founder → correção/auditoria/revalidação se necessário → promoção autorizada do mesmo SHA.
- FinanQA obrigatório: aplicação Django real, `127.0.0.1:5500`, `FINANQA_SOURCE_BRANCH=main-validation`, `FINANQA_SOURCE_SHA=EXACT_COMMIT_UNDER_QA`, banco descartável isolado e uso do banco de produção proibido. Screenshots e testes automatizados são evidência de apoio; somente o Founder pode declarar `FOUNDER_LIVE_QA=PASS` ou `REJECTED`.
- Promoção exige confirmação do SHA aprovado, HEAD exato remoto de `main-validation`, auditoria independente, identidade/ancestralidade das branches, segurança do banco, preservação dos arquivos locais do Founder e ausência de commits posteriores. Mudança interveniente invalida a aprovação; não há herança silenciosa.
- Governança/documentação também exige revisão/QA e autorização do Founder para publicação em `main`; não há isenção automática. O gate de protótipo visual antes do frontend e o live QA depois da integração permanecem distintos.
- Handoff: registrar SHAs de `main`, `main-validation` e candidato, worktrees, auditoria, FinanQA/banco, QA e autorização do Founder, findings, bloqueios, segurança do banco e próxima ação. Distinguir `PUBLISHED_TO_VALIDATION` de `PROMOTED_TO_MAIN`.
- Parar por SHA/branch divergente, QA ausente ou sem SHA exato, mudança posterior, auditoria pendente, banco de produção, risco a arquivos do Founder ou promoção fora do protocolo. Somente `FINANPE-CHECKPOINT-SCHEDULER-012` escreve `docs/PROJECT_STATE.md`; demais agentes não editam o checkpoint.

Detalhamento normativo: `docs/GOVERNANCE_FINANPE.md`, seção 10.

## Evidência e parada

Classifique decisões relevantes como `CONFIRMED`, `INFERRED`, `NOT_VERIFIED` ou `BLOCKED`. Diferencie `CLAIM` de `EVIDENCE` e informe evidência verificável: caminho, símbolo/linha quando disponível, comando, resultado real e SHA. Nunca declare `PASS` sem executar o teste e guardar sua saída bruta.

Pare se houver contradição canônica, necessidade de decisão do Founder, SHA/worktree inválidos, escopo maior que o autorizado, código funcional fora do escopo, alteração de banco/migration não autorizada, perda de dados, falha de teste ou necessidade de inventar autorização. Antes de concluir, apresente diff, caminhos alterados, comandos e resultados reais; auditor independente não altera o alvo auditado.
