# Ingestão de leads com atribuição (Publ.IA) — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Um site externo (hoje nexuspublica.com.br, tenant Nexus) empurra pessoas — com a origem já resolvida — para o CRM do e1p por `POST /public/ingest/leads`, autenticado por credencial de máquina com escopo `lead_ingest`, com idempotência, tags de origem, fato na timeline, ida ao Ganho na compra, funil por evento e leitura do código de origem na 1ª mensagem de WhatsApp.

**Architecture:** Dois módulos novos em `apps/api/app/modules/`: `machine_tokens` (credencial global sem RLS, irmã de `device_tokens`, sem `user_id`) e `lead_ingest` (contrato pydantic congelado, registro de idempotência com RLS e restrição única, serviço que reaproveita `crm.absorb_lead`/`move_client`, `funnels.engine.enroll` e `core.facts.record`, rota pública que resolve o tenant PELO TOKEN e abre `tenant_session`). O inbox de WhatsApp ganha uma chamada para o leitor de código. Configuração por tenant (produto e funil por evento) numa coluna JSON de `tenant_profiles`, escrita por script de administração — sem tela.

**Tech Stack:** Python 3.13, FastAPI 0.115, SQLAlchemy 2 + Alembic, pydantic 2.10, pytest (SQLite em memória para a suíte comum; Postgres 16 real via testcontainers para `rls_e2e`).

**Spec:** F:/Projetos/Mkt-spec-atribuicao/docs/superpowers/specs/2026-09-30-atribuicao-publia-e1p-design.md (§6)

## Global Constraints

- Rota: `POST /public/ingest/leads`, cabeçalho `Authorization: Bearer <token de máquina, escopo lead_ingest>` (spec §6.1). Publicamente: `https://<domínio do e1p>/api/public/ingest/leads` (Traefik/Caddy removem `/api`).
- Contrato do §6.1 é CONGELADO: campos `evento`, `chave_idempotencia`, `ocorrido_em`, `contato{nome,email,telefone}`, `tags`, `atribuicao{situacao,primeiro_toque,ultimo_toque}`, `pedido{provedor,order_id,plano,periodo,valor_bruto_centavos,valor_liquido_centavos}` — nenhum renomeado.
- `evento` ∈ `lead | carrinho_abandonado | compra_aprovada | renovacao | reembolso | chargeback | cancelamento`; `situacao` ∈ `resolvida | apenas_kiwify | sem_origem`.
- Respostas: `201` criado, `200` chave já processada (no-op), `401` token, `422` payload inválido. Nenhum outro código é produzido de propósito (500 = falha inesperada, o site retenta).
- O tenant vem do token, nunca do corpo. Campo `tenant_id` no corpo é ignorado.
- `contato` exige e-mail **ou** telefone; `""` vindo do site vale como ausente, não como e-mail inválido.
- `pedido` só nos eventos de venda (aceito como opcional em todos; não é exigido por evento).
- Contato entra por `absorb_lead` com `source="api"` (valor já existente em `SOURCE_VALUES`); `Client.source` nunca é sobrescrito.
- Tags: acrescentadas sem duplicar; máx. **50** tags por contato, **40** caracteres por tag; o excedente é descartado e registrado no fato (`tags_descartadas`) e no registro — nunca vira 422.
- Idempotência: tabela `lead_ingest_records` com `UniqueConstraint("tenant_id", "chave_idempotencia")`.
- Fato: `module="comercial"`, `kind` por evento na taxonomia `comercial.<entidade>.<verbo>` (a guarda de `core/facts.py` recusa `publia.*` sob `comercial`), atribuição e pedido em JSON no corpo, **sem** campos `*_centavos` (invariante 2 de `core/facts.py`).
- Etapa: `compra_aprovada` → coluna `is_won`; `reembolso`/`chargeback` → tag `<produto>:reembolso`/`<produto>:chargeback`, sem mover nem apagar; `cancelamento` → `<produto>:cancelou`; `renovacao` só registra.
- `<produto>` é o slug configurado por tenant (`lead_ingest_config.produto`, Nexus = `publia`); sem produto configurado não há tag de produto nem leitura de código no WhatsApp.
- WhatsApp: código `<canal>-<tipo>-<id>`, máx. 20 caracteres, canais `ig` `gg` `em` `wa` `pt` (spec §4.1); tags `origem:<canal>`, `post:<código>`, `<produto>:lead-whatsapp`; só na 1ª mensagem de contato criado por ela.
- Funil por evento: `lead_ingest_config.funis[evento]`; sem mapeamento, `default_entry_funnel_id` só para `lead`, `carrinho_abandonado`, `compra_aprovada`.
- Regra de Ouro nº 1: nenhuma query de negócio filtra `tenant_id` à mão; `get_db` (sessão global) só em `lead_ingest/router.py`, para ler `machine_tokens`, e o módulo entra na ALLOWLIST de `tests/test_tenancy_guard.py`.
- Migrations: `0088` → `0089` → `0090`, encadeadas a partir de `0087` (head em `origin/main` 0d23c74). Só DDL, nenhum `UPDATE`. Antes de abrir PR, conferir colisão: `git fetch origin && git ls-tree --name-only origin/main apps/api/migrations/versions/ | grep -E "/00(8[89]|9)"` deve sair vazio; se não sair, renumerar as três.
- Python dos comandos: `F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe` (o venv do checkout principal; a worktree não tem venv próprio). Diretório: `F:/Projetos/e1p/_wt-ingest-atribuicao/apps/api`.
- Gate de CI que vale aqui (`.github/workflows/ci.yml`): `ruff check .` + `python -m pytest -q -m 'not rls_e2e'` dentro da imagem de produção, e `python -m pytest -q -m rls_e2e` (exige ≥ 9 executados) no job `cross-tenant-rls`. **Não há mypy no CI.** `main` é protegida: 5 required checks, push direto rejeitado.
- `git push` e `gh pr create` são exclusivos do `@devops`. Este plano só faz commits locais na branch `feat/ingest-atribuicao-publia`.
- Commits: Conventional Commits em português, terminando com linha em branco + `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` (as duas `-m` do `git commit` produzem a linha em branco).
- Fora de escopo: `apps/web`, `packages/shared-types`, relatório da fase 2.

## Review Focus

1. **Mesmo e-mail com telefone diferente** (e telefone de um contato + e-mail de outro): cai no contato existente, sem card novo e sem trocar o telefone já gravado; o telefone vence o e-mail. → Task 7, `test_mesmo_email_com_telefone_diferente_nao_cria_card_nem_troca_telefone` e `test_telefone_de_um_e_email_de_outro_fica_com_o_dono_do_telefone`.
2. **Lista de tags acima do limite / tag de 41+ caracteres:** responde 201, guarda as 50 primeiras, registra as descartadas no fato e no registro. → Task 7, `test_tags_acima_do_limite_nao_derrubam_e_ficam_registradas`.
3. **Reenvios concorrentes da mesma chave** (Kiwify reenvia até 5×; fila do site retenta): só um tem efeito, o outro responde "já processado". → Task 10, `test_retentativas_concorrentes_da_mesma_chave_so_uma_tem_efeito` (Postgres real) e Task 2, `test_corrida_perdida_no_insert_vira_none`.
4. **Token do tenant A com contato existente no tenant B** (e `tenant_id` forjado no corpo): cria contato novo em A, não toca B. → Task 10, `test_contato_de_outro_tenant_nao_e_reaproveitado`; Task 9, `test_tenant_vem_do_token_nunca_do_corpo`.
5. **Código no WhatsApp em maiúsculas, com espaços extras, sem acento ou com acento decomposto (iOS), e falso positivo** como "código pt-br": lê os primeiros, ignora o último. → Task 12, `test_le_codigo_valido` e `test_ignora_o_que_nao_e_codigo`; Task 13, `test_codigo_em_maiusculas_e_com_espacos_e_lido`.

---

## File Structure

| Arquivo | Papel |
|---|---|
| `apps/api/app/modules/machine_tokens/__init__.py` | Criado (vazio) |
| `apps/api/app/modules/machine_tokens/models.py` | Criado: `MachineToken` (global, sem RLS), `SCOPE_LEAD_INGEST`, `SCOPES` |
| `apps/api/app/modules/machine_tokens/service.py` | Criado: emitir, resolver (401 fail-closed), listar, revogar |
| `apps/api/migrations/versions/0088_machine_tokens.py` | Criado: tabela `machine_tokens` |
| `apps/api/app/modules/platform/service.py` | Modificado (≈ linha 176): exclusão de conta apaga `machine_tokens` do tenant |
| `apps/api/app/modules/lead_ingest/__init__.py` | Criado (vazio) |
| `apps/api/app/modules/lead_ingest/models.py` | Criado: `LeadIngestRecord` (RLS, única por tenant+chave) |
| `apps/api/app/modules/lead_ingest/registro.py` | Criado: `reivindicar`, `concluir`, `contato_da_chave` |
| `apps/api/migrations/versions/0089_lead_ingest_records.py` | Criado: tabela com RLS |
| `apps/api/app/modules/settings/models.py` | Modificado (após linha 52): coluna `lead_ingest_config` |
| `apps/api/migrations/versions/0090_tenant_profiles_lead_ingest_config.py` | Criado |
| `apps/api/app/modules/lead_ingest/config.py` | Criado: vocabulário de eventos, `produto`, `validar_produto`, `funil_do_evento` |
| `apps/api/app/modules/lead_ingest/schemas.py` | Criado: contrato §6.1 (`IngestIn`, `IngestOut`) |
| `apps/api/app/modules/lead_ingest/tags.py` | Criado: `somar_tags` |
| `apps/api/app/modules/crm/models.py` | Modificado (após linha 28): `TAG_LIMIT`, `TAG_MAX_LENGTH` |
| `apps/api/app/modules/crm/schemas.py` | Modificado (linhas 9, 94-100): validador de tags usa as constantes |
| `apps/api/app/modules/crm/service.py` | Modificado (linhas 229-275, 278-301, 314-386): `auto_enroll`, `find_lead` |
| `apps/api/app/modules/funnels/automation.py` | Modificado (linhas 31-105): respeita `auto_enroll`; `_ja_esta_andando` → `jornada_viva` |
| `apps/api/app/core/facts.py` | Modificado (após linha 55): 8 kinds `comercial.*` novos |
| `apps/api/app/modules/lead_ingest/service.py` | Criado: `ingest` |
| `apps/api/app/modules/lead_ingest/router.py` | Criado: rota + dependência de credencial |
| `apps/api/app/modules/__init__.py` | Modificado: registra o router |
| `apps/api/app/main.py` | Modificado: remove `PublicLeadsCORSMiddleware` (resto do PR #270) |
| `infra/docker-compose.traefik.yml` | Modificado (linhas 197-198): comentário que citava o middleware removido |
| `apps/api/app/db/registry.py` | Modificado: registra `MachineToken` e `LeadIngestRecord` |
| `apps/api/app/scripts/lead_ingest_admin.py` | Criado: CLI `emitir-token`, `listar-tokens`, `revogar-token`, `configurar`, `mostrar` |
| `apps/api/app/modules/lead_ingest/codigo.py` | Criado: `ler_codigo` (puro) |
| `apps/api/app/modules/lead_ingest/whatsapp.py` | Criado: `aplicar_codigo_da_primeira_mensagem` (não commita) |
| `apps/api/app/modules/whatsapp_inbox/service.py` | Modificado (linhas 144-165, 418-433, 492-501): `_resolve_client` + chamada do leitor |
| `apps/api/tests/lead_ingest_apoio.py` | Criado: payloads compartilhados dos testes (não coletado) |
| `apps/api/tests/test_machine_tokens.py`, `test_lead_ingest_registro.py`, `test_lead_ingest_config.py`, `test_lead_ingest_schemas.py`, `test_lead_ingest_tags.py`, `test_lead_ingest_crm_hooks.py`, `test_lead_ingest_service.py`, `test_lead_ingest_etapa_funil.py`, `test_lead_ingest_router.py`, `test_lead_ingest_rls.py`, `test_lead_ingest_admin.py`, `test_lead_ingest_codigo.py`, `test_lead_ingest_whatsapp.py` | Criados |
| `apps/api/tests/test_platform.py`, `apps/api/tests/test_tenancy_guard.py` | Modificados |
| `CLAUDE.md` | Modificado: nota da seção "Removida: a chave de API" + seção nova |
| `docs/RUNBOOK-INGESTAO-DE-LEADS.md` | Criado: emitir a credencial do tenant Nexus, configurar, testar, revogar |

**Por que dois módulos e não um.** A credencial é genérica (escopo é coluna; amanhã outro sistema pode ganhar outro escopo) e não sabe nada de lead; a ingestão é um consumidor dela. Mesma separação de `device_tokens` × `payables/receipts_router.py`.

**Por que uma tabela nova e não `device_tokens` com outro escopo.** `DeviceToken` exige `user_id` (o dono é uma pessoa), aparece na tela de celulares do usuário (`/settings/device-tokens` lista por `user_id`) e `device_tokens.resolve` devolve **403** para escopo errado (`device_tokens/service.py:44-47`) — o contrato da ingestão só conhece 401.

---

### Task 1: Credencial de máquina (`machine_tokens`)

**Files:**
- Create: `apps/api/app/modules/machine_tokens/__init__.py`
- Create: `apps/api/app/modules/machine_tokens/models.py`
- Create: `apps/api/app/modules/machine_tokens/service.py`
- Create: `apps/api/migrations/versions/0088_machine_tokens.py`
- Modify: `apps/api/app/db/registry.py:26-34` (import novo)
- Modify: `apps/api/app/modules/platform/service.py:176` (DELETE antes de `users`)
- Test: `apps/api/tests/test_machine_tokens.py`, `apps/api/tests/test_platform.py` (teste novo no fim)

**Interfaces:**
- Consumes: `app.core.security.generate_reset_token() -> tuple[str, str]`, `hash_token(raw: str) -> str`.
- Produces: `MachineToken` (`id`, `tenant_id`, `name`, `token_hash`, `scope`, `last_used_at`, `revoked_at`, `created_at`); `SCOPE_LEAD_INGEST = "lead_ingest"`; `SCOPES: frozenset[str]`; `MachineTokenError(message, status_code)`; `create_token(db, *, tenant_id: str, name: str, scope: str) -> tuple[MachineToken, str]`; `resolve(db, *, raw: str, scope: str) -> MachineToken`; `list_tokens(db, *, tenant_id: str) -> list[MachineToken]`; `revoke(db, *, token_id: str) -> MachineToken`.

- [ ] **Step 1: Escrever os testes que falham**

Criar `apps/api/tests/test_machine_tokens.py`:

```python
"""Credencial de máquina (escopo `lead_ingest`): tabela global, só hash, 401 fail-closed."""
import pytest
from sqlalchemy.orm import Session

from app.modules.device_tokens import service as device_tokens_service
from app.modules.machine_tokens import service
from app.modules.machine_tokens.models import SCOPE_LEAD_INGEST

TENANT = "tenant-nexus-0001"


def _emite(db: Session, *, tenant_id: str = TENANT, name: str = "site nexuspublica"):
    return service.create_token(db, tenant_id=tenant_id, name=name, scope=SCOPE_LEAD_INGEST)


def test_emitir_devolve_o_cru_uma_vez_e_guarda_so_o_hash(db: Session):
    token, raw = _emite(db)
    assert len(raw) > 20
    assert token.token_hash != raw
    assert raw not in token.token_hash
    assert token.scope == SCOPE_LEAD_INGEST
    assert token.tenant_id == TENANT
    assert token.revoked_at is None


def test_emitir_recusa_escopo_desconhecido(db: Session):
    with pytest.raises(service.MachineTokenError) as e:
        service.create_token(db, tenant_id=TENANT, name="x", scope="receipt_upload")
    assert e.value.status_code == 422


def test_resolver_devolve_o_tenant_e_marca_uso(db: Session):
    _, raw = _emite(db)
    achado = service.resolve(db, raw=raw, scope=SCOPE_LEAD_INGEST)
    assert achado.tenant_id == TENANT
    assert achado.last_used_at is not None


@pytest.mark.parametrize("raw", ["", "nao-existe", "Bearer qualquer"])
def test_resolver_recusa_desconhecido_com_401(db: Session, raw: str):
    with pytest.raises(service.MachineTokenError) as e:
        service.resolve(db, raw=raw, scope=SCOPE_LEAD_INGEST)
    assert e.value.status_code == 401


def test_resolver_recusa_revogado_com_401(db: Session):
    token, raw = _emite(db)
    service.revoke(db, token_id=token.id)
    with pytest.raises(service.MachineTokenError) as e:
        service.resolve(db, raw=raw, scope=SCOPE_LEAD_INGEST)
    assert e.value.status_code == 401


def test_resolver_recusa_outro_escopo_com_401_e_nao_403(db: Session):
    _, raw = _emite(db)
    with pytest.raises(service.MachineTokenError) as e:
        service.resolve(db, raw=raw, scope="outro_escopo")
    assert e.value.status_code == 401


def test_token_de_dispositivo_nao_vale_como_credencial_de_maquina(db: Session):
    _, raw = device_tokens_service.create_token(
        db, tenant_id=TENANT, user_id="u-1", name="iPhone"
    )
    with pytest.raises(service.MachineTokenError) as e:
        service.resolve(db, raw=raw, scope=SCOPE_LEAD_INGEST)
    assert e.value.status_code == 401


def test_listar_traz_so_o_tenant_pedido_inclusive_revogados(db: Session):
    revogado, _ = _emite(db, name="site antigo")
    service.revoke(db, token_id=revogado.id)
    _emite(db, name="site novo")
    _emite(db, tenant_id="outro-tenant-0002", name="de outro tenant")
    nomes = {t.name for t in service.list_tokens(db, tenant_id=TENANT)}
    assert nomes == {"site antigo", "site novo"}


def test_revogar_inexistente_da_404(db: Session):
    with pytest.raises(service.MachineTokenError) as e:
        service.revoke(db, token_id="nao-existe")
    assert e.value.status_code == 404


def test_revogar_duas_vezes_preserva_a_primeira_data(db: Session):
    token, _ = _emite(db)
    primeira = service.revoke(db, token_id=token.id).revoked_at
    assert service.revoke(db, token_id=token.id).revoked_at == primeira
```

No fim de `apps/api/tests/test_platform.py`, acrescentar:

```python
def test_delete_account_apaga_a_credencial_de_maquina_do_tenant(
    client: TestClient, admin_headers, db: Session, _tenant_session_to_test_db
):
    """`machine_tokens` é GLOBAL (não herda `TenantMixin`) e por isso escapa da purga dinâmica.

    Credencial que sobrevive ao tenant é pior que lixo: o site continuaria autenticando e a
    ingestão gravaria leads sob um `tenant_id` que não existe mais.
    """
    from app.modules.machine_tokens import service as machine_tokens_service
    from app.modules.machine_tokens.models import SCOPE_LEAD_INGEST, MachineToken

    created = client.post("/admin/accounts", json=_account_payload(), headers=admin_headers).json()
    tid = created["tenant"]["id"]
    machine_tokens_service.create_token(db, tenant_id=tid, name="site", scope=SCOPE_LEAD_INGEST)

    assert client.delete(f"/admin/accounts/{tid}", headers=admin_headers).status_code == 204
    assert db.query(MachineToken).filter(MachineToken.tenant_id == tid).count() == 0
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd F:/Projetos/e1p/_wt-ingest-atribuicao/apps/api && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m pytest tests/test_machine_tokens.py tests/test_platform.py -k "machine or maquina" -v`
Expected: erro de coleta `ModuleNotFoundError: No module named 'app.modules.machine_tokens'`.

- [ ] **Step 3: Implementar o módulo**

Criar `apps/api/app/modules/machine_tokens/__init__.py` vazio.

Criar `apps/api/app/modules/machine_tokens/models.py`:

```python
"""Credencial de máquina: token com escopo, emitido para um TENANT (não para uma pessoa).

Irmã de `device_tokens` — hash sha256, escopo travado, revogação —, com uma diferença de
propósito: o dono de um `DeviceToken` é uma PESSOA (o Atalho do iOS dela); o dono de um
`MachineToken` é um SISTEMA que fala com o e1p servidor-a-servidor. Hoje, o site que empurra
leads (`POST /public/ingest/leads`). Por isso não há `user_id`.

Reconstrói, com escopo e contrato novos, a capacidade que o PR #270 removeu (chave de API de
"Integrações", migração 0083) — o caso "site headless que não embute iframe" que a própria nota
de remoção deixou previsto.

Tabela GLOBAL (sem `TenantMixin`, sem RLS) pela mesma razão de `device_tokens` e `users`: o
tenant é resolvido A PARTIR do token, antes de existir uma `tenant_session`. Guarda só hash e
metadado de credencial — nenhum dado de negócio. Quem a lê: a dependência de autenticação de
`lead_ingest/router.py` e o script `app/scripts/lead_ingest_admin.py`. Nenhum módulo de negócio.

⚠️ Por ser global, a purga dinâmica de `platform.delete_account` (que varre subclasses de
`TenantMixin`) NÃO a alcança — o DELETE explícito mora lá.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, _uuid

# Autoriza SOMENTE `POST /public/ingest/leads`: uma escrita que não devolve nenhum dado do
# tenant. O pior caso de um vazamento é alguém criar leads falsos — visíveis e apagáveis.
SCOPE_LEAD_INGEST = "lead_ingest"
SCOPES = frozenset({SCOPE_LEAD_INGEST})


class MachineToken(Base, TimestampMixin):
    __tablename__ = "machine_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # Coluna de RESOLUÇÃO, não de controle de acesso (a tabela é global).
    tenant_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    # sha256 do token cru. O cru NUNCA é persistido.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

Criar `apps/api/app/modules/machine_tokens/service.py`:

```python
"""Ciclo de vida da credencial de máquina: emitir, resolver, listar, revogar."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import generate_reset_token, hash_token
from app.modules.machine_tokens.models import SCOPES, MachineToken


class MachineTokenError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def create_token(
    db: Session, *, tenant_id: str, name: str, scope: str
) -> tuple[MachineToken, str]:
    """Emite e devolve `(linha, token_cru)`. O cru é mostrado UMA vez e nunca mais."""
    if scope not in SCOPES:
        raise MachineTokenError(f"Escopo desconhecido: {scope}", 422)
    raw, hashed = generate_reset_token()  # mesmo par sha256 do reset de senha e do Atalho
    token = MachineToken(
        tenant_id=tenant_id, name=name.strip() or "Integração", token_hash=hashed, scope=scope
    )
    db.add(token)
    db.commit()
    db.refresh(token)
    return token, raw


def resolve(db: Session, *, raw: str, scope: str) -> MachineToken:
    """Resolve o token cru. Desconhecido, revogado ou de outro escopo → 401, sem distinguir.

    Diferente de `device_tokens.resolve`, que separa 401 de 403: o contrato da ingestão
    (spec §6.1) só conhece 401 para credencial, e dizer a quem não se autenticou que "o token
    existe, só não serve aqui" é informação de graça para quem testa um token vazado.

    Marca `last_used_at` para quem administra enxergar credencial abandonada.
    """
    token = db.scalar(select(MachineToken).where(MachineToken.token_hash == hash_token(raw)))
    if token is None or token.revoked_at is not None or token.scope != scope:
        raise MachineTokenError("Credencial inválida", 401)
    token.last_used_at = datetime.now(UTC)
    db.commit()
    return token


def list_tokens(db: Session, *, tenant_id: str) -> list[MachineToken]:
    """Ativas E revogadas, mais nova primeiro — é a visão de quem administra, não de quem usa.

    Filtro explícito por `tenant_id`: a tabela é global (sem RLS), mesma exceção documentada
    de `users` na Regra de Ouro nº 1.
    """
    stmt = (
        select(MachineToken)
        .where(MachineToken.tenant_id == tenant_id)
        .order_by(MachineToken.created_at.desc(), MachineToken.id.desc())
    )
    return list(db.scalars(stmt).all())


def revoke(db: Session, *, token_id: str) -> MachineToken:
    """Revoga. Revogar de novo não reescreve a data: ela é a evidência de QUANDO parou."""
    token = db.get(MachineToken, token_id)
    if token is None:
        raise MachineTokenError("Credencial não encontrada", 404)
    if token.revoked_at is None:
        token.revoked_at = datetime.now(UTC)
        db.commit()
    return token
```

Em `apps/api/app/db/registry.py`, depois de `from app.modules.juridico.models import LegalDocument  # noqa: F401`, acrescentar:

```python
from app.modules.machine_tokens.models import MachineToken  # noqa: F401
```

Em `apps/api/app/modules/platform/service.py`, dentro do `with tenant_session(tenant_id) as tdb:` de `delete_account`, imediatamente ANTES de `tdb.execute(text("DELETE FROM users WHERE tenant_id = :tid"), {"tid": tenant_id})`, inserir:

```python
        # `machine_tokens` é GLOBAL (não herda TenantMixin) e escapa do laço acima. Credencial
        # que sobrevive ao tenant continuaria autenticando o site e gravando leads sob um
        # `tenant_id` que não existe mais. Tabela sem RLS: o filtro explícito é obrigatório.
        tdb.execute(text("DELETE FROM machine_tokens WHERE tenant_id = :tid"), {"tid": tenant_id})
```

Criar `apps/api/migrations/versions/0088_machine_tokens.py`:

```python
"""machine_tokens: credencial de máquina com escopo, por tenant (ingestão de leads)

Revision ID: 0088
Revises: 0087
Create Date: 2026-09-30

Reconstrói, com escopo e contrato novos, a capacidade que a 0083 removeu (chave de API de
"Integrações", PR #270): o caso que a própria nota de remoção previu — site headless que não
embute iframe — apareceu (site da Nexus Pública → `POST /public/ingest/leads`).

Tabela GLOBAL, deliberadamente SEM RLS, pela mesma razão de `device_tokens` (0057): o tenant é
resolvido A PARTIR do token, antes de existir `tenant_session`. Guarda só hash sha256 e
metadado. DDL puro, sem UPDATE.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0088"
down_revision: str | None = "0087"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "machine_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_machine_tokens_tenant_id", "machine_tokens", ["tenant_id"])
    # Único: é o caminho quente de toda requisição, e dois tokens com o mesmo hash seriam
    # a mesma credencial com dois donos.
    op.create_index("ix_machine_tokens_token_hash", "machine_tokens", ["token_hash"], unique=True)


def downgrade() -> None:
    op.drop_table("machine_tokens")
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd F:/Projetos/e1p/_wt-ingest-atribuicao/apps/api && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m pytest tests/test_machine_tokens.py tests/test_platform.py tests/test_device_tokens.py -v`
Expected: todos PASS (12 novos em `test_machine_tokens.py` + o novo de `test_platform.py`; os antigos seguem verdes).

Run: `cd F:/Projetos/e1p/_wt-ingest-atribuicao/apps/api && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m alembic heads`
Expected: `0088 (head)`.

Run: `cd F:/Projetos/e1p/_wt-ingest-atribuicao/apps/api && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m ruff check . --fix && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m ruff check .`
Expected: `All checks passed!`

- [ ] **Step 5: Commit**

```bash
cd F:/Projetos/e1p/_wt-ingest-atribuicao && git add apps/api/app/modules/machine_tokens apps/api/migrations/versions/0088_machine_tokens.py apps/api/app/db/registry.py apps/api/app/modules/platform/service.py apps/api/tests/test_machine_tokens.py apps/api/tests/test_platform.py && git commit -m "feat(machine-tokens): credencial de máquina com escopo lead_ingest, global e só com hash" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Registro de idempotência (`lead_ingest_records`)

**Files:**
- Create: `apps/api/app/modules/lead_ingest/__init__.py`
- Create: `apps/api/app/modules/lead_ingest/models.py`
- Create: `apps/api/app/modules/lead_ingest/registro.py`
- Create: `apps/api/migrations/versions/0089_lead_ingest_records.py`
- Modify: `apps/api/app/db/registry.py` (import novo, depois de `juridico`)
- Test: `apps/api/tests/test_lead_ingest_registro.py`

**Interfaces:**
- Consumes: `Client` (`app.modules.crm.models`) como alvo da FK.
- Produces: `LeadIngestRecord` (`id`, `tenant_id`, `chave_idempotencia`, `evento`, `ocorrido_em`, `payload: dict`, `client_id: str | None`, `tags_descartadas: list[str]`, `concluido_em: datetime | None`); `registro._buscar(db, *, chave: str) -> LeadIngestRecord | None`; `registro.reivindicar(db, *, tenant_id: str, chave: str, evento: str, ocorrido_em: datetime, payload: dict) -> LeadIngestRecord | None`; `registro.concluir(registro: LeadIngestRecord, *, client_id: str, tags_descartadas: list[str]) -> None`; `registro.contato_da_chave(db, *, chave: str) -> str | None`.

- [ ] **Step 1: Escrever os testes que falham**

Criar `apps/api/tests/test_lead_ingest_registro.py`:

```python
"""Reivindicação de chave de idempotência da ingestão (spec §6.2)."""
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.crm.models import Client
from app.modules.lead_ingest import registro
from app.modules.lead_ingest.models import LeadIngestRecord

TENANT = "tenant-nexus-0001"
CHAVE = "kiwify:ord_123:compra_aprovada"
QUANDO = datetime(2026, 10, 2, 17, 31, tzinfo=UTC)


def _reivindica(db: Session, chave: str = CHAVE):
    return registro.reivindicar(
        db, tenant_id=TENANT, chave=chave, evento="compra_aprovada", ocorrido_em=QUANDO,
        payload={"evento": "compra_aprovada"},
    )


def _contato(db: Session) -> Client:
    contato = Client(tenant_id=TENANT, name="Maria", source="api")
    db.add(contato)
    db.commit()
    return contato


def test_chave_nova_e_reivindicada_com_id_e_sem_conclusao(db: Session):
    linha = _reivindica(db)
    assert linha is not None and linha.id
    assert linha.concluido_em is None
    assert linha.payload == {"evento": "compra_aprovada"}


def test_chave_concluida_nao_e_reivindicada_de_novo(db: Session):
    contato = _contato(db)
    linha = _reivindica(db)
    registro.concluir(linha, client_id=contato.id, tags_descartadas=["x" * 41])
    db.commit()
    assert _reivindica(db) is None
    assert registro.contato_da_chave(db, chave=CHAVE) == contato.id
    assert db.scalar(select(LeadIngestRecord)).tags_descartadas == ["x" * 41]


def test_chave_reivindicada_e_nao_concluida_e_retomada(db: Session):
    """Queda entre os dois commits do serviço: a próxima tentativa retoma, não vira no-op."""
    primeira = _reivindica(db)
    db.commit()
    retomada = _reivindica(db)
    assert retomada is not None
    assert retomada.id == primeira.id
    assert db.scalar(select(func.count(LeadIngestRecord.id))) == 1


def test_chaves_diferentes_convivem(db: Session):
    assert _reivindica(db, "kiwify:a:compra_aprovada") is not None
    assert _reivindica(db, "kiwify:b:compra_aprovada") is not None
    assert db.scalar(select(func.count(LeadIngestRecord.id))) == 2


def test_corrida_perdida_no_insert_vira_none(db: Session, monkeypatch):
    """No Postgres, o INSERT de quem chegou depois espera no índice único e então falha.

    Aqui forçamos o mesmo caminho: a busca "não vê" a linha que já existe, o INSERT bate na
    restrição única, e quem perdeu responde "já processado" em vez de estourar 500.
    """
    _reivindica(db)
    db.commit()
    monkeypatch.setattr(registro, "_buscar", lambda _db, *, chave: None)
    assert _reivindica(db) is None


def test_contato_da_chave_desconhecida_e_none(db: Session):
    assert registro.contato_da_chave(db, chave="nunca-vista") is None


def test_restricao_unica_por_tenant_e_chave_esta_no_modelo():
    nomes = {c.name for c in LeadIngestRecord.__table__.constraints}
    assert "uq_lead_ingest_tenant_chave" in nomes
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd F:/Projetos/e1p/_wt-ingest-atribuicao/apps/api && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m pytest tests/test_lead_ingest_registro.py -v`
Expected: erro de coleta `ModuleNotFoundError: No module named 'app.modules.lead_ingest'`.

- [ ] **Step 3: Implementar**

Criar `apps/api/app/modules/lead_ingest/__init__.py` vazio.

Criar `apps/api/app/modules/lead_ingest/models.py`:

```python
"""Registro de idempotência da ingestão de leads (`POST /public/ingest/leads`).

Uma linha por `(tenant_id, chave_idempotencia)`, com restrição ÚNICA no banco (spec §6.2): a
Kiwify reenvia o mesmo webhook até 5 vezes e o site tem fila com nova tentativa — a mesma venda
VAI chegar mais de uma vez, e só a primeira pode ter efeito.

Tabela de NEGÓCIO (RLS). `payload` é o registro BRUTO da entrada (o mesmo papel de
`kiwify_eventos` no site), com contato e valores. É o único lugar do e1p onde o valor do pedido
fica, e é de propósito: `facts` não guarda dinheiro (invariante 2 de `core/facts.py`) e não
existe entidade de pedido no e1p (spec §10). `client_id` com CASCADE: apagar o contato (LGPD)
leva junto o payload que tem o e-mail e o telefone dele.

`concluido_em` separa "reivindicada" de "processada". `crm.absorb_lead` commita no meio do
caminho, então a reivindicação entra no MESMO commit do contato e tags + fato + etapa entram no
seguinte. Se o processo cair entre os dois, a linha fica sem `concluido_em` e a PRÓXIMA tentativa
retoma em vez de responder "já processado" — sem isso, uma queda no meio viraria venda sem tag e
sem Ganho, confirmada como sucesso para quem reenviou.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantMixin, TimestampMixin, _uuid


class LeadIngestRecord(Base, TenantMixin, TimestampMixin):
    __tablename__ = "lead_ingest_records"
    __table_args__ = (
        UniqueConstraint("tenant_id", "chave_idempotencia", name="uq_lead_ingest_tenant_chave"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    chave_idempotencia: Mapped[str] = mapped_column(String(200), nullable=False)
    evento: Mapped[str] = mapped_column(String(32), nullable=False)
    # Quando ACONTECEU (a venda, o abandono), não quando chegou aqui.
    ocorrido_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    client_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("clients.id", ondelete="CASCADE"), nullable=True, index=True
    )
    tags_descartadas: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    concluido_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

Criar `apps/api/app/modules/lead_ingest/registro.py`:

```python
"""Reivindicar e concluir uma chave de idempotência (ver `models.LeadIngestRecord`)."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.lead_ingest.models import LeadIngestRecord


def _buscar(db: Session, *, chave: str) -> LeadIngestRecord | None:
    # Sem filtro de tenant: a sessão já vem RLS-escopada (Regra de Ouro nº 1).
    return db.scalar(
        select(LeadIngestRecord).where(LeadIngestRecord.chave_idempotencia == chave)
    )


def reivindicar(
    db: Session,
    *,
    tenant_id: str,
    chave: str,
    evento: str,
    ocorrido_em: datetime,
    payload: dict,
) -> LeadIngestRecord | None:
    """Devolve a linha a processar, ou `None` se a chave já foi (ou está sendo) processada.

    Linha existente SEM `concluido_em` é devolvida para retomada (ver a docstring do modelo).
    **NÃO commita**: a reivindicação só fica visível para as outras requisições junto com o
    primeiro commit de quem chamou.
    """
    existente = _buscar(db, chave=chave)
    if existente is not None:
        return None if existente.concluido_em is not None else existente
    novo = LeadIngestRecord(
        tenant_id=tenant_id, chave_idempotencia=chave, evento=evento,
        ocorrido_em=ocorrido_em, payload=payload,
    )
    db.add(novo)
    try:
        db.flush()
    except IntegrityError:
        # Outra requisição com a MESMA chave inseriu primeiro. No Postgres, este flush ficou
        # parado no índice único até ela commitar — e então falhou. Quem chegou depois não
        # tem efeito nenhum: responde "já processado".
        db.rollback()
        return None
    return novo


def concluir(
    registro: LeadIngestRecord, *, client_id: str, tags_descartadas: list[str]
) -> None:
    """Marca como processada. **NÃO commita**: entra no commit das tags, do fato e da etapa."""
    registro.client_id = client_id
    registro.tags_descartadas = list(tags_descartadas)
    registro.concluido_em = datetime.now(UTC)


def contato_da_chave(db: Session, *, chave: str) -> str | None:
    existente = _buscar(db, chave=chave)
    return existente.client_id if existente is not None else None
```

Em `apps/api/app/db/registry.py`, depois de `from app.modules.juridico.models import LegalDocument  # noqa: F401`, acrescentar:

```python
from app.modules.lead_ingest.models import LeadIngestRecord  # noqa: F401
```

Criar `apps/api/migrations/versions/0089_lead_ingest_records.py`:

```python
"""lead_ingest_records: idempotência da ingestão de leads, única por (tenant, chave)

Revision ID: 0089
Revises: 0088
Create Date: 2026-09-30

Tabela de NEGÓCIO com RLS (mesma policy `tenant_isolation` de todas): guarda o payload bruto,
com contato e valores. A restrição única `(tenant_id, chave_idempotencia)` é a idempotência —
no banco, não em código: dois reenvios simultâneos da Kiwify serializam no índice e o segundo
falha, em vez de os dois passarem pela checagem antes de qualquer um gravar.

DDL puro, sem UPDATE (a armadilha das 0046/0066/0067/0068/0069/0073 não se aplica).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0089"
down_revision: str | None = "0088"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "lead_ingest_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
        sa.Column("chave_idempotencia", sa.String(200), nullable=False),
        sa.Column("evento", sa.String(32), nullable=False),
        sa.Column("ocorrido_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "client_id",
            sa.String(36),
            sa.ForeignKey("clients.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
        sa.Column("tags_descartadas", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("concluido_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "tenant_id", "chave_idempotencia", name="uq_lead_ingest_tenant_chave"
        ),
    )
    op.execute("ALTER TABLE lead_ingest_records ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE lead_ingest_records FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON lead_ingest_records
            USING (tenant_id = current_setting('app.current_tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true))
        """
    )


def downgrade() -> None:
    op.drop_table("lead_ingest_records")
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd F:/Projetos/e1p/_wt-ingest-atribuicao/apps/api && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m pytest tests/test_lead_ingest_registro.py -v`
Expected: 7 PASS.

Run: `cd F:/Projetos/e1p/_wt-ingest-atribuicao/apps/api && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m alembic heads && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m ruff check . --fix && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m ruff check .`
Expected: `0089 (head)` e `All checks passed!`

- [ ] **Step 5: Commit**

```bash
cd F:/Projetos/e1p/_wt-ingest-atribuicao && git add apps/api/app/modules/lead_ingest apps/api/migrations/versions/0089_lead_ingest_records.py apps/api/app/db/registry.py apps/api/tests/test_lead_ingest_registro.py && git commit -m "feat(lead-ingest): registro de idempotência único por tenant e chave, com retomada" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Configuração por tenant (produto e funil por evento)

**Files:**
- Modify: `apps/api/app/modules/settings/models.py:52` (coluna nova logo abaixo de `default_entry_funnel_id`)
- Create: `apps/api/migrations/versions/0090_tenant_profiles_lead_ingest_config.py`
- Create: `apps/api/app/modules/lead_ingest/config.py`
- Test: `apps/api/tests/test_lead_ingest_config.py`

**Interfaces:**
- Consumes: `TenantProfile.default_entry_funnel_id` (já existe).
- Produces: `TenantProfile.lead_ingest_config: dict` (`{"produto": str, "funis": {evento: funnel_id}}`); `config.EVENTOS: tuple[str, ...]`; `config.EVENTOS_DE_ENTRADA: frozenset[str]`; `config.produto(perfil: TenantProfile) -> str | None`; `config.validar_produto(valor: str) -> str` (levanta `ValueError`); `config.funil_do_evento(perfil: TenantProfile, evento: str) -> str | None`.

- [ ] **Step 1: Escrever os testes que falham**

Criar `apps/api/tests/test_lead_ingest_config.py`:

```python
"""Configuração da ingestão por tenant: produto (prefixo de tag) e funil por evento."""
import pytest

from app.modules.lead_ingest import config
from app.modules.settings.models import TenantProfile


def _perfil(cfg: dict | None = None, padrao: str | None = None) -> TenantProfile:
    return TenantProfile(
        tenant_id="t-1", lead_ingest_config={} if cfg is None else cfg,
        default_entry_funnel_id=padrao,
    )


def test_produto_configurado():
    assert config.produto(_perfil({"produto": "publia"})) == "publia"


@pytest.mark.parametrize("valor", [None, "", "Publ.IA", "publia com espaço", "x" * 21, 7])
def test_produto_invalido_ou_ausente_e_none(valor):
    assert config.produto(_perfil({"produto": valor})) is None


def test_sem_configuracao_nenhuma_nao_ha_produto():
    assert config.produto(_perfil()) is None


def test_validar_produto_normaliza_e_recusa():
    assert config.validar_produto("  PublIA ") == "publia"
    with pytest.raises(ValueError):
        config.validar_produto("Publ.IA")


def test_evento_mapeado_usa_o_funil_do_evento():
    perfil = _perfil({"funis": {"carrinho_abandonado": "f-recuperacao"}}, padrao="f-padrao")
    assert config.funil_do_evento(perfil, "carrinho_abandonado") == "f-recuperacao"


@pytest.mark.parametrize("evento", ["lead", "carrinho_abandonado", "compra_aprovada"])
def test_evento_de_entrada_sem_mapeamento_cai_no_padrao(evento):
    assert config.funil_do_evento(_perfil(padrao="f-padrao"), evento) == "f-padrao"


@pytest.mark.parametrize("evento", ["renovacao", "reembolso", "chargeback", "cancelamento"])
def test_pos_venda_sem_mapeamento_nao_cai_no_padrao(evento):
    """Reembolso não pode reinscrever o cliente no funil de boas-vindas."""
    assert config.funil_do_evento(_perfil(padrao="f-padrao"), evento) is None


def test_pos_venda_mapeado_explicitamente_vale():
    perfil = _perfil({"funis": {"cancelamento": "f-retencao"}}, padrao="f-padrao")
    assert config.funil_do_evento(perfil, "cancelamento") == "f-retencao"


@pytest.mark.parametrize("funis", [{"lead": ""}, {"lead": None}, "lixo", ["lead"]])
def test_mapeamento_vazio_ou_malformado_cai_no_padrao(funis):
    assert config.funil_do_evento(_perfil({"funis": funis}, padrao="f-padrao"), "lead") == (
        "f-padrao"
    )
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd F:/Projetos/e1p/_wt-ingest-atribuicao/apps/api && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m pytest tests/test_lead_ingest_config.py -v`
Expected: erro de coleta `ImportError: cannot import name 'config' from 'app.modules.lead_ingest'`.

- [ ] **Step 3: Implementar**

Em `apps/api/app/modules/settings/models.py`, logo depois da linha `default_entry_funnel_id: Mapped[str | None] = mapped_column(String(36), nullable=True)`, acrescentar:

```python

    # Ingestão de leads com atribuição (`POST /public/ingest/leads`, módulo `lead_ingest`):
    # `{"produto": "<slug>", "funis": {"<evento>": "<funnel_id>"}}`. `{}` = sem tag de produto,
    # sem leitura de código no WhatsApp e sem funil por evento (cai no funil padrão acima).
    # Sem tela: quem escreve é `app/scripts/lead_ingest_admin.py`. Ver `lead_ingest/config.py`.
    lead_ingest_config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
```

Criar `apps/api/migrations/versions/0090_tenant_profiles_lead_ingest_config.py`:

```python
"""tenant_profiles.lead_ingest_config: produto e funil por evento da ingestão de leads

Revision ID: 0090
Revises: 0089
Create Date: 2026-09-30

`{}` = o comportamento de um tenant que nunca configurou nada. O `server_default` é o que
preenche as linhas existentes, como DDL: um `UPDATE` aqui rodaria sob FORCE RLS sem
`app.current_tenant_id`, seria filtrado a zero linhas e "passaria" em silêncio.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0090"
down_revision: str | None = "0089"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tenant_profiles",
        sa.Column("lead_ingest_config", sa.JSON(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("tenant_profiles", "lead_ingest_config")
```

Criar `apps/api/app/modules/lead_ingest/config.py`:

```python
"""Configuração da ingestão por tenant: `tenant_profiles.lead_ingest_config` (JSON).

Formato: `{"produto": "publia", "funis": {"lead": "<funnel_id>", ...}}`.

**Por que `produto` é configuração, e não `"publia"` no código.** A spec (§6.2/§6.3) fala em
`publia:reembolso`, `publia:cancelou`, `publia:lead-whatsapp` — tags do tenant Nexus. O e1p é
multi-tenant: cravar o produto de um cliente no núcleo faria toda empresa do produto receber
tag de outra. O prefixo vira dado do tenant; sem ele, essas tags simplesmente não existem.

**Por que o funil padrão NÃO vale para pós-venda.** "Sem mapeamento, vale o comportamento atual
(`default_entry_funnel_id`)" (spec §6.4) é sobre quem ENTRA: lead, carrinho, compra. Aplicar ao pé
da letra a renovação, reembolso, chargeback e cancelamento poria quem pediu o dinheiro de volta
na jornada de boas-vindas. Pós-venda só entra em funil se o dono mapear explicitamente.
"""
from __future__ import annotations

import re

from app.modules.settings.models import TenantProfile

EVENTOS = (
    "lead",
    "carrinho_abandonado",
    "compra_aprovada",
    "renovacao",
    "reembolso",
    "chargeback",
    "cancelamento",
)
EVENTOS_DE_ENTRADA = frozenset({"lead", "carrinho_abandonado", "compra_aprovada"})

# Cabe em `<produto>:lead-whatsapp` dentro dos 40 caracteres de tag do CRM.
_PRODUTO_VALIDO = re.compile(r"^[a-z0-9][a-z0-9-]{0,19}$")


def _config(perfil: TenantProfile) -> dict:
    valor = perfil.lead_ingest_config
    return valor if isinstance(valor, dict) else {}


def produto(perfil: TenantProfile) -> str | None:
    """O slug do produto, ou `None` (tag de produto e leitura de código desligadas)."""
    valor = _config(perfil).get("produto")
    if isinstance(valor, str) and _PRODUTO_VALIDO.match(valor):
        return valor
    return None


def validar_produto(valor: str) -> str:
    limpo = valor.strip().lower()
    if not _PRODUTO_VALIDO.match(limpo):
        raise ValueError(
            "produto deve ter de 1 a 20 caracteres: letras minúsculas, dígitos e hífen "
            "(ex.: publia)"
        )
    return limpo


def funil_do_evento(perfil: TenantProfile, evento: str) -> str | None:
    funis = _config(perfil).get("funis")
    mapeado = funis.get(evento) if isinstance(funis, dict) else None
    if isinstance(mapeado, str) and mapeado:
        return mapeado
    if evento in EVENTOS_DE_ENTRADA:
        return perfil.default_entry_funnel_id
    return None
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd F:/Projetos/e1p/_wt-ingest-atribuicao/apps/api && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m pytest tests/test_lead_ingest_config.py tests/test_settings.py -v`
Expected: todos PASS.

Run: `cd F:/Projetos/e1p/_wt-ingest-atribuicao/apps/api && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m alembic heads && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m ruff check . --fix && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m ruff check .`
Expected: `0090 (head)` e `All checks passed!`

- [ ] **Step 5: Commit**

```bash
cd F:/Projetos/e1p/_wt-ingest-atribuicao && git add apps/api/app/modules/settings/models.py apps/api/migrations/versions/0090_tenant_profiles_lead_ingest_config.py apps/api/app/modules/lead_ingest/config.py apps/api/tests/test_lead_ingest_config.py && git commit -m "feat(lead-ingest): produto e funil por evento configuráveis por tenant" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Contrato da ingestão (schemas do §6.1)

**Files:**
- Create: `apps/api/app/modules/lead_ingest/schemas.py`
- Create: `apps/api/tests/lead_ingest_apoio.py`
- Test: `apps/api/tests/test_lead_ingest_schemas.py`

**Interfaces:**
- Consumes: `config.EVENTOS` (Task 3).
- Produces: `Evento` (Literal), `Situacao` (Literal), `Contato(nome: str | None, email: str | None, telefone: str | None)`, `Toque` (extra permitido), `Atribuicao(situacao, primeiro_toque: Toque | None, ultimo_toque: Toque | None)`, `Pedido` (extra permitido), `IngestIn(evento, chave_idempotencia, ocorrido_em: AwareDatetime, contato, tags: list[str], atribuicao, pedido: Pedido | None)`, `IngestOut(resultado: Literal["processado", "ja_processado"], contato_id: str | None)`. Em `tests/lead_ingest_apoio.py`: `TENANT`, `EXEMPLO_DA_SPEC`, `LEAD`, `corpo(**sobre) -> dict`, `payload(**sobre) -> IngestIn`.

- [ ] **Step 1: Escrever o apoio e os testes que falham**

Criar `apps/api/tests/lead_ingest_apoio.py`:

```python
"""Apoio compartilhado dos testes da ingestão de leads.

Não é coletado pelo pytest (não começa com `test_`). Importe com
`from tests.lead_ingest_apoio import ...`, como `test_fuso_do_processo.py` faz com o conftest.
"""
from __future__ import annotations

import copy
from typing import Any

from app.modules.lead_ingest.schemas import IngestIn

TENANT = "tenant-nexus-0001"

TOQUE: dict[str, Any] = {
    "utm_source": "instagram",
    "utm_medium": "organic_social",
    "utm_campaign": "publia-lanc-out26",
    "utm_content": "ig-r-c8abc",
    "utm_term": None,
    "gclid": None,
    "fbclid": "fb.1.abc",
    "landing_path": "/publia-vender",
    "referrer_host": "l.instagram.com",
    "ocorrido_em": "2026-09-30T10:00:00-03:00",
}

# O JSON do §6.1, com valores concretos no lugar das reticências.
EXEMPLO_DA_SPEC: dict[str, Any] = {
    "evento": "compra_aprovada",
    "chave_idempotencia": "kiwify:ord_123:compra_aprovada",
    "ocorrido_em": "2026-10-02T14:31:00-03:00",
    "contato": {
        "nome": "Maria Prefeitura",
        "email": "maria@exemplo.gov.br",
        "telefone": "(11) 99999-8888",
    },
    "tags": [
        "origem:instagram",
        "meio:organico",
        "campanha:publia-lanc-out26",
        "post:ig-r-c8abc",
        "publia:comprou-essencial-anual",
    ],
    "atribuicao": {"situacao": "resolvida", "primeiro_toque": TOQUE, "ultimo_toque": TOQUE},
    "pedido": {
        "provedor": "kiwify",
        "order_id": "ord_123",
        "plano": "essencial",
        "periodo": "anual",
        "valor_bruto_centavos": 49900,
        "valor_liquido_centavos": 44300,
    },
}

LEAD: dict[str, Any] = {
    "evento": "lead",
    "chave_idempotencia": "site:lead:1",
    "ocorrido_em": "2026-10-02T14:31:00-03:00",
    "contato": {
        "nome": "Maria Prefeitura",
        "email": "maria@exemplo.gov.br",
        "telefone": "(11) 99999-8888",
    },
    "tags": ["origem:instagram", "post:ig-r-c8abc"],
    "atribuicao": {
        "situacao": "resolvida",
        "ultimo_toque": {"utm_source": "instagram", "utm_content": "ig-r-c8abc"},
    },
}


def corpo(**sobre: Any) -> dict[str, Any]:
    """O JSON de um `lead`, com os campos de `sobre` substituídos."""
    base = copy.deepcopy(LEAD)
    base.update(sobre)
    return base


def payload(**sobre: Any) -> IngestIn:
    return IngestIn.model_validate(corpo(**sobre))
```

Criar `apps/api/tests/test_lead_ingest_schemas.py`:

```python
"""O contrato do §6.1: o que passa, o que vira 422, e o que é tolerado de propósito."""
import copy
from datetime import timedelta
from typing import get_args

import pytest
from pydantic import ValidationError

from app.modules.lead_ingest import config
from app.modules.lead_ingest.schemas import Evento, IngestIn
from tests.lead_ingest_apoio import EXEMPLO_DA_SPEC, corpo


def test_exemplo_da_spec_valida_e_preserva_o_fuso():
    dados = IngestIn.model_validate(EXEMPLO_DA_SPEC)
    assert dados.evento == "compra_aprovada"
    assert dados.ocorrido_em.utcoffset() == timedelta(hours=-3)
    assert dados.pedido is not None and dados.pedido.valor_bruto_centavos == 49900
    assert dados.atribuicao.ultimo_toque is not None
    assert dados.atribuicao.ultimo_toque.utm_content == "ig-r-c8abc"


def test_vocabulario_de_eventos_e_um_so():
    assert set(get_args(Evento)) == set(config.EVENTOS)


def test_contato_sem_email_e_sem_telefone_e_recusado():
    with pytest.raises(ValidationError, match="e-mail ou telefone"):
        IngestIn.model_validate(corpo(contato={"nome": "Sem Canal"}))


def test_string_vazia_vale_como_ausente_e_nao_como_email_invalido():
    dados = IngestIn.model_validate(
        corpo(contato={"nome": "Ana", "email": "", "telefone": "(11) 98888-7777"})
    )
    assert dados.contato.email is None
    assert dados.contato.telefone == "(11) 98888-7777"


def test_email_invalido_e_recusado():
    with pytest.raises(ValidationError):
        IngestIn.model_validate(corpo(contato={"email": "nao-e-email"}))


def test_evento_desconhecido_e_recusado():
    with pytest.raises(ValidationError):
        IngestIn.model_validate(corpo(evento="compra"))


def test_ocorrido_em_sem_fuso_e_recusado():
    with pytest.raises(ValidationError):
        IngestIn.model_validate(corpo(ocorrido_em="2026-10-02T14:31:00"))


def test_chave_so_de_espacos_e_recusada():
    with pytest.raises(ValidationError):
        IngestIn.model_validate(corpo(chave_idempotencia="   "))


def test_sessenta_tags_passam_no_contrato_mas_cento_e_uma_nao():
    """O limite de 50 é do CONTATO e vira descarte registrado, não 422 (spec §6.2).

    100 é só teto anti-abuso do corpo da requisição.
    """
    assert len(IngestIn.model_validate(corpo(tags=[f"t:{i}" for i in range(60)])).tags) == 60
    with pytest.raises(ValidationError):
        IngestIn.model_validate(corpo(tags=[f"t:{i}" for i in range(101)]))


def test_toque_aceita_click_id_que_o_contrato_nao_lista():
    """O site captura gbraid/wbraid (spec §5.1), o contrato só lista gclid/fbclid."""
    exemplo = copy.deepcopy(EXEMPLO_DA_SPEC)
    exemplo["atribuicao"]["ultimo_toque"]["gbraid"] = "gb-1"
    dados = IngestIn.model_validate(exemplo)
    assert dados.atribuicao.model_dump(mode="json")["ultimo_toque"]["gbraid"] == "gb-1"


def test_sem_origem_aceita_toques_nulos_e_pedido_ausente():
    dados = IngestIn.model_validate(
        corpo(atribuicao={"situacao": "sem_origem", "primeiro_toque": None, "ultimo_toque": None})
    )
    assert dados.atribuicao.primeiro_toque is None
    assert dados.pedido is None


def test_tenant_id_no_corpo_e_ignorado():
    dados = IngestIn.model_validate(corpo(tenant_id="outro-tenant"))
    assert "tenant_id" not in dados.model_dump()
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd F:/Projetos/e1p/_wt-ingest-atribuicao/apps/api && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m pytest tests/test_lead_ingest_schemas.py -v`
Expected: erro de coleta `ModuleNotFoundError: No module named 'app.modules.lead_ingest.schemas'`.

- [ ] **Step 3: Implementar**

Criar `apps/api/app/modules/lead_ingest/schemas.py`:

```python
"""Contrato de `POST /public/ingest/leads` — spec §6.1, CONGELADO.

O site codifica contra este formato EM PARALELO: renomear campo, evento ou código de status aqui
quebra o outro lado sem nenhum teste deste repositório ficar vermelho. Mudança de contrato é
mudança de spec primeiro.

O que é tolerado de propósito, para que uma variação inofensiva do site não vire 422 — e 422 é
erro PERMANENTE para a fila do site, que desiste de reenviar:
- `""` em nome/e-mail/telefone vale como ausente;
- `Toque` e `Pedido` aceitam campos extras (o site captura `gbraid`/`wbraid`, spec §5.1, e o
  contrato só lista `gclid`/`fbclid`);
- campos desconhecidos na raiz (inclusive um `tenant_id`) são IGNORADOS — o tenant vem do token.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)

Evento = Literal[
    "lead",
    "carrinho_abandonado",
    "compra_aprovada",
    "renovacao",
    "reembolso",
    "chargeback",
    "cancelamento",
]
Situacao = Literal["resolvida", "apenas_kiwify", "sem_origem"]

# Teto anti-abuso do corpo. Os limites do CONTATO (50 tags de 40 caracteres) são aplicados na
# soma, com descarte registrado — ver `lead_ingest/tags.py`.
TagIn = Annotated[str, Field(max_length=200)]


class Contato(BaseModel):
    nome: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = None
    telefone: str | None = Field(default=None, max_length=32)

    @field_validator("nome", "email", "telefone", mode="before")
    @classmethod
    def _vazio_e_ausente(cls, v: object) -> object:
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v

    @model_validator(mode="after")
    def _email_ou_telefone(self) -> Contato:
        if not self.email and not self.telefone:
            raise ValueError("contato exige e-mail ou telefone")
        return self


class Toque(BaseModel):
    model_config = ConfigDict(extra="allow")

    utm_source: str | None = Field(default=None, max_length=500)
    utm_medium: str | None = Field(default=None, max_length=500)
    utm_campaign: str | None = Field(default=None, max_length=500)
    utm_content: str | None = Field(default=None, max_length=500)
    utm_term: str | None = Field(default=None, max_length=500)
    gclid: str | None = Field(default=None, max_length=500)
    fbclid: str | None = Field(default=None, max_length=500)
    landing_path: str | None = Field(default=None, max_length=500)
    referrer_host: str | None = Field(default=None, max_length=255)
    ocorrido_em: datetime | None = None


class Atribuicao(BaseModel):
    situacao: Situacao
    primeiro_toque: Toque | None = None
    ultimo_toque: Toque | None = None


class Pedido(BaseModel):
    model_config = ConfigDict(extra="allow")

    provedor: str = Field(min_length=1, max_length=40)
    order_id: str = Field(min_length=1, max_length=120)
    plano: str | None = Field(default=None, max_length=80)
    periodo: str | None = Field(default=None, max_length=40)
    valor_bruto_centavos: int | None = Field(default=None, ge=0)
    valor_liquido_centavos: int | None = Field(default=None, ge=0)


class IngestIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    evento: Evento
    chave_idempotencia: str = Field(min_length=1, max_length=200)
    ocorrido_em: AwareDatetime
    contato: Contato
    tags: list[TagIn] = Field(default_factory=list, max_length=100)
    atribuicao: Atribuicao
    # Só nos eventos de venda (spec §6.1); opcional em todos, sem exigência por evento.
    pedido: Pedido | None = None


class IngestOut(BaseModel):
    """Corpo da resposta. O contrato do site depende só do STATUS; isto é para diagnóstico."""

    resultado: Literal["processado", "ja_processado"]
    contato_id: str | None
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd F:/Projetos/e1p/_wt-ingest-atribuicao/apps/api && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m pytest tests/test_lead_ingest_schemas.py -v`
Expected: 12 PASS.

Run: `cd F:/Projetos/e1p/_wt-ingest-atribuicao/apps/api && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m ruff check . --fix && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m ruff check .`
Expected: `All checks passed!`

- [ ] **Step 5: Commit**

```bash
cd F:/Projetos/e1p/_wt-ingest-atribuicao && git add apps/api/app/modules/lead_ingest/schemas.py apps/api/tests/lead_ingest_apoio.py apps/api/tests/test_lead_ingest_schemas.py && git commit -m "feat(lead-ingest): contrato congelado do POST /public/ingest/leads (spec §6.1)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Soma de tags com limite e descarte registrado

**Files:**
- Modify: `apps/api/app/modules/crm/models.py:28` (constantes logo abaixo de `SOURCE_VALUES`)
- Modify: `apps/api/app/modules/crm/schemas.py:9` e `:94-100`
- Create: `apps/api/app/modules/lead_ingest/tags.py`
- Test: `apps/api/tests/test_lead_ingest_tags.py`

**Interfaces:**
- Produces: `crm.models.TAG_LIMIT = 50`, `crm.models.TAG_MAX_LENGTH = 40`; `tags.somar_tags(atuais: list[str] | None, novas: list[str]) -> tuple[list[str], list[str]]` (resultantes, descartadas).

- [ ] **Step 1: Escrever os testes que falham**

Criar `apps/api/tests/test_lead_ingest_tags.py`:

```python
"""Soma de tags vindas de fora: sem duplicar, sem estourar 50 × 40, descarte registrado."""
import pytest
from pydantic import ValidationError

from app.modules.crm.models import TAG_LIMIT, TAG_MAX_LENGTH
from app.modules.crm.schemas import ClientCreate
from app.modules.lead_ingest.tags import somar_tags


def test_limites_sao_os_do_crm():
    assert (TAG_LIMIT, TAG_MAX_LENGTH) == (50, 40)


def test_soma_sem_duplicar_preservando_a_ordem():
    resultado, descartadas = somar_tags(
        ["vindo-do-site", "origem:instagram"], ["origem:instagram", "post:ig-r-c8abc"]
    )
    assert resultado == ["vindo-do-site", "origem:instagram", "post:ig-r-c8abc"]
    assert descartadas == []


def test_tag_nova_e_normalizada_mas_a_antiga_fica_como_o_dono_escreveu():
    resultado, _ = somar_tags(["Tem Filhos", "origem:instagram"], ["  Origem:Instagram ", ""])
    assert resultado == ["Tem Filhos", "origem:instagram"]


def test_acima_do_limite_guarda_as_primeiras_e_lista_o_resto_uma_vez():
    atuais = [f"a:{i:02d}" for i in range(48)]
    resultado, descartadas = somar_tags(atuais, ["n:1", "n:2", "n:3", "n:4", "n:3"])
    assert len(resultado) == 50
    assert resultado[-2:] == ["n:1", "n:2"]
    assert descartadas == ["n:3", "n:4"]


def test_tag_de_41_caracteres_e_descartada_e_a_de_40_entra():
    quarenta, quarenta_e_um = "c:" + "x" * 38, "c:" + "x" * 39
    resultado, descartadas = somar_tags([], [quarenta, quarenta_e_um])
    assert resultado == [quarenta]
    assert descartadas == [quarenta_e_um]


def test_nao_muta_a_lista_do_contato():
    atuais = ["origem:instagram"]
    somar_tags(atuais, ["post:ig-r-c8abc"])
    assert atuais == ["origem:instagram"]


def test_schema_do_crm_continua_recusando_51_tags():
    with pytest.raises(ValidationError, match="máximo de 50 tags"):
        ClientCreate(name="X", tags=[f"t{i}" for i in range(51)])
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd F:/Projetos/e1p/_wt-ingest-atribuicao/apps/api && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m pytest tests/test_lead_ingest_tags.py -v`
Expected: erro de coleta `ImportError: cannot import name 'TAG_LIMIT' from 'app.modules.crm.models'`.

- [ ] **Step 3: Implementar**

Em `apps/api/app/modules/crm/models.py`, logo depois de `SOURCE_VALUES = {"manual", "landing", "ai", "import", "api", "whatsapp"}`, acrescentar:

```python
# Limites de `Client.tags`. Validados no schema (`ClientBase._tags`) e respeitados por quem soma
# tags por fora dele (`lead_ingest/tags.py`). Um lugar só, para os dois não divergirem.
TAG_LIMIT = 50
TAG_MAX_LENGTH = 40
```

Em `apps/api/app/modules/crm/schemas.py`, trocar a linha 9:

```python
from app.modules.crm.models import GENDER_VALUES, SOURCE_VALUES
```

por:

```python
from app.modules.crm.models import GENDER_VALUES, SOURCE_VALUES, TAG_LIMIT, TAG_MAX_LENGTH
```

e, dentro de `_tags`, trocar:

```python
                if len(t) > 40:
                    raise ValueError("tag muito longa (máx. 40 caracteres)")
                seen.append(t)
        if len(seen) > 50:
            raise ValueError("máximo de 50 tags por cliente")
```

por:

```python
                if len(t) > TAG_MAX_LENGTH:
                    raise ValueError(f"tag muito longa (máx. {TAG_MAX_LENGTH} caracteres)")
                seen.append(t)
        if len(seen) > TAG_LIMIT:
            raise ValueError(f"máximo de {TAG_LIMIT} tags por cliente")
```

Criar `apps/api/app/modules/lead_ingest/tags.py`:

```python
"""Soma de tags vindas de fora no contato: sem duplicar, sem estourar os limites do CRM.

O schema do CRM (`ClientBase._tags`) RECUSA lista acima do limite — certo para quem edita na
tela, errado para a ingestão: recusar seria 422, a fila do site trataria como erro permanente e
a venda ficaria sem contato. A spec (§6.2) manda o contrário: acrescenta o que couber e REGISTRA
o que sobrou (o fato na linha do tempo leva a origem completa e a lista de descartadas).
"""
from __future__ import annotations

from app.modules.crm.models import TAG_LIMIT, TAG_MAX_LENGTH


def somar_tags(atuais: list[str] | None, novas: list[str]) -> tuple[list[str], list[str]]:
    """Devolve `(tags_resultantes, descartadas)`, nas ordens de chegada. Não muta `atuais`.

    Tags NOVAS chegam normalizadas — sem espaço nas pontas, em minúsculas: a taxonomia da spec
    (§4) é minúscula, e `Origem:Instagram` e `origem:instagram` virariam dois filtros no CRM. As
    que já estavam no contato ficam como estão: o dono pode ter escrito "Tem Filhos" à mão.
    """
    resultado = list(atuais or [])
    descartadas: list[str] = []
    for bruta in novas:
        tag = bruta.strip().lower()
        if not tag or tag in resultado or tag in descartadas:
            continue
        if len(tag) > TAG_MAX_LENGTH or len(resultado) >= TAG_LIMIT:
            descartadas.append(tag)
            continue
        resultado.append(tag)
    return resultado, descartadas
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd F:/Projetos/e1p/_wt-ingest-atribuicao/apps/api && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m pytest tests/test_lead_ingest_tags.py tests/test_crm.py tests/test_crm_models.py -v`
Expected: todos PASS.

Run: `cd F:/Projetos/e1p/_wt-ingest-atribuicao/apps/api && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m ruff check . --fix && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m ruff check .`
Expected: `All checks passed!`

- [ ] **Step 5: Commit**

```bash
cd F:/Projetos/e1p/_wt-ingest-atribuicao && git add apps/api/app/modules/crm/models.py apps/api/app/modules/crm/schemas.py apps/api/app/modules/lead_ingest/tags.py apps/api/tests/test_lead_ingest_tags.py && git commit -m "feat(lead-ingest): soma de tags sem duplicar, com limite do CRM e descarte registrado" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Ganchos no CRM e no auto-enroll (`find_lead`, `auto_enroll`, `jornada_viva`)

**Files:**
- Modify: `apps/api/app/modules/crm/service.py:229-275` (`create_client`), `:278-301` (novo `find_lead` depois de `_find_existing`), `:314-386` (`absorb_lead`)
- Modify: `apps/api/app/modules/funnels/automation.py:31-105`
- Test: `apps/api/tests/test_lead_ingest_crm_hooks.py`

**Interfaces:**
- Consumes: `_find_existing(db, *, phone_key, email)` (já existe), `normalize_br`.
- Produces: `crm_service.create_client(db, *, tenant_id, actor, data, auto_enroll: bool = True) -> Client`; `crm_service.absorb_lead(db, *, tenant_id, actor, data, auto_enroll: bool = True) -> tuple[Client, bool]`; payload dos eventos `crm.client.created`/`crm.client.returned` ganha `auto_enroll: bool`; `crm_service.find_lead(db, *, phone: str | None, email: str | None) -> Client | None`; `automation.jornada_viva(db, *, funnel_id: str, client_id: str) -> bool`.

**Por quê.** `absorb_lead` com `source="api"` dispara o auto-enroll no funil padrão (`automation.py:27`, `AUTO_ENROLL_SOURCES = {"landing", "api"}`) tanto na criação quanto no retorno. A ingestão escolhe o funil pelo EVENTO (Task 8); sem um jeito de desligar o caminho automático, o mesmo contato entraria em dois funis — e um reembolso o reinscreveria nas boas-vindas.

- [ ] **Step 1: Escrever os testes que falham**

Criar `apps/api/tests/test_lead_ingest_crm_hooks.py`:

```python
"""Ganchos que a ingestão usa no CRM: `find_lead`, `auto_enroll=False`, `jornada_viva`."""
from contextlib import contextmanager

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import events
from app.modules.crm import service as crm_service
from app.modules.crm.models import Client
from app.modules.crm.schemas import ClientCreate
from app.modules.funnels import automation
from app.modules.funnels.models import RUN_WAITING, Funnel, FunnelRun
from app.modules.settings.models import TenantProfile

TENANT = "tenant-nexus-0001"


@pytest.fixture()
def emitidos():
    events.clear()
    capturados: list[tuple[str, dict]] = []
    for nome in (crm_service.EVENT_CLIENT_CREATED, crm_service.EVENT_CLIENT_RETURNED):
        events.subscribe(nome, lambda _nome=nome, **p: capturados.append((_nome, p)))
    yield capturados
    events.clear()


@pytest.fixture()
def _fake_session(db: Session, monkeypatch):
    @contextmanager
    def _factory(_tenant_id):
        yield db

    monkeypatch.setattr(automation, "tenant_session", _factory)


def _absorve(db: Session, **kw):
    return crm_service.absorb_lead(
        db, tenant_id=TENANT, actor="teste",
        data=ClientCreate(name="Maria", email="maria@exemplo.gov.br", source="api"), **kw,
    )


def _funil_padrao(db: Session) -> Funnel:
    funil = Funnel(tenant_id=TENANT, name="Entrada", nodes=[{"id": "n1"}], edges=[])
    db.add(funil)
    db.commit()
    db.add(TenantProfile(tenant_id=TENANT, default_entry_funnel_id=funil.id))
    db.commit()
    return funil


def test_padrao_continua_emitindo_auto_enroll_verdadeiro(db: Session, emitidos):
    _absorve(db)
    assert [nome for nome, _ in emitidos] == [crm_service.EVENT_CLIENT_CREATED]
    assert emitidos[0][1]["auto_enroll"] is True


def test_auto_enroll_falso_viaja_na_criacao_e_no_retorno(db: Session, emitidos):
    _absorve(db, auto_enroll=False)
    _absorve(db, auto_enroll=False)
    assert [(nome, p["auto_enroll"]) for nome, p in emitidos] == [
        (crm_service.EVENT_CLIENT_CREATED, False),
        (crm_service.EVENT_CLIENT_RETURNED, False),
    ]


def test_automacao_respeita_auto_enroll_falso(db: Session, _fake_session):
    _funil_padrao(db)
    contato = Client(tenant_id=TENANT, name="Lead API", source="api")
    db.add(contato)
    db.commit()
    automation.on_client_created(
        tenant_id=TENANT, client_id=contato.id, source="api", auto_enroll=False
    )
    automation.on_client_returned(
        tenant_id=TENANT, client_id=contato.id, source="api", auto_enroll=False
    )
    assert db.scalar(select(FunnelRun).where(FunnelRun.client_id == contato.id)) is None


def test_find_lead_acha_por_telefone_em_outro_formato_e_por_email_sem_caixa(db: Session):
    contato = Client(
        tenant_id=TENANT, name="Maria", email="Maria@Exemplo.gov.br",
        phone="(11) 99999-8888", phone_key="5511999998888", source="api",
    )
    db.add(contato)
    db.commit()
    assert crm_service.find_lead(db, phone="5511999998888", email=None).id == contato.id
    assert crm_service.find_lead(db, phone=None, email="maria@exemplo.gov.br").id == contato.id
    assert crm_service.find_lead(db, phone="(21) 98888-7777", email="outra@x.com") is None


def test_jornada_viva_e_publica_e_ve_espera(db: Session):
    run = FunnelRun(
        tenant_id=TENANT, funnel_id="f-1", client_id="c-1", status=RUN_WAITING, steps=[]
    )
    db.add(run)
    db.commit()
    assert automation.jornada_viva(db, funnel_id="f-1", client_id="c-1") is True
    assert automation.jornada_viva(db, funnel_id="f-1", client_id="c-2") is False
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd F:/Projetos/e1p/_wt-ingest-atribuicao/apps/api && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m pytest tests/test_lead_ingest_crm_hooks.py -v`
Expected: FAIL — `KeyError: 'auto_enroll'`, `TypeError: absorb_lead() got an unexpected keyword argument 'auto_enroll'`, `AttributeError: ... has no attribute 'find_lead'` / `'jornada_viva'`.

- [ ] **Step 3: Implementar**

Em `apps/api/app/modules/crm/service.py`, trocar a assinatura de `create_client`:

```python
def create_client(db: Session, *, tenant_id: str, actor: str, data: ClientCreate) -> Client:
```

por:

```python
def create_client(
    db: Session, *, tenant_id: str, actor: str, data: ClientCreate, auto_enroll: bool = True
) -> Client:
```

e o `events.emit` do fim de `create_client`:

```python
    events.emit(
        EVENT_CLIENT_CREATED, tenant_id=tenant_id, client_id=client.id, source=client.source,
        notes=data.notes,
    )
```

por:

```python
    # `auto_enroll=False`: quem criou escolhe o funil sozinho (a ingestão de leads, que decide
    # pelo EVENTO — `lead_ingest/service.py`). Sem isto, o caminho automático inscreveria no
    # funil padrão e o contato andaria em dois funis.
    events.emit(
        EVENT_CLIENT_CREATED, tenant_id=tenant_id, client_id=client.id, source=client.source,
        notes=data.notes, auto_enroll=auto_enroll,
    )
```

Logo depois do fim de `_find_existing` (antes de `_ROTULO_DE_RETORNO = {`), acrescentar:

```python
def find_lead(db: Session, *, phone: str | None, email: str | None) -> Client | None:
    """A MESMA identidade de `absorb_lead`, sem efeito colateral nenhum.

    Para quem precisa saber se a pessoa já existe sem passar pelo "voltou" — a ingestão de
    pós-venda (reembolso, chargeback...), em que `absorb_lead` reabriria o card do Ganho.
    """
    return _find_existing(db, phone_key=normalize_br(phone), email=email)
```

Trocar a assinatura de `absorb_lead`:

```python
def absorb_lead(
    db: Session, *, tenant_id: str, actor: str, data: ClientCreate
) -> tuple[Client, bool]:
```

por:

```python
def absorb_lead(
    db: Session,
    *,
    tenant_id: str,
    actor: str,
    data: ClientCreate,
    auto_enroll: bool = True,
) -> tuple[Client, bool]:
```

trocar:

```python
    if existente is None:
        return create_client(db, tenant_id=tenant_id, actor=actor, data=data), True
```

por:

```python
    if existente is None:
        novo = create_client(
            db, tenant_id=tenant_id, actor=actor, data=data, auto_enroll=auto_enroll
        )
        return novo, True
```

e, no `events.emit(EVENT_CLIENT_RETURNED, ...)` do fim, trocar:

```python
        notes=data.notes,
    )
    return existente, False
```

por:

```python
        notes=data.notes,
        auto_enroll=auto_enroll,
    )
    return existente, False
```

Em `apps/api/app/modules/funnels/automation.py`, trocar:

```python
def on_client_created(
    *, tenant_id: str, client_id: str, source: str, notes: str = "", **_: object
) -> None:
    if source not in AUTO_ENROLL_SOURCES:
        return
```

por:

```python
def on_client_created(
    *,
    tenant_id: str,
    client_id: str,
    source: str,
    notes: str = "",
    auto_enroll: bool = True,
    **_: object,
) -> None:
    # `auto_enroll=False`: quem criou o contato já decidiu o funil (ingestão de leads, que
    # escolhe pelo EVENTO). Inscrever aqui também poria o contato em dois funis.
    if not auto_enroll or source not in AUTO_ENROLL_SOURCES:
        return
```

trocar:

```python
def _ja_esta_andando(db, *, funnel_id: str, client_id: str) -> bool:
```

por:

```python
def jornada_viva(db, *, funnel_id: str, client_id: str) -> bool:
```

trocar:

```python
def on_client_returned(
    *, tenant_id: str, client_id: str, source: str, notes: str = "", **_: object
) -> None:
```

por:

```python
def on_client_returned(
    *,
    tenant_id: str,
    client_id: str,
    source: str,
    notes: str = "",
    auto_enroll: bool = True,
    **_: object,
) -> None:
```

dentro dela, trocar:

```python
    if source not in AUTO_ENROLL_SOURCES:
        return
    with tenant_session(tenant_id) as db:
        profile = settings_service.get_profile(db, tenant_id)
        if not profile.default_entry_funnel_id:
            return
        if _ja_esta_andando(
```

por:

```python
    if not auto_enroll or source not in AUTO_ENROLL_SOURCES:
        return
    with tenant_session(tenant_id) as db:
        profile = settings_service.get_profile(db, tenant_id)
        if not profile.default_entry_funnel_id:
            return
        if jornada_viva(
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd F:/Projetos/e1p/_wt-ingest-atribuicao/apps/api && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m pytest tests/test_lead_ingest_crm_hooks.py tests/test_lead_auto_enroll.py tests/test_lead_absorb.py tests/test_lead_portas.py tests/test_crm.py -v`
Expected: todos PASS.

Run: `cd F:/Projetos/e1p/_wt-ingest-atribuicao/apps/api && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m ruff check . --fix && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m ruff check .`
Expected: `All checks passed!`

- [ ] **Step 5: Commit**

```bash
cd F:/Projetos/e1p/_wt-ingest-atribuicao && git add apps/api/app/modules/crm/service.py apps/api/app/modules/funnels/automation.py apps/api/tests/test_lead_ingest_crm_hooks.py && git commit -m "feat(crm): absorb_lead aceita auto_enroll=False e find_lead expõe a identidade do lead" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Serviço de ingestão — contato, tags e fato

**Files:**
- Modify: `apps/api/app/core/facts.py:55` (8 kinds novos depois de `COM_PAGINA_PUBLICADA`)
- Create: `apps/api/app/modules/lead_ingest/service.py`
- Test: `apps/api/tests/test_lead_ingest_service.py`

**Interfaces:**
- Consumes: `registro.reivindicar/concluir/contato_da_chave` (Task 2); `config.produto`, `config.EVENTOS_DE_ENTRADA` (Task 3); `IngestIn`, `Contato` (Task 4); `somar_tags` (Task 5); `crm_service.find_lead`, `absorb_lead(..., auto_enroll=False)` (Task 6); `settings_service.get_profile(db, tenant_id)`; `facts.record`; `audit.record`.
- Produces: constantes `COM_LEAD_RECEBIDO`, `COM_CARRINHO_ABANDONADO`, `COM_COMPRA_APROVADA`, `COM_ASSINATURA_RENOVADA`, `COM_COMPRA_REEMBOLSADA`, `COM_COMPRA_CONTESTADA`, `COM_ASSINATURA_CANCELADA`, `COM_ORIGEM_IDENTIFICADA` em `core/facts.py`; `service.ATOR = "integracao:lead_ingest"`; `service.ResultadoIngest(processado: bool, contato_id: str | None)`; `service.ingest(db, *, tenant_id: str, dados: IngestIn) -> ResultadoIngest`.

**Taxonomia.** A spec dá `publia.compra.aprovada` como exemplo de `kind`, mas `facts.record` levanta `FactError` se o `kind` não começar pelo `module` (`core/facts.py`, "Invariante 1"), e a spec fixa `module="comercial"`. Fica `comercial.<entidade>.<verbo>`, sem nome de produto (o e1p é multi-tenant).

- [ ] **Step 1: Escrever os testes que falham**

Criar `apps/api/tests/test_lead_ingest_service.py`:

```python
"""`lead_ingest.service.ingest`: contato, tags, fato e idempotência (spec §6.2).

Etapa do Kanban e funil por evento: `test_lead_ingest_etapa_funil.py`.
"""
import json

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import events
from app.core.facts import Fact
from app.modules.crm.models import Client
from app.modules.lead_ingest import registro as registro_service
from app.modules.lead_ingest import service
from app.modules.lead_ingest.models import LeadIngestRecord
from app.modules.settings import service as settings_service
from tests.lead_ingest_apoio import TENANT, payload


@pytest.fixture(autouse=True)
def _sem_assinantes():
    # O barramento é global ao processo; sem isto, um assinante registrado no import de
    # `app.main` tentaria abrir conexão Postgres real ao receber `crm.client.*`.
    events.clear()
    yield
    events.clear()


def _ingere(db: Session, **sobre):
    return service.ingest(db, tenant_id=TENANT, dados=payload(**sobre))


def _fatos(db: Session, client_id: str, kind: str) -> list[Fact]:
    return list(
        db.scalars(select(Fact).where(Fact.client_id == client_id, Fact.kind == kind)).all()
    )


def _produto(db: Session, nome: str = "publia") -> None:
    perfil = settings_service.get_profile(db, TENANT)
    perfil.lead_ingest_config = {"produto": nome}
    db.commit()


def test_lead_novo_cria_contato_api_com_tags_e_fato(db: Session):
    r = _ingere(db)
    assert r.processado is True
    contato = db.get(Client, r.contato_id)
    assert contato.source == "api"
    assert contato.tags == ["origem:instagram", "post:ig-r-c8abc"]
    [fato] = _fatos(db, contato.id, "comercial.lead.recebido")
    assert fato.title == "Deixou o contato no site"
    corpo = json.loads(fato.body)
    assert corpo["atribuicao"]["situacao"] == "resolvida"
    assert corpo["atribuicao"]["ultimo_toque"]["utm_content"] == "ig-r-c8abc"
    assert corpo["tags_descartadas"] == []


def test_mesma_chave_repetida_e_no_op(db: Session):
    primeiro = _ingere(db)
    segundo = _ingere(db, tags=["outra:tag"])
    assert segundo.processado is False
    assert segundo.contato_id == primeiro.contato_id
    assert db.scalar(select(func.count(Client.id))) == 1
    assert len(_fatos(db, primeiro.contato_id, "comercial.lead.recebido")) == 1
    assert "outra:tag" not in db.get(Client, primeiro.contato_id).tags


def test_retoma_chave_reivindicada_que_nao_concluiu(db: Session):
    """Queda entre o commit do contato e o das tags: a próxima tentativa processa."""
    dados = payload()
    registro_service.reivindicar(
        db, tenant_id=TENANT, chave=dados.chave_idempotencia, evento=dados.evento,
        ocorrido_em=dados.ocorrido_em, payload={},
    )
    db.commit()
    r = service.ingest(db, tenant_id=TENANT, dados=dados)
    assert r.processado is True
    assert db.scalar(select(func.count(LeadIngestRecord.id))) == 1
    assert db.scalar(select(LeadIngestRecord.concluido_em)) is not None


def test_fato_nao_guarda_dinheiro_mas_o_registro_bruto_guarda(db: Session):
    r = _ingere(
        db, evento="compra_aprovada", chave_idempotencia="kiwify:ord_1:compra_aprovada",
        pedido={
            "provedor": "kiwify", "order_id": "ord_1", "plano": "essencial", "periodo": "anual",
            "valor_bruto_centavos": 49900, "valor_liquido_centavos": 44300,
            "taxa_centavos": 5600,
        },
    )
    [fato] = _fatos(db, r.contato_id, "comercial.compra.aprovada")
    assert json.loads(fato.body)["pedido"] == {
        "provedor": "kiwify", "order_id": "ord_1", "plano": "essencial", "periodo": "anual",
    }
    assert "49900" not in fato.body and "44300" not in fato.body and "5600" not in fato.body
    assert db.scalar(select(LeadIngestRecord)).payload["pedido"]["valor_bruto_centavos"] == 49900


def test_dedup_por_telefone_em_formato_diferente(db: Session):
    primeiro = _ingere(db)
    segundo = _ingere(
        db, chave_idempotencia="site:lead:2",
        contato={"nome": "Maria", "telefone": "5511999998888"},
    )
    assert segundo.contato_id == primeiro.contato_id
    assert db.scalar(select(func.count(Client.id))) == 1


def test_mesmo_email_com_telefone_diferente_nao_cria_card_nem_troca_telefone(db: Session):
    primeiro = _ingere(db)
    segundo = _ingere(
        db, chave_idempotencia="site:lead:2",
        contato={
            "nome": "Maria", "email": "MARIA@exemplo.gov.br", "telefone": "(21) 98888-7777",
        },
    )
    assert segundo.contato_id == primeiro.contato_id
    assert db.scalar(select(func.count(Client.id))) == 1
    assert db.get(Client, primeiro.contato_id).phone == "(11) 99999-8888"


def test_telefone_de_um_e_email_de_outro_fica_com_o_dono_do_telefone(db: Session):
    maria = _ingere(db)
    joao = _ingere(
        db, chave_idempotencia="site:lead:2",
        contato={"nome": "João", "email": "joao@exemplo.gov.br", "telefone": "(21) 98888-7777"},
    )
    misto = _ingere(
        db, chave_idempotencia="site:lead:3",
        contato={"nome": "?", "email": "maria@exemplo.gov.br", "telefone": "(21) 98888-7777"},
    )
    assert misto.contato_id == joao.contato_id
    assert misto.contato_id != maria.contato_id


def test_tags_somam_entre_eventos_sem_duplicar(db: Session):
    r = _ingere(db)
    _ingere(
        db, chave_idempotencia="site:lead:2",
        tags=["origem:instagram", "campanha:publia-lanc-out26"],
    )
    assert db.get(Client, r.contato_id).tags == [
        "origem:instagram", "post:ig-r-c8abc", "campanha:publia-lanc-out26",
    ]


def test_tags_acima_do_limite_nao_derrubam_e_ficam_registradas(db: Session):
    longa = "campanha:" + "x" * 32  # 41 caracteres
    r = _ingere(db, tags=[f"t:{i:02d}" for i in range(60)] + [longa])
    assert r.processado is True
    contato = db.get(Client, r.contato_id)
    assert len(contato.tags) == 50
    esperadas = [f"t:{i:02d}" for i in range(50, 60)] + [longa]
    [fato] = _fatos(db, contato.id, "comercial.lead.recebido")
    assert json.loads(fato.body)["tags_descartadas"] == esperadas
    assert db.scalar(select(LeadIngestRecord)).tags_descartadas == esperadas


@pytest.mark.parametrize(
    ("evento", "tag", "kind"),
    [
        ("reembolso", "publia:reembolso", "comercial.compra.reembolsada"),
        ("chargeback", "publia:chargeback", "comercial.compra.contestada"),
        ("cancelamento", "publia:cancelou", "comercial.assinatura.cancelada"),
    ],
)
def test_pos_venda_aplica_tag_de_produto_sem_passar_pelo_voltou(db: Session, evento, tag, kind):
    _produto(db)
    compra = _ingere(db, evento="compra_aprovada", chave_idempotencia="kiwify:ord_1:compra")
    depois = _ingere(db, evento=evento, chave_idempotencia=f"kiwify:ord_1:{evento}", tags=[])
    assert depois.contato_id == compra.contato_id
    assert tag in db.get(Client, compra.contato_id).tags
    assert len(_fatos(db, compra.contato_id, kind)) == 1
    assert _fatos(db, compra.contato_id, "crm.lead.retornou") == []


def test_renovacao_so_registra(db: Session):
    _produto(db)
    compra = _ingere(db, evento="compra_aprovada", chave_idempotencia="kiwify:ord_1:compra")
    antes = list(db.get(Client, compra.contato_id).tags)
    _ingere(db, evento="renovacao", chave_idempotencia="kiwify:ord_1:renovacao:2026-11", tags=[])
    assert db.get(Client, compra.contato_id).tags == antes
    assert len(_fatos(db, compra.contato_id, "comercial.assinatura.renovada")) == 1


def test_sem_produto_configurado_nao_inventa_tag(db: Session):
    r = _ingere(db, evento="reembolso", chave_idempotencia="kiwify:ord_9:reembolso", tags=[])
    assert not any(t.endswith(":reembolso") for t in db.get(Client, r.contato_id).tags)


def test_pos_venda_de_quem_nunca_chegou_cria_o_contato(db: Session):
    _produto(db)
    r = _ingere(
        db, evento="chargeback", chave_idempotencia="kiwify:ord_7:chargeback",
        contato={"nome": "Ana", "email": "ana@exemplo.gov.br"}, tags=[],
    )
    contato = db.get(Client, r.contato_id)
    assert contato.source == "api"
    assert contato.tags == ["publia:chargeback"]


def test_contato_so_com_email_usa_o_email_como_nome(db: Session):
    r = _ingere(db, contato={"email": "sem.nome@exemplo.gov.br"})
    assert db.get(Client, r.contato_id).name == "sem.nome@exemplo.gov.br"
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd F:/Projetos/e1p/_wt-ingest-atribuicao/apps/api && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m pytest tests/test_lead_ingest_service.py -v`
Expected: erro de coleta `ImportError: cannot import name 'service' from 'app.modules.lead_ingest'`.

- [ ] **Step 3: Implementar**

Em `apps/api/app/core/facts.py`, logo depois de `COM_PAGINA_PUBLICADA = "comercial.pagina.publicada"`, acrescentar:

```python
# Ingestão de leads com atribuição (`lead_ingest`, spec da Publ.IA §6). Um por evento do
# contrato, sem nome de produto: o e1p é multi-tenant, o produto mora em `pedido`.
COM_LEAD_RECEBIDO = "comercial.lead.recebido"
COM_CARRINHO_ABANDONADO = "comercial.carrinho.abandonado"
COM_COMPRA_APROVADA = "comercial.compra.aprovada"
COM_ASSINATURA_RENOVADA = "comercial.assinatura.renovada"
COM_COMPRA_REEMBOLSADA = "comercial.compra.reembolsada"
COM_COMPRA_CONTESTADA = "comercial.compra.contestada"
COM_ASSINATURA_CANCELADA = "comercial.assinatura.cancelada"
# Código de origem lido na 1ª mensagem de WhatsApp (`lead_ingest/whatsapp.py`).
COM_ORIGEM_IDENTIFICADA = "comercial.origem.identificada"
```

Criar `apps/api/app/modules/lead_ingest/service.py`:

```python
"""Ingestão de leads com atribuição: o site empurra PESSOAS, o e1p absorve (spec §6.2).

Uma chamada de `ingest`, na ordem:

1. **Reivindica a chave** (`registro.reivindicar`). Repetida e concluída → no-op (HTTP 200).
2. **Resolve o contato.** Evento de ENTRADA (lead, carrinho, compra) passa por
   `crm.absorb_lead` com `source="api"` — a porta única de lead, com a dedup de sempre (telefone
   normalizado, depois e-mail). Evento de PÓS-VENDA (renovação, reembolso, chargeback,
   cancelamento) de quem já existe NÃO passa: `absorb_lead` reabre card em coluna terminal, e um
   reembolso tiraria do Ganho quem comprou — o contrário da spec ("não movem o card").
3. **Soma tags** sem duplicar e sem estourar o limite do CRM; o que sobrar fica registrado.
4. **Grava o fato** na timeline (`module="comercial"`), com a atribuição no corpo.

`absorb_lead` commita no meio (é assim que ele é, e os outros chamadores dependem disso): a
reivindicação entra no MESMO commit do contato, e tags + fato + conclusão no seguinte. Ver a
docstring de `models.LeadIngestRecord` sobre a retomada quando o processo cai entre os dois.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core import audit, facts
from app.core.facts import (
    COM_ASSINATURA_CANCELADA,
    COM_ASSINATURA_RENOVADA,
    COM_CARRINHO_ABANDONADO,
    COM_COMPRA_APROVADA,
    COM_COMPRA_CONTESTADA,
    COM_COMPRA_REEMBOLSADA,
    COM_LEAD_RECEBIDO,
)
from app.modules.crm import service as crm_service
from app.modules.crm.models import Client
from app.modules.crm.schemas import ClientCreate
from app.modules.lead_ingest import config
from app.modules.lead_ingest import registro as registro_service
from app.modules.lead_ingest.schemas import Contato, IngestIn
from app.modules.lead_ingest.tags import somar_tags
from app.modules.settings import service as settings_service

ATOR = "integracao:lead_ingest"

KIND_POR_EVENTO = {
    "lead": COM_LEAD_RECEBIDO,
    "carrinho_abandonado": COM_CARRINHO_ABANDONADO,
    "compra_aprovada": COM_COMPRA_APROVADA,
    "renovacao": COM_ASSINATURA_RENOVADA,
    "reembolso": COM_COMPRA_REEMBOLSADA,
    "chargeback": COM_COMPRA_CONTESTADA,
    "cancelamento": COM_ASSINATURA_CANCELADA,
}

# Título FIXO por evento: o plano e a origem vêm do site e vão no corpo. Interpolar texto de
# fora no título arriscaria a guarda de dinheiro de `facts.record` (um plano com "R$" viraria
# `FactError` → 500 → reenvio eterno da fila do site).
TITULO_POR_EVENTO = {
    "lead": "Deixou o contato no site",
    "carrinho_abandonado": "Abandonou o carrinho",
    "compra_aprovada": "Compra aprovada",
    "renovacao": "Assinatura renovada",
    "reembolso": "Compra reembolsada",
    "chargeback": "Chargeback na compra",
    "cancelamento": "Assinatura cancelada",
}

# `<produto>:<sufixo>` (spec §6.2). Cancelamento não é reembolso: tag própria.
SUFIXO_DE_PRODUTO = {
    "reembolso": "reembolso",
    "chargeback": "chargeback",
    "cancelamento": "cancelou",
}


@dataclass(frozen=True)
class ResultadoIngest:
    processado: bool  # False = chave já processada (no-op, HTTP 200)
    contato_id: str | None


def ingest(db: Session, *, tenant_id: str, dados: IngestIn) -> ResultadoIngest:
    """Processa um evento do site. A sessão já vem RLS-escopada no tenant DO TOKEN."""
    # Lido ANTES da reivindicação: `get_profile` commita quando cria o perfil, e um commit no
    # meio publicaria a reivindicação antes de existir contato.
    perfil = settings_service.get_profile(db, tenant_id)
    registro = registro_service.reivindicar(
        db,
        tenant_id=tenant_id,
        chave=dados.chave_idempotencia,
        evento=dados.evento,
        ocorrido_em=dados.ocorrido_em,
        payload=dados.model_dump(mode="json"),
    )
    if registro is None:
        return ResultadoIngest(
            processado=False,
            contato_id=registro_service.contato_da_chave(db, chave=dados.chave_idempotencia),
        )

    contato = _resolve_contato(db, tenant_id=tenant_id, dados=dados)

    novas = list(dados.tags)
    prefixo = config.produto(perfil)
    sufixo = SUFIXO_DE_PRODUTO.get(dados.evento)
    if prefixo and sufixo:
        novas.append(f"{prefixo}:{sufixo}")
    contato.tags, descartadas = somar_tags(contato.tags, novas)

    facts.record(
        db,
        tenant_id=tenant_id,
        module="comercial",
        kind=KIND_POR_EVENTO[dados.evento],
        title=TITULO_POR_EVENTO[dados.evento],
        actor=ATOR,
        body=_corpo(dados, descartadas),
        client_id=contato.id,
        subject_type="lead_ingest",
        subject_id=registro.id,
        occurred_at=dados.ocorrido_em,
    )
    registro_service.concluir(registro, client_id=contato.id, tags_descartadas=descartadas)
    audit.record(
        db, tenant_id=tenant_id, actor=ATOR, action="lead_ingest.process", target=registro.id
    )
    db.commit()
    return ResultadoIngest(processado=True, contato_id=contato.id)


def _resolve_contato(db: Session, *, tenant_id: str, dados: IngestIn) -> Client:
    contato = dados.contato
    if dados.evento not in config.EVENTOS_DE_ENTRADA:
        existente = crm_service.find_lead(db, phone=contato.telefone, email=contato.email)
        if existente is not None:
            return existente
    cliente, _novo = crm_service.absorb_lead(
        db,
        tenant_id=tenant_id,
        actor=ATOR,
        data=ClientCreate(
            name=_nome(contato), email=contato.email, phone=contato.telefone, source="api"
        ),
        # O funil é decidido pelo EVENTO, não pelo caminho automático do `source`.
        auto_enroll=False,
    )
    return cliente


def _nome(contato: Contato) -> str:
    """Kiwify e formulário mandam nome; carrinho abandonado às vezes não. O card precisa de um."""
    return (contato.nome or contato.email or contato.telefone or "")[:255]


def _corpo(dados: IngestIn, descartadas: list[str]) -> str:
    """A atribuição completa e o pedido — SEM valores (invariante 2 de `core/facts.py`).

    O fato não guarda dinheiro: o valor da venda mora no registro bruto
    (`lead_ingest_records.payload`) e, na origem, na Kiwify. Filtra por SUFIXO (`*_centavos`), e
    não por nome, porque `Pedido` aceita campos extras: um `taxa_centavos` que o site passe a
    mandar amanhã não pode entrar aqui pela porta dos fundos.
    """
    pedido = None
    if dados.pedido is not None:
        pedido = {
            chave: valor
            for chave, valor in dados.pedido.model_dump(mode="json").items()
            if not chave.endswith("_centavos")
        }
    return json.dumps(
        {
            "evento": dados.evento,
            "chave_idempotencia": dados.chave_idempotencia,
            "atribuicao": dados.atribuicao.model_dump(mode="json"),
            "pedido": pedido,
            "tags_descartadas": descartadas,
        },
        ensure_ascii=False,
        indent=2,
    )
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd F:/Projetos/e1p/_wt-ingest-atribuicao/apps/api && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m pytest tests/test_lead_ingest_service.py tests/test_facts_core.py tests/test_audit_target_flush_gate.py tests/test_audit_target_e_id_gate.py -v`
Expected: todos PASS (16 em `test_lead_ingest_service.py`, contando os 3 do parametrize).

Run: `cd F:/Projetos/e1p/_wt-ingest-atribuicao/apps/api && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m ruff check . --fix && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m ruff check .`
Expected: `All checks passed!`

- [ ] **Step 5: Commit**

```bash
cd F:/Projetos/e1p/_wt-ingest-atribuicao && git add apps/api/app/core/facts.py apps/api/app/modules/lead_ingest/service.py apps/api/tests/test_lead_ingest_service.py && git commit -m "feat(lead-ingest): serviço absorve o contato, soma tags e grava o fato sem dinheiro" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Ganho na compra e funil por evento

**Files:**
- Modify: `apps/api/app/modules/lead_ingest/service.py` (imports, `logger`, fim de `ingest`, duas funções novas)
- Test: `apps/api/tests/test_lead_ingest_etapa_funil.py`

**Interfaces:**
- Consumes: `crm_service.ensure_stages(db, tenant_id) -> list[PipelineStage]` (só ativas, ordenadas), `crm_service.move_client(db, *, client_id, tenant_id, actor, by_ai, stage_id) -> Client` (commita a sessão inteira e emite `crm.client.moved` depois); `config.funil_do_evento` (Task 3); `automation.jornada_viva` (Task 6); `engine.enroll(db, *, tenant_id, actor, funnel_id, client_id, ...) -> FunnelRun` (commita); `FunnelError`.
- Produces: `service._fechar(db, *, tenant_id: str, evento: str, contato: Client) -> None`; `service._inscrever_no_funil(db, *, tenant_id: str, perfil: TenantProfile, evento: str, contato_id: str) -> None`.

- [ ] **Step 1: Escrever os testes que falham**

Criar `apps/api/tests/test_lead_ingest_etapa_funil.py`:

```python
"""Ingestão: compra vai ao Ganho, pós-venda não tira de lá, e o funil é escolhido pelo evento."""
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import events
from app.core.facts import Fact
from app.modules.crm.models import Client, PipelineStage
from app.modules.funnels.models import Funnel, FunnelRun
from app.modules.lead_ingest import service
from app.modules.settings import service as settings_service
from tests.lead_ingest_apoio import TENANT, payload


@pytest.fixture(autouse=True)
def _sem_assinantes():
    events.clear()
    yield
    events.clear()


def _ingere(db: Session, **sobre):
    return service.ingest(db, tenant_id=TENANT, dados=payload(**sobre))


def _etapa(db: Session, client_id: str) -> str:
    return db.get(PipelineStage, db.get(Client, client_id).stage_id).name


def _conta_fatos(db: Session, client_id: str, kind: str) -> int:
    return db.scalar(
        select(func.count(Fact.id)).where(Fact.client_id == client_id, Fact.kind == kind)
    )


def _funil(db: Session, nome: str, *, espera: bool = False) -> Funnel:
    if espera:
        nodes = [
            {"id": "n1", "data": {"key": "esperar", "config": {"delay_minutes": 60}}},
            {"id": "n2"},
        ]
        edges = [{"id": "e1", "source": "n1", "target": "n2"}]
    else:
        nodes, edges = [{"id": "n1"}], []
    funil = Funnel(tenant_id=TENANT, name=nome, nodes=nodes, edges=edges)
    db.add(funil)
    db.commit()
    db.refresh(funil)
    return funil


def _configura(db: Session, *, padrao: str | None = None, **cfg) -> None:
    perfil = settings_service.get_profile(db, TENANT)
    perfil.default_entry_funnel_id = padrao
    perfil.lead_ingest_config = cfg
    db.commit()


def _funis_do(db: Session, client_id: str) -> list[str]:
    return [
        r.funnel_id
        for r in db.scalars(select(FunnelRun).where(FunnelRun.client_id == client_id)).all()
    ]


def test_compra_aprovada_move_para_o_ganho(db: Session):
    r = _ingere(db, evento="compra_aprovada", chave_idempotencia="kiwify:ord_1:compra")
    assert _etapa(db, r.contato_id) == "Ganho"
    assert _conta_fatos(db, r.contato_id, "crm.etapa.movida") == 1


@pytest.mark.parametrize("evento", ["reembolso", "chargeback", "cancelamento", "renovacao"])
def test_pos_venda_nao_tira_do_ganho_nem_reabre(db: Session, evento: str):
    compra = _ingere(db, evento="compra_aprovada", chave_idempotencia="kiwify:ord_1:compra")
    _ingere(db, evento=evento, chave_idempotencia=f"kiwify:ord_1:{evento}")
    assert _etapa(db, compra.contato_id) == "Ganho"
    assert _conta_fatos(db, compra.contato_id, "crm.lead.reaberto") == 0


def test_compra_sem_coluna_de_ganho_ativa_registra_sem_mover(db: Session):
    _ingere(db)  # semeia as colunas e põe o contato em Entrada
    ganho = db.scalar(select(PipelineStage).where(PipelineStage.is_won.is_(True)))
    ganho.is_archived = True
    db.commit()
    r = _ingere(db, evento="compra_aprovada", chave_idempotencia="kiwify:ord_1:compra")
    assert r.processado is True
    assert _etapa(db, r.contato_id) == "Entrada"
    assert _conta_fatos(db, r.contato_id, "comercial.compra.aprovada") == 1


def test_evento_mapeado_vai_so_para_o_funil_do_evento(db: Session):
    padrao = _funil(db, "Boas-vindas")
    recuperacao = _funil(db, "Recuperação")
    _configura(db, padrao=padrao.id, funis={"carrinho_abandonado": recuperacao.id})
    r = _ingere(db, evento="carrinho_abandonado", chave_idempotencia="kiwify:c1:carrinho")
    assert _funis_do(db, r.contato_id) == [recuperacao.id]


def test_lead_sem_mapeamento_cai_no_funil_padrao(db: Session):
    padrao = _funil(db, "Boas-vindas")
    _configura(db, padrao=padrao.id)
    r = _ingere(db)
    assert _funis_do(db, r.contato_id) == [padrao.id]


@pytest.mark.parametrize("evento", ["renovacao", "reembolso", "chargeback", "cancelamento"])
def test_pos_venda_sem_mapeamento_nao_entra_no_funil_padrao(db: Session, evento: str):
    padrao = _funil(db, "Boas-vindas")
    _configura(db, padrao=padrao.id)
    r = _ingere(
        db, evento=evento, chave_idempotencia=f"kiwify:o:{evento}",
        contato={"nome": "Ana", "email": "ana@exemplo.gov.br"},
    )
    assert _funis_do(db, r.contato_id) == []


def test_pos_venda_mapeado_explicitamente_inscreve(db: Session):
    retencao = _funil(db, "Retenção")
    _configura(db, funis={"cancelamento": retencao.id})
    r = _ingere(
        db, evento="cancelamento", chave_idempotencia="kiwify:o:cancelamento",
        contato={"nome": "Ana", "email": "ana@exemplo.gov.br"},
    )
    assert _funis_do(db, r.contato_id) == [retencao.id]


def test_jornada_viva_nao_e_duplicada(db: Session):
    padrao = _funil(db, "Boas-vindas", espera=True)
    _configura(db, padrao=padrao.id)
    primeiro = _ingere(db)
    _ingere(db, chave_idempotencia="site:lead:2")
    assert _funis_do(db, primeiro.contato_id) == [padrao.id]


def test_funil_inexistente_nao_derruba_a_ingestao(db: Session):
    _configura(db, funis={"lead": "funil-que-nao-existe"})
    r = _ingere(db)
    assert r.processado is True
    assert _funis_do(db, r.contato_id) == []
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd F:/Projetos/e1p/_wt-ingest-atribuicao/apps/api && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m pytest tests/test_lead_ingest_etapa_funil.py -v`
Expected: FAIL — `assert 'Entrada' == 'Ganho'` e listas de funil vazias onde se espera uma inscrição. `test_pos_venda_nao_tira_do_ganho_nem_reabre`, `test_compra_sem_coluna...`, `test_pos_venda_sem_mapeamento...` e `test_funil_inexistente...` podem passar já (o comportamento ausente é justamente o que eles exigem).

- [ ] **Step 3: Implementar**

Em `apps/api/app/modules/lead_ingest/service.py`:

1. Na docstring do módulo, trocar a linha:

```python
4. **Grava o fato** na timeline (`module="comercial"`), com a atribuição no corpo.
```

por:

```python
4. **Grava o fato** na timeline (`module="comercial"`), com a atribuição no corpo.
5. **Fecha.** `compra_aprovada` leva o card ao Ganho (coluna `is_won`) no mesmo commit.
6. **Inscreve no funil do evento** (`config.funil_do_evento`), se não houver jornada viva nele.
```

2. Trocar o bloco de imports:

```python
import json
from dataclasses import dataclass
```

por:

```python
import json
import logging
from dataclasses import dataclass
```

e acrescentar, junto dos outros `from app.modules...`:

```python
from app.modules.funnels import automation, engine
from app.modules.funnels.service import FunnelError
from app.modules.settings.models import TenantProfile
```

3. Depois de `ATOR = "integracao:lead_ingest"`, acrescentar:

```python
logger = logging.getLogger("e1p.lead_ingest")
```

4. No fim de `ingest`, trocar:

```python
    db.commit()
    return ResultadoIngest(processado=True, contato_id=contato.id)
```

por:

```python
    _fechar(db, tenant_id=tenant_id, evento=dados.evento, contato=contato)
    _inscrever_no_funil(
        db, tenant_id=tenant_id, perfil=perfil, evento=dados.evento, contato_id=contato.id
    )
    return ResultadoIngest(processado=True, contato_id=contato.id)
```

5. No fim do arquivo, acrescentar:

```python
def _fechar(db: Session, *, tenant_id: str, evento: str, contato: Client) -> None:
    """Commita o que está pendente; em `compra_aprovada`, junto com a ida ao Ganho.

    `move_client` commita a sessão inteira: tags, fato e conclusão do registro entram no MESMO
    commit da mudança de etapa, e o aviso de "movido para Ganho" (notifications) só sai depois
    dele. Reembolso, chargeback e cancelamento NÃO movem o card (spec §6.2): a venda aconteceu,
    e o que mudou depois fica em tag e fato, não apagado.
    """
    if evento != "compra_aprovada":
        db.commit()
        return
    ganho = next((s for s in crm_service.ensure_stages(db, tenant_id) if s.is_won), None)
    if ganho is None:
        logger.warning(
            "[lead_ingest] tenant=%s sem coluna de Ganho ativa; compra registrada sem mover o "
            "card %s",
            tenant_id, contato.id,
        )
        db.commit()
        return
    if contato.stage_id == ganho.id:
        db.commit()
        return
    crm_service.move_client(
        db, client_id=contato.id, tenant_id=tenant_id, actor=ATOR, by_ai=False,
        stage_id=ganho.id,
    )


def _inscrever_no_funil(
    db: Session, *, tenant_id: str, perfil: TenantProfile, evento: str, contato_id: str
) -> None:
    """Funil por evento (spec §6.4). Melhor esforço: o lead já está commitado.

    Mesma contenção do caminho automático (`automation.on_client_returned`): quem já anda no
    funil não recomeça do zero porque o site mandou outro evento.
    """
    funil_id = config.funil_do_evento(perfil, evento)
    if not funil_id or automation.jornada_viva(db, funnel_id=funil_id, client_id=contato_id):
        return
    try:
        engine.enroll(
            db, tenant_id=tenant_id, actor=ATOR, funnel_id=funil_id, client_id=contato_id
        )
    except FunnelError:
        # Funil apagado, vazio ou sem entrada: não pode virar 500 — o site reenviaria e
        # receberia 200 (chave concluída), e a inscrição continuaria sem acontecer em silêncio.
        logger.warning(
            "[lead_ingest] inscrição falhou tenant=%s funil=%s evento=%s cliente=%s",
            tenant_id, funil_id, evento, contato_id,
        )
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd F:/Projetos/e1p/_wt-ingest-atribuicao/apps/api && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m pytest tests/test_lead_ingest_etapa_funil.py tests/test_lead_ingest_service.py tests/test_crm_stage_order_gate.py -v`
Expected: todos PASS.

Run: `cd F:/Projetos/e1p/_wt-ingest-atribuicao/apps/api && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m ruff check . --fix && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m ruff check .`
Expected: `All checks passed!`

- [ ] **Step 5: Commit**

```bash
cd F:/Projetos/e1p/_wt-ingest-atribuicao && git add apps/api/app/modules/lead_ingest/service.py apps/api/tests/test_lead_ingest_etapa_funil.py && git commit -m "feat(lead-ingest): compra aprovada vai ao Ganho e cada evento entra no seu funil" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Rota `POST /public/ingest/leads`, guarda de tenancy e CORS

**Files:**
- Create: `apps/api/app/modules/lead_ingest/router.py`
- Modify: `apps/api/app/modules/__init__.py:25-26` (import) e `:71-72` (`ALL_ROUTERS`)
- Modify: `apps/api/tests/test_tenancy_guard.py:11-41` (ALLOWLIST + docstring)
- Modify: `apps/api/app/main.py:1-78` (remove `PublicLeadsCORSMiddleware`)
- Modify: `infra/docker-compose.traefik.yml:197-198` (comentário)
- Test: `apps/api/tests/test_lead_ingest_router.py`

**Interfaces:**
- Consumes: `machine_tokens_service.resolve` (Task 1), `service.ingest` (Tasks 7-8), `IngestIn`/`IngestOut` (Task 4), `get_db`, `get_tenant_session_factory` (`app.db.session`).
- Produces: `router` (`APIRouter(prefix="/public/ingest")`); `credencial_de_ingestao(authorization, db) -> MachineToken`; `ingest_lead(dados, response, credencial, session_factory) -> IngestOut`.

**Decisão sobre CORS.** O `PublicLeadsCORSMiddleware` (`app/main.py:11-55,78`) abre CORS para `/public/leads/*`, rota apagada no PR #270 — sobra morta. A rota nova NÃO precisa de CORS: é servidor-a-servidor (o token de máquina não pode morar num navegador), e sem CORS um `fetch` de página alheia nem lê a resposta. O middleware sai; um teste prova que nem a rota velha nem a nova devolvem `Access-Control-Allow-Origin` para origem estranha. (Verificado em FastAPI 0.115: dependência que levanta `HTTPException` é resolvida ANTES da validação do corpo, então credencial ruim + corpo ruim = 401.)

- [ ] **Step 1: Escrever os testes que falham**

Criar `apps/api/tests/test_lead_ingest_router.py`:

```python
"""`POST /public/ingest/leads`: credencial, contrato de status (201/200/401/422) e CORS."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.crm.models import Client
from app.modules.device_tokens import service as device_tokens_service
from app.modules.machine_tokens import service as machine_tokens_service
from app.modules.machine_tokens.models import SCOPE_LEAD_INGEST
from tests.lead_ingest_apoio import corpo

URL = "/public/ingest/leads"
REGISTER = {
    "legal_name": "Nexus Pública",
    "document": "11222333000181",
    "slug": "nexus",
    "email": "dono@nexus.example.com",
    "name": "Dono",
    "password": "senha-bem-comprida",
}


@pytest.fixture()
def cadastro(client: TestClient) -> dict:
    return client.post("/auth/register", json=REGISTER).json()


@pytest.fixture()
def tenant_id(cadastro: dict) -> str:
    return cadastro["tenant"]["id"]


@pytest.fixture()
def credencial(db: Session, tenant_id: str) -> dict[str, str]:
    _, raw = machine_tokens_service.create_token(
        db, tenant_id=tenant_id, name="site", scope=SCOPE_LEAD_INGEST
    )
    return {"Authorization": f"Bearer {raw}"}


def test_primeiro_envio_201_e_repetido_200(client: TestClient, credencial, db, tenant_id):
    primeiro = client.post(URL, json=corpo(), headers=credencial)
    assert primeiro.status_code == 201, primeiro.text
    assert primeiro.json()["resultado"] == "processado"
    contato = db.get(Client, primeiro.json()["contato_id"])
    assert contato.tenant_id == tenant_id
    assert contato.source == "api"

    repetido = client.post(URL, json=corpo(), headers=credencial)
    assert repetido.status_code == 200
    assert repetido.json() == {"resultado": "ja_processado", "contato_id": contato.id}


def test_tenant_vem_do_token_nunca_do_corpo(client: TestClient, credencial, db, tenant_id):
    resp = client.post(URL, json=corpo(tenant_id="outro-tenant-qualquer-123"), headers=credencial)
    assert resp.status_code == 201
    assert db.get(Client, resp.json()["contato_id"]).tenant_id == tenant_id


@pytest.mark.parametrize("cabecalho", [None, "Bearer nao-existe", "Token abc", "bearer"])
def test_credencial_ausente_ou_invalida_401(client: TestClient, tenant_id, cabecalho):
    headers = {} if cabecalho is None else {"Authorization": cabecalho}
    assert client.post(URL, json=corpo(), headers=headers).status_code == 401


def test_credencial_revogada_401(client: TestClient, db, tenant_id):
    token, raw = machine_tokens_service.create_token(
        db, tenant_id=tenant_id, name="site", scope=SCOPE_LEAD_INGEST
    )
    machine_tokens_service.revoke(db, token_id=token.id)
    resp = client.post(URL, json=corpo(), headers={"Authorization": f"Bearer {raw}"})
    assert resp.status_code == 401


def test_token_de_dispositivo_nao_abre_a_ingestao(client: TestClient, db, tenant_id):
    _, raw = device_tokens_service.create_token(
        db, tenant_id=tenant_id, user_id="u-1", name="iPhone"
    )
    resp = client.post(URL, json=corpo(), headers={"Authorization": f"Bearer {raw}"})
    assert resp.status_code == 401


def test_jwt_do_dono_nao_abre_a_ingestao(client: TestClient, cadastro):
    headers = {"Authorization": f"Bearer {cadastro['access_token']}"}
    assert client.post(URL, json=corpo(), headers=headers).status_code == 401


def test_credencial_e_conferida_antes_do_corpo(client: TestClient, tenant_id):
    resp = client.post(
        URL, json={"evento": "nao-existe"}, headers={"Authorization": "Bearer nao-existe"}
    )
    assert resp.status_code == 401


def test_corpo_invalido_com_credencial_valida_422(client: TestClient, credencial):
    resp = client.post(URL, json=corpo(contato={"nome": "Sem Canal"}), headers=credencial)
    assert resp.status_code == 422


def test_rota_removida_no_270_nao_volta_com_cors_aberto(client: TestClient):
    resp = client.post(
        "/public/leads/qualquer", json={}, headers={"Origin": "https://site-qualquer.example"}
    )
    assert resp.status_code in (404, 405)
    assert "access-control-allow-origin" not in resp.headers


def test_ingestao_nao_tem_cors_para_navegador(client: TestClient):
    resp = client.options(
        URL,
        headers={
            "Origin": "https://nexuspublica.com.br",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert resp.headers.get("access-control-allow-origin") != "https://nexuspublica.com.br"
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd F:/Projetos/e1p/_wt-ingest-atribuicao/apps/api && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m pytest tests/test_lead_ingest_router.py -v`
Expected: FAIL — `assert 404 == 201` (rota inexistente) e `test_rota_removida_no_270...` falha porque o middleware injeta `access-control-allow-origin`.

- [ ] **Step 3: Implementar a rota e registrá-la**

Criar `apps/api/app/modules/lead_ingest/router.py`:

```python
"""`POST /public/ingest/leads` — entrada servidor-a-servidor de leads com atribuição.

Usa `get_db` (sessão GLOBAL, sem tenant) SÓ para resolver a credencial em `machine_tokens`,
tabela global sem RLS — o mesmo uso legítimo do login sobre `users` e do Atalho do iOS sobre
`device_tokens`. Todo dado de negócio é lido e escrito numa `tenant_session` aberta com o
tenant DO TOKEN (nunca do corpo — spec §6.1), via `get_tenant_session_factory`, como a página
pública faz com o tenant do snapshot.

Sem CORS de propósito: o token de máquina não pode morar num navegador.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_db, get_tenant_session_factory
from app.modules.lead_ingest import service
from app.modules.lead_ingest.schemas import IngestIn, IngestOut
from app.modules.machine_tokens import service as machine_tokens_service
from app.modules.machine_tokens.models import SCOPE_LEAD_INGEST, MachineToken

router = APIRouter(prefix="/public/ingest", tags=["lead-ingest-public"])


def credencial_de_ingestao(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> MachineToken:
    """Resolvida ANTES do corpo: credencial ruim é 401 mesmo com corpo inválido."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credencial ausente")
    try:
        return machine_tokens_service.resolve(
            db, raw=authorization.split(" ", 1)[1].strip(), scope=SCOPE_LEAD_INGEST
        )
    except machine_tokens_service.MachineTokenError as e:
        raise HTTPException(e.status_code, str(e)) from e


@router.post("/leads", response_model=IngestOut, status_code=status.HTTP_201_CREATED)
def ingest_lead(
    dados: IngestIn,
    response: Response,
    credencial: MachineToken = Depends(credencial_de_ingestao),
    session_factory=Depends(get_tenant_session_factory),
) -> IngestOut:
    with session_factory(credencial.tenant_id) as tdb:
        resultado = service.ingest(tdb, tenant_id=credencial.tenant_id, dados=dados)
    if not resultado.processado:
        response.status_code = status.HTTP_200_OK
    return IngestOut(
        resultado="processado" if resultado.processado else "ja_processado",
        contato_id=resultado.contato_id,
    )
```

Em `apps/api/app/modules/__init__.py`, depois de `from app.modules.juridico.router import router as juridico_router`, acrescentar:

```python
from app.modules.lead_ingest.router import router as lead_ingest_router
```

e, em `ALL_ROUTERS`, depois de `    juridico_router,`, acrescentar:

```python
    lead_ingest_router,
```

- [ ] **Step 4: Rodar a guarda de tenancy e ver falhar**

Run: `cd F:/Projetos/e1p/_wt-ingest-atribuicao/apps/api && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m pytest tests/test_tenancy_guard.py -v`
Expected: FAIL em `test_no_business_module_uses_get_db` com `['lead_ingest']`.

- [ ] **Step 5: Registrar o uso legítimo na ALLOWLIST**

Em `apps/api/tests/test_tenancy_guard.py`, na docstring, depois do item de `device_tokens` (que termina em `nenhum dado de negócio.`), acrescentar:

```
  - lead_ingest    → `POST /public/ingest/leads` resolve a credencial em `machine_tokens`
                  (tabela GLOBAL sem RLS, só hash sha256 + metadado) pela sessão global e então
                  abre `tenant_session` com o tenant DO TOKEN para todo dado de negócio — mesmo
                  padrão de pages/quotes/contracts/whatsapp_inbox.
```

e trocar:

```python
    "whatsapp_inbox", "device_tokens",
}
```

por:

```python
    "whatsapp_inbox", "device_tokens", "lead_ingest",
}
```

- [ ] **Step 6: Remover o middleware de CORS morto**

Substituir o conteúdo de `apps/api/app/main.py` por:

```python
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import composicao  # noqa: F401 — a fiacao e as guardas fail-closed rodam no import
from app.config import settings
from app.modules import ALL_ROUTERS

# Sem isto, o root logger fica sem handler (só o "lastResort" do Python, WARNING+ pra stderr) —
# logger.info/exception de core/email.py, core/whatsapp.py, core/payment_gateway.py etc. nunca
# aparecem em `docker logs`. Mesmo padrão já usado em app/worker.py.
logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="e1p API",
    description="Backend multi-tenant da plataforma e1p (Empresa de 1 Pessoa)",
    version="0.0.0",
)

# CORS só para o front do próprio e1p. NÃO há exceção para rota pública: a única que existia
# (`PublicLeadsCORSMiddleware`, CORS aberto para `/public/leads/*`) sobrou morta depois que a
# rota foi apagada no PR #270 e saiu em 2026-09-30. A ingestão nova (`/public/ingest/leads`) é
# servidor-a-servidor — o token de máquina não pode morar num navegador.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Módulos de negócio (vão sendo registrados conforme construídos — ver app/modules/__init__.py)
for router in ALL_ROUTERS:
    app.include_router(router)


@app.get("/health", tags=["infra"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": "e1p-api", "env": settings.environment}
```

Em `infra/docker-compose.traefik.yml`, trocar as duas linhas:

```yaml
      # mais específico (maior prioridade) só pra `/p/`. `/p/:slug` já é público/sem-sessão por
      # design (mesmo padrão de CORS aberto de `/public/leads/*` — ver PublicLeadsCORSMiddleware),
      # então não há dado sensível em jogo pra esse risco de clickjacking valer a pena.
```

por:

```yaml
      # mais específico (maior prioridade) só pra `/p/`. `/p/:slug` já é público/sem-sessão por
      # design, então não há dado sensível em jogo pra esse risco de clickjacking valer a pena.
```

- [ ] **Step 7: Rodar e ver passar**

Run: `cd F:/Projetos/e1p/_wt-ingest-atribuicao/apps/api && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m pytest tests/test_lead_ingest_router.py tests/test_tenancy_guard.py tests/test_health.py tests/test_pages.py -v`
Expected: todos PASS.

Run: `cd F:/Projetos/e1p/_wt-ingest-atribuicao/apps/api && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m ruff check . --fix && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m ruff check .`
Expected: `All checks passed!`

- [ ] **Step 8: Commit**

```bash
cd F:/Projetos/e1p/_wt-ingest-atribuicao && git add apps/api/app/modules/lead_ingest/router.py apps/api/app/modules/__init__.py apps/api/tests/test_tenancy_guard.py apps/api/app/main.py infra/docker-compose.traefik.yml apps/api/tests/test_lead_ingest_router.py && git commit -m "feat(lead-ingest): POST /public/ingest/leads com credencial de máquina e sem CORS" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Prova em Postgres real (RLS, isolamento e corrida)

**Files:**
- Test: `apps/api/tests/test_lead_ingest_rls.py`

**Interfaces:**
- Consumes: migrations 0088-0090; `ingest_service.ingest`; `machine_tokens_service.create_token/resolve`; `crm_service.absorb_lead` (substituído por versão lenta no teste de corrida); `tests.lead_ingest_apoio.payload`.
- Produces: nada para outras tasks (só prova).

O que a suíte SQLite não consegue provar: (1) `lead_ingest_records` é fail-closed entre tenants; (2) a MESMA chave em dois tenants processa nos dois (a unicidade é por tenant); (3) contato existente no tenant B não é reaproveitado por token do tenant A — no SQLite, `_find_existing` acharia (não há RLS); (4) dois reenvios simultâneos da mesma chave têm UM efeito; (5) `machine_tokens` é legível pelo papel `e1p_app` sem GUC (o caminho de produção via `get_db`).

- [ ] **Step 1: Escrever o teste**

Criar `apps/api/tests/test_lead_ingest_rls.py`:

```python
"""Ingestão de leads sob RLS REAL (papel não-superusuário `e1p_app`, Postgres via testcontainers).

Mesmo bootstrap de `test_crm_events_rls.py`: engine cru da URL do container, migrations com
`alembic upgrade head` como `e1p_app`. Cada caso negativo tem controle positivo.

Marcado `rls_e2e`: NÃO roda no `pytest -q` (suíte SQLite), só no job `cross-tenant-rls` do CI
ou manualmente com Docker (`pytest -m rls_e2e`).
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest

pytest.importorskip("testcontainers.postgres")

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402
from testcontainers.postgres import PostgresContainer  # noqa: E402

from app.core import events  # noqa: E402
from app.modules.crm import service as crm_service  # noqa: E402
from app.modules.lead_ingest import service as ingest_service  # noqa: E402
from app.modules.machine_tokens import service as machine_tokens_service  # noqa: E402
from app.modules.machine_tokens.models import SCOPE_LEAD_INGEST  # noqa: E402
from tests.lead_ingest_apoio import payload  # noqa: E402

pytestmark = pytest.mark.rls_e2e

_ROOT_USER = "e1p_root"
_ROOT_PASS = "rootpass"  # noqa: S105 (senha efêmera do container de teste)
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


def _run_migrations_as_app(app_url: str) -> None:
    from alembic import command
    from alembic.config import Config

    from app.config import settings

    original_url = settings.database_url
    settings.database_url = app_url
    try:
        cfg = Config(str(_API_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(_API_DIR / "migrations"))
        command.upgrade(cfg, "head")
    finally:
        settings.database_url = original_url


@pytest.fixture(scope="module")
def ambiente():
    with PostgresContainer(
        "postgres:16-alpine",
        username=_ROOT_USER,
        password=_ROOT_PASS,
        dbname=_DB_NAME,
        driver="psycopg",
    ) as pg:
        host = pg.get_container_host_ip()
        port = pg.get_exposed_port(5432)
        super_url = f"postgresql+psycopg://{_ROOT_USER}:{_ROOT_PASS}@{host}:{port}/{_DB_NAME}"
        app_url = f"postgresql+psycopg://e1p_app:{_APP_PASS}@{host}:{port}/{_DB_NAME}"
        _bootstrap_rls_role(super_url)
        _run_migrations_as_app(app_url)
        yield {"url": app_url, "tenant_a": str(uuid4()), "tenant_b": str(uuid4())}


@pytest.fixture(autouse=True)
def _sem_assinantes():
    # `move_client` emite `crm.client.moved`; o assinante de notifications abriria
    # `tenant_session` na URL de settings, não na do container.
    events.clear()
    yield
    events.clear()


@contextmanager
def _sessao(url: str, tenant_id: str | None):
    """Espelho de `db.session.tenant_session` apontado ao container (GUC em escopo de sessão)."""
    engine = create_engine(url, poolclass=NullPool)
    conn = engine.connect()
    try:
        if tenant_id is not None:
            conn.execute(
                text("SELECT set_config('app.current_tenant_id', :t, false)"), {"t": tenant_id}
            )
            conn.commit()
        db = Session(bind=conn, autoflush=False, expire_on_commit=False)
        try:
            yield db
        finally:
            db.close()
    finally:
        conn.close()
        engine.dispose()


def _email() -> str:
    return f"{uuid4().hex[:12]}@exemplo.gov.br"


def _ingere(url: str, tenant_id: str, **sobre):
    with _sessao(url, tenant_id) as db:
        return ingest_service.ingest(db, tenant_id=tenant_id, dados=payload(**sobre))


def test_registro_de_ingestao_e_isolado_e_fail_closed(ambiente):
    url, a, b = ambiente["url"], ambiente["tenant_a"], ambiente["tenant_b"]
    chave = f"site:lead:{uuid4()}"
    assert _ingere(url, a, chave_idempotencia=chave, contato={"email": _email()}).processado

    def _conta(tenant_id: str | None) -> int:
        with _sessao(url, tenant_id) as db:
            return db.scalar(
                text("SELECT count(*) FROM lead_ingest_records WHERE chave_idempotencia = :c"),
                {"c": chave},
            )

    assert _conta(a) == 1  # controle positivo: o dono enxerga
    assert _conta(b) == 0  # outro tenant não enxerga
    assert _conta(None) == 0  # sessão sem GUC não enxerga nada


def test_mesma_chave_em_dois_tenants_processa_nos_dois(ambiente):
    url, a, b = ambiente["url"], ambiente["tenant_a"], ambiente["tenant_b"]
    chave = f"kiwify:{uuid4()}:compra_aprovada"
    for tenant_id in (a, b):
        resultado = _ingere(
            url, tenant_id, evento="compra_aprovada", chave_idempotencia=chave,
            contato={"email": _email()},
        )
        assert resultado.processado is True


def test_contato_de_outro_tenant_nao_e_reaproveitado(ambiente):
    url, a, b = ambiente["url"], ambiente["tenant_a"], ambiente["tenant_b"]
    email, telefone = _email(), f"(11) 9{uuid4().int % 10**8:08d}"
    contato = {"nome": "Maria", "email": email, "telefone": telefone}
    em_b = _ingere(url, b, chave_idempotencia=f"site:lead:{uuid4()}", contato=contato)
    em_a = _ingere(url, a, chave_idempotencia=f"site:lead:{uuid4()}", contato=contato)

    assert em_a.processado is True
    assert em_a.contato_id != em_b.contato_id
    with _sessao(url, a) as db:
        assert db.scalar(
            text("SELECT tenant_id FROM clients WHERE id = :id"), {"id": em_a.contato_id}
        ) == a
        assert db.scalar(
            text("SELECT count(*) FROM clients WHERE id = :id"), {"id": em_b.contato_id}
        ) == 0
    with _sessao(url, b) as db:  # controle positivo: B continua com o seu, intocado
        assert db.scalar(
            text("SELECT count(*) FROM facts WHERE client_id = :id AND kind = :k"),
            {"id": em_b.contato_id, "k": "comercial.lead.recebido"},
        ) == 1


def test_retentativas_concorrentes_da_mesma_chave_so_uma_tem_efeito(ambiente, monkeypatch):
    url, a = ambiente["url"], ambiente["tenant_a"]
    # Aquece: perfil e colunas do Kanban já existem, senão as duas threads disputariam o seed.
    _ingere(url, a, chave_idempotencia=f"aquece:{uuid4()}", contato={"email": _email()})

    original = crm_service.absorb_lead

    def _lento(*args, **kwargs):
        # Segura a reivindicação ABERTA (não commitada) tempo suficiente para a outra thread
        # bater no índice único e ficar esperando — a janela real do reenvio da Kiwify.
        time.sleep(1.0)
        return original(*args, **kwargs)

    monkeypatch.setattr(crm_service, "absorb_lead", _lento)
    chave, email = f"kiwify:{uuid4()}:lead", _email()
    largada = threading.Barrier(2)

    def _envia():
        largada.wait()
        return _ingere(url, a, chave_idempotencia=chave, contato={"email": email})

    with ThreadPoolExecutor(max_workers=2) as pool:
        futuros = [pool.submit(_envia), pool.submit(_envia)]
        resultados = [f.result(timeout=30) for f in futuros]

    assert sorted(r.processado for r in resultados) == [False, True]
    with _sessao(url, a) as db:
        assert db.scalar(
            text(
                "SELECT count(*) FROM facts f JOIN lead_ingest_records r ON f.subject_id = r.id "
                "WHERE r.chave_idempotencia = :c AND f.kind = 'comercial.lead.recebido'"
            ),
            {"c": chave},
        ) == 1
        assert db.scalar(text("SELECT count(*) FROM clients WHERE email = :e"), {"e": email}) == 1


def test_credencial_de_maquina_resolve_sem_tenant_na_sessao(ambiente):
    """O caminho de produção: `get_db` (sem GUC) lê `machine_tokens`, tabela global."""
    url, a = ambiente["url"], ambiente["tenant_a"]
    with _sessao(url, None) as db:
        _, raw = machine_tokens_service.create_token(
            db, tenant_id=a, name="site", scope=SCOPE_LEAD_INGEST
        )
        assert machine_tokens_service.resolve(db, raw=raw, scope=SCOPE_LEAD_INGEST).tenant_id == a
```

- [ ] **Step 2: Rodar (exige Docker ligado)**

Run: `cd F:/Projetos/e1p/_wt-ingest-atribuicao/apps/api && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m pytest tests/test_lead_ingest_rls.py -m rls_e2e -v`
Expected: 5 PASS. Se algum falhar, é defeito real das Tasks 1-9 (migração sem RLS, filtro de tenant faltando, corrida não serializada) — corrigir na task dona, não no teste. Se aparecer `5 skipped`, o `testcontainers` não está no venv: o job do CI reprovaria do mesmo jeito.

Prova de que o teste de corrida morde: comentar temporariamente o `try/except IntegrityError` de `registro.reivindicar` (deixando só `db.flush()`) e rodar `-k concorrentes` — deve falhar com `IntegrityError` saindo da thread. Desfazer.

- [ ] **Step 3: Rodar toda a suíte `rls_e2e` (o CI exige ≥ 9 executados)**

Run: `cd F:/Projetos/e1p/_wt-ingest-atribuicao/apps/api && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m pytest -q -m rls_e2e`
Expected: tudo PASS, nenhum skipped.

- [ ] **Step 4: Commit**

```bash
cd F:/Projetos/e1p/_wt-ingest-atribuicao && git add apps/api/tests/test_lead_ingest_rls.py && git commit -m "test(lead-ingest): RLS real, isolamento entre tenants e corrida de reenvios no Postgres" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Script de administração (emitir credencial, configurar produto e funis)

**Files:**
- Create: `apps/api/app/scripts/lead_ingest_admin.py`
- Test: `apps/api/tests/test_lead_ingest_admin.py`

**Interfaces:**
- Consumes: `machine_tokens_service.create_token/list_tokens/revoke`, `MachineTokenError` (Task 1); `config.EVENTOS`, `config.validar_produto` (Task 3); `settings_service.get_profile`; `Funnel`; `Tenant`; `get_db`, `tenant_session`.
- Produces: `AdminError`; `_sessao_global() -> ContextManager[Session]`; `tenant_por_slug(db, slug: str) -> Tenant`; `emitir_token(db, *, slug: str, nome: str) -> tuple[MachineToken, str]`; `ler_funis(pares: list[str]) -> dict[str, str]`; `configurar(tdb, *, tenant_id: str, produto: str | None, funis: dict[str, str]) -> dict`; `main(argv: list[str] | None = None) -> int`.

**Por que script e não tela.** A credencial é emitida uma vez por integração e trocada raramente; a configuração muda quando o dono monta um funil novo. Uma tela em `/config` seria superfície de ataque e de manutenção (web + shared-types + e2e de 360px) para um gesto raro. Mesmo padrão de `merge_duplicate_clients.py`.

- [ ] **Step 1: Escrever os testes que falham**

Criar `apps/api/tests/test_lead_ingest_admin.py`:

```python
"""`app/scripts/lead_ingest_admin.py`: emitir credencial e configurar produto/funis por tenant."""
import json
from contextlib import contextmanager

import pytest
from sqlalchemy.orm import Session

from app.modules.auth.models import Tenant
from app.modules.funnels.models import Funnel
from app.modules.machine_tokens import service as machine_tokens_service
from app.modules.machine_tokens.models import SCOPE_LEAD_INGEST
from app.modules.settings import service as settings_service
from app.scripts import lead_ingest_admin as admin


@pytest.fixture()
def tenant(db: Session) -> Tenant:
    t = Tenant(slug="nexus", legal_name="Nexus Pública", document="11222333000181")
    db.add(t)
    db.commit()
    return t


@pytest.fixture()
def mesma_sessao(db: Session, monkeypatch):
    @contextmanager
    def _mesma(*_args, **_kwargs):
        yield db

    monkeypatch.setattr(admin, "_sessao_global", _mesma)
    monkeypatch.setattr(admin, "tenant_session", _mesma)


def _funil(db: Session, tenant_id: str, nome: str) -> Funnel:
    funil = Funnel(tenant_id=tenant_id, name=nome, nodes=[{"id": "n1"}], edges=[])
    db.add(funil)
    db.commit()
    return funil


def test_emitir_token_resolve_o_tenant_pelo_slug(db: Session, tenant: Tenant):
    token, raw = admin.emitir_token(db, slug=" Nexus ", nome="site nexuspublica.com.br")
    assert token.tenant_id == tenant.id
    assert machine_tokens_service.resolve(db, raw=raw, scope=SCOPE_LEAD_INGEST).id == token.id


def test_slug_desconhecido_e_erro_de_operador(db: Session, tenant: Tenant):
    with pytest.raises(admin.AdminError, match="Tenant não encontrado"):
        admin.emitir_token(db, slug="nao-existe", nome="x")


def test_ler_funis():
    assert admin.ler_funis(["lead=f1", " compra_aprovada = f2 ", "renovacao="]) == {
        "lead": "f1", "compra_aprovada": "f2", "renovacao": "",
    }


@pytest.mark.parametrize("par", ["lead", "compra=f1"])
def test_ler_funis_recusa_formato_ou_evento_invalido(par: str):
    with pytest.raises(admin.AdminError):
        admin.ler_funis([par])


def test_configurar_grava_produto_e_funis_e_mescla(db: Session, tenant: Tenant):
    f1 = _funil(db, tenant.id, "Boas-vindas")
    f2 = _funil(db, tenant.id, "Recuperação")
    admin.configurar(db, tenant_id=tenant.id, produto="publia", funis={"lead": f1.id})
    resultado = admin.configurar(
        db, tenant_id=tenant.id, produto=None, funis={"carrinho_abandonado": f2.id}
    )
    assert resultado == {
        "produto": "publia", "funis": {"lead": f1.id, "carrinho_abandonado": f2.id},
    }
    assert settings_service.get_profile(db, tenant.id).lead_ingest_config == resultado


def test_configurar_com_funil_vazio_remove_o_mapeamento(db: Session, tenant: Tenant):
    f1 = _funil(db, tenant.id, "Boas-vindas")
    admin.configurar(db, tenant_id=tenant.id, produto="publia", funis={"lead": f1.id})
    resultado = admin.configurar(db, tenant_id=tenant.id, produto=None, funis={"lead": ""})
    assert resultado == {"produto": "publia", "funis": {}}


def test_configurar_recusa_funil_inexistente_sem_gravar_nada(db: Session, tenant: Tenant):
    with pytest.raises(admin.AdminError, match="Funil não encontrado"):
        admin.configurar(db, tenant_id=tenant.id, produto="publia", funis={"lead": "nao-existe"})
    assert settings_service.get_profile(db, tenant.id).lead_ingest_config == {}


def test_configurar_recusa_produto_invalido(db: Session, tenant: Tenant):
    with pytest.raises(admin.AdminError):
        admin.configurar(db, tenant_id=tenant.id, produto="Publ.IA", funis={})


def test_main_emitir_token_imprime_o_cru_uma_vez(db, tenant, mesma_sessao, capsys):
    assert admin.main(["emitir-token", "--tenant", "nexus", "--nome", "site"]) == 0
    raw = capsys.readouterr().out.strip().splitlines()[-1]
    assert machine_tokens_service.resolve(db, raw=raw, scope=SCOPE_LEAD_INGEST).tenant_id == (
        tenant.id
    )


def test_main_com_slug_errado_sai_com_2(db, tenant, mesma_sessao, capsys):
    assert admin.main(["configurar", "--tenant", "nao-existe", "--produto", "publia"]) == 2
    assert "Tenant não encontrado" in capsys.readouterr().err


def test_main_configurar_e_mostrar(db, tenant, mesma_sessao, capsys):
    f1 = _funil(db, tenant.id, "Boas-vindas")
    argv = ["configurar", "--tenant", "nexus", "--produto", "publia", "--funil", f"lead={f1.id}"]
    assert admin.main(argv) == 0
    capsys.readouterr()
    assert admin.main(["mostrar", "--tenant", "nexus"]) == 0
    assert json.loads(capsys.readouterr().out) == {"produto": "publia", "funis": {"lead": f1.id}}


def test_main_listar_e_revogar(db, tenant, mesma_sessao, capsys):
    token, raw = admin.emitir_token(db, slug="nexus", nome="site")
    assert admin.main(["listar-tokens", "--tenant", "nexus"]) == 0
    assert token.id in capsys.readouterr().out
    assert admin.main(["revogar-token", "--id", token.id]) == 0
    with pytest.raises(machine_tokens_service.MachineTokenError):
        machine_tokens_service.resolve(db, raw=raw, scope=SCOPE_LEAD_INGEST)
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd F:/Projetos/e1p/_wt-ingest-atribuicao/apps/api && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m pytest tests/test_lead_ingest_admin.py -v`
Expected: erro de coleta `ImportError: cannot import name 'lead_ingest_admin' from 'app.scripts'`.

- [ ] **Step 3: Implementar**

Criar `apps/api/app/scripts/lead_ingest_admin.py`:

```python
"""Administração da ingestão de leads (`POST /public/ingest/leads`) — sem tela, de propósito.

    docker compose exec api python -m app.scripts.lead_ingest_admin emitir-token --tenant <slug> --nome "site nexuspublica.com.br"
    docker compose exec api python -m app.scripts.lead_ingest_admin listar-tokens --tenant <slug>
    docker compose exec api python -m app.scripts.lead_ingest_admin revogar-token --id <uuid>
    docker compose exec api python -m app.scripts.lead_ingest_admin configurar --tenant <slug> --produto publia --funil lead=<funnel_id> --funil carrinho_abandonado=<funnel_id>
    docker compose exec api python -m app.scripts.lead_ingest_admin mostrar --tenant <slug>

O token cru é impresso UMA vez, na última linha: guarde-o direto no cofre do site. Erro de
operador (slug, evento ou funil inexistente) sai com código 2 e mensagem, nunca traceback.

Isolamento: `tenants` e `machine_tokens` são globais (sessão de `get_db`, filtro explícito); a
configuração mora em `tenant_profiles` (RLS) e é escrita numa `tenant_session` do tenant
resolvido pelo slug. Passo a passo de produção: `docs/RUNBOOK-INGESTAO-DE-LEADS.md`.
"""  # noqa: E501
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.db.session import get_db, tenant_session
from app.modules.auth.models import Tenant
from app.modules.funnels.models import Funnel
from app.modules.lead_ingest import config
from app.modules.machine_tokens import service as machine_tokens_service
from app.modules.machine_tokens.models import SCOPE_LEAD_INGEST, MachineToken
from app.modules.settings import service as settings_service

ATOR = "script:lead_ingest_admin"


class AdminError(Exception):
    """Entrada inválida do operador. Vira mensagem e exit 2, nunca traceback."""


@contextmanager
def _sessao_global() -> Iterator[Session]:
    gen = get_db()
    db = next(gen)
    try:
        yield db
    finally:
        gen.close()


def tenant_por_slug(db: Session, slug: str) -> Tenant:
    # `tenants` é GLOBAL, sem RLS — o filtro explícito é a exceção documentada da Regra de
    # Ouro nº 1, a mesma do login.
    tenant = db.scalar(select(Tenant).where(Tenant.slug == slug.strip().lower()))
    if tenant is None:
        raise AdminError(f"Tenant não encontrado: {slug}")
    return tenant


def emitir_token(db: Session, *, slug: str, nome: str) -> tuple[MachineToken, str]:
    tenant = tenant_por_slug(db, slug)
    return machine_tokens_service.create_token(
        db, tenant_id=tenant.id, name=nome, scope=SCOPE_LEAD_INGEST
    )


def ler_funis(pares: list[str]) -> dict[str, str]:
    """`["lead=<id>", "renovacao="]` → `{"lead": "<id>", "renovacao": ""}` (`""` remove)."""
    funis: dict[str, str] = {}
    for par in pares:
        evento, separador, funil_id = par.partition("=")
        evento = evento.strip()
        if not separador:
            raise AdminError(f"Use evento=funil_id; recebi: {par}")
        if evento not in config.EVENTOS:
            raise AdminError(
                f"Evento desconhecido: {evento}. Válidos: {', '.join(config.EVENTOS)}"
            )
        funis[evento] = funil_id.strip()
    return funis


def configurar(
    tdb: Session, *, tenant_id: str, produto: str | None, funis: dict[str, str]
) -> dict:
    """Mescla na configuração atual e devolve a resultante.

    Nada é gravado se algo for inválido: o perfil só recebe o dicionário novo no fim.
    """
    perfil = settings_service.get_profile(tdb, tenant_id)
    atual = dict(perfil.lead_ingest_config or {})
    if produto is not None:
        try:
            atual["produto"] = config.validar_produto(produto)
        except ValueError as e:
            raise AdminError(str(e)) from e
    mapa = dict(atual.get("funis") or {})
    for evento, funil_id in funis.items():
        if not funil_id:
            mapa.pop(evento, None)
            continue
        # RLS: só enxerga funil DESTE tenant — um id de outro tenant cai aqui também.
        if tdb.get(Funnel, funil_id) is None:
            raise AdminError(f"Funil não encontrado neste tenant: {funil_id}")
        mapa[evento] = funil_id
    atual["funis"] = mapa
    # Dicionário NOVO, não mutação do antigo: coluna JSON sem MutableDict — o ORM só percebe
    # a mudança por atribuição.
    perfil.lead_ingest_config = atual
    audit.record(
        tdb, tenant_id=tenant_id, actor=ATOR, action="settings.lead_ingest.configure",
        target=perfil.id,
    )
    tdb.commit()
    return atual


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.scripts.lead_ingest_admin",
        description="Credencial e configuração da ingestão de leads (POST /public/ingest/leads).",
    )
    sub = parser.add_subparsers(dest="comando", required=True)

    emitir = sub.add_parser("emitir-token", help="Emite credencial lead_ingest (mostrada UMA vez).")
    emitir.add_argument("--tenant", required=True, help="slug do tenant")
    emitir.add_argument("--nome", required=True, help="quem usa (ex.: site nexuspublica.com.br)")

    listar = sub.add_parser("listar-tokens", help="Credenciais do tenant, ativas e revogadas.")
    listar.add_argument("--tenant", required=True, help="slug do tenant")

    revogar = sub.add_parser("revogar-token", help="Revoga uma credencial pelo id.")
    revogar.add_argument("--id", required=True, help="id da credencial (de listar-tokens)")

    configurar_cmd = sub.add_parser("configurar", help="Grava produto e/ou funil por evento.")
    configurar_cmd.add_argument("--tenant", required=True, help="slug do tenant")
    configurar_cmd.add_argument("--produto", default=None, help="slug do produto (ex.: publia)")
    configurar_cmd.add_argument(
        "--funil", action="append", default=[],
        help="evento=funnel_id (repetível; evento= remove o mapeamento)",
    )

    mostrar = sub.add_parser("mostrar", help="Mostra a configuração atual do tenant.")
    mostrar.add_argument("--tenant", required=True, help="slug do tenant")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.comando == "emitir-token":
            with _sessao_global() as db:
                token, raw = emitir_token(db, slug=args.tenant, nome=args.nome)
            print(f"Credencial {token.id} emitida para o tenant {token.tenant_id} "
                  f"({token.scope}).")
            print("Token (aparece só agora; guarde no cofre do site):")
            print(raw)
            return 0
        if args.comando == "listar-tokens":
            with _sessao_global() as db:
                tenant = tenant_por_slug(db, args.tenant)
                for t in machine_tokens_service.list_tokens(db, tenant_id=tenant.id):
                    situacao = "revogada" if t.revoked_at else "ativa"
                    print(f"{t.id}  {situacao:8}  {t.scope}  {t.name}  último uso: "
                          f"{t.last_used_at or 'nunca'}")
            return 0
        if args.comando == "revogar-token":
            with _sessao_global() as db:
                try:
                    token = machine_tokens_service.revoke(db, token_id=args.id)
                except machine_tokens_service.MachineTokenError as e:
                    raise AdminError(str(e)) from e
            print(f"Credencial {token.id} revogada em {token.revoked_at}.")
            return 0
        with _sessao_global() as db:
            tenant_id = tenant_por_slug(db, args.tenant).id
        with tenant_session(tenant_id) as tdb:
            if args.comando == "configurar":
                resultado = configurar(
                    tdb, tenant_id=tenant_id, produto=args.produto, funis=ler_funis(args.funil)
                )
            else:
                resultado = dict(settings_service.get_profile(tdb, tenant_id).lead_ingest_config)
        print(json.dumps(resultado, ensure_ascii=False, indent=2))
        return 0
    except AdminError as e:
        print(f"Erro: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd F:/Projetos/e1p/_wt-ingest-atribuicao/apps/api && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m pytest tests/test_lead_ingest_admin.py tests/test_audit_target_e_id_gate.py tests/test_audit_target_flush_gate.py -v`
Expected: todos PASS.

Run: `cd F:/Projetos/e1p/_wt-ingest-atribuicao/apps/api && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m ruff check . --fix && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m ruff check .`
Expected: `All checks passed!` (se `E501` acusar alguma linha de código fora da docstring, quebre a linha; o `noqa: E501` cobre só a docstring com os comandos longos).

- [ ] **Step 5: Commit**

```bash
cd F:/Projetos/e1p/_wt-ingest-atribuicao && git add apps/api/app/scripts/lead_ingest_admin.py apps/api/tests/test_lead_ingest_admin.py && git commit -m "feat(lead-ingest): script para emitir credencial e configurar produto e funis por tenant" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: Leitor do código de origem (puro)

**Files:**
- Create: `apps/api/app/modules/lead_ingest/codigo.py`
- Test: `apps/api/tests/test_lead_ingest_codigo.py`

**Interfaces:**
- Produces: `CANAIS: dict[str, str]` (`ig→instagram`, `gg→google`, `em→email`, `wa→whatsapp`, `pt→parceria`); `TAMANHO_MAX_CODIGO = 20`; `CODIGO_SEM_ORIGEM = "np-lp"`; `CodigoLido(codigo: str, origem: str | None)`; `ler_codigo(texto: str | None) -> CodigoLido | None`.

**`np-lp`.** A spec §5.4 manda o botão usar `np-lp` quando não há código — e `np` não é canal do §4.1. É reconhecido como "veio da landing sem toque rastreado": devolve `origem=None` (nada de `origem:` nem `post:` inventados; spec §5.3: "nunca classificar silenciosamente como direto").

- [ ] **Step 1: Escrever os testes que falham**

Criar `apps/api/tests/test_lead_ingest_codigo.py`:

```python
"""Leitura do código `<canal>-<tipo>-<id>` na mensagem de WhatsApp (spec §4.1 e §6.3)."""
import unicodedata

import pytest

from app.modules.lead_ingest.codigo import CodigoLido, ler_codigo


@pytest.mark.parametrize(
    ("texto", "codigo", "origem"),
    [
        ("Olá! Quero saber da Publ.IA (código ig-r-c8abc)", "ig-r-c8abc", "instagram"),
        ("CÓDIGO IG-R-C8ABC", "ig-r-c8abc", "instagram"),
        ("codigo   gg-s-out26a obrigado", "gg-s-out26a", "google"),
        ("código: em-n12-topo", "em-n12-topo", "email"),
        ("Oi (código wa-l-abc1).", "wa-l-abc1", "whatsapp"),
        ("código pt-x-parc1", "pt-x-parc1", "parceria"),
        (unicodedata.normalize("NFD", "código ig-b-bio1"), "ig-b-bio1", "instagram"),
        ("código ig-r-" + "a" * 15, "ig-r-" + "a" * 15, "instagram"),  # exatamente 20
        ("Olá! Quero saber da Publ.IA (código np-lp)", "np-lp", None),
    ],
)
def test_le_codigo_valido(texto, codigo, origem):
    assert ler_codigo(texto) == CodigoLido(codigo=codigo, origem=origem)


@pytest.mark.parametrize(
    "texto",
    [
        None,
        "",
        "Olá, quero saber da Publ.IA",
        "ig-r-c8abc sem a palavra-chave",
        "meu código pt-br é esse",  # dois segmentos: não é código
        "código xx-r-abc",  # canal desconhecido
        "código ig-r-",
        "código ig-r-" + "a" * 16,  # 21 caracteres
    ],
)
def test_ignora_o_que_nao_e_codigo(texto):
    assert ler_codigo(texto) is None
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd F:/Projetos/e1p/_wt-ingest-atribuicao/apps/api && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m pytest tests/test_lead_ingest_codigo.py -v`
Expected: erro de coleta `ModuleNotFoundError: No module named 'app.modules.lead_ingest.codigo'`.

- [ ] **Step 3: Implementar**

Criar `apps/api/app/modules/lead_ingest/codigo.py`:

```python
"""Código de origem dentro da mensagem de WhatsApp (spec §4.1 e §6.3). Puro, sem I/O.

O site abre `wa.me` com a mensagem pronta "… (código ig-r-c8abc)". Formato do código:
`<canal>-<tipo>-<id>`, minúsculas, máx. 20 caracteres, canal ∈ ig gg em wa pt. O prefixo é o
que deixa o e1p derivar a origem sem consultar o site.

Tolerante ao que a pessoa (ou o teclado) faz com a mensagem pronta: maiúsculas, espaços extras,
"codigo" sem acento, dois-pontos, e acento DECOMPOSTO (o iOS às vezes manda "o" + acento
combinante em vez de "ó"; sem normalizar, "código" não casaria). Exige a palavra "código"
antes: um "ig-r-abc" solto no meio da conversa não é atribuição.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

CANAIS = {
    "ig": "instagram",
    "gg": "google",
    "em": "email",
    "wa": "whatsapp",
    "pt": "parceria",
}
TAMANHO_MAX_CODIGO = 20
# Botão da landing sem toque prévio (spec §5.4): veio do site, origem desconhecida.
CODIGO_SEM_ORIGEM = "np-lp"

_NA_MENSAGEM = re.compile(
    r"c[oó]digo\s*[:#]?\s*(?P<codigo>[a-z0-9]+(?:-[a-z0-9]+)+)(?![a-z0-9-])",
    re.IGNORECASE,
)
_FORMATO = re.compile(r"^(?P<canal>ig|gg|em|wa|pt)-[a-z0-9]+-[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(frozen=True)
class CodigoLido:
    codigo: str
    origem: str | None  # None = `np-lp`: veio da landing sem toque rastreado


def ler_codigo(texto: str | None) -> CodigoLido | None:
    if not texto:
        return None
    achado = _NA_MENSAGEM.search(unicodedata.normalize("NFC", texto))
    if achado is None:
        return None
    codigo = achado.group("codigo").lower()
    if len(codigo) > TAMANHO_MAX_CODIGO:
        return None
    if codigo == CODIGO_SEM_ORIGEM:
        return CodigoLido(codigo=codigo, origem=None)
    formato = _FORMATO.match(codigo)
    if formato is None:
        return None
    return CodigoLido(codigo=codigo, origem=CANAIS[formato.group("canal")])
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd F:/Projetos/e1p/_wt-ingest-atribuicao/apps/api && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m pytest tests/test_lead_ingest_codigo.py -v`
Expected: 17 PASS.

Run: `cd F:/Projetos/e1p/_wt-ingest-atribuicao/apps/api && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m ruff check . --fix && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m ruff check .`
Expected: `All checks passed!`

- [ ] **Step 5: Commit**

```bash
cd F:/Projetos/e1p/_wt-ingest-atribuicao && git add apps/api/app/modules/lead_ingest/codigo.py apps/api/tests/test_lead_ingest_codigo.py && git commit -m "feat(lead-ingest): leitor do código de origem na mensagem de WhatsApp" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: Código na 1ª mensagem de WhatsApp de contato novo

**Files:**
- Create: `apps/api/app/modules/lead_ingest/whatsapp.py`
- Modify: `apps/api/app/modules/whatsapp_inbox/service.py:144-165` (`_resolve_client` + wrapper), `:418-433` (chamada), `:492-501` (leitura do código), imports
- Test: `apps/api/tests/test_lead_ingest_whatsapp.py`

**Interfaces:**
- Consumes: `ler_codigo`, `CodigoLido` (Task 12); `config.produto` (Task 3); `somar_tags` (Task 5); `COM_ORIGEM_IDENTIFICADA` (Task 7); `facts.record`; `TenantProfile`; `Client`.
- Produces: `lead_ingest.whatsapp.aplicar_codigo_da_primeira_mensagem(db, *, tenant_id: str, cliente: Client, perfil: TenantProfile, texto: str | None, occurred_at: datetime | None) -> CodigoLido | None` (NÃO commita); `whatsapp_inbox.service._resolve_client(db, *, tenant_id, phone, name) -> tuple[Client, bool]`. `_get_or_create_client` continua com a mesma assinatura (usado por `tests/test_lead_portas.py`).

- [ ] **Step 1: Escrever os testes que falham**

Criar `apps/api/tests/test_lead_ingest_whatsapp.py`:

```python
"""Código de origem na 1ª mensagem de WhatsApp de um contato novo (spec §6.3)."""
import json

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import events
from app.core.facts import Fact
from app.core.whatsapp.inbound import InboundMessage
from app.modules.crm.models import Client
from app.modules.settings import service as settings_service
from app.modules.whatsapp_inbox import service as inbox_service

TENANT = "11111111-1111-1111-1111-111111111111"
FONE = "5511977776666"


@pytest.fixture(autouse=True)
def _sem_assinantes():
    events.clear()
    yield
    events.clear()


def _produto(db: Session, produto: str = "publia") -> None:
    perfil = settings_service.get_profile(db, TENANT)
    perfil.lead_ingest_config = {"produto": produto}
    db.commit()


def _recebe(db: Session, texto: str, *, msg_id: str = "wamid.1") -> None:
    inbox_service.ingest_webhook_payload(
        db, tenant_id=TENANT,
        messages=[InboundMessage(
            wa_message_id=msg_id, from_phone=FONE, kind="text", text_body=texto,
            media_ref=None, push_name="Maria",
        )],
    )


def _contato(db: Session) -> Client:
    return db.scalar(select(Client).where(Client.phone_key == FONE))


def _fatos_de_origem(db: Session, client_id: str) -> list[Fact]:
    return list(db.scalars(
        select(Fact).where(
            Fact.client_id == client_id, Fact.kind == "comercial.origem.identificada"
        )
    ).all())


def test_primeira_mensagem_com_codigo_aplica_origem_post_e_lead_whatsapp(db: Session):
    _produto(db)
    _recebe(db, "Olá! Quero saber da Publ.IA (código ig-r-c8abc)")
    contato = _contato(db)
    assert contato.source == "whatsapp"
    assert contato.tags == ["origem:instagram", "post:ig-r-c8abc", "publia:lead-whatsapp"]
    [fato] = _fatos_de_origem(db, contato.id)
    assert json.loads(fato.body)["codigo"] == "ig-r-c8abc"


def test_codigo_em_maiusculas_e_com_espacos_e_lido(db: Session):
    _produto(db)
    _recebe(db, "Olá!   CODIGO    IG-S-OUT26A  obrigado")
    assert "post:ig-s-out26a" in _contato(db).tags


def test_np_lp_marca_lead_whatsapp_sem_inventar_origem(db: Session):
    _produto(db)
    _recebe(db, "Olá! Quero saber da Publ.IA (código np-lp)")
    assert _contato(db).tags == ["publia:lead-whatsapp"]


def test_contato_que_ja_existia_nao_e_relido(db: Session):
    _produto(db)
    db.add(Client(tenant_id=TENANT, name="Maria", phone=FONE, phone_key=FONE, source="landing"))
    db.commit()
    _recebe(db, "Oi de novo (código ig-r-c8abc)")
    contato = _contato(db)
    assert contato.tags == []
    assert _fatos_de_origem(db, contato.id) == []


def test_segunda_mensagem_do_contato_novo_nao_troca_a_origem(db: Session):
    _produto(db)
    _recebe(db, "Olá (código ig-r-c8abc)", msg_id="wamid.1")
    _recebe(db, "achei também pelo google (código gg-s-xyz1)", msg_id="wamid.2")
    tags = _contato(db).tags
    assert "post:ig-r-c8abc" in tags
    assert "post:gg-s-xyz1" not in tags


def test_sem_produto_configurado_a_leitura_fica_desligada(db: Session):
    _recebe(db, "Olá (código ig-r-c8abc)")
    contato = _contato(db)
    assert contato.tags == []
    assert _fatos_de_origem(db, contato.id) == []


def test_mensagem_sem_codigo_so_cria_o_contato(db: Session):
    _produto(db)
    _recebe(db, "Oi, quanto custa?")
    contato = _contato(db)
    assert contato is not None
    assert contato.tags == []
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd F:/Projetos/e1p/_wt-ingest-atribuicao/apps/api && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m pytest tests/test_lead_ingest_whatsapp.py -v`
Expected: FAIL em `test_primeira_mensagem...`, `test_codigo_em_maiusculas...`, `test_np_lp...` e `test_segunda_mensagem...` (`assert [] == [...]`); os de "não lê" já passam.

- [ ] **Step 3: Implementar o aplicador**

Criar `apps/api/app/modules/lead_ingest/whatsapp.py`:

```python
"""Origem do lead que chega pelo WhatsApp com código (spec §6.3).

Chamado pelo inbox (`whatsapp_inbox/service.py::ingest_webhook_payload`) na 1ª mensagem de um
contato que a PRÓPRIA mensagem criou. **NÃO commita**: roda dentro da transação-por-mensagem do
inbox — tag e fato entram junto com a mensagem, ou nenhum dos dois.

Desligado por padrão: só lê código o tenant que configurou um `produto` (`lead_ingest/config.py`).
Num produto multi-tenant, "código pt-..." numa conversa qualquer não pode virar etiqueta de origem
para quem nunca pôs link com código no ar.
"""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy.orm import Session

from app.core import facts
from app.core.facts import COM_ORIGEM_IDENTIFICADA
from app.modules.crm.models import Client
from app.modules.lead_ingest import config
from app.modules.lead_ingest.codigo import CodigoLido, ler_codigo
from app.modules.lead_ingest.tags import somar_tags
from app.modules.settings.models import TenantProfile

ATOR = "whatsapp:inbox"


def aplicar_codigo_da_primeira_mensagem(
    db: Session,
    *,
    tenant_id: str,
    cliente: Client,
    perfil: TenantProfile,
    texto: str | None,
    occurred_at: datetime | None,
) -> CodigoLido | None:
    prefixo = config.produto(perfil)
    if prefixo is None:
        return None
    lido = ler_codigo(texto)
    if lido is None:
        return None
    novas = [f"{prefixo}:lead-whatsapp"]
    if lido.origem is not None:
        novas = [f"origem:{lido.origem}", f"post:{lido.codigo}", *novas]
    cliente.tags, descartadas = somar_tags(cliente.tags, novas)
    facts.record(
        db,
        tenant_id=tenant_id,
        module="comercial",
        kind=COM_ORIGEM_IDENTIFICADA,
        title=f"Chegou pelo WhatsApp com o código {lido.codigo}",
        actor=ATOR,
        body=json.dumps(
            {"codigo": lido.codigo, "origem": lido.origem, "tags_descartadas": descartadas},
            ensure_ascii=False,
            indent=2,
        ),
        client_id=cliente.id,
        subject_type="client",
        subject_id=cliente.id,
        occurred_at=occurred_at,
    )
    return lido
```

- [ ] **Step 4: Ligar no inbox**

Em `apps/api/app/modules/whatsapp_inbox/service.py`:

1. Junto dos imports `from app.modules.crm.schemas import ClientCreate`, acrescentar:

```python
from app.modules.lead_ingest import whatsapp as lead_ingest_whatsapp
```

2. Substituir a função inteira `_get_or_create_client` (linhas 144-165) por:

```python
def _resolve_client(
    db: Session, *, tenant_id: str, phone: str, name: str
) -> tuple[Client, bool]:
    """Resolve o contato pelo telefone NORMALIZADO — a mesma identidade que o site usa.

    Devolve `(contato, criado_agora)`. Comparar `Client.phone` cru (como era até aqui) deixava o
    conserto pela metade: o formulário guarda "(11) 99999-8888" e o WhatsApp guarda
    "5511999998888", então a mesma pessoa continuaria virando dois cards.

    `criado_agora` existe para a leitura do código de origem (spec §6.3), que só vale na 1ª
    mensagem de um contato NOVO.
    """
    chave = normalize_br(phone)
    if chave:
        client = db.scalars(
            select(Client).where(Client.phone_key == chave).order_by(Client.created_at, Client.id)
        ).first()
        if client is not None:
            return client, False
    # Fallback para contato legado cujo telefone nunca normalizou (e portanto não tem chave).
    client = db.scalar(select(Client).where(Client.phone == phone))
    if client is not None:
        return client, False
    novo = crm_service.create_client(
        db, tenant_id=tenant_id, actor="whatsapp:inbox",
        data=ClientCreate(name=name or phone, phone=phone, source="whatsapp"),
    )
    return novo, True


def _get_or_create_client(db: Session, *, tenant_id: str, phone: str, name: str) -> Client:
    """Só o contato, sem dizer se foi criado agora (ver `_resolve_client`)."""
    return _resolve_client(db, tenant_id=tenant_id, phone=phone, name=name)[0]
```

3. Em `ingest_webhook_payload`, trocar:

```python
                client_id = None
                client = None
            else:
```

por:

```python
                client_id = None
                client = None
                contato_novo = False
            else:
```

e trocar:

```python
                client = _get_or_create_client(
                    db, tenant_id=tenant_id, phone=msg.from_phone,
                    name="" if msg.from_me else msg.push_name,
                )
                client_id = client.id
```

por:

```python
                client, contato_novo = _resolve_client(
                    db, tenant_id=tenant_id, phone=msg.from_phone,
                    name="" if msg.from_me else msg.push_name,
                )
                client_id = client.id
```

4. Ainda em `ingest_webhook_payload`, dentro do bloco `if direction == DIRECTION_IN and not da_equipe:`, logo DEPOIS do `facts.record(...)` de `COM_MENSAGEM_RECEBIDA` (o que termina em `occurred_at=msg.occurred_at,` / `)`), acrescentar no mesmo nível de indentação do `facts.record`:

```python
                # A 1ª mensagem de um contato que ESTA mensagem acabou de criar pode trazer o
                # código de origem que o site pôs no `wa.me` (spec §6.3). Contato que já existia
                # não é relido: o código da primeira conversa é o que atribui; reler a cada
                # mensagem reescreveria a origem com o que a pessoa colou depois.
                if contato_novo and client is not None and msg.kind == KIND_TEXT:
                    lead_ingest_whatsapp.aplicar_codigo_da_primeira_mensagem(
                        db, tenant_id=tenant_id, cliente=client, perfil=profile,
                        texto=msg.text_body, occurred_at=msg.occurred_at,
                    )
```

- [ ] **Step 5: Rodar e ver passar**

Run: `cd F:/Projetos/e1p/_wt-ingest-atribuicao/apps/api && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m pytest tests/test_lead_ingest_whatsapp.py tests/test_whatsapp_inbox_service.py tests/test_lead_portas.py tests/test_facts_whatsapp.py tests/test_whatsapp_inbox_self_chat.py tests/test_whatsapp_inbox_unidentified.py -v`
Expected: todos PASS.

Run: `cd F:/Projetos/e1p/_wt-ingest-atribuicao/apps/api && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m ruff check . --fix && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m ruff check .`
Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
cd F:/Projetos/e1p/_wt-ingest-atribuicao && git add apps/api/app/modules/lead_ingest/whatsapp.py apps/api/app/modules/whatsapp_inbox/service.py apps/api/tests/test_lead_ingest_whatsapp.py && git commit -m "feat(whatsapp): 1ª mensagem de contato novo com código aplica origem, post e lead-whatsapp" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 14: Documentação, runbook do tenant Nexus e gates finais

**Files:**
- Modify: `CLAUDE.md` (seção "## Removida: a chave de API de "Integrações"" ≈ linhas 3895-3920, e seção nova antes de "## 7. Materiais de referência")
- Create: `docs/RUNBOOK-INGESTAO-DE-LEADS.md`

**Interfaces:**
- Consumes: tudo o que as Tasks 1-13 entregaram (os textos abaixo descrevem o código que subiu; se algo mudou na execução, ajuste o texto ao código, não o contrário).
- Produces: nada de código.

- [ ] **Step 1: Atualizar a nota de remoção no CLAUDE.md**

Em `CLAUDE.md`, na seção `## Removida: a chave de API de "Integrações" (leads de site externo) — 2026-08-28`, depois do último parágrafo (o que termina em `headless que não pode embutir iframe).`), acrescentar:

```markdown
- **[2026-09-30] O caso previsto acima apareceu, e a capacidade voltou ESCOPADA** — não como
  "chave de API" genérica: `POST /public/ingest/leads` com credencial de máquina
  (`machine_tokens`, escopo `lead_ingest`), contrato fechado e idempotência por chave. Ver
  §"Ingestão de leads com atribuição". Nada da 0083 foi desfeito: `integration_keys` e
  `public_integration_keys` continuam apagadas, e o resto que sobrava do #270 em `app/main.py`
  (`PublicLeadsCORSMiddleware`, CORS aberto para `/public/leads/*`) saiu junto.
```

- [ ] **Step 2: Escrever a seção nova no CLAUDE.md**

Antes de `## 7. Materiais de referência (fora do repo)`, inserir:

```markdown
## Ingestão de leads com atribuição (Publ.IA → e1p) — 2026-09-30

> Spec: `docs/superpowers/specs/2026-09-30-atribuicao-publia-e1p-design.md` **no repositório do
> site** (Mkt), §6 · Plano: `docs/superpowers/plans/2026-09-30-ingest-atribuicao-publia.md` ·
> Runbook: `docs/RUNBOOK-INGESTAO-DE-LEADS.md`

Um site externo (hoje nexuspublica.com.br, tenant Nexus) empurra **pessoas** — quem deixou
contato ou comprou — com a origem já resolvida. O visitante anônimo fica no site; o e1p não o vê.

- [x] **`machine_tokens` (0088)** — credencial de máquina, tabela GLOBAL sem RLS, só hash
  sha256, escopo `lead_ingest`, dono = TENANT (não há `user_id`). Desconhecida, revogada ou de
  outro escopo → **401** sem distinguir (diferente de `device_tokens`, que dá 403). Sem tela:
  `python -m app.scripts.lead_ingest_admin emitir-token|listar-tokens|revogar-token`.
  ⚠️ Global = fora da purga dinâmica de `platform.delete_account`; o `DELETE` explícito mora lá.
- [x] **`POST /public/ingest/leads`** (`modules/lead_ingest/router.py`) — `get_db` só para
  resolver a credencial (módulo na ALLOWLIST de `test_tenancy_guard.py`); todo o resto numa
  `tenant_session` do tenant **do token**. Contrato congelado em `lead_ingest/schemas.py`:
  **201** processado, **200** chave já processada, **401** credencial, **422** corpo. Sem CORS.
- [x] **Idempotência (0089)** — `lead_ingest_records`, RLS, única por `(tenant_id,
  chave_idempotencia)`. `absorb_lead` commita no meio, então a reivindicação entra no commit do
  contato e tags + fato + Ganho no seguinte; linha sem `concluido_em` é **retomada** na próxima
  tentativa. `payload` guarda o bruto, com valores — é o único lugar do e1p com o valor do pedido.
- [x] **Serviço** (`lead_ingest/service.py`) — entrada (lead, carrinho, compra) via
  `absorb_lead(source="api", auto_enroll=False)`; pós-venda de contato conhecido **não** passa por
  `absorb_lead` (reabriria o card do Ganho) — usa `crm.find_lead`. Tags somadas por
  `lead_ingest/tags.py` (50 × 40, excedente descartado E registrado). Fato `comercial.*` por
  evento (`core/facts.py`), atribuição em JSON no corpo, **sem `*_centavos`** (invariante 2).
  `compra_aprovada` → coluna `is_won` via `move_client`; reembolso/chargeback/cancelamento só
  tag `<produto>:reembolso|chargeback|cancelou`; renovação só fato.
- [x] **Configuração por tenant (0090)** — `tenant_profiles.lead_ingest_config`:
  `{"produto": "publia", "funis": {evento: funnel_id}}`, escrita por
  `lead_ingest_admin configurar`. Sem `produto`, não há tag de produto nem leitura de código no
  WhatsApp. Funil sem mapeamento cai no `default_entry_funnel_id` **só** para lead, carrinho e
  compra — pós-venda só entra em funil mapeado.
- [x] **WhatsApp com código** (`lead_ingest/codigo.py` + `whatsapp.py`, chamado do inbox) — só na
  1ª mensagem de contato criado por ela: `origem:<instagram|google|email|whatsapp|parceria>`,
  `post:<código>`, `<produto>:lead-whatsapp` e fato `comercial.origem.identificada`. `np-lp`
  (botão sem toque) marca só `<produto>:lead-whatsapp`.
- [x] **CRM ganhou dois ganchos**: `absorb_lead`/`create_client` aceitam `auto_enroll=False`
  (viaja no evento; `funnels/automation.py` respeita) e `crm.find_lead`. `automation._ja_esta_andando`
  virou `jornada_viva` (pública). Limites de tag viraram `crm.models.TAG_LIMIT`/`TAG_MAX_LENGTH`.

**Regra que fica:** tag de produto e vocabulário de `origem:` são DADO do tenant/contrato, nunca
literal no núcleo; e o contrato de `lead_ingest/schemas.py` só muda depois da spec — o site
codifica contra ele sem nenhum teste deste repo para avisar.

- **Dívida:** `device_tokens` tem o mesmo furo que `machine_tokens` fechou (global, sobrevive à
  exclusão de conta). A retomada pode duplicar o fato se um reenvio cair nos milissegundos entre os
  dois commits de uma tentativa em andamento. O vocabulário `origem:` derivado do prefixo do código
  precisa casar com as tags que o site envia (o site usa `utm_source`; e-mail e parceria divergem —
  `nexus-newsletter`, `partner-{slug}`). `packages/shared-types/src/generated.ts` ainda lista
  `/public/leads/{key}` (stale desde o #270) e não tem a rota nova — regenerar com
  `pnpm generate:types` quando alguém mexer ali. Relatório por origem é a fase 2 da spec.
```

- [ ] **Step 3: Escrever o runbook**

Criar `docs/RUNBOOK-INGESTAO-DE-LEADS.md`:

````markdown
# Runbook — Ingestão de leads com atribuição (`POST /public/ingest/leads`)

**Para quem:** quem opera o e1p em produção. **Quando:** ao ligar um site externo ao CRM de um
tenant (hoje: nexuspublica.com.br → tenant Nexus), ao trocar a credencial, ou ao diagnosticar
lead que não chegou. Desenho: seção "Ingestão de leads com atribuição" do `CLAUDE.md`.

Todos os comandos rodam no host da API, na pasta do `docker compose` de produção.

## 1. Descobrir o slug do tenant

```bash
docker compose exec postgres psql -U e1puser -d e1pdb -c \
  "SELECT id, slug, legal_name FROM tenants WHERE legal_name ILIKE '%nexus%';"
```

`tenants` é tabela global (sem RLS); o slug é o subdomínio do tenant. Abaixo, `<slug>`.

## 2. Emitir a credencial

```bash
docker compose exec api python -m app.scripts.lead_ingest_admin emitir-token \
  --tenant <slug> --nome "site nexuspublica.com.br"
```

A **última linha** é o token cru. Ele aparece só agora: o e1p guarda apenas o hash.
Entregue-o direto no cofre do site (variável de ambiente que a squad do site definir) — nunca em
chat, e-mail, issue ou commit. Perdeu? Emita outro e revogue o perdido (passo 6).

## 3. Configurar produto e funis

Monte os funis no editor (Funis) e copie o id de cada um da URL. Depois:

```bash
docker compose exec api python -m app.scripts.lead_ingest_admin configurar --tenant <slug> \
  --produto publia \
  --funil lead=<id do funil Boas-vindas> \
  --funil carrinho_abandonado=<id do funil Recuperação> \
  --funil compra_aprovada=<id do funil Onboarding>
docker compose exec api python -m app.scripts.lead_ingest_admin mostrar --tenant <slug>
```

- `--produto publia` liga as tags `publia:reembolso`, `publia:chargeback`, `publia:cancelou`,
  `publia:lead-whatsapp` e a leitura do código na 1ª mensagem de WhatsApp. Sem produto, nada disso.
- `--funil evento=` (vazio) remove um mapeamento. Evento sem mapeamento: lead, carrinho e compra
  caem no funil de entrada padrão de Configurações; renovação, reembolso, chargeback e
  cancelamento não entram em funil nenhum.
- Eventos válidos: `lead`, `carrinho_abandonado`, `compra_aprovada`, `renovacao`, `reembolso`,
  `chargeback`, `cancelamento`.

## 4. Testar de ponta a ponta

```bash
curl -sS -X POST "https://<domínio do e1p>/api/public/ingest/leads" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"evento":"lead","chave_idempotencia":"teste:runbook:1","ocorrido_em":"2026-10-01T10:00:00-03:00",
       "contato":{"nome":"Teste Runbook","email":"teste.runbook@example.com"},
       "tags":["origem:teste"],"atribuicao":{"situacao":"sem_origem"}}' -w "\nHTTP %{http_code}\n"
```

Esperado: `HTTP 201` e o card "Teste Runbook" na Entrada, com a tag `origem:teste` e o fato
"Deixou o contato no site" no histórico. Repetir o mesmo comando: `HTTP 200` com
`"resultado":"ja_processado"` e nada novo no card. Apague o card de teste depois.

## 5. Diagnóstico

| Sintoma | Causa provável |
|---|---|
| `401` | Token errado, revogado, ou cabeçalho sem `Bearer `. `listar-tokens` mostra situação e último uso. |
| `422` | Corpo fora do contrato (o `detail` diz o campo). Erro permanente: a fila do site não deve reenviar. |
| `200` inesperado | A `chave_idempotencia` já foi processada — o site está reutilizando chave. |
| `500` | Falha inesperada; o site reenvia. Ver `docker compose logs api` (logger `e1p.lead_ingest`). |
| Lead chegou e não entrou no funil | Funil apagado ou vazio: procure `[lead_ingest] inscrição falhou` no log. |

## 6. Trocar ou revogar a credencial

```bash
docker compose exec api python -m app.scripts.lead_ingest_admin listar-tokens --tenant <slug>
docker compose exec api python -m app.scripts.lead_ingest_admin emitir-token --tenant <slug> --nome "site (rotação)"
# ...troque no cofre do site, confirme um 201...
docker compose exec api python -m app.scripts.lead_ingest_admin revogar-token --id <id da antiga>
```

Revogada, a credencial responde 401 na hora. Excluir a conta do tenant apaga as credenciais dele.
````

- [ ] **Step 4: Gates finais (em série, nunca dois ao mesmo tempo — CLAUDE.md §5)**

Run: `cd F:/Projetos/e1p/_wt-ingest-atribuicao/apps/api && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m ruff check . && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m pytest -q -m "not rls_e2e"`
Expected: `All checks passed!` e a suíte inteira verde (nenhuma falha, só o skip que já existia).

Run: `cd F:/Projetos/e1p/_wt-ingest-atribuicao/apps/api && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m pytest -q -m rls_e2e`
Expected: tudo PASS, zero skipped.

Run: `cd F:/Projetos/e1p/_wt-ingest-atribuicao/apps/api && F:/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m alembic heads`
Expected: exatamente uma linha, `0090 (head)`.

Run: `cd F:/Projetos/e1p/_wt-ingest-atribuicao && git fetch origin && git ls-tree --name-only origin/main apps/api/migrations/versions/ | grep -E "/00(8[89]|9)"`
Expected: saída vazia. Se aparecer `0088`/`0089`/`0090` em `origin/main`, renumerar as três migrations desta branch (arquivo, `revision`, `down_revision`) acima da maior de `main` e rodar de novo os dois comandos anteriores.

Run: `cd F:/Projetos/e1p/_wt-ingest-atribuicao && bash scripts/gates.sh`
Expected: as três suítes verdes em série (o backend não mexeu em `apps/web`; o `pnpm e2e` só confirma que nada vizinho quebrou).

Rodar os agentes de QA do repositório (CLAUDE.md §5.3): `regression-tester`, `bug-hunter`, `dedup-checker` sobre o diff `origin/main...HEAD`. Achado procedente volta à task dona com teste novo.

- [ ] **Step 5: Commit**

```bash
cd F:/Projetos/e1p/_wt-ingest-atribuicao && git add CLAUDE.md docs/RUNBOOK-INGESTAO-DE-LEADS.md && git commit -m "docs(lead-ingest): entrada no CLAUDE.md e runbook da credencial do tenant Nexus" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Push e PR: entregar ao `@devops` (exclusivo). A `main` exige os 5 checks do `ci.yml`.

---

## Self-review (feito na escrita)

- **Cobertura do §6:** 6.1 contrato → Task 4 (campos, eventos, situações) e Task 9 (201/200/401/422, tenant do token); 6.2 token → Task 1; idempotência → Tasks 2 e 10; `absorb_lead` + `source="api"` + dedup → Tasks 6-7; tags 50/40 com registro → Tasks 5 e 7; `Fact` `comercial` com atribuição e pedido → Task 7; Ganho/reembolso/chargeback/cancelamento/renovação → Tasks 7-8; 6.3 → Tasks 12-13; 6.4 → Tasks 3, 8 e 11. Testes do §9 do e1p: todos têm dono (token sem escopo 401 — Tasks 1 e 9; chave repetida 200 — Task 9; dedup — Task 7; compra/reembolso — Task 8; WhatsApp — Task 13).
- **Placeholders:** nenhum TBD/TODO; todo passo de código traz o código.
- **Nomes entre tasks:** `create_token/resolve/list_tokens/revoke`, `reivindicar/concluir/contato_da_chave`, `produto/validar_produto/funil_do_evento/EVENTOS/EVENTOS_DE_ENTRADA`, `somar_tags`, `find_lead`, `auto_enroll`, `jornada_viva`, `ingest/ResultadoIngest`, `ler_codigo/CodigoLido`, `aplicar_codigo_da_primeira_mensagem`, `_resolve_client` — conferidos nas seções Interfaces e no código de cada task.
