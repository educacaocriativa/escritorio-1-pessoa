import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.modules import ALL_ROUTERS
from app.modules.notifications.service import register as register_notifications

# Sem isto, o root logger fica sem handler (só o "lastResort" do Python, WARNING+ pra stderr) —
# logger.info/exception de core/email.py, core/whatsapp.py, core/payment_gateway.py etc. nunca
# aparecem em `docker logs`. Mesmo padrão já usado em app/worker.py.
logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="e1p API",
    description="Backend multi-tenant da plataforma e1p (Empresa de 1 Pessoa)",
    version="0.0.0",
)

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

# Liga os assinantes do barramento de eventos (ex.: WhatsApp ao mover card no CRM).
register_notifications()


@app.get("/health", tags=["infra"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": "e1p-api", "env": settings.environment}
