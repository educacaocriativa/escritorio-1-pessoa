"""Object storage S3-compatível para os bytes dos Anexos (Story 3.5).

Wrapper fino sobre `boto3` (cliente `s3`) parametrizado por `endpoint_url`: aponta tanto para
AWS S3 real (caminho documentado em `docs/AWS-DEPLOYMENT.md`) quanto para um provedor
S3-compatível mais barato hoje na VPS (MinIO self-hosted / Backblaze B2 / Wasabi) SEM trocar
código — só configuração (ver `Settings` em `app/config.py`).

Padrão de degradação graciosa (igual a WhatsApp/SMTP/gateway): se `s3_bucket` estiver vazio,
`is_configured()` retorna False e o service de Anexos continua gravando os bytes no Postgres
(comportamento legado preservado). Nenhuma chamada de rede acontece nesse caso.

Isolamento de tenant (Regra de Ouro nº 1) é reforçado no próprio path via `build_key`, que
prefixa a chave por `tenant_id` — defesa-em-profundidade em complemento (não substituição) à
RLS que já protege a linha de metadado em `attachments`.
"""
from __future__ import annotations

import logging
from functools import lru_cache

from app.config import settings

logger = logging.getLogger("e1p.storage")


def is_configured() -> bool:
    """True se o storage S3 está ligado (bucket definido). Vazio = fallback Postgres."""
    return bool(settings.s3_bucket)


def build_key(tenant_id: str, attachment_id: str, filename: str) -> str:
    """Monta a chave do objeto isolada por tenant.

    Formato: `tenants/{tenant_id}/attachments/{attachment_id}/{filename}`. O `attachment_id`
    (único) garante que nomes de arquivo repetidos não colidam; o prefixo `tenants/{tenant_id}`
    isola o path por tenant (reforça AC1/IV2 junto com a RLS do metadado).
    """
    safe_name = (filename or "arquivo").replace("/", "_").replace("\\", "_").lstrip(".")
    return f"tenants/{tenant_id}/attachments/{attachment_id}/{safe_name or 'arquivo'}"


@lru_cache(maxsize=1)
def _client():
    """Cliente boto3 S3 (cacheado). Importa boto3 lazy para não exigir a dependência quando o
    storage está desligado (fallback Postgres em dev/CI)."""
    import boto3  # noqa: PLC0415 (import lazy proposital — só quando o S3 está ligado)

    kwargs: dict[str, str] = {"region_name": settings.s3_region}
    if settings.s3_endpoint_url:
        kwargs["endpoint_url"] = settings.s3_endpoint_url
    if settings.s3_access_key_id:
        kwargs["aws_access_key_id"] = settings.s3_access_key_id
    if settings.s3_secret_access_key:
        kwargs["aws_secret_access_key"] = settings.s3_secret_access_key
    return boto3.client("s3", **kwargs)


def put_object(key: str, data: bytes, content_type: str) -> None:
    """Sobe os bytes para o bucket configurado."""
    _client().put_object(
        Bucket=settings.s3_bucket,
        Key=key,
        Body=data,
        ContentType=content_type or "application/octet-stream",
    )


def get_object(key: str) -> bytes:
    """Baixa os bytes do objeto."""
    resp = _client().get_object(Bucket=settings.s3_bucket, Key=key)
    return resp["Body"].read()


def delete_object(key: str) -> None:
    """Remove o objeto do bucket."""
    _client().delete_object(Bucket=settings.s3_bucket, Key=key)
