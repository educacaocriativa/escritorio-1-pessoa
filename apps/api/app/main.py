import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.modules import ALL_ROUTERS
from app.modules.funnels.automation import register as register_funnel_automation
from app.modules.notifications.service import register as register_notifications


class PublicLeadsCORSMiddleware:
    """CORS aberto (qualquer origem) só para `POST /public/leads/*`.

    O `CORSMiddleware` global (abaixo) fica travado em `frontend_url` + `allow_credentials=True`
    — é o que protege a API autenticada. Mas o site externo de um cliente (ex.: doroeventos.com.br)
    precisa chamar essa rota via `fetch`/`<form>` de QUALQUER origem, sem cookie/credencial
    nenhuma. Em vez de afrouxar o middleware global (enfraqueceria tudo), este middleware ASGI
    puro fica ANTES dele na pilha (adicionado depois = mais externo, ver ordem do Starlette) e
    intercepta só esse prefixo: responde o preflight OPTIONS direto e injeta
    `Access-Control-Allow-Origin` na resposta real, sem tocar em mais nada.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/public/leads"):
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        origin = headers.get(b"origin", b"*")

        if scope["method"] == "OPTIONS":
            await send({
                "type": "http.response.start",
                "status": 204,
                "headers": [
                    (b"access-control-allow-origin", origin),
                    (b"access-control-allow-methods", b"POST, OPTIONS"),
                    (b"access-control-allow-headers", b"content-type"),
                    (b"access-control-max-age", b"600"),
                ],
            })
            await send({"type": "http.response.body", "body": b""})
            return

        async def _send(message):
            if message["type"] == "http.response.start":
                message["headers"] = [
                    *message.get("headers", []),
                    (b"access-control-allow-origin", origin),
                ]
            await send(message)

        await self.app(scope, receive, _send)

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
# Adicionado DEPOIS do CORSMiddleware global → fica MAIS EXTERNO na pilha (Starlette prepende
# a cada add_middleware), então intercepta /public/leads/* antes da política travada acima.
app.add_middleware(PublicLeadsCORSMiddleware)

# Módulos de negócio (vão sendo registrados conforme construídos — ver app/modules/__init__.py)
for router in ALL_ROUTERS:
    app.include_router(router)

# Liga os assinantes do barramento de eventos (ex.: WhatsApp ao mover card no CRM;
# auto-enroll no funil de vendas padrão ao criar lead).
register_notifications()
register_funnel_automation()


@app.get("/health", tags=["infra"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": "e1p-api", "env": settings.environment}
