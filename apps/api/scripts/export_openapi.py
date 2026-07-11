"""Exporta o schema OpenAPI do FastAPI para packages/shared-types/openapi.json.

Standalone: NÃO precisa do servidor rodando. O FastAPI monta o schema automaticamente a partir
das rotas / `response_model`, então basta importar o app e chamar `app.openapi()`. É a peça que
"elimina a manutenção manual" do shared-types (Story 4.5 / CLAUDE.md §6.1): rode-o (via
`pnpm generate:types` na raiz) sempre que um schema Pydantic do backend mudar.

Uso:
    python apps/api/scripts/export_openapi.py

Observação: `app.main` cria a Engine do SQLAlchemy a partir de `DATABASE_URL`. `create_engine`
importa o driver do dialeto — em ambiente sem `psycopg` (ex.: fora do container), rode com
`DATABASE_URL=sqlite://` que a exportação continua funcionando (não abre conexão real).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Garante que `app` seja importável mesmo rodando a partir da raiz do monorepo.
API_ROOT = Path(__file__).resolve().parents[1]  # .../apps/api
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.main import app  # noqa: E402 (import após ajustar sys.path)

REPO_ROOT = Path(__file__).resolve().parents[3]  # .../ (raiz do monorepo)
OUTPUT = REPO_ROOT / "packages" / "shared-types" / "openapi.json"


def main() -> None:
    schema = app.openapi()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"OpenAPI exportado para {OUTPUT}")


if __name__ == "__main__":
    main()
