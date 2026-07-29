"""Autenticação do upload de comprovante: JWT (web/Android) OU token de dispositivo (iOS).

Duas portas de entrada, uma identidade. O resto do código recebe um `CurrentUser` normal e
não sabe qual credencial foi usada.

O token de dispositivo é DELIBERADAMENTE limitado a este único endpoint de escrita: ele vive
em texto claro dentro do Atalho, no aparelho, então o desenho assume vazamento. O pior caso é
alguém depositar arquivos na bandeja do dono — que ele vê e descarta. Nenhum dado sai.
"""
from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.core.tenancy import CurrentUser
from app.db.session import get_db, tenant_session


def receipt_uploader(
    authorization: str | None = Header(default=None),
    x_e1p_device_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> CurrentUser:
    """Aceita `Authorization: Bearer <jwt>` OU `X-E1P-Device-Token: <raw>`.

    O JWT tem precedência: se a pessoa está logada no PWA, é a sessão dela que vale.
    """
    if authorization and authorization.lower().startswith("bearer "):
        payload = decode_access_token(authorization.split(" ", 1)[1])
        if not payload or "sub" not in payload or "tenant_id" not in payload:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token inválido")
        return CurrentUser(
            user_id=payload["sub"],
            tenant_id=payload["tenant_id"],
            role=payload.get("role", "owner"),
            allowed_modules=payload.get("allowed_modules", []),
            is_platform_admin=bool(payload.get("is_platform_admin", False)),
        )

    if x_e1p_device_token:
        # Import adiado (não no topo do módulo): `app.modules.device_tokens` é submódulo de
        # `app.modules`, cujo `__init__.py` importa `receipts_router`, que importa este módulo —
        # um import no topo criaria import circular na inicialização do pacote (mesmo padrão já
        # usado em `receipts_router.py` para `AttachmentError`).
        from app.modules.device_tokens import service as device_tokens_service
        from app.modules.device_tokens.models import SCOPE_RECEIPT_UPLOAD
        from app.modules.device_tokens.service import DeviceTokenError

        # Lookup pela sessão SEM tenant (`get_db`): `device_tokens` é global por design — o
        # tenant só é conhecido DEPOIS de resolver o token. Mesmo uso legítimo de `get_db` que
        # o login faz sobre `users`. Injetado por Depends (e não via SessionLocal direto) para
        # que os testes possam apontá-lo ao SQLite, como já fazem com o resto.
        try:
            token = device_tokens_service.resolve(
                db, raw=x_e1p_device_token, scope=SCOPE_RECEIPT_UPLOAD
            )
        except DeviceTokenError as e:
            raise HTTPException(e.status_code, str(e)) from e
        return CurrentUser(
            user_id=token.user_id,
            tenant_id=token.tenant_id,
            # O token não carrega papel/módulos; damos o mínimo viável para a rota de upload,
            # que não consulta RBAC além do módulo 'payables'.
            role="owner",
            allowed_modules=[],
        )

    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credencial ausente")


def get_receipt_db(user: CurrentUser = Depends(receipt_uploader)) -> Iterator[Session]:
    """Sessão com RLS fixada no tenant resolvido pela credencial (JWT ou dispositivo)."""
    with tenant_session(user.tenant_id) as db:
        yield db
