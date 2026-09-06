"""Trilha de auditoria (Regra de Ouro nº 3).

Toda ação relevante grava quem fez. Ações da IA marcam is_ai=True, que a UI mostra como
"Ação executada pela IA".
"""
from __future__ import annotations

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantMixin, TimestampMixin, _uuid


class AuditEntry(Base, TenantMixin, TimestampMixin):
    __tablename__ = "audit_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    actor: Mapped[str] = mapped_column(String(64), nullable=False)  # user_id ou "ai"
    is_ai: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    target: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    detail: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    """SNAPSHOT em texto livre do que o `target` sozinho não consegue recuperar depois.

    MESMO raciocínio de `PlatformAuditEntry.actor_email` (abaixo): quando a linha apontada pelo
    `target` é APAGADA na própria ação auditada, o id vira um ponteiro para o nada — não há
    FK/join possível depois. Foi o caso que abriu esta coluna (issue #307): `google.credential.
    disconnect` e `.revoked` gravavam `target=cred.id` e apagavam a `GoogleCredential` na mesma
    transação, então QUAL conta Google saiu deixava de existir no banco.

    POR QUE UMA COLUNA, e não compor no `target` (as duas opções que a #307 pesou):

    1. O `target` já foi sobrecarregado antes, e machucou. Sem campo de detalhe, o módulo `dna`
       enfiou três formas diferentes no mesmo campo — id, `f"{source}:{key}"`
       (`dna/eventos.py::alvo_da_resposta`) e uma contagem crua (`dna/router.py`) — e
       `scripts/nucleo_activation.py` precisou virar PARSER do campo (`target.split(":", 1)[0]`
       e `int(e.target)`). Aquele parse só é seguro porque a query filtra
       `action.startswith("dna.")` antes: o campo não tem contrato, tem convenção por ação.
       Uma quarta forma (`id:email`) estenderia exatamente esse defeito.
    2. NÃO CABE, e o estouro seria SILENCIOSO no teste e FATAL em produção. `target` é
       `String(255)`; `cred.id` é um UUID de 36 chars e o e-mail vai a 254 (RFC 5321) — o
       composto chega a 291. O Postgres de produção RECUSA (`value too long for type character
       varying(255)`) e derrubaria justo o `disconnect`; o SQLite da suíte IGNORA o limite e
       ficaria verde. Coluna própria dá 255 inteiros ao e-mail.

    `default=""`/`NOT NULL` (não `nullable`) de propósito: os 121 `audit.record()` existentes
    seguem sem passar nada e gravam `""`. Ausência de detalhe é "não se aplica", não é
    desconhecido — não há semântica de NULL a preservar aqui (ao contrário da 0086).

    ⚠️ LGPD: isto é dado pessoal e é PARA ficar em claro (a trilha existe para ser lida). Fica
    do lado CERTO da linha por herdar `TenantMixin`: `platform/service.py::_business_table_names`
    descobre a tabela por `issubclass(..., TenantMixin)`, então a coluna É purgada junto com o
    tenant. É a diferença deliberada para `PlatformAuditEntry`, que fica FORA do `TenantMixin`
    justamente para sobreviver à purga.
    """


def record(
    db,
    *,
    tenant_id: str,
    actor: str,
    action: str,
    target: str = "",
    detail: str = "",
    is_ai: bool = False,
):
    """Grava uma entrada de auditoria. Chame em toda mutação de dados de negócio.

    Use `detail` para o SNAPSHOT que o `target` não recupera depois (ver o docstring da coluna):
    quando a linha apontada pelo `target` morre na própria ação, o id não basta.
    """
    entry = AuditEntry(
        tenant_id=tenant_id,
        actor=actor,
        action=action,
        target=target,
        detail=detail,
        is_ai=is_ai,
    )
    db.add(entry)
    return entry


class PlatformAuditEntry(Base, TimestampMixin):
    """Log de PLATAFORMA (fora do tenant) para operações destrutivas do Master (LGPD).

    Deliberadamente SEM ``TenantMixin``: assim `_business_table_names()` (descoberta dinâmica
    via ``issubclass(mapper.class_, TenantMixin)`` em platform/service.py) NUNCA a inclui na
    purga por tenant. Por isso o registro SOBREVIVE à exclusão da conta — resta o rastro de
    quem/quando/qual tenant, que os `audit_entries` do próprio tenant (esses sim, purgados)
    não conseguem preservar.

    Guarda SNAPSHOTS (``actor_email``, ``target_tenant_slug``) porque o tenant-alvo é apagado
    logo em seguida: não há como fazer FK/join depois. O ator é sempre o Master (não é apagado),
    mas mantemos o e-mail como snapshot para o log ser autossuficiente.
    """

    __tablename__ = "platform_audit_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    actor_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    actor_email: Mapped[str] = mapped_column(String(255), nullable=False)
    target_tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    target_tenant_slug: Mapped[str] = mapped_column(String(63), nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False)


def record_platform(
    db,
    *,
    actor_user_id: str,
    actor_email: str,
    target_tenant_id: str,
    target_tenant_slug: str,
    action: str,
):
    """Grava um log de PLATAFORMA (fora do tenant), que sobrevive à purga do tenant.

    Use para operações destrutivas do Master (ex.: exclusão de conta), gravando na sessão
    GLOBAL (`get_db`), NUNCA numa `tenant_session` do tenant que está sendo apagado.
    """
    entry = PlatformAuditEntry(
        actor_user_id=actor_user_id,
        actor_email=actor_email,
        target_tenant_id=target_tenant_id,
        target_tenant_slug=target_tenant_slug,
        action=action,
    )
    db.add(entry)
    return entry
