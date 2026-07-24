# RUN-LOG: Financeiro — DRE em matriz + Lucratividade por Contrato

Pipeline informal (sem story/epic formal em `docs/stories/`), disparado direto na conversa.
Consolidado conforme `.claude/rules/handoff-consolidation.md` (5 handoffs `devops-to-devops`
consecutivos, mesmo tema). Handoff mais recente (2026-07-24T11-21-00Z) segue individual — é o
próximo a ser lido pela próxima sessão.

## Wave 1: descoberta + deploy do que já existia — 2026-07-23

**Status:** ✅ DONE
**Agente:** devops

### Delivered
- Usuário pediu "deploy"; investigação mostrou que não havia código novo (só 2 commits de
  docs/specs locais não pusheados: DRE-matriz-mensal e Lucratividade-por-Contrato).
- Push bloqueado por branch protection (4 status checks obrigatórios) — descoberta nova, não
  documentada em handoffs anteriores.
- PR #46 (docs-only) aberta, CI verde, squash-merge. Deploy na VPS (Hostinger,
  `e1p.doroeventos.com.br`): `8cb4832` → `6cb0c5c`.

### Decisões
- Toda vez que houver commits locais não pusheados, é preciso passar por PR + CI — push direto
  em `main` não funciona mais.
- Squash-merge diverge o `git status` local (commits antigos vs. squash novo) — resolvido com
  `git reset --hard origin/main` (seguro quando o conteúdo é idêntico).

### Original handoff
Arquivado: `.aiox/handoffs/_archive/financeiro-dre-matriz-lucratividade/handoff-2026-07-23T17-31-00Z.yaml`

---

## Wave 2: feature completa achada numa worktree órfã — 2026-07-23

**Status:** ✅ DONE
**Agente:** devops

### Delivered
- Usuário perguntou por que não via "Despesas & receitas"/Lucratividade no app (comparando com
  screenshot de outro app, Ksmv/AxisGov). Investigação achou a feature **inteira** (backend
  `dre.py`/`profitability.py` + testes + frontend `DrePage.tsx`/`LucratividadePage.tsx`) pronta
  numa branch/worktree local nunca integrada: `worktree-dre-matriz-e-lucratividade-contrato`
  (20 commits, nunca pushada).
- PR #47 (feature completa, 1 fix de lint) + PR #48 (correção não commitada achada na worktree
  pós-merge — guarda de race condition em `LucratividadePage.tsx`) — CI verde nas duas,
  squash-merge. Deploy real (rebuild de verdade): `main` `6cb0c5c` → `879a9c5` → `2ecc72f` na VPS.
- Worktree removida ao final (precisou PowerShell — `git worktree remove`/bash deu erro de OS
  em path longo).

### Decisões
- **Nunca rebase** uma branch de feature já mergeada via squash sobre a `main` pós-merge —
  22 commits reaplicados patch-a-patch colidiram com o squash mesmo com conteúdo idêntico.
  Caminho certo pra recuperar 1 commit avulso de uma branch já mergeada: nova branch a partir
  de `origin/main` + `git cherry-pick <commit>` (não o histórico todo).
- `gh pr view --json files` mostra o diff pelo merge-base HISTÓRICO — uma branch aberta antes
  de um squash-merge lista arquivos já idênticos em `main` como "changed" de novo. Não confiar
  nesse número sem checar se precisa rebase/cherry-pick antes de abrir PR.
- Nenhuma story formal criada em `docs/stories/` para esta feature — dívida de rastreabilidade
  (sugestão recorrente: story retroativa).

### Original handoff
Arquivado: `.aiox/handoffs/_archive/financeiro-dre-matriz-lucratividade/handoff-2026-07-23T18-05-00Z.yaml`

---

## Wave 3: limpeza pós-merge — 2026-07-23

**Status:** ✅ DONE
**Agente:** devops

### Delivered
- Usuário pediu "gera handoff e limpe". Achadas 2 branches remotas órfãs (PR #47/#48) que o
  `--delete-branch` não tinha conseguido apagar (erro de worktree bloqueou a limpeza local E
  aparentemente também a remota) — deletadas manualmente + `git fetch --prune`.
- Branch antiga de outra sessão (`worktree-crm-inserir-etapa-posicao`, já mergeada) também
  removida, após confirmação com o usuário.

### Decisões
- Depois de um merge que reportar erro de limpeza LOCAL, sempre conferir se a branch REMOTA
  também não foi apagada (`git fetch --prune` + checar) — não assumir que só porque o merge em
  si funcionou, o `--delete-branch` completou.
- VPS em 80% de disco — estável, sem ação necessária, mas monitorar.

### Original handoff
Arquivado: `.aiox/handoffs/_archive/financeiro-dre-matriz-lucratividade/handoff-2026-07-23T18-30-00Z.yaml`

---

## Wave 4: drill-down analítico da célula — 2026-07-24

**Status:** ✅ DONE
**Agente:** devops

### Delivered
- Usuário pediu uma tela (referência: screenshot de outro app) onde clicar num valor da matriz
  traz o analítico. Implementado do zero: backend (`DreMatrixRow.grupo_dre` + `matrix_cell_
  entries()` + `GET /financial-intelligence/dre/matrix/entries`) e frontend (células viram
  botões, drawer reaproveitando o padrão da Lucratividade).
- 23 testes novos no backend (782 total) + 2 arquivos de teste novos no frontend (142 total).
- **Validado manualmente no navegador** via stack Docker local — não só testes automatizados
  (regra do CLAUDE.md pra mudança de UI). Testado nos dois modos de agrupamento (`dre` e
  `cost_center`), confirmando que o filtro por centro de custo não vaza lançamentos entre
  centros.
- PR #51, CI verde, squash-merge, deploy: `main` `dbdec78` → `63b0761` na VPS.

### Decisões
- Achado (e corrigido) um bug de AMBIENTE local não relacionado à feature: volume Postgres
  local com `meta_media_id` já aplicado via DDL manual mas `alembic_version` desalinhada em
  `0054` (cenário JÁ documentado no docstring da migration 0055) — corrigido com `UPDATE
  alembic_version SET version_num='0055'` (bookkeeping, sem alterar dados). Pode se repetir em
  outra sessão que suba esse mesmo volume do zero.
- `DreMatrixRow.grupo_dre` (grupo de ORIGEM do lançamento) foi necessário pra evitar ambiguidade
  quando duas categorias homônimas existem em grupos DRE diferentes sob o mesmo centro de custo.
- Endpoint novo reusa o sentinel `"_unassigned"` já existente pro bucket sem centro de custo —
  sem mapeamento extra no frontend (`group.key` já serve direto como `cost_center_id`).

### Original handoff
Arquivado: `.aiox/handoffs/_archive/financeiro-dre-matriz-lucratividade/handoff-2026-07-24T10-58-00Z.yaml`

---

## Wave 5: TOTAL GERAL + INVESTIMENTO — 2026-07-24

**Status:** ✅ DONE
**Agente:** devops

### Delivered
- Usuário pediu: `TOTAL GERAL` antes do grupo Investimento + nova linha `TOTAL GERAL +
  INVESTIMENTO` (gasto total do período incluindo capex). Implementado 100% no frontend
  (`investmentTotals`/`splitGroupsAroundInvestment` em `dreMatrix.ts`) — os campos por linha já
  vinham da API da Wave 4, sem mudança de backend.
- 5 testes novos (147 total no frontend). Validado manualmente no navegador: com investimento
  de -R$7.833,75 e TOTAL GERAL de -R$561,07, a linha combinada mostrou -R$8.394,82 (bate), na
  posição certa.
- PR #52, CI verde, squash-merge, deploy: `main` `63b0761` → `16911ca` na VPS.
- Usuário também perguntou (dúvida conceitual, sem mudança de código): "baixa"/regime de caixa
  é `paid_at` (setado no `mark_paid`/webhook — quando o dinheiro de fato muda de mão) vs.
  regime de competência (`competence_date`, o que a DRE usa hoje) — confirmado que `paid_at`
  não aparece em NENHUM lugar da tela hoje (nem na matriz, nem no drawer). Usuário confirmou
  que era só dúvida conceitual, sem pedir a mudança de mostrar `paid_at` no drawer.

### Decisões
- `investmentTotals()` soma por `kind="informational"`, não pelo grupo "INVESTIMENTO" nomeado —
  funciona igual nos dois modos de agrupamento (em `cost_center` as linhas de investimento ficam
  espalhadas por vários centros, sem seção própria).
- Reordenação (`TOTAL GERAL` antes de Investimento) só acontece em `group_by=dre` — único modo
  onde Investimento é uma seção própria e sempre por último.

### Carry-forward
- Follow-up EM ABERTO, não pedido ainda: mostrar `paid_at` (data de baixa) no drawer de
  drill-down, ao lado do status — mudança pequena se o usuário pedir no futuro (dado já existe
  no banco, só falta expor no schema/render).
- Dívida de rastreabilidade repetida: nenhuma das 5 waves teve story formal em `docs/stories/`.
- VPS em ~80% de disco (Wave 3) — segue sem ação, mas cresce; reavaliar se cruzar ~90%.
- `docker-compose.monitoring.yml` sem nome de projeto próprio — warning de orphan container
  (Uptime Kuma) segue aparecendo em todo deploy; não urgente.

### Handoff ativo (NÃO arquivado — é o próximo a ler)
`.aiox/handoffs/handoff-devops-to-devops-2026-07-24T11-21-00Z.yaml`
