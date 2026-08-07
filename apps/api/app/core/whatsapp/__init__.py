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

import logging
from typing import TYPE_CHECKING

from app.config import settings
from app.core.phone import normalize_br
from app.core.whatsapp import capabilities
from app.core.whatsapp.providers import evolution, meta
from app.core.whatsapp.providers.meta import WhatsappApiError

if TYPE_CHECKING:
    from app.modules.settings.models import TenantProfile

logger = logging.getLogger("e1p.whatsapp")

__all__ = [
    "WhatsappApiError",
    "is_deliverable",
    "fetch_group_subject",
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

    DERIVA de `capabilities.for_profile` em vez de repetir a comparação: assim o que os
    consumidores de domínio checam (posso mandar texto livre?) e o que este módulo faz de fato
    (por qual API o texto sai) não conseguem divergir. Gate em
    `tests/test_whatsapp_capabilities.py::test_capabilities_e_despachante_nunca_divergem`."""
    return evolution if capabilities.for_profile(profile) is capabilities.EVOLUTION else meta


def is_deliverable(profile: TenantProfile | None) -> bool:
    """Existe, AGORA, transporte capaz de entregar para este tenant?

    Sem isso, quem enfileira não distingue "vai sair" de "vai morrer": os providers devolvem
    `"logged"` quando não têm credencial — um status de sucesso aparente, TERMINAL (o worker não
    reprocessa `logged`). Foi assim que um convite de funcionário sumiu em produção
    (2026-08-05): a sessão Evolution tinha caído, o envio caiu no stub da Meta e a tela do Master
    disse que estava tudo certo.

    Mora no despachante, e não em cada call site, pela mesma razão de `_addressable` e
    `capabilities`: é a fronteira por onde TODO envio passa, e são seis os caminhos que enfileiram
    WhatsApp. Responde sobre a POSSIBILIDADE de entregar — não promete que o WhatsApp do
    destinatário existe, nem que a sessão não vai cair no minuto seguinte.
    """
    if _resolve(profile) is evolution:
        # Credencial da Evolution é GLOBAL; o vínculo com o tenant é o `whatsapp_provider`, que
        # `_resolve` já conferiu e que só `confirm()`/`promote_pending_connections` escrevem.
        return bool(settings.evolution_api_key)
    if profile is not None:
        return bool(profile.whatsapp_token and profile.whatsapp_phone_id)
    return bool(settings.whatsapp_token and settings.whatsapp_phone_id)


def _addressable(to: str) -> str:
    """Transforma o destinatário GUARDADO num endereço que o WhatsApp entende.

    Bug real de produção (2026-08-05): o funil registrava a mensagem e ela nunca chegava. A
    Evolution devolvia `400` porque o contato estava gravado como `43984074017` — o que o dono
    digitou, sem código do país — e esse número simplesmente NÃO existe no WhatsApp
    (`/chat/whatsappNumbers` confirmou: `exists:false`; com `55` na frente, `exists:true`).

    Por que aqui e não em cada call site: seis caminhos resolvem destinatário de campos de
    telefone crus (funil, alerta pra equipe, convite de funcionário, orçamento, cobrança,
    contrato) e só `Client` tem o gêmeo normalizado (`phone_key`, PR #76). Consertar um por um
    deixaria quatro quebrados. O despachante é por onde TODO envio passa — mesma razão de
    `capabilities` viver aqui em vez de `if` espalhado.

    Isto NÃO reescreve o que está guardado: `clients.phone` continua sendo a evidência do que a
    pessoa digitou, no mesmo par `raw_description`/`user_description` de `bank_transactions`.

    **Nem todo `to` é telefone** e reescrever os outros trocaria uma falha visível por uma
    entrega no lugar errado: grupo é JID (`...@g.us`), contato não identificado é `@lid`, o
    destinatário do owner cai em e-mail (placeholder histórico de `_owner_recipient`) e o funil
    cai no NOME do contato quando não há telefone. Tudo que tem `@` sai intacto por guarda
    explícita; o resto sai intacto porque `normalize_br` devolve `None` quando não é BR.

    ⚠️ **Suposição BR-only** (decisão do fundador, coerente com CPF/CNPJ, boleto e Pix): um
    celular estrangeiro de 10-11 dígitos é reescrito como se fosse brasileiro, e aí a mensagem
    vai para outra pessoa — pior que falhar. É por isso que toda reescrita é logada: o caso
    estrangeiro precisa APARECER, não sumir.
    """
    if "@" in to:
        return to
    normalized = normalize_br(to)
    if normalized is None or normalized == to:
        return to
    logger.info("[whatsapp] destinatário normalizado: %s -> %s", to, normalized)
    return normalized


def _evolution_instance(profile: TenantProfile | None) -> str:
    """Mesmo formato de `whatsapp_session/service.py::_instance_name` — só chamada quando
    `_resolve` já confirmou `profile.whatsapp_provider == "evolution"`, então `profile` nunca é
    None aqui (garantia do chamador, não repetida em runtime)."""
    return f"e1p-{profile.tenant_id}"  # type: ignore[union-attr]


def fetch_group_subject(*, profile: TenantProfile | None, group_jid: str) -> str | None:
    """Nome do grupo, ou `None` quando não dá pra saber. Só a Evolution tem grupos — a Cloud API
    da Meta não suporta o recurso —, então em qualquer outro transporte a resposta é `None` sem
    chamada de rede nenhuma."""
    if _resolve(profile) is not evolution:
        return None
    return evolution.fetch_group_subject(
        instance=_evolution_instance(profile), group_jid=group_jid
    )


def send_text(
    *,
    to: str,
    text: str,
    profile: TenantProfile | None = None,
    token: str | None = None,
    phone_id: str | None = None,
) -> str:
    provider = _resolve(profile)
    to = _addressable(to)
    if provider is evolution:
        # Evolution não usa token/phone_id por tenant (credencial GLOBAL) — identifica a
        # instância pelo tenant_id, não por essas duas credenciais da Meta.
        return provider.send_text(to=to, text=text, instance=_evolution_instance(profile))
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
    quick_reply_payload: str | None = None,
) -> str:
    provider = _resolve(profile)
    to = _addressable(to)
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
        # Só o aviso do briefing usa (ver `providers/meta.send_template`). A Evolution recusa
        # template inteiro, então o parâmetro extra nunca a alcança de forma significativa.
        quick_reply_payload=quick_reply_payload,
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
    to = _addressable(to)
    if provider is evolution:
        return provider.send_media(
            to=to, instance=_evolution_instance(profile), kind=kind, media_id=media_id,
            caption=caption,
        )
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
    if provider is evolution:
        # Evolution não tem endpoint de upload separado (ver docstring de
        # providers/evolution.py::upload_media) — não usa token/phone_id.
        return provider.upload_media(
            file_bytes=file_bytes, filename=filename, mime_type=mime_type,
        )
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
