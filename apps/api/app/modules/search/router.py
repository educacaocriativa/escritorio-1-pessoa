"""Busca global — a rota.

**Sem `require_module` como guarda da rota, e isso é deliberado.** A busca cruza sete módulos; um
guard só teria de escolher um deles e estaria errado nos outros seis. O RBAC entra como FILTRO por
entidade, dentro do serviço, com o MESMO critério de `require_module` — dono, ou `allowed_modules`
vazio, vê tudo (spec §6.4).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.tenancy import CurrentUser, get_current_user, get_tenant_db
from app.modules.search import service
from app.modules.search.schemas import SearchGroupOut, SearchItemOut, SearchOut

router = APIRouter(prefix="/search", tags=["search"])


def _modulos(user: CurrentUser) -> list[str]:
    """Mesma regra de `require_module`: dono, ou lista vazia, não tem restrição."""
    if user.role == "owner":
        return []
    return user.allowed_modules


@router.get("", response_model=SearchOut)
def search(
    q: str = Query(default=""),
    limit: int = Query(default=3, ge=1, le=50),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
) -> SearchOut:
    grupos = service.buscar(db, q=q, modulos_liberados=_modulos(user), limite=limit)
    return SearchOut(
        groups=[
            SearchGroupOut(
                type=g.tipo,
                has_more=g.tem_mais,
                total=g.total,
                items=[
                    SearchItemOut(
                        id=i.id,
                        title=i.titulo,
                        subtitle=i.subtitulo,
                        route=i.rota,
                        snippet=i.trecho,
                    )
                    for i in g.itens
                ],
            )
            for g in grupos
        ]
    )
