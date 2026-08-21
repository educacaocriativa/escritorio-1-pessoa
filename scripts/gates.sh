#!/usr/bin/env bash
# O ALVO ÚNICO das suítes pesadas — encadeia EM SÉRIE o que não pode se sobrepor (issue #162).
#
# ── POR QUE UM ALVO ÚNICO, E NÃO TRÊS COMANDOS SOLTOS ────────────────────────────────────────────
# `pytest -q`, `pytest -m rls_e2e` (Docker) e `pnpm e2e` rodando AO MESMO TEMPO inventam falhas:
# testes que passam isolados ficam vermelhos, e as mensagens são `AssertionError` e
# `locator not found` — exatamente o que uma regressão de VERDADE diria. Quem economiza relógio
# rodando as três em paralelo investiga um bug que não existe, ou pior: cataloga como "aquele
# flake" uma quebra que era real. Observado em duas sessões independentes durante o #146 (PR #158).
#
# O único sinal secundário é o TEMPO — e ninguém o lê no meio de uma investigação. Números CITADOS
# da issue #162 (medidos lá, NÃO remedidos aqui): sob concorrência a `pytest -q` foi de 21min para
# 48min, e o Playwright de 1,9min para 9,2min. Por isso este script IMPRIME o tempo de cada etapa:
# o sinal fraco passa a ficar escrito na tela em vez de depender de alguém lembrar dele.
#
# É a MESMA classe que o #147 (PR #148) já fechou DENTRO do Playwright com `workers: 1` por padrão
# — "o paralelo inventa falhas", ver o cabeçalho de `apps/web/playwright.config.ts` — e a mesma que
# o `mutation.yml` já fecha com `concurrency:` ("duas corridas simultâneas disputariam os mesmos
# vCPU e a segunda mediria contenção de CPU, não qualidade de teste"). O que faltava era a mesma
# proteção ENTRE as suítes. Este arquivo é ela.
#
# ⚠️ ESTE SCRIPT NÃO É UM LOCK. Ele torna o modo certo o mais fácil; não impede que alguém abra
# outro terminal e rode `pnpm e2e` por cima — nem que outra worktree do mesmo repo faça isso. A
# regra escrita, com o mecanismo da falha, está no CLAUDE.md §5.5.
#
# ── A ORDEM NÃO É ARBITRÁRIA ─────────────────────────────────────────────────────────────────────
# É a mesma do `.github/workflows/ci.yml`, do mais barato para o mais caro: lint + suíte limpa (sem
# Docker) → RLS no Postgres real (Docker) → régua de 360px (sobe um Vite numa porta). Falha rápido:
# a etapa barata reprova primeiro e as caras nem começam.
#
# O teste de MUTAÇÃO (`pnpm --filter @e1p/web mutation`, ~21min) NÃO entra aqui de propósito: é
# diagnóstico periódico da qualidade da suíte, não portaria de mudança — a mesma razão pela qual
# ele mora num workflow noturno e não no `ci.yml` (ver o cabeçalho de `mutation.yml`). Se você o
# rodar à mão, ele conta como quarta suíte pesada: não o sobreponha a estas três.
#
# ── FUSO: ESTE SCRIPT NÃO MEXE EM `TZ`, DE PROPÓSITO ─────────────────────────────────────────────
# `TZ=UTC` NÃO troca o fuso no Windows: a variável chega ao Python, mas o fuso local não muda
# (verificado; `apps/api/tests/test_search_deep.py` documenta). Um `TZ=...` na frente destas suítes
# daria a impressão de estar exercitando fuso sem exercitar nada. A régua do fuso é a do CLAUDE.md
# §5.2 (mock do fuso do TENANT), nunca a variável de ambiente da máquina.
#
# ── USO ──────────────────────────────────────────────────────────────────────────────────────────
#   bash scripts/gates.sh                 # as três, em série
#   E2E_PORT=5373 bash scripts/gates.sh   # em OUTRA worktree (a 5273 colide entre checkouts, #123)
#
# ⚠️ Dívida HERDADA da etapa 1, já registrada no CLAUDE.md: `scripts/check.sh` resolve `ruff`/
# `python` do PATH (que pode não ser o do venv) e mascara falha do frontend com `|| true` no
# vitest. Enquanto isso não for corrigido, a etapa 1 pode ficar verde com o vitest vermelho. Este
# script não conserta nem piora essa dívida — mas não a esconde de quem lê.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# O junit da etapa 2 mora em `.pytest_cache/`, que o .gitignore já ignora — nada de artefato solto
# na árvore, e nada de caminho POSIX de `mktemp` chegando a um Python de Windows.
RLS_XML_REL=".pytest_cache/gates-rls-results.xml"
RLS_XML="apps/api/$RLS_XML_REL"

ETAPAS_TOTAL=3
etapa=0
inicio_total=$SECONDS

anuncia() {
  etapa=$((etapa + 1))
  echo ""
  echo "=============================================================================="
  echo "> Etapa $etapa/$ETAPAS_TOTAL — $1"
  echo "=============================================================================="
}

# Cronometra e IMPRIME, inclusive quando a etapa falha: o tempo é o único sinal secundário de
# contaminação (ver cabeçalho), e ele só serve se estiver na tela.
cronometra() {
  local rotulo="$1"; shift
  local inicio=$SECONDS rc=0
  "$@" || rc=$?
  echo "[tempo] $rotulo: $((SECONDS - inicio))s (exit $rc)"
  return "$rc"
}

echo "=============================================================================="
echo "  gates.sh — as três suítes pesadas, UMA DE CADA VEZ (issue #162)"
echo ""
echo "  AVISO: não rode nenhuma suíte em outro terminal enquanto isto roda. Sob"
echo "  concorrência elas se contaminam e a falha fica INDISTINGUÍVEL de regressão"
echo "  real (AssertionError / locator not found). Ver CLAUDE.md §5.5."
echo "=============================================================================="

# ── Preflight ────────────────────────────────────────────────────────────────────────────────────
# Só o que as etapas TARDIAS exigem. Descobrir na etapa 3 que falta `pnpm`, depois de 20 minutos de
# etapa 1, é exatamente o desperdício que "falha rápido" existe para evitar.
faltando=()
command -v pnpm >/dev/null 2>&1 || faltando+=("pnpm (etapa 3)")
docker info >/dev/null 2>&1 || faltando+=("Docker respondendo (etapa 2)")
if [ "${#faltando[@]}" -gt 0 ]; then
  echo ""
  echo "FALHOU no preflight — falta:"
  for f in "${faltando[@]}"; do echo "    - $f"; done
  echo ""
  echo "  PULAR uma destas etapas é ficar verde sem ter exercido o que ela protege. Sem Docker,"
  echo "  os arquivos rls_e2e viram SKIPPED na coleta e o pytest devolve 5 — verde sem RLS"
  echo "  nenhuma exercida. Resolva e rode de novo; este script não se pula sozinho."
  exit 1
fi

# ── Etapa 1 — lint + types + suíte limpa (sem Docker) ────────────────────────────────────────────
anuncia "lint + types + suíte limpa  (scripts/check.sh)"
cronometra "check.sh" bash scripts/check.sh

# ── Etapa 2 — isolamento cross-tenant no Postgres real ───────────────────────────────────────────
# Filtra por PROPRIEDADE (o marker), NÃO por arquivo nomeado — mesma escolha do job
# `cross-tenant-rls` do ci.yml, para que um arquivo `test_*_rls.py` novo entre sozinho.
etapa_rls() {
  local rc=0
  mkdir -p "apps/api/.pytest_cache"
  ( cd apps/api && python -m pytest -q -m rls_e2e --junitxml="$RLS_XML_REL" ) || rc=$?
  # rc: 0=passaram · 1=algum FALHOU · 5=nenhum rodou/coletado · outros=erro de coleta/uso.
  # Falha real (rc != 0 e != 5) derruba já aqui; rc=0 e rc=5 seguem para a guarda anti-skip.
  if [ "$rc" -ne 0 ] && [ "$rc" -ne 5 ]; then return "$rc"; fi
  # Guarda anti-skip-silencioso — a MESMA do ci.yml (Story 7.1): o exit code do pytest sozinho não
  # basta, porque cada arquivo rls_e2e abre com `importorskip("testcontainers.postgres")`. Exigimos
  # que >= 1 teste tenha REALMENTE executado (coletado E não-skipped). O one-liner abaixo é o
  # MESMO do ci.yml, de propósito: uma convenção só, e quem mudar uma metade acha a outra por grep.
  python -c 'import sys,xml.etree.ElementTree as ET; r=ET.parse(sys.argv[1]).getroot(); s=r if r.tag=="testsuite" else r.find("testsuite"); t=int(s.get("tests",0)); k=int(s.get("skipped",0)); ex=t-k; print(f"rls_e2e: coletados={t} executados={ex} skipped={k}"); ok=ex>=1; ok or print("ERRO: nenhum teste rls_e2e executou (todos SKIPPED ou zero coletados). RLS real nao foi exercida — falhando em vez de passar em silencio."); sys.exit(0 if ok else 1)' "$RLS_XML"
}
anuncia "isolamento cross-tenant no Postgres real  (pytest -m rls_e2e)"
cronometra "pytest -m rls_e2e" etapa_rls

# ── Etapa 3 — régua de layout em 360px ───────────────────────────────────────────────────────────
# `E2E_PORT` passa adiante sozinho (é lido pelo playwright.config.ts). Em worktree paralela, use
# uma porta própria: `reuseExistingServer` é `false`, então porta ocupada vira erro alto — o que é
# o comportamento certo, e não o disfarce de medir o branch alheio (#123).
anuncia "régua de layout em 360px  (Playwright, workers: 1 por padrão — #147)"
cronometra "pnpm e2e" pnpm --filter @e1p/web e2e

echo ""
echo "=============================================================================="
echo "OK — as $ETAPAS_TOTAL suítes pesadas passaram, em série. Total: $((SECONDS - inicio_total))s"
echo "=============================================================================="
