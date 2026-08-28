"""Rotas da Vima.

⚠️ **Sem `require_module`, de propósito.** O briefing não é um módulo entre os outros: é a
leitura do dia de QUALQUER usuário, e o recorte de permissão já acontece um nível abaixo, no
dado (`vima/permissions.py`). Exigir um módulo aqui bloquearia o funcionário inteiro em vez de
lhe entregar o briefing do que ele pode ver.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.tenancy import CurrentUser, get_current_user, get_tenant_db
from app.modules.vima import pergunta as pergunta_service
from app.modules.vima import service
from app.modules.vima.schemas import BriefingOut, PerguntaIn, PerguntaOut, to_out

router = APIRouter(prefix="/vima", tags=["vima"])


@router.get("/briefing", response_model=BriefingOut)
def briefing(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
) -> BriefingOut:
    """O briefing de hoje. Gera na primeira leitura do dia; nas seguintes, relê o gravado."""
    return to_out(service.gerar_ou_ler(db, user=user))


@router.post("/briefing/{briefing_id}/read", response_model=BriefingOut)
def marcar_lido(
    briefing_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
) -> BriefingOut:
    """Marca como lido. É o que fecha a janela do briefing seguinte — ver `_inicio_da_janela`."""
    try:
        return to_out(service.marcar_lido(db, briefing_id=briefing_id, user=user))
    except service.VimaError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/pergunta", response_model=PerguntaOut)
def perguntar(
    corpo: PerguntaIn,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
) -> PerguntaOut:
    """O dono pergunta, a Vima responde consultando os dados reais. Sem persistência: o
    histórico vem do front a cada chamada (ver spec 2026-08-28)."""
    historico = [
        pergunta_service.Turno(papel=t.papel, texto=t.texto) for t in corpo.historico
    ]
    resultado = pergunta_service.responder(
        db, user=user, pergunta=corpo.texto, historico=historico
    )
    return PerguntaOut(resposta=resultado.texto, por_ia=resultado.por_ia)
