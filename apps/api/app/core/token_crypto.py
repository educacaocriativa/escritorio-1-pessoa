"""Criptografia simétrica em repouso para tokens OAuth (Fernet / AES-128-CBC + HMAC).

Motivação (dívida técnica da Story 4.1, endereçada antes de produção): os tokens do Google
(`access_token`/`refresh_token`) eram guardados em TEXTO PLANO no Postgres — protegidos só pela
RLS. Um dump/backup vazado ou acesso ao banco expunha os tokens diretamente. Agora ciframos em
repouso: o banco guarda ciphertext, o código Python sempre vê texto plano (transparente via o
`TypeDecorator` `EncryptedToken`).

Escolha da lib: `cryptography` (Fernet) — JÁ vem no projeto como dependência de
`python-jose[cryptography]`, sem nova dependência (CLAUDE.md §3.4 "Custo importa"). Fernet é
AES-128 em CBC com HMAC-SHA256 (autenticado) — adequado e simples para segredos curtos.

Idempotência / best-effort (mesmo espírito fail-safe do resto do módulo Google):
- `encrypt_token` marca o ciphertext com o prefixo `enc:v1:`; se já vier marcado, NÃO re-cifra.
- `decrypt_token` só decifra o que tem o prefixo; texto plano legado (pré-criptografia) passa
  direto, sem quebrar. Assim a migração de dados existentes é natural — ao regravar, cifra.

Chave: `GOOGLE_TOKEN_ENCRYPTION_KEY` (env). Em dev/test, se ausente, deriva-se uma chave do
`JWT_SECRET` (fallback) para que a criptografia esteja SEMPRE ativa (nunca texto plano, nem em
teste). Em PRODUÇÃO com o Google configurado, a env dedicada é OBRIGATÓRIA (guard de boot em
config.py) — chave dedicada evita acoplar a rotação do JWT à leitura dos tokens já gravados.
"""
from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

from app.config import settings

logger = logging.getLogger("e1p.token_crypto")

# Marca do nosso ciphertext. Versionado p/ permitir troca futura de esquema sem ambiguidade.
_PREFIX = "enc:v1:"


def _derive_fernet_key(secret: str) -> bytes:
    """Deriva uma chave Fernet válida (32 bytes base64 urlsafe) de uma passphrase arbitrária."""
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _fernet() -> Fernet:
    """Constrói o cifrador a partir da config atual.

    Não cacheamos (sha256 + Fernet() são baratos e as operações de token são raras): assim
    respeitamos monkeypatch de settings nos testes, sem estado obsoleto entre casos.
    """
    key = settings.google_token_encryption_key
    if key:
        try:
            # Aceita uma Fernet key crua (base64 urlsafe de 32 bytes)...
            return Fernet(key.encode("ascii") if isinstance(key, str) else key)
        except (ValueError, TypeError):
            # ...ou uma passphrase qualquer (deriva a chave dela).
            return Fernet(_derive_fernet_key(key))
    # Fallback dev/test: deriva do JWT_SECRET. Produção exige a env dedicada (guard de boot).
    return Fernet(_derive_fernet_key(settings.jwt_secret))


def encrypt_token(plaintext: str | None) -> str | None:
    """Cifra um token para persistência. Idempotente: vazio/None passa direto; já-cifrado não
    é re-cifrado (evita camadas duplas)."""
    if not plaintext:
        return plaintext
    if plaintext.startswith(_PREFIX):
        return plaintext
    token = _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")
    return _PREFIX + token


def decrypt_token(stored: str | None) -> str | None:
    """Decifra um token lido do banco. Best-effort: vazio/None passa direto; texto plano legado
    (sem o prefixo) passa direto; falha de decifração (chave trocada) loga e retorna vazio em vez
    de quebrar a operação de negócio."""
    if not stored:
        return stored
    if not stored.startswith(_PREFIX):
        return stored  # legado em texto plano — não força migração destrutiva
    raw = stored[len(_PREFIX):]
    try:
        return _fernet().decrypt(raw.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        logger.warning("[token_crypto] falha ao decifrar token (chave rotacionada/inválida?)")
        return ""


class EncryptedToken(TypeDecorator):
    """Coluna `Text` que cifra em repouso de forma transparente.

    O tipo SQL subjacente continua sendo `TEXT` (o ciphertext é só mais longo), então trocar uma
    coluna `Text` por `EncryptedToken` NÃO exige migration de schema. O Python sempre lê/escreve
    texto plano; o banco sempre guarda ciphertext (prefixo `enc:v1:`).
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect) -> str | None:  # noqa: ANN001
        return encrypt_token(value)

    def process_result_value(self, value: str | None, dialect) -> str | None:  # noqa: ANN001
        return decrypt_token(value)
