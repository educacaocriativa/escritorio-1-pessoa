"""Envio de WhatsApp via Evolution API (Baileys, não-oficial) — transporte alternativo ao Meta
Cloud API (`providers/meta.py`). Ver
docs/superpowers/specs/2026-07-30-whatsapp-evolution-multi-tenant-design.md.

Diferente do Meta: a API key é GLOBAL (`settings.evolution_api_key`), não por tenant — só o
NOME DA INSTÂNCIA (`e1p-{tenant_id}`, calculado pelo chamador; ver Onda 2) varia por tenant.
Sem API key configurada (Evolution desligada), NÃO falha: registra como "logged", mesmo
contrato do provider Meta.
"""
from __future__ import annotations

import base64
import logging

import httpx

from app.config import settings
from app.core.whatsapp.inbound import InboundMessage

logger = logging.getLogger("e1p.whatsapp.evolution")


class EvolutionUnsupportedError(Exception):
    """Levantado por operações que a Evolution API não suporta (ver `capabilities.EVOLUTION`:
    templates=False). Um consumidor real só chega aqui se ignorou `capabilities.py` — é bug de
    quem chama, não caso de "logged" gracioso."""


def send_text(*, to: str, text: str, instance: str) -> str:
    """Retorna 'sent' | 'logged' | 'failed'. Mesmo contrato do provider Meta: NUNCA propaga
    exceção (fire-and-forget, degradação graciosa)."""
    if not settings.evolution_api_key:
        logger.info("[whatsapp.evolution:logged] instancia=%s para=%s msg=%s", instance, to, text)
        return "logged"
    try:
        resp = httpx.post(
            f"{settings.evolution_api_url}/message/sendText/{instance}",
            headers={"apikey": settings.evolution_api_key},
            json={"number": to, "text": text, "delay": 1000},
            timeout=10,
        )
        resp.raise_for_status()
        return "sent"
    except Exception:
        logger.exception("[whatsapp.evolution:failed] instancia=%s para=%s", instance, to)
        return "failed"


def upload_media(*, file_bytes: bytes, filename: str, mime_type: str) -> str:
    """A Evolution API NÃO tem endpoint de upload separado (diferente do Meta) — a mídia vai
    inline (base64) no próprio POST de envio. Esta função é só uma conveniência LOCAL, sem
    chamada de rede, que devolve os bytes em base64 como referência opaca — mantém o mesmo
    padrão de 2 passos (`upload_media` → `send_media(media_id=...)`) que o despachante já usa
    para o Meta, sem precisar de nenhuma mudança nos call sites do domínio quando a Onda 2 ligar
    o fio. `filename`/`mime_type` não são usados aqui (Evolution não precisa deles no upload,
    só no envio — ver `send_media`); mantidos na assinatura por simetria com o provider Meta."""
    return base64.b64encode(file_bytes).decode("ascii")


def send_media(
    *, to: str, instance: str, kind: str, media_id: str, caption: str = ""
) -> str:
    """`media_id` aqui é o base64 devolvido por `upload_media` (não um ID remoto — ver docstring
    de `upload_media`). Retorna 'sent' | 'logged' | 'failed'. Mesmo contrato de send_text: NUNCA
    propaga exceção."""
    if not settings.evolution_api_key:
        logger.info("[whatsapp.evolution:logged] mídia instancia=%s para=%s kind=%s",
                     instance, to, kind)
        return "logged"
    body: dict = {"number": to, "mediatype": kind, "media": media_id}
    if caption:
        body["caption"] = caption
    try:
        resp = httpx.post(
            f"{settings.evolution_api_url}/message/sendMedia/{instance}",
            headers={"apikey": settings.evolution_api_key},
            json=body,
            timeout=30,
        )
        resp.raise_for_status()
        return "sent"
    except Exception:
        logger.exception("[whatsapp.evolution:failed] mídia instancia=%s para=%s", instance, to)
        return "failed"


def send_template(**_kwargs: object) -> str:
    raise EvolutionUnsupportedError(
        "Evolution API não suporta templates aprovados (capabilities.EVOLUTION.templates=False)"
    )


def create_template(**_kwargs: object) -> dict:
    raise EvolutionUnsupportedError("Evolution API não suporta templates aprovados")


def fetch_template_status(**_kwargs: object) -> dict:
    raise EvolutionUnsupportedError("Evolution API não suporta templates aprovados")


def delete_template(**_kwargs: object) -> None:
    raise EvolutionUnsupportedError("Evolution API não suporta templates aprovados")


def verify_webhook_signature(**_kwargs: object) -> bool:
    raise EvolutionUnsupportedError(
        "Evolution API não usa HMAC de webhook — autenticação é por isolamento de rede + "
        "segredo por tenant (ver Onda 3 da spec)"
    )


def fetch_media_url(**_kwargs: object) -> str:
    raise EvolutionUnsupportedError(
        "Evolution API entrega mídia inline no payload do webhook, sem endpoint de resolução "
        "separado (ver Onda 3 da spec)"
    )


def download_media(**_kwargs: object) -> bytes:
    raise EvolutionUnsupportedError(
        "Evolution API entrega mídia inline no payload do webhook, sem endpoint de download "
        "separado (ver Onda 3 da spec)"
    )


# message[key] -> kind normalizado (ver InboundMessage.kind). "documentWithCaptionMessage"
# embrulha um documentMessage (documento com legenda) num nível extra — tratado à parte abaixo.
_MEDIA_MESSAGE_KEYS = {
    "imageMessage": "image",
    "audioMessage": "audio",
    "videoMessage": "video",
    "documentMessage": "document",
}


def _extract_media(message: dict) -> tuple[str | None, dict | None]:
    """Devolve (kind, objeto da mídia) pro primeiro tipo de mídia reconhecido em `message`, ou
    (None, None) se for texto puro. `documentWithCaptionMessage` embrulha o documentMessage real
    um nível a mais (documento enviado com legenda) — desembrulha antes de checar os demais."""
    wrapped = message.get("documentWithCaptionMessage", {}).get("message", {})
    if "documentMessage" in wrapped:
        return "document", wrapped["documentMessage"]
    for key, kind in _MEDIA_MESSAGE_KEYS.items():
        if key in message:
            return kind, message[key]
    return None, None


def parse_inbound(payload: dict) -> list[InboundMessage]:
    """Extrai a mensagem do formato da Evolution API (evento `messages.upsert`). `@lid` no
    lugar do telefone → `from_phone=None` — NUNCA adivinhado por heurística (ver bandeja "Não
    identificados", Onda 3).

    Mídia (imagem/áudio/documento/vídeo): a Evolution não tem endpoint de resolução separado
    (ver `fetch_media_url`/`download_media` acima) — os bytes só chegam se o webhook foi
    configurado com `webhook.base64=true` (ver `whatsapp_session/service.py::connect`), inline
    em `message.base64` (confirmado contra o código-fonte da Evolution: `whatsapp.baileys.
    service.ts`, `messageRaw.message.base64 = buffer.toString('base64')`). Se a Evolution não
    conseguiu baixar (erro dela, ou webhookBase64 desligado), `media_bytes` fica None — a
    mensagem ainda é registrada (com legenda, se houver), só sem anexo.
    """
    try:
        data = payload.get("data", payload)
        key = data.get("key", {})
        remote_jid = key.get("remoteJid", "")
        wa_message_id = key.get("id", "")
        if not wa_message_id:
            return []
        from_phone = None
        if remote_jid.endswith("@s.whatsapp.net"):
            from_phone = remote_jid.split("@")[0]
        push_name = data.get("pushName", "")
        message = data.get("message", {})

        media_kind, media_obj = _extract_media(message)
        if media_kind is None:
            text_body = message.get("conversation", "") or message.get(
                "extendedTextMessage", {}
            ).get("text", "")
            return [InboundMessage(
                wa_message_id=wa_message_id, from_phone=from_phone, kind="text",
                text_body=text_body, media_ref=None, push_name=push_name,
            )]

        raw_b64 = message.get("base64")
        media_bytes = base64.b64decode(raw_b64) if raw_b64 else None
        mime_type = (media_obj.get("mimetype") or "application/octet-stream").split(";")[0].strip()
        return [InboundMessage(
            wa_message_id=wa_message_id, from_phone=from_phone, kind=media_kind,
            text_body=media_obj.get("caption", ""), media_ref=None, push_name=push_name,
            media_bytes=media_bytes, media_mime_type=mime_type,
            media_filename=media_obj.get("fileName") or media_obj.get("title"),
        )]
    except (AttributeError, TypeError, KeyError, ValueError):
        return []
