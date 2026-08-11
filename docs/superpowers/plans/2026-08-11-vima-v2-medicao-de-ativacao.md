# Vima V2 — medição de ativação do núcleo: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this
> plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** o DNA passa a deixar rastro append em `audit_entries` de tudo que acontece com ele —
respondida, pulada, núcleo aberto, núcleo abandonado — mais um script que lê esse rastro.

**Architecture:** quatro `action`s novas em `audit_entries` (zero migration: `action` é
`String(128)` e `target` é `String(255)`), emitidas por uma **porta única** (`dna/eventos.py`)
que valida o vocabulário na hora e é guardada por allowlist de call sites. O `source`
(`nucleo｜gancho｜config`) vai no **`target`**, nunca no `action`. Duas rotas novas viram uma só
(`POST /dna/nucleo/{evento}`). A leitura é script, não tela.

**Tech Stack:** FastAPI (Python 3.13) · SQLAlchemy 2 · pytest · React 18 + Vite + TS · vitest.

**Fonte da verdade:** `docs/superpowers/specs/2026-08-11-vima-v2-medicao-de-ativacao-design.md`
(APROVADA e mergeada em `main @ d36bbf3`, PR #109). O desenho está fechado — este plano só o
executa. Toda referência `§N` abaixo é a essa spec.

**Worktree:** `.claude/worktrees/vima-v2-medicao`, branch `feat/vima-v2-medicao-ativacao`,
criada de `origin/main @ d36bbf3`.

---

## Global Constraints

Valem para **toda** tarefa deste plano. Não repetidas em cada uma.

- **ZERO migration.** `audit_entries.action` é `String(128)` e `target` é `String(255)`. Se você
  se pegar escrevendo um arquivo em `apps/api/migrations/versions/`, parou de seguir o plano.
- **`source` vai no `target`, NUNCA no `action`** (§3.2). Quatro actions × três sources seriam
  doze strings, e é assim que 117 viram 200.
- **Toda `action` do módulo `dna` começa com `dna.`** e está na tupla `eventos.ACTIONS` (§6.3).
- **Nenhuma tela, nenhum dashboard, nenhum endpoint de leitura, nenhum limiar** (§0.2). Instrumentar,
  não analisar.
- **O beacon NUNCA tranca a porta** (§6.2). O `abandon` é disparado e a saída **não o aguarda** —
  nem `await` bloqueante antes do `navigate`, nem `catch` que desvie o fluxo.
- **A autoridade do `localStorage` (`e1p_dna_nucleo`) NÃO se move para o servidor** (§7). Está
  fora de escopo de propósito: seria mudança de comportamento embutida numa onda de medição.
- **Datas no fuso do tenant** (§6.6). `local_date` / `format_datetime_br` / `hoje_do_tenant`,
  nunca `datetime.now(UTC).date()` nem `.date()` em `timestamptz`. `apps/api/app/modules/dna/`
  já está na varredura AST de `tests/test_fuso_do_tenant.py`; **todo arquivo novo naquela pasta
  entra no gate automaticamente** (o teste é `parametrize` sobre `DNA_DIR.glob("*.py")`).
- **Todo gate tem controle positivo** (§6.3, §6.5). Sem ele, um gate que deixasse de encontrar o
  que varre passa verde por vacuidade.
- **Idioma** (`CLAUDE.md` §8): produto e comentários de domínio em **PT-BR**; identificadores em
  inglês quando o domínio é técnico, em PT-BR quando é domínio de negócio (o módulo `dna` já usa
  `responder`/`pular`/`faltantes` — siga o vizinho).
- **Commits: Conventional Commits**, com o sufixo `[Vima V2]`.

### Comandos (rode as etapas INDIVIDUALMENTE)

`scripts/check.sh` mascara falha de frontend com `|| true` no vitest e resolve `ruff`/`python` do
PATH (que pode não ser o do venv). **Não o use.** Use, sempre com caminho absoluto (o cwd do Bash
reseta depois de invocar um Skill):

```bash
# Python — venv ÚNICO do repositório, mesmo rodando de dentro da worktree
PY=/f/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe
WT=/f/Projetos/e1p/escritorio-1-pessoa/.claude/worktrees/vima-v2-medicao

cd $WT/apps/api && $PY -m pytest tests/test_dna_router.py -q      # um arquivo
cd $WT/apps/api && $PY -m pytest -q                                # a suíte inteira
cd $WT/apps/api && $PY -m ruff check app tests
cd $WT/apps/api && TZ=UTC $PY -m pytest -q                         # ver "Se a suíte quebrar"

# Frontend
cd $WT && pnpm --filter @e1p/web test -- --run
cd $WT && pnpm --filter @e1p/web typecheck
```

**Se a suíte quebrar:** reproduza com `TZ=UTC` **antes** de culpar o seu diff. É classe reincidente
neste repositório (#84 corrigiu, #90 e #101 voltaram por frestas do gate).

**Autoridade:** `main` é protegida (push direto = `GH006`). `git push` e `gh pr create` são
**exclusivos do @devops** — ao terminar, delegue; não execute.

---

## File Structure

| Arquivo | Responsabilidade | Tarefa |
|---|---|---|
| `apps/api/app/modules/dna/eventos.py` **(criar)** | O vocabulário (4 constantes + `ACTIONS`) e `registrar()`, a **única** função do módulo que chama `audit.record`. Valida `dna.`-prefixo e pertinência à tupla na hora. | 1 |
| `apps/api/app/modules/dna/service.py` **(modificar)** | `_gravar` ganha `db.flush()` + `eventos.registrar(...)` antes do commit; `responder`/`pular` passam a ação. | 1 |
| `apps/api/app/modules/dna/models.py` **(modificar)** | A docstring da linha 5 deixa de ser falsa: ganha a lista de call sites verificável por `grep`. | 1 |
| `apps/api/tests/test_dna_audit.py` **(criar)** | §6.1 (target correto), §6.4 (duas entradas / uma linha) e o `source` chegando ao `target` nas três origens. | 1 |
| `apps/api/tests/test_dna_vocabulario_gate.py` **(criar)** | §6.3: allowlist de call sites por AST + o vocabulário, **com controle positivo**. | 1 |
| `apps/api/app/modules/dna/schemas.py` **(modificar)** | `NucleoEventoIn` (`exibidas: int \| None`). | 2 |
| `apps/api/app/modules/dna/router.py` **(modificar)** | `POST /dna/nucleo/{evento}` → 204. | 2 |
| `apps/api/tests/test_dna_nucleo_eventos.py` **(criar)** | §3.3 (403 não produz evento, **com** controle positivo), open/abandon, evento fora da tupla → 404. | 2 |
| `apps/web/src/features/dna/NucleoPage.tsx` **(modificar)** | Dispara os dois beacons, sem nunca trancar a entrada. | 3 |
| `apps/web/src/features/dna/NucleoPage.test.tsx` **(modificar)** | §6.2: a covardia, mecanizada. | 3 |
| `apps/api/app/scripts/nucleo_activation.py` **(criar)** | A leitura. Sem `--fix`. Imprime quantos tenants varreu. | 4 |
| `apps/api/tests/test_nucleo_activation.py` **(criar)** | §6.5: a derivação, **com** controle positivo (`k > 0`). | 4 |
| `CLAUDE.md` **(modificar)** | A entrada — AC obrigatório (§5, passo 4). Escrita a partir do código que subiu. | 5 |

**Por que `eventos.py` é um arquivo próprio e não constantes no `models.py`:** ele carrega uma
**função guardada** (`registrar`), não só strings. Pô-la no `models.py` faria o model importar
`core.audit`, e a allowlist do gate perderia o alvo óbvio. O precedente do repo é
`bank/origin.py::sync_origin_movement` — "a única função do repositório que escreve `source ∈
SOURCES_SISTEMA`, guardada por allowlist de call sites".

---

## Task 1: A trilha nasce em `responder`/`pular`, e o vocabulário tem dono

Fecha §6.1, §6.3, §6.4 e os itens 1, 4, 5 e 8 da Definição de pronto.

**Files:**
- Create: `apps/api/app/modules/dna/eventos.py`
- Modify: `apps/api/app/modules/dna/service.py` (`_gravar`, `responder`, `pular`)
- Modify: `apps/api/app/modules/dna/models.py:1-9` (docstring)
- Test: `apps/api/tests/test_dna_audit.py` (criar)
- Test: `apps/api/tests/test_dna_vocabulario_gate.py` (criar)

**Interfaces:**
- Consumes: `app.core.audit.record(db, *, tenant_id, actor, action, target="", is_ai=False)` —
  já existe, **não mude a assinatura**.
- Produces (a Task 2 e a Task 4 dependem destes nomes exatos):
  - `eventos.ACTION_SAVE: str = "dna.answer.save"`
  - `eventos.ACTION_SKIP: str = "dna.answer.skip"`
  - `eventos.ACTION_OPEN: str = "dna.nucleo.open"`
  - `eventos.ACTION_ABANDON: str = "dna.nucleo.abandon"`
  - `eventos.ACTIONS: tuple[str, ...]` — as quatro, nesta ordem
  - `eventos.EVENTOS_DO_NUCLEO: dict[str, str]` — `{"open": ACTION_OPEN, "abandon": ACTION_ABANDON}`
  - `eventos.PREFIXO: str = "dna."`
  - `eventos.alvo_da_resposta(source: str, key: str) -> str` — devolve `f"{source}:{key}"`
  - `eventos.VocabularioError(Exception)`
  - `eventos.registrar(db, *, tenant_id: str, actor: str, action: str, target: str = "") -> AuditEntry`

---

- [ ] **Step 1: Escreva o gate de vocabulário falhando** (`apps/api/tests/test_dna_vocabulario_gate.py`)

Este passo vem primeiro de propósito: o gate é o artefato que impede a tarefa de ser feita errada,
e escrevê-lo depois é escrevê-lo sobre o que você já fez.

```python
"""§6.3 — o vocabulário do DNA tem uma porta só, e ela é guardada.

`facts.record` tem guarda mecânica equivalente (o `kind` tem de começar pelo `module`) e
`audit.record` **não tem nenhuma** — `account_deleted`, sem pontos e fora do padrão, é a prova de
que a convenção sozinha não segura o vocabulário. Sem esta guarda, quatro actions × três sources
viram doze strings, e é assim que 117 viram 200.

**Controle positivo obrigatório** em cada asserção: um gate que deixasse de encontrar as chamadas
(glob quebrado, `audit` importado com outro nome, pasta renomeada) passaria **verde por vacuidade**
— a família do "teste que passa e não prova nada" que o Epic 8 documenta oito vezes.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.modules.dna import eventos

_DNA_DIR = Path(__file__).resolve().parents[1] / "app" / "modules" / "dna"

# A allowlist tem UM membro, e é esse o ponto. Mesmo padrão de `_CHAMADORES_PERMITIDOS` do
# `sync_origin_movement`: quem precisar entrar aqui entra COM a justificativa, e é isso que faz a
# revisão acontecer — não a linha na lista.
_PODE_CHAMAR_AUDIT = {"eventos.py"}


def _chamadas_a_audit_record(fonte: str) -> list[int]:
    """Linhas de `audit.record(...)` — a forma que qualquer call site do repo usa."""
    linhas: list[int] = []
    for no in ast.walk(ast.parse(fonte)):
        if (
            isinstance(no, ast.Call)
            and isinstance(no.func, ast.Attribute)
            and no.func.attr == "record"
            and isinstance(no.func.value, ast.Name)
            and no.func.value.id == "audit"
        ):
            linhas.append(no.lineno)
    return linhas


def test_o_scanner_acha_o_que_promete_achar():
    """Controle positivo DO SCANNER. Sem ele, um scanner quebrado aprova o módulo inteiro."""
    achou = _chamadas_a_audit_record(
        "from app.core import audit\n"
        "audit.record(db, tenant_id=t, actor=a, action='dna.inventada', target='')\n"
    )
    assert achou == [2]
    # E o não-membro: uma chamada que NÃO é `audit.record` não pode ser contada.
    assert _chamadas_a_audit_record("facts.record(db, kind='crm.lead.created')\n") == []


def test_so_o_eventos_py_chama_audit_record():
    ofensores: list[str] = []
    for arquivo in sorted(_DNA_DIR.glob("*.py")):
        if arquivo.name in _PODE_CHAMAR_AUDIT:
            continue
        for linha in _chamadas_a_audit_record(arquivo.read_text(encoding="utf-8")):
            ofensores.append(f"{arquivo.name}:{linha}")
    assert not ofensores, (
        "Estes pontos gravam trilha por fora da porta do módulo, e por isso escapam da validação "
        f"de vocabulário. Use `eventos.registrar(...)`: {ofensores}"
    )


def test_a_porta_do_modulo_existe_de_fato():
    """Controle positivo do gate acima: se NINGUÉM mais chama, é porque `eventos.py` chama."""
    fonte = (_DNA_DIR / "eventos.py").read_text(encoding="utf-8")
    assert _chamadas_a_audit_record(fonte), (
        "`eventos.py` deixou de chamar `audit.record`. O gate acima passaria verde sobre um "
        "módulo que não grava trilha nenhuma — exatamente a vacuidade que ele existe para impedir."
    )


def test_toda_action_declarada_comeca_com_dna():
    assert eventos.ACTIONS, "a tupla está vazia: não há vocabulário para guardar"
    for action in eventos.ACTIONS:
        assert action.startswith(eventos.PREFIXO), action


def test_a_tupla_e_o_conjunto_que_a_spec_fechou():
    """A instanciação obrigatória: o conjunto tem membros escritos, e são estes quatro."""
    assert eventos.ACTIONS == (
        "dna.answer.save",
        "dna.answer.skip",
        "dna.nucleo.open",
        "dna.nucleo.abandon",
    )
    assert set(eventos.EVENTOS_DO_NUCLEO) == {"open", "abandon"}


@pytest.mark.parametrize("intrusa", ["settings.perfil.update", "dna.inventada", "account_deleted"])
def test_registrar_recusa_action_fora_da_tupla(intrusa: str):
    """O controle positivo que importa: a guarda MORDE.

    `dna.inventada` é o não-membro sutil — começa com `dna.` e mesmo assim é recusada, porque o
    prefixo sozinho não é o contrato. `account_deleted` é o membro real do repo que prova que a
    convenção sem guarda não segura nada.
    """
    with pytest.raises(eventos.VocabularioError):
        eventos.registrar(
            db=None, tenant_id="t", actor="u", action=intrusa, target=""
        )
```

- [ ] **Step 2: Rode o gate e veja falhar pelo motivo certo**

```bash
PY=/f/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe
cd /f/Projetos/e1p/escritorio-1-pessoa/.claude/worktrees/vima-v2-medicao/apps/api
$PY -m pytest tests/test_dna_vocabulario_gate.py -q
```

Esperado: **erro de coleção** — `ModuleNotFoundError: No module named 'app.modules.dna.eventos'`.
Se você vir qualquer outra falha, leia antes de seguir.

- [ ] **Step 3: Escreva `apps/api/app/modules/dna/eventos.py`**

```python
"""O vocabulário do rastro do DNA, e a única porta que o grava.

**Por que existe.** `dna_answers` é upsert por `(tenant, question_key)`: responder no núcleo e
editar depois no `/config` sobrescreve `value`, `answered_at`, `answered_by` **e `source`** — a
linha passa a dizer que a resposta nasceu no `/config`, e o fato de ela ter vindo do núcleo, e
*quando*, deixa de existir. A docstring de `models.py` sempre defendeu o upsert dizendo que "o
histórico de quem mudou o quê já é trabalho de `core/audit.py`". Até 2026-08-11 isso era falso:
`audit` aparecia UMA vez no módulo `dna`, dentro daquela frase, com zero chamadas. Este módulo é
o que torna a frase verdadeira.

**`source` vai no `target`, NUNCA no `action`.** Quatro actions × três sources (`nucleo｜gancho｜
config`) seriam doze strings, e é assim que 117 actions distintas viram 200. O repo já tem
`account_deleted` — sem pontos, fora do padrão `<entidade>.<entidade>.<verbo>` — provando que a
convenção sozinha não segura o vocabulário.

**Por que a validação é aqui e não uma convenção.** `facts.record` tem guarda mecânica (o `kind`
tem de começar pelo `module`); `audit.record` não tem nenhuma. Esta função é a guarda equivalente
para o DNA, e `tests/test_dna_vocabulario_gate.py` garante por AST que ela é o único caminho.

Consumidores (verificável por `grep -rn "eventos.registrar" apps/api/app/modules/dna/`):
`service._gravar` (save/skip) e `router.nucleo_evento` (open/abandon). **Se esta lista divergir do
grep, ela é que está errada** — a lista de consumidores numa docstring tem de ser verificável.
"""
from __future__ import annotations

from app.core import audit

PREFIXO = "dna."

ACTION_SAVE = "dna.answer.save"
ACTION_SKIP = "dna.answer.skip"
ACTION_OPEN = "dna.nucleo.open"
ACTION_ABANDON = "dna.nucleo.abandon"

#: O conjunto fechado. Acrescentar aqui é a única forma de emitir uma action nova.
ACTIONS: tuple[str, ...] = (ACTION_SAVE, ACTION_SKIP, ACTION_OPEN, ACTION_ABANDON)

#: A rota nova é UMA, com o evento no caminho: `POST /dna/nucleo/{evento}`. Porta estreita
#: validada contra um conjunto, como `service._validar` já faz contra o catálogo.
EVENTOS_DO_NUCLEO: dict[str, str] = {"open": ACTION_OPEN, "abandon": ACTION_ABANDON}


class VocabularioError(Exception):
    """Erro de programação, não de usuário: estoura na hora, como `FactError`."""


def alvo_da_resposta(source: str, key: str) -> str:
    """O `target` de uma resposta: `<source>:<pergunta>`.

    É esta string que sobrevive ao upsert e distingue "respondeu no núcleo" de "editou no
    `/config`" — as duas linhas de audit que o `dna_answers` não consegue guardar.
    """
    return f"{source}:{key}"


def registrar(db, *, tenant_id: str, actor: str, action: str, target: str = ""):
    """Grava a trilha do DNA, validando o vocabulário AGORA.

    ⚠️ Quem chama é responsável pelo `db.flush()` quando o `target` depende de uma linha recém
    adicionada — o `id` tem default Python-side e só existe depois do INSERT (defeito MNT-001, 17
    call sites no projeto; o módulo `bank` já faz certo).
    """
    if not action.startswith(PREFIXO) or action not in ACTIONS:
        raise VocabularioError(
            f"'{action}' não é uma action do DNA. O vocabulário é fechado e mora em "
            f"`eventos.ACTIONS`: {ACTIONS}. Se o evento é novo, declare-o lá — e note que o "
            "`source` vai no TARGET, nunca no action."
        )
    return audit.record(db, tenant_id=tenant_id, actor=actor, action=action, target=target)
```

- [ ] **Step 4: Rode o gate e veja passar**

```bash
cd /f/Projetos/e1p/escritorio-1-pessoa/.claude/worktrees/vima-v2-medicao/apps/api
$PY -m pytest tests/test_dna_vocabulario_gate.py -q
```

Esperado: **PASS**, 7 testes (os 3 `parametrize` contam separado).

- [ ] **Step 5: Escreva os testes de comportamento falhando** (`apps/api/tests/test_dna_audit.py`)

```python
"""§6.1 e §6.4 — o upsert deixa de apagar a história.

O teste de maior valor da onda é `test_editar_no_config_nao_apaga_a_historia_do_nucleo`: ele é a
diferença entre o upsert apagar história e o upsert ser só estado atual.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import AuditEntry
from app.modules.dna.models import DnaAnswer

REGISTER = {
    "legal_name": "Medicao ME",
    "document": "11444777000161",
    "slug": "medicaome",
    "email": "medicao@example.com",
    "name": "Flávio",
    "password": "uma-senha-bem-grande",
}

TICKET = "oferta.ticket_tipico"


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _alvos(db: Session, action: str) -> list[str]:
    return [
        e.target
        for e in db.scalars(select(AuditEntry).where(AuditEntry.action == action)).all()
    ]


def test_responder_grava_trilha_com_o_source_no_target(
    client: TestClient, headers: dict[str, str], db: Session
):
    """§6.1. A asserção é o VALOR do target, não `!= ""`.

    `target != ""` passaria com qualquer string — inclusive com a errada. Afirmar o valor exato é
    o que faz este teste morrer se alguém trocar o `source` de lugar (para o `action`, que é a
    forma proibida) ou esquecer a chave da pergunta.
    """
    r = client.put(TICKET, json={"valor": "2k_10k", "source": "nucleo"}, headers=headers)
    assert r.status_code == 200

    assert _alvos(db, "dna.answer.save") == [f"nucleo:{TICKET}"]


def test_pular_uma_pergunta_grava_trilha(
    client: TestClient, headers: dict[str, str], db: Session
):
    r = client.post(f"{TICKET}/pular", json={"source": "gancho"}, headers=headers)
    assert r.status_code == 200

    assert _alvos(db, "dna.answer.skip") == [f"gancho:{TICKET}"]
    # Não-membro: pular não é salvar.
    assert _alvos(db, "dna.answer.save") == []


def test_editar_no_config_nao_apaga_a_historia_do_nucleo(
    client: TestClient, headers: dict[str, str], db: Session
):
    """§6.4 — o teste de maior valor da onda.

    Responder no núcleo e, semanas depois, editar a mesma pergunta na aba de `/config` fazia a
    linha passar a dizer que aquela resposta NASCEU no `/config`. O upsert continua sendo upsert:
    o que muda é que a história agora mora noutro lugar, que é append.
    """
    client.put(TICKET, json={"valor": "2k_10k", "source": "nucleo"}, headers=headers)
    client.put(TICKET, json={"valor": "10k_50k", "source": "config"}, headers=headers)

    # O upsert continua sendo upsert: UMA linha, com o estado ATUAL.
    linhas = db.scalars(select(DnaAnswer).where(DnaAnswer.question_key == TICKET)).all()
    assert len(linhas) == 1
    assert linhas[0].value == "10k_50k"
    assert linhas[0].source == "config"

    # E a história das DUAS passagens sobrevive.
    assert sorted(_alvos(db, "dna.answer.save")) == [f"config:{TICKET}", f"nucleo:{TICKET}"]
```

⚠️ **Atenção às rotas nos `client.put`/`client.post` acima:** o router tem `prefix="/dna"`, então
o caminho real é `/dna/oferta.ticket_tipico`. Escreva `f"/dna/{TICKET}"` — o trecho acima está
propositalmente com o caminho relativo para você **não** copiar sem ler. Corrija ao escrever o
arquivo.

- [ ] **Step 6: Rode e veja falhar**

```bash
cd /f/Projetos/e1p/escritorio-1-pessoa/.claude/worktrees/vima-v2-medicao/apps/api
$PY -m pytest tests/test_dna_audit.py -q
```

Esperado: **3 failed** — `assert [] == ['nucleo:oferta.ticket_tipico']`. Nenhuma trilha existe
ainda. Se falhar com 404 na rota, você não corrigiu o caminho do Step 5.

- [ ] **Step 7: Ligue a trilha em `service.py`**

Em `apps/api/app/modules/dna/service.py`, acrescente o import e mude as três funções:

```python
from app.modules.dna import catalog, eventos          # `eventos` é novo na linha do import
from app.modules.dna.models import DnaAnswer
```

```python
def responder(
    db: Session,
    *,
    tenant_id: str,
    key: str,
    valor: Any,
    user_id: str | None,
    source: str,
) -> DnaAnswer:
    """Grava a resposta, validando contra o catálogo. Commita."""
    pergunta = _pergunta(key)
    _validar(pergunta, valor)
    return _gravar(
        db, tenant_id=tenant_id, key=key, valor=valor, user_id=user_id, source=source,
        acao=eventos.ACTION_SAVE,
    )


def pular(
    db: Session, *, tenant_id: str, key: str, user_id: str | None, source: str
) -> DnaAnswer:
    """Registra que o dono viu e pulou. `value` nulo é o registro — não é linha ausente."""
    _pergunta(key)
    return _gravar(
        db, tenant_id=tenant_id, key=key, valor=None, user_id=user_id, source=source,
        acao=eventos.ACTION_SKIP,
    )
```

```python
def _gravar(
    db: Session,
    *,
    tenant_id: str,
    key: str,
    valor: Any,
    user_id: str | None,
    source: str,
    acao: str,
) -> DnaAnswer:
    """Upsert por `(tenant, pergunta)` — a unique constraint da migration é o que o garante.

    ⚠️ **`db.flush()` ANTES de `eventos.registrar`, e a razão aqui NÃO é a do MNT-001.** O padrão
    do repo (`bank.create_account`) existe porque o `target` costuma ser o `id` da linha, que tem
    default Python-side e ainda é `None` antes do INSERT. Este `target` é
    `<source>:<pergunta>` e não depende de `id` nenhum — mas o flush continua sendo obrigatório
    pelo segundo motivo que `bank.create_transaction` documenta: é no flush que a unique
    constraint de `(tenant, question_key)` fala. Sem ele, gravaríamos um rastro afirmando uma
    resposta que a constraint ainda pode recusar — trilha que mente.
    """
    linha = db.scalar(select(DnaAnswer).where(DnaAnswer.question_key == key))
    if linha is None:
        linha = DnaAnswer(tenant_id=tenant_id, question_key=key)
        db.add(linha)
    linha.value = valor
    linha.answered_at = datetime.now(UTC)
    linha.answered_by = user_id
    linha.source = source
    db.flush()
    eventos.registrar(
        db,
        tenant_id=tenant_id,
        actor=user_id or "",
        action=acao,
        target=eventos.alvo_da_resposta(source, key),
    )
    db.commit()
    db.refresh(linha)
    return linha
```

- [ ] **Step 8: Rode e veja passar**

```bash
cd /f/Projetos/e1p/escritorio-1-pessoa/.claude/worktrees/vima-v2-medicao/apps/api
$PY -m pytest tests/test_dna_audit.py tests/test_dna_vocabulario_gate.py -q
```

Esperado: **PASS** (3 + 7).

- [ ] **Step 9: Torne a docstring de `models.py` verdadeira** (DoD 8)

Substitua o parágrafo das linhas 3-5 de `apps/api/app/modules/dna/models.py` por:

```python
"""A resposta do DNA — estado atual, não história.

**É upsert, não append — o oposto de `core/facts.py`, e de propósito.** Fato é história; DNA é
estado atual. Guardar versões faria toda leitura ter que decidir qual resposta vale.

**O histórico de quem mudou o quê é trabalho de `core/audit.py`, e desde 2026-08-11 isso é
verdade.** Até essa data a frase acima estava escrita aqui e não tinha código atrás: `audit`
aparecia UMA vez no módulo inteiro, dentro dela, com zero chamadas. Era a classe de defeito nº 1
do Epic 8 — o documento que afirma sobre a camada de baixo e desliga quem viria conferir —, e aqui
mais grave, porque **sustentava uma decisão de modelagem**: o upsert foi aceito em troca de uma
rede que ninguém tinha tecido.

Quem grava, hoje (verificável por `grep -rn "eventos.registrar" apps/api/app/modules/dna/`):
`service._gravar` → `dna.answer.save` / `dna.answer.skip`, com `target=<source>:<pergunta>`;
`router.nucleo_evento` → `dna.nucleo.open` / `dna.nucleo.abandon`. **Se esta lista divergir do
grep, é ela que está errada.**

`value` nulo NÃO é ausência de linha: é "o dono viu a pergunta e pulou". A distinção sustenta a
quarentena de 7 dias em `cadencia.py` sem tabela nova.
"""
```

- [ ] **Step 10: Rode o módulo inteiro + o gate de fuso**

```bash
cd /f/Projetos/e1p/escritorio-1-pessoa/.claude/worktrees/vima-v2-medicao/apps/api
$PY -m pytest tests/test_dna_audit.py tests/test_dna_vocabulario_gate.py tests/test_dna_router.py \
  tests/test_dna_service.py tests/test_dna_models.py tests/test_dna_cadencia.py \
  tests/test_dna_catalog.py tests/test_dna_resolver.py tests/test_dna_briefing.py \
  tests/test_fuso_do_tenant.py -q
$PY -m ruff check app tests
```

Esperado: **PASS** em tudo. `test_fuso_do_tenant.py` importa: `eventos.py` é arquivo novo em
`app/modules/dna/` e o gate o varre automaticamente — ele não lê relógio, então passa.

- [ ] **Step 11: Commit**

```bash
cd /f/Projetos/e1p/escritorio-1-pessoa/.claude/worktrees/vima-v2-medicao
git add apps/api/app/modules/dna/eventos.py apps/api/app/modules/dna/service.py \
        apps/api/app/modules/dna/models.py apps/api/tests/test_dna_audit.py \
        apps/api/tests/test_dna_vocabulario_gate.py
git commit -m "feat: o DNA deixa rastro, e a docstring que prometia isso vira verdade [Vima V2]"
```

---

## Task 2: `POST /dna/nucleo/{evento}` — o núcleo aberto e o abandonado

Fecha §3.3, §3.4 e os itens 2 e 3 (metade de servidor) da Definição de pronto.

**Files:**
- Modify: `apps/api/app/modules/dna/schemas.py` (acrescentar `NucleoEventoIn`)
- Modify: `apps/api/app/modules/dna/router.py` (rota nova, **antes** de `PUT /{key}`)
- Test: `apps/api/tests/test_dna_nucleo_eventos.py` (criar)

**Interfaces:**
- Consumes: `eventos.EVENTOS_DO_NUCLEO`, `eventos.registrar` (Task 1).
- Produces (a Task 3 depende deste contrato exato):
  - `POST /dna/nucleo/open`, corpo `{"exibidas": <int >= 1>}` → **204** sem corpo
  - `POST /dna/nucleo/abandon`, corpo `{}` → **204** sem corpo
  - evento fora de `{open, abandon}` → **404**
  - `open` sem `exibidas` (ou `< 1`) → **422**
  - sem o módulo `settings` → **403**, e **nenhuma** entrada de audit

---

- [ ] **Step 1: Escreva o teste falhando** (`apps/api/tests/test_dna_nucleo_eventos.py`)

```python
"""§3.3 — o caminho de erro grava NADA, e é isso que o torna distinguível.

`dna.nucleo.open` é emitido DEPOIS de `GET /dna/faltantes` responder com sucesso, isto é, depois
de a pessoa ter de fato visto perguntas. Gravar `abandon` no caminho de erro seria mentira; criar
um terceiro evento (`dna.nucleo.unavailable`) seria categoria que ninguém pediu, com um consumidor
que não existe. Com `open` condicionado ao sucesso, **ausência de `open` ⇒ a pessoa nunca entrou**
— verdade, derivada, sem evento novo.

**Membro** de "abandonou o núcleo": um tenant com `dna.nucleo.open`, dois `dna.answer.save` e
`dna.nucleo.abandon`.
**Não-membro:** um sub-usuário sem o módulo `settings` que tomou 403 — nenhum evento, e o
relatório não o conta como abandono.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import AuditEntry
from app.core.security import create_access_token

REGISTER = {
    "legal_name": "Nucleo ME",
    "document": "11444777000161",
    "slug": "nucleome",
    "email": "nucleo@example.com",
    "name": "Flávio",
    "password": "uma-senha-bem-grande",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def tenant_id(client: TestClient, headers: dict[str, str]) -> str:
    return client.get("/auth/me", headers=headers).json()["user"]["tenant_id"]


@pytest.fixture()
def headers_sub_crm(tenant_id: str) -> dict[str, str]:
    """Sub-usuário só de CRM: o DNA é da EMPRESA e não é dele."""
    token = create_access_token(
        {
            "sub": "sub-crm",
            "tenant_id": tenant_id,
            "role": "member",
            "allowed_modules": ["comercial"],
        }
    )
    return {"Authorization": f"Bearer {token}"}


def _do_dna(db: Session) -> list[tuple[str, str]]:
    return [
        (e.action, e.target)
        for e in db.scalars(
            select(AuditEntry).where(AuditEntry.action.like("dna.%"))
        ).all()
    ]


def test_open_grava_o_denominador_que_a_pessoa_VIU(
    client: TestClient, headers: dict[str, str], db: Session
):
    """§3.4 — o progresso é derivado, mas o denominador é GRAVADO.

    `GET /dna/faltantes` devolve só as não respondidas: na segunda visita a pessoa vê 4, não 6, e
    "2 de 6" seria falso sobre o que ela viu. E `catalog.NUCLEO` pode crescer — o eixo de
    Calibração já cresceu de 6 para 7 em 2026-08-09 —, o que viraria todo "k de 6" histórico em
    "k de 7" RETROATIVAMENTE. O número exibido é evidência do que a pessoa viu, no princípio do
    `raw_description` de `bank_transactions`: imutável porque é prova.
    """
    r = client.post("/dna/nucleo/open", json={"exibidas": 4}, headers=headers)
    assert r.status_code == 204
    assert r.content == b""

    assert _do_dna(db) == [("dna.nucleo.open", "4")]


def test_abandon_grava_sem_alvo(client: TestClient, headers: dict[str, str], db: Session):
    r = client.post("/dna/nucleo/abandon", json={}, headers=headers)
    assert r.status_code == 204

    assert _do_dna(db) == [("dna.nucleo.abandon", "")]


def test_evento_fora_da_tupla_nao_existe(client: TestClient, headers: dict[str, str], db: Session):
    """Porta estreita validada contra um conjunto, como `_validar` faz contra o catálogo."""
    r = client.post("/dna/nucleo/desistiu", json={}, headers=headers)
    assert r.status_code == 404
    assert _do_dna(db) == []


def test_open_sem_denominador_e_recusado(
    client: TestClient, headers: dict[str, str], db: Session
):
    """Um `open` sem o número exibido não responde à pergunta que ele existe para responder."""
    assert client.post("/dna/nucleo/open", json={}, headers=headers).status_code == 422
    assert client.post("/dna/nucleo/open", json={"exibidas": 0}, headers=headers).status_code == 422
    assert _do_dna(db) == []


def test_403_do_sub_usuario_nao_produz_evento_nenhum(
    client: TestClient, headers: dict[str, str], headers_sub_crm: dict[str, str], db: Session
):
    """§3.3 — o não-membro, com o membro ao lado.

    Sem o controle positivo abaixo este teste passaria verde se a ROTA INTEIRA sumisse: zero
    eventos é o resultado esperado, e zero eventos também é o resultado de não haver rota.
    """
    r = client.post("/dna/nucleo/open", json={"exibidas": 6}, headers=headers_sub_crm)
    assert r.status_code == 403
    assert _do_dna(db) == []

    # Controle positivo: o MEMBRO, na mesma sessão, produz evento.
    assert client.post(
        "/dna/nucleo/open", json={"exibidas": 6}, headers=headers
    ).status_code == 204
    assert _do_dna(db) == [("dna.nucleo.open", "6")]
```

- [ ] **Step 2: Rode e veja falhar**

```bash
cd /f/Projetos/e1p/escritorio-1-pessoa/.claude/worktrees/vima-v2-medicao/apps/api
$PY -m pytest tests/test_dna_nucleo_eventos.py -q
```

Esperado: **5 failed**. `POST /dna/nucleo/open` cai em `PUT /{key}`? Não — o método é `POST` e
`/{key}` é `PUT`; a resposta será **405** ou **404**. Qualquer uma serve como "a rota não existe".

- [ ] **Step 3: Acrescente o schema** em `apps/api/app/modules/dna/schemas.py`

Depois de `class PularIn`:

```python
class NucleoEventoIn(BaseModel):
    """Corpo de `POST /dna/nucleo/{evento}`.

    `exibidas` é o **denominador VISTO** e só faz sentido no `open` — o `abandon` manda `{}`. Por
    isso o campo é opcional no schema e a obrigatoriedade é decidida por evento no router: um
    `int` obrigatório aqui recusaria o `abandon`, e um default `0` gravaria "vi zero perguntas",
    que é afirmação falsa em vez de campo ausente.
    """

    exibidas: int | None = None
```

- [ ] **Step 4: Acrescente a rota** em `apps/api/app/modules/dna/router.py`

Imports (acrescente ao que já existe):

```python
from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.modules.dna import cadencia, catalog, eventos, service
from app.modules.dna.schemas import NucleoEventoIn, PerguntaOut, PularIn, RespostaIn, to_out
```

Insira o bloco abaixo **antes** de `@router.put("/{key}")`. Ele não colide com `/{key}/pular`
(aquele exige o literal `pular` no 3º segmento), mas rota específica antes de rota curinga é a
ordem que não depende dessa análise continuar verdadeira:

```python
@router.post("/nucleo/{evento}", status_code=204)
def nucleo_evento(
    evento: str,
    corpo: NucleoEventoIn,
    user: CurrentUser = Depends(require_module("settings")),
    db: Session = Depends(get_tenant_db),
) -> Response:
    """O núcleo exibido e o núcleo abandonado — os dois eventos que o servidor não via.

    **UMA rota, com o evento no caminho**, validado contra `eventos.EVENTOS_DO_NUCLEO`: porta
    estreita contra um conjunto, como `service._validar` já faz contra o catálogo.

    ⚠️ **Responde 204 e o front IGNORA a resposta.** Telemetria não pode trancar a entrada do
    produto (§6.2): quem chama dispara e segue. É por isso que não há corpo de resposta a
    desenhar — não existe consumidor para ele.

    ⚠️ **O caminho de erro grava NADA, e é isso que o torna distinguível.** Esta rota exige o
    módulo `settings`; um sub-usuário sem ele toma 403 e não produz evento. Como o front só emite
    `open` DEPOIS de `GET /dna/faltantes` ter sucesso, **ausência de `open` ⇒ a pessoa nunca
    entrou** — verdade derivada, sem inventar um terceiro evento.
    """
    action = eventos.EVENTOS_DO_NUCLEO.get(evento)
    if action is None:
        raise HTTPException(
            status_code=404,
            detail=f"evento '{evento}' não existe; são {sorted(eventos.EVENTOS_DO_NUCLEO)}",
        )

    alvo = ""
    if action == eventos.ACTION_OPEN:
        # O denominador é gravado porque NÃO é derivável: `faltantes` devolve só as não
        # respondidas (na 2ª visita são 4, não 6) e `catalog.NUCLEO` pode crescer.
        if corpo.exibidas is None or corpo.exibidas < 1:
            raise HTTPException(
                status_code=422,
                detail="'exibidas' é obrigatório no open: é a evidência do que a pessoa viu",
            )
        alvo = str(corpo.exibidas)

    eventos.registrar(
        db, tenant_id=user.tenant_id, actor=user.user_id, action=action, target=alvo
    )
    db.commit()
    return Response(status_code=204)
```

- [ ] **Step 5: Rode e veja passar**

```bash
cd /f/Projetos/e1p/escritorio-1-pessoa/.claude/worktrees/vima-v2-medicao/apps/api
$PY -m pytest tests/test_dna_nucleo_eventos.py tests/test_dna_router.py \
  tests/test_dna_vocabulario_gate.py tests/test_fuso_do_tenant.py -q
$PY -m ruff check app tests
```

Esperado: **PASS**. Se o 422 vier como 500, você deixou o `HTTPException` dentro de um `try` que
converte tudo em `DnaError`.

- [ ] **Step 6: Commit**

```bash
cd /f/Projetos/e1p/escritorio-1-pessoa/.claude/worktrees/vima-v2-medicao
git add apps/api/app/modules/dna/router.py apps/api/app/modules/dna/schemas.py \
        apps/api/tests/test_dna_nucleo_eventos.py
git commit -m "feat: o servidor passa a ver o nucleo aberto e o nucleo abandonado [Vima V2]"
```

---

## Task 3: O `NucleoPage` avisa — e a telemetria tem a mesma covardia que ele já tinha

Fecha §6.2 e a metade de frontend do item 3 da Definição de pronto.

**Files:**
- Modify: `apps/web/src/features/dna/NucleoPage.tsx`
- Test: `apps/web/src/features/dna/NucleoPage.test.tsx`

**Interfaces:**
- Consumes: `POST /dna/nucleo/open` com `{exibidas}` e `POST /dna/nucleo/abandon` com `{}` (Task 2).
- Produces: nada que outra tarefa consuma. `CHAVE_NUCLEO` (`"e1p_dna_nucleo"`) **continua sendo a
  autoridade sobre reexibir o núcleo** e **não muda** (§7).

**A regra que decide todo este arquivo:** `sair()` é chamado por **quatro** caminhos e só **um**
deles é abandono.

| Caminho | É abandono? | O que emite |
|---|---|---|
| `catch` do `GET /dna/faltantes` (403 / rede ruim) | **não** — a pessoa nunca entrou | nada |
| `perguntas.length === 0` (não havia o que perguntar) | **não** | nada |
| `avancar()` no fim da sequência (respondeu tudo) | **não** — isso é conclusão | nada |
| botão "Pular por enquanto" | **sim** | `abandon` |

Por isso o beacon **não** entra dentro de `sair()`. Um `abandon` dentro dele reportaria abandono
para quem concluiu o núcleo e para quem tomou 403 — e gravar `abandon` no caminho de erro seria
mentira (§3.3).

---

- [ ] **Step 1: Escreva os testes falhando** (`apps/web/src/features/dna/NucleoPage.test.tsx`)

Substitua o arquivo inteiro por:

```tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import NucleoPage, { CHAVE_NUCLEO } from "./NucleoPage";

// `vi.hoisted` porque a fábrica do `vi.mock` sobe para o topo do arquivo e não enxergaria um
// `const` comum declarado aqui.
const PERGUNTAS = vi.hoisted(() => [
  {
    key: "oferta.o_que_vende",
    classe: "retrato",
    eixo: "oferta",
    texto: "O que você vende?",
    formato: "escolha",
    opcoes: [
      { rotulo: "Serviço por projeto", valor: "servico_projeto" },
      { rotulo: "Produto digital", valor: "produto_digital" },
    ],
  },
  {
    key: "oferta.em_uma_frase",
    classe: "retrato",
    eixo: "oferta",
    texto: "O que você responde?",
    formato: "texto",
    opcoes: [],
  },
]);

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  put: vi.fn(),
  post: vi.fn(),
}));

const navegar = vi.hoisted(() => vi.fn());

vi.mock("../../lib/api", () => ({
  api: apiMock,
  apiErrorMessage: (e: unknown) => String(e),
}));

vi.mock("react-router-dom", async () => {
  const real = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return { ...real, useNavigate: () => navegar };
});

function montar() {
  return render(
    <MemoryRouter>
      <NucleoPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  apiMock.get.mockResolvedValue({ data: PERGUNTAS });
  apiMock.put.mockResolvedValue({ data: {} });
  apiMock.post.mockResolvedValue({ data: {} });
});

describe("NucleoPage", () => {
  it("mostra uma pergunta por vez, com o progresso visível", async () => {
    montar();
    await waitFor(() => expect(screen.getByText("O que você vende?")).toBeInTheDocument());
    expect(screen.queryByText("O que você responde?")).not.toBeInTheDocument();
    expect(screen.getByText("1 de 2")).toBeInTheDocument();
  });

  it("oferece sair da sequência inteira — não é um beco", async () => {
    montar();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /pular por enquanto/i })).toBeInTheDocument(),
    );
  });

  it("avisa que o núcleo abriu, com o denominador que a pessoa VIU", async () => {
    montar();
    await waitFor(() => expect(screen.getByText("O que você vende?")).toBeInTheDocument());

    expect(apiMock.post).toHaveBeenCalledWith("/dna/nucleo/open", { exibidas: 2 });
  });

  it("403 no faltantes NÃO produz evento — a pessoa nunca entrou", async () => {
    apiMock.get.mockRejectedValue(new Error("403"));
    montar();

    await waitFor(() => expect(navegar).toHaveBeenCalledWith("/", { replace: true }));
    expect(apiMock.post).not.toHaveBeenCalled();
  });

  it("núcleo vazio não é abertura nem abandono", async () => {
    apiMock.get.mockResolvedValue({ data: [] });
    montar();

    await waitFor(() => expect(navegar).toHaveBeenCalledWith("/", { replace: true }));
    expect(apiMock.post).not.toHaveBeenCalled();
  });

  it("o beacon de abertura falhando NÃO tranca a entrada", async () => {
    // §6.2: a instrumentação tem de ter a mesma covardia que a página já tinha para o 403.
    apiMock.post.mockRejectedValue(new Error("500"));
    montar();

    await waitFor(() => expect(screen.getByText("O que você vende?")).toBeInTheDocument());
    expect(navegar).not.toHaveBeenCalled();
  });

  it("'Pular por enquanto' avisa o abandono E SAI SEM ESPERAR", async () => {
    // A asserção que mecaniza "a saída NÃO o aguarda": nenhum `await` entre o clique e a
    // verificação. Se alguém escrever `await api.post(...)` antes do `sair()`, a marca do
    // localStorage só existiria num microtask seguinte e esta linha falharia.
    apiMock.post.mockRejectedValue(new Error("500"));
    montar();
    const botao = await screen.findByRole("button", { name: /pular por enquanto/i });

    fireEvent.click(botao);

    expect(localStorage.getItem(CHAVE_NUCLEO)).toBe("1");
    expect(navegar).toHaveBeenCalledWith("/", { replace: true });
    expect(apiMock.post).toHaveBeenCalledWith("/dna/nucleo/abandon", {});
  });

  it("concluir a sequência NÃO é abandono", async () => {
    montar();
    // 1ª pergunta (escolha) → clica numa opção; 2ª é texto → escreve e salva.
    fireEvent.click(await screen.findByRole("button", { name: "Serviço por projeto" }));
    const caixa = await screen.findByPlaceholderText("Escreva do seu jeito");
    fireEvent.change(caixa, { target: { value: "Faço sites" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar" }));

    await waitFor(() => expect(navegar).toHaveBeenCalledWith("/", { replace: true }));
    expect(apiMock.post).not.toHaveBeenCalledWith("/dna/nucleo/abandon", {});
  });
});
```

- [ ] **Step 2: Rode e veja falhar**

```bash
cd /f/Projetos/e1p/escritorio-1-pessoa/.claude/worktrees/vima-v2-medicao
pnpm --filter @e1p/web test -- --run src/features/dna/NucleoPage.test.tsx
```

Esperado: os 2 primeiros passam; **"avisa que o núcleo abriu"** e **"'Pular por enquanto' avisa o
abandono"** falham (`api.post` nunca chamado com `/dna/nucleo/...`). Os de covardia podem passar
por vacuidade neste ponto — é esperado, eles ganham sentido depois do Step 3.

- [ ] **Step 3: Ligue os beacons** em `apps/web/src/features/dna/NucleoPage.tsx`

Acrescente a função `avisar` e o handler `abandonar`, e mude só o `useEffect` e o `onClick` do
botão. **`sair()` não muda.**

```tsx
/**
 * Telemetria: **dispara e esquece.**
 *
 * §6.2 — o beacon NUNCA pode trancar a entrada. Esta página já tinha a covardia certa para o 403
 * e para rede ruim (cai em `sair()`); a instrumentação tem de ter a mesma. Sem `await`, sem
 * `.then` que navegue, e com o `catch` engolindo tudo: uma medição que derruba o produto que ela
 * mede não é medição, é regressão.
 */
function avisar(evento: "open" | "abandon", corpo: Record<string, number> = {}) {
  void api.post(`/dna/nucleo/${evento}`, corpo).catch(() => {
    // De propósito: a medição é secundária ao produto.
  });
}
```

No `useEffect`, dentro do `.then`:

```tsx
      .then(({ data }) => {
        const lista = data ?? [];
        if (!vivo) return;
        setPerguntas(lista);
        // `open` só DEPOIS do sucesso e só quando havia o que ver: é isso que faz "ausência de
        // `open` ⇒ a pessoa nunca entrou" ser verdade, sem inventar um terceiro evento (§3.3).
        // Com a lista vazia a página redireciona sem exibir nada — não houve abertura.
        if (lista.length > 0) avisar("open", { exibidas: lista.length });
      })
```

Acrescente, ao lado de `sair()`:

```tsx
  /**
   * "Pular por enquanto" — o ÚNICO caminho que é abandono.
   *
   * `sair()` também é chamado pelo 403/rede ruim, pelo núcleo vazio e pelo fim da sequência.
   * Nenhum dos três é abandono, e gravar `abandon` no caminho de erro seria mentira — por isso o
   * beacon mora aqui e não lá dentro. A ordem importa menos do que a ausência de `await`: o aviso
   * é disparado e a saída **não o aguarda**.
   */
  function abandonar() {
    avisar("abandon");
    sair();
  }
```

E no botão:

```tsx
      <button
        type="button"
        onClick={abandonar}
        className="w-full text-center text-xs text-neutral-400 underline"
      >
        Pular por enquanto
      </button>
```

- [ ] **Step 4: Rode e veja passar**

```bash
cd /f/Projetos/e1p/escritorio-1-pessoa/.claude/worktrees/vima-v2-medicao
pnpm --filter @e1p/web test -- --run src/features/dna/NucleoPage.test.tsx
pnpm --filter @e1p/web typecheck
```

Esperado: **8 passed**.

- [ ] **Step 5: Rode a suíte de frontend inteira** (o `check.sh` a mascara com `|| true`)

```bash
cd /f/Projetos/e1p/escritorio-1-pessoa/.claude/worktrees/vima-v2-medicao
pnpm --filter @e1p/web test -- --run
```

Esperado: **PASS**. Nenhum outro teste toca `NucleoPage`.

- [ ] **Step 6: Commit**

```bash
cd /f/Projetos/e1p/escritorio-1-pessoa/.claude/worktrees/vima-v2-medicao
git add apps/web/src/features/dna/NucleoPage.tsx apps/web/src/features/dna/NucleoPage.test.tsx
git commit -m "feat: o nucleo avisa que abriu e que foi abandonado, sem nunca trancar a entrada [Vima V2]"
```

---

## Task 4: `app/scripts/nucleo_activation.py` — a leitura é script, não tela

Fecha §4, §6.5, §6.6 e os itens 6 e 7 da Definição de pronto.

**Files:**
- Create: `apps/api/app/scripts/nucleo_activation.py`
- Test: `apps/api/tests/test_nucleo_activation.py` (criar)

**Interfaces:**
- Consumes: `eventos.ACTION_*` e `eventos.PREFIXO` (Task 1); `app.db.session.get_db` /
  `tenant_session`; `app.modules.auth.models.Tenant`; `app.modules.settings.service.tenant_timezone`;
  `app.core.tz.format_datetime_br`.
- Produces (a Task 5 documenta estes nomes):
  - `Passagem` (dataclass frozen): `abertura: datetime` · `exibidas: int` · `respondidas: int` ·
    `puladas: int` · `fim: datetime | None` · `abandonou: bool`
  - `derivar(entradas: Sequence[AuditEntry]) -> list[Passagem]` — **pura**, recebe já ordenado
  - `respostas_por_origem(entradas: Sequence[AuditEntry]) -> dict[str, int]` — **pura**
  - `entradas_do_dna(db: Session) -> list[AuditEntry]`
  - `rodape(passagens: int, tenants: int, abandonos: int) -> str`
  - `main() -> int`

**A decisão de isolamento, e por que ela NÃO é `e1p_root`.** A §4 obrigação 2 exige que a auditoria
não consulte tabela com RLS por uma sessão sem tenant — foi assim que a sondagem de `phone_key`
devolveu `contatos=0` e o silêncio quase virou um "está tudo limpo" falso. **O molde que a própria
§4 nomeia (`app/scripts/investment_audit.py`) satisfaz isso pelo outro mecanismo**, e é o dele que
este script copia: itera a tabela GLOBAL `tenants` (sem RLS) por `get_db()` e abre
`tenant_session(tenant_id)` por tenant — a RLS faz o recorte. Mesmo padrão de
`merge_duplicate_clients` e `migrate_attachments_to_s3`.

⚠️ **Rodar este script sob `e1p_root` seria ATIVAMENTE ERRADO**, e a razão vai escrita no arquivo:
sob um papel que faz bypass, a policy não se aplica, e como as queries do repositório **não
filtram tenant à mão** (Regra de Ouro nº 1) cada tenant reportaria os eventos de todos os outros.
As duas defesas não se somam — escolher uma exclui a outra. Decisão do fundador, 2026-08-11.

---

- [ ] **Step 1: Escreva os testes falhando** (`apps/api/tests/test_nucleo_activation.py`)

```python
"""§6.5 — a derivação do progresso, com controle positivo.

Sem um caso em que `k > 0`, o teste passa verde num script que devolve zero para sempre — a
família do §2 do Epic 8 (o teste que passa e não prova nada), e o mesmo cuidado que
`test_volume_nao_altera_a_divergencia` tomou.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.audit import AuditEntry
from app.scripts import nucleo_activation as na

REGISTER = {
    "legal_name": "Script ME",
    "document": "11444777000161",
    "slug": "scriptme",
    "email": "script@example.com",
    "name": "Flávio",
    "password": "uma-senha-bem-grande",
}


def _e(action: str, target: str, minuto: int) -> AuditEntry:
    """Uma entrada com `created_at` EXPLÍCITO.

    ⚠️ Não semeie pela rota HTTP aqui: `created_at` vem de `server_default=func.now()`, que no
    SQLite tem resolução de SEGUNDO — quatro chamadas no mesmo segundo saem com o mesmo carimbo e
    a ordem passaria a depender do desempate por uuid, que é arbitrário. O teste mediria o acaso.
    """
    return AuditEntry(
        tenant_id="t",
        actor="u",
        action=action,
        target=target,
        created_at=datetime(2026, 8, 11, 12, minuto, tzinfo=UTC),
    )


def test_uma_passagem_completa_com_k_maior_que_zero():
    """O controle positivo: `respondidas` PRECISA ser > 0 em algum caso."""
    passagens = na.derivar(
        [
            _e("dna.nucleo.open", "6", 0),
            _e("dna.answer.save", "nucleo:oferta.o_que_vende", 1),
            _e("dna.answer.save", "nucleo:oferta.em_uma_frase", 2),
            _e("dna.answer.skip", "nucleo:oferta.como_cobra", 3),
            _e("dna.nucleo.abandon", "", 4),
        ]
    )

    assert len(passagens) == 1
    p = passagens[0]
    assert p.exibidas == 6
    assert p.respondidas == 2
    assert p.puladas == 1
    assert p.abandonou is True
    assert p.fim == datetime(2026, 8, 11, 12, 4, tzinfo=UTC)


def test_resposta_de_outra_origem_nao_conta_como_progresso_do_nucleo():
    """É PARA ISSO que o `source` vive no `target`.

    O não-membro: uma pergunta respondida na aba de `/config` no meio de uma passagem do núcleo
    não é progresso do núcleo. Sem o recorte por prefixo, ela seria contada e o denominador
    passaria a mentir.
    """
    [p] = na.derivar(
        [
            _e("dna.nucleo.open", "6", 0),
            _e("dna.answer.save", "config:oferta.ticket_tipico", 1),
            _e("dna.answer.save", "gancho:dinheiro.cobranca_antecedencia_dias", 2),
            _e("dna.answer.save", "nucleo:oferta.o_que_vende", 3),
        ]
    )

    assert p.respondidas == 1
    assert p.abandonou is False
    assert p.fim is None


def test_duas_passagens_do_mesmo_dono_nao_se_misturam():
    """Um dono que abandonou no celular e depois abriu no desktop deixa DOIS `open` (§7)."""
    passagens = na.derivar(
        [
            _e("dna.nucleo.open", "6", 0),
            _e("dna.answer.save", "nucleo:oferta.o_que_vende", 1),
            _e("dna.nucleo.abandon", "", 2),
            _e("dna.nucleo.open", "5", 10),
            _e("dna.answer.save", "nucleo:oferta.em_uma_frase", 11),
        ]
    )

    assert [(p.exibidas, p.respondidas, p.abandonou) for p in passagens] == [
        (6, 1, True),
        (5, 1, False),
    ]


def test_resposta_antes_de_qualquer_open_nao_inventa_passagem():
    """Gancho e `/config` acontecem fora do núcleo o tempo todo, e não são passagem nenhuma."""
    assert na.derivar([_e("dna.answer.save", "gancho:oferta.como_cobra", 0)]) == []


def test_respostas_por_origem_separa_as_tres_portas():
    """A evidência sobre a quarentena de 7 dias e o "uma por dia" (a meia dívida da §0.1)."""
    contagem = na.respostas_por_origem(
        [
            _e("dna.nucleo.open", "6", 0),
            _e("dna.answer.save", "nucleo:a", 1),
            _e("dna.answer.skip", "gancho:b", 2),
            _e("dna.answer.save", "config:c", 3),
            _e("dna.answer.save", "config:d", 4),
        ]
    )

    assert contagem == {"nucleo": 1, "gancho": 1, "config": 2}


def test_o_rodape_diz_QUANTOS_TENANTS_foram_varridos():
    """A lição literal do `investment_audit.py`.

    `0 em 0 tenants` e `0 em 7 tenants` são resultados DIFERENTES, e o primeiro é defeito do
    próprio script. Um rodapé que não carrega o denominador não distingue os dois.
    """
    vazio = na.rodape(passagens=0, tenants=0, abandonos=0)
    povoado = na.rodape(passagens=0, tenants=7, abandonos=0)

    assert vazio != povoado
    assert "0 tenant" in vazio
    assert "7 tenant" in povoado


def test_entradas_do_dna_le_so_o_que_e_do_dna(client: TestClient, db: Session):
    """A query real, contra o banco de teste — e o não-membro ao lado."""
    headers = {
        "Authorization": "Bearer "
        + client.post("/auth/register", json=REGISTER).json()["access_token"]
    }
    client.post("/dna/nucleo/open", json={"exibidas": 6}, headers=headers)
    client.put(
        "/dna/oferta.ticket_tipico", json={"valor": "2k_10k", "source": "nucleo"}, headers=headers
    )
    # O não-membro: uma action de OUTRO módulo, na mesma tabela, não pode entrar na leitura.
    db.add(AuditEntry(tenant_id="t", actor="u", action="bank.account.create", target="xyz"))
    db.commit()

    acoes = [e.action for e in na.entradas_do_dna(db)]

    assert acoes == ["dna.nucleo.open", "dna.answer.save"]
```

- [ ] **Step 2: Rode e veja falhar**

```bash
cd /f/Projetos/e1p/escritorio-1-pessoa/.claude/worktrees/vima-v2-medicao/apps/api
$PY -m pytest tests/test_nucleo_activation.py -q
```

Esperado: erro de coleção — `ModuleNotFoundError: app.scripts.nucleo_activation`.

- [ ] **Step 3: Escreva `apps/api/app/scripts/nucleo_activation.py`**

```python
"""Lê o rastro de ativação do núcleo do DNA: quem abriu, quanto respondeu, quem abandonou.

    docker compose exec api python -m app.scripts.nucleo_activation

**Não existe `--fix`, e a ausência é a decisão** — a mesma de `investment_audit.py`: com uma flag
de correção, alguém a roda no deploy sem ler a saída. Aqui não haveria sequer o que corrigir: o
rastro é evidência, e "corrigir" evidência é reescrever história.

**Instrumentar, não analisar.** Este script não decide nada, não tem limiar e não diz quantos
tenants bastam. A §5 da spec recusou escrever um "leia quando houver 20 tenants" porque seria
número sem evidência (Artigo IV) — a decisão de ler é do fundador. Enquanto a contagem for 2, a
resposta à pergunta da dívida ("o núcleo ajudou ou atrapalhou?") vem de conversar com as duas
pessoas reais; o rastro existe para o dia em que isso deixar de ser verdade.

⚠️ **Isolamento — e por que este script NÃO roda sob `e1p_root`.** Ele itera a tabela GLOBAL
`tenants` (sem RLS) e abre `tenant_session` por tenant, exatamente como `investment_audit.py`,
`merge_duplicate_clients` e `migrate_attachments_to_s3`. O perigo que a §4 nomeia é real e é
outro: uma consulta a tabela com RLS por uma sessão **sem** tenant devolve zero linhas **sem
erro** — foi assim que a sondagem de `phone_key` em produção quase virou um "está tudo limpo"
falso. As duas saídas para isso são o papel que faz bypass **ou** a GUC fixada por tenant, e elas
se EXCLUEM: sob `e1p_root` a policy não se aplica, e como nenhuma query deste repositório filtra
tenant à mão (Regra de Ouro nº 1) cada tenant reportaria os eventos de todos os outros. Se algum
dia este script precisar do papel de bypass, ele precisa ganhar `WHERE tenant_id` explícito no
mesmo commit.

Por isso a saída imprime **quantos tenants foram varridos**: `0 passagens em 0 tenants` e
`0 passagens em 7 tenants` são resultados diferentes, e o primeiro é um defeito deste script, não
um produto que ninguém usou.

⚠️ **Fuso:** todo horário sai por `format_datetime_br` no fuso do tenant. Um `open` às 22h em
UTC−3 é 01h do dia seguinte em UTC, e um relatório de ativação que trocasse o dia estaria medindo
outra coisa (§6.6).
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import AuditEntry
from app.core.tz import format_datetime_br
from app.db.session import get_db, tenant_session
from app.modules.auth.models import Tenant
from app.modules.dna import eventos
from app.modules.settings.service import tenant_timezone

logger = logging.getLogger("e1p.nucleo_activation")


@dataclass(frozen=True)
class Passagem:
    """Uma passagem pelo núcleo: de um `open` até o `abandon` (ou até o fim do rastro).

    `exibidas` é o denominador VISTO, lido do `target` do `open` — não é `len(catalog.NUCLEO)`.
    `faltantes` devolve só as não respondidas, então na segunda visita a pessoa vê 4 e não 6; e
    `catalog.NUCLEO` pode crescer, o que viraria todo "k de 6" histórico em "k de 7"
    retroativamente. O progresso (`respondidas`/`puladas`) é DERIVADO dos eventos, e nada de
    derivado é guardado — mesmo princípio de `last_interaction_at` nunca ser coluna.
    """

    abertura: datetime
    exibidas: int
    respondidas: int = 0
    puladas: int = 0
    fim: datetime | None = None

    @property
    def abandonou(self) -> bool:
        return self.fim is not None


def entradas_do_dna(db: Session) -> list[AuditEntry]:
    """Toda a trilha do DNA do tenant da sessão, em ordem.

    ⚠️ O desempate por `id` entrega **estabilidade**, não cronologia: `created_at` tem
    `server_default=func.now()`, que no Postgres é o timestamp da TRANSAÇÃO. Cada evento do DNA
    nasce numa request própria, então na prática os carimbos são distintos — mas dentro do mesmo
    instante não existe "mais novo", e uma ordem arbitrária que MUDA entre duas chamadas idênticas
    seria pior (a lição do histórico de saques da Onda 3).
    """
    return list(
        db.scalars(
            select(AuditEntry)
            .where(AuditEntry.action.startswith(eventos.PREFIXO))
            .order_by(AuditEntry.created_at, AuditEntry.id)
        ).all()
    )


def _origem(entrada: AuditEntry) -> str:
    """A porta de entrada da resposta, lida do `target` (`<source>:<pergunta>`)."""
    return entrada.target.split(":", 1)[0]


def derivar(entradas: Sequence[AuditEntry]) -> list[Passagem]:
    """As passagens pelo núcleo. **Pura** — recebe já ordenado, não lê banco nem relógio.

    Resposta fora de uma passagem aberta é ignorada de propósito: gancho e `/config` acontecem o
    tempo todo, e contá-los inventaria passagem onde não houve abertura. É esse recorte que faz o
    `source` no `target` pagar a conta.
    """
    passagens: list[Passagem] = []
    aberta: Passagem | None = None

    for e in entradas:
        if e.action == eventos.ACTION_OPEN:
            if aberta is not None:
                passagens.append(aberta)
            aberta = Passagem(
                abertura=e.created_at, exibidas=int(e.target) if e.target.isdigit() else 0
            )
        elif e.action == eventos.ACTION_ABANDON:
            if aberta is not None:
                passagens.append(_com(aberta, fim=e.created_at))
                aberta = None
        elif aberta is not None and _origem(e) == "nucleo":
            if e.action == eventos.ACTION_SAVE:
                aberta = _com(aberta, respondidas=aberta.respondidas + 1)
            elif e.action == eventos.ACTION_SKIP:
                aberta = _com(aberta, puladas=aberta.puladas + 1)

    if aberta is not None:
        passagens.append(aberta)
    return passagens


def _com(p: Passagem, **campos) -> Passagem:
    """`Passagem` é frozen de propósito: a evidência não é editada no meio da varredura."""
    return Passagem(
        abertura=campos.get("abertura", p.abertura),
        exibidas=campos.get("exibidas", p.exibidas),
        respondidas=campos.get("respondidas", p.respondidas),
        puladas=campos.get("puladas", p.puladas),
        fim=campos.get("fim", p.fim),
    )


def respostas_por_origem(entradas: Sequence[AuditEntry]) -> dict[str, int]:
    """Quantas respostas vieram de cada porta. **Pura.**

    A instrumentação NÃO é escopada só ao núcleo, e é isso que produz evidência sobre a quarentena
    de 7 dias e o "uma por dia" — a meia dívida da §0.1. Sai de graça: `responder`/`pular` já
    recebiam `source`.
    """
    contagem: dict[str, int] = {}
    for e in entradas:
        if e.action in (eventos.ACTION_SAVE, eventos.ACTION_SKIP):
            origem = _origem(e)
            contagem[origem] = contagem.get(origem, 0) + 1
    return contagem


def rodape(*, passagens: int, tenants: int, abandonos: int) -> str:
    return (
        f"{passagens} passagem(ns) pelo núcleo em {tenants} tenant(s); "
        f"{abandonos} abandonada(s)."
    )


def _tenants() -> list[tuple[str, str]]:
    """`(id, slug)` de todos os tenants. `tenants` é GLOBAL e não tem RLS."""
    gen = get_db()
    db = next(gen)
    try:
        return [(t.id, t.slug) for t in db.scalars(select(Tenant)).all()]
    finally:
        gen.close()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logger.info("=== Ativação do núcleo do DNA (Vima V2) — SÓ LEITURA ===")

    tenants = _tenants()
    total = abandonos = 0
    for tenant_id, slug in tenants:
        with tenant_session(tenant_id) as db:
            entradas = entradas_do_dna(db)
            if not entradas:
                continue
            fuso = tenant_timezone(db)
            passagens = derivar(entradas)
            total += len(passagens)
            abandonos += sum(1 for p in passagens if p.abandonou)

            logger.info("")
            logger.info("  %s (tenant %s) — fuso %s", slug, tenant_id, fuso)
            for n, p in enumerate(passagens, start=1):
                fim = format_datetime_br(p.fim, fuso) if p.fim else "sem abandono registrado"
                logger.info(
                    "    passagem %d: abriu %s com %d pergunta(s) à vista",
                    n,
                    format_datetime_br(p.abertura, fuso),
                    p.exibidas,
                )
                logger.info(
                    "      respondidas %d · puladas %d · %s", p.respondidas, p.puladas, fim
                )
            origens = respostas_por_origem(entradas)
            if origens:
                logger.info(
                    "    respostas por origem: %s",
                    " · ".join(f"{k} {v}" for k, v in sorted(origens.items())),
                )

    logger.info("")
    logger.info(rodape(passagens=total, tenants=len(tenants), abandonos=abandonos))
    if not tenants:
        logger.warning(
            "NENHUM tenant varrido — isto é um defeito deste script, não um produto sem uso."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Rode e veja passar**

```bash
cd /f/Projetos/e1p/escritorio-1-pessoa/.claude/worktrees/vima-v2-medicao/apps/api
$PY -m pytest tests/test_nucleo_activation.py -q
$PY -m ruff check app tests
```

Esperado: **7 passed**. Se `test_entradas_do_dna_le_so_o_que_e_do_dna` falhar com `bank.account.create`
na lista, o `startswith` foi trocado por `like("%dna%")` em algum momento — volte ao prefixo.

- [ ] **Step 5: Rode a suíte de backend INTEIRA, e depois com `TZ=UTC`**

```bash
cd /f/Projetos/e1p/escritorio-1-pessoa/.claude/worktrees/vima-v2-medicao/apps/api
$PY -m pytest -q
TZ=UTC $PY -m pytest -q
```

Esperado: **PASS** nas duas. Se quebrar só na segunda, é a classe reincidente do fuso — o defeito
está no teste novo, não no diff de outra pessoa.

- [ ] **Step 6: Commit**

```bash
cd /f/Projetos/e1p/escritorio-1-pessoa/.claude/worktrees/vima-v2-medicao
git add apps/api/app/scripts/nucleo_activation.py apps/api/tests/test_nucleo_activation.py
git commit -m "feat: script que le a ativacao do nucleo — sem --fix, e dizendo quantos tenants varreu [Vima V2]"
```

---

## Task 5: A entrada no `CLAUDE.md`

Fecha o item 9 da Definição de pronto. **É AC obrigatório** (`CLAUDE.md` §5, passo 4): a tarefa não
está concluída sem ele. Escrito a partir do **código que subiu**, não do que a spec pretendia — se
algo saiu diferente nas Tasks 1-4, é o código que manda.

**Files:**
- Modify: `CLAUDE.md` — inserir uma subseção **dentro** de `## Vima V2: o DNA da Empresa
  (2026-08-08)`, logo **depois** da subseção `### A cobrança ganhou antecedência...` e **antes** de
  `## 6.0 Correções importantes`.

---

- [ ] **Step 1: Feche a dívida no lugar onde ela está escrita**

Em `CLAUDE.md`, na linha que hoje diz:

```markdown
- **Dívidas:** as 46 perguntas nunca foram validadas com dono real; não há medição de ativação do
  núcleo, então não se sabe se ele ajudou ou atrapalhou; a quarentena de 7 dias e o "uma por dia"
  são números sem evidência.
```

troque por:

```markdown
- **Dívidas:** as 46 perguntas nunca foram validadas com dono real (**não é instrumentável — é
  conversa com dono**); ~~não há medição de ativação do núcleo~~ **FECHADA em 2026-08-11**, ver "A
  ativação do núcleo deixou de ser invisível" abaixo; a quarentena de 7 dias e o "uma por dia"
  continuam sendo números sem evidência, mas **agora existe evidência sendo acumulada** — ler 2
  tenants não confirma número nenhum.
```

> Dívida resolvida e ainda escrita manda o próximo leitor resolver de novo o que já está resolvido
> (`CLAUDE.md` §5, passo 4). Mas fechar as três de uma vez seria mentira: a spec §0.1 fecha **uma
> e meia** de três.

- [ ] **Step 2: Escreva a subseção**

```markdown
### A ativação do núcleo deixou de ser invisível (2026-08-11)

> Spec: `docs/superpowers/specs/2026-08-11-vima-v2-medicao-de-ativacao-design.md` ·
> Plano: `docs/superpowers/plans/2026-08-11-vima-v2-medicao-de-ativacao.md`

A dívida escrita dizia *"não há medição de ativação do núcleo"*. Verificado no código, o estado era
**pior**, e em dois pontos era **destruição de dado acontecendo agora**. Esta onda é
**instrumentar, não analisar**: nenhuma tela, nenhum endpoint de leitura, nenhum limiar, nenhuma
migration.

- [x] **A docstring de `dna/models.py` parou de ser falsa.** Ela defendia o upsert dizendo que *"o
  histórico de quem mudou o quê já é trabalho de `core/audit.py`"* — e `audit` aparecia **UMA** vez
  no módulo inteiro, **dentro dessa frase**, com zero chamadas. É a classe de defeito nº 1 do Epic
  8 (o documento que afirma sobre a camada de baixo e desliga quem viria conferir), e aqui mais
  grave que nas quatro instâncias de lá porque **sustentava uma decisão de modelagem**: o upsert foi
  aceito em troca de uma rede que ninguém tinha tecido. A escolha foi **tecer a rede**, não corrigir
  a frase para menos.
- [x] **Quatro `action`s, e o `source` mora no `target`.** `dna.answer.save` · `dna.answer.skip` ·
  `dna.nucleo.open` · `dna.nucleo.abandon`, com `target=<source>:<pergunta>` nas duas primeiras e
  `str(n)` no `open`. ⚠️ **Quatro actions × três sources (`nucleo｜gancho｜config`) seriam DOZE
  strings**, e é assim que 117 actions distintas viram 200 — o repo já tem `account_deleted`, sem
  pontos e fora do padrão, provando que a convenção sozinha não segura o vocabulário.
- [x] **`dna/eventos.py` é a porta única, com guarda mecânica.** `facts.record` valida o `kind`
  contra o `module`; `audit.record` **não valida nada**. `eventos.registrar` recusa toda action
  fora de `ACTIONS`, e um gate AST (`test_dna_vocabulario_gate.py`) garante que ninguém mais no
  módulo chama `audit.record` — allowlist de **um** membro, no padrão de `sync_origin_movement`.
  **Com controle positivo em cada asserção**, inclusive um do próprio scanner: sem ele, um glob que
  deixasse de casar aprovaria o módulo inteiro em silêncio.
- [x] **O teste que prova a dívida fechada:** responder `oferta.ticket_tipico` no núcleo, editar a
  mesma pergunta no `/config`, e asserir **duas** entradas de audit com **uma** linha em
  `dna_answers`. É a diferença entre o upsert apagar história e o upsert ser só estado atual.
- ⚠️ **`db.flush()` antes de gravar a trilha, e a razão NÃO é a do MNT-001.** O padrão do repo
  (`bank.create_account`) existe porque o `target` costuma ser o `id`, que tem default Python-side
  e é `None` antes do INSERT. Aqui o `target` é `<source>:<pergunta>` e **não depende de `id`
  nenhum** — o flush fica pelo segundo motivo que `bank.create_transaction` documenta: é nele que a
  unique constraint de `(tenant, question_key)` fala, e um rastro escrito antes dela afirmaria uma
  resposta que ainda pode ser recusada. **Escrever aqui a justificativa do MNT-001 seria repetir a
  classe de defeito que esta própria onda veio fechar.** Os outros 17 call sites continuam abertos.
- [x] **`POST /dna/nucleo/{evento}` — UMA rota, evento no caminho**, validado contra tupla
  declarada, 204, e **o front ignora a resposta**.
- ⚠️ **O caminho de erro grava NADA, e é isso que o torna distinguível.** `open` é emitido só
  **depois** de `GET /dna/faltantes` ter sucesso **e só quando havia pergunta para ver** — então
  **ausência de `open` ⇒ a pessoa nunca entrou**, verdade derivada sem inventar um terceiro evento.
  Um sub-usuário sem o módulo `settings` toma 403 e **não é contado como abandono**.
- ⚠️ **`sair()` do `NucleoPage` tem QUATRO chamadores e só UM é abandono.** 403/rede ruim, núcleo
  vazio e fim da sequência **não são** abandono; só o botão "Pular por enquanto" é. Por isso o
  beacon **não** entrou dentro de `sair()` — lá dentro ele reportaria abandono para quem concluiu o
  núcleo, e gravar `abandon` no caminho de erro seria mentira.
- ⚠️ **A covardia da telemetria é MECANIZADA, não prometida.** O teste clica em "Pular por
  enquanto" com o `POST` rejeitando e verifica `localStorage` e navegação **sem nenhum `await` entre
  o clique e a asserção**: se alguém escrever `await api.post(...)` antes do `sair()`, a marca só
  existiria num microtask seguinte e o teste morre. É a forma executável de *"o abandon é disparado
  e a saída não o aguarda"*.
- [x] **O denominador é GRAVADO; o progresso é DERIVADO.** `faltantes` devolve só as não
  respondidas (na 2ª visita a pessoa vê 4, não 6), e `catalog.NUCLEO` pode crescer — o eixo de
  Calibração já cresceu de 6 para 7 em 2026-08-09 —, o que viraria todo "k de 6" histórico em "k de
  7" **retroativamente**. O número exibido é evidência do que a pessoa viu, no princípio do
  `raw_description` de `bank_transactions`.
- [x] **`python -m app.scripts.nucleo_activation` — sem `--fix`, imprimindo quantos tenants
  varreu.** `0 passagens em 0 tenants` e `0 em 7` são resultados diferentes, e o primeiro é defeito
  do script.
  - ⚠️ **Ele NÃO roda sob `e1p_root`, e a spec pedia isso.** O perigo que ela nomeia é real (uma
    consulta a tabela com RLS por sessão **sem** tenant devolve zero linhas sem erro — a sondagem
    de `phone_key`), mas as duas saídas se **excluem**: sob um papel que faz bypass a policy não se
    aplica, e como nenhuma query deste repositório filtra tenant à mão (Regra de Ouro nº 1), cada
    tenant reportaria os eventos de **todos os outros**. O script segue o molde que a própria spec
    nomeia (`investment_audit.py`): itera a tabela global `tenants` e abre `tenant_session` por
    tenant. **Regra que fica: "rode sob o papel de bypass" e "abra sessão por tenant" são duas
    respostas à mesma armadilha, e escolher uma proíbe a outra — quem migrar este script para
    `e1p_root` precisa acrescentar `WHERE tenant_id` no mesmo commit.**
- [x] **A instrumentação NÃO é escopada ao núcleo, e isso saiu de graça.** `responder`/`pular` já
  recebiam `source`, então a mesma chamada cobre `gancho` e `config` — é essa contagem por origem
  que vira a evidência sobre a quarentena de 7 dias e o "uma por dia" (a meia dívida acima).
- **Consequência aceita: a marca `localStorage` (`e1p_dna_nucleo`) CONTINUA sendo a autoridade
  sobre reexibir o núcleo.** Movê-la para o servidor seria mudança de comportamento embutida numa
  onda de medição, e misturar as duas tira do gate a capacidade de julgar o que quebrou o quê
  (o argumento que manteve SIG-001 fora da 8.16 e separou 8.19 de 8.20). Um dono que abandonou no
  celular e abriu no desktop **verá o núcleo de novo**, e o rastro mostrará **dois `open`** — isso é
  verdade sobre aparelhos, e o script não os reporta como duas passagens do mesmo dono.
- **LGPD:** `audit_entries` é purgado com o tenant pelo `delete_account` (descoberta dinâmica de
  subclasses de `TenantMixin`). Tenant que sai leva a ativação dele, e é o comportamento correto;
  `platform_audit_entries` **não** é usada aqui — aquela existe para operação destrutiva do Master,
  não para telemetria de produto.
- **A população é 2, e é ela que decidiu o desenho.** Os tenants reais que passarão pelo núcleo nos
  próximos ~3 meses são **dois** (o fundador e o sócio — a produção foi zerada em 05/08 para o sócio
  começar do zero). Funil com N=2 é ilusão estatística: *1 de 2 pulando o núcleo* é "50% de
  abandono" e **não significa nada**. O que justifica esta onda **não é estatística, é
  irreconstrutibilidade** — o mesmo argumento do `ai_usage` (*"o consumo passado não foi guardado
  por ninguém e não tem como ser reconstruído"*). **Enquanto forem 2, a resposta à pergunta da
  dívida vem de conversar com as duas pessoas.**
- **Dívida:** `audit_entries` cresce — quatro eventos por tenant por passagem, mais um por resposta
  de gancho. Dezenas por tenant por ano; irrelevante hoje, anotado para não ser descoberto como
  surpresa.
- **Dívida:** o script não tem teste `rls_e2e` (o `investment_audit.py` tem). A leitura por tenant é
  coberta contra o SQLite dos testes, e o isolamento real depende do mesmo `tenant_session` que os
  outros três scripts já usam em produção.
- **Dívida (a que NÃO fecha):** as 46 perguntas seguem nunca validadas com dono real. Não é
  instrumentável; é conversa com dono.
```

- [ ] **Step 3: Confira que a entrada descreve o código que subiu**

```bash
cd /f/Projetos/e1p/escritorio-1-pessoa/.claude/worktrees/vima-v2-medicao
git diff origin/main --stat
grep -rn "eventos.registrar" apps/api/app/modules/dna/   # a lista de consumidores da docstring
```

Cada `[x]` da entrada precisa ter linha no diff. Cada `grep` citado numa docstring precisa
devolver o que ela promete — **é a regra do item 12 do WhatsApp**, e ela vale para o texto que você
acabou de escrever.

- [ ] **Step 4: A suíte inteira, uma última vez**

```bash
PY=/f/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe
cd /f/Projetos/e1p/escritorio-1-pessoa/.claude/worktrees/vima-v2-medicao/apps/api
$PY -m pytest -q && TZ=UTC $PY -m pytest -q && $PY -m ruff check app tests
cd /f/Projetos/e1p/escritorio-1-pessoa/.claude/worktrees/vima-v2-medicao
pnpm --filter @e1p/web test -- --run && pnpm --filter @e1p/web typecheck
```

- [ ] **Step 5: Commit**

```bash
cd /f/Projetos/e1p/escritorio-1-pessoa/.claude/worktrees/vima-v2-medicao
git add CLAUDE.md
git commit -m "docs: registra a medicao de ativacao do nucleo, escrita do codigo que subiu [Vima V2]"
```

- [ ] **Step 6: Delegue o push e o PR ao @devops**

`main` é protegida (`GH006`) e `git push` / `gh pr create` são **exclusivos do @devops**. **Não
execute.** Peça a abertura do PR de `feat/vima-v2-medicao-ativacao` para `main`, com os 4 checks
obrigatórios.

---

## O que este plano NÃO faz

Escrito para que ninguém "complete" a onda ampliando-a:

- **Nenhuma tela, nenhum dashboard, nenhum endpoint de leitura.** A leitura é o script da Task 4.
- **Nenhum limiar** de "quantos tenants bastam" — seria número sem evidência (Artigo IV), o mesmo
  motivo pelo qual o V2 recusou inventar a 8ª pergunta de Calibração.
- **Nenhuma migration.**
- **Nenhuma medição de tempo-em-tela nem latência por pergunta** — exigiria telemetria de interação,
  e a pergunta da dívida não precisa dela.
- **Nenhuma agregação cross-tenant** — com N=2, agregar é aritmética sobre ruído.
- **A autoridade do `localStorage` não se move para o servidor** (§7).
- **Onda 4 (import OFX) não é isto.** A spec dela existe (PRs #107/#108) e **o gate não abriu**:
  precisa de um ciclo real, e nenhum ciclo anterior a `PRIMEIRO_CICLO_MEDIVEL` (2026-09-01) serve.
- **Vima V3 (Memória Empresarial) não é isto.** Desbloqueada, adiada nesta rodada.

---

## Self-review (feita contra a spec, 2026-08-11)

**Cobertura da spec** — cada seção tem tarefa:

| Spec | Onde |
|---|---|
| §2.1 upsert apaga a evidência | Task 1, Step 5 (`test_editar_no_config_...`) |
| §2.2 docstring aponta para rede inexistente | Task 1, Step 9 |
| §2.3 abandono não deixa rastro | Task 2 + Task 3 |
| §3.1 `audit_entries` (zero migration) | Global Constraints + Task 1 |
| §3.2 vocabulário; `source` no `target` | Task 1, Steps 1-4 |
| §3.3 caminho de erro grava nada | Task 2 Step 1 + Task 3 Step 1 |
| §3.4 denominador gravado, progresso derivado | Task 2 Step 4 + Task 4 (`Passagem`) |
| §4 script sem `--fix`, conta tenants, isolamento | Task 4 |
| §5 gatilho é contador, não data (nenhum limiar) | "O que este plano NÃO faz" |
| §6.1 `flush` antes de gravar | Task 1 Step 7 |
| §6.2 o beacon nunca tranca a porta | Task 3 |
| §6.3 gate de vocabulário com controle positivo | Task 1 Steps 1-4 |
| §6.4 duas entradas, uma linha | Task 1 Step 5 |
| §6.5 derivação com controle positivo | Task 4 Step 1 |
| §6.6 fuso | Global Constraints + Task 4 (`format_datetime_br`) |
| §7 consequências aceitas | Task 5 (entrada) |
| §9 DoD 1-9 | 1→T1 · 2→T2/T3 · 3→T2/T3 · 4→T1 · 5→T1 · 6→T4 · 7→T4 · 8→T1 · 9→T5 |

**Consistência de tipos** — os nomes atravessam tarefas sem divergir: `eventos.ACTION_OPEN`
(T1→T2→T4), `eventos.EVENTOS_DO_NUCLEO` (T1→T2), `eventos.alvo_da_resposta` (T1→T4 via `_origem`),
o contrato HTTP `{exibidas}` (T2→T3), `CHAVE_NUCLEO` (T3, inalterado).

**Dois desvios da spec, ambos deliberados e escritos:**

1. **§6.1 — a justificativa do `flush`.** A spec diz que sem ele *"o `target` nasce vazio: o `id`
   tem default Python-side"*. Isso é verdade dos 17 call sites do MNT-001 e **falso neste**: o
   `target` aqui é `<source>:<pergunta>` e não toca em `id` nenhum. O `flush` **fica** (a spec o
   exige, e há razão real — a unique constraint fala nele), mas o comentário no código diz a razão
   **verdadeira**. Copiar a justificativa errada seria cometer, dentro desta onda, a classe de
   defeito que ela veio fechar.
2. **§4/DoD 6 — `e1p_root`.** Resolvido pelo molde que a própria §4 nomeia
   (`tenant_session` por tenant, sob `e1p_app`), porque sob bypass as queries do repo — que não
   filtram tenant à mão — cruzariam tenants. Decisão do fundador, 2026-08-11. Registrada na Task 4 e
   na entrada do `CLAUDE.md`.
