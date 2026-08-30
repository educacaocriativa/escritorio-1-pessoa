# Vima: voz na entrada Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O dono manda uma nota de voz para a própria self-chat do WhatsApp (Evolution); a Vima transcreve via Groq e responde exatamente como responderia a uma pergunta digitada, ecoando o que entendeu.

**Architecture:** `core/transcription.py` é um segundo ponto único de acesso a IA (irmão de `core/ai.py`, mas para a Groq) — transcreve áudio e contabiliza no `ai_usage` (migration nova: `provider` + `audio_seconds`). `vima/whatsapp_conversa.py` ganha `responder_audio()`, que transcreve e delega para o mesmo mecanismo de resposta que o caminho de texto já usa. `whatsapp_inbox/service.py` passa a rotear `kind == "audio"` da self-chat para lá, ao lado de `kind == "text"`.

**Tech Stack:** FastAPI/SQLAlchemy/Alembic (Python 3.13), `httpx` para a chamada HTTP à Groq (sem SDK novo — mesmo padrão de `core/whatsapp/providers/evolution.py`), pytest com `monkeypatch` para mockar `httpx.post`.

**Spec:** `docs/superpowers/specs/2026-08-29-vima-voz-entrada-design.md`

## Global Constraints

- Comentários e docstrings de domínio em PT-BR; identificadores de código em inglês (CLAUDE.md §8).
- `core/transcription.transcribe` exige `db` e `tenant_id` como parâmetros obrigatórios — mesma disciplina de `core/ai.py` (impossível chamar a Groq sem contabilizar).
- Nenhuma migration desta fatia faz `UPDATE` — só `ADD COLUMN` com `server_default`, para não cair na armadilha do backfill silenciosamente filtrado por `FORCE ROW LEVEL SECURITY` (0046/0066/0067/0068/0069/0073).
- `ai_usage.record` continua **best-effort**: nunca levanta, mesmo se a gravação do ledger falhar.
- `whatsapp.send_text` nunca levanta (fire-and-forget); `core/transcription.transcribe` também nunca levanta — devolve `None` em qualquer falha.
- Nenhum dado de áudio é persistido em lugar nenhum (nem banco, nem disco, nem cache) além da chamada síncrona à Groq.
- Antes de escrever o corpo da chamada HTTP à Groq (Task 2, passo 1), confirme o formato real de request/response na documentação oficial via WebFetch — este repositório já pagou por seis vezes por supor o formato de uma API de terceiro em vez de verificar (ver CLAUDE.md, seção "WhatsApp Evolution").

---

### Task 1: `ai_usage` ganha `provider` e `audio_seconds`

**Files:**
- Modify: `apps/api/app/core/ai_usage.py`
- Create: `apps/api/migrations/versions/0084_ai_usage_provider_and_audio_seconds.py`
- Test: `apps/api/tests/test_ai_usage_provider.py`

**Interfaces:**
- Produces: `ai_usage.record(db, *, tenant_id, task, model, provider: str = "anthropic", input_tokens=0, output_tokens=0, cache_read_tokens=0, cache_creation_tokens=0, audio_seconds: float | None = None, user_id=None) -> AIUsage | None`. `AIUsage.provider: str` (default `"anthropic"`), `AIUsage.audio_seconds: float | None`.

- [ ] **Step 1: Escrever os testes (falhando)**

Crie `apps/api/tests/test_ai_usage_provider.py`:

```python
"""`ai_usage` passa a distinguir PROVEDOR (Anthropic vs. Groq) — a fatia de voz da Vima introduz
a Groq como segundo provedor de IA do repositório. `provider` tem default 'anthropic' para não
exigir mudança nos dezenas de call sites existentes; só quem grava transcrição passa 'groq'
explícito, junto de `audio_seconds` (a "moeda" da Groq, que cobra por segundo, não por token)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.core import ai_usage
from app.core.ai_usage import AIUsage

TENANT = "t-provider"


def test_record_sem_provider_grava_anthropic_e_audio_seconds_nulo(db: Session):
    ai_usage.record(db, tenant_id=TENANT, task="vima.briefing", model="claude-haiku-4-5")
    db.commit()

    linha = db.query(AIUsage).one()
    assert linha.provider == "anthropic"
    assert linha.audio_seconds is None


def test_record_com_provider_groq_grava_audio_seconds(db: Session):
    ai_usage.record(
        db, tenant_id=TENANT, task="vima.transcricao", model="whisper-large-v3",
        provider="groq", audio_seconds=4.2,
    )
    db.commit()

    linha = db.query(AIUsage).one()
    assert linha.provider == "groq"
    assert linha.audio_seconds == 4.2
    assert linha.input_tokens == 0
    assert linha.output_tokens == 0


def test_uma_linha_anthropic_e_uma_groq_convivem_sem_se_confundir(db: Session):
    ai_usage.record(db, tenant_id=TENANT, task="vima.pergunta", model="claude-sonnet-5")
    ai_usage.record(
        db, tenant_id=TENANT, task="vima.transcricao", model="whisper-large-v3",
        provider="groq", audio_seconds=1.0,
    )
    db.commit()

    linhas = {l.provider: l for l in db.query(AIUsage).all()}
    assert linhas["anthropic"].audio_seconds is None
    assert linhas["groq"].audio_seconds == 1.0
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `cd apps/api && pytest tests/test_ai_usage_provider.py -v`
Expected: FAIL — `TypeError: record() got an unexpected keyword argument 'provider'` (a coluna/param ainda não existem).

- [ ] **Step 3: Implementar**

Edite `apps/api/app/core/ai_usage.py`:

1. No import do topo, troque:
```python
from sqlalchemy import BigInteger, DateTime, String, func
```
por:
```python
from sqlalchemy import BigInteger, DateTime, Float, String, func
```

2. Na classe `AIUsage`, troque a linha `task`/`model` e as colunas de token para incluir `provider` e `audio_seconds`:

```python
    task: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    # 'anthropic' (default — todo call site pré-existente) ou 'groq' (transcrição de voz da
    # Vima, ver core/transcription.py). Os dois cobram diferente — tokens vs. segundos de áudio
    # — por isso `audio_seconds` é coluna IRMÃ, nunca achatada em `input_tokens`.
    provider: Mapped[str] = mapped_column(String(32), default="anthropic", nullable=False)
    # O modelo que REALMENTE rodou, não o configurado. Divergem quando o roteamento muda, e é a
    # linha gravada que precisa valer para reconstruir a conta.
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    input_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    # Cache tem preço próprio (leitura ~0,1× do input; escrita ~1,25×), então somar tudo em
    # `input_tokens` produziria uma conta errada — para mais ou para menos, dependendo do mix.
    cache_read_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    cache_creation_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    # Só preenchido em linhas de transcrição (provider='groq'); NULL em toda linha Anthropic.
    # Nunca coexiste com os contadores de token acima.
    audio_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
```

3. Na função `record`, acrescente os dois parâmetros novos (mantendo a ordem dos existentes) e passe-os ao construtor:

```python
def record(
    db: Session,
    *,
    tenant_id: str,
    task: str,
    model: str,
    provider: str = "anthropic",
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
    audio_seconds: float | None = None,
    user_id: str | None = None,
) -> AIUsage | None:
    """Registra uma chamada de IA (Anthropic ou Groq). **Nunca levanta** — devolve `None` se não
    conseguiu gravar.

    ... (docstring restante inalterada) ...
    """
    try:
        with db.begin_nested():
            uso = AIUsage(
                tenant_id=tenant_id,
                user_id=user_id,
                task=task,
                provider=provider,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=cache_read_tokens,
                cache_creation_tokens=cache_creation_tokens,
                audio_seconds=audio_seconds,
            )
            db.add(uso)
            db.flush()
        return uso
    except Exception:  # noqa: BLE001
        logger.exception(
            "Falha ao registrar uso de IA (task=%s, model=%s, tenant=%s) — "
            "a chamada já aconteceu e já custou; seguindo sem o registro.",
            task, model, tenant_id,
        )
        return None
```

Também atualize a primeira linha da docstring do módulo (topo do arquivo) de `"""O ledger de uso de IA — quanto se gastou, por quem, em qual tarefa.` para deixar claro que agora é multi-provedor:

```python
"""O ledger de uso de IA — quanto se gastou, por quem, em qual tarefa, com qual PROVEDOR.
```

E a docstring da classe `AIUsage`, de `"""Uma chamada à Anthropic, com o que ela custou em tokens."""` para:

```python
    """Uma chamada a um provedor de IA — Anthropic (texto) ou Groq (transcrição de voz)."""
```

Crie `apps/api/migrations/versions/0084_ai_usage_provider_and_audio_seconds.py`:

```python
"""ai_usage ganha provider e audio_seconds — a Groq entra como segundo provedor de IA

Revision ID: 0084
Revises: 0083
Create Date: 2026-08-29

Por quê: a fatia de voz da Vima (docs/superpowers/specs/2026-08-29-vima-voz-entrada-design.md)
introduz a Groq (transcrição de áudio) como segundo provedor de IA do repositório — hoje
`ai_usage` assume implicitamente um único provedor (Anthropic): não existe coluna `provider`, e
`input_tokens`/`output_tokens`/`cache_*` são conceitos de cobrança da Anthropic que não fazem
sentido para a Groq (que cobra por SEGUNDO de áudio, não por token).

`provider` nasce com `server_default='anthropic'` PERMANENTE — ao contrário de
`opening_balance_is_known` (0074), aqui o default NÃO é removido depois: `ai_usage.record()`
continua chamado por dezenas de call sites Anthropic existentes que não vão declarar `provider`,
e forçar todos a mudar seria puro churn sem ganho — só o caminho novo (Groq) passa o valor
explícito. Sem UPDATE: DDL puro (`ADD COLUMN` com `server_default`), a mesma disciplina segura
das migrations 0074/0075/0077 contra a armadilha do backfill sob FORCE RLS (a RLS não alcança
DDL, só DML).

`audio_seconds` é nullable, sem default: preenchido SÓ em linhas de transcrição (provider='groq');
toda linha Anthropic tem `audio_seconds IS NULL` para sempre. Os dois nunca coexistem numa linha.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0084"
down_revision: str | None = "0083"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "ai_usage"


def upgrade() -> None:
    op.add_column(
        _TABLE,
        sa.Column("provider", sa.String(32), nullable=False, server_default="anthropic"),
    )
    op.add_column(_TABLE, sa.Column("audio_seconds", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column(_TABLE, "audio_seconds")
    op.drop_column(_TABLE, "provider")
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `cd apps/api && pytest tests/test_ai_usage_provider.py tests/test_ai.py tests/test_ai_complete_with_tools.py -v`
Expected: PASS em todos — os testes existentes de `test_ai.py`/`test_ai_complete_with_tools.py` continuam verdes porque `provider`/`audio_seconds` têm default.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/core/ai_usage.py apps/api/migrations/versions/0084_ai_usage_provider_and_audio_seconds.py apps/api/tests/test_ai_usage_provider.py
git commit -m "feat: ai_usage ganha provider e audio_seconds — Groq como segundo provedor de IA"
```

---

### Task 2: `core/transcription.py` — Groq Whisper (STT)

**Files:**
- Modify: `apps/api/app/config.py`
- Create: `apps/api/app/core/transcription.py`
- Test: `apps/api/tests/test_transcription.py`

**Interfaces:**
- Consumes: `ai_usage.record(db, *, tenant_id, task, model, provider, audio_seconds, user_id=None)` (Task 1). `settings.groq_api_key: str` (novo).
- Produces: `transcription.TranscriptionResult` (dataclass: `text: str`, `audio_seconds: float`). `transcription.transcribe(db, *, tenant_id: str, audio_bytes: bytes, mime_type: str, user_id: str | None = None) -> TranscriptionResult | None` — nunca levanta, `None` em qualquer falha (sem chave, erro HTTP, erro de rede, texto vazio).

- [ ] **Step 0 (obrigatório antes do Step 1): confirmar o formato real da API da Groq**

WebFetch `https://console.groq.com/docs/speech-to-text` (ou a URL equivalente da documentação oficial de transcrição da Groq). Confirme, especificamente:
- O endpoint exato (`POST https://api.groq.com/openai/v1/audio/transcriptions` é o assumido abaixo — a Groq espelha a API de áudio da OpenAI).
- O nome do campo do arquivo no multipart (`file`, assumido abaixo).
- Se `response_format=verbose_json` devolve mesmo um campo `duration` (segundos, float) no nível raiz do JSON — é dele que `audio_seconds` é lido.
- O nome do modelo Whisper disponível na Groq hoje (`whisper-large-v3` é o assumido abaixo — pode ter mudado).
- Se o campo de texto no JSON de sucesso é `text` (assumido abaixo).

Se qualquer um divergir do assumido, ajuste os nomes de campo/URL/modelo no código do Step 3 E nos testes do Step 1 ANTES de prosseguir — não implemente sobre suposição não verificada (é exatamente a classe de bug que a integração com a Evolution pagou seis vezes).

- [ ] **Step 1: Escrever os testes (falhando)**

Primeiro, adicione o campo em `apps/api/app/config.py`. Logo abaixo de `anthropic_api_key: str = ""` (dentro do bloco `# IA`), acrescente:

```python
    # Groq (Whisper) — transcrição de voz da Vima (core/transcription.py). Segundo provedor de
    # IA do repositório: `core/ai.py` só fala com a Anthropic, que não aceita áudio como entrada.
    # Vazio = mensagens de áudio da self-chat degradam para uma desculpa (graceful degradation,
    # NÃO bloqueante — ao contrário de `anthropic_api_key`, que é exigida em produção).
    groq_api_key: str = ""
```

Crie `apps/api/tests/test_transcription.py`:

```python
"""Transcrição de voz via Groq — a chamada real (`httpx.post`) é sempre mockada, mesmo padrão de
`test_whatsapp.py` (este ambiente não tem credenciais reais)."""
from __future__ import annotations

import httpx
import pytest
from sqlalchemy.orm import Session

from app.config import settings
from app.core import transcription
from app.core.ai_usage import AIUsage

TENANT = "t-transcricao"


class _FakeResponse:
    def __init__(self, status_code: int = 200, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "erro", request=httpx.Request("POST", "https://x"), response=self
            )

    def json(self) -> dict:
        return self._payload

    @property
    def text(self) -> str:
        return str(self._payload)


@pytest.fixture(autouse=True)
def _sem_chave_por_padrao(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "groq_api_key", "")


def test_sem_groq_api_key_devolve_none_sem_chamar_httpx(db: Session, monkeypatch):
    def _boom(*_a, **_kw):
        raise AssertionError("httpx.post não deveria ser chamado sem GROQ_API_KEY")

    monkeypatch.setattr(httpx, "post", _boom)

    resultado = transcription.transcribe(
        db, tenant_id=TENANT, audio_bytes=b"audio", mime_type="audio/ogg",
    )
    assert resultado is None


def test_transcricao_com_sucesso_grava_no_ledger_e_devolve_texto(db: Session, monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "gsk-fake")
    monkeypatch.setattr(
        httpx, "post",
        lambda *a, **kw: _FakeResponse(
            200, {"text": " quanto tenho a receber essa semana? ", "duration": 3.4}
        ),
    )

    resultado = transcription.transcribe(
        db, tenant_id=TENANT, audio_bytes=b"audio-bytes", mime_type="audio/ogg",
        user_id="user-1",
    )

    assert resultado is not None
    assert resultado.text == "quanto tenho a receber essa semana?"
    assert resultado.audio_seconds == 3.4

    linha = db.query(AIUsage).one()
    assert linha.provider == "groq"
    assert linha.task == "vima.transcricao"
    assert linha.model == transcription._MODELO
    assert linha.audio_seconds == 3.4
    assert linha.user_id == "user-1"
    assert linha.input_tokens == 0  # a "moeda" da Groq é audio_seconds, não token


def test_transcricao_manda_o_arquivo_e_o_modelo_certo(db: Session, monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "gsk-fake")
    capturado = {}

    def _fake_post(url, *, headers, files, data, timeout):
        capturado.update(url=url, headers=headers, files=files, data=data)
        return _FakeResponse(200, {"text": "oi", "duration": 1.0})

    monkeypatch.setattr(httpx, "post", _fake_post)

    transcription.transcribe(db, tenant_id=TENANT, audio_bytes=b"XYZ", mime_type="audio/ogg")

    assert capturado["headers"]["Authorization"] == "Bearer gsk-fake"
    assert capturado["data"]["model"] == transcription._MODELO
    assert capturado["files"]["file"][1] == b"XYZ"
    assert capturado["files"]["file"][2] == "audio/ogg"


def test_erro_http_da_groq_devolve_none_sem_gravar_ledger(db: Session, monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "gsk-fake")
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _FakeResponse(401, {}))

    resultado = transcription.transcribe(
        db, tenant_id=TENANT, audio_bytes=b"audio", mime_type="audio/ogg",
    )
    assert resultado is None
    assert db.query(AIUsage).count() == 0


def test_erro_de_rede_devolve_none(db: Session, monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "gsk-fake")

    def _raise(*_a, **_kw):
        raise httpx.ConnectError("sem rede")

    monkeypatch.setattr(httpx, "post", _raise)

    resultado = transcription.transcribe(
        db, tenant_id=TENANT, audio_bytes=b"audio", mime_type="audio/ogg",
    )
    assert resultado is None


def test_texto_vazio_da_groq_devolve_none(db: Session, monkeypatch):
    # Áudio ilegível: a Groq às vezes devolve texto vazio (ou só espaços) em vez de erro HTTP.
    monkeypatch.setattr(settings, "groq_api_key", "gsk-fake")
    monkeypatch.setattr(
        httpx, "post", lambda *a, **kw: _FakeResponse(200, {"text": "   ", "duration": 0.5}),
    )

    resultado = transcription.transcribe(
        db, tenant_id=TENANT, audio_bytes=b"audio", mime_type="audio/ogg",
    )
    assert resultado is None
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `cd apps/api && pytest tests/test_transcription.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.core.transcription'`.

- [ ] **Step 3: Implementar**

Crie `apps/api/app/core/transcription.py` (ajuste URL/nomes de campo se o Step 0 tiver divergido do assumido):

```python
"""Transcrição de voz (Groq, Whisper) — segundo ponto único de acesso a um provedor de IA,
irmão de `core/ai.py` (Anthropic). A API de mensagens da Anthropic não aceita áudio como
entrada; transcrição exige um provedor de STT dedicado. Provedores diferentes, formas de
cobrança diferentes (segundos de áudio, não tokens) — misturar as duas chaves num módulo só
criaria acoplamento sem ganho. Ver
docs/superpowers/specs/2026-08-29-vima-voz-entrada-design.md.

REGRA: mesma obrigatoriedade do item 1 do docstring de `core/ai.py` — `db` e `tenant_id` são
OBRIGATÓRIOS, para que seja estruturalmente impossível chamar a Groq sem contabilizar (ledger
`ai_usage`, `provider='groq'`).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.core import ai_usage

logger = logging.getLogger("e1p.transcription")

_MODELO = "whisper-large-v3"
_URL = "https://api.groq.com/openai/v1/audio/transcriptions"


@dataclass
class TranscriptionResult:
    text: str
    audio_seconds: float


def _response_body(exc: Exception) -> str:
    """O corpo da resposta que a Groq devolveu junto com o erro — mesma disciplina de
    `core/whatsapp/providers/evolution.py::_response_body`: o status sozinho não diagnostica
    nada, o corpo geralmente já diz o motivo."""
    resp = getattr(exc, "response", None)
    if resp is None:
        return "(sem resposta HTTP)"
    try:
        return resp.text[:400]
    except Exception:  # noqa: BLE001 — diagnóstico nunca pode virar a causa de outra falha
        return "(corpo ilegível)"


def transcribe(
    db: Session, *, tenant_id: str, audio_bytes: bytes, mime_type: str,
    user_id: str | None = None,
) -> TranscriptionResult | None:
    """Transcreve um áudio via Groq. **Nunca levanta** — devolve `None` em qualquer falha (sem
    `GROQ_API_KEY`, erro HTTP, erro de rede, transcrição vazia), para o chamador decidir a
    desculpa que manda ao dono. O áudio em si nunca é persistido — só esta chamada síncrona.
    """
    if not settings.groq_api_key:
        return None

    try:
        resp = httpx.post(
            _URL,
            headers={"Authorization": f"Bearer {settings.groq_api_key}"},
            files={"file": ("audio", audio_bytes, mime_type or "application/octet-stream")},
            data={"model": _MODELO, "response_format": "verbose_json"},
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001 — provedor externo, nunca derruba quem chamou
        logger.exception(
            "[transcription] falha ao transcrever áudio via Groq (corpo: %s)",
            _response_body(exc),
        )
        return None

    texto = (payload.get("text") or "").strip()
    duracao = payload.get("duration")
    if not texto or duracao is None:
        return None

    ai_usage.record(
        db, tenant_id=tenant_id, task="vima.transcricao", model=_MODELO, provider="groq",
        audio_seconds=float(duracao), user_id=user_id,
    )
    return TranscriptionResult(text=texto, audio_seconds=float(duracao))
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `cd apps/api && pytest tests/test_transcription.py -v`
Expected: PASS em todos os 6 testes.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/config.py apps/api/app/core/transcription.py apps/api/tests/test_transcription.py
git commit -m "feat: core/transcription.py — transcrição de voz via Groq Whisper"
```

---

### Task 3: `vima/whatsapp_conversa.responder_audio` — transcreve, ecoa, responde

**Files:**
- Modify: `apps/api/app/modules/vima/whatsapp_conversa.py`
- Test: `apps/api/tests/test_vima_whatsapp_conversa.py`

**Interfaces:**
- Consumes: `transcription.transcribe(db, *, tenant_id, audio_bytes, mime_type, user_id=None) -> TranscriptionResult | None` (Task 2). `transcription.TranscriptionResult.text: str`.
- Produces: `whatsapp_conversa.responder_audio(db, *, tenant_id: str, phone: str, wa_message_id: str, audio_bytes: bytes, audio_mime_type: str, profile) -> None`. `whatsapp_conversa.responder(...)` mantém a MESMA assinatura pública de hoje (nenhum teste existente deve precisar mudar).

- [ ] **Step 1: Escrever os testes (falhando)**

Acrescente ao FINAL de `apps/api/tests/test_vima_whatsapp_conversa.py` (depois do último teste existente, `test_responder_falha_no_meio_manda_desculpa_em_vez_de_estourar`):

```python

# ── responder_audio() — a voz vira pergunta, com eco ────────────────────────────────────────


def test_responder_audio_transcreve_e_ecoa_a_pergunta_entendida(db: Session, monkeypatch):
    from app.modules.vima.pergunta import Resposta
    from app.core.transcription import TranscriptionResult

    user = User(
        tenant_id=TENANT, email="dono6@example.com", name="Dono", password_hash="x",
        phone="5511999995555",
    )
    db.add(user)
    db.commit()

    capturado = {}

    monkeypatch.setattr(
        vc.transcription, "transcribe",
        lambda db, *, tenant_id, audio_bytes, mime_type, user_id=None: TranscriptionResult(
            text="quanto tenho a receber?", audio_seconds=2.1,
        ),
    )
    monkeypatch.setattr(
        vc.pergunta_service, "responder",
        lambda db, *, user, pergunta, historico: Resposta(texto="R$ 500,00", por_ia=True),
    )

    def _fake_send_text(*, to, text, profile=None, **_kw):
        capturado["texto_enviado"] = text
        return "sent"

    monkeypatch.setattr(vc.whatsapp, "send_text", _fake_send_text)

    vc.responder_audio(
        db, tenant_id=TENANT, phone="5511999995555", wa_message_id="wamid.audio1",
        audio_bytes=b"audio-bytes", audio_mime_type="audio/ogg", profile=None,
    )

    assert capturado["texto_enviado"] == '🎤 "quanto tenho a receber?" — R$ 500,00'


def test_responder_audio_guarda_o_turno_com_o_texto_transcrito(db: Session, monkeypatch):
    from app.modules.vima.pergunta import Resposta
    from app.core.transcription import TranscriptionResult

    user = User(
        tenant_id=TENANT, email="dono7@example.com", name="Dono", password_hash="x",
        phone="5511999996666",
    )
    db.add(user)
    db.commit()

    monkeypatch.setattr(
        vc.transcription, "transcribe",
        lambda *a, **kw: TranscriptionResult(text="e essa semana?", audio_seconds=1.0),
    )
    monkeypatch.setattr(
        vc.pergunta_service, "responder",
        lambda db, *, user, pergunta, historico: Resposta(texto="R$ 100,00", por_ia=True),
    )
    monkeypatch.setattr(vc.whatsapp, "send_text", lambda **_kw: "sent")

    vc.responder_audio(
        db, tenant_id=TENANT, phone="5511999996666", wa_message_id="wamid.audio2",
        audio_bytes=b"x", audio_mime_type="audio/ogg", profile=None,
    )

    historico = vc._historico(vc._chave(TENANT, "5511999996666"))
    assert [(t.papel, t.texto) for t in historico] == [
        ("usuario", "e essa semana?"), ("vima", "R$ 100,00"),
    ]


def test_responder_audio_sem_transcricao_manda_desculpa_sem_chamar_pergunta(
    db: Session, monkeypatch,
):
    user = User(
        tenant_id=TENANT, email="dono8@example.com", name="Dono", password_hash="x",
        phone="5511999997778",
    )
    db.add(user)
    db.commit()

    chamado = {"n": 0}
    capturado = {}

    monkeypatch.setattr(vc.transcription, "transcribe", lambda *a, **kw: None)
    monkeypatch.setattr(
        vc.pergunta_service, "responder",
        lambda *a, **kw: chamado.update(n=chamado["n"] + 1),
    )

    def _fake_send_text(*, to, text, profile=None, **_kw):
        capturado["texto"] = text
        return "sent"

    monkeypatch.setattr(vc.whatsapp, "send_text", _fake_send_text)

    vc.responder_audio(
        db, tenant_id=TENANT, phone="5511999997778", wa_message_id="wamid.audiofalha",
        audio_bytes=b"ruido", audio_mime_type="audio/ogg", profile=None,
    )

    assert chamado["n"] == 0  # nunca chegou a chamar pergunta.responder
    assert "não consegui" in capturado["texto"].lower()


def test_responder_audio_ignora_reentrega_do_mesmo_wa_message_id(db: Session, monkeypatch):
    from app.core.transcription import TranscriptionResult
    from app.modules.vima.pergunta import Resposta

    user = User(
        tenant_id=TENANT, email="dono9@example.com", name="Dono", password_hash="x",
        phone="5511999998889",
    )
    db.add(user)
    db.commit()

    chamadas = {"n": 0}

    def _fake_transcribe(*a, **kw):
        chamadas["n"] += 1
        return TranscriptionResult(text="oi", audio_seconds=1.0)

    monkeypatch.setattr(vc.transcription, "transcribe", _fake_transcribe)
    monkeypatch.setattr(
        vc.pergunta_service, "responder",
        lambda db, *, user, pergunta, historico: Resposta(texto="ok", por_ia=True),
    )
    monkeypatch.setattr(vc.whatsapp, "send_text", lambda **_kw: "sent")

    for _ in range(2):
        vc.responder_audio(
            db, tenant_id=TENANT, phone="5511999998889", wa_message_id="wamid.audiodup",
            audio_bytes=b"x", audio_mime_type="audio/ogg", profile=None,
        )

    assert chamadas["n"] == 1  # não paga a Groq de novo numa reentrega
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `cd apps/api && pytest tests/test_vima_whatsapp_conversa.py -v`
Expected: FAIL — `AttributeError: module 'app.modules.vima.whatsapp_conversa' has no attribute 'transcription'` (ou `responder_audio`).

- [ ] **Step 3: Implementar**

Reescreva `apps/api/app/modules/vima/whatsapp_conversa.py` por inteiro com este conteúdo:

```python
"""Vima por WhatsApp: quando o dono manda mensagem pro PRÓPRIO número conectado (self-chat,
Evolution), essa mensagem vira pergunta à Vima em vez de virar mensagem de CRM — em TEXTO
(`responder`) ou em ÁUDIO transcrito (`responder_audio`).

Ver docs/superpowers/specs/2026-08-28-vima-canal-whatsapp-design.md (texto) e
docs/superpowers/specs/2026-08-29-vima-voz-entrada-design.md (voz).
"""
from __future__ import annotations

import logging
import time

from sqlalchemy.orm import Session

from app.core import transcription, whatsapp
from app.core.phone import normalize_br
from app.modules.auth.models import User
from app.modules.vima import pergunta as pergunta_service
from app.modules.vima import scheduler

logger = logging.getLogger("e1p.vima")

# Poucos minutos — o suficiente para uma sequência natural de perguntas, curto o bastante para
# nunca virar "histórico permanente" (decisão da spec: zero persistência).
TTL_CONTEXTO_SEGUNDOS = 5 * 60
TTL_DEDUP_SEGUNDOS = 5 * 60

# Em processo — não sobrevive a reiniciar, não é compartilhado entre réplicas. Aceito para a
# escala atual (ver spec); Redis é o próximo passo se um dia isso incomodar de verdade.
_HISTORICO: dict[str, list[tuple[float, pergunta_service.Turno]]] = {}
_VISTAS: dict[str, float] = {}


def _chave(tenant_id: str, phone: str) -> str:
    return f"{tenant_id}:{normalize_br(phone) or phone}"


def _ja_processada(wa_message_id: str) -> bool:
    expira = _VISTAS.get(wa_message_id)
    return expira is not None and expira > time.monotonic()


def _marcar_processada(wa_message_id: str) -> None:
    _VISTAS[wa_message_id] = time.monotonic() + TTL_DEDUP_SEGUNDOS
    if len(_VISTAS) > 1000:  # limpeza oportunista — sem isso o dict cresce sem limite
        agora = time.monotonic()
        for chave in [k for k, exp in _VISTAS.items() if exp <= agora]:
            del _VISTAS[chave]


def _historico(chave: str) -> list[pergunta_service.Turno]:
    agora = time.monotonic()
    vivos = [(exp, t) for exp, t in _HISTORICO.get(chave, []) if exp > agora]
    _HISTORICO[chave] = vivos
    return [t for _, t in vivos]


def _guardar_turno(chave: str, papel: str, texto: str) -> None:
    expira = time.monotonic() + TTL_CONTEXTO_SEGUNDOS
    _HISTORICO.setdefault(chave, []).append(
        (expira, pergunta_service.Turno(papel=papel, texto=texto))
    )


def _usuario_do_telefone(db: Session, tenant_id: str, phone: str) -> User | None:
    """O mesmo casamento por telefone normalizado que `vima.scheduler.responder_optin` já faz
    para o toque no botão do briefing — reusa `scheduler.usuarios_ativos` (pública desde a
    tarefa anterior) em vez de reescrever a consulta pela terceira vez (a primeira é
    `whatsapp_inbox.service._e_telefone_da_equipe`, que fica como está: devolve só `bool` e
    não precisa da linha inteira)."""
    chave = normalize_br(phone)
    if chave is None:
        return None
    return next(
        (
            u for u in scheduler.usuarios_ativos(db, tenant_id)
            if u.phone and normalize_br(u.phone) == chave
        ),
        None,
    )


def responder(
    db: Session, *, tenant_id: str, phone: str, wa_message_id: str, texto: str, profile,
) -> None:
    """O dono perguntou algo em TEXTO na self-chat — responde pelo MESMO canal. Ver `_responder`
    para o mecanismo compartilhado com `responder_audio`."""
    _responder(
        db, tenant_id=tenant_id, phone=phone, wa_message_id=wa_message_id, texto=texto,
        profile=profile,
    )


def responder_audio(
    db: Session, *, tenant_id: str, phone: str, wa_message_id: str, audio_bytes: bytes,
    audio_mime_type: str, profile,
) -> None:
    """O dono mandou uma NOTA DE VOZ na self-chat — transcreve (Groq) e segue o MESMO caminho de
    `responder`: a transcrição vira o `texto` que alimenta `pergunta.responder`, e a resposta
    final ECOA o que foi entendido (`🎤 "..."`), porque o dono nunca vê a transcrição em lugar
    nenhum — sem o eco, um erro de transcrição vira resposta certa pra pergunta errada, sem
    nenhuma pista do porquê. Ver docs/superpowers/specs/2026-08-29-vima-voz-entrada-design.md.

    Checa `_ja_processada` ANTES de transcrever — evita pagar a Groq de novo numa reentrega de
    webhook que a checagem de dentro de `_responder` também pegaria, só que depois do gasto.
    """
    if _ja_processada(wa_message_id):
        return  # reentrega do webhook — já respondida (ou já falhou e já pedimos desculpa)

    resultado = transcription.transcribe(
        db, tenant_id=tenant_id, audio_bytes=audio_bytes, mime_type=audio_mime_type,
    )
    if resultado is None:
        _marcar_processada(wa_message_id)
        whatsapp.send_text(
            to=phone, text="Não consegui entender o áudio — tenta de novo em instantes.",
            profile=profile,
        )
        return

    _responder(
        db, tenant_id=tenant_id, phone=phone, wa_message_id=wa_message_id, texto=resultado.text,
        profile=profile, eco=f'🎤 "{resultado.text}" — ',
    )


def _responder(
    db: Session, *, tenant_id: str, phone: str, wa_message_id: str, texto: str, profile,
    eco: str = "",
) -> None:
    """O mecanismo compartilhado por `responder` (texto) e `responder_audio` (voz, já
    transcrita): resolve o usuário, chama `pergunta.responder`, grava o turno no cache e manda a
    resposta pelo mesmo canal — com `eco` prefixado quando a pergunta veio de áudio.

    NÃO commita: roda dentro da transação-por-mensagem do `ingest`, que decide quando commitar
    (mesmo padrão de `vima.scheduler.responder_optin`).

    Nunca deixa uma falha muda: qualquer erro no meio do caminho ainda tenta mandar uma resposta
    de desculpa pelo mesmo canal — `whatsapp.send_text` nunca levanta (fire-and-forget por
    contrato), então essa tentativa é sempre segura.
    """
    if _ja_processada(wa_message_id):
        return  # reentrega do webhook — já respondida
    _marcar_processada(wa_message_id)

    user = _usuario_do_telefone(db, tenant_id, phone)
    if user is None:
        # Defensivo: o chamador já confirmou que o telefone é de um usuário ativo
        # (`_e_telefone_da_equipe`), mas não há garantia atômica entre a checagem e aqui —
        # melhor desistir em silêncio do que estourar.
        logger.warning("[vima] self-chat sem usuário correspondente: tenant=%s", tenant_id)
        return

    chave = _chave(tenant_id, phone)

    try:
        resultado = pergunta_service.responder(
            db, user=scheduler.como_ator(user), pergunta=texto, historico=_historico(chave),
        )
    except Exception:  # noqa: BLE001 — falha nunca fica muda (ver docstring)
        logger.exception("[vima] falha ao responder pergunta via WhatsApp self-chat")
        db.rollback()
        whatsapp.send_text(
            to=phone, text="Não consegui responder agora — tenta de novo em instantes.",
            profile=profile,
        )
        return

    _guardar_turno(chave, "usuario", texto)
    _guardar_turno(chave, "vima", resultado.texto)
    whatsapp.send_text(to=phone, text=f"{eco}{resultado.texto}", profile=profile)
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `cd apps/api && pytest tests/test_vima_whatsapp_conversa.py -v`
Expected: PASS em todos — os testes antigos de `responder()` continuam verdes sem mudança nenhuma (assinatura pública inalterada), e os quatro novos de `responder_audio()` passam.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/modules/vima/whatsapp_conversa.py apps/api/tests/test_vima_whatsapp_conversa.py
git commit -m "feat: vima/whatsapp_conversa.responder_audio — transcreve e ecoa a pergunta entendida"
```

---

### Task 4: roteamento — self-chat de ÁUDIO chama `responder_audio`

**Files:**
- Modify: `apps/api/app/modules/whatsapp_inbox/service.py`
- Test: `apps/api/tests/test_whatsapp_inbox_self_chat.py`

**Interfaces:**
- Consumes: `vima_whatsapp.responder_audio(db, *, tenant_id, phone, wa_message_id, audio_bytes, audio_mime_type, profile)` (Task 3). `whatsapp_inbox.models.KIND_AUDIO` (já existe).

- [ ] **Step 1: Atualizar os testes (o antigo teste de áudio precisa mudar de comportamento)**

Em `apps/api/tests/test_whatsapp_inbox_self_chat.py`, REMOVA o teste `test_midia_na_self_chat_cai_no_caminho_normal_sem_erro` por inteiro (o comportamento dele — áudio cai no caminho normal — deixa de ser verdade) e substitua por estes DOIS testes, no mesmo lugar:

```python
def test_audio_na_self_chat_roteia_para_responder_audio(db, monkeypatch):
    user = User(
        tenant_id=TENANT_ID, email="dono2@example.com", name="Dono", password_hash="x",
        phone="5511988880001",
    )
    db.add(user)
    db.commit()

    chamada = {}

    def _fake_responder_audio(
        db, *, tenant_id, phone, wa_message_id, audio_bytes, audio_mime_type, profile,
    ):
        chamada.update(
            tenant_id=tenant_id, phone=phone, wa_message_id=wa_message_id,
            audio_bytes=audio_bytes, audio_mime_type=audio_mime_type,
        )

    monkeypatch.setattr(vc, "responder_audio", _fake_responder_audio)

    inbox_service.ingest_webhook_payload(
        db, tenant_id=TENANT_ID,
        messages=[_self_chat_msg(
            wa_message_id="self.audio", kind="audio", text_body="",
            from_phone="5511988880001", chat_jid="5511988880001@s.whatsapp.net",
            media_bytes=b"\x00\x01audio-bytes", media_mime_type="audio/ogg",
        )],
    )

    assert chamada == {
        "tenant_id": TENANT_ID, "phone": "5511988880001", "wa_message_id": "self.audio",
        "audio_bytes": b"\x00\x01audio-bytes", "audio_mime_type": "audio/ogg",
    }
    assert db.scalar(select(WhatsappMessage)) is None  # não gravou no inbox normal
    assert db.scalar(select(Client)) is None  # não virou lead


def test_imagem_na_self_chat_continua_no_caminho_normal_sem_erro(db, monkeypatch):
    # Só texto e áudio viram pergunta à Vima; outra mídia (imagem/documento/vídeo) continua
    # caindo no comportamento JÁ EXISTENTE (grava mensagem, sem virar lead) — o ponto de
    # extensão que a fatia de texto deixou marcado, agora restrito ao que não é áudio.
    user = User(
        tenant_id=TENANT_ID, email="dono2b@example.com", name="Dono", password_hash="x",
        phone="5511988880009",
    )
    db.add(user)
    db.commit()

    chamado = {"n": 0}
    monkeypatch.setattr(vc, "responder", lambda *a, **kw: chamado.update(n=chamado["n"] + 1))
    monkeypatch.setattr(
        vc, "responder_audio", lambda *a, **kw: chamado.update(n=chamado["n"] + 1)
    )

    inbox_service.ingest_webhook_payload(
        db, tenant_id=TENANT_ID,
        messages=[_self_chat_msg(
            wa_message_id="self.imagem", kind="image", text_body="",
            from_phone="5511988880009", chat_jid="5511988880009@s.whatsapp.net",
        )],
    )

    assert chamado["n"] == 0  # não roteou para a Vima
    row = db.scalar(select(WhatsappMessage).where(WhatsappMessage.wa_message_id == "self.imagem"))
    assert row is not None  # gravou normalmente, como antes desta feature
    assert db.scalar(select(Client)) is None
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `cd apps/api && pytest tests/test_whatsapp_inbox_self_chat.py -v`
Expected: FAIL em `test_audio_na_self_chat_roteia_para_responder_audio` (o roteamento ainda não existe — o áudio ainda cai no caminho normal, então `chamada` fica vazio e a asserção de igualdade falha).

- [ ] **Step 3: Implementar**

Em `apps/api/app/modules/whatsapp_inbox/service.py`, no bloco de import de `app.modules.whatsapp_inbox.models` (linhas ~31-45), acrescente `KIND_AUDIO` à tupla:

```python
from app.modules.whatsapp_inbox.models import (
    CHAT_KIND_DIRECT,
    CHAT_KIND_GROUP,
    DIRECTION_IN,
    DIRECTION_OUT,
    KIND_AUDIO,
    KIND_TEXT,
    LEGACY_CHAT_JID,
    MEDIA_STATUS_DOWNLOADED,
    MEDIA_STATUS_FAILED,
    MEDIA_STATUS_NONE,
    MEDIA_STATUS_PENDING,
    PublicWhatsappAccount,
    WhatsappChat,
    WhatsappMessage,
)
```

Em seguida, troque o bloco do self-chat (dentro do `for msg in messages:`, o `if msg.from_me and da_equipe and msg.kind == KIND_TEXT:` de hoje):

```python
            # Self-chat: o dono perguntando à Vima pelo próprio número conectado. Só existe no
            # Evolution — `from_me` é exclusivo daquele transporte (a Meta nunca entrega mensagem
            # própria no webhook, ver `core/whatsapp/inbound.py`) —, então não há guarda extra de
            # "é Evolution?" aqui: a condição já é estruturalmente inalcançável na Meta. Mídia no
            # mesmo self-chat cai no comportamento normal abaixo — ponto de extensão da fatia de
            # voz (ver a spec).
            if msg.from_me and da_equipe and msg.kind == KIND_TEXT:
                vima_whatsapp.responder(
                    db, tenant_id=tenant_id, phone=msg.from_phone,
                    wa_message_id=msg.wa_message_id, texto=msg.text_body, profile=profile,
                )
                db.commit()
                continue
```

por:

```python
            # Self-chat: o dono perguntando à Vima pelo próprio número conectado. Só existe no
            # Evolution — `from_me` é exclusivo daquele transporte (a Meta nunca entrega mensagem
            # própria no webhook, ver `core/whatsapp/inbound.py`) —, então não há guarda extra de
            # "é Evolution?" aqui: a condição já é estruturalmente inalcançável na Meta. TEXTO e
            # ÁUDIO (transcrito antes de responder, ver `vima/whatsapp_conversa
            # .responder_audio`) viram pergunta; outra mídia (imagem/documento/vídeo) cai no
            # comportamento normal abaixo.
            if msg.from_me and da_equipe and msg.kind in (KIND_TEXT, KIND_AUDIO):
                if msg.kind == KIND_TEXT:
                    vima_whatsapp.responder(
                        db, tenant_id=tenant_id, phone=msg.from_phone,
                        wa_message_id=msg.wa_message_id, texto=msg.text_body, profile=profile,
                    )
                else:
                    vima_whatsapp.responder_audio(
                        db, tenant_id=tenant_id, phone=msg.from_phone,
                        wa_message_id=msg.wa_message_id, audio_bytes=msg.media_bytes or b"",
                        audio_mime_type=msg.media_mime_type or "", profile=profile,
                    )
                db.commit()
                continue
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `cd apps/api && pytest tests/test_whatsapp_inbox_self_chat.py tests/test_vima_whatsapp_conversa.py tests/test_whatsapp_inbox_service.py -v`
Expected: PASS em todos.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/modules/whatsapp_inbox/service.py apps/api/tests/test_whatsapp_inbox_self_chat.py
git commit -m "feat: self-chat de áudio roteia para responder_audio — voz vira pergunta à Vima"
```

---

### Task 5: suíte completa, CLAUDE.md e commit final

**Files:**
- Modify: `CLAUDE.md`

**Interfaces:** (nenhuma — só documentação e verificação)

- [ ] **Step 1: Rodar a suíte inteira do backend**

Run: `cd apps/api && ruff check . && pytest -q`
Expected: `ruff check .` limpo; `pytest -q` — todos os testes passam (nenhuma regressão nos módulos tocados: `ai_usage`, `transcription`, `vima/whatsapp_conversa`, `whatsapp_inbox/service`).

Se algo falhar, corrija antes de prosseguir — não há passo de "ignorar por enquanto" neste plano.

- [ ] **Step 2: Escrever a entrada no CLAUDE.md**

Abra `CLAUDE.md` (raiz do repo) e localize a seção `## Vima: canal WhatsApp (self-chat, Evolution) (2026-08-28)`. Ela termina com o bloco:

```markdown
**Fora de escopo, declarado:**
- Meta como transporte — sem `from_me`, sem self-chat possível no modelo da Meta.
- Entrada por voz (nota de áudio) — o ponto de extensão fica marcado, a transcrição em si não é
  desta fatia.
- Saída por voz.
- Ativação por palavra-chave — toda mensagem de texto no self-chat é pergunta, por decisão.
- Qualquer persistência da conversa, permanente ou não além do cache curto acima.
```

Troque a linha `- Entrada por voz (nota de áudio) — o ponto de extensão fica marcado, a transcrição em si não é\n  desta fatia.` por:

```markdown
- ~~Entrada por voz (nota de áudio)~~ — **FEITO**, ver a seção logo abaixo.
```

Logo depois desse bloco (`Qualquer persistência da conversa...`) e ANTES da próxima seção (`## Vima: o Registro de Fatos e o briefing`), insira a nova seção inteira:

```markdown

## Vima: voz na entrada (self-chat, Evolution) (2026-08-29)

> Spec: `docs/superpowers/specs/2026-08-29-vima-voz-entrada-design.md` ·
> Plano: `docs/superpowers/plans/2026-08-29-vima-voz-entrada.md`

Terceira fatia do caminho até o Jarbes. O dono manda uma nota de voz para a própria self-chat —
o mesmo gatilho da fatia de texto (PR #268), agora também para `kind == "audio"` — e a Vima
transcreve (Groq, Whisper) antes de responder pelo MESMO mecanismo que já atende texto. Só
ENTRADA: a resposta continua sempre em texto.

- [x] **`core/transcription.py` — segundo provedor de IA do repositório, irmão de `core/ai.py`.**
  A API de mensagens da Anthropic não aceita áudio como entrada; a Groq (Whisper) é quem
  transcreve. `transcribe(db, *, tenant_id, audio_bytes, mime_type, user_id=None)` segue a
  MESMA obrigatoriedade de `core/ai.py` (`db`/`tenant_id` obrigatórios — impossível chamar a
  Groq sem contabilizar) e nunca levanta: `None` em qualquer falha (sem `GROQ_API_KEY`, erro
  HTTP, erro de rede, texto vazio), para o chamador decidir a desculpa.
- [x] **`ai_usage` ganhou `provider` e `audio_seconds`** (migration 0084). `provider` tem
  default `'anthropic'` PERMANENTE — os call sites existentes não mudaram; só `vima.transcricao`
  passa `provider='groq'` explícito, com `audio_seconds` preenchido (a Groq cobra por segundo de
  áudio, não por token — por isso a coluna é irmã, nunca achatada em `input_tokens`).
- [x] **`vima/whatsapp_conversa.responder_audio`** — transcreve e delega para o MESMO mecanismo
  interno (`_responder`) que `responder()` (texto) já usava; a assinatura pública de `responder`
  não mudou. A resposta final ecoa o que foi entendido (`🎤 "pergunta entendida" — resposta`),
  porque o dono nunca vê a transcrição em lugar nenhum — sem o eco, um erro de transcrição vira
  resposta certa para a pergunta errada, sem nenhuma pista do porquê.
  - **Falha na transcrição:** mesma disciplina de "falha nunca fica muda" da fatia anterior —
    desculpa padrão pelo mesmo canal, sem chamar `pergunta.responder`.
  - **Dedup ANTES de transcrever:** uma reentrega do webhook não paga a Groq de novo — o mesmo
    `wa_message_id` é checado antes da chamada cara, não só dentro do mecanismo compartilhado.
- [x] **`whatsapp_inbox/service.py`** — a condição de self-chat passou de
  `msg.kind == KIND_TEXT` para `msg.kind in (KIND_TEXT, KIND_AUDIO)`. Os bytes/mime do áudio já
  chegam decodificados no parse do provider Evolution (`media_bytes`/`media_mime_type`) — sem
  fetch adicional, processamento continua síncrono dentro do próprio webhook. Outra mídia
  (imagem/documento/vídeo) no mesmo self-chat continua caindo no comportamento normal, como
  antes desta fatia.
- **PII — decisão nova, não herdada por analogia:** o áudio bruto (voz do dono) sai para a Groq
  sem qualquer anonimização — não existe anonimização de voz. É diferente do risco aceito em
  2026-07-11 (aquele é sobre dado ESTRUTURADO); aqui é a gravação inteira. Aceito pelo dono do
  produto para esta fatia; o áudio em si nunca é persistido em lugar nenhum (nem banco, nem
  disco, nem cache) além da chamada síncrona à Groq.

**Fora de escopo, declarado:**
- Saída por voz (TTS) — a resposta da Vima continua sempre em texto.
- Ativação por palavra-chave — inalterado, toda mensagem (texto OU áudio) é pergunta.
- Limite de duração/tamanho de áudio — sem validação própria; um áudio acima do teto da Groq
  falha na chamada e cai no caminho de erro já descrito.
- Qualquer persistência de áudio ou transcrição além do cache curto de texto que
  `whatsapp_conversa.py` já mantinha para a fatia de texto.
```

- [ ] **Step 3: Commit final da documentação**

```bash
git add CLAUDE.md
git commit -m "docs: CLAUDE.md registra a voz na entrada da Vima — self-chat, Evolution, Groq"
```
