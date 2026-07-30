"""Despachante de transporte WhatsApp.

Onda 0 (esta): só o provider Meta existe (`providers/meta.py`). Este módulo já aceita `profile=`
em toda função de envio/mídia — extrai `token`/`phone_id` do `TenantProfile` antes de delegar —
para que os 9 pontos de chamada do domínio parem de manusear credenciais cruas. A RESOLUÇÃO,
porém, é sempre `providers.meta`: não existe outro provider nem o campo
`TenantProfile.whatsapp_provider` ainda (chega na Onda 2, junto com `providers/evolution.py` na
Onda 1). Ver docs/superpowers/specs/2026-07-30-whatsapp-evolution-multi-tenant-design.md.

Contrato preservado (idêntico ao módulo único que este pacote substitui):
- `send_text`/`send_template`/`send_media` devolvem "sent" | "logged" | "failed" e NUNCA
  propagam exceção (fire-and-forget, degradação graciosa).
- As administrativas (`create_template`, `fetch_template_status`, `delete_template`,
  `upload_media`, `fetch_media_url`, `download_media`) PROPAGAM `WhatsappApiError`.

Retrocompatibilidade: `token=`/`phone_id=` continuam aceitos diretamente (sem `profile`) — tanto
para a suíte de testes existente (`tests/test_whatsapp.py`, que testa o provider Meta via este
despachante sem nunca passar `profile`) quanto para chamadores que já têm as credenciais soltas
por razão própria (ver `platform/service.py::_send_invite`, que extrai token/phone_id DENTRO de
uma `tenant_session` fechada antes de enviar, evitando acessar atributo de um `TenantProfile`
SQLAlchemy já detached — ver nota nesse arquivo).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.whatsapp.providers import meta
from app.core.whatsapp.providers.meta import WhatsappApiError

if TYPE_CHECKING:
    from app.modules.settings.models import TenantProfile

__all__ = [
    "WhatsappApiError",
    "send_text",
    "send_template",
    "send_media",
    "upload_media",
    "fetch_media_url",
    "download_media",
    "verify_webhook_signature",
    "create_template",
    "fetch_template_status",
    "delete_template",
]


def _resolve(profile: TenantProfile | None):
    """Escolhe o provider pelo transporte do tenant.

    PONTO DE EXTENSÃO (Onda 2): quando `TenantProfile.whatsapp_provider` existir, este função
    passa a ser `meta if profile is None or profile.whatsapp_provider != "evolution" else
    evolution`. Até lá só `meta` existe — não há branch para escrever."""
    return meta


def send_text(
    *,
    to: str,
    text: str,
    profile: TenantProfile | None = None,
    token: str | None = None,
    phone_id: str | None = None,
) -> str:
    provider = _resolve(profile)
    if profile is not None:
        token = profile.whatsapp_token
        phone_id = profile.whatsapp_phone_id
    return provider.send_text(to=to, text=text, token=token, phone_id=phone_id)


def send_template(
    *,
    to: str,
    template_name: str,
    language: str,
    variables: list[str],
    profile: TenantProfile | None = None,
    token: str | None = None,
    phone_id: str | None = None,
) -> str:
    provider = _resolve(profile)
    if profile is not None:
        token = profile.whatsapp_token or ""
        phone_id = profile.whatsapp_phone_id or ""
    return provider.send_template(
        to=to,
        token=token or "",
        phone_id=phone_id or "",
        template_name=template_name,
        language=language,
        variables=variables,
    )


def send_media(
    *,
    to: str,
    kind: str,
    media_id: str,
    caption: str = "",
    profile: TenantProfile | None = None,
    token: str | None = None,
    phone_id: str | None = None,
) -> str:
    provider = _resolve(profile)
    if profile is not None:
        token = profile.whatsapp_token or ""
        phone_id = profile.whatsapp_phone_id or ""
    return provider.send_media(
        to=to,
        token=token or "",
        phone_id=phone_id or "",
        kind=kind,
        media_id=media_id,
        caption=caption,
    )


def upload_media(
    *,
    file_bytes: bytes,
    filename: str,
    mime_type: str,
    profile: TenantProfile | None = None,
    token: str | None = None,
    phone_id: str | None = None,
) -> str:
    provider = _resolve(profile)
    if profile is not None:
        token = profile.whatsapp_token or ""
        phone_id = profile.whatsapp_phone_id or ""
    return provider.upload_media(
        phone_id=phone_id or "",
        token=token or "",
        file_bytes=file_bytes,
        filename=filename,
        mime_type=mime_type,
    )


def fetch_media_url(
    *,
    media_id: str,
    profile: TenantProfile | None = None,
    token: str | None = None,
) -> str:
    provider = _resolve(profile)
    if profile is not None:
        token = profile.whatsapp_token or ""
    return provider.fetch_media_url(token=token or "", media_id=media_id)


def download_media(
    *,
    url: str,
    profile: TenantProfile | None = None,
    token: str | None = None,
) -> bytes:
    provider = _resolve(profile)
    if profile is not None:
        token = profile.whatsapp_token or ""
    return provider.download_media(token=token or "", url=url)


def verify_webhook_signature(
    *, app_secret: str, body: bytes, signature_header: str | None
) -> bool:
    """Sem variante `profile=`: quem chama já tem `app_secret` resolvido de
    `PublicWhatsappAccount` (tabela global, pré-autenticação), não de `TenantProfile`."""
    return meta.verify_webhook_signature(
        app_secret=app_secret, body=body, signature_header=signature_header
    )


def create_template(
    *,
    waba_id: str,
    token: str,
    name: str,
    language: str,
    category: str,
    body_text: str,
    variable_examples: list[str],
) -> dict:
    return meta.create_template(
        waba_id=waba_id,
        token=token,
        name=name,
        language=language,
        category=category,
        body_text=body_text,
        variable_examples=variable_examples,
    )


def fetch_template_status(*, token: str, meta_template_id: str) -> dict:
    return meta.fetch_template_status(token=token, meta_template_id=meta_template_id)


def delete_template(*, waba_id: str, token: str, name: str) -> None:
    meta.delete_template(waba_id=waba_id, token=token, name=name)
