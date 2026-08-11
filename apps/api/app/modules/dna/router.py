"""Rotas do DNA da Empresa.

⚠️ **`require_module("settings")` aqui, e não filtro no dado.** É o oposto da decisão do
`vima/router.py`, e de propósito: lá o recorte é por LINHA (o funcionário recebe o briefing do
que ele pode ver); aqui a superfície inteira é da empresa, então bloquear a rota é a resposta
certa. `require_module` já dá owner-vê-tudo e lista-vazia-vê-tudo.

**`hoje_do_tenant(db)` e `tenant_timezone(db)` são chamados AQUI**, e descem por parâmetro até
`cadencia`. É o que mantém aquele módulo puro e o gate de fuso satisfeito.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.core.tenancy import CurrentUser, get_tenant_db, require_module
from app.modules.dna import cadencia, catalog, eventos, service
from app.modules.dna.schemas import (
    NucleoEventoIn,
    PerguntaOut,
    PularIn,
    RespostaIn,
    to_out,
)
from app.modules.settings.service import hoje_do_tenant, tenant_timezone

router = APIRouter(prefix="/dna", tags=["dna"])


@router.get("/pendente", response_model=PerguntaOut | None)
def pendente(
    gancho: str = Query(...),
    user: CurrentUser = Depends(require_module("settings")),
    db: Session = Depends(get_tenant_db),
) -> PerguntaOut | None:
    """A pergunta deste gancho hoje — ou nada, que é o caso na maioria dos dias."""
    fuso = tenant_timezone(db)
    achada = cadencia.pendente(
        db, gancho=gancho, hoje=hoje_do_tenant(db), fuso=fuso
    )
    return to_out(achada) if achada else None


@router.get("/faltantes", response_model=list[PerguntaOut])
def faltantes(
    gancho: str = Query(...),
    user: CurrentUser = Depends(require_module("settings")),
    db: Session = Depends(get_tenant_db),
) -> list[PerguntaOut]:
    """Sem cadência: a sequência anunciada do núcleo e a lista da aba de configurações."""
    return [to_out(p) for p in cadencia.faltantes(db, gancho=gancho)]


@router.get("/catalogo", response_model=list[PerguntaOut])
def catalogo(
    user: CurrentUser = Depends(require_module("settings")),
) -> list[PerguntaOut]:
    """As 45, na ordem do catálogo.

    A aba de configurações é a única superfície SEM cadência — a pessoa escolheu estar ali, e
    esconder pergunta de quem foi procurá-la é hostil.
    """
    return [to_out(p) for p in catalog.PERGUNTAS]


@router.get("/respostas")
def respostas(
    user: CurrentUser = Depends(require_module("settings")),
    db: Session = Depends(get_tenant_db),
) -> dict[str, Any]:
    return service.respostas(db)


@router.post("/nucleo/{evento}", status_code=204)
def nucleo_evento(
    evento: str,
    corpo: NucleoEventoIn,
    user: CurrentUser = Depends(require_module("settings")),
    db: Session = Depends(get_tenant_db),
) -> Response:
    """O núcleo exibido e o núcleo abandonado — os dois eventos que o servidor não via.

    **UMA rota, com o evento no caminho**, validado contra `eventos.EVENTOS_DO_NUCLEO`: porta
    estreita contra um conjunto, como `service._validar` já faz contra o catálogo. Declarada
    ANTES de `PUT /{key}` e de `POST /{key}/pular`: as três não colidem hoje (aquelas exigem o
    literal `pular` no 3º segmento), mas rota específica antes de rota curinga é a ordem que não
    depende dessa análise continuar verdadeira.

    ⚠️ **Responde 204 e o front IGNORA a resposta.** Telemetria não pode trancar a entrada do
    produto (§6.2): quem chama dispara e segue. É por isso que não há corpo de resposta a
    desenhar — não existe consumidor para ele.

    ⚠️ **O caminho de erro grava NADA, e é isso que o torna distinguível.** Esta rota exige o
    módulo `settings`; um sub-usuário sem ele toma 403 e não produz evento. Como o front só emite
    `open` DEPOIS de `GET /dna/faltantes` ter sucesso, **ausência de `open` ⇒ a pessoa nunca
    entrou** — verdade derivada, sem inventar um terceiro evento.
    """
    action = eventos.EVENTOS_DO_NUCLEO.get(evento)
    if action is None:
        raise HTTPException(
            status_code=404,
            detail=f"evento '{evento}' não existe; são {sorted(eventos.EVENTOS_DO_NUCLEO)}",
        )

    alvo = ""
    if action == eventos.ACTION_OPEN:
        # O denominador é gravado porque NÃO é derivável: `faltantes` devolve só as não
        # respondidas (na 2ª visita são 4, não 6) e `catalog.NUCLEO` pode crescer.
        if corpo.exibidas is None or corpo.exibidas < 1:
            raise HTTPException(
                status_code=422,
                detail="'exibidas' é obrigatório no open: é a evidência do que a pessoa viu",
            )
        alvo = str(corpo.exibidas)

    eventos.registrar(
        db, tenant_id=user.tenant_id, actor=user.user_id, action=action, target=alvo
    )
    db.commit()
    return Response(status_code=204)


@router.put("/{key}", response_model=PerguntaOut)
def responder(
    key: str,
    corpo: RespostaIn,
    user: CurrentUser = Depends(require_module("settings")),
    db: Session = Depends(get_tenant_db),
) -> PerguntaOut:
    try:
        service.responder(
            db, tenant_id=user.tenant_id, key=key, valor=corpo.valor,
            user_id=user.user_id, source=corpo.source,
        )
    except service.DnaError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return to_out(catalog.POR_KEY[key])


@router.post("/{key}/pular", response_model=PerguntaOut)
def pular(
    key: str,
    corpo: PularIn,
    user: CurrentUser = Depends(require_module("settings")),
    db: Session = Depends(get_tenant_db),
) -> PerguntaOut:
    try:
        service.pular(
            db, tenant_id=user.tenant_id, key=key, user_id=user.user_id, source=corpo.source
        )
    except service.DnaError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return to_out(catalog.POR_KEY[key])
