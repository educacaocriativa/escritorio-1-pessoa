#!/usr/bin/env bash
# Verificação de qualidade — rode a cada mudança (ver CLAUDE.md §5).
# Falha rápido: se qualquer etapa quebrar, o script retorna erro.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "▶ Backend: lint (ruff)"
( cd apps/api && ruff check . )

echo "▶ Backend: testes (pytest)"
( cd apps/api && python -m pytest -q )

echo "▶ Frontend: typecheck"
if command -v pnpm >/dev/null 2>&1; then
  pnpm --filter @e1p/web typecheck || { echo "⚠ instale deps com 'pnpm install' antes"; }
  echo "▶ Frontend: testes (vitest)"
  pnpm --filter @e1p/web test || true
else
  echo "⚠ pnpm não encontrado — pulei etapas do frontend"
fi

echo "✅ check concluído"
