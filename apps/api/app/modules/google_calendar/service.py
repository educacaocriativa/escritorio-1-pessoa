"""Regras da integração Google (OAuth + Calendar API), via httpx puro.

Sem SDK oficial (google-api-python-client): replicamos o estilo de core/whatsapp.py — httpx
direto, "sem credencial = no-op/log, com credencial = chamada real" — consistente com o padrão
do projeto e com "Custo importa" (CLAUDE.md §3.4).

Princípio de robustez (mesmo de core/whatsapp.py, exigido por IV1/IV2): uma falha na chamada ao
Google (rede, token revogado, quota) NUNCA derruba a operação de negócio da Agenda — captura,
loga (sem vazar o token) e retorna None. O evento é criado normalmente, apenas sem Meet.
"""
from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core import audit
from app.core.security import sign_oauth_state
from app.modules.google_calendar.models import DEFAULT_SCOPE, GoogleCredential

logger = logging.getLogger("e1p.google_calendar")

_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 (endpoint público, não é segredo)
_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
_REVOKE_URL = "https://oauth2.googleapis.com/revoke"  # noqa: S105 (endpoint público)
_CALENDAR_EVENTS_URL = (
    "https://www.googleapis.com/calendar/v3/calendars/primary/events?conferenceDataVersion=1"
)
_HTTP_TIMEOUT = 10

# Tipos de evento onde "reunião" faz sentido (geram Meet). Bloqueios/prazos/cobranças não.
MEET_KINDS = {"reuniao", "atendimento", "audiencia"}


class GoogleNotConfiguredError(Exception):
    """O app OAuth do Google não está configurado na plataforma (config global vazia)."""


# ── Fluxo OAuth ──────────────────────────────────────────────────────────────
def build_authorize_url(tenant_id: str) -> str:
    """Monta a URL de autorização do Google. `access_type=offline` + `prompt=consent` garantem
    o refresh_token na primeira autorização; `state` assinado protege contra CSRF."""
    if not settings.google_oauth_configured:
        raise GoogleNotConfiguredError("Integração Google não configurada")
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_oauth_redirect_uri,
        "response_type": "code",
        "scope": DEFAULT_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": sign_oauth_state(tenant_id),
    }
    return f"{_AUTH_URL}?{urlencode(params)}"


def exchange_code(code: str) -> dict:
    """Troca o `code` do callback por tokens (access + refresh)."""
    resp = httpx.post(
        _TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": settings.google_oauth_redirect_uri,
        },
        timeout=_HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_account_email(access_token: str) -> str:
    """Busca o e-mail da conta Google conectada (para exibir 'conectado como ...')."""
    resp = httpx.get(
        _USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=_HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json().get("email", "")


def _expiry_from(token_data: dict) -> datetime | None:
    expires_in = token_data.get("expires_in")
    if not expires_in:
        return None
    try:
        return datetime.now(UTC) + timedelta(seconds=int(expires_in))
    except (TypeError, ValueError):
        return None


def get_credential(db: Session) -> GoogleCredential | None:
    """A credencial do tenant atual (RLS já isola a sessão). None se não conectado."""
    return db.scalars(select(GoogleCredential)).first()


def upsert_credential(db: Session, *, tenant_id: str, email: str, token_data: dict) -> None:
    """Cria/atualiza a credencial do tenant (uma por tenant). Preserva o refresh_token antigo
    se o Google não devolver um novo (ele só vem na 1ª autorização com prompt=consent)."""
    cred = get_credential(db)
    if cred is None:
        cred = GoogleCredential(tenant_id=tenant_id)
        db.add(cred)
    cred.google_account_email = email
    cred.access_token = token_data.get("access_token", "")
    new_refresh = token_data.get("refresh_token")
    if new_refresh:
        cred.refresh_token = new_refresh
    cred.token_expiry = _expiry_from(token_data)
    cred.scope = token_data.get("scope", DEFAULT_SCOPE)
    audit.record(
        db, tenant_id=tenant_id, actor="google:oauth", action="google.credential.connect",
        target=cred.id,
    )
    db.commit()


def handle_callback(db: Session, *, tenant_id: str, code: str) -> None:
    """Fluxo completo do callback: troca o code por tokens, descobre o e-mail e faz upsert."""
    token_data = exchange_code(code)
    access_token = token_data.get("access_token", "")
    email = fetch_account_email(access_token) if access_token else ""
    upsert_credential(db, tenant_id=tenant_id, email=email, token_data=token_data)


def disconnect(db: Session, *, tenant_id: str, actor: str) -> bool:
    """Apaga a credencial do tenant. Best-effort: tenta revogar no Google, mas SEMPRE apaga
    localmente mesmo se a revogação falhar (a intenção do usuário é desconectar)."""
    cred = get_credential(db)
    if cred is None:
        return False
    token_to_revoke = cred.refresh_token or cred.access_token
    if token_to_revoke:
        try:
            httpx.post(
                _REVOKE_URL, data={"token": token_to_revoke}, timeout=_HTTP_TIMEOUT
            )
        except Exception:
            logger.exception("[google:revoke:failed] tenant=%s", tenant_id)
    db.delete(cred)
    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="google.credential.disconnect",
        target=cred.id,
    )
    db.commit()
    return True


# ── Geração de Meet ao criar evento ──────────────────────────────────────────
def _ensure_fresh_token(db: Session, cred: GoogleCredential) -> str | None:
    """Retorna um access_token válido, renovando via refresh_token se já expirou. None se não
    dá para renovar (sem refresh_token)."""
    expiry = cred.token_expiry
    if expiry is not None and expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    if expiry is None or expiry > datetime.now(UTC):
        return cred.access_token or None
    if not cred.refresh_token:
        return None
    resp = httpx.post(
        _TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": cred.refresh_token,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
        },
        timeout=_HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    token_data = resp.json()
    cred.access_token = token_data.get("access_token", "")
    cred.token_expiry = _expiry_from(token_data)
    db.add(cred)
    return cred.access_token or None


def create_meet_event(
    db: Session, *, tenant_id: str, event
) -> tuple[str | None, str | None] | None:
    """Cria o evento espelho no Google Calendar (com link de Meet) para um AgendaEvent.

    Retorna (hangout_link, google_event_id) em caso de sucesso, ou None se:
    - o tenant não tem Google conectado (no-op — preserva AC3/IV1); ou
    - a chamada ao Google falhou (rede/token/quota) — a exceção é capturada e logada, NUNCA
      propagada, para não derrubar a criação do evento da Agenda (IV1/IV2).
    """
    cred = get_credential(db)
    if cred is None:
        return None
    try:
        access_token = _ensure_fresh_token(db, cred)
        if not access_token:
            return None
        body = {
            "summary": event.title,
            "description": event.description or "",
            "start": {"dateTime": _iso(event.starts_at)},
            "end": {"dateTime": _iso(event.ends_at)},
            "attendees": [{"email": g} for g in (event.guests or [])],
            "conferenceData": {
                "createRequest": {
                    "requestId": uuid.uuid4().hex,
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            },
        }
        resp = httpx.post(
            _CALENDAR_EVENTS_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            json=body,
            timeout=_HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("hangoutLink"), data.get("id")
    except Exception:
        # Falha de integração externa não derruba a Agenda (IV1). Não logamos o token.
        logger.exception("[google:create_meet:failed] tenant=%s", tenant_id)
        return None


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()
