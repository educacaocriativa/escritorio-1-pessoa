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
    """O **id** da entidade sobre a qual a ação aconteceu — ou `""` quando não há entidade.

    **É contrato, e é fechado (issue #312).** `target` é um id, e só isso. NUNCA um composto
    (`f"{source}:{key}"`), NUNCA um valor (uma contagem, um total, uma data). O que não é id vai
    em `detail`, que é livre por definição — ver o docstring logo abaixo. Um id no `target` é o
    que permite JOIN; qualquer outra coisa transforma o consumidor em parser.

    **Por que isto precisou virar contrato escrito.** O campo não tinha nenhum, e por isso
    acumulou TRÊS formas conforme a action: id nu (a esmagadora maioria das chamadas do repo),
    `<source>:<pergunta>` no módulo `dna` e uma contagem crua (`str(exibidas)`) no `open` do
    núcleo. A conta chegou no consumidor: `scripts/nucleo_activation.py` virou PARSER do campo
    (`target.split(":", 1)[0]` e `int(target)`), e aquele parse só era seguro porque a query
    filtrava `action.startswith("dna.")` antes. Não era contrato: era convenção por ação, e a
    convenção morava no chamador. `wallet/models.py` documenta um abuso irmão, já corrigido
    (`target=str(total)` — o VALOR, não um id).

    ⚠️ **Docstring não contém nada sozinha** — foi exatamente uma docstring que descreveu o
    defeito MNT-001 por semanas enquanto os 17 call sites continuavam lá. Quem segura ESTE
    contrato é `tests/test_audit_target_e_id_gate.py`, que reprova por AST qualquer `target=`
    que seja f-string, `str(...)` de valor, concatenação ou literal composto — inclusive quando
    a composição está escondida atrás de uma variável ou de um helper que devolve f-string
    (a forma que o `dna` usava).
    """

    detail: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    """SNAPSHOT em texto livre do que o `target` sozinho não consegue recuperar depois.

    MESMO raciocínio de `PlatformAuditEntry.actor_email` (abaixo): quando a linha apontada pelo
    `target` é APAGADA na própria ação auditada, o id vira um ponteiro para o nada — não há
    FK/join possível depois. Foi o caso que abriu esta coluna (issue #307): `google.credential.
    disconnect` e `.revoked` gravavam `target=cred.id` e apagavam a `GoogleCredential` na mesma
    transação, então QUAL conta Google saiu deixava de existir no banco.

    POR QUE UMA COLUNA, e não compor no `target` (as duas opções que a #307 pesou):

    1. O `target` já foi sobrecarregado antes, e machucou. Sem campo de detalhe, o módulo `dna`
       enfiou três formas diferentes no mesmo campo — id, `f"{source}:{key}"` (por um helper
       `alvo_da_resposta`) e uma contagem crua (`dna/router.py`) — e
       `scripts/nucleo_activation.py` precisou virar PARSER do campo (`target.split(":", 1)[0]`
       e `int(e.target)`). Aquele parse só era seguro porque a query filtra
       `action.startswith("dna.")` antes: o campo não tinha contrato, tinha convenção por ação.
       Uma quarta forma (`id:email`) estenderia exatamente esse defeito.

       ERRATA (2026-09-05, issue #312): o `dna` foi migrado para esta coluna e
       `alvo_da_resposta` deixou de existir — hoje o `save`/`skip` grava `target=<id da
       DnaAnswer>` e `detail=<source>`, e o `open` grava `target=""` e `detail=<exibidas>`.
       O parse SOBREVIVE em `nucleo_activation.py`, mas só como leitura do LEGADO já gravado em
       produção, marcada como tal e coberta por teste. O `target` ganhou o contrato que não
       tinha (ver o docstring da coluna, acima); esta razão nº 1 continua sendo por que a
       coluna existe, e não deixou de valer por ter sido paga.
    2. NÃO CABE, e o estouro seria SILENCIOSO no teste e FATAL em produção. `target` é
       `String(255)`; `cred.id` é um UUID de 36 chars e o e-mail vai a 254 (RFC 5321) — o
       composto chega a 291. O Postgres de produção RECUSA (`value too long for type character
       varying(255)`) e derrubaria justo o `disconnect`; o SQLite da suíte IGNORA o limite e
       ficaria verde. Coluna própria dá 255 inteiros ao e-mail.

    `default=""`/`NOT NULL` (não `nullable`) de propósito: a esmagadora maioria dos
    `audit.record()` do repo não tem detalhe nenhum a dar, segue sem passar nada e grava `""`.
    Ausência de detalhe é "não se aplica", não é desconhecido — não há semântica de NULL a
    preservar aqui (ao contrário da 0086).

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
