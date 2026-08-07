# Vima — Registro de Fatos e Briefing · Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dar ao e1p memória do que aconteceu (`facts`) e uma leitura diária que o dono recebe sem perguntar (o briefing).

**Architecture:** Uma tabela `facts` por tenant, append-only, absorvendo `client_events`. Oito módulos gravam fatos narrativos na mesma transação do fato de negócio. Um compositor determinístico junta Fato (log) + Ausência (estado + relógio) + Tendência (motor financeiro já existente), filtra por `allowed_modules`, colapsa, agrega, prioriza e corta. A Claude só narra o payload pronto — mesmo padrão de `ai_narrator.py`, com anonimizador nas duas pontas e fallback por template.

**Tech Stack:** FastAPI · SQLAlchemy 2 · Alembic · PostgreSQL 16 (RLS `FORCE`) · React 18 + Vite + TypeScript + Tailwind · Anthropic SDK

**Spec:** [`docs/superpowers/specs/2026-08-06-vima-registro-de-fatos-e-briefing-design.md`](../specs/2026-08-06-vima-registro-de-fatos-e-briefing-design.md)

**Branch:** `feat/vima-registro-de-fatos-e-briefing` (criada de `origin/main`, head `0068`)

---

## Global Constraints

Valem para **toda** tarefa deste plano.

- **Isolamento de tenant é RLS, não filtro manual.** Nenhuma query nova adiciona `WHERE tenant_id`. Toda tabela nova herda `TenantMixin` e ganha `ENABLE` + `FORCE ROW LEVEL SECURITY` + policy `tenant_isolation` na migration.
- **"Hoje" é `hoje_do_tenant(db)`** de `app.modules.settings.service`. `datetime.now(UTC).date()` em lógica de negócio é regressão declarada neste repositório.
- **Texto para humano nunca usa `isoformat()`.** Backend: `format_datetime_br` / `format_date_br` de `app.core.tz`. Frontend: `lib/datetime.ts`, única porta de formatação.
- **Nada vai à Claude sem `anonymizer.mask` antes** e `anonymizer.unmask` depois (Regra de Ouro nº 2).
- **Toda ação de IA grava `is_ai=True`** (Regra de Ouro nº 3). Quando a IA **não** rodou, não grava rastro de IA.
- **Migrations que fazem backfill desabilitam a RLS de TODA tabela que a consulta toca** — a de destino *e* as das subconsultas — e restauram `ENABLE` + `FORCE` depois. Sem isso o UPDATE/INSERT roda, não falha, e afeta zero linhas em silêncio.
- **`db.flush()` antes de usar o `id` de um objeto recém-adicionado** como `subject_id`. A dívida MNT-001 registra 17 call sites que gravam trilha apontando para lugar nenhum por não fazer isso.
- **Idioma:** domínio e comentários em PT-BR; identificadores em inglês quando já for a convenção do arquivo.
- **Commits:** Conventional Commits. `main` é protegida — todo trabalho vai por PR.
- **Rodar antes de considerar concluído:** `cd apps/api && pytest` e `pnpm --filter @e1p/web test`. Não confie no `scripts/check.sh` isoladamente — ele mascara falha de frontend com `|| true` no vitest (dívida registrada).

---

## Estrutura de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `apps/api/app/core/facts.py` | **Criar.** Modelo `Fact`, taxonomia de `kind`, função `record()`, guarda da Invariante 2. Espelha o formato de `core/audit.py` (modelo + função no mesmo módulo). |
| `apps/api/migrations/versions/0069_facts.py` | **Criar.** Cria `facts`, migra `client_events`, dropa `client_events`. |
| `apps/api/migrations/versions/0070_briefings.py` | **Criar.** Tabela `briefings`. |
| `apps/api/migrations/versions/0071_user_briefing_prefs.py` | **Criar.** `users.briefing_whatsapp_enabled`, `users.briefing_hour`. |
| `apps/api/app/modules/crm/models.py` | **Modificar.** Remove `ClientEvent` e as constantes `KIND_*`. |
| `apps/api/app/modules/crm/service.py` | **Modificar.** `record_event` vira wrapper fino de `core.facts.record`; 5 call sites. |
| `apps/api/app/modules/crm/timeline.py` | **Modificar.** Metade persistida lê de `Fact`. |
| `apps/api/app/modules/vima/permissions.py` | **Criar.** Filtro de módulo no nível do DADO (não é `require_module`, que é guard de rota). |
| `apps/api/app/modules/vima/absences.py` | **Criar.** As cinco famílias de ausência. Puro, com relógio injetável. |
| `apps/api/app/modules/vima/trends.py` | **Criar.** Adaptador que lê `financial_intelligence/engine.py` sem empurrar I/O para dentro dele. |
| `apps/api/app/modules/vima/composer.py` | **Criar.** Colapso, agregação, priorização, corte. Puro. |
| `apps/api/app/modules/vima/narrator.py` | **Criar.** mask → `ai.complete` → unmask, com fallback por template. |
| `apps/api/app/modules/vima/models.py` | **Criar.** `Briefing`. |
| `apps/api/app/modules/vima/service.py` | **Criar.** Orquestra: coleta → filtra → compõe → narra → grava. Idempotente por (usuário, dia). |
| `apps/api/app/modules/vima/router.py` | **Criar.** `GET /vima/briefing`, `POST /vima/briefing/{id}/read`. |
| `apps/api/app/modules/vima/scheduler.py` | **Criar.** Job que gera e enfileira a entrega. |
| `apps/api/app/core/whatsapp/capabilities.py` | **Modificar.** `briefing_needs_optin`, **com consumidor no mesmo passo**. |
| `apps/web/src/features/vima/BriefingPage.tsx` | **Criar.** A tela, em `ProtectedBareLayout`, 360px-first. |
| `apps/web/src/features/vima/PreferenciasSection.tsx` | **Criar.** WhatsApp do briefing + horário, sem exigir módulo. |
| `apps/web/src/features/crm/ClientTimeline.tsx` | **Modificar.** Chaves de `APARENCIA` para a taxonomia nova. |

---

## Ondas

| Onda | Entregável | Tarefas |
|---|---|---|
| **1** | `facts` existe e absorveu `client_events`. A timeline do contato funciona idêntica. Nada visível mudou. | 1–4 |
| **2** | Oito módulos gravando. O log enche de verdade. | 5–8 |
| **3** | `GET /vima/briefing` devolve o briefing composto e narrado. Sem tela. | 9–14 |
| **4** | O dono vê na tela e recebe no WhatsApp. | 15–19 |
| **5** | `/config` separado em áreas. **Independente** — pode rodar antes, depois ou em paralelo. | 20 |

Pode-se parar depois de qualquer onda com software funcionando.

---

# ONDA 1 — O registro nasce

### Task 1: `core/facts.py` — modelo, taxonomia e `record()`

**Files:**
- Create: `apps/api/app/core/facts.py`
- Modify: `apps/api/app/db/registry.py`
- Test: `apps/api/tests/test_facts_core.py`

**Interfaces:**
- Consumes: `app.db.base.Base`, `TenantMixin`, `TimestampMixin`, `_uuid`
- Produces: `Fact` (modelo), `FactError`, `record(db, *, tenant_id, module, kind, title, actor, body="", client_id=None, subject_type=None, subject_id=None, is_ai=False, occurred_at=None) -> Fact`, e as constantes `CRM_LEAD_CRIADO`, `CRM_LEAD_RETORNOU`, `CRM_ETAPA_MOVIDA`, `CRM_LEAD_REABERTO`, `CRM_NOTA_CRIADA`, `CRM_FUNIL_INSCRITO`

- [ ] **Step 1: Escrever os testes que falham**

```python
# apps/api/tests/test_facts_core.py
"""A função que grava fato: convenção de kind e a Invariante 2 (fato não guarda dinheiro)."""
from datetime import UTC, datetime

import pytest

from app.core.facts import CRM_LEAD_CRIADO, Fact, FactError, record


def test_grava_sem_commitar(db):
    """Mesmo padrão de `receivables.build_charge`: quem chama decide o momento do commit."""
    f = record(
        db, tenant_id="t1", module="crm", kind=CRM_LEAD_CRIADO,
        title="Chegou pelo site", actor="system",
    )
    assert f.id
    assert f.module == "crm"
    assert f.origin == "emitted"
    assert f.is_ai is False
    # Ainda não commitado: a linha só existe na sessão.
    assert db.query(Fact).count() == 0
    db.commit()
    assert db.query(Fact).count() == 1


def test_kind_precisa_comecar_com_o_modulo(db):
    """Convenção `<módulo>.<entidade>.<verbo>` verificada mecanicamente, não por disciplina."""
    with pytest.raises(FactError, match="kind"):
        record(
            db, tenant_id="t1", module="crm", kind="financeiro.pagamento.recebido",
            title="qualquer coisa", actor="system",
        )


def test_titulo_com_dinheiro_e_recusado(db):
    """Invariante 2: o fato diz 'Pagamento de João recebido', nunca 'Recebido R$ 3.200'.

    Copiar o valor criaria uma segunda versão da verdade sobre dinheiro — o bug que a Onda 0
    do Epic 8 desfez. E, como o texto congelado nunca carrega valor, um fato de `crm` é
    estruturalmente incapaz de vazar número financeiro para um sub-usuário só de CRM.
    """
    with pytest.raises(FactError, match="dinheiro"):
        record(
            db, tenant_id="t1", module="financeiro", kind="financeiro.pagamento.recebido",
            title="Recebido R$ 3.200,00 de João", actor="system",
        )


def test_body_pode_conter_dinheiro(db):
    """`body` carrega texto do usuário; `title` é gerado pelo sistema.

    Uma anotação em que o dono escreveu 'combinei R$ 500' são as palavras dele, não uma
    segunda fonte de verdade — recusar isso seria falso positivo.
    """
    f = record(
        db, tenant_id="t1", module="crm", kind="crm.nota.criada",
        title="Anotação", body="combinei R$ 500 de entrada", actor="user:u1",
    )
    assert "R$ 500" in f.body


def test_occurred_at_e_distinto_de_created_at(db):
    """Mensagem recebida 23h50 e processada 23h55 pertence à noite de ontem."""
    ontem = datetime(2026, 8, 5, 23, 50, tzinfo=UTC)
    f = record(
        db, tenant_id="t1", module="whatsapp", kind="whatsapp.mensagem.recebida",
        title="Contato escreveu", actor="client", occurred_at=ontem,
    )
    db.commit()
    assert f.occurred_at == ontem
    assert f.created_at != ontem


def test_dois_fatos_do_mesmo_commit_tem_instantes_distintos(db):
    """`created_at` tem default do lado do PYTHON, sobrescrevendo `server_default=func.now()`.

    No Postgres `now()` é o timestamp da TRANSAÇÃO: dois fatos do mesmo commit sairiam com
    instante idêntico, o desempate cairia no uuid, e a timeline mostraria "Reaberto" acima de
    "Voltou pelo site" — invertendo a causalidade na tela.
    """
    a = record(db, tenant_id="t1", module="crm", kind="crm.lead.retornou",
               title="Voltou pelo site", actor="client")
    b = record(db, tenant_id="t1", module="crm", kind="crm.lead.reaberto",
               title="Reaberto em Entrada", actor="system")
    db.commit()
    assert a.created_at != b.created_at
```

- [ ] **Step 2: Rodar os testes para confirmar que falham**

Run: `cd apps/api && pytest tests/test_facts_core.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'app.core.facts'`

- [ ] **Step 3: Escrever `core/facts.py`**

```python
# apps/api/app/core/facts.py
"""O Registro de Fatos — a memória narrativa do negócio.

Espelha o formato de `core/audit.py` (modelo + função de gravação no mesmo módulo), mas com
propósito distinto: `audit_entries` é trilha TÉCNICA ("quem mutou o quê"), `facts` é NARRATIVA
("o que aconteceu"). A trilha responde auditoria; o fato responde ao dono.

Duas invariantes que valem para toda linha:

1. **Texto congelado.** `title` e `body` são texto, não referência. Um fato gravado hoje diz
   "Movido de Em contato → Proposta" e continua dizendo isso depois de a coluna ser renomeada.
   Evidência não se reescreve sozinha — mesmo princípio de `bank_transactions.raw_description`.

2. **O fato não guarda dinheiro.** O valor é lido de `charges`/`bank_transactions` na hora de
   compor, nunca copiado para cá. Copiar criaria uma segunda versão da verdade sobre dinheiro —
   a forma exata do bug que a Onda 0 do Epic 8 gastou uma onda inteira desfazendo. A guarda
   abaixo torna isso mecânico em vez de disciplina.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.db.base import Base, TenantMixin, TimestampMixin, _uuid

# --- Taxonomia -------------------------------------------------------------------------
# Convenção: `<módulo>.<entidade>.<verbo-no-passado>`. Registro único e greppável — trinta
# módulos emitindo string solta produzem `payment_received` e `payment.received` convivendo
# em seis meses.

CRM_LEAD_CRIADO = "crm.lead.criado"
CRM_LEAD_RETORNOU = "crm.lead.retornou"
CRM_ETAPA_MOVIDA = "crm.etapa.movida"
CRM_LEAD_REABERTO = "crm.lead.reaberto"
CRM_NOTA_CRIADA = "crm.nota.criada"
CRM_FUNIL_INSCRITO = "crm.funil.inscrito"


class FactError(ValueError):
    """Violação de invariante do registro. Estoura a transação de propósito."""


# `R$ 1.234,56`, `R$1234`, `R$ 12,00` — o formato que o sistema gera em `_brl()`.
_PADRAO_DINHEIRO = re.compile(r"R\$\s*[\d.,]+")


class Fact(Base, TenantMixin, TimestampMixin):
    """Um fato narrativo na história do negócio."""

    __tablename__ = "facts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # O vocabulário de `User.allowed_modules`. É o eixo de permissão do briefing.
    module: Mapped[str] = mapped_column(String(32), nullable=False)
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    title: Mapped[str] = mapped_column(String(140), nullable=False)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # CASCADE: a história de um contato não sobrevive ao contato (LGPD, direito ao
    # esquecimento). Contato é o sujeito PRIVILEGIADO num produto centrado em CRM; os demais
    # sujeitos usam a referência leve abaixo, que não cascateia e exige expurgo explícito.
    client_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("clients.id", ondelete="CASCADE"), nullable=True, index=True
    )
    subject_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    subject_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    is_ai: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # QUANDO ACONTECEU, distinto de `created_at` (quando gravamos). Mensagem recebida às 23h50
    # e processada às 23h55 pertence à noite de ontem. A janela do briefing usa este campo.
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False, index=True
    )
    # `emitted` hoje. Existe para que um backfill futuro seja distinguível SEM migration —
    # nenhuma consulta pode assumir que o log cobre desde sempre.
    origin: Mapped[str] = mapped_column(String(16), default="emitted", nullable=False)

    # Default do lado do PYTHON, sobrescrevendo o `server_default=func.now()` do
    # TimestampMixin. No Postgres `now()` é o timestamp da TRANSAÇÃO: dois fatos do mesmo
    # commit sairiam com instante idêntico e o desempate cairia no uuid, invertendo a
    # causalidade na tela. Lição já paga por `ClientEvent`. O `server_default` fica para
    # qualquer INSERT que não passe pelo ORM.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )


def record(
    db: Session,
    *,
    tenant_id: str,
    module: str,
    kind: str,
    title: str,
    actor: str,
    body: str = "",
    client_id: str | None = None,
    subject_type: str | None = None,
    subject_id: str | None = None,
    is_ai: bool = False,
    occurred_at: datetime | None = None,
) -> Fact:
    """Grava um fato narrativo. **NÃO commita** — quem chama decide o momento.

    Sem retry, sem fila, sem abstração. Se falhar, a transação inteira falha — que é o
    comportamento correto: um fato que existe sem o negócio (ou o inverso) é pior que nenhum
    fato.

    ⚠️ Chame `db.flush()` antes se `subject_id` vier de um objeto recém-adicionado: o `id`
    ainda é `None` antes do flush. É a dívida MNT-001 em 17 call sites de `audit.record`.
    """
    if not kind.startswith(f"{module}."):
        raise FactError(
            f"kind '{kind}' não segue a convenção '<módulo>.<entidade>.<verbo>' "
            f"para o módulo '{module}'"
        )
    if _PADRAO_DINHEIRO.search(title):
        raise FactError(
            f"Invariante 2: o título do fato não pode conter valor monetário — {title!r}. "
            "O valor é lido da origem (charges/bank_transactions) na composição."
        )

    fact = Fact(
        tenant_id=tenant_id,
        module=module,
        kind=kind,
        title=title[:140],
        body=body,
        actor=actor,
        client_id=client_id,
        subject_type=subject_type,
        subject_id=subject_id,
        is_ai=is_ai,
        occurred_at=occurred_at or datetime.now(UTC),
    )
    db.add(fact)
    return fact
```

- [ ] **Step 4: Registrar o modelo**

Em `apps/api/app/db/registry.py`, adicionar após a linha `from app.core.audit import ...`:

```python
from app.core.facts import Fact  # noqa: F401
```

- [ ] **Step 5: Rodar os testes para confirmar que passam**

Run: `cd apps/api && pytest tests/test_facts_core.py -v`
Expected: PASS — 6 testes

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/core/facts.py apps/api/app/db/registry.py apps/api/tests/test_facts_core.py
git commit -m "feat: core/facts — o registro de fatos, com as duas invariantes mecânicas"
```

---

### Task 2: Migration 0069 — cria `facts`, absorve `client_events`

**Files:**
- Create: `apps/api/migrations/versions/0069_facts.py`
- Test: `apps/api/tests/test_migration_0069_facts_rls.py`

**Interfaces:**
- Consumes: `Fact` (Task 1)
- Produces: tabela `facts` com RLS `FORCE`; tabela `client_events` deixa de existir

- [ ] **Step 1: Escrever o teste de migration contra Postgres real**

```python
# apps/api/tests/test_migration_0069_facts_rls.py
"""A 0069 migra `client_events` → `facts` e dropa a origem.

Roda contra Postgres REAL como o papel não-superusuário `e1p_app`, porque a armadilha que este
teste existe para pegar é invisível no SQLite: sob `FORCE ROW LEVEL SECURITY` e sem a GUC
`app.current_tenant_id`, o INSERT ... SELECT afeta ZERO LINHAS **em silêncio**. A migration
completa com sucesso aparente e a timeline de todo contato fica vazia em produção.
"""
import pytest

pytestmark = pytest.mark.rls_e2e


def test_backfill_preserva_os_eventos_e_dropa_a_origem(pg_engine_migrado_ate_0069):
    """Semeado com 3 client_events antes da 0069; os 3 precisam existir em `facts`."""
    with pg_engine_migrado_ate_0069.connect() as conn:
        conn.exec_driver_sql("SET app.current_tenant_id = 't1'")
        total = conn.exec_driver_sql("SELECT count(*) FROM facts").scalar()
        assert total == 3, "backfill perdeu linhas — provável RLS ligada na janela"

        modulos = conn.exec_driver_sql("SELECT DISTINCT module FROM facts").scalars().all()
        assert modulos == ["crm"]

        kinds = conn.exec_driver_sql(
            "SELECT kind FROM facts ORDER BY occurred_at"
        ).scalars().all()
        assert kinds == ["crm.lead.criado", "crm.etapa.movida", "crm.nota.criada"]

        # occurred_at herdou o created_at do evento antigo (melhor sinal disponível).
        nulos = conn.exec_driver_sql(
            "SELECT count(*) FROM facts WHERE occurred_at IS NULL"
        ).scalar()
        assert nulos == 0

    with pg_engine_migrado_ate_0069.connect() as conn:
        existe = conn.exec_driver_sql(
            "SELECT to_regclass('public.client_events')"
        ).scalar()
        assert existe is None, "client_events deveria ter sido dropada"


def test_rls_fail_closed_sem_guc(pg_engine_migrado_ate_0069):
    """Sem a GUC do tenant, `facts` não devolve linha nenhuma."""
    with pg_engine_migrado_ate_0069.connect() as conn:
        total = conn.exec_driver_sql("SELECT count(*) FROM facts").scalar()
        assert total == 0


def test_isolamento_cross_tenant(pg_engine_migrado_ate_0069):
    with pg_engine_migrado_ate_0069.connect() as conn:
        conn.exec_driver_sql("SET app.current_tenant_id = 't2'")
        total = conn.exec_driver_sql("SELECT count(*) FROM facts").scalar()
        assert total == 0
```

A fixture `pg_engine_migrado_ate_0069` segue o padrão de `tests/test_receipts_rls.py` (testcontainers, `alembic upgrade` como `e1p_app`), semeando três `client_events` no tenant `t1` **antes** de aplicar a 0069.

- [ ] **Step 2: Rodar para confirmar que falha**

Run: `cd apps/api && pytest tests/test_migration_0069_facts_rls.py -v -m rls_e2e`
Expected: FAIL — a revision 0069 não existe

- [ ] **Step 3: Escrever a migration**

```python
# apps/api/migrations/versions/0069_facts.py
"""Registro de Fatos: cria `facts` e absorve `client_events`

Revision ID: 0069
Revises: 0068
Create Date: 2026-08-06

`client_events` era a linha do tempo narrativa do CRM. `facts` é a mesma ideia para o negócio
inteiro, com duas colunas que o antecessor não tinha: `module` (o eixo de permissão do
briefing, vocabulário de `User.allowed_modules`) e `occurred_at` (quando aconteceu, distinto
de quando gravamos).

Consolidar em vez de coexistir: `client_events` nasceu em 2026-08-04 com pouquíssimos registros
(dois tenants em teste). É o momento mais barato que vai existir para unificar.

⚠️ ARMADILHA QUE **SE APLICA** AQUI: o INSERT ... SELECT abaixo lê `client_events` e escreve em
`facts`. A migration roda como o papel dono NÃO-superusuário `e1p_app`, **sem** a GUC
`app.current_tenant_id`. Sob `FORCE ROW LEVEL SECURITY`, o SELECT devolve zero linhas e o
INSERT grava zero — **em silêncio**. O sintoma em produção não seria erro de deploy, seria "a
timeline de todo contato está vazia". Por isso a RLS das DUAS tabelas é desabilitada só na
janela e restaurada logo depois — mesmo padrão da 0046, 0066, 0067 e 0068. DDL é transacional
no Postgres e a migration roda offline, então não há janela de exposição.

`occurred_at` herda `client_events.created_at`: é o melhor sinal disponível para um evento que
nunca soube distinguir "aconteceu" de "foi gravado".
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0069"
down_revision: str | None = "0068"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# `client_events.kind` era curto e implicitamente do CRM. A taxonomia nova é explícita.
_DE_PARA_KIND = {
    "lead_created": "crm.lead.criado",
    "lead_return": "crm.lead.retornou",
    "stage_move": "crm.etapa.movida",
    "reopened": "crm.lead.reaberto",
    "note": "crm.nota.criada",
    "funnel": "crm.funil.inscrito",
}


def upgrade() -> None:
    op.create_table(
        "facts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("module", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=48), nullable=False),
        sa.Column("title", sa.String(length=140), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("client_id", sa.String(length=36), nullable=True),
        sa.Column("subject_type", sa.String(length=32), nullable=True),
        sa.Column("subject_id", sa.String(length=36), nullable=True),
        sa.Column("actor", sa.String(length=64), nullable=False),
        sa.Column("is_ai", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("origin", sa.String(length=16), nullable=False, server_default="emitted"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["client_id"], ["clients.id"], name="fk_facts_client", ondelete="CASCADE"
        ),
    )
    # A janela do briefing: "o que aconteceu neste tenant desde X".
    op.create_index("ix_facts_tenant_occurred", "facts", ["tenant_id", "occurred_at"])
    # A timeline do contato: "os N mais recentes desta pessoa".
    op.create_index("ix_facts_client_occurred", "facts", ["client_id", "occurred_at"])
    # O filtro de permissão do briefing.
    op.create_index("ix_facts_tenant_module_occurred", "facts", ["tenant_id", "module", "occurred_at"])

    op.execute("ALTER TABLE facts ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE facts FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON facts
            USING (tenant_id = current_setting('app.current_tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true))
        """
    )

    # --- migração dos dados (ver a ARMADILHA no docstring) ---
    op.execute("ALTER TABLE client_events DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE facts DISABLE ROW LEVEL SECURITY")

    caso = " ".join(
        f"WHEN '{antigo}' THEN '{novo}'" for antigo, novo in _DE_PARA_KIND.items()
    )
    op.execute(
        f"""
        INSERT INTO facts (
            id, tenant_id, module, kind, title, body, client_id,
            subject_type, subject_id, actor, is_ai, occurred_at, origin,
            created_at, updated_at
        )
        SELECT
            e.id, e.tenant_id, 'crm',
            CASE e.kind {caso} ELSE 'crm.evento.' || e.kind END,
            e.title, e.body, e.client_id,
            'client', e.client_id, e.actor, e.is_ai, e.created_at, 'emitted',
            e.created_at, e.updated_at
        FROM client_events e
        """
    )

    op.execute("ALTER TABLE facts ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE facts FORCE ROW LEVEL SECURITY")

    op.drop_table("client_events")


def downgrade() -> None:
    """Recria `client_events` vazia. Os dados NÃO voltam.

    Reverter é destrutivo de propósito: fatos de outros módulos gravados depois da 0069 não
    têm para onde ir em `client_events`, que só conhece contatos. Restaurar dados exige backup.
    """
    op.create_table(
        "client_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("client_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("title", sa.String(length=140), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("actor", sa.String(length=64), nullable=False),
        sa.Column("is_ai", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["client_id"], ["clients.id"], name="fk_client_events_client", ondelete="CASCADE"
        ),
    )
    op.execute("ALTER TABLE client_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE client_events FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON client_events
            USING (tenant_id = current_setting('app.current_tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true))
        """
    )
    op.drop_table("facts")
```

- [ ] **Step 4: Rodar o teste de migration**

Run: `cd apps/api && pytest tests/test_migration_0069_facts_rls.py -v -m rls_e2e`
Expected: PASS — 3 testes

- [ ] **Step 5: Provar o teste por mutação**

Comentar as duas linhas `DISABLE ROW LEVEL SECURITY` na migration e rodar de novo.
Expected: `test_backfill_preserva_os_eventos_e_dropa_a_origem` FALHA com `assert 0 == 3`.
Descomentar e confirmar que volta a passar.

⚠️ Não reverta a mutação com `git checkout` — o arquivo tem trabalho não commitado. Edite de volta à mão.

- [ ] **Step 6: Commit**

```bash
git add apps/api/migrations/versions/0069_facts.py apps/api/tests/test_migration_0069_facts_rls.py
git commit -m "feat: migration 0069 — facts absorve client_events, com a janela de RLS no backfill"
```

---

### Task 3: `crm/service.py` passa a gravar em `facts`

**Files:**
- Modify: `apps/api/app/modules/crm/service.py` (`record_event` e os 5 call sites nas linhas 241, 329, 344, 446)
- Modify: `apps/api/app/modules/crm/models.py` (remove `ClientEvent` e as constantes `KIND_*`)
- Modify: `apps/api/app/db/registry.py` (remove `ClientEvent` do import)
- Test: `apps/api/tests/test_lead_absorb.py` (existente — precisa continuar verde)

**Interfaces:**
- Consumes: `app.core.facts.record`, `CRM_LEAD_CRIADO`, `CRM_LEAD_RETORNOU`, `CRM_ETAPA_MOVIDA`, `CRM_LEAD_REABERTO`, `CRM_NOTA_CRIADA`, `CRM_FUNIL_INSCRITO` (Task 1)
- Produces: `crm.service.record_event(db, *, tenant_id, client_id, kind, title, actor, body="", is_ai=False) -> Fact` — mesma assinatura de antes, agora devolvendo `Fact`

- [ ] **Step 1: Escrever o teste que falha**

```python
# apps/api/tests/test_crm_grava_em_facts.py
"""O CRM grava em `facts`, com module='crm' e a taxonomia nova."""
import pytest
from fastapi.testclient import TestClient

from app.core.facts import CRM_LEAD_CRIADO, Fact

REGISTER = {
    "legal_name": "Estúdio Ana", "document": "11222333000181", "slug": "estudioana",
    "email": "ana@example.com", "name": "Ana", "password": "senha-bem-comprida",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_criar_contato_grava_fato_de_crm(client: TestClient, headers, db):
    client.post("/crm/clients", json={"name": "Flavio Kato"}, headers=headers)
    fatos = db.query(Fact).all()
    assert len(fatos) == 1
    assert fatos[0].module == "crm"
    assert fatos[0].kind == CRM_LEAD_CRIADO
    assert fatos[0].client_id is not None
    assert fatos[0].subject_type == "client"
```

- [ ] **Step 2: Rodar para confirmar que falha**

Run: `cd apps/api && pytest tests/test_crm_grava_em_facts.py -v`
Expected: FAIL — nenhum `Fact` gravado (o CRM ainda escreve em `ClientEvent`)

- [ ] **Step 3: Reescrever `record_event` como wrapper**

Em `apps/api/app/modules/crm/service.py`, substituir a função inteira (linhas 167–190):

```python
def record_event(
    db: Session,
    *,
    tenant_id: str,
    client_id: str,
    kind: str,
    title: str,
    actor: str,
    body: str = "",
    is_ai: bool = False,
) -> Fact:
    """Grava um fato narrativo do CRM. **NÃO commita** — quem chama decide o momento.

    Wrapper fino sobre `core.facts.record`: mantido porque os 5 call sites do CRM não precisam
    repetir `module="crm"` nem `subject_type="client"`, e porque a assinatura já era esta.
    """
    return facts.record(
        db, tenant_id=tenant_id, module="crm", kind=kind, title=title,
        actor=actor, body=body, client_id=client_id,
        subject_type="client", subject_id=client_id, is_ai=is_ai,
    )
```

Trocar o import no topo do arquivo: remover `ClientEvent` de `from app.modules.crm.models import ...` e adicionar:

```python
from app.core import facts
from app.core.facts import (
    CRM_ETAPA_MOVIDA, CRM_FUNIL_INSCRITO, CRM_LEAD_CRIADO,
    CRM_LEAD_REABERTO, CRM_LEAD_RETORNOU, CRM_NOTA_CRIADA, Fact,
)
```

- [ ] **Step 4: Trocar as constantes nos 5 call sites**

Nas linhas 241, 329, 344 e 446, substituir cada `kind=KIND_X` da lista antiga pela constante nova correspondente: `KIND_LEAD_CREATED`→`CRM_LEAD_CRIADO`, `KIND_LEAD_RETURN`→`CRM_LEAD_RETORNOU`, `KIND_STAGE_MOVE`→`CRM_ETAPA_MOVIDA`, `KIND_REOPENED`→`CRM_LEAD_REABERTO`, `KIND_NOTE`→`CRM_NOTA_CRIADA`, `KIND_FUNNEL`→`CRM_FUNIL_INSCRITO`.

- [ ] **Step 5: Remover `ClientEvent` do modelo e do registry**

Em `apps/api/app/modules/crm/models.py`: apagar a classe `ClientEvent` inteira e o bloco de constantes `KIND_*` / `EVENT_KINDS`. Remover os imports que ficarem órfãos (`Boolean`, `Text`, `func`, `UTC`, `datetime`) **somente se** nenhum outro modelo do arquivo os usar.

Em `apps/api/app/db/registry.py`, trocar:

```python
from app.modules.crm.models import Client, ClientEvent, PipelineStage  # noqa: F401
```

por:

```python
from app.modules.crm.models import Client, PipelineStage  # noqa: F401
```

- [ ] **Step 6: Rodar a suíte do CRM inteira**

Run: `cd apps/api && pytest tests/test_crm_grava_em_facts.py tests/test_lead_absorb.py tests/test_crm.py tests/test_crm_merge.py tests/test_crm_stage_order_gate.py -v`
Expected: PASS. `test_lead_absorb.py` cobre a ordenação de `lead_return` + `reopened` no mesmo commit — ela prova que o default de `created_at` em Python sobreviveu à mudança.

- [ ] **Step 7: Commit**

```bash
git add apps/api/app/modules/crm/ apps/api/app/db/registry.py apps/api/tests/test_crm_grava_em_facts.py
git commit -m "refactor: CRM grava em facts; ClientEvent removido"
```

---

### Task 4: `crm/timeline.py` lê de `facts`

**Files:**
- Modify: `apps/api/app/modules/crm/timeline.py:24,54-69`
- Modify: `apps/web/src/features/crm/ClientTimeline.tsx:12-22`
- Test: `apps/api/tests/test_client_timeline.py` (existente — precisa continuar verde)

**Interfaces:**
- Consumes: `app.core.facts.Fact` (Task 1)
- Produces: nenhuma mudança de contrato HTTP — `GET /crm/clients/{id}/timeline` devolve o mesmo shape

- [ ] **Step 1: Escrever o teste que falha**

```python
# adicionar em apps/api/tests/test_client_timeline.py
def test_timeline_le_de_facts_com_a_taxonomia_nova(client: TestClient, headers, contato):
    """A metade PERSISTIDA mudou de tabela; a DERIVADA (quotes/charges) não mudou nada."""
    corpo = client.get(f"/crm/clients/{contato}/timeline", headers=headers).json()
    assert [e["kind"] for e in corpo["entries"]] == ["crm.lead.criado"]
```

- [ ] **Step 2: Rodar para confirmar que falha**

Run: `cd apps/api && pytest tests/test_client_timeline.py::test_timeline_le_de_facts_com_a_taxonomia_nova -v`
Expected: FAIL — `AssertionError: ['lead_created'] != ['crm.lead.criado']`

- [ ] **Step 3: Trocar a fonte persistida**

Em `apps/api/app/modules/crm/timeline.py`, trocar o import da linha 24:

```python
from app.core.facts import Fact
```

E substituir o bloco das linhas 54–69:

```python
    eventos = list(
        db.scalars(
            select(Fact)
            .where(Fact.client_id == client_id)
            .order_by(Fact.occurred_at.desc(), Fact.id.desc())
            .limit(limit + 1)
        ).all()
    )
    if len(eventos) > limit:
        truncated = True
        eventos = eventos[:limit]
    for e in eventos:
        entradas.append({
            "id": e.id, "kind": e.kind, "title": e.title, "body": e.body,
            "actor": e.actor, "is_ai": e.is_ai, "at": _instante(e.occurred_at),
        })
```

Atualizar a docstring do módulo: a fonte persistida agora é `facts`, não `client_events`. A frase sobre o financeiro ser lido na origem **permanece** — a Invariante 2 não mudou.

- [ ] **Step 4: Atualizar o mapa de aparência no frontend**

Em `apps/web/src/features/crm/ClientTimeline.tsx`, substituir as seis primeiras chaves de `APARENCIA`. As três últimas (`quote`, `charge`, `payment`) **não mudam** — são geradas pelo próprio `timeline.py` a partir de `quotes`/`charges`, não lidas da tabela.

```tsx
const APARENCIA: Record<string, { icon: JSX.Element; cor: string }> = {
  "crm.lead.criado": { icon: <UserPlus size={14} />, cor: "bg-primary-50 text-primary-700" },
  "crm.lead.retornou": { icon: <RotateCcw size={14} />, cor: "bg-primary-50 text-primary-700" },
  "crm.etapa.movida": { icon: <ArrowRightLeft size={14} />, cor: "bg-neutral-100 text-neutral-600" },
  "crm.lead.reaberto": { icon: <RotateCcw size={14} />, cor: "bg-amber-50 text-amber-700" },
  "crm.nota.criada": { icon: <MessageSquarePlus size={14} />, cor: "bg-emerald-50 text-emerald-700" },
  "crm.funil.inscrito": { icon: <Workflow size={14} />, cor: "bg-neutral-100 text-neutral-600" },
  quote: { icon: <FileText size={14} />, cor: "bg-sky-50 text-sky-700" },
  charge: { icon: <Receipt size={14} />, cor: "bg-sky-50 text-sky-700" },
  payment: { icon: <Receipt size={14} />, cor: "bg-emerald-50 text-emerald-700" },
};
```

O `?? NEUTRO` já existente significa que uma chave errada degrada para o ícone neutro — é cosmético, não derruba a tela.

- [ ] **Step 5: Rodar backend e frontend**

Run: `cd apps/api && pytest tests/test_client_timeline.py -v`
Expected: PASS

Run: `pnpm --filter @e1p/web test -- ClientTimeline`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/modules/crm/timeline.py apps/api/tests/test_client_timeline.py apps/web/src/features/crm/ClientTimeline.tsx
git commit -m "refactor: timeline do contato lê de facts"
```

> **Fim da Onda 1.** `facts` existe, o CRM grava nela, a timeline lê dela, `client_events` não existe mais. Nada visível mudou para o usuário. Ponto de parada válido.

---

# ONDA 2 — Os oito emissores

Todos seguem a mesma forma: `facts.record(...)` na camada de **serviço**, dentro da mesma transação do fato de negócio, com `db.flush()` antes se o `id` do sujeito for necessário.

### Task 5: `receivables` e `payables` emitem

**Files:**
- Modify: `apps/api/app/core/facts.py` (constantes novas)
- Modify: `apps/api/app/modules/receivables/service.py`
- Modify: `apps/api/app/modules/payables/service.py`
- Test: `apps/api/tests/test_facts_financeiro.py`

**Interfaces:**
- Consumes: `facts.record` (Task 1)
- Produces: constantes `FIN_PAGAMENTO_RECEBIDO`, `FIN_COBRANCA_VENCIDA`, `FIN_COBRANCA_PROTESTADA`, `FIN_CONTA_PAGA`

- [ ] **Step 1: Escrever o teste que falha**

```python
# apps/api/tests/test_facts_financeiro.py
"""Receber e pagar gravam fato — sem o valor no título (Invariante 2)."""
import pytest
from fastapi.testclient import TestClient

from app.core.facts import FIN_CONTA_PAGA, FIN_PAGAMENTO_RECEBIDO, Fact

REGISTER = {
    "legal_name": "Estúdio Ana", "document": "11222333000181", "slug": "estudioana",
    "email": "ana@example.com", "name": "Ana", "password": "senha-bem-comprida",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_baixa_de_cobranca_grava_fato_sem_valor(client: TestClient, headers, db):
    contato = client.post(
        "/crm/clients", json={"name": "Flavio Kato"}, headers=headers
    ).json()["id"]
    cobranca = client.post(
        "/receivables/charges",
        json={"client_id": contato, "description": "Consultoria",
              "amount_cents": 320000, "due_date": "2026-08-20", "method": "pix"},
        headers=headers,
    ).json()
    client.post(f"/receivables/charges/{cobranca['id']}/pay", headers=headers)

    fato = db.query(Fact).filter(Fact.kind == FIN_PAGAMENTO_RECEBIDO).one()
    assert fato.module == "financeiro"
    assert fato.subject_type == "charge"
    assert fato.subject_id == cobranca["id"]
    assert fato.client_id == contato
    assert "R$" not in fato.title  # Invariante 2


def test_conta_paga_grava_fato(client: TestClient, headers, db):
    conta = client.post(
        "/payables/bills",
        json={"description": "Aluguel", "amount_cents": 89000,
              "due_date": "2026-08-10", "category": "estrutura"},
        headers=headers,
    ).json()
    client.post(f"/payables/bills/{conta['id']}/pay", headers=headers)

    fato = db.query(Fact).filter(Fact.kind == FIN_CONTA_PAGA).one()
    assert fato.module == "financeiro"
    assert fato.subject_type == "payable"
    assert "R$" not in fato.title
```

- [ ] **Step 2: Rodar para confirmar que falha**

Run: `cd apps/api && pytest tests/test_facts_financeiro.py -v`
Expected: FAIL com `ImportError: cannot import name 'FIN_CONTA_PAGA'`

- [ ] **Step 3: Adicionar as constantes**

Em `apps/api/app/core/facts.py`, após as constantes de CRM:

```python
FIN_PAGAMENTO_RECEBIDO = "financeiro.pagamento.recebido"
FIN_COBRANCA_VENCIDA = "financeiro.cobranca.vencida"
FIN_COBRANCA_PROTESTADA = "financeiro.cobranca.protestada"
FIN_CONTA_PAGA = "financeiro.conta.paga"
```

- [ ] **Step 4: Emitir em `receivables`**

Em `apps/api/app/modules/receivables/service.py`, dentro de `apply_paid` (a versão sem commit, extraída em ondas anteriores), logo após marcar a cobrança como paga:

```python
    facts.record(
        db,
        tenant_id=charge.tenant_id,
        module="financeiro",
        kind=FIN_PAGAMENTO_RECEBIDO,
        title=f"Pagamento de {_nome_do_contato(db, charge.client_id)} recebido",
        actor="system",
        client_id=charge.client_id,
        subject_type="charge",
        subject_id=charge.id,
    )
```

Onde `_nome_do_contato` é um helper local que devolve `Client.name` ou `"contato não identificado"`. **O valor não entra no título** — quem compõe o briefing lê `charge.amount_cents` na origem.

Mesma forma em `protest_charge` (`FIN_COBRANCA_PROTESTADA`, título `f"Cobrança de {nome} protestada"`).

- [ ] **Step 5: Emitir em `payables`**

Em `apps/api/app/modules/payables/service.py`, dentro de `apply_paid`:

```python
    facts.record(
        db,
        tenant_id=payable.tenant_id,
        module="financeiro",
        kind=FIN_CONTA_PAGA,
        title=f"Conta paga: {payable.description[:80]}",
        actor="system",
        subject_type="payable",
        subject_id=payable.id,
    )
```

- [ ] **Step 6: Rodar os testes**

Run: `cd apps/api && pytest tests/test_facts_financeiro.py tests/test_receivables.py tests/test_payables.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add apps/api/app/core/facts.py apps/api/app/modules/receivables/ apps/api/app/modules/payables/ apps/api/tests/test_facts_financeiro.py
git commit -m "feat: receivables e payables emitem fato"
```

---

### Task 6: `agenda` e `quotes` emitem

**Files:**
- Modify: `apps/api/app/core/facts.py`
- Modify: `apps/api/app/modules/agenda/service.py`
- Modify: `apps/api/app/modules/quotes/service.py`
- Test: `apps/api/tests/test_facts_agenda_quotes.py`

**Interfaces:**
- Produces: `AGENDA_EVENTO_CANCELADO`, `AGENDA_EVENTO_REMARCADO`, `COM_ORCAMENTO_ENVIADO`, `COM_ORCAMENTO_ACEITO`, `COM_ORCAMENTO_RECUSADO`

- [ ] **Step 1: Escrever o teste que falha**

```python
# apps/api/tests/test_facts_agenda_quotes.py
"""Agenda e orçamentos gravam fato."""
import pytest
from fastapi.testclient import TestClient

from app.core.facts import AGENDA_EVENTO_CANCELADO, COM_ORCAMENTO_ACEITO, Fact

REGISTER = {
    "legal_name": "Estúdio Ana", "document": "11222333000181", "slug": "estudioana",
    "email": "ana@example.com", "name": "Ana", "password": "senha-bem-comprida",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_cancelar_evento_grava_fato(client: TestClient, headers, db):
    evento = client.post(
        "/agenda/events",
        json={"title": "Reunião com Maria", "starts_at": "2026-08-10T14:00:00Z",
              "ends_at": "2026-08-10T15:00:00Z"},
        headers=headers,
    ).json()
    client.post(f"/agenda/events/{evento['id']}/cancel", headers=headers)

    fato = db.query(Fact).filter(Fact.kind == AGENDA_EVENTO_CANCELADO).one()
    assert fato.module == "agenda"
    assert fato.subject_type == "agenda_event"
    assert "Reunião com Maria" in fato.title


def test_aprovar_orcamento_grava_fato(client: TestClient, headers, db):
    contato = client.post(
        "/crm/clients", json={"name": "Flavio Kato"}, headers=headers
    ).json()["id"]
    orcamento = client.post(
        "/quotes",
        json={"client_id": contato, "title": "Consultoria",
              "items": [{"description": "Hora", "quantity": 10, "unit_cents": 20000}]},
        headers=headers,
    ).json()
    client.post(f"/quotes/{orcamento['id']}/approve", headers=headers)

    fato = db.query(Fact).filter(Fact.kind == COM_ORCAMENTO_ACEITO).one()
    assert fato.module == "comercial"
    assert fato.client_id == contato
    assert "R$" not in fato.title  # Invariante 2
```

- [ ] **Step 2: Rodar para confirmar que falha**

Run: `cd apps/api && pytest tests/test_facts_agenda_quotes.py -v`
Expected: FAIL com `ImportError`

- [ ] **Step 3: Adicionar as constantes**

Em `apps/api/app/core/facts.py`:

```python
AGENDA_EVENTO_CANCELADO = "agenda.evento.cancelado"
AGENDA_EVENTO_REMARCADO = "agenda.evento.remarcado"

COM_ORCAMENTO_ENVIADO = "comercial.orcamento.enviado"
COM_ORCAMENTO_ACEITO = "comercial.orcamento.aceito"
COM_ORCAMENTO_RECUSADO = "comercial.orcamento.recusado"
```

⚠️ `quotes` e `pages` usam `module="comercial"`, não `module="quotes"` — o vocabulário é o de `allowed_modules`, que o dono enxerga na tela de permissões, não o nome da pasta.

- [ ] **Step 4: Emitir em `agenda`**

Em `apps/api/app/modules/agenda/service.py`, dentro de `cancel_event`, após a troca de status:

```python
    facts.record(
        db, tenant_id=event.tenant_id, module="agenda", kind=AGENDA_EVENTO_CANCELADO,
        title=f"Cancelado: {event.title[:100]}", actor=f"user:{user_id}",
        subject_type="agenda_event", subject_id=event.id,
    )
```

E em `reschedule_event`, com `AGENDA_EVENTO_REMARCADO` e título `f"Remarcado: {event.title[:100]}"`.

- [ ] **Step 5: Emitir em `quotes`**

Em `apps/api/app/modules/quotes/service.py`, dentro de `approve_quote` (antes do efeito dominó, para que o fato do orçamento preceda o da cobrança na ordem):

```python
    facts.record(
        db, tenant_id=quote.tenant_id, module="comercial", kind=COM_ORCAMENTO_ACEITO,
        title=f"Orçamento “{quote.title[:80]}” aceito", actor="client",
        client_id=quote.client_id, subject_type="quote", subject_id=quote.id,
    )
```

E em `send_quote` (`COM_ORCAMENTO_ENVIADO`) e `reject_quote` (`COM_ORCAMENTO_RECUSADO`), com os títulos análogos.

- [ ] **Step 6: Rodar os testes**

Run: `cd apps/api && pytest tests/test_facts_agenda_quotes.py tests/test_agenda.py tests/test_quotes.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add apps/api/app/core/facts.py apps/api/app/modules/agenda/ apps/api/app/modules/quotes/ apps/api/tests/test_facts_agenda_quotes.py
git commit -m "feat: agenda e quotes emitem fato"
```

---

### Task 7: `whatsapp_inbox` emite — e o dono para de virar lead

**Files:**
- Modify: `apps/api/app/core/facts.py`
- Modify: `apps/api/app/modules/whatsapp_inbox/service.py` (`ingest_webhook_payload`)
- Test: `apps/api/tests/test_facts_whatsapp.py`

**Interfaces:**
- Produces: `WA_MENSAGEM_RECEBIDA`; guarda `_e_telefone_de_usuario(db, phone_key) -> bool`

- [ ] **Step 1: Escrever os testes que falham**

```python
# apps/api/tests/test_facts_whatsapp.py
"""Mensagem recebida vira fato — e a do próprio dono não vira lead."""
from app.core.facts import WA_MENSAGEM_RECEBIDA, Fact
from app.modules.crm.models import Client
from app.modules.whatsapp_inbox import service as inbox


def _payload(telefone: str, texto: str) -> dict:
    return {
        "event": "messages.upsert",
        "data": {
            "key": {"remoteJid": f"{telefone}@s.whatsapp.net", "id": "MSG1", "fromMe": False},
            "pushName": "Contato",
            "message": {"conversation": texto},
            "messageTimestamp": 1754400000,
        },
    }


def test_mensagem_de_contato_vira_fato(db, tenant_semeado):
    inbox.ingest_webhook_payload(db, tenant_id=tenant_semeado.id,
                                 payload=_payload("5511999998888", "oi"))
    db.commit()
    fato = db.query(Fact).filter(Fact.kind == WA_MENSAGEM_RECEBIDA).one()
    assert fato.module == "comercial"
    assert fato.client_id is not None


def test_mensagem_do_proprio_dono_nao_vira_lead_nem_fato(db, tenant_semeado, dono):
    """Bug pré-existente que o opt-in por botão da Meta tornaria diário.

    O telefone do dono está em `User.phone`. Pelo caminho normal de ingestão, `absorb_lead`
    criaria um contato no CRM para ele — e ele apareceria no próprio funil de vendas.
    """
    antes = db.query(Client).count()
    inbox.ingest_webhook_payload(
        db, tenant_id=tenant_semeado.id,
        payload=_payload(dono.phone, "Ver briefing"),
    )
    db.commit()
    assert db.query(Client).count() == antes
    assert db.query(Fact).filter(Fact.kind == WA_MENSAGEM_RECEBIDA).count() == 0
```

A fixture `dono` devolve o `User` do tenant com `phone="5511977776666"` preenchido.

- [ ] **Step 2: Rodar para confirmar que falha**

Run: `cd apps/api && pytest tests/test_facts_whatsapp.py -v`
Expected: FAIL — `ImportError` na primeira, e a segunda cria um `Client` a mais

- [ ] **Step 3: Adicionar a constante e a guarda**

Em `apps/api/app/core/facts.py`:

```python
WA_MENSAGEM_RECEBIDA = "comercial.mensagem.recebida"
```

Em `apps/api/app/modules/whatsapp_inbox/service.py`, um helper novo:

```python
def _e_telefone_de_usuario(db: Session, phone_key: str | None) -> bool:
    """O telefone é de um usuário ATIVO deste tenant?

    Mensagem do próprio dono (ou de um funcionário) não é lead: ela entraria no funil de
    vendas e no painel de inadimplência como se fosse cliente. Com o opt-in do briefing por
    botão na Meta, isso passaria a acontecer todo dia.

    ⚠️ `users` é tabela GLOBAL, sem RLS — o filtro por `tenant_id` aqui é explícito e
    obrigatório (é a exceção documentada na Regra de Ouro nº 1).
    """
    if not phone_key:
        return False
    encontrado = db.execute(
        select(User.id)
        .where(User.tenant_id == _tenant_atual(db))
        .where(User.is_active.is_(True))
        .where(User.phone.is_not(None))
    ).all()
    return any(normalize_br(u_phone) == phone_key for (u_phone,) in _fones(db))
```

Implementação concreta (o helper acima em forma final, sem pseudo-código):

```python
def _e_telefone_de_usuario(db: Session, tenant_id: str, phone_key: str | None) -> bool:
    if not phone_key:
        return False
    fones = db.scalars(
        select(User.phone)
        .where(User.tenant_id == tenant_id)
        .where(User.is_active.is_(True))
        .where(User.phone.is_not(None))
    ).all()
    return any(normalize_br(f) == phone_key for f in fones)
```

- [ ] **Step 4: Aplicar a guarda e emitir o fato**

Em `ingest_webhook_payload`, logo depois de resolver `phone_key` da mensagem recebida e **antes** de qualquer chamada a `absorb_lead` / `_get_or_create_chat`:

```python
    if _e_telefone_de_usuario(db, tenant_id, phone_key):
        # Mensagem do próprio time. Não vira lead, não vira conversa de cliente, não vira
        # fato. O consumidor dela é o opt-in do briefing (Task 19), que lê o payload do
        # botão antes de chegar aqui.
        return None
```

E, após criar a `WhatsappMessage` de entrada:

```python
    facts.record(
        db, tenant_id=tenant_id, module="comercial", kind=WA_MENSAGEM_RECEBIDA,
        title=f"{nome_ou_telefone} escreveu no WhatsApp", actor="client",
        client_id=chat.client_id, subject_type="whatsapp_chat", subject_id=chat.id,
        occurred_at=instante_da_mensagem,
    )
```

`occurred_at` vem do `messageTimestamp` do payload, **não** de `now()` — é exatamente o caso que a coluna existe para resolver.

- [ ] **Step 5: Rodar os testes**

Run: `cd apps/api && pytest tests/test_facts_whatsapp.py tests/test_whatsapp_inbox.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/core/facts.py apps/api/app/modules/whatsapp_inbox/ apps/api/tests/test_facts_whatsapp.py
git commit -m "feat: whatsapp_inbox emite fato; mensagem do próprio time não vira lead"
```

---

### Task 8: `pages` e `funnels` emitem — incluindo a jornada que falha

**Files:**
- Modify: `apps/api/app/core/facts.py`
- Modify: `apps/api/app/modules/pages/service.py` (`public_submit`)
- Modify: `apps/api/app/modules/funnels/engine.py` (`_drive`, caminho de falha)
- Test: `apps/api/tests/test_facts_pages_funnels.py`

**Interfaces:**
- Produces: `COM_FORMULARIO_RECEBIDO`, `COM_PAGINA_PUBLICADA`, `OP_JORNADA_INSCRITA`, `OP_JORNADA_CONCLUIDA`, `OP_JORNADA_FALHOU`

- [ ] **Step 1: Escrever os testes que falham**

```python
# apps/api/tests/test_facts_pages_funnels.py
"""Topo do funil: página converteu, jornada andou — e jornada que quebrou em silêncio."""
from app.core.facts import COM_FORMULARIO_RECEBIDO, OP_JORNADA_FALHOU, Fact


def test_formulario_da_pagina_grava_fato_com_a_pagina_de_origem(db, pagina_publicada):
    """A ATRIBUIÇÃO é o que torna o fato útil: qual página converteu."""
    from app.modules.pages import service as pages

    pages.public_submit(
        db, slug=pagina_publicada.slug,
        dados={"name": "Maria", "phone": "(11) 98888-7777"},
    )
    db.commit()

    fato = db.query(Fact).filter(Fact.kind == COM_FORMULARIO_RECEBIDO).one()
    assert fato.module == "comercial"
    assert fato.subject_type == "page"
    assert fato.subject_id == pagina_publicada.id
    assert pagina_publicada.title in fato.title


def test_jornada_que_falha_grava_fato(db, funil_com_no_quebrado, contato):
    """Hoje uma ação de nó que falha marca a run como `failed` e NÃO derruba a request — por
    design. Ninguém é avisado, e o dono descobre semanas depois porque um cliente reclamou.
    """
    from app.modules.funnels import engine

    engine.enroll(db, funnel_id=funil_com_no_quebrado.id, client_id=contato.id)
    db.commit()

    fato = db.query(Fact).filter(Fact.kind == OP_JORNADA_FALHOU).one()
    assert fato.module == "operacao"
    assert fato.subject_type == "funnel_run"
    assert funil_com_no_quebrado.name in fato.title
```

- [ ] **Step 2: Rodar para confirmar que falha**

Run: `cd apps/api && pytest tests/test_facts_pages_funnels.py -v`
Expected: FAIL com `ImportError`

- [ ] **Step 3: Adicionar as constantes**

```python
COM_FORMULARIO_RECEBIDO = "comercial.formulario.recebido"
COM_PAGINA_PUBLICADA = "comercial.pagina.publicada"

OP_JORNADA_INSCRITA = "operacao.jornada.inscrita"
OP_JORNADA_CONCLUIDA = "operacao.jornada.concluida"
OP_JORNADA_FALHOU = "operacao.jornada.falhou"
```

- [ ] **Step 4: Emitir em `pages`**

Em `public_submit`, após `absorb_lead` devolver o contato:

```python
    facts.record(
        db, tenant_id=page.tenant_id, module="comercial", kind=COM_FORMULARIO_RECEBIDO,
        title=f"Formulário recebido da página “{page.title[:70]}”", actor="client",
        client_id=cliente.id, subject_type="page", subject_id=page.id,
    )
```

O `absorb_lead` já grava `crm.lead.criado`. **Os dois fatos ficam** — a atribuição de marketing e o nascimento do contato são informações diferentes, e o V3 vai querer as duas. Quem funde numa linha só é o compositor (Task 12).

Em `publish_page`, emitir `COM_PAGINA_PUBLICADA` com `title=f"Página “{page.title[:70]}” publicada"` e `actor=f"user:{user_id}"`.

- [ ] **Step 5: Emitir em `funnels`**

Em `apps/api/app/modules/funnels/engine.py`, dentro de `_drive`, no bloco `except` que hoje marca a run como `failed`:

```python
    except Exception as exc:  # noqa: BLE001 — o comportamento de não derrubar é deliberado
        run.status = "failed"
        run.last_error = str(exc)[:500]
        facts.record(
            db, tenant_id=run.tenant_id, module="operacao", kind=OP_JORNADA_FALHOU,
            title=f"Automação “{funnel.name[:70]}” falhou", body=str(exc)[:500],
            actor="system", client_id=run.client_id,
            subject_type="funnel_run", subject_id=run.id,
        )
        logger.exception("Jornada %s falhou", run.id)
        return
```

E, em `enroll`, `OP_JORNADA_INSCRITA`; ao chegar em `status="done"`, `OP_JORNADA_CONCLUIDA`.

- [ ] **Step 6: Rodar os testes**

Run: `cd apps/api && pytest tests/test_facts_pages_funnels.py tests/test_pages.py tests/test_funnels_engine.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add apps/api/app/core/facts.py apps/api/app/modules/pages/ apps/api/app/modules/funnels/ apps/api/tests/test_facts_pages_funnels.py
git commit -m "feat: pages e funnels emitem fato — incluindo a jornada que falha em silêncio"
```

> **Fim da Onda 2.** Oito módulos gravando. O log enche de verdade. Ainda nada visível. Ponto de parada válido.

---

# ONDA 3 — O briefing como API

### Task 9: Filtro de permissão no nível do dado

**Files:**
- Create: `apps/api/app/modules/vima/__init__.py` (vazio)
- Create: `apps/api/app/modules/vima/permissions.py`
- Test: `apps/api/tests/test_vima_permissions.py`

**Interfaces:**
- Produces: `modulos_permitidos(user: CurrentUser) -> set[str] | None` (`None` = todos), `pode_ver(user, module) -> bool`

- [x] **Step 1: Escrever o teste que falha**

```python
# apps/api/tests/test_vima_permissions.py
"""O filtro decide quais REGRAS rodam, não quais resultados aparecem."""
from app.core.tenancy import CurrentUser
from app.modules.vima.permissions import modulos_permitidos, pode_ver


def _usuario(role: str, modulos: list[str]) -> CurrentUser:
    return CurrentUser(
        user_id="u1", tenant_id="t1", role=role,
        allowed_modules=modulos, is_platform_admin=False,
    )


def test_owner_ve_tudo():
    assert modulos_permitidos(_usuario("owner", [])) is None
    assert pode_ver(_usuario("owner", []), "financeiro") is True


def test_lista_vazia_em_sub_usuario_tambem_e_tudo():
    """`allowed_modules=[]` significa 'sem restrição' em `require_module`. Mesmo sentido aqui —
    divergir criaria dois significados para o mesmo dado."""
    assert modulos_permitidos(_usuario("sub_user", [])) is None


def test_sub_usuario_so_de_crm_nao_ve_financeiro():
    u = _usuario("sub_user", ["crm", "comercial"])
    assert modulos_permitidos(u) == {"crm", "comercial"}
    assert pode_ver(u, "financeiro") is False
    assert pode_ver(u, "crm") is True
```

- [x] **Step 2: Rodar para confirmar que falha**

Run: `cd apps/api && pytest tests/test_vima_permissions.py -v`
Expected: FAIL com `ModuleNotFoundError`

- [x] **Step 3: Escrever `permissions.py`**

```python
# apps/api/app/modules/vima/permissions.py
"""Filtro de módulo no nível do DADO.

`core.tenancy.require_module` é guard de ROTA — bloqueia acesso a um endpoint. O briefing é
*uma* rota que atravessa oito módulos, então precisa de um filtro diferente: quais fatos,
ausências e tendências este usuário pode ver.

A regra de decisão é a MESMA de `require_module` (owner vê tudo; lista vazia vê tudo; senão
só o que está na lista). Divergir daria dois significados para `allowed_modules` e o bug
apareceria como vazamento, não como erro.

⚠️ O filtro decide quais REGRAS RODAM, não quais resultados aparecem. Para um usuário só de
CRM a regra de tendência financeira não é executada — não é calculada e escondida. Mais barato,
e elimina a classe inteira de bug em que um dado proibido vaza porque alguém esqueceu de
aplicar o filtro na saída.
"""
from __future__ import annotations

from app.core.tenancy import CurrentUser


def modulos_permitidos(user: CurrentUser) -> set[str] | None:
    """Devolve o conjunto de módulos visíveis, ou `None` quando não há restrição."""
    if user.role == "owner" or not user.allowed_modules:
        return None
    return set(user.allowed_modules)


def pode_ver(user: CurrentUser, module: str) -> bool:
    permitidos = modulos_permitidos(user)
    return permitidos is None or module in permitidos
```

- [x] **Step 4: Rodar para confirmar que passa**

Run: `cd apps/api && pytest tests/test_vima_permissions.py -v`
Expected: PASS — 3 testes

- [x] **Step 5: Commit**

```bash
git add apps/api/app/modules/vima/ apps/api/tests/test_vima_permissions.py
git commit -m "feat: vima/permissions — filtro de módulo no nível do dado"
```

---

### Task 10: As cinco famílias de Ausência

**Files:**
- Create: `apps/api/app/modules/vima/absences.py`
- Test: `apps/api/tests/test_vima_absences.py`

**Interfaces:**
- Consumes: `modulos_permitidos` (Task 9), `hoje_do_tenant` de `app.modules.settings.service`
- Produces: `@dataclass Ausencia(module, kind, title, subject_type, subject_id, dias, client_id)`, `coletar(db, *, user, hoje, limiares=None) -> list[Ausencia]`, `LIMIARES_PADRAO: dict[str, int]`

- [x] **Step 1: Escrever os testes que falham**

```python
# apps/api/tests/test_vima_absences.py
"""Ausência = estado em aberto + relógio. Não vem do log, então funciona no dia 1."""
from datetime import date, timedelta

from app.modules.vima.absences import LIMIARES_PADRAO, coletar


def test_boleto_que_vence_amanha_aparece(db, usuario_owner, conta_vencendo_amanha):
    hoje = date(2026, 8, 6)
    ausencias = coletar(db, user=usuario_owner, hoje=hoje)
    kinds = [a.kind for a in ausencias]
    assert "financeiro.conta.vencendo" in kinds


def test_sub_usuario_de_crm_nao_recebe_ausencia_financeira(
    db, usuario_so_crm, conta_vencendo_amanha
):
    """A regra financeira NÃO RODA para ele — não é calculada e escondida."""
    ausencias = coletar(db, user=usuario_so_crm, hoje=date(2026, 8, 6))
    assert all(a.module != "financeiro" for a in ausencias)


def test_contato_sem_resposta_nossa_aparece(db, usuario_owner, conversa_esperando_resposta):
    """A última mensagem é `in` e passaram mais horas que o limiar."""
    ausencias = coletar(db, user=usuario_owner, hoje=date(2026, 8, 6))
    assert any(a.kind == "comercial.contato.esperando_resposta" for a in ausencias)


def test_ignora_mensagens_anteriores_a_correcao_de_autoria(
    db, usuario_owner, conversa_antiga_toda_in
):
    """As mensagens gravadas antes da correção entraram TODAS como `in` e não têm conserto
    retroativo — `fromMe` nunca foi persistido. Lê-las como direção real produziria ausência
    falsa em toda conversa antiga."""
    ausencias = coletar(db, user=usuario_owner, hoje=date(2026, 8, 6))
    assert not any(a.kind == "comercial.contato.esperando_resposta" for a in ausencias)


def test_card_parado_usa_stage_entered_at(db, usuario_owner, card_parado_ha_12_dias):
    """Mesma coluna que ordena a fila do Kanban (0068), segundo propósito, campo nenhum novo."""
    ausencias = coletar(db, user=usuario_owner, hoje=date(2026, 8, 6))
    parado = next(a for a in ausencias if a.kind == "comercial.card.parado")
    assert parado.dias == 12


def test_topo_seco_quando_nao_ha_formulario_na_janela(db, usuario_owner):
    ausencias = coletar(db, user=usuario_owner, hoje=date(2026, 8, 6))
    assert any(a.kind == "comercial.topo.sem_lead" for a in ausencias)


def test_limiares_sao_injetaveis(db, usuario_owner, card_parado_ha_12_dias):
    """O V2 (DNA da Empresa) substitui os defaults — 'você gosta de responder rápido?' É o
    limiar de 'você esqueceu de responder Carlos'."""
    ausencias = coletar(
        db, user=usuario_owner, hoje=date(2026, 8, 6),
        limiares={**LIMIARES_PADRAO, "card_parado_dias": 30},
    )
    assert not any(a.kind == "comercial.card.parado" for a in ausencias)


def test_ausencia_ja_reportada_nao_reincide(db, usuario_owner, card_parado_ha_12_dias,
                                            briefing_de_ontem_com_o_card):
    """A regra do silêncio: reportada ao CRUZAR o limiar, não enquanto permanece cruzada.

    Se o briefing repetir as mesmas pendências todo dia, em duas semanas virou papel de parede
    e o dono lê por cima — inclusive no dia em que aparece a quinta. É a Regra 7 do Epic 8 em
    outro domínio: "dentro da banda: verde e SILÊNCIO".
    """
    ausencias = coletar(db, user=usuario_owner, hoje=date(2026, 8, 6),
                        ja_reportadas=briefing_de_ontem_com_o_card)
    assert not any(a.kind == "comercial.card.parado" for a in ausencias)


def test_ausencia_reincide_quando_escala(db, usuario_owner, card_parado_ha_12_dias,
                                         briefing_de_ontem_com_o_card):
    """Escalada é notícia nova: cruzou 3 dias, agora são 12."""
    ausencias = coletar(
        db, user=usuario_owner, hoje=date(2026, 8, 6),
        ja_reportadas={**briefing_de_ontem_com_o_card, "comercial.card.parado:c1": 3},
    )
    assert any(a.kind == "comercial.card.parado" for a in ausencias)
```

`coletar` recebe `ja_reportadas: dict[str, int] | None` — chave `f"{kind}:{subject_id}"`, valor `dias` na última vez que foi reportada. Uma ausência é suprimida quando já está na chave **e** `dias` não dobrou desde então.

- [x] **Step 2: Rodar para confirmar que falha**

Run: `cd apps/api && pytest tests/test_vima_absences.py -v`
Expected: FAIL com `ModuleNotFoundError`

- [x] **Step 3: Escrever `absences.py`**

```python
# apps/api/app/modules/vima/absences.py
"""As cinco famílias de Ausência: o que NÃO aconteceu.

Ausência não vem do log — vem do **estado em aberto mais um relógio**. Isso tem uma
consequência boa: ela funciona no dia 1, sem depender de backfill nenhum. O briefing nasce
fraco em Fato e completo em Ausência.

`hoje` é PARÂMETRO OBRIGATÓRIO, nunca lido do relógio aqui dentro — mesma disciplina de
`payables.is_overdue`, que exige `today`. Um default que lê o relógio é exatamente por onde o
fuso errado volta.

Os limiares são injetáveis porque o V2 (DNA da Empresa) vai substituí-los: "você gosta de
responder rápido?" é literalmente o limiar de `contato.esperando_resposta`. Os defaults são
conservadores de propósito — pela assimetria de credibilidade, uma regra que dispara demais
custa mais caro que uma que não dispara.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tenancy import CurrentUser
from app.modules.vima.permissions import pode_ver

# A correção de autoria (`fromMe` → `direction`) entrou nesta data. Mensagens anteriores estão
# TODAS gravadas como `in` e não têm conserto retroativo. Ler direção sobre elas produziria
# ausência falsa em toda conversa antiga do sistema.
CORTE_AUTORIA = datetime(2026, 8, 5, tzinfo=UTC)

LIMIARES_PADRAO: dict[str, int] = {
    "sem_resposta_nossa_horas": 24,
    "contato_sumido_dias": 30,
    "card_parado_dias": 10,
    "topo_sem_lead_dias": 5,
    "prazo_vencendo_dias": 1,
}


@dataclass(frozen=True)
class Ausencia:
    module: str
    kind: str
    title: str
    dias: int
    subject_type: str | None = None
    subject_id: str | None = None
    client_id: str | None = None


def coletar(
    db: Session,
    *,
    user: CurrentUser,
    hoje: date,
    limiares: dict[str, int] | None = None,
) -> list[Ausencia]:
    """Roda apenas as regras dos módulos que o usuário pode ver."""
    lim = {**LIMIARES_PADRAO, **(limiares or {})}
    fora: list[Ausencia] = []

    if pode_ver(user, "agenda"):
        fora.extend(_prazos_estourados(db, hoje))
    if pode_ver(user, "financeiro"):
        fora.extend(_dinheiro_com_data(db, hoje, lim))
    if pode_ver(user, "comercial"):
        fora.extend(_silencio_nosso(db, hoje, lim))
        fora.extend(_contato_sumido(db, hoje, lim))
        fora.extend(_cards_parados(db, hoje, lim))
        fora.extend(_topo_seco(db, hoje, lim))

    return fora
```

As seis funções privadas (`_prazos_estourados`, `_dinheiro_com_data`, `_silencio_nosso`, `_contato_sumido`, `_cards_parados`, `_topo_seco`) são consultas diretas às tabelas já existentes. `_silencio_nosso` e `_contato_sumido` filtram `WhatsappMessage.created_at >= CORTE_AUTORIA`. `_cards_parados` lê `Client.stage_entered_at` e exclui etapas com `is_won` ou `is_lost`. `_topo_seco` conta `Fact` com `kind == COM_FORMULARIO_RECEBIDO` na janela.

- [x] **Step 4: Rodar para confirmar que passa**

Run: `cd apps/api && pytest tests/test_vima_absences.py -v`
Expected: PASS — 7 testes

- [x] **Step 5: Commit**

```bash
git add apps/api/app/modules/vima/absences.py apps/api/tests/test_vima_absences.py
git commit -m "feat: vima/absences — as cinco famílias, com limiares injetáveis"
```

---

### Task 11: Adaptador de Tendência

**Files:**
- Create: `apps/api/app/modules/vima/trends.py`
- Test: `apps/api/tests/test_vima_trends.py`

**Interfaces:**
- Consumes: `financial_intelligence.engine` (puro), `pode_ver` (Task 9)
- Produces: `@dataclass Tendencia(module, nivel, title)`, `coletar(db, *, user, hoje) -> list[Tendencia]`

- [x] **Step 1: Escrever o teste que falha**

```python
# apps/api/tests/test_vima_trends.py
"""Tendência é quase toda de graça: o motor financeiro já produz os sinais."""
from datetime import date

from app.modules.vima.trends import coletar


def test_le_os_sinais_do_motor_financeiro(db, usuario_owner, movimento_financeiro):
    tendencias = coletar(db, user=usuario_owner, hoje=date(2026, 8, 6))
    assert tendencias
    assert all(t.module == "financeiro" for t in tendencias)
    assert all(t.nivel in {"verde", "amarelo", "vermelho"} for t in tendencias)


def test_sub_usuario_de_crm_nao_recebe_nenhuma(db, usuario_so_crm, movimento_financeiro):
    assert coletar(db, user=usuario_so_crm, hoje=date(2026, 8, 6)) == []
```

- [x] **Step 2: Rodar para confirmar que falha**

Run: `cd apps/api && pytest tests/test_vima_trends.py -v`
Expected: FAIL com `ModuleNotFoundError`

- [x] **Step 3: Escrever `trends.py`**

```python
# apps/api/app/modules/vima/trends.py
"""Adaptador dos sinais do motor financeiro para o briefing.

`financial_intelligence/engine.py` já produz `Signal` com 🟢🟡🔴 e explicação numérica. Este
módulo **lê** os sinais; não recalcula nada.

⚠️ O `engine.py` é PURO — sem I/O, sem relógio, com gates AST provando. Este adaptador faz a
coleta de dados FORA dele e passa o resultado pronto. Empurrar I/O para dentro do motor
quebraria os gates e a garantia que eles protegem.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.core.tenancy import CurrentUser
from app.modules.financial_intelligence import diagnostics
from app.modules.financial_intelligence.engine import AMARELO, VERDE, VERMELHO
from app.modules.vima.permissions import pode_ver

_NIVEL = {VERDE: "verde", AMARELO: "amarelo", VERMELHO: "vermelho"}


@dataclass(frozen=True)
class Tendencia:
    module: str
    nivel: str
    title: str


def coletar(db: Session, *, user: CurrentUser, hoje: date) -> list[Tendencia]:
    if not pode_ver(user, "financeiro"):
        return []
    sinais = diagnostics.build_signals(db, hoje=hoje)
    return [
        Tendencia(module="financeiro", nivel=_NIVEL.get(s.level, "verde"),
                  title=f"{s.title} — {s.explanation}")
        for s in sinais
    ]
```

- [x] **Step 4: Rodar para confirmar que passa**

Run: `cd apps/api && pytest tests/test_vima_trends.py -v`
Expected: PASS — 2 testes

- [x] **Step 5: Commit**

```bash
git add apps/api/app/modules/vima/trends.py apps/api/tests/test_vima_trends.py
git commit -m "feat: vima/trends — adaptador dos sinais do motor financeiro"
```

---

### Task 12: O compositor

**Files:**
- Create: `apps/api/app/modules/vima/composer.py`
- Test: `apps/api/tests/test_vima_composer.py`

**Interfaces:**
- Consumes: `Fact` (Task 1), `Ausencia` (Task 10), `Tendencia` (Task 11)
- Produces: `@dataclass Linha(secao, module, texto)`, `@dataclass Payload(referencia, desde, linhas, excedente)`, `compor(*, fatos, ausencias, tendencias, valores, teto=12) -> Payload`

- [x] **Step 1: Escrever os testes que falham**

```python
# apps/api/tests/test_vima_composer.py
"""O compositor decide O QUE entra e em que ordem. A Claude decide apenas COMO dizer."""
from datetime import UTC, datetime

from app.core.facts import COM_FORMULARIO_RECEBIDO, CRM_LEAD_CRIADO, OP_JORNADA_INSCRITA
from app.modules.vima.composer import compor


def _fato(kind, title, module, client_id=None, quando=None, fid="f1"):
    return type("F", (), {
        "id": fid, "kind": kind, "title": title, "module": module,
        "client_id": client_id, "subject_type": None, "subject_id": None,
        "occurred_at": quando or datetime(2026, 8, 6, 3, 0, tzinfo=UTC),
    })()


def test_colapsa_formulario_e_lead_num_acontecimento_so():
    """Dois fatos, um acontecimento. Ambos ficam GRAVADOS; o colapso é da composição."""
    p = compor(
        fatos=[
            _fato(COM_FORMULARIO_RECEBIDO, "Formulário recebido da página “Consultoria”",
                  "comercial", client_id="c1", fid="f1"),
            _fato(CRM_LEAD_CRIADO, "Chegou pelo site", "crm", client_id="c1", fid="f2"),
        ],
        ausencias=[], tendencias=[], valores={},
    )
    aconteceu = [l for l in p.linhas if l.secao == "ACONTECEU"]
    assert len(aconteceu) == 1
    assert "Consultoria" in aconteceu[0].texto
    assert "funil" in aconteceu[0].texto


def test_agrega_acima_de_tres_do_mesmo_kind():
    fatos = [
        _fato(OP_JORNADA_INSCRITA, "Contato entrou na automação “Boas-vindas”",
              "operacao", fid=f"f{i}")
        for i in range(40)
    ]
    p = compor(fatos=fatos, ausencias=[], tendencias=[], valores={})
    aconteceu = [l for l in p.linhas if l.secao == "ACONTECEU"]
    assert len(aconteceu) == 1
    assert "40" in aconteceu[0].texto


def test_injeta_o_valor_lido_da_origem():
    """A Invariante 2 diz que o FATO não guarda dinheiro. O compositor injeta na composição."""
    f = _fato("financeiro.pagamento.recebido", "Pagamento de João recebido", "financeiro",
              fid="f1")
    f.subject_type, f.subject_id = "charge", "ch1"
    p = compor(fatos=[f], ausencias=[], tendencias=[],
               valores={("charge", "ch1"): "R$ 3.200,00"})
    assert "R$ 3.200,00" in p.linhas[0].texto


def test_corta_no_teto_e_declara_o_excedente():
    fatos = [_fato(f"crm.nota.criada", f"Nota {i}", "crm", fid=f"f{i}") for i in range(50)]
    p = compor(fatos=fatos, ausencias=[], tendencias=[], valores={}, teto=5)
    assert len([l for l in p.linhas if l.secao == "ACONTECEU"]) == 5
    assert p.excedente == 45


def test_ausencia_vem_antes_de_fato_na_ordem_de_prioridade():
    from app.modules.vima.absences import Ausencia

    p = compor(
        fatos=[_fato(CRM_LEAD_CRIADO, "Chegou pelo site", "crm")],
        ausencias=[Ausencia(module="comercial", kind="comercial.contato.esperando_resposta",
                            title="Carlos esperando sua resposta há 2 dias", dias=2)],
        tendencias=[], valores={},
    )
    assert p.linhas[0].secao == "PENDENTE"
```

- [x] **Step 2: Rodar para confirmar que falha**

Run: `cd apps/api && pytest tests/test_vima_composer.py -v`
Expected: FAIL com `ModuleNotFoundError`

- [x] **Step 3: Escrever `composer.py`**

```python
# apps/api/app/modules/vima/composer.py
"""Colapsa, agrega, prioriza e corta. Puro — sem banco, sem relógio, sem rede.

**O compositor decide O QUE entra e em que ordem. A Claude decide apenas COMO dizer.**

Se a LLM escolhesse o que importa, isso seria Inferência — a categoria deferida ao V4 por
assimetria de credibilidade. A priorização aqui é determinística: peso fixo por `kind` mais
recência. Chata e previsível, que é o ponto.

`valores` chega pronto de fora, mapeando `(subject_type, subject_id) → "R$ 3.200,00"`. É como
a Invariante 2 se sustenta: o fato nunca guardou o dinheiro; o valor é lido da origem
(`charges`/`bank_transactions`) e injetado aqui, no momento da leitura — mesma mecânica do
`crm/timeline.py`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.core.facts import COM_FORMULARIO_RECEBIDO, CRM_LEAD_CRIADO

# Pares que descrevem UM acontecimento. `crm.lead.criado` é consequência do formulário; juntos
# viram uma frase. Os dois fatos continuam gravados — a atribuição de marketing e o nascimento
# do contato são informações diferentes, e o V3 vai querer as duas.
_COLAPSOS: dict[tuple[str, str], str] = {
    (COM_FORMULARIO_RECEBIDO, CRM_LEAD_CRIADO): "{a} e entrou no funil",
}

# Peso maior aparece primeiro. Ausência sempre acima de fato: ela pede ação.
_PESO_PADRAO = 10
_PESOS: dict[str, int] = {
    "financeiro.pagamento.recebido": 90,
    "operacao.jornada.falhou": 85,
    COM_FORMULARIO_RECEBIDO: 80,
    "comercial.mensagem.recebida": 70,
    "comercial.orcamento.aceito": 70,
    "agenda.evento.cancelado": 60,
}

_LIMITE_AGREGACAO = 3


@dataclass(frozen=True)
class Linha:
    secao: str  # "ACONTECEU" | "PENDENTE" | "NÚMEROS"
    module: str
    texto: str


@dataclass(frozen=True)
class Payload:
    referencia: datetime | None
    desde: datetime | None
    linhas: list[Linha]
    excedente: int

    def vazio(self) -> bool:
        return not self.linhas
```

`compor()` executa, nesta ordem: (1) colapso pelos pares de `_COLAPSOS` casando `client_id` e janela de 60 segundos; (2) agregação acima de `_LIMITE_AGREGACAO` fatos do mesmo `kind`; (3) injeção de `valores` por `(subject_type, subject_id)`; (4) ordenação por seção (`PENDENTE` → `ACONTECEU` → `NÚMEROS`) e, dentro dela, por `_PESOS` e `occurred_at` decrescente; (5) corte no `teto`, com o resto contado em `excedente`.

- [x] **Step 4: Rodar para confirmar que passa**

Run: `cd apps/api && pytest tests/test_vima_composer.py -v`
Expected: PASS — 5 testes

- [x] **Step 5: Commit**

```bash
git add apps/api/app/modules/vima/composer.py apps/api/tests/test_vima_composer.py
git commit -m "feat: vima/composer — colapso, agregação, priorização e corte"
```

---

### Task 13: O narrador e o fallback

**Files:**
- Create: `apps/api/app/modules/vima/narrator.py`
- Test: `apps/api/tests/test_vima_narrator.py`

**Interfaces:**
- Consumes: `Payload` (Task 12), `app.core.ai.complete`, `app.core.anonymizer.anonymizer`, `app.core.audit.record`
- Produces: `@dataclass Narracao(texto, por_ia)`, `narrar(db, *, tenant_id, payload, nome_do_usuario) -> Narracao`, `render_template(payload, nome_do_usuario) -> str`

- [x] **Step 1: Escrever os testes que falham**

```python
# apps/api/tests/test_vima_narrator.py
"""mask → Claude → unmask, com fallback por template. Mesmo caminho do ai_narrator."""
from app.core.audit import AuditEntry
from app.modules.vima.composer import Linha, Payload
from app.modules.vima.narrator import narrar

_PAYLOAD = Payload(
    referencia=None, desde=None, excedente=0,
    linhas=[Linha(secao="ACONTECEU", module="financeiro",
                  texto="Pagamento de João recebido — R$ 3.200,00")],
)


def test_sem_chave_cai_no_template_e_nao_grava_rastro_de_ia(db, monkeypatch):
    """Seguindo o ai_narrator: quando a IA não rodou, não grava rastro de IA."""
    monkeypatch.setattr("app.config.settings.anthropic_api_key", "")
    n = narrar(db, tenant_id="t1", payload=_PAYLOAD, nome_do_usuario="Flávio")
    db.commit()
    assert n.por_ia is False
    assert "Pagamento de João recebido" in n.texto
    assert db.query(AuditEntry).filter(AuditEntry.is_ai.is_(True)).count() == 0


def test_erro_da_api_cai_no_template_com_o_mesmo_conteudo(db, monkeypatch):
    monkeypatch.setattr("app.config.settings.anthropic_api_key", "sk-fake")

    def _explode(**kwargs):
        raise RuntimeError("timeout")

    monkeypatch.setattr("app.core.ai.complete", _explode)
    n = narrar(db, tenant_id="t1", payload=_PAYLOAD, nome_do_usuario="Flávio")
    assert n.por_ia is False
    assert "Pagamento de João recebido" in n.texto


def test_narracao_bem_sucedida_grava_rastro_de_ia(db, monkeypatch):
    monkeypatch.setattr("app.config.settings.anthropic_api_key", "sk-fake")
    monkeypatch.setattr(
        "app.core.ai.complete",
        lambda **kw: type("R", (), {"text": "Bom dia. Entrou dinheiro.",
                                    "input_tokens": 10, "output_tokens": 5})(),
    )
    n = narrar(db, tenant_id="t1", payload=_PAYLOAD, nome_do_usuario="Flávio")
    db.commit()
    assert n.por_ia is True
    assert db.query(AuditEntry).filter(AuditEntry.is_ai.is_(True)).count() == 1


def test_o_telefone_vai_mascarado_e_volta_real(db, monkeypatch):
    """Regra de Ouro nº 2: nenhum texto vai ao Claude sem passar pelo anonimizador antes."""
    visto = {}
    monkeypatch.setattr("app.config.settings.anthropic_api_key", "sk-fake")

    def _captura(**kw):
        visto["mensagem"] = kw["user_message"]
        return type("R", (), {"text": kw["user_message"], "input_tokens": 1,
                              "output_tokens": 1})()

    monkeypatch.setattr("app.core.ai.complete", _captura)
    p = Payload(referencia=None, desde=None, excedente=0, linhas=[
        Linha(secao="PENDENTE", module="comercial",
              texto="Ligar para (11) 99999-8888"),
    ])
    n = narrar(db, tenant_id="t1", payload=p, nome_do_usuario="Flávio")
    assert "(11) 99999-8888" not in visto["mensagem"]
    assert "[FONE_1]" in visto["mensagem"]
    assert "(11) 99999-8888" in n.texto
```

- [x] **Step 2: Rodar para confirmar que falha**

Run: `cd apps/api && pytest tests/test_vima_narrator.py -v`
Expected: FAIL com `ModuleNotFoundError`

- [x] **Step 3: Escrever `narrator.py`**

```python
# apps/api/app/modules/vima/narrator.py
"""Narra o payload já composto. A IA entra SÓ AQUI e SÓ DEPOIS de tudo estar calculado.

Mesmo fluxo obrigatório de `financial_intelligence/ai_narrator.py`:
  1. Monta o texto-fonte a partir do `Payload`.
  2. `anonymizer.mask` — Regra de Ouro nº 2.
  3. `ai.complete`.
  4. `anonymizer.unmask` — os valores reais voltam LOCALMENTE, nunca no Claude.

Degradação graciosa: sem `ANTHROPIC_API_KEY` (ou em qualquer erro), devolve o MESMO payload
renderizado por template. O briefing continua íntegro, só deixa de ser conversado — e nesse
caso NÃO grava rastro de IA, porque não houve IA.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.config import settings
from app.core import ai, audit
from app.core.anonymizer import anonymizer
from app.modules.vima.composer import Payload

logger = logging.getLogger("e1p.vima")

_SYSTEM = (
    "Você é a Vima, assistente de um profissional autônomo brasileiro. "
    "Recebe um briefing JÁ CALCULADO por um motor determinístico, dividido em ACONTECEU, "
    "PENDENTE e NÚMEROS. Reescreva em português do Brasil, em tom direto e caloroso, "
    "como quem atualiza um sócio que acabou de acordar. No máximo 3 parágrafos curtos.\n"
    "REGRAS ABSOLUTAS: use SOMENTE os fatos, números, nomes e datas presentes no texto — "
    "NUNCA invente nada. Mantenha os marcadores entre colchetes (ex.: [FONE_1]) EXATAMENTE "
    "como estão. NUNCA sugira uma ação que não esteja no texto. NUNCA reordene por "
    "importância: a ordem recebida já é a ordem certa."
)


@dataclass(frozen=True)
class Narracao:
    texto: str
    por_ia: bool


def render_template(payload: Payload, nome_do_usuario: str) -> str:
    """O fallback. Mesmo conteúdo, sem prosa."""
    partes = [f"Bom dia, {nome_do_usuario}."]
    for secao in ("ACONTECEU", "PENDENTE", "NÚMEROS"):
        linhas = [l for l in payload.linhas if l.secao == secao]
        if not linhas:
            continue
        partes.append(f"\n{secao}")
        partes.extend(f"  • {l.texto}" for l in linhas)
    if payload.excedente:
        partes.append(f"\n… e mais {payload.excedente} coisas antes disso.")
    return "\n".join(partes)


def narrar(
    db: Session, *, tenant_id: str, payload: Payload, nome_do_usuario: str
) -> Narracao:
    fonte = render_template(payload, nome_do_usuario)
    if not settings.anthropic_api_key:
        return Narracao(texto=fonte, por_ia=False)

    seguro, mapa = anonymizer.mask(fonte)
    try:
        resposta = ai.complete(system=_SYSTEM, user_message=seguro, max_tokens=1500)
    except Exception:
        logger.exception("Narração da Vima falhou; caindo no template")
        return Narracao(texto=fonte, por_ia=False)

    texto = anonymizer.unmask(resposta.text, mapa)
    audit.record(
        db, tenant_id=tenant_id, actor="ai", action="vima.briefing.narrado",
        target="", is_ai=True,
    )
    return Narracao(texto=texto, por_ia=True)
```

- [x] **Step 4: Rodar para confirmar que passa**

Run: `cd apps/api && pytest tests/test_vima_narrator.py -v`
Expected: PASS — 4 testes

- [x] **Step 5: Commit**

```bash
git add apps/api/app/modules/vima/narrator.py apps/api/tests/test_vima_narrator.py
git commit -m "feat: vima/narrator — mask, narração e fallback por template"
```

---

### Task 14: `Briefing`, migration 0070, serviço e rota

**Files:**
- Create: `apps/api/app/modules/vima/models.py`, `apps/api/app/modules/vima/service.py`, `apps/api/app/modules/vima/schemas.py`, `apps/api/app/modules/vima/router.py`
- Create: `apps/api/migrations/versions/0070_briefings.py`
- Modify: `apps/api/app/db/registry.py`, `apps/api/app/main.py`
- Test: `apps/api/tests/test_vima_briefing.py`

**Interfaces:**
- Consumes: tudo das Tasks 9–13
- Produces: `Briefing` (modelo), `gerar_ou_ler(db, *, user, hoje) -> Briefing`, `marcar_lido(db, *, briefing_id, user) -> Briefing`, rotas `GET /vima/briefing` e `POST /vima/briefing/{id}/read`

- [x] **Step 1: Escrever os testes que falham**

```python
# apps/api/tests/test_vima_briefing.py
"""O briefing como API: idempotente por (usuário, dia) e filtrado por permissão."""
import pytest
from fastapi.testclient import TestClient

from app.modules.vima.models import Briefing


def test_gera_uma_vez_por_usuario_por_dia(client: TestClient, headers, db, monkeypatch):
    """Reabrir a tela relê o gravado; não narra de novo. Sem isso, F5 dez vezes = dez
    narrações pagas."""
    chamadas = {"n": 0}
    monkeypatch.setattr("app.config.settings.anthropic_api_key", "sk-fake")

    def _conta(**kw):
        chamadas["n"] += 1
        return type("R", (), {"text": "prosa", "input_tokens": 1, "output_tokens": 1})()

    monkeypatch.setattr("app.core.ai.complete", _conta)

    a = client.get("/vima/briefing", headers=headers).json()
    b = client.get("/vima/briefing", headers=headers).json()
    assert a["id"] == b["id"]
    assert chamadas["n"] == 1
    assert db.query(Briefing).count() == 1


def test_sub_usuario_de_crm_nao_recebe_linha_financeira(
    client: TestClient, headers_sub_crm, cobranca_paga_hoje
):
    corpo = client.get("/vima/briefing", headers=headers_sub_crm).json()
    assert all(l["module"] != "financeiro" for l in corpo["linhas"])


def test_marcar_lido(client: TestClient, headers):
    b = client.get("/vima/briefing", headers=headers).json()
    assert b["read_at"] is None
    lido = client.post(f"/vima/briefing/{b['id']}/read", headers=headers).json()
    assert lido["read_at"] is not None


def test_dia_sem_nada_devolve_briefing_vazio_e_nao_falha(client: TestClient, headers):
    corpo = client.get("/vima/briefing", headers=headers).json()
    assert corpo["vazio"] is True
    assert corpo["texto"]
```

- [x] **Step 2: Rodar para confirmar que falha**

Run: `cd apps/api && pytest tests/test_vima_briefing.py -v`
Expected: FAIL com 404 na rota

- [x] **Step 3: Escrever o modelo**

```python
# apps/api/app/modules/vima/models.py
"""O briefing gravado. Idempotente por (tenant, usuário, dia de referência)."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantMixin, TimestampMixin, _uuid


class Briefing(Base, TenantMixin, TimestampMixin):
    __tablename__ = "briefings"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "reference_date", name="uq_briefing_dia"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    reference_date: Mapped[date] = mapped_column(Date, nullable=False)
    # O payload composto, guardado como evidência do que a IA recebeu. Sem ele não dá para
    # auditar uma narração estranha.
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    texto: Mapped[str] = mapped_column(Text, nullable=False)
    por_ia: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    vazio: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

- [x] **Step 4: Escrever a migration 0070**

```python
# apps/api/migrations/versions/0070_briefings.py
"""Briefings da Vima

Revision ID: 0070
Revises: 0069
Create Date: 2026-08-06

Sem backfill — não há briefing anterior a esta migration, então a armadilha da RLS não se
aplica aqui.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0070"
down_revision: str | None = "0069"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "briefings",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("reference_date", sa.Date(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("texto", sa.Text(), nullable=False),
        sa.Column("por_ia", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("vazio", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "user_id", "reference_date", name="uq_briefing_dia"),
    )
    op.create_index("ix_briefings_user_id", "briefings", ["user_id"])

    op.execute("ALTER TABLE briefings ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE briefings FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON briefings
            USING (tenant_id = current_setting('app.current_tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true))
        """
    )


def downgrade() -> None:
    op.drop_table("briefings")
```

- [x] **Step 5: Escrever o serviço e a rota**

`vima/service.py::gerar_ou_ler(db, *, user, hoje)`:
1. `SELECT` por `(tenant_id, user_id, reference_date=hoje)` — se existir, devolve (idempotência).
2. Janela: desde o `created_at` do último briefing **lido** desse usuário, com teto de 7 dias.
3. Coleta fatos com `WHERE module = ANY(:permitidos)` quando `modulos_permitidos` não for `None`.
4. Coleta ausências (Task 10) e tendências (Task 11).
5. Monta `valores` lendo `charges`/`payables`/`bank_transactions` por `(subject_type, subject_id)` e formatando com `_brl`.
6. `compor(...)` (Task 12), `narrar(...)` (Task 13).
7. Grava `Briefing` e commita.

`vima/router.py` expõe `GET /vima/briefing` (usa `get_tenant_db` + `get_current_user`, **sem** `require_module` — o briefing é de todo usuário) e `POST /vima/briefing/{id}/read`. Registrar o router em `main.py` e importar `Briefing` em `registry.py`.

⚠️ `hoje` vem de `hoje_do_tenant(db)`, nunca de `datetime.now(UTC).date()`.

- [x] **Step 6: Rodar os testes**

Run: `cd apps/api && pytest tests/test_vima_briefing.py -v`
Expected: PASS — 4 testes

- [x] **Step 7: Estender o gate de fuso para cobrir a Vima**

Em `apps/api/tests/test_fuso_do_tenant.py`, incluir `app/modules/vima/` na varredura que reprova `datetime.now(UTC).date()` em lógica de negócio. O módulo inteiro precisa ancorar "hoje" em `hoje_do_tenant(db)`; `absences.py` e `composer.py` são puros e recebem `hoje` por parâmetro, então a varredura também prova que nenhum deles leu o relógio por conta própria.

Run: `cd apps/api && pytest tests/test_fuso_do_tenant.py -v`
Expected: PASS

- [x] **Step 8: Rodar a suíte inteira**

Run: `cd apps/api && pytest`
Expected: PASS

- [x] **Step 9: Commit**

```bash
git add apps/api/app/modules/vima/ apps/api/migrations/versions/0070_briefings.py apps/api/app/db/registry.py apps/api/app/main.py apps/api/tests/test_vima_briefing.py apps/api/tests/test_fuso_do_tenant.py
git commit -m "feat: GET /vima/briefing — composição, narração e idempotência por dia"
```

> **Fim da Onda 3.** O briefing existe como API. Dá para ler o JSON e avaliar a qualidade do conteúdo antes de investir em UX. Ponto de parada válido — e recomendado, porque é aqui que se descobre se os limiares estão calibrados.

---

# ONDA 4 — As superfícies

### Task 15: Preferências do usuário

**Files:**
- Create: `apps/api/migrations/versions/0071_user_briefing_prefs.py`
- Modify: `apps/api/app/modules/auth/models.py`, `apps/api/app/modules/auth/router.py`, `apps/api/app/modules/auth/schemas.py`
- Test: `apps/api/tests/test_vima_preferencias.py`

**Interfaces:**
- Produces: `users.briefing_whatsapp_enabled` (bool, default `False`), `users.briefing_hour` (String(5), default `"07:00"`); rotas `GET /auth/me/preferences`, `PATCH /auth/me/preferences`

- [ ] **Step 1: Escrever o teste que falha**

```python
# apps/api/tests/test_vima_preferencias.py
"""A preferência é DO USUÁRIO — não pode exigir o módulo `settings`."""
from fastapi.testclient import TestClient


def test_default_e_desligado(client: TestClient, headers):
    p = client.get("/auth/me/preferences", headers=headers).json()
    assert p["briefing_whatsapp_enabled"] is False
    assert p["briefing_hour"] == "07:00"


def test_sub_usuario_sem_settings_configura_o_proprio_briefing(
    client: TestClient, headers_sub_crm
):
    """`/config` exige o módulo `settings`. Um sub-usuário sem ele precisa poder ligar o
    próprio WhatsApp e escolher o próprio horário — configurar a própria entrega não é
    configuração de empresa."""
    r = client.patch(
        "/auth/me/preferences",
        json={"briefing_whatsapp_enabled": True, "briefing_hour": "08:30"},
        headers=headers_sub_crm,
    )
    assert r.status_code == 200
    assert r.json()["briefing_hour"] == "08:30"


def test_sem_telefone_nao_pode_ligar(client: TestClient, headers_sem_telefone):
    r = client.patch(
        "/auth/me/preferences", json={"briefing_whatsapp_enabled": True},
        headers=headers_sem_telefone,
    )
    assert r.status_code == 422
```

- [ ] **Step 2: Rodar para confirmar que falha**

Run: `cd apps/api && pytest tests/test_vima_preferencias.py -v`
Expected: FAIL com 404

- [ ] **Step 3: Migration 0071**

```python
# apps/api/migrations/versions/0071_user_briefing_prefs.py
"""Preferências de briefing por usuário

Revision ID: 0071
Revises: 0070
Create Date: 2026-08-06

⚠️ `users` é tabela GLOBAL, SEM RLS (login por e-mail é global). Não há janela de RLS a abrir
aqui — e é justamente por isso que toda consulta a `users` precisa de filtro explícito por
`tenant_id`, que é a exceção documentada da Regra de Ouro nº 1.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0071"
down_revision: str | None = "0070"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("briefing_whatsapp_enabled", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
    )
    op.add_column(
        "users",
        sa.Column("briefing_hour", sa.String(length=5), nullable=False, server_default="07:00"),
    )


def downgrade() -> None:
    op.drop_column("users", "briefing_hour")
    op.drop_column("users", "briefing_whatsapp_enabled")
```

- [ ] **Step 4: Modelo, schemas e rotas**

Em `auth/models.py`, adicionar os dois campos à classe `User`. Em `auth/schemas.py`, `PreferencesOut` e `PreferencesUpdate` (com `briefing_hour` validado por regex `^([01]\d|2[0-3]):[0-5]\d$`). Em `auth/router.py`, as duas rotas usando `get_current_user` — **sem** `require_module`.

A validação de "sem telefone não liga" vive no serviço: se `briefing_whatsapp_enabled` for `True` e `user.phone` for vazio, `HTTPException(422, "Cadastre um WhatsApp antes de ligar o briefing")`.

- [ ] **Step 5: Rodar os testes**

Run: `cd apps/api && pytest tests/test_vima_preferencias.py tests/test_auth.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add apps/api/migrations/versions/0071_user_briefing_prefs.py apps/api/app/modules/auth/ apps/api/tests/test_vima_preferencias.py
git commit -m "feat: preferências de briefing por usuário, fora do módulo settings"
```

---

### Task 16: A tela e o roteamento de entrada

**Files:**
- Create: `apps/web/src/features/vima/BriefingPage.tsx`, `apps/web/src/features/vima/PreferenciasSection.tsx`
- Create: `apps/web/src/features/vima/BriefingPage.test.tsx`
- Modify: `apps/web/src/app/routes.tsx` (ou equivalente), `packages/shared-types/src/generated.ts`

**Interfaces:**
- Consumes: `GET /vima/briefing`, `POST /vima/briefing/{id}/read`, `GET/PATCH /auth/me/preferences`
- Produces: rota `/vima`, redirecionamento condicional na entrada

- [ ] **Step 1: Escrever o teste que falha**

```tsx
// apps/web/src/features/vima/BriefingPage.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import BriefingPage from "./BriefingPage";

describe("BriefingPage", () => {
  it("mostra o texto do briefing e marca como lido", async () => {
    const marcar = vi.fn();
    vi.mock("../../lib/api", () => ({
      api: {
        get: () => Promise.resolve({ data: {
          id: "b1", texto: "Bom dia, Flávio. Entrou um pagamento.",
          vazio: false, read_at: null, linhas: [],
        }}),
        post: marcar,
      },
      apiErrorMessage: () => "",
    }));
    render(<BriefingPage />);
    await waitFor(() =>
      expect(screen.getByText(/Entrou um pagamento/)).toBeInTheDocument()
    );
    await waitFor(() => expect(marcar).toHaveBeenCalled());
  });

  it("dia sem nada não parece erro", async () => {
    vi.mock("../../lib/api", () => ({
      api: { get: () => Promise.resolve({ data: {
        id: "b2", texto: "Bom dia, Flávio. Tudo tranquilo por aqui.",
        vazio: true, read_at: null, linhas: [],
      }}), post: vi.fn() },
      apiErrorMessage: () => "",
    }));
    render(<BriefingPage />);
    await waitFor(() =>
      expect(screen.getByText(/Tudo tranquilo/)).toBeInTheDocument()
    );
  });
});
```

- [ ] **Step 2: Rodar para confirmar que falha**

Run: `pnpm --filter @e1p/web test -- BriefingPage`
Expected: FAIL — módulo não existe

- [ ] **Step 3: Escrever a tela**

`BriefingPage.tsx` renderiza em `ProtectedBareLayout` (sem sidebar/topbar — mesmo padrão de `/compartilhar` e `/comprovante/:id`), com:
- saudação e o `texto` narrado, tipografia grande e legível
- as `linhas` agrupadas por seção como apoio visual abaixo da prosa
- um botão "Ir para o painel"
- um link discreto para as preferências

**360px primeiro.** Nenhuma largura fixa; tudo em `max-w-prose` com padding responsivo. Este repositório já pagou caro por esquecer isso — o `AppShell` sem breakpoint fez uma conta ser marcada como paga sem o dono conseguir ver o checkbox (PR #56).

Datas e horas **só** por `lib/datetime.ts` com `useFuso()`. `toLocale*` cru é o bug que a correção de fuso de 2026-08-05 eliminou de ~25 telas.

`marcar_lido` é chamado uma vez, no mount, quando `read_at` vier nulo.

- [ ] **Step 4: Roteamento de entrada**

Na rota raiz autenticada: se existir briefing de hoje com `read_at == null`, redireciona para `/vima`; senão, Cockpit. O briefing é artefato **diário** — aparecer a cada login transformaria a porta de entrada em obstáculo.

- [ ] **Step 5: Preferências na própria tela**

`PreferenciasSection.tsx`: toggle do WhatsApp + seletor de horário, consumindo `GET/PATCH /auth/me/preferences`. Fica acessível a partir do briefing, sem exigir módulo nenhum.

- [ ] **Step 6: Rodar os testes**

Run: `pnpm --filter @e1p/web test -- vima`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add apps/web/src/features/vima/ apps/web/src/app/ packages/shared-types/
git commit -m "feat: tela do briefing, porta de entrada uma vez por dia"
```

---

### Task 17: O job agendado

**Files:**
- Create: `apps/api/app/modules/vima/scheduler.py`
- Modify: `apps/api/app/worker.py`
- Test: `apps/api/tests/test_vima_scheduler.py`

**Interfaces:**
- Consumes: `gerar_ou_ler` (Task 14), preferências (Task 15)
- Produces: `tick(db_factory, *, agora) -> int` (quantos briefings gerou)

- [ ] **Step 1: Escrever o teste que falha**

```python
# apps/api/tests/test_vima_scheduler.py
"""Gera no horário de cada usuário, no fuso do tenant — não em UTC cru."""
from datetime import UTC, datetime


def test_gera_apenas_para_quem_ja_chegou_no_horario(db, tenant_br, usuarios_com_horarios):
    from app.modules.vima.scheduler import tick

    # 07:05 em America/Sao_Paulo = 10:05 UTC
    gerados = tick(lambda: db, agora=datetime(2026, 8, 6, 10, 5, tzinfo=UTC))
    horarios = {u.briefing_hour for u in usuarios_com_horarios if u.gerou}
    assert "07:00" in horarios
    assert "09:00" not in horarios
    assert gerados == 1


def test_nao_gera_duas_vezes_no_mesmo_dia(db, tenant_br, usuarios_com_horarios):
    from app.modules.vima.scheduler import tick

    tick(lambda: db, agora=datetime(2026, 8, 6, 10, 5, tzinfo=UTC))
    assert tick(lambda: db, agora=datetime(2026, 8, 6, 11, 0, tzinfo=UTC)) == 0


def test_briefing_vazio_nao_enfileira_whatsapp(db, tenant_br, usuario_sem_nada):
    """Um 'bom dia, nada aconteceu' diário é a forma mais rápida de ser silenciado — e um
    canal silenciado não entrega o dia em que importa."""
    from app.modules.notifications.models import Notification
    from app.modules.vima.scheduler import tick

    tick(lambda: db, agora=datetime(2026, 8, 6, 10, 5, tzinfo=UTC))
    assert db.query(Notification).count() == 0
```

- [ ] **Step 2: Rodar para confirmar que falha**

Run: `cd apps/api && pytest tests/test_vima_scheduler.py -v`
Expected: FAIL com `ModuleNotFoundError`

- [ ] **Step 3: Escrever `scheduler.py`**

`tick(db_factory, *, agora)`:
1. Para cada tenant ativo, abre `tenant_session` e resolve o fuso com `tenant_timezone(db)`.
2. Converte `agora` para o fuso do tenant; `hoje = hoje_do_tenant(db)`.
3. Para cada usuário ativo com `briefing_hour <= hora local` e sem briefing de `hoje`: chama `gerar_ou_ler`.
4. Se `briefing_whatsapp_enabled` e **não** `briefing.vazio`, enfileira a `Notification` (Tasks 18/19).
5. Devolve a contagem.

Chamado pelo worker existente no mesmo laço periódico que já processa `notifications` e o tick de funis.

- [ ] **Step 4: Rodar os testes**

Run: `cd apps/api && pytest tests/test_vima_scheduler.py -v`
Expected: PASS — 3 testes

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/modules/vima/scheduler.py apps/api/app/worker.py apps/api/tests/test_vima_scheduler.py
git commit -m "feat: job que gera o briefing no horário de cada usuário, no fuso do tenant"
```

---

### Task 18: Entrega por Evolution — o briefing inteiro

**Files:**
- Modify: `apps/api/app/core/whatsapp/capabilities.py`
- Modify: `apps/api/app/modules/vima/scheduler.py`
- Test: `apps/api/tests/test_vima_whatsapp_evolution.py`

**Interfaces:**
- Produces: `Capabilities.briefing_needs_optin: bool`

- [ ] **Step 1: Escrever os testes que falham**

```python
# apps/api/tests/test_vima_whatsapp_evolution.py
"""Tenant Evolution recebe o briefing inteiro, em um passo."""
from app.core.whatsapp.capabilities import for_profile
from app.modules.notifications.models import Notification


def test_evolution_nao_precisa_de_optin():
    assert for_profile("evolution").briefing_needs_optin is False


def test_meta_precisa_de_optin():
    """Parâmetro de template da Cloud API não aceita quebra de linha, e às 7h o dono está
    sempre fora da janela de 24h."""
    assert for_profile("meta").briefing_needs_optin is True


def test_enfileira_o_texto_inteiro_em_tenant_evolution(db, tenant_evolution, usuario_com_optin):
    from datetime import UTC, datetime

    from app.modules.vima.scheduler import tick

    tick(lambda: db, agora=datetime(2026, 8, 6, 10, 5, tzinfo=UTC))
    n = db.query(Notification).one()
    assert n.channel == "whatsapp"
    assert len(n.message) > 100  # o briefing, não um aviso
```

- [ ] **Step 2: Rodar para confirmar que falha**

Run: `cd apps/api && pytest tests/test_vima_whatsapp_evolution.py -v`
Expected: FAIL com `AttributeError: 'Capabilities' object has no attribute 'briefing_needs_optin'`

- [ ] **Step 3: Adicionar a capacidade — com o consumidor no mesmo passo**

Em `apps/api/app/core/whatsapp/capabilities.py`, adicionar o campo ao dataclass e aos dois perfis:

```python
    # Meta: parâmetro de template não aceita quebra de linha, e às 7h o dono está fora da
    # janela de 24h — então o briefing completo só sai depois que ELE escrever. Evolution não
    # tem janela nem template: sai direto.
    #
    # Consumidores (verificável por grep — `capabilities` já passou meses com zero call sites
    # enquanto a docstring afirmava ter três):
    #   - app/modules/vima/scheduler.py::_entregar_no_whatsapp
    briefing_needs_optin: bool
```

`EVOLUTION` recebe `briefing_needs_optin=False`; `META`, `True`.

- [ ] **Step 4: Escrever o consumidor**

Em `scheduler.py`, a função `_entregar_no_whatsapp(db, *, user, briefing, capabilities)`: quando `briefing_needs_optin` for `False`, enfileira uma `Notification` de canal `whatsapp` com `message=briefing.texto` e `recipient=user.phone`.

- [ ] **Step 5: Rodar os testes**

Run: `cd apps/api && pytest tests/test_vima_whatsapp_evolution.py tests/test_whatsapp_capabilities.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/core/whatsapp/capabilities.py apps/api/app/modules/vima/scheduler.py apps/api/tests/test_vima_whatsapp_evolution.py
git commit -m "feat: briefing por WhatsApp em tenant Evolution, com capacidade e consumidor juntos"
```

---

### Task 19: Entrega por Meta — template com botão e o opt-in de volta

**Files:**
- Modify: `apps/api/app/modules/vima/scheduler.py`
- Modify: `apps/api/app/modules/whatsapp_inbox/service.py`
- Test: `apps/api/tests/test_vima_whatsapp_meta.py`

**Interfaces:**
- Consumes: a guarda `_e_telefone_de_usuario` (Task 7), `briefing_needs_optin` (Task 18)
- Produces: `PAYLOAD_BOTAO_BRIEFING = "vima_briefing"`; `responder_optin(db, *, tenant_id, phone_key) -> bool`

- [ ] **Step 1: Escrever os testes que falham**

```python
# apps/api/tests/test_vima_whatsapp_meta.py
"""Meta em dois tempos: template com botão → ele toca → a janela abre → sai o texto inteiro."""
from datetime import UTC, datetime

from app.modules.notifications.models import Notification
from app.modules.vima.scheduler import tick
from app.modules.whatsapp_inbox.service import PAYLOAD_BOTAO_BRIEFING, ingest_webhook_payload


def test_primeiro_passo_e_o_template_curto(db, tenant_meta, usuario_com_optin):
    tick(lambda: db, agora=datetime(2026, 8, 6, 10, 5, tzinfo=UTC))
    n = db.query(Notification).one()
    assert n.purpose == "vima_briefing_aviso"
    assert len(n.message) < 200  # é o aviso, não o briefing


def test_toque_no_botao_libera_o_briefing_inteiro(db, tenant_meta, usuario_com_optin):
    tick(lambda: db, agora=datetime(2026, 8, 6, 10, 5, tzinfo=UTC))
    ingest_webhook_payload(db, tenant_id=tenant_meta.id, payload={
        "event": "messages.upsert",
        "data": {
            "key": {"remoteJid": f"{usuario_com_optin.phone}@s.whatsapp.net",
                    "id": "BTN1", "fromMe": False},
            "message": {"buttonsResponseMessage": {"selectedButtonId": PAYLOAD_BOTAO_BRIEFING}},
            "messageTimestamp": 1754470000,
        },
    })
    db.commit()

    completos = db.query(Notification).filter(
        Notification.purpose == "vima_briefing_texto"
    ).all()
    assert len(completos) == 1
    assert len(completos[0].message) > 100


def test_o_toque_nao_cria_contato_no_crm(db, tenant_meta, usuario_com_optin):
    """A guarda da Task 7 vale aqui: a resposta vem do telefone do PRÓPRIO dono."""
    from app.modules.crm.models import Client

    antes = db.query(Client).count()
    tick(lambda: db, agora=datetime(2026, 8, 6, 10, 5, tzinfo=UTC))
    ingest_webhook_payload(db, tenant_id=tenant_meta.id, payload={
        "event": "messages.upsert",
        "data": {
            "key": {"remoteJid": f"{usuario_com_optin.phone}@s.whatsapp.net",
                    "id": "BTN2", "fromMe": False},
            "message": {"buttonsResponseMessage": {"selectedButtonId": PAYLOAD_BOTAO_BRIEFING}},
            "messageTimestamp": 1754470000,
        },
    })
    db.commit()
    assert db.query(Client).count() == antes
```

- [ ] **Step 2: Rodar para confirmar que falha**

Run: `cd apps/api && pytest tests/test_vima_whatsapp_meta.py -v`
Expected: FAIL com `ImportError: cannot import name 'PAYLOAD_BOTAO_BRIEFING'`

- [ ] **Step 3: O primeiro passo — o aviso**

Em `_entregar_no_whatsapp`, quando `briefing_needs_optin` for `True`, enfileirar `Notification` com `purpose="vima_briefing_aviso"` e uma mensagem curta e de uma linha, referenciando o template aprovado com botão de resposta rápida.

⚠️ **Dependência externa, fora do repositório:** o template precisa de aprovação da Meta. Enquanto não houver, a entrega falha. A UI de preferências diz isso em vez de deixar o botão quebrado.

- [ ] **Step 4: O segundo passo — reconhecer o toque**

Em `whatsapp_inbox/service.py`, **antes** da guarda `_e_telefone_de_usuario` (que retorna cedo):

```python
PAYLOAD_BOTAO_BRIEFING = "vima_briefing"


def _payload_do_botao(mensagem: dict) -> str | None:
    resposta = mensagem.get("buttonsResponseMessage") or {}
    return resposta.get("selectedButtonId")
```

E no fluxo de `ingest_webhook_payload`:

```python
    if _payload_do_botao(conteudo) == PAYLOAD_BOTAO_BRIEFING and _e_telefone_de_usuario(
        db, tenant_id, phone_key
    ):
        # A janela de 24h acabou de abrir. Enfileira o briefing inteiro como texto livre.
        vima_scheduler.responder_optin(db, tenant_id=tenant_id, phone_key=phone_key)
        return None
```

A ordem importa: o teste do botão vem **antes** do `return None` da guarda, senão o toque seria descartado junto com as demais mensagens do time.

- [ ] **Step 5: Rodar os testes**

Run: `cd apps/api && pytest tests/test_vima_whatsapp_meta.py tests/test_facts_whatsapp.py -v`
Expected: PASS

- [ ] **Step 6: Rodar a suíte inteira**

Run: `cd apps/api && pytest && pnpm --filter @e1p/web test`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add apps/api/app/modules/vima/scheduler.py apps/api/app/modules/whatsapp_inbox/service.py apps/api/tests/test_vima_whatsapp_meta.py
git commit -m "feat: briefing por WhatsApp em tenant Meta, com opt-in por botão"
```

> **Fim da Onda 4.** O dono vê na tela e recebe no WhatsApp nos dois transportes. **Validação manual em ~360px pendente** — bloqueia release, não bloqueia merge.

---

# ONDA 5 — `/config` separado (independente)

### Task 20: Separar a tela de configurações em áreas

**Files:**
- Modify: `apps/web/src/features/config/ConfiguracoesPage.tsx`
- Create: `apps/web/src/features/config/EmpresaTab.tsx`, `CanaisTab.tsx`, `IntegracoesTab.tsx`, `VendasTab.tsx`
- Test: `apps/web/src/features/config/ConfiguracoesPage.test.tsx` (existente — precisa continuar verde)

**Interfaces:**
- Consumes: os componentes existentes `WhatsappSection`, `CelularSection`, `IntegrationsSection`
- Produces: nenhuma mudança de contrato de API

- [ ] **Step 1: Escrever o teste que falha**

```tsx
// adicionar em apps/web/src/features/config/ConfiguracoesPage.test.tsx
it("separa os assuntos em abas em vez de empilhar tudo numa coluna", async () => {
  render(<ConfiguracoesPage />);
  expect(screen.getByRole("tab", { name: /empresa/i })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: /canais/i })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: /integrações/i })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: /vendas/i })).toBeInTheDocument();

  // A aba Empresa começa ativa; o WhatsApp (aba Canais) não está montado.
  expect(screen.queryByText(/conectar por QR/i)).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Rodar para confirmar que falha**

Run: `pnpm --filter @e1p/web test -- ConfiguracoesPage`
Expected: FAIL — nenhum `role="tab"` na tela

- [ ] **Step 3: Extrair as quatro abas**

- `EmpresaTab.tsx` — "Perfil da empresa" + "Brand Kit" + "Prévia" (hoje inline em `ConfiguracoesPage.tsx:126-201`)
- `CanaisTab.tsx` — `<WhatsappSection />` + `<CelularSection />`
- `IntegracoesTab.tsx` — `<IntegrationsSection />` + `<GoogleSection />` (hoje inline em `:252-305`)
- `VendasTab.tsx` — "Funil de entrada padrão" (hoje inline em `:228`)

`ConfiguracoesPage.tsx` fica só com o cabeçalho, o estado do perfil e o seletor de abas.

**Escopo apertado: reorganizar e separar, não redesenhar.** Nenhum campo novo, nenhuma regra nova, nenhuma mudança de comportamento. O diff precisa ser revisável.

- [ ] **Step 4: Rodar os testes**

Run: `pnpm --filter @e1p/web test -- config`
Expected: PASS — incluindo `WhatsappSection.test.tsx` (454 linhas) sem alteração

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/features/config/
git commit -m "refactor: /config separado em abas — Empresa, Canais, Integrações, Vendas"
```

---

## Auto-revisão

**Cobertura da spec.** Cada seção mapeada: modelo `Fact` e as 5 invariantes → Task 1; migration e absorção de `client_events` → Task 2; `record()` → Task 1; oito emissores → Tasks 3, 5–8; sem backfill → Task 2 (`origin='emitted'`, sem etapa de reconstrução); LGPD por expurgo → Task 1 (FK `CASCADE` em `client_id`) — ⚠️ *a rotina de expurgo dos sujeitos polimórficos não tem tarefa própria neste plano*, ver Lacunas; briefing por usuário → Task 14; filtro antes da narração → Tasks 9 e 14; três categorias → Tasks 10, 11, 14; regra do silêncio → Task 10 (limiares) — ⚠️ *a supressão de reincidência não tem teste próprio*, ver Lacunas; compositor → Task 12; payload e narração → Task 13; fallback → Task 13; idempotência → Task 14; batch fora → nenhuma tarefa (correto); tela → Task 16; preferências → Tasks 15 e 16; WhatsApp dois caminhos → Tasks 18 e 19; guarda do dono → Tasks 7 e 19; `/config` → Task 20; os 5 gates → Tasks 1 (Invariante 2), 9+14 (permissão), 13 (fallback), 14 (idempotência) — ⚠️ *o gate de fuso não tem teste dedicado*, ver Lacunas.

**Lacuna assumida, uma só** (declarada em vez de escondida):

**Expurgo dos sujeitos polimórficos** (LGPD, spec §"LGPD: expurgo explícito por sujeito") não tem tarefa própria. Só o `client_id` cascateia; os demais sujeitos (`charge`, `payable`, `agenda_event`, `quote`, `page`, `funnel_run`, `whatsapp_chat`) deixariam fato órfão se a entidade fosse apagada de verdade. **A ser verificado durante a Onda 2:** quantos desses módulos fazem `DELETE` real hoje, em vez de troca de status. Se algum fizer, a rotina de expurgo vira tarefa da Onda 2; se nenhum fizer, vira dívida registrada com o gatilho explícito ("quando o primeiro `DELETE` real aparecer").

*(As lacunas de regra do silêncio e de gate de fuso, achadas nesta mesma revisão, foram fechadas — Task 10 Step 1 e Task 14 Step 7.)*

**Consistência de tipos.** `facts.record` tem a mesma assinatura em todas as chamadas (Tasks 1, 3, 5–8). `Ausencia` (Task 10) e `Tendencia` (Task 11) são consumidas por `compor` (Task 12) com os campos que declaram. `Payload`/`Linha` (Task 12) são consumidos por `narrar` (Task 13) e por `render_template`. `briefing_needs_optin` é declarado na Task 18 e consumido nas Tasks 18 e 19.

**Placeholders:** nenhum "TBD"/"TODO"/"similar à Task N". As três funções descritas em prosa (as seis privadas de `absences.py`, o corpo de `compor()`, o corpo de `gerar_ou_ler`) têm assinatura, contrato e ordem de operações explícitos, mais os testes que as definem por comportamento.
