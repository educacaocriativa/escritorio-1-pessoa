# Webhook de status de template (Meta) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Quando a Meta aprova ou rejeita um template, o status no e1p muda sozinho — sem ninguém clicar em "Sincronizar".

**Architecture:** O endpoint público `POST /public/whatsapp/webhook` já existe, já faz handshake, já valida `X-Hub-Signature-256` e já resolve o tenant sem autenticação. Ele só sabe ler UM tipo de evento: mensagem recebida, roteada pelo `metadata.phone_number_id`. Evento de status de template **não tem** `phone_number_id` — ele identifica a conta pelo **WABA ID** em `entry[].id`. Então esta onda abre um SEGUNDO caminho de roteamento no mesmo endpoint: `public_whatsapp_accounts` ganha a coluna `waba_id` (dual-write + backfill), o provider Meta ganha um parser de `message_template_status_update`, e `whatsapp_templates/service.py` ganha a função que aplica o status dentro da sessão do tenant certo.

**Tech Stack:** FastAPI · SQLAlchemy 2 (Mapped/mapped_column) · Alembic · Postgres com `FORCE ROW LEVEL SECURITY` · pytest (SQLite em memória + testcontainers para RLS real) · React/Vitest no front.

**Spec:** issue [#36](https://github.com/flavio-kato/escritorio-1-pessoa/issues/36), **item 5** ("Atualizar `status`/`category_approved`/`rejected_reason` a partir do payload do evento"). Contexto original do webhook: [docs/superpowers/specs/2026-07-19-whatsapp-inbox-design.md](../specs/2026-07-19-whatsapp-inbox-design.md).

---

## O que esta onda paga (e o que ela NÃO paga)

A issue #36 tem 6 itens. Auditoria de 17/08/2026 contra `main` (e343898):

| # | Item | Estado |
|---|---|---|
| 1 | Endpoint público | ✅ já existe — `apps/api/app/modules/whatsapp_inbox/router.py:28,66` |
| 2 | Handshake `hub.challenge` | ✅ já existe — `router.py:29-42` |
| 3 | Assinatura `X-Hub-Signature-256` | ✅ já existe — `providers/meta.py:213-222` |
| 4 | Roteamento multi-tenant sem auth | ✅ já existe — `public_whatsapp_accounts` |
| 5 | **Tratar `message_template_status_update`** | ❌ **é o que este plano faz** |
| 6 | Manter "Sincronizar" manual | ✅ fica como está, é o fallback |

**Correção de 17/08 (conferência na fonte, Task 3 Step 1):** a primeira versão deste plano dizia que o evento não carrega categoria. **Carrega** — o campo é `message_template_category`, e está no exemplo oficial. Então `category_approved` **é** atualizado, e os 3 campos que a issue pede ficam cobertos. Duas cautelas que ficam no código: o campo só é escrito quando vem presente (evento sem categoria não apaga o que o "Sincronizar" trouxe), e a lista de `event` da Meta tem **14 valores** (`ARCHIVED`, `FLAGGED`, `LOCKED`, `IN_APPEAL`, `LIMIT_EXCEEDED`, `REINSTATED`, ...) contra os 5 que este produto sabe representar — o que torna o filtro de status mais necessário, não menos.

**Fora de escopo, deliberadamente:**

- **Status que a tela não sabe mostrar são ignorados.** `STATUS_LABEL` em `WhatsappSection.tsx` é um `Record` FECHADO de 5 chaves; gravar `FLAGGED` renderiza rótulo vazio. Ignorar mantém o último status válido, e o "Sincronizar" (item 6) segue disponível.
- **`disable_info` / `other_info` / `rejection_info`** (objetos condicionais do payload) não são lidos — `reason` já dá o motivo em texto, que é o que a tela mostra.
- **Eventos de status de ENTREGA de mensagem** (`statuses`) continuam ignorados, como hoje.

**Fonte conferida:** [message_template_status_update](https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/message_template_status_update) — WABA em `entry[].id`, `message_template_id` **inteiro** (por isso o `str()` no parser), `reason: "NONE"` quando não há motivo.

## Global Constraints

- **Regra de Ouro nº 1 (RLS):** dentro de uma sessão de tenant, NUNCA filtrar por `tenant_id` na query — a RLS isola. Ver `whatsapp_templates/service.py:110`.
- **A ARMADILHA do backfill:** migration roda como `e1p_app` (não-superusuário) **sem** a GUC `app.current_tenant_id`. Sob `FORCE ROW LEVEL SECURITY`, um `SELECT`/`UPDATE` que toque `tenant_profiles` é filtrado a **ZERO LINHAS, EM SILÊNCIO**. Toda migration que lê tabela com RLS precisa da janela DISABLE/ENABLE+FORCE. Precedentes: 0046, 0066, 0067, 0068, 0078.
- **`public_whatsapp_accounts` NÃO tem RLS** (tabela global, criada em `0054_whatsapp_inbox.py:100-108` sem `ENABLE ROW LEVEL SECURITY`) — só a FONTE do backfill (`tenant_profiles`) precisa da janela.
- **Head do Alembic hoje é `0078`.** A nova revision é `0079`. Se ao executar este plano `main` já tiver avançado, **reconfira o head** antes de escrever o arquivo (histórico do projeto: colisão de número entre frentes paralelas).
- **Migration não importa de `app.`** — convenção do repo (0 de 78 fazem isso).
- Código e comentários em **português**; comentário explica o PORQUÊ, não o quê.
- Lint: `ruff check .` dentro de `apps/api`; `eslint . --max-warnings 0` em `apps/web`.
- Nenhuma mudança de schema de API → **não** é preciso rodar `pnpm generate:types`.

## File Structure

| Arquivo | Responsabilidade nesta onda |
|---|---|
| `apps/api/migrations/versions/0079_public_whatsapp_account_waba_id.py` | **Criar.** Coluna `waba_id` + índice + backfill sob janela de RLS. |
| `apps/api/app/modules/whatsapp_inbox/models.py` | **Modificar.** `PublicWhatsappAccount.waba_id`. |
| `apps/api/app/modules/whatsapp_inbox/service.py` | **Modificar.** `resolve_by_waba_id`. |
| `apps/api/app/modules/settings/service.py` | **Modificar.** Dual-write do `waba_id` no snapshot. |
| `apps/api/app/core/whatsapp/providers/meta.py` | **Modificar.** `TemplateStatusEvent`, `extract_waba_id`, `parse_template_status` — só forma, zero domínio. |
| `apps/api/app/modules/whatsapp_templates/service.py` | **Modificar.** `apply_status_events` — o domínio (o que é status conhecido, o que gravar). |
| `apps/api/app/modules/whatsapp_inbox/router.py` | **Modificar.** O ramo de template no `POST /webhook` + extração do helper de assinatura. |
| `apps/web/src/features/config/WhatsappSection.tsx` | **Modificar.** A instrução que faz o webhook de fato disparar (assinar o campo no painel da Meta). |

Testes novos: `apps/api/tests/test_migration_0079_waba_id.py`, `apps/api/tests/test_whatsapp_template_status_webhook.py`, `apps/api/tests/test_whatsapp_template_status_rls.py`. Testes ampliados: `test_whatsapp_inbox_service.py` (ou o de settings), `test_whatsapp_templates.py`, `apps/web/src/features/config/WhatsappSection.test.tsx`.

---

### Task 1: A coluna `waba_id` no snapshot global (+ migration com backfill)

**Files:**
- Create: `apps/api/migrations/versions/0079_public_whatsapp_account_waba_id.py`
- Modify: `apps/api/app/modules/whatsapp_inbox/models.py:144-162`
- Test: `apps/api/tests/test_migration_0079_waba_id.py`

**Interfaces:**
- Produces: `PublicWhatsappAccount.waba_id: Mapped[str | None]` (String(64), nullable, indexado). Nullable de propósito: linhas antigas existem antes do backfill, e `nullable=False` sem default derrubaria o deploy.

- [ ] **Step 1: Confirmar que o head ainda é 0078**

Run:
```bash
cd apps/api && ls migrations/versions | sort | tail -3
```
Esperado: `0078_agenda_event_client.py` é o último. Se não for, use o próximo número livre e ajuste `down_revision` — e ajuste também as asserções do teste do Step 6.

- [ ] **Step 2: Escrever o teste que falha**

Create `apps/api/tests/test_migration_0079_waba_id.py`:

```python
"""A 0079 encadeia na 0078 e o backfill do `waba_id` abre a janela de RLS na FONTE.

O `UPDATE` lê `tenant_profiles`, que tem `FORCE ROW LEVEL SECURITY` desde a 0022. A migration
roda como `e1p_app` SEM a GUC `app.current_tenant_id`: sem a janela, o backfill seria filtrado
a ZERO LINHAS, em silêncio — e o sintoma em produção não seria erro de deploy, seria "a Meta
aprovou o template e o e1p continua dizendo Pendente". Este teste lê o TEXTO da migration
porque a asserção é sobre o que o arquivo faz rodar, não sobre um efeito observável em SQLite
(que não tem RLS). O efeito real é exercido em `test_whatsapp_template_status_rls.py`.
"""
import importlib.util
from pathlib import Path

import pytest

_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations" / "versions" / "0079_public_whatsapp_account_waba_id.py"
)


@pytest.fixture(scope="module")
def migration_module():
    spec = importlib.util.spec_from_file_location("migracao_0079", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revisao_encadeia_na_0078(migration_module):
    assert migration_module.revision == "0079"
    assert migration_module.down_revision == "0078"


def test_backfill_abre_e_fecha_a_janela_de_rls_na_fonte():
    texto = _MIGRATION.read_text(encoding="utf-8")
    assert "ALTER TABLE tenant_profiles DISABLE ROW LEVEL SECURITY" in texto
    assert "ALTER TABLE tenant_profiles ENABLE ROW LEVEL SECURITY" in texto
    # ENABLE sozinho não basta: sem FORCE, o dono da tabela volta a escapar da policy.
    assert "ALTER TABLE tenant_profiles FORCE ROW LEVEL SECURITY" in texto


def test_backfill_e_reentrante():
    """`a.waba_id IS NULL` — rodar a SQL de novo à mão contra produção (coisa que já aconteceu
    na história deste projeto) não pode sobrescrever o que o dual-write já corrigiu depois."""
    texto = _MIGRATION.read_text(encoding="utf-8")
    assert "a.waba_id IS NULL" in texto
```

- [ ] **Step 3: Rodar o teste para ver falhar**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_migration_0079_waba_id.py -v`
Expected: FAIL — `FileNotFoundError` / `spec_from_file_location` retorna `None` (a migration não existe).

- [ ] **Step 4: Escrever a migration**

Create `apps/api/migrations/versions/0079_public_whatsapp_account_waba_id.py`:

```python
"""Roteamento do webhook por WABA: public_whatsapp_accounts.waba_id

Revision ID: 0079
Revises: 0078
Create Date: 2026-08-17

O webhook público da Meta resolve o tenant pelo `phone_number_id` que vem em
`value.metadata` — é o que o evento de MENSAGEM carrega. O evento de aprovação de template
(`message_template_status_update`) NÃO carrega telefone nenhum: ele identifica a conta pelo
WABA ID, em `entry[].id`. Sem esta coluna, o evento chega e morre em 404.

Nullable de propósito: as linhas já existentes precedem a coluna, e `NOT NULL` sem default
derrubaria o deploy. O dual-write de `settings/service.py::_sync_whatsapp_webhook_snapshot`
sempre preenche daqui pra frente (o snapshot só é criado quando as 4 credenciais existem, e
`whatsapp_waba_id` é uma delas), e o backfill abaixo cobre quem já estava configurado.

⚠️ ARMADILHA QUE **SE APLICA** AQUI: esta migration FAZ BACKFILL lendo `tenant_profiles`, que
tem `FORCE ROW LEVEL SECURITY` desde a 0022. Ela roda como o papel dono não-superusuário
`e1p_app`, **sem** a GUC `app.current_tenant_id` — a RLS filtra SELECT também, então o
`UPDATE ... FROM tenant_profiles` seria filtrado a **ZERO LINHAS, EM SILÊNCIO**. Em produção o
sintoma não seria erro de deploy: seria todo tenant já configurado continuar sem receber o
evento de aprovação, e ninguém descobre até alguém reclamar que o template "ficou pendente
pra sempre". Por isso a RLS é desabilitada em `tenant_profiles` (a FONTE) na janela do
backfill e restaurada com ENABLE + FORCE logo depois. Mesmo padrão da 0046, 0066, 0067, 0068
e 0078.

O ALVO (`public_whatsapp_accounts`) NÃO precisa de janela: é tabela GLOBAL, criada na 0054 sem
`ENABLE ROW LEVEL SECURITY` — é justamente por não ter RLS que ela serve pra resolver tenant
antes de qualquer autenticação.

DDL é transacional no Postgres e a migration roda offline, então não há janela de exposição.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0079"
down_revision: str | None = "0078"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def backfill_waba_id() -> None:
    """A janela de RLS na FONTE + o UPDATE reentrante (ver ARMADILHA no docstring do módulo).

    Extraído como função própria (em vez de inline em `upgrade()`) seguindo o precedente da
    0078: o teste de RLS reexecuta exatamente este código — o mesmo que rodaria numa
    reexecução manual contra produção — sem duplicar a SQL numa cópia que poderia divergir.
    """
    op.execute("ALTER TABLE tenant_profiles DISABLE ROW LEVEL SECURITY")

    op.execute(
        """
        UPDATE public_whatsapp_accounts AS a
           SET waba_id = p.whatsapp_waba_id
          FROM tenant_profiles AS p
         WHERE p.tenant_id = a.tenant_id
           AND p.whatsapp_waba_id IS NOT NULL
           AND a.waba_id IS NULL
        """
    )

    op.execute("ALTER TABLE tenant_profiles ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenant_profiles FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    op.add_column(
        "public_whatsapp_accounts", sa.Column("waba_id", sa.String(64), nullable=True)
    )
    op.create_index(
        "ix_public_whatsapp_accounts_waba_id", "public_whatsapp_accounts", ["waba_id"]
    )

    # --- backfill (ver a ARMADILHA no docstring: sem esta janela, tudo aqui é no-op) ---
    backfill_waba_id()


def downgrade() -> None:
    op.drop_index(
        "ix_public_whatsapp_accounts_waba_id", table_name="public_whatsapp_accounts"
    )
    op.drop_column("public_whatsapp_accounts", "waba_id")
```

- [ ] **Step 5: Adicionar a coluna ao model**

Modify `apps/api/app/modules/whatsapp_inbox/models.py` — dentro de `class PublicWhatsappAccount`, logo após `verify_token`:

```python
    # O WABA ID (WhatsApp Business Account) do tenant. Redundante com
    # `TenantProfile.whatsapp_waba_id` de propósito, pelo MESMO motivo de `app_secret` estar
    # aqui: o evento de aprovação de template chega numa requisição SEM tenant e traz só o
    # WABA em `entry[].id` — `tenant_profiles` tem RLS e é ilegível nesse ponto.
    #
    # NÃO é único: um WABA pode ter vários números, e cada número é uma linha desta tabela.
    # Todas as linhas do mesmo WABA pertencem ao MESMO tenant (o dual-write escreve os dois
    # campos do mesmo perfil), então qualquer uma serve para resolver tenant/app_secret.
    waba_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
```

- [ ] **Step 6: Rodar o teste para ver passar**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_migration_0079_waba_id.py -v`
Expected: PASS (4 testes).

- [ ] **Step 7: Rodar a suíte SQLite inteira (a coluna nova entra no `create_all` dos testes)**

Run: `cd apps/api && .venv/Scripts/python -m pytest -q -m 'not rls_e2e'`
Expected: PASS, sem regressão.

- [ ] **Step 8: Commit**

```bash
git add apps/api/migrations/versions/0079_public_whatsapp_account_waba_id.py \
        apps/api/app/modules/whatsapp_inbox/models.py \
        apps/api/tests/test_migration_0079_waba_id.py
git commit -m "feat: public_whatsapp_accounts sabe de qual WABA é a conta [#36]"
```

---

### Task 2: Dual-write e lookup por WABA

**Files:**
- Modify: `apps/api/app/modules/settings/service.py:142-176` (`_sync_whatsapp_webhook_snapshot`)
- Modify: `apps/api/app/modules/whatsapp_inbox/service.py:100-116`
- Test: `apps/api/tests/test_whatsapp_inbox_service.py` (acrescentar ao arquivo existente)

**Interfaces:**
- Consumes: `PublicWhatsappAccount.waba_id` (Task 1).
- Produces: `whatsapp_inbox.service.resolve_by_waba_id(db: Session, *, waba_id: str) -> PublicWhatsappAccount | None` — usado pelo router na Task 5.

- [ ] **Step 1: Escrever os testes que falham**

Append em `apps/api/tests/test_whatsapp_inbox_service.py`:

```python
def test_snapshot_grava_o_waba_id_do_perfil(db):
    """Sem isto, todo tenant que salvar credenciais DEPOIS da 0079 ficaria fora do
    roteamento por WABA — o backfill cobre só quem já existia."""
    from app.modules.settings import service as settings_service
    from app.modules.settings.schemas import ProfileUpdate
    from app.modules.whatsapp_inbox.models import PublicWhatsappAccount

    settings_service.update_profile(
        db,
        tenant_id="t-waba",
        actor="dono@e1p.com",
        data=ProfileUpdate(
            whatsapp_token="tok-1",
            whatsapp_phone_id="phone-1",
            whatsapp_waba_id="waba-1",
            whatsapp_app_secret="segredo-1",
        ),
    )

    snap = db.get(PublicWhatsappAccount, "phone-1")
    assert snap is not None
    assert snap.waba_id == "waba-1"


def test_resolve_by_waba_id_encontra_a_conta(db):
    from app.modules.whatsapp_inbox import service
    from app.modules.whatsapp_inbox.models import PublicWhatsappAccount

    db.add(PublicWhatsappAccount(
        phone_number_id="phone-9", tenant_id="t-9", app_secret="shh",
        verify_token="verify-9", waba_id="waba-9",
    ))
    db.commit()

    conta = service.resolve_by_waba_id(db, waba_id="waba-9")
    assert conta is not None
    assert conta.tenant_id == "t-9"


def test_resolve_by_waba_id_devolve_none_para_waba_desconhecida(db):
    from app.modules.whatsapp_inbox import service

    assert service.resolve_by_waba_id(db, waba_id="waba-que-nao-existe") is None


def test_resolve_by_waba_id_ignora_identificador_com_nul(db):
    """Mesma guarda de `resolve_account`: o WABA vem de payload público e um NUL quebraria o
    bind do parâmetro no psycopg (inofensivo em SQLite, explode em produção)."""
    from app.modules.whatsapp_inbox import service

    assert service.resolve_by_waba_id(db, waba_id="waba\x00-1") is None
```

Antes de rodar, confira a assinatura real de `ProfileUpdate` (`apps/api/app/modules/settings/schemas.py`) e o nome do fixture de tenant usado no arquivo — se o teste existente já cria perfil por outro caminho, siga o caminho dele em vez de inventar um.

- [ ] **Step 2: Rodar para ver falhar**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_whatsapp_inbox_service.py -k "waba" -v`
Expected: FAIL — `AttributeError: module 'app.modules.whatsapp_inbox.service' has no attribute 'resolve_by_waba_id'` e, no primeiro teste, `assert None == "waba-1"`.

- [ ] **Step 3: Dual-write**

Modify `apps/api/app/modules/settings/service.py`, na construção do snapshot dentro de `_sync_whatsapp_webhook_snapshot`:

```python
    db.add(
        PublicWhatsappAccount(
            phone_number_id=profile.whatsapp_phone_id,
            tenant_id=profile.tenant_id,
            app_secret=profile.whatsapp_app_secret,
            verify_token=profile.whatsapp_verify_token,
            # O evento de aprovação de template chega roteado por WABA, não por telefone —
            # ver o docstring da 0079. `fully_configured` acima já garante que não é None.
            waba_id=profile.whatsapp_waba_id,
        )
    )
```

- [ ] **Step 4: Lookup por WABA**

Modify `apps/api/app/modules/whatsapp_inbox/service.py`, logo após `resolve_by_verify_token`:

```python
def resolve_by_waba_id(db: Session, *, waba_id: str) -> PublicWhatsappAccount | None:
    """Resolve tenant/app_secret pelo WABA ID — o caminho do evento de status de TEMPLATE, que
    não carrega `phone_number_id` nenhum (ver `providers/meta.parse_template_status`).

    `waba_id` não é único (um WABA pode ter vários números, e cada número é uma linha), mas
    todas as linhas do mesmo WABA são do mesmo tenant e carregam o mesmo `app_secret` — o
    dual-write escreve ambos a partir do mesmo perfil. A ordenação por `phone_number_id` só
    torna a escolha determinística entre linhas equivalentes.
    """
    if not _is_safe_identifier(waba_id):
        return None
    return db.scalars(
        select(PublicWhatsappAccount)
        .where(PublicWhatsappAccount.waba_id == waba_id)
        .order_by(PublicWhatsappAccount.phone_number_id)
    ).first()
```

- [ ] **Step 5: Rodar os testes para ver passar**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_whatsapp_inbox_service.py tests/test_settings.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/modules/settings/service.py \
        apps/api/app/modules/whatsapp_inbox/service.py \
        apps/api/tests/test_whatsapp_inbox_service.py
git commit -m "feat: resolver o tenant do webhook pelo WABA, não só pelo telefone [#36]"
```

---

### Task 3: O parser do evento no provider Meta

**Files:**
- Modify: `apps/api/app/core/whatsapp/providers/meta.py` (acrescentar após `parse_inbound`)
- Test: `apps/api/tests/test_whatsapp_inbound_parsing.py` (acrescentar ao arquivo existente)

**Interfaces:**
- Produces:
  - `meta.TEMPLATE_STATUS_FIELD: str = "message_template_status_update"`
  - `meta.TemplateStatusEvent` — dataclass frozen com `meta_template_id: str`, `status: str`, `rejected_reason: str | None`, `category: str | None`
  - `meta.extract_waba_id(payload: dict) -> str | None`
  - `meta.parse_template_status(payload: dict) -> list[TemplateStatusEvent]`
- **Nenhuma das duas funções levanta exceção.** Isso é decisão de projeto, não descuido: as mensagens de 400 do endpoint hoje nascem no caminho de MENSAGEM (`_extract_phone_number_id` / `parse_inbound`), e há teste para cada uma delas. Um payload malformado precisa continuar caindo exatamente onde caía. Estas funções devolvem `[]`/`None` diante de qualquer surpresa de forma, e o fluxo segue para o caminho antigo — que responde o mesmo 400 de sempre.

- [ ] **Step 1: Conferir a forma do payload NA FONTE antes de escrever o parser**

Abra a referência de webhooks da Meta (`developers.facebook.com/docs/graph-api/webhooks/reference/whatsapp-business-account/` → `message_template_status_update`) e confirme os nomes: `entry[].id` (WABA), `changes[].field`, `value.event`, `value.message_template_id`, `value.reason`. Confirme também se `message_template_id` chega como **número** (é o esperado — por isso o parser faz `str(...)`). Regra do projeto: nunca assumir schema de terceiro de cabeça. Se algo divergir do descrito aqui, ajuste o parser E os testes, e anote a divergência no commit.

- [ ] **Step 2: Escrever os testes que falham**

Append em `apps/api/tests/test_whatsapp_inbound_parsing.py`:

```python
# ── Evento de status de template (message_template_status_update) ───────────

from app.core.whatsapp.providers import meta


def _evento_template(*, event="APPROVED", template_id=123456, reason="NONE", waba="waba-1"):
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": waba,
            "changes": [{
                "field": "message_template_status_update",
                "value": {
                    "event": event,
                    "message_template_id": template_id,
                    "message_template_name": "lembrete_cobranca",
                    "message_template_language": "pt_BR",
                    "reason": reason,
                },
            }],
        }],
    }


def test_parse_template_status_extrai_aprovacao():
    eventos = meta.parse_template_status(_evento_template())
    assert len(eventos) == 1
    assert eventos[0].meta_template_id == "123456"  # a Meta manda número; guardamos texto
    assert eventos[0].status == "APPROVED"
    assert eventos[0].rejected_reason is None  # "NONE" da Meta NÃO é um motivo


def test_parse_template_status_guarda_o_motivo_da_rejeicao():
    eventos = meta.parse_template_status(
        _evento_template(event="REJECTED", reason="INVALID_FORMAT")
    )
    assert eventos[0].status == "REJECTED"
    assert eventos[0].rejected_reason == "INVALID_FORMAT"


def test_parse_template_status_ignora_evento_de_mensagem():
    """O MESMO endpoint recebe os dois tipos. Confundi-los seria pior que ignorá-los."""
    payload = {
        "entry": [{
            "id": "waba-1",
            "changes": [{
                "field": "messages",
                "value": {
                    "metadata": {"phone_number_id": "phone-1"},
                    "messages": [{"from": "5511900000000", "id": "wamid.1", "type": "text",
                                  "text": {"body": "oi"}}],
                },
            }],
        }],
    }
    assert meta.parse_template_status(payload) == []


def test_parse_template_status_nao_levanta_com_payload_deformado():
    """Contrato explícito: quem responde 400 é o caminho de mensagem, e há teste pra cada
    forma quebrada lá. Este parser roda ANTES e não pode roubar aquela resposta."""
    for deformado in [
        {"entry": "nao-e-lista"},
        {"entry": [{"changes": "nao-e-lista"}]},
        {"entry": [{"changes": [{"field": "message_template_status_update", "value": "boom"}]}]},
        {},
    ]:
        assert meta.parse_template_status(deformado) == []


def test_parse_template_status_descarta_evento_sem_id_de_template():
    payload = _evento_template()
    del payload["entry"][0]["changes"][0]["value"]["message_template_id"]
    assert meta.parse_template_status(payload) == []


def test_extract_waba_id_le_o_id_do_entry():
    assert meta.extract_waba_id(_evento_template(waba="waba-42")) == "waba-42"


def test_extract_waba_id_devolve_none_quando_nao_ha():
    assert meta.extract_waba_id({"entry": [{}]}) is None
    assert meta.extract_waba_id({"entry": "nao-e-lista"}) is None
    assert meta.extract_waba_id({"entry": [{"id": 123}]}) is None  # número não é WABA válido
```

- [ ] **Step 3: Rodar para ver falhar**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_whatsapp_inbound_parsing.py -k "template_status or waba" -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'parse_template_status'`.

- [ ] **Step 4: Escrever o parser**

Modify `apps/api/app/core/whatsapp/providers/meta.py` — acrescente `from dataclasses import dataclass` aos imports e, logo após `parse_inbound`:

```python
# ── Status de template (message_template_status_update) ─────────────────────

# O `field` do `change` que carrega aprovação/rejeição de template. O MESMO webhook recebe
# `messages` (mensagem recebida) e este — é o `field` que separa um do outro.
TEMPLATE_STATUS_FIELD = "message_template_status_update"


@dataclass(frozen=True)
class TemplateStatusEvent:
    """Um evento de mudança de status, já normalizado. Só FORMA — o que é status válido e o
    que fazer com ele é decisão do domínio (`whatsapp_templates/service.apply_status_events`).
    """

    meta_template_id: str  # texto: a Meta manda número no webhook e String(64) no GET da Graph
    status: str  # o `event` cru da Meta, ainda NÃO validado contra os STATUS_* do model
    rejected_reason: str | None


def extract_waba_id(payload: dict) -> str | None:
    """O WABA ID vive em `entry[].id` — o evento de template não traz telefone nenhum, então
    este é o ÚNICO identificador de conta disponível para resolver o tenant.

    Nunca levanta: ver o contrato no docstring de `parse_template_status`.
    """
    try:
        for entry in payload.get("entry", []):
            waba_id = entry.get("id")
            if isinstance(waba_id, str) and waba_id:
                return waba_id
    except (AttributeError, TypeError, KeyError):
        return None
    return None


def parse_template_status(payload: dict) -> list[TemplateStatusEvent]:
    """Extrai os eventos de status de template do payload da Meta.

    **Nunca levanta exceção — devolve `[]`.** Diferente de `parse_inbound` (que levanta
    `ValueError` e vira 400), esta função roda ANTES do caminho de mensagem no router, sobre
    TODO payload que chega. Se ela levantasse, roubaria os 400 que hoje nascem em
    `_extract_phone_number_id`/`parse_inbound` — e cada um deles tem teste. Diante de qualquer
    surpresa de forma, o resultado é "não era evento de template", o fluxo segue para o
    caminho antigo, e o pior caso é o status ficar como estava até alguém usar o botão
    "Sincronizar" (que continua existindo justamente para isso).
    """
    out: list[TemplateStatusEvent] = []
    try:
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                if change.get("field") != TEMPLATE_STATUS_FIELD:
                    continue
                value = change.get("value", {})
                if not isinstance(value, dict):
                    continue
                meta_template_id = value.get("message_template_id")
                status = value.get("event")
                if meta_template_id is None or not isinstance(status, str):
                    continue
                reason = value.get("reason")
                out.append(
                    TemplateStatusEvent(
                        meta_template_id=str(meta_template_id),
                        status=status,
                        # A Meta manda a string "NONE" quando não há motivo — guardá-la faria a
                        # tela mostrar "NONE" como se fosse a justificativa da Meta.
                        rejected_reason=(
                            reason if isinstance(reason, str) and reason != "NONE" else None
                        ),
                    )
                )
    except (AttributeError, TypeError, KeyError):
        return []
    return out
```

- [ ] **Step 5: Rodar os testes para ver passar**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_whatsapp_inbound_parsing.py -q && ruff check .`
Expected: PASS + lint limpo.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/core/whatsapp/providers/meta.py apps/api/tests/test_whatsapp_inbound_parsing.py
git commit -m "feat: o provider Meta sabe ler message_template_status_update [#36]"
```

---

### Task 4: Aplicar o status no template do tenant

**Files:**
- Modify: `apps/api/app/modules/whatsapp_templates/service.py` (acrescentar após `sync_template`)
- Test: `apps/api/tests/test_whatsapp_templates.py` (acrescentar ao arquivo existente)

**Interfaces:**
- Consumes: `meta.TemplateStatusEvent` (Task 3).
- Produces: `whatsapp_templates.service.apply_status_events(db: Session, *, tenant_id: str, events: list[TemplateStatusEvent]) -> int` — devolve quantos templates foram de fato atualizados. Recebe uma sessão **já** no tenant certo (o router abre).

- [ ] **Step 1: Escrever os testes que falham**

Append em `apps/api/tests/test_whatsapp_templates.py`:

```python
def test_apply_status_events_aprova_o_template(db):
    from app.core.whatsapp.providers.meta import TemplateStatusEvent
    from app.modules.whatsapp_templates import service
    from app.modules.whatsapp_templates.models import WhatsappTemplate

    tpl = WhatsappTemplate(
        tenant_id="t-1", name="lembrete", language="pt_BR", category_requested="UTILITY",
        body_text="Olá {{1}}", variable_count=1, status="PENDING", meta_template_id="777",
    )
    db.add(tpl)
    db.commit()

    aplicados = service.apply_status_events(
        db, tenant_id="t-1",
        events=[TemplateStatusEvent(meta_template_id="777", status="APPROVED",
                                    rejected_reason=None)],
    )

    assert aplicados == 1
    db.refresh(tpl)
    assert tpl.status == "APPROVED"


def test_apply_status_events_guarda_o_motivo_da_rejeicao(db):
    from app.core.whatsapp.providers.meta import TemplateStatusEvent
    from app.modules.whatsapp_templates import service
    from app.modules.whatsapp_templates.models import WhatsappTemplate

    tpl = WhatsappTemplate(
        tenant_id="t-1", name="promo", language="pt_BR", category_requested="MARKETING",
        body_text="Oi", variable_count=0, status="PENDING", meta_template_id="888",
    )
    db.add(tpl)
    db.commit()

    service.apply_status_events(
        db, tenant_id="t-1",
        events=[TemplateStatusEvent(meta_template_id="888", status="REJECTED",
                                    rejected_reason="INVALID_FORMAT")],
    )

    db.refresh(tpl)
    assert tpl.status == "REJECTED"
    assert tpl.rejected_reason == "INVALID_FORMAT"


def test_apply_status_events_ignora_status_que_a_tela_nao_sabe_mostrar(db):
    """A tela tem um Record FECHADO com 5 status (`STATUS_LABEL` em WhatsappSection.tsx).
    Gravar "FLAGGED" ou "PENDING_DELETION" faria o rótulo sair vazio — e um status que a Meta
    inventar amanhã não pode quebrar a tela de quem nem usa aquele recurso."""
    from app.core.whatsapp.providers.meta import TemplateStatusEvent
    from app.modules.whatsapp_templates import service
    from app.modules.whatsapp_templates.models import WhatsappTemplate

    tpl = WhatsappTemplate(
        tenant_id="t-1", name="x", language="pt_BR", category_requested="UTILITY",
        body_text="Oi", variable_count=0, status="APPROVED", meta_template_id="999",
    )
    db.add(tpl)
    db.commit()

    aplicados = service.apply_status_events(
        db, tenant_id="t-1",
        events=[TemplateStatusEvent(meta_template_id="999", status="FLAGGED",
                                    rejected_reason=None)],
    )

    assert aplicados == 0
    db.refresh(tpl)
    assert tpl.status == "APPROVED"  # intocado


def test_apply_status_events_nao_preserva_categoria_inventada(db):
    """O evento de status NÃO carrega categoria (quem carrega é `template_category_update`).
    `category_approved` tem que sobreviver intacto — apagá-lo perderia o que o "Sincronizar"
    já tinha trazido."""
    from app.core.whatsapp.providers.meta import TemplateStatusEvent
    from app.modules.whatsapp_templates import service
    from app.modules.whatsapp_templates.models import WhatsappTemplate

    tpl = WhatsappTemplate(
        tenant_id="t-1", name="y", language="pt_BR", category_requested="MARKETING",
        body_text="Oi", variable_count=0, status="PENDING", meta_template_id="1000",
        category_approved="UTILITY",
    )
    db.add(tpl)
    db.commit()

    service.apply_status_events(
        db, tenant_id="t-1",
        events=[TemplateStatusEvent(meta_template_id="1000", status="APPROVED",
                                    rejected_reason=None)],
    )

    db.refresh(tpl)
    assert tpl.category_approved == "UTILITY"


def test_apply_status_events_ignora_template_desconhecido(db):
    """Evento de um template criado direto no painel da Meta, que nunca existiu aqui."""
    from app.core.whatsapp.providers.meta import TemplateStatusEvent
    from app.modules.whatsapp_templates import service

    aplicados = service.apply_status_events(
        db, tenant_id="t-1",
        events=[TemplateStatusEvent(meta_template_id="nao-existe", status="APPROVED",
                                    rejected_reason=None)],
    )
    assert aplicados == 0


def test_apply_status_events_isola_falha_de_um_evento(db):
    """Um lote pode trazer vários eventos. Um desconhecido no meio não pode impedir os outros
    — mesmo princípio de `whatsapp_inbox.service.ingest_webhook_payload`."""
    from app.core.whatsapp.providers.meta import TemplateStatusEvent
    from app.modules.whatsapp_templates import service
    from app.modules.whatsapp_templates.models import WhatsappTemplate

    tpl = WhatsappTemplate(
        tenant_id="t-1", name="z", language="pt_BR", category_requested="UTILITY",
        body_text="Oi", variable_count=0, status="PENDING", meta_template_id="1111",
    )
    db.add(tpl)
    db.commit()

    aplicados = service.apply_status_events(
        db, tenant_id="t-1",
        events=[
            TemplateStatusEvent(meta_template_id="orfao", status="APPROVED",
                                rejected_reason=None),
            TemplateStatusEvent(meta_template_id="1111", status="APPROVED",
                                rejected_reason=None),
        ],
    )

    assert aplicados == 1
    db.refresh(tpl)
    assert tpl.status == "APPROVED"
```

Antes de rodar: confira os campos obrigatórios de `WhatsappTemplate` em `models.py:86-115` e ajuste os construtores acima se faltar algum (`id` tem default `_uuid`). Se o arquivo de teste já tiver um helper que monta template, **use o helper** em vez destes construtores.

- [ ] **Step 2: Rodar para ver falhar**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_whatsapp_templates.py -k "apply_status" -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'apply_status_events'`.

- [ ] **Step 3: Implementar**

Modify `apps/api/app/modules/whatsapp_templates/service.py` — acrescente o import do evento no topo:

```python
from app.core.whatsapp.providers.meta import TemplateStatusEvent
```

e, logo após `sync_template`:

```python
# Os únicos status que este produto sabe representar — espelham os STATUS_* do model e o
# `STATUS_LABEL` da tela (`apps/web/src/features/config/WhatsappSection.tsx`), que é um Record
# FECHADO. A Meta emite outros valores no webhook (`PENDING_DELETION`, `FLAGGED`, ...);
# gravá-los faria a tela mostrar rótulo vazio, então eles são ignorados de propósito.
_STATUS_CONHECIDOS = frozenset(
    {STATUS_PENDING, STATUS_APPROVED, STATUS_REJECTED, STATUS_PAUSED, STATUS_DISABLED}
)


def apply_status_events(
    db: Session, *, tenant_id: str, events: list[TemplateStatusEvent]
) -> int:
    """Aplica os eventos de `message_template_status_update` já parseados. Devolve quantos
    templates foram de fato atualizados.

    Recebe uma sessão JÁ no tenant certo (o router do webhook abre a `tenant_session` depois de
    resolver a conta pelo WABA). Por isso NÃO filtra por `tenant_id` na query — a RLS isola
    (Regra de Ouro nº 1); o parâmetro `tenant_id` existe para log e para deixar a assinatura
    igual à das irmãs deste módulo.

    **`category_approved` NÃO é tocado de propósito.** O evento de status não carrega categoria
    — quem carrega é o evento `template_category_update`, que este produto não assina. Escrever
    `None` aqui apagaria a categoria que o "Sincronizar" manual trouxe. Se um dia a categoria
    precisar vir por webhook, é um evento NOVO a tratar, não um campo a mais neste.

    Cada evento é commitado isoladamente: um evento órfão no meio do lote não pode impedir os
    demais (mesmo princípio de `whatsapp_inbox.service.ingest_webhook_payload`).
    """
    aplicados = 0
    for event in events:
        if event.status not in _STATUS_CONHECIDOS:
            logger.info(
                "[whatsapp_template:webhook] status desconhecido ignorado tenant=%s "
                "meta_template_id=%s status=%s",
                tenant_id, event.meta_template_id, event.status,
            )
            continue
        template = db.scalar(
            select(WhatsappTemplate).where(
                WhatsappTemplate.meta_template_id == event.meta_template_id
            )
        )
        if template is None:
            # Template criado direto no painel da Meta, ou de outro tenant (a RLS já o
            # escondeu). Não é erro: a Meta manda o evento pra todo mundo daquele WABA.
            logger.info(
                "[whatsapp_template:webhook] template desconhecido tenant=%s "
                "meta_template_id=%s", tenant_id, event.meta_template_id,
            )
            continue
        template.status = event.status
        template.rejected_reason = event.rejected_reason
        db.commit()
        aplicados += 1
    return aplicados
```

- [ ] **Step 4: Rodar os testes para ver passar**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_whatsapp_templates.py -q && ruff check .`
Expected: PASS + lint limpo.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/modules/whatsapp_templates/service.py apps/api/tests/test_whatsapp_templates.py
git commit -m "feat: aplicar status de template vindo do webhook [#36]"
```

---

### Task 5: O ramo de template no endpoint público (o fio inteiro)

**Files:**
- Modify: `apps/api/app/modules/whatsapp_inbox/router.py:66-109`
- Test: `apps/api/tests/test_whatsapp_template_status_webhook.py` (criar)

**Interfaces:**
- Consumes: `service.resolve_by_waba_id` (Task 2), `whatsapp.meta.parse_template_status` / `extract_waba_id` (Task 3), `whatsapp_templates.service.apply_status_events` (Task 4).
- Produces: nada novo para outras tasks — é a costura.
- Import cruzado: `whatsapp_inbox/router.py` passa a importar `whatsapp_templates/service.py`. Não há ciclo: `whatsapp_templates.service` → `settings.service` → `whatsapp_inbox.**models**` (nunca o router).

- [ ] **Step 1: Escrever os testes que falham**

Create `apps/api/tests/test_whatsapp_template_status_webhook.py`:

```python
"""O MESMO endpoint público recebe mensagem e aprovação de template — e o segundo tipo chega
roteado por WABA, sem telefone nenhum. Ver issue #36 item 5.
"""
import hashlib
import hmac
import json

from sqlalchemy import select

from app.modules.whatsapp_inbox.models import PublicWhatsappAccount
from app.modules.whatsapp_templates.models import WhatsappTemplate


def _seed(db, *, tenant_id="t-1", waba_id="waba-1", app_secret="segredo", meta_template_id="777"):
    db.add(PublicWhatsappAccount(
        phone_number_id="phone-1", tenant_id=tenant_id, app_secret=app_secret,
        verify_token="verify-1", waba_id=waba_id,
    ))
    db.add(WhatsappTemplate(
        tenant_id=tenant_id, name="lembrete", language="pt_BR", category_requested="UTILITY",
        body_text="Olá {{1}}", variable_count=1, status="PENDING",
        meta_template_id=meta_template_id,
    ))
    db.commit()


def _payload(*, waba_id="waba-1", event="APPROVED", template_id=777, reason="NONE"):
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": waba_id,
            "changes": [{
                "field": "message_template_status_update",
                "value": {
                    "event": event, "message_template_id": template_id,
                    "message_template_name": "lembrete", "message_template_language": "pt_BR",
                    "reason": reason,
                },
            }],
        }],
    }


def _sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _post(client, payload, *, secret="segredo", signature=None):
    body = json.dumps(payload).encode()
    return client.post(
        "/public/whatsapp/webhook", content=body,
        headers={
            "content-type": "application/json",
            "x-hub-signature-256": signature or _sign(body, secret),
        },
    )


def test_aprovacao_da_meta_atualiza_o_template_sem_ninguem_clicar(client, db):
    _seed(db)
    resp = _post(client, _payload())
    assert resp.status_code == 200

    tpl = db.scalar(select(WhatsappTemplate).where(WhatsappTemplate.meta_template_id == "777"))
    assert tpl.status == "APPROVED"


def test_rejeicao_traz_o_motivo(client, db):
    _seed(db)
    resp = _post(client, _payload(event="REJECTED", reason="INVALID_FORMAT"))
    assert resp.status_code == 200

    tpl = db.scalar(select(WhatsappTemplate).where(WhatsappTemplate.meta_template_id == "777"))
    assert tpl.status == "REJECTED"
    assert tpl.rejected_reason == "INVALID_FORMAT"


def test_assinatura_invalida_nao_muda_nada(client, db):
    """Sem esta checagem, qualquer um na internet aprovaria template alheio com um curl."""
    _seed(db)
    resp = _post(client, _payload(), signature="sha256=forjado")
    assert resp.status_code == 403

    tpl = db.scalar(select(WhatsappTemplate).where(WhatsappTemplate.meta_template_id == "777"))
    assert tpl.status == "PENDING"


def test_waba_desconhecida_da_404(client, db):
    _seed(db)
    resp = _post(client, _payload(waba_id="waba-de-outra-plataforma"))
    assert resp.status_code == 404


def test_evento_de_template_nao_exige_phone_number_id(client, db):
    """A regressão que este arquivo existe pra impedir: antes desta onda o payload de template
    morria em 404 'phone_number_id não encontrado' porque só havia um caminho de roteamento."""
    _seed(db)
    resp = _post(client, _payload())
    assert resp.status_code == 200
    assert "phone_number_id" not in resp.text


def test_mensagem_recebida_continua_funcionando(client, db):
    """O ramo novo roda ANTES do antigo em todo payload — o caminho de mensagem não pode ter
    mudado de comportamento."""
    from app.modules.whatsapp_inbox.models import WhatsappMessage

    _seed(db)
    payload = {
        "entry": [{
            "id": "waba-1",
            "changes": [{
                "field": "messages",
                "value": {
                    "metadata": {"phone_number_id": "phone-1"},
                    "contacts": [{"profile": {"name": "Cliente"}, "wa_id": "5511900000000"}],
                    "messages": [{"from": "5511900000000", "id": "wamid.novo", "type": "text",
                                  "text": {"body": "Olá!"}}],
                },
            }],
        }],
    }
    resp = _post(client, payload)
    assert resp.status_code == 200
    assert db.scalar(
        select(WhatsappMessage).where(WhatsappMessage.wa_message_id == "wamid.novo")
    ) is not None
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_whatsapp_template_status_webhook.py -v`
Expected: FAIL — os testes de template recebem **404** ("phone_number_id não encontrado no payload"). É exatamente o bug que a issue descreve.

- [ ] **Step 3: Extrair o helper de assinatura**

Modify `apps/api/app/modules/whatsapp_inbox/router.py` — acrescente antes de `receive_webhook`:

```python
def _exigir_assinatura(*, app_secret: str, body: bytes, signature_header: str | None) -> None:
    """Levanta 403 se a assinatura não bater. Extraído porque os DOIS ramos do webhook
    (mensagem e status de template) precisam da mesma checagem com o `app_secret` da conta já
    resolvida — duas cópias divergiriam na primeira mudança."""
    if not whatsapp.verify_webhook_signature(
        app_secret=app_secret, body=body, signature_header=signature_header
    ):
        raise HTTPException(status_code=403, detail="Assinatura inválida")
```

e troque o bloco atual de checagem (`router.py:96-100`) por:

```python
    _exigir_assinatura(
        app_secret=account.app_secret,
        body=body,
        signature_header=request.headers.get("x-hub-signature-256"),
    )
```

- [ ] **Step 4: Acrescentar o ramo de template**

Modify `apps/api/app/modules/whatsapp_inbox/router.py` — importe o service de templates no topo:

```python
from app.modules.whatsapp_templates import service as whatsapp_templates_service
```

e insira em `receive_webhook`, **depois** da validação do JSON (`if not isinstance(payload, dict)`) e **antes** de `phone_number_id = _extract_phone_number_id(payload)`:

```python
    # ── Ramo 1: aprovação/rejeição de template ──────────────────────────────
    # Roda ANTES do caminho de mensagem porque é ele que sabe se este payload é de template.
    # `parse_template_status` nunca levanta (ver docstring lá): payload de mensagem, ou
    # qualquer payload deformado, devolve [] e o fluxo cai no caminho antigo — que segue
    # respondendo os mesmos 400 de sempre, com os mesmos testes.
    #
    # O roteamento aqui é por WABA, não por telefone: o evento de template NÃO tem
    # `metadata.phone_number_id` (era assim que ele morria em 404 antes da issue #36).
    template_events = whatsapp.meta.parse_template_status(payload)
    if template_events:
        waba_id = whatsapp.meta.extract_waba_id(payload)
        if not waba_id:
            raise HTTPException(status_code=404, detail="WABA não encontrada no payload")
        account = service.resolve_by_waba_id(db, waba_id=waba_id)
        if account is None:
            raise HTTPException(
                status_code=404, detail="Conta não configurada nesta plataforma"
            )
        _exigir_assinatura(
            app_secret=account.app_secret,
            body=body,
            signature_header=request.headers.get("x-hub-signature-256"),
        )
        with session_factory(account.tenant_id) as tdb:
            whatsapp_templates_service.apply_status_events(
                tdb, tenant_id=account.tenant_id, events=template_events
            )
        return {"status": "ok"}

    # ── Ramo 2: mensagem recebida (o caminho original) ──────────────────────
```

- [ ] **Step 5: Rodar os testes para ver passar**

Run:
```bash
cd apps/api && .venv/Scripts/python -m pytest tests/test_whatsapp_template_status_webhook.py tests/test_whatsapp_inbox_webhook.py -v
```
Expected: PASS — inclusive os 14 testes antigos de `test_whatsapp_inbox_webhook.py`, sem nenhum ajuste neles. Se algum dos antigos quebrou, o ramo novo está roubando resposta de erro do caminho de mensagem: reveja o Step 4 do Task 3 (o parser não pode levantar).

- [ ] **Step 6: Suíte completa + lint**

Run: `cd apps/api && ruff check . && .venv/Scripts/python -m pytest -q -m 'not rls_e2e'`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/api/app/modules/whatsapp_inbox/router.py \
        apps/api/tests/test_whatsapp_template_status_webhook.py
git commit -m "feat: o webhook aprova o template sozinho, sem clicar em Sincronizar [#36]"
```

---

### Task 6: A prova sob RLS real (Postgres)

**Files:**
- Create: `apps/api/tests/test_whatsapp_template_status_rls.py`

**Interfaces:**
- Consumes: tudo das Tasks 1-5.
- Este teste existe porque **duas** coisas desta onda são invisíveis para a suíte SQLite: (a) o backfill da 0079 seria filtrado a zero linhas sem a janela de RLS, e (b) o `apply_status_events` roda numa sessão de tenant e não pode enxergar/alterar template de outro tenant. A suíte SQLite passa dos dois jeitos.
- Precisa de **Docker rodando** (testcontainers). Roda em ~10s. Rodar localmente, não deixar para o CI descobrir.

- [ ] **Step 1: Escrever o teste**

Create `apps/api/tests/test_whatsapp_template_status_rls.py`:

```python
"""O backfill da 0079 e a aplicação do status, sob Postgres real com FORCE ROW LEVEL SECURITY.

Dois enganos que a suíte SQLite deixa passar inteiros:

1. O backfill da 0079 lê `tenant_profiles` (RLS). Sem a janela DISABLE/ENABLE+FORCE, o UPDATE
   é filtrado a ZERO LINHAS em silêncio — todo tenant já configurado ficaria de fora do
   roteamento por WABA e o webhook responderia 404 pra sempre, sem erro em lugar nenhum.
2. `apply_status_events` não filtra por tenant_id (Regra de Ouro nº 1). Se a RLS não estiver
   isolando de fato, um evento aprovaria o template homônimo de OUTRO tenant.

Cada asserção vem com o controle positivo ao lado, pelo mesmo motivo do
`test_auth_timezone_rls.py`: provar que ela falha pelo motivo certo, e não porque o dado nem
chegou a ser gravado.

O container roda as migrations em DUAS etapas (`0078`, depois `0079`) — sem isso não existiria
linha nenhuma no momento do backfill, e o teste passaria com a janela de RLS removida.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest

pytest.importorskip("testcontainers.postgres")

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402
from testcontainers.postgres import PostgresContainer  # noqa: E402

pytestmark = pytest.mark.rls_e2e

_APP_PASS = "e1ppass"  # noqa: S105 (senha efêmera do papel de app no container de teste)
_DB_NAME = "e1pdb"
_API_DIR = Path(__file__).resolve().parents[1]


def _bootstrap_rls_role(super_url: str) -> None:
    engine = create_engine(super_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            conn.execute(text(f"CREATE ROLE e1p_app WITH LOGIN PASSWORD '{_APP_PASS}' NOSUPERUSER"))
            conn.execute(text(f"GRANT ALL PRIVILEGES ON DATABASE {_DB_NAME} TO e1p_app"))
            conn.execute(text("GRANT ALL ON SCHEMA public TO e1p_app"))
    finally:
        engine.dispose()


def _migrar_ate(app_url: str, revision: str) -> None:
    """Roda as migrations como `e1p_app` — o papel NÃO-superusuário, SEM a GUC de tenant. É
    exatamente assim que elas rodam em produção, e é por isso que a janela de RLS importa."""
    from alembic import command
    from alembic.config import Config

    from app.config import settings

    original = settings.database_url
    settings.database_url = app_url
    try:
        cfg = Config(str(_API_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(_API_DIR / "migrations"))
        command.upgrade(cfg, revision)
    finally:
        settings.database_url = original


@contextmanager
def _tenant_session(app_url: str, tenant_id: str):
    """Sessão COM a GUC de tenant — o que as rotas de módulo de negócio usam."""
    engine = create_engine(app_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant_id', :t, false)"), {"t": tenant_id}
            )
            conn.commit()
            session = Session(bind=conn)
            try:
                yield session
            finally:
                session.close()
    finally:
        engine.dispose()


@contextmanager
def _raw_session(app_url: str):
    """Sessão SEM tenant — exatamente o que o webhook público usa (`get_db`)."""
    engine = create_engine(app_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            session = Session(bind=conn)
            try:
                yield session
            finally:
                session.close()
    finally:
        engine.dispose()


@contextmanager
def _container_migrado_ate(revision: str):
    with PostgresContainer("postgres:16-alpine", dbname=_DB_NAME) as pg:
        super_url = pg.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql+psycopg://"
        )
        _bootstrap_rls_role(super_url)
        host = super_url.split("@", 1)[1]
        url = f"postgresql+psycopg://e1p_app:{_APP_PASS}@{host}"
        _migrar_ate(url, revision)
        yield url


@pytest.fixture(scope="module")
def app_url():
    """Banco no head — para o teste de isolamento."""
    with _container_migrado_ate("head") as url:
        yield url


def _criar_template(db: Session, *, tenant_id: str, meta_template_id: str) -> str:
    from app.modules.whatsapp_templates.models import WhatsappTemplate

    tpl = WhatsappTemplate(
        tenant_id=tenant_id, name="lembrete", language="pt_BR", category_requested="UTILITY",
        body_text="Olá {{1}}", variable_count=1, status="PENDING",
        meta_template_id=meta_template_id,
    )
    db.add(tpl)
    db.commit()
    return tpl.id


def test_backfill_da_0079_preenche_waba_id_de_quem_ja_estava_configurado():
    """Container PRÓPRIO, parado na 0078: precisa existir linha ANTES do backfill rodar.

    É esta asserção que morre se alguém remover a janela de RLS da migration — e ela morre do
    jeito certo: `waba_id` volta NULL, sem erro nenhum, exatamente como aconteceria em
    produção.
    """
    from app.modules.auth.models import Tenant
    from app.modules.settings.models import TenantProfile
    from app.modules.whatsapp_inbox.models import PublicWhatsappAccount

    with _container_migrado_ate("0078") as url:
        # `tenants` não tem RLS; `tenant_profiles` tem — por isso o perfil é criado numa sessão
        # COM a GUC, pelo mesmo caminho que a aplicação usa.
        with _raw_session(url) as raw:
            raw.add(Tenant(id="t-backfill", name="Tenant do backfill"))
            raw.commit()

        with _tenant_session(url, "t-backfill") as tdb:
            tdb.add(TenantProfile(
                tenant_id="t-backfill",
                whatsapp_token="tok", whatsapp_phone_id="phone-1",
                whatsapp_waba_id="waba-real", whatsapp_app_secret="segredo",
                whatsapp_verify_token="verify-1",
            ))
            tdb.commit()

        # O snapshot global existe desde a 0054 — mas SEM a coluna `waba_id`, que só nasce na
        # 0079. Por isso ele é inserido aqui via SQL crua, com as colunas de então.
        with _raw_session(url) as raw:
            raw.execute(text(
                "INSERT INTO public_whatsapp_accounts "
                "(phone_number_id, tenant_id, app_secret, verify_token) "
                "VALUES ('phone-1', 't-backfill', 'segredo', 'verify-1')"
            ))
            raw.commit()

        _migrar_ate(url, "0079")

        # Sessão CRUA de propósito: é como o webhook lê essa tabela, sem tenant nenhum.
        with _raw_session(url) as raw:
            conta = raw.get(PublicWhatsappAccount, "phone-1")
            assert conta is not None, "o snapshot sumiu — a migration derrubou a linha"
            assert conta.waba_id == "waba-real", (
                "o backfill não enxergou `tenant_profiles` — a janela de RLS da 0079 sumiu"
            )


def test_evento_nao_aprova_template_de_outro_tenant(app_url):
    """`apply_status_events` NÃO filtra por tenant_id — quem isola é a RLS. Se a policy não
    estiver valendo, o evento do tenant A aprova o template homônimo do tenant B: a Meta não
    garante `meta_template_id` único entre WABAs diferentes."""
    from app.core.whatsapp.providers.meta import TemplateStatusEvent
    from app.modules.auth.models import Tenant
    from app.modules.whatsapp_templates import service
    from app.modules.whatsapp_templates.models import WhatsappTemplate

    with _raw_session(app_url) as raw:
        raw.add(Tenant(id="t-A", name="Tenant A"))
        raw.add(Tenant(id="t-B", name="Tenant B"))
        raw.commit()

    with _tenant_session(app_url, "t-A") as db_a:
        id_a = _criar_template(db_a, tenant_id="t-A", meta_template_id="777")
    with _tenant_session(app_url, "t-B") as db_b:
        id_b = _criar_template(db_b, tenant_id="t-B", meta_template_id="777")

    with _tenant_session(app_url, "t-A") as db_a:
        aplicados = service.apply_status_events(
            db_a, tenant_id="t-A",
            events=[TemplateStatusEvent(
                meta_template_id="777", status="APPROVED", rejected_reason=None
            )],
        )
        assert aplicados == 1

    # Controle positivo: em A mudou de fato (senão o assert de B abaixo passaria por nada ter
    # acontecido, e não por isolamento).
    with _tenant_session(app_url, "t-A") as db_a:
        assert db_a.get(WhatsappTemplate, id_a).status == "APPROVED"

    with _tenant_session(app_url, "t-B") as db_b:
        assert db_b.get(WhatsappTemplate, id_b).status == "PENDING", (
            "o evento do tenant A tocou o template do tenant B — a RLS não isolou"
        )
```

Antes de rodar: confira os campos obrigatórios de `Tenant` e `TenantProfile` (`auth/models.py`, `settings/models.py`) e ajuste os construtores se algum `nullable=False` sem default estiver faltando. O fuso mora em `tenants` desde a 0073 — se `Tenant` exigir `timezone`, passe `"America/Sao_Paulo"`.

- [ ] **Step 2: Rodar (exige Docker)**

Run: `cd apps/api && .venv/Scripts/python -m pytest -m rls_e2e tests/test_whatsapp_template_status_rls.py -v`
Expected: PASS, **2 executados, 0 skipped**. Se disser `skipped`, o Docker não está rodando — o CI trata "tudo skipped" como falha (Story 7.1), então isto NÃO conta como verde.

- [ ] **Step 3: Provar que o teste do backfill pega o erro que ele existe pra pegar**

Comente as três linhas `ALTER TABLE tenant_profiles ...` de `backfill_waba_id()` e rode de novo.
Expected: **FAIL** em `test_backfill_da_0079_preenche_waba_id_de_quem_ja_estava_configurado` (`waba_id` volta `None`). Descomente e confirme que volta a passar.

⚠️ Faça este passo por **cópia do arquivo** (`cp` antes, restaurar depois) — nunca com `git checkout`, que apagaria trabalho não commitado do diretório.

- [ ] **Step 4: Commit**

```bash
git add apps/api/tests/test_whatsapp_template_status_rls.py
git commit -m "test: o backfill do waba_id e o isolamento do evento, sob RLS real [#36]"
```

---

### Task 7: A instrução que faz o webhook de fato disparar

**Files:**
- Modify: `apps/web/src/features/config/WhatsappSection.tsx:277-295`
- Test: `apps/web/src/features/config/WhatsappSection.test.tsx`

**Interfaces:**
- Consumes: nada do backend (é copy).
- **Por que isto é parte da onda, e não um extra:** no painel da Meta, a URL do webhook e os CAMPOS assinados são coisas separadas. Quem seguiu a instrução atual assinou `messages` e só. Sem assinar `message_template_status_update`, todo o código das Tasks 1-6 nunca é chamado — o recurso fica pronto e desligado, e o sintoma é "não funcionou", indistinguível de bug.

- [ ] **Step 1: Escrever o teste que falha**

Append em `apps/web/src/features/config/WhatsappSection.test.tsx` (use o mesmo helper de render/perfil que o arquivo já usa para os testes do bloco de webhook — procure por `whatsapp_verify_token`):

```tsx
it("diz quais campos assinar no painel da Meta", async () => {
  // A URL e o verify token sozinhos não fazem o webhook disparar: sem assinar os CAMPOS,
  // a Meta nunca envia nada. `message_template_status_update` é o que traz a aprovação
  // do template sem ninguém clicar em Sincronizar (issue #36).
  renderComPerfil({ whatsapp_verify_token: "abc123" });

  expect(await screen.findByText(/message_template_status_update/)).toBeInTheDocument();
  expect(screen.getByText(/messages/)).toBeInTheDocument();
});
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `cd apps/web && pnpm vitest run src/features/config/WhatsappSection.test.tsx -t "campos assinar"`
Expected: FAIL — `Unable to find an element with the text: /message_template_status_update/`.

- [ ] **Step 3: Acrescentar a instrução**

Modify `apps/web/src/features/config/WhatsappSection.tsx` — dentro do bloco `{profile.whatsapp_verify_token && (...)}`, logo após o `<div>` do "Verify token":

```tsx
              <div className="mt-2">
                <span className="mb-1 block text-xs text-neutral-500">
                  Campos a assinar (Webhook fields)
                </span>
                <code className="block rounded-lg bg-white px-3 py-2 text-xs">
                  messages, message_template_status_update
                </code>
                <p className="mt-1 text-xs text-neutral-500">
                  Sem o segundo, o status dos seus templates só muda quando você clicar em
                  &quot;Sincronizar&quot;.
                </p>
              </div>
```

- [ ] **Step 4: Rodar os testes para ver passar**

Run: `cd apps/web && pnpm vitest run src/features/config/WhatsappSection.test.tsx && pnpm lint && pnpm typecheck`
Expected: PASS + lint/typecheck limpos.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/features/config/WhatsappSection.tsx \
        apps/web/src/features/config/WhatsappSection.test.tsx
git commit -m "feat: a tela diz quais campos assinar no painel da Meta [#36]"
```

---

### Task 8: Fechar a issue com o que ficou de fora

**Files:**
- Nenhum arquivo de código.

- [ ] **Step 1: Suíte inteira, uma última vez**

Run:
```bash
cd apps/api && ruff check . && .venv/Scripts/python -m pytest -q -m 'not rls_e2e'
cd apps/api && .venv/Scripts/python -m pytest -q -m rls_e2e
cd apps/web && pnpm lint && pnpm typecheck && pnpm test
```
Expected: tudo PASS. Confirme com os OLHOS que o `rls_e2e` diz `executados >= 2`, não `skipped`.

- [ ] **Step 2: Abrir o PR (via @devops — `git push` e `gh pr create` são exclusivos dele)**

Corpo do PR: o que mudou, e a nota de operação — **tenants já configurados precisam voltar ao painel da Meta e assinar o campo `message_template_status_update`**; o backfill resolve o lado do e1p, mas a assinatura do campo mora na Meta e ninguém consegue fazê-la pelo tenant.

- [ ] **Step 3: Comentar na issue #36 o que NÃO foi feito, antes de fechá-la**

```bash
gh issue comment 36 --body "Item 5 pago em <PR>. Itens 1-4 e 6 já existiam desde o épico da Caixa de Entrada.

Fica FORA, de propósito: \`category_approved\` continua vindo só do botão Sincronizar — o evento \`message_template_status_update\` não carrega categoria (quem carrega é \`template_category_update\`, que não assinamos). Status desconhecidos da Meta (\`FLAGGED\`, \`PENDING_DELETION\`) são ignorados: a tela tem um Record fechado de 5 status.

Operação: tenants já configurados precisam assinar o campo \`message_template_status_update\` no painel da Meta — a tela de Configurações agora diz isso."
```

Só então fechar a issue.

---

## Self-Review

**Cobertura da spec (issue #36, item 5):** "Atualizar `status`/`category_approved`/`rejected_reason` a partir do payload do evento (mesmos campos que `sync_template`/`fetch_template_status` já tratam hoje — reaproveitar a lógica)."

- `status` → Task 4, com a restrição ao conjunto que a tela sabe mostrar.
- `rejected_reason` → Task 4, com `"NONE"` → `None`.
- `category_approved` → **divergência consciente da issue**, documentada em "O que esta onda paga", no docstring de `apply_status_events` e no comentário de fechamento (Task 8): o evento não carrega o campo, e escrevê-lo apagaria dado bom.
- "reaproveitar a lógica" → os três campos gravados são os mesmos de `sync_template`; a leitura da Graph API não é reaproveitável (o webhook empurra, não puxa), então o que se reaproveita é o formato de gravação, não a chamada HTTP.
- O item 5 pressupõe roteamento resolvido (item 4), mas o item 4 entregue só roteia por telefone — a lacuna vira as Tasks 1-2, sem as quais o item 5 é inalcançável.

**Consistência de tipos entre tasks:** `TemplateStatusEvent(meta_template_id: str, status: str, rejected_reason: str | None)` é produzido na Task 3 e consumido na Task 4 e nos testes da Task 6 com essa mesma ordem/nomes. `resolve_by_waba_id(db, *, waba_id)` é definido na Task 2 e chamado na Task 5 com keyword. `apply_status_events(db, *, tenant_id, events) -> int` idem. `waba_id` é `str | None` no model (Task 1) e o router só chama o lookup depois de checar `if not waba_id` (Task 5).

**Ordem das Tasks:** 1 → 2 (coluna antes do dual-write), 3 e 4 são independentes entre si e de 1-2, 5 depende de todas, 6 depende de 5, 7 é independente. Só 5 é bloqueante para 6.
