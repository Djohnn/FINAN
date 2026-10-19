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

## Evidência e parada

Classifique decisões relevantes como `CONFIRMED`, `INFERRED`, `NOT_VERIFIED` ou `BLOCKED`. Diferencie `CLAIM` de `EVIDENCE` e informe evidência verificável: caminho, símbolo/linha quando disponível, comando, resultado real e SHA. Nunca declare `PASS` sem executar o teste e guardar sua saída bruta.

Pare se houver contradição canônica, necessidade de decisão do Founder, SHA/worktree inválidos, escopo maior que o autorizado, código funcional fora do escopo, alteração de banco/migration não autorizada, perda de dados, falha de teste ou necessidade de inventar autorização. Antes de concluir, apresente diff, caminhos alterados, comandos e resultados reais; auditor independente não altera o alvo auditado.
