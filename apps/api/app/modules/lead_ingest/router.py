"""`POST /public/ingest/leads` — entrada servidor-a-servidor de leads com atribuição.

Usa `get_db` (sessão GLOBAL, sem tenant) SÓ para resolver a credencial em `machine_tokens`,
tabela global sem RLS — o mesmo uso legítimo do login sobre `users` e do Atalho do iOS sobre
`device_tokens`. Todo dado de negócio é lido e escrito numa `tenant_session` aberta com o
tenant DO TOKEN (nunca do corpo — spec §6.1), via `get_tenant_session_factory`, como a página
pública faz com o tenant do snapshot.

Sem CORS de propósito: o token de máquina não pode morar num navegador.
"""
from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session

from app.db.session import get_db, get_tenant_session_factory
from app.modules.lead_ingest import service
from app.modules.lead_ingest.schemas import IngestIn, IngestOut
from app.modules.machine_tokens import service as machine_tokens_service
from app.modules.machine_tokens.models import SCOPE_LEAD_INGEST, MachineToken

LIMITE_CORPO_BYTES = 64 * 1024


class RotaComLimiteDeCorpo(APIRoute):
    """Recusa com 413 corpo > 64 KB ANTES de o FastAPI lê-lo e validá-lo.

    `Toque`/`Pedido` aceitam campos extras que acabam na timeline; sem teto, um token vazado
    (ou um bug do site) enche o banco. Confere `Content-Length` e, para corpo sem ele (chunked),
    conta os bytes conforme chegam e aborta ao passar do teto.
    """

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            declarado = request.headers.get("content-length")
            if declarado and declarado.isdigit() and int(declarado) > LIMITE_CORPO_BYTES:
                raise _corpo_grande()
            lido = bytearray()
            async for pedaco in request.stream():
                lido.extend(pedaco)
                if len(lido) > LIMITE_CORPO_BYTES:
                    raise _corpo_grande()
            request._body = bytes(lido)  # o FastAPI reaproveita o corpo já lido
            return await original(request)

        return handler


def _corpo_grande() -> HTTPException:
    return HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Corpo grande demais")


router = APIRouter(
    prefix="/public/ingest", tags=["lead-ingest-public"], route_class=RotaComLimiteDeCorpo
)


def credencial_de_ingestao(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> MachineToken:
    """Resolvida ANTES do corpo: credencial ruim é 401 mesmo com corpo inválido."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credencial ausente")
    try:
        return machine_tokens_service.resolve(
            db, raw=authorization.split(" ", 1)[1].strip(), scope=SCOPE_LEAD_INGEST
        )
    except machine_tokens_service.MachineTokenError as e:
        raise HTTPException(e.status_code, str(e)) from e


@router.post("/leads", response_model=IngestOut, status_code=status.HTTP_201_CREATED)
def ingest_lead(
    dados: IngestIn,
    response: Response,
    credencial: MachineToken = Depends(credencial_de_ingestao),
    session_factory=Depends(get_tenant_session_factory),
) -> IngestOut:
    with session_factory(credencial.tenant_id) as tdb:
        resultado = service.ingest(tdb, tenant_id=credencial.tenant_id, dados=dados)
    if not resultado.processado:
        response.status_code = status.HTTP_200_OK
    return IngestOut(
        resultado="processado" if resultado.processado else "ja_processado",
        contato_id=resultado.contato_id,
    )
