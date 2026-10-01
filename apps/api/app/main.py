import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import composicao  # noqa: F401 — a fiacao e as guardas fail-closed rodam no import
from app.config import settings
from app.modules import ALL_ROUTERS

# Sem isto, o root logger fica sem handler (só o "lastResort" do Python, WARNING+ pra stderr) —
# logger.info/exception de core/email.py, core/whatsapp.py, core/payment_gateway.py etc. nunca
# aparecem em `docker logs`. Mesmo padrão já usado em app/worker.py.
logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="e1p API",
    description="Backend multi-tenant da plataforma e1p (Empresa de 1 Pessoa)",
    version="0.0.0",
)

# CORS só para o front do próprio e1p. NÃO há exceção para rota pública: a única que existia
# (`PublicLeadsCORSMiddleware`, CORS aberto para `/public/leads/*`) sobrou morta depois que a
# rota foi apagada no PR #270 e saiu em 2026-09-30. A ingestão nova (`/public/ingest/leads`) é
# servidor-a-servidor — o token de máquina não pode morar num navegador.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Módulos de negócio (vão sendo registrados conforme construídos — ver app/modules/__init__.py)
for router in ALL_ROUTERS:
    app.include_router(router)


@app.get("/health", tags=["infra"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": "e1p-api", "env": settings.environment}
