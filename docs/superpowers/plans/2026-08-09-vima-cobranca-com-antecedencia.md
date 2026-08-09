# Vima — antecedência da cobrança e o conserto da regra do silêncio · Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer a cobrança a receber avisar antes de vencer, e fazer a regra do silêncio do briefing valer de verdade — hoje ela cala por exatamente um dia e volta.

**Architecture:** Duas mudanças acopladas em `app/modules/vima/`. (1) A escalada do silêncio troca `anterior * 2` por `_proximo_marco(anterior)`, uma função que atravessa o zero — o ramo positivo é a expressão de hoje, intacta. (2) O mapa gravado no payload deixa de ser "o que eu disse" e passa a ser "em que ponto cada ausência viva parou", carregando também as caladas e as cortadas pelo teto. Em cima disso, `_dinheiro_com_data` ganha antecedência para `Charge` e o catálogo do DNA ganha a 7ª pergunta de Calibração.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2, pytest. Sem migration. Sem frontend. Sem IA.

> **Spec:** `docs/superpowers/specs/2026-08-09-vima-cobranca-com-antecedencia-design.md`

## Global Constraints

- **Idioma:** nomes de domínio, docstrings e comentários em **PT-BR**; identificadores de código em inglês. Convenção do repositório (CLAUDE.md §8).
- **Sem migration.** `dna_answers` é chave/valor e o catálogo é código. Se você se pegar escrevendo um arquivo em `apps/api/migrations/versions/`, pare — o plano está sendo mal executado.
- **`absences.py` e `resolver.py` são módulos PUROS:** não leem relógio, nem para carimbar instante. `hoje` entra por parâmetro. O gate `tests/test_fuso_do_tenant.py` reprova violação por varredura AST.
- **Antecedência padrão da cobrança: `3` dias.** Decidido pelo dono do produto. Não é derivado de outro número.
- **Os três comandos, sempre, antes de declarar qualquer tarefa concluída:**
  - `cd apps/api && ../../.venv/Scripts/python.exe -m ruff check .` *(veja "Ambiente" abaixo para o caminho real do interpretador)*
  - `cd apps/api && <python> -m pytest`
  - `pnpm --filter @e1p/web test`
- **Commits:** Conventional Commits em PT-BR, com `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>` na última linha.
- **`git push` e `gh pr create` são exclusivos do @devops.** Não execute nenhum dos dois.

## Ambiente

O trabalho acontece no worktree **já criado** em `.claude/worktrees/vima-cobranca-antecedencia`, branch `feat/vima-cobranca-com-antecedencia`, nascida de `origin/main` (`a6e7e9a`). O spec já está commitado nela (`59e05cc`).

O worktree **não herda toolchain**. Antes da Tarefa 1:

```bash
cd .claude/worktrees/vima-cobranca-antecedencia
pnpm install
```

Python usa o venv do checkout principal apontando para o código do worktree. A partir de
`.claude/worktrees/vima-cobranca-antecedencia/apps/api`, o interpretador é:

```
../../../../apps/api/.venv/Scripts/python.exe
```

Confirme uma vez, antes de começar, que ele existe e roda a suíte:

```bash
cd apps/api && ../../../../apps/api/.venv/Scripts/python.exe -m pytest -q 2>&1 | tail -5
```

Nos comandos das tarefas abaixo, `<python>` significa esse caminho. Se ele não existir, pare e
peça orientação — **não** crie um venv novo no worktree.

---

### Task 1: A prova do defeito — o teste de três dias que precisa FALHAR

**Files:**
- Create: `apps/api/tests/test_vima_regra_do_silencio.py`

**Interfaces:**
- Consumes: `absences.coletar(db, *, user, hoje, limiares=None, ja_reportadas=None, agora=None) -> list[Ausencia]` e `composer.compor(*, fatos, ausencias, tendencias, valores, teto=12, referencia=None, desde=None) -> Payload` — as assinaturas **de hoje**, que as Tarefas 3 e 4 vão mudar.
- Produces: o helper `_um_dia(db, user, *, hoje, marcos) -> tuple[bool, dict[str, int]]`. **É o único ponto do arquivo que conhece as assinaturas** — as Tarefas 3 e 4 editam só ele, nunca as asserções.

⚠️ **Esta tarefa termina com um teste VERMELHO commitado, de propósito.** É o gate de abertura do spec: se o teste passar de primeira, a leitura de código que motivou o trabalho estava errada e **o design inteiro volta para a mesa**. Nesse caso, pare, não implemente nada, e reporte.

- [ ] **Step 1: Escrever o teste que falha**

Crie `apps/api/tests/test_vima_regra_do_silencio.py` com exatamente:

```python
"""A regra do silêncio ao longo de VÁRIOS dias — que é onde ela quebra.

`test_vima_absences.py` cobre as duas transições de UM dia e passa. A sequência de três dias é
a menor que exercita o encadeamento real do produto: o mapa gravado num dia é a entrada do dia
seguinte. É aí que a ausência calada some do registro e volta a falar no dia seguinte, porque
"sem valor anterior" e "nunca falei disto" são indistinguíveis.
"""
from datetime import UTC, date, datetime

import pytest
from sqlalchemy.orm import Session

from app.core.tenancy import CurrentUser
from app.modules.crm.models import Client, PipelineStage
from app.modules.vima import composer
from app.modules.vima.absences import coletar

TENANT = "t1"
KIND_CARD = "comercial.card.parado"
CHAVE_CARD = f"{KIND_CARD}:c1"


@pytest.fixture()
def usuario_owner() -> CurrentUser:
    return CurrentUser(
        user_id="u1", tenant_id=TENANT, role="owner",
        allowed_modules=[], is_platform_admin=False,
    )


@pytest.fixture()
def card_parado(db: Session) -> Client:
    """Entrou na etapa em 25/07: 12 dias em 06/08, 13 em 07/08, 14 em 08/08."""
    etapa = PipelineStage(tenant_id=TENANT, name="Em contato", position=1)
    db.add(etapa)
    db.flush()
    card = Client(
        id="c1", tenant_id=TENANT, name="Carlos", stage_id=etapa.id,
        stage_entered_at=datetime(2026, 7, 25, 12, 0, tzinfo=UTC),
    )
    db.add(card)
    db.commit()
    return card


def _um_dia(
    db: Session, user: CurrentUser, *, hoje: date, marcos: dict[str, int]
) -> tuple[bool, dict[str, int]]:
    """Um dia inteiro do briefing: coleta, compõe, e devolve (falou do card?, mapa de amanhã).

    ⚠️ É o ÚNICO lugar deste arquivo que conhece as assinaturas de `coletar` e `compor`. Quando
    elas mudarem, edite só este helper — as asserções descrevem comportamento de produto e não
    devem mudar junto com a forma de chamar.
    """
    ausencias = coletar(db, user=user, hoje=hoje, ja_reportadas=marcos)
    payload = composer.compor(fatos=[], ausencias=ausencias, tendencias=[], valores={})
    falou = any(linha.kind == KIND_CARD for linha in payload.linhas)
    return falou, payload.ausencias_ditas


def test_ausencia_calada_continua_calada_no_dia_seguinte(db, usuario_owner, card_parado):
    """Fala no dia 12, cala no 13, e no 14 tem de CONTINUAR calada — a próxima é a 24.

    Hoje ela volta no dia 14. O mapa do payload é montado só com o que foi dito, então a
    ausência calada no dia 13 não entra nele; no dia 14 não há valor anterior e ela é tratada
    como novidade. O silêncio prometido dura exatamente um dia, e o dono vê a mesma pendência
    dia sim, dia não.
    """
    falou_12, marcos = _um_dia(db, usuario_owner, hoje=date(2026, 8, 6), marcos={})
    assert falou_12, "cruzou o limiar de 10 dias — tem de ser dito"
    assert marcos[CHAVE_CARD] == 12

    falou_13, marcos = _um_dia(db, usuario_owner, hoje=date(2026, 8, 7), marcos=marcos)
    assert not falou_13, "13 dias não é notícia nova"

    falou_14, _ = _um_dia(db, usuario_owner, hoje=date(2026, 8, 8), marcos=marcos)
    assert not falou_14, "14 dias também não é: a regra vale além de um dia"
```

- [ ] **Step 2: Rodar e CONFIRMAR que falha**

Run: `cd apps/api && <python> -m pytest tests/test_vima_regra_do_silencio.py -v`

Expected: **FAIL** em `assert not falou_14`, com a mensagem `14 dias também não é: a regra vale além de um dia`.

**Se passar:** pare imediatamente. Não siga para a Tarefa 2. Reporte que o teste passou, cole a saída, e diga que o design precisa ser revisto — a premissa dele era que este teste falha.

- [ ] **Step 3: Commitar o vermelho**

```bash
git add apps/api/tests/test_vima_regra_do_silencio.py
git commit -m "test: a regra do silêncio cala por um dia só, e este teste prova [vermelho]

O silêncio promete voltar quando os dias DOBRAM. Encadeando três dias reais — o
mapa de um dia como entrada do seguinte — a pendência volta no terceiro, porque
a ausência calada nao entra no mapa daquele dia e no dia seguinte nao ha valor
anterior para compará-la.

Os testes existentes cobrem uma transição de um dia e passam. Nenhum atravessa
três, que é onde a sequência quebra.

Commitado VERMELHO de propósito: é o gate de abertura do plano.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `_proximo_marco` — a escalada que atravessa o zero

**Files:**
- Modify: `apps/api/app/modules/vima/absences.py:121-133` (`_ja_dita` → `_calada`, mais a função nova)
- Test: `apps/api/tests/test_vima_regra_do_silencio.py` (acrescenta testes de unidade)

**Interfaces:**
- Produces: `_proximo_marco(anterior: int) -> int` e `_calada(ausencia: Ausencia, marcos: dict[str, int] | None) -> bool`, ambas privadas de `absences.py`. `_ja_dita` deixa de existir.

- [ ] **Step 1: Escrever os testes de unidade**

Acrescente ao fim de `apps/api/tests/test_vima_regra_do_silencio.py`:

```python
# ── A função de escalada ────────────────────────────────────────────────────────────────


def test_o_ramo_positivo_e_o_comportamento_de_hoje():
    """É a identidade que torna seguro aplicar o conserto às cinco famílias de ausência.

    Se este teste falhar, o conserto deixou de ser transparente para card parado, contato
    sumido, ninguém respondeu, prazo e topo seco — e o raio da mudança passou a ser outro.
    """
    from app.modules.vima.absences import _proximo_marco

    for anterior in (1, 2, 3, 10, 12, 30):
        assert _proximo_marco(anterior) == anterior * 2


def test_falou_antes_de_vencer_volta_no_vencimento():
    """Marco negativo é "ainda não venceu". O próximo momento que é notícia é o vencimento.

    Com `anterior * 2` puro, um marco de -3 pede -6 — um número que `dias` nunca mais alcança,
    porque ele só cresce. A ausência deixaria de ser calada para sempre.
    """
    from app.modules.vima.absences import _proximo_marco

    assert _proximo_marco(-3) == 0
    assert _proximo_marco(-1) == 0


def test_falou_no_vencimento_volta_no_primeiro_dia_de_atraso():
    """Zero dobrado é zero: sem este ramo, a ausência falaria todo dia depois de vencer."""
    from app.modules.vima.absences import _proximo_marco

    assert _proximo_marco(0) == 1
```

- [ ] **Step 2: Rodar e verificar que falham**

Run: `cd apps/api && <python> -m pytest tests/test_vima_regra_do_silencio.py -k proximo_marco -v`

Expected: FAIL — `ImportError: cannot import name '_proximo_marco'`.

- [ ] **Step 3: Implementar**

Em `apps/api/app/modules/vima/absences.py`, substitua a função `_ja_dita` inteira (linhas 121-133) por:

```python
def _proximo_marco(anterior: int) -> int:
    """Em que intensidade esta ausência volta a ser notícia.

    ⚠️ O ramo positivo é LITERALMENTE a expressão que existia aqui antes (`anterior * 2`), e
    isso não é coincidência: é o que torna seguro aplicar o conserto às cinco famílias de uma
    vez. Card parado dito no dia 10 continua voltando no dia 20, sem comportamento novo.

    Os dois ramos de cima existem porque ausência com DATA tem intensidade negativa antes de
    vencer, e dobrar um negativo aponta para o lado errado: um marco de -3 pediria -6, que
    `dias` nunca mais alcança. A sequência que os três ramos produzem é
    `cruzou o limiar → venceu → 1 → 2 → 4 → 8 → 16`.
    """
    if anterior < 0:
        return 0
    if anterior == 0:
        return 1
    return anterior * 2


def _calada(ausencia: Ausencia, marcos: dict[str, int] | None) -> bool:
    """A regra do silêncio: reportada ao CRUZAR o limiar, não enquanto permanece cruzada.

    Escalada é notícia nova. O fator 2 do ramo positivo é arbitrário e deliberadamente grosso:
    "parado há 3 dias" virando "parado há 4" não é informação, virando "parado há 12" é.
    """
    if not marcos:
        return False
    anterior = marcos.get(f"{ausencia.kind}:{ausencia.subject_id}")
    if anterior is None:
        return False
    return ausencia.dias < _proximo_marco(anterior)
```

E na linha 118, dentro de `coletar`, troque a chamada:

```python
    return [a for a in fora if not _calada(a, ja_reportadas)]
```

- [ ] **Step 4: Rodar e verificar que passam**

Run: `cd apps/api && <python> -m pytest tests/test_vima_regra_do_silencio.py tests/test_vima_absences.py -v`

Expected: os três testes de `_proximo_marco` PASSAM; todos os de `test_vima_absences.py` PASSAM (a prova de que o ramo positivo não mudou); `test_ausencia_calada_continua_calada_no_dia_seguinte` continua FALHANDO (o mapa ainda não foi consertado — é a Tarefa 4).

- [ ] **Step 5: Commitar**

```bash
git add apps/api/app/modules/vima/absences.py apps/api/tests/test_vima_regra_do_silencio.py
git commit -m "feat: a escalada do silêncio atravessa o zero [Vima]

Ausência com data tem intensidade NEGATIVA antes de vencer, e \`anterior * 2\`
sobre negativo aponta para o lado errado: um marco de -3 pede -6, que \`dias\`
nunca alcança porque só cresce.

\`_proximo_marco\` mantém o ramo positivo literalmente igual — é isso que prova
que card parado, contato sumido, prazo e topo seco não mudam de comportamento.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: `Coleta` — `coletar` passa a devolver também o que calou

**Files:**
- Modify: `apps/api/app/modules/vima/absences.py:83-118` (assinatura e retorno de `coletar`, mais o dataclass)
- Modify: `apps/api/app/modules/vima/service.py:59-72` (call site)
- Modify: `apps/api/tests/test_vima_absences.py` (11 call sites)
- Modify: `apps/api/tests/test_dna_briefing.py:62` (1 call site)
- Modify: `apps/api/tests/test_vima_regra_do_silencio.py` (só o helper `_um_dia`)

**Interfaces:**
- Consumes: `_calada` e `_proximo_marco` da Tarefa 2.
- Produces: `absences.Coleta`, dataclass congelado com `ditas: list[Ausencia]` e `marcos_anteriores: dict[str, int]`. `coletar(...) -> Coleta`.

⚠️ **Esta tarefa não muda comportamento nenhum.** É troca de forma, ampla e mecânica, isolada num commit próprio para que a revisão do commit seguinte mostre só o que de fato mudou.

- [ ] **Step 1: Escrever o teste do contrato novo**

Acrescente ao fim de `apps/api/tests/test_vima_regra_do_silencio.py`:

```python
# ── O contrato de `coletar` ─────────────────────────────────────────────────────────────


def test_coletar_devolve_o_marco_anterior_de_quem_calou(db, usuario_owner, card_parado):
    """A ausência calada precisa CHEGAR ao compositor de alguma forma, senão ele não tem como
    carregar o marco dela adiante — e é exatamente isso que a faz voltar no dia seguinte."""
    coleta = coletar(
        db, user=usuario_owner, hoje=date(2026, 8, 7), ja_reportadas={CHAVE_CARD: 12}
    )
    assert not any(a.kind == KIND_CARD for a in coleta.ditas), "13 dias não é notícia"
    assert coleta.marcos_anteriores[CHAVE_CARD] == 12


def test_coletar_carrega_o_marco_de_quem_FALOU_tambem(db, usuario_owner, card_parado):
    """`marcos_anteriores` não é "as caladas": é o marco de toda ausência viva que já tem um.

    Quem foi dito e depois CORTADO pelo teto de 12 linhas também precisa preservar o marco —
    ninguém leu aquela linha, então calá-la amanhã seria calar por algo que não foi lido.
    """
    coleta = coletar(
        db, user=usuario_owner, hoje=date(2026, 8, 30), ja_reportadas={CHAVE_CARD: 12}
    )
    assert any(a.kind == KIND_CARD for a in coleta.ditas), "36 dias passou do marco 24"
    assert coleta.marcos_anteriores[CHAVE_CARD] == 12
```

- [ ] **Step 2: Rodar e verificar que falham**

Run: `cd apps/api && <python> -m pytest tests/test_vima_regra_do_silencio.py -k coletar -v`

Expected: FAIL — `AttributeError: 'list' object has no attribute 'ditas'`.

- [ ] **Step 3: Implementar o dataclass e o retorno**

Em `apps/api/app/modules/vima/absences.py`, logo depois do dataclass `Ausencia` (linha 70), acrescente:

```python
@dataclass(frozen=True)
class Coleta:
    """O que o briefing pode dizer hoje, mais a memória de tudo que está vivo.

    ⚠️ `marcos_anteriores` NÃO é "as caladas". É o marco de toda ausência que existe hoje e já
    foi dita alguma vez — calada ou dita. A diferença aparece no teto: uma ausência dita e
    CORTADA pelas 12 linhas também precisa preservar o marco, porque ninguém a leu. Quem
    reduzir isto às caladas reintroduz a piscada por outro caminho.
    """

    ditas: list[Ausencia]
    marcos_anteriores: dict[str, int]
```

Depois troque a anotação de retorno de `coletar` (linha 91) de `-> list[Ausencia]` para `-> Coleta`, e substitua a linha 118 (`return [a for a in fora ...]`) por:

```python
    marcos = ja_reportadas or {}
    return Coleta(
        ditas=[a for a in fora if not _calada(a, marcos)],
        marcos_anteriores={
            chave: marcos[chave]
            for a in fora
            if (chave := f"{a.kind}:{a.subject_id}") in marcos
        },
    )
```

- [ ] **Step 4: Atualizar o call site de produção**

Em `apps/api/app/modules/vima/service.py`, `gerar_ou_ler` (linhas 59-72). Extraia a coleta para
uma variável antes de compor, porque a Tarefa 4 vai precisar dos dois campos:

```python
    coleta = absences.coletar(
        db, user=user, hoje=dia, agora=agora,
        # O DNA da Empresa entra aqui, e só aqui. Sem resposta, o dicionário vem vazio e os
        # defaults conservadores do V1 continuam valendo.
        limiares=dna_resolver.limiares(db),
        ja_reportadas=_ja_reportadas(db, user=user),
    )

    payload = composer.compor(
        fatos=fatos,
        ausencias=coleta.ditas,
        tendencias=trends.coletar(db, user=user, hoje=dia),
        valores=_valores_da_origem(db, fatos),
        referencia=agora,
        desde=desde,
    )
```

- [ ] **Step 5: Atualizar os call sites de teste**

Em `apps/api/tests/test_vima_absences.py`, todas as 11 chamadas a `coletar(...)` passam a ler
`.ditas`. O padrão é sempre o mesmo — a variável recebe `coletar(...).ditas`:

```python
    ausencias = coletar(db, user=usuario_owner, hoje=HOJE).ditas
```

Aplique a todas: linhas 110, 119, 125, 135, 141, 147, 154, 169, 177, 199, 206, 221, 224. Nenhuma
asserção muda.

Em `apps/api/tests/test_dna_briefing.py:62`, a mesma coisa — acrescente `.ditas` ao fim da
chamada a `absences.coletar(...)`.

Em `apps/api/tests/test_vima_regra_do_silencio.py`, edite **apenas** o helper `_um_dia`:

```python
    coleta = coletar(db, user=user, hoje=hoje, ja_reportadas=marcos)
    payload = composer.compor(fatos=[], ausencias=coleta.ditas, tendencias=[], valores={})
```

- [ ] **Step 6: Rodar a suíte inteira**

Run: `cd apps/api && <python> -m pytest -q`

Expected: tudo PASSA menos `test_ausencia_calada_continua_calada_no_dia_seguinte`, que continua o
único vermelho. Se qualquer outro teste falhar, um call site ficou para trás — procure com
`grep -rn "coletar(" apps/api --include=*.py`.

- [ ] **Step 7: Commitar**

```bash
git add apps/api/app/modules/vima/absences.py apps/api/app/modules/vima/service.py apps/api/tests/
git commit -m "refactor: coletar devolve as ditas E o marco de quem já foi dito [Vima]

Sem comportamento novo — troca de forma, ampla e mecânica, isolada para que o
commit seguinte mostre só o que de fato muda.

\`marcos_anteriores\` carrega o marco de toda ausência viva, calada ou dita: quem
foi dito e cortado pelo teto também precisa preservá-lo, porque ninguém leu.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: O mapa passa a ser de marcos, e o vermelho da Tarefa 1 fica verde

**Files:**
- Modify: `apps/api/app/modules/vima/composer.py:64-73` (campo do `Payload`) e `:103-132` (`compor`)
- Modify: `apps/api/app/modules/vima/service.py` (call site, `_serializar`, `_ja_reportadas`)
- Modify: `apps/api/tests/test_vima_regra_do_silencio.py` (helper `_um_dia`, mais dois testes)

**Interfaces:**
- Consumes: `absences.Coleta` da Tarefa 3.
- Produces: `composer.compor(..., marcos_anteriores: dict[str, int] | None = None)`; `Payload.marcos: dict[str, int]` (o campo `ausencias_ditas` deixa de existir); a chave JSON `"marcos"` no payload gravado, com leitura de `"ausencias_ditas"` como fallback permanente.

- [ ] **Step 1: Escrever os dois testes que faltam**

Acrescente ao fim de `apps/api/tests/test_vima_regra_do_silencio.py`:

```python
# ── O mapa gravado ──────────────────────────────────────────────────────────────────────


def test_ausencia_cortada_pelo_teto_preserva_o_marco(db, usuario_owner, card_parado):
    """Cortada pelo teto não foi dita a ninguém — não pode ser calada nem esquecida.

    Hoje ela é esquecida: some do mapa e volta amanhã como novidade. O `Payload` já prometia o
    contrário na própria docstring.
    """
    coleta = coletar(
        db, user=usuario_owner, hoje=date(2026, 8, 30), ja_reportadas={CHAVE_CARD: 12}
    )
    payload = composer.compor(
        fatos=[], ausencias=coleta.ditas, tendencias=[], valores={},
        marcos_anteriores=coleta.marcos_anteriores, teto=0,
    )
    assert payload.linhas == [], "teto=0 não mostra nada"
    assert payload.marcos[CHAVE_CARD] == 12, "o marco de quem ninguém leu tem de sobreviver"


def test_briefing_gravado_antes_desta_mudanca_continua_calando(db):
    """Os payloads em produção têm a chave antiga. Sem o fallback, todo o silêncio seria
    perdido no dia do deploy e o briefing repetiria tudo de uma vez."""
    import json

    from app.modules.vima.service import _marcos_do_payload

    antigo = json.dumps({"linhas": [], "ausencias_ditas": {CHAVE_CARD: 12}})
    assert _marcos_do_payload(antigo) == {CHAVE_CARD: 12}

    novo = json.dumps({"linhas": [], "marcos": {CHAVE_CARD: 12}})
    assert _marcos_do_payload(novo) == {CHAVE_CARD: 12}
```

- [ ] **Step 2: Rodar e verificar que falham**

Run: `cd apps/api && <python> -m pytest tests/test_vima_regra_do_silencio.py -v`

Expected: FAIL nos dois novos (`compor() got an unexpected keyword argument 'marcos_anteriores'` e `ImportError: cannot import name '_marcos_do_payload'`), e o vermelho da Tarefa 1 continua falhando.

- [ ] **Step 3: Implementar no compositor**

Em `apps/api/app/modules/vima/composer.py`, no dataclass `Payload`, substitua o campo
`ausencias_ditas` e o comentário acima dele por:

```python
    # `{kind}:{subject_id}` → o `dias` em que cada ausência VIVA parou. Não é "o que foi dito
    # hoje": a calada preserva o marco anterior (senão amanhã ela volta como novidade) e a
    # cortada pelo teto também (ninguém a leu). Some sozinho quando a ausência é resolvida,
    # porque quem não aparece na coleta de hoje não é carregado adiante.
    marcos: dict[str, int] = field(default_factory=dict)
```

Na assinatura de `compor`, acrescente o parâmetro depois de `tendencias`:

```python
    marcos_anteriores: dict[str, int] | None = None,
```

E no `return Payload(...)`, substitua a linha de `ausencias_ditas` por:

```python
        marcos={
            **(marcos_anteriores or {}),
            **{c.chave: c.dias for c in mantidas if c.chave},
        },
```

- [ ] **Step 4: Implementar no serviço**

Em `apps/api/app/modules/vima/service.py`:

**(a)** No `compor(...)` de `gerar_ou_ler`, passe o mapa:

```python
        ausencias=coleta.ditas,
        marcos_anteriores=coleta.marcos_anteriores,
```

**(b)** Em `_serializar`, troque a chave e a docstring:

```python
def _serializar(payload: composer.Payload) -> dict:
    """A evidência do que a IA recebeu, mais o que precisa sobreviver até o briefing seguinte.

    `marcos` existe para a regra do silêncio: sem guardar em que intensidade cada ausência
    parou, amanhã não há como saber se ela escalou.
    """
    return {
        "referencia": payload.referencia.isoformat() if payload.referencia else None,
        "desde": payload.desde.isoformat() if payload.desde else None,
        "excedente": payload.excedente,
        "linhas": [asdict(linha) for linha in payload.linhas],
        "marcos": payload.marcos,
    }
```

**(c)** Extraia a leitura do payload para uma função própria e use-a em `_ja_reportadas`.
Acrescente logo abaixo de `_ja_reportadas`:

```python
def _marcos_do_payload(payload: str) -> dict[str, int]:
    """Lê o mapa de marcos, aceitando o nome antigo.

    ⚠️ O fallback para `ausencias_ditas` é PERMANENTE, não transitório: os briefings gravados
    em produção têm a chave antiga, e removê-lo faria o produto perder todo o silêncio no dia
    do deploy — o briefing repetiria de uma vez tudo o que já tinha dito. Mesma forma do
    default `""` de `Linha.kind`. Tirá-lo exigiria migrar payload, o que custa mais do que a
    linha custa.
    """
    try:  # payload corrompido não pode calar o briefing de hoje
        dados = json.loads(payload)
    except (TypeError, ValueError):
        return {}
    bruto = dados.get("marcos")
    if bruto is None:
        bruto = dados.get("ausencias_ditas") or {}
    return {str(k): int(v) for k, v in bruto.items()}
```

E em `_ja_reportadas`, substitua o bloco `try/except` + `return` finais por:

```python
    return _marcos_do_payload(anterior.payload)
```

- [ ] **Step 5: Atualizar o helper do teste**

Em `apps/api/tests/test_vima_regra_do_silencio.py`, `_um_dia` passa a encadear o mapa:

```python
    coleta = coletar(db, user=user, hoje=hoje, ja_reportadas=marcos)
    payload = composer.compor(
        fatos=[], ausencias=coleta.ditas, tendencias=[], valores={},
        marcos_anteriores=coleta.marcos_anteriores,
    )
    falou = any(linha.kind == KIND_CARD for linha in payload.linhas)
    return falou, payload.marcos
```

- [ ] **Step 6: Rodar a suíte inteira**

Run: `cd apps/api && <python> -m pytest -q`

Expected: **tudo verde, inclusive `test_ausencia_calada_continua_calada_no_dia_seguinte`.** Se
algum teste de `test_dna_briefing.py` ou `test_vima_*` falhar por `ausencias_ditas`, é call site
esquecido: `grep -rn "ausencias_ditas" apps/api --include=*.py` deve sobrar só dentro de
`_marcos_do_payload` e do teste do fallback.

- [ ] **Step 7: Commitar**

```bash
git add apps/api/app/modules/vima/ apps/api/tests/
git commit -m "fix: a ausência calada para de voltar no dia seguinte [Vima]

O mapa do payload deixa de ser "o que eu disse" e passa a ser "em que ponto cada
ausência viva parou". A calada preserva o marco; a cortada pelo teto também,
porque ninguém a leu; a resolvida cai sozinha, por não aparecer na coleta.

Fecha o vermelho commitado no início do plano. O nome antigo \`ausencias_ditas\`
continua sendo LIDO para sempre: os briefings em produção têm essa chave, e
perder o silêncio no dia do deploy faria o briefing repetir tudo de uma vez.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: A cobrança a receber ganha antecedência

**Files:**
- Modify: `apps/api/app/modules/vima/absences.py:49-59` (`LIMIARES_PADRAO`) e `:173-225` (`_dinheiro_com_data`)
- Test: `apps/api/tests/test_vima_absences.py`

**Interfaces:**
- Consumes: `_proximo_marco` (Tarefa 2), `Coleta` (Tarefa 3).
- Produces: a chave `"cobranca_antecedencia_dias"` em `LIMIARES_PADRAO` (default `3`), consumida pelo catálogo do DNA na Tarefa 6; e o `kind` `"financeiro.cobranca.vencendo"`, que substitui `"financeiro.cobranca.vencida"`.

- [ ] **Step 1: Escrever os testes**

Acrescente ao fim de `apps/api/tests/test_vima_absences.py`. Note o import novo de `Charge` e
`STATUS_OPEN` de receivables — o arquivo hoje só importa os de `payables`:

⚠️ `Charge.kind` e `Charge.method` são `nullable=False` **sem default** — a fixture abaixo copia
a forma que já existe em `tests/test_client_timeline.py:55`. Não invente campos: uma fixture
inventada documenta um payload que não funciona.

```python
def _cobranca(db: Session, *, due: date, desc: str = "Mensalidade agosto") -> Charge:
    cobranca = Charge(
        tenant_id=TENANT, description=desc,
        kind="service", method="pix", amount_cents=200_000,
        due_date=due, status=CHARGE_OPEN,
    )
    db.add(cobranca)
    db.commit()
    return cobranca


def test_cobranca_avisa_antes_de_vencer(db: Session, usuario_owner):
    """A dívida que o V2 expôs: o dono era avisado do que DEVE e surpreendido pelo que não
    recebeu. Numa empresa de uma pessoa, é o dinheiro que entra que um toque antes do
    vencimento ainda salva."""
    _cobranca(db, due=date(2026, 8, 9))  # vence em 3 dias

    ausencias = coletar(db, user=usuario_owner, hoje=HOJE).ditas
    cobrancas = [a for a in ausencias if a.kind == "financeiro.cobranca.vencendo"]
    assert len(cobrancas) == 1
    assert "vence em 09/08" in cobrancas[0].title
    assert cobrancas[0].dias == -3


def test_cobranca_que_vence_hoje_diz_hoje(db: Session, usuario_owner):
    _cobranca(db, due=HOJE)

    (cobranca,) = [
        a
        for a in coletar(db, user=usuario_owner, hoje=HOJE).ditas
        if a.kind == "financeiro.cobranca.vencendo"
    ]
    assert "vence hoje" in cobranca.title
    assert cobranca.dias == 0


def test_cobranca_vencida_mantem_a_voz_de_vencida(db: Session, usuario_owner):
    """"não foi paga" é o estado que muda o que o dono faz, e continua distinto de propósito."""
    _cobranca(db, due=date(2026, 8, 3))

    (cobranca,) = [
        a
        for a in coletar(db, user=usuario_owner, hoje=HOJE).ditas
        if a.kind == "financeiro.cobranca.vencendo"
    ]
    assert "venceu há 3 dia(s) e não foi paga" in cobranca.title
    assert cobranca.dias == 3


def test_a_antecedencia_da_cobranca_tem_limiar_proprio(db: Session, usuario_owner):
    """Cutucar cliente e juntar dinheiro para pagar um boleto são intenções diferentes, e o
    dono responde as duas perguntas separadamente no DNA."""
    _cobranca(db, due=date(2026, 8, 12))  # vence em 6 dias

    curto = coletar(
        db, user=usuario_owner, hoje=HOJE,
        limiares={"cobranca_antecedencia_dias": 3, "dinheiro_com_data_dias": 7},
    ).ditas
    assert not [a for a in curto if a.kind == "financeiro.cobranca.vencendo"]

    longo = coletar(
        db, user=usuario_owner, hoje=HOJE,
        limiares={"cobranca_antecedencia_dias": 7, "dinheiro_com_data_dias": 0},
    ).ditas
    assert [a for a in longo if a.kind == "financeiro.cobranca.vencendo"]


def test_a_cadencia_inteira_de_uma_cobranca(db: Session, usuario_owner):
    """Aviso, vencimento, e depois dobrando: -3 → 0 → 1 → 2 → 4 → 8.

    É a cadência que o dono do produto escolheu, e a prova de que os três ramos de
    `_proximo_marco` se encadeiam sobre um caso real de dinheiro.
    """
    _cobranca(db, due=date(2026, 8, 20))
    marcos: dict[str, int] = {}
    falados: list[date] = []

    for offset in range(-4, 17):
        hoje = date(2026, 8, 20) + timedelta(days=offset)
        coleta = coletar(db, user=usuario_owner, hoje=hoje, ja_reportadas=marcos)
        ditas = [a for a in coleta.ditas if a.kind == "financeiro.cobranca.vencendo"]
        marcos = dict(coleta.marcos_anteriores)
        for a in ditas:
            falados.append(hoje)
            marcos[f"{a.kind}:{a.subject_id}"] = a.dias

    assert falados == [
        date(2026, 8, 17),  # cruzou a antecedência de 3 dias
        date(2026, 8, 20),  # venceu
        date(2026, 8, 21),  # 1 dia
        date(2026, 8, 22),  # 2 dias
        date(2026, 8, 24),  # 4 dias
        date(2026, 8, 28),  # 8 dias
        date(2026, 9, 5),   # 16 dias
    ]
```

No topo do arquivo, acrescente aos imports:

```python
from datetime import UTC, date, datetime, timedelta
...
from app.modules.receivables.models import STATUS_OPEN as CHARGE_OPEN
from app.modules.receivables.models import Charge
```

- [ ] **Step 2: Rodar e verificar que falham**

Run: `cd apps/api && <python> -m pytest tests/test_vima_absences.py -k cobranca -v`

Expected: FAIL — nenhuma ausência com `kind == "financeiro.cobranca.vencendo"` é produzida.

- [ ] **Step 3: Implementar o limiar**

Em `apps/api/app/modules/vima/absences.py`, acrescente ao fim de `LIMIARES_PADRAO`:

```python
    # A cobrança a receber passou a ter antecedência própria, e o número NÃO é derivado do da
    # conta a pagar: juntar dinheiro para pagar um boleto e cutucar um cliente antes de ele
    # atrasar são intenções diferentes, com prazos diferentes. 3 é escolha do dono do produto.
    "cobranca_antecedencia_dias": 3,
```

- [ ] **Step 4: Implementar a regra**

Em `_dinheiro_com_data`, substitua a docstring e o bloco de cobranças. A docstring passa a ser:

```python
    """Conta a pagar e cobrança a receber que a data alcançou.

    As duas direções seguem a MESMA regra desde 2026-08-09 — cada uma com o seu limiar. Antes,
    conta a pagar tinha antecedência e cobrança só aparecia depois de vencida: o dono era
    avisado com folga do que devia e surpreendido pelo que não recebeu, que é o inverso do que
    ajuda numa empresa de uma pessoa. O toque antes do vencimento só muda o resultado do lado
    de quem recebe.

    Os limiares são separados porque as intenções são: `dinheiro_com_data_dias` é "quanto tempo
    preciso para ter o dinheiro", `cobranca_antecedencia_dias` é "quanto antes eu cutuco".
    """
```

E o bloco das cobranças vira:

```python
    limite_cobranca = hoje + timedelta(days=lim["cobranca_antecedencia_dias"])
    cobrancas = db.scalars(
        select(Charge)
        .where(Charge.status == COBRANCA_ABERTA, Charge.due_date <= limite_cobranca)
        .order_by(Charge.due_date)
    ).all()
    for cobranca in cobrancas:
        dias = (hoje - cobranca.due_date).days
        alvo = cobranca.description or "Cobrança"
        if dias > 0:
            quando = f"venceu há {dias} dia(s) e não foi paga"
        elif dias == 0:
            quando = "vence hoje"
        else:
            quando = f"vence em {cobranca.due_date.strftime('%d/%m')}"
        fora.append(
            Ausencia(
                # ⚠️ Era `financeiro.cobranca.vencida`, que virou mentira quando a linha passou
                # a sair ANTES de vencer. O renome custa uma repetição no dia do deploy (as
                # chaves gravadas usam o nome velho), e é barato: o comportamento mudou mesmo.
                module="financeiro", kind="financeiro.cobranca.vencendo",
                title=f"{alvo} — {_brl(cobranca.amount_cents)} {quando}",
                dias=dias, subject_type="charge", subject_id=cobranca.id,
                client_id=cobranca.client_id,
            )
        )
    return fora
```

Renomeie também a variável `limite` (usada pelas contas a pagar) para `limite_conta`, para as
duas ficarem simétricas e ninguém reusar a errada.

- [ ] **Step 5: Rodar e verificar que passam**

Run: `cd apps/api && <python> -m pytest tests/test_vima_absences.py tests/test_vima_regra_do_silencio.py -v`

Expected: todos PASSAM. Se `test_a_cadencia_inteira_de_uma_cobranca` falhar numa data específica,
compare a lista produzida com a esperada antes de mexer em qualquer coisa — a sequência de marcos
é o contrato, e uma data a mais ou a menos aponta para qual ramo de `_proximo_marco` está errado.

- [ ] **Step 6: Verificar que ninguém mais usa o nome antigo**

Run: `grep -rn "cobranca.vencida" apps/ packages/`

Expected: **nenhum resultado.** Se aparecer, é consumidor não previsto — pare e reporte antes de
seguir.

- [ ] **Step 7: Commitar**

```bash
git add apps/api/app/modules/vima/absences.py apps/api/tests/test_vima_absences.py
git commit -m "feat: a cobrança a receber avisa antes de vencer [Vima]

O dono era avisado com folga do que devia e surpreendido pelo que não recebeu.
As duas direções do dinheiro passam a seguir a mesma regra, cada uma com o seu
limiar — juntar dinheiro e cutucar cliente são intenções com prazos diferentes.

\`financeiro.cobranca.vencida\` virou \`.vencendo\`: o nome antigo passa a ser
mentira quando a linha sai antes de vencer. Custa uma repetição no dia do
deploy, porque as chaves gravadas usam o nome velho.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: A 7ª pergunta de Calibração, e o gate que casa gancho com `kind`

**Files:**
- Modify: `apps/api/app/modules/dna/catalog.py:131-196` (a tupla `_CALIBRACAO`)
- Modify: `apps/api/tests/test_dna_catalog.py:62-64` (contagem)
- Test: `apps/api/tests/test_dna_catalog.py` (gate novo)

**Interfaces:**
- Consumes: `LIMIARES_PADRAO["cobranca_antecedencia_dias"]` da Tarefa 5 e o `kind` `financeiro.cobranca.vencendo`.
- Produces: a pergunta `dinheiro.cobranca_antecedencia_dias` no catálogo.

- [ ] **Step 1: Escrever os testes**

Em `apps/api/tests/test_dna_catalog.py`, substitua o teste de contagem (linhas 62-64) por:

```python
def test_o_catalogo_tem_46_perguntas_sendo_7_de_calibracao():
    """São 7 de Calibração porque existem 7 consumidores — nem um a mais.

    A sétima nasceu com o consumidor no mesmo passo (a antecedência da cobrança a receber).
    Esse é o único caminho legítimo para este número subir.
    """
    assert len(PERGUNTAS) == 46
    assert sum(1 for p in PERGUNTAS if p.classe == CALIBRACAO) == 7
```

E acrescente ao fim do arquivo o gate novo:

```python
def test_todo_gancho_de_calibracao_aponta_para_um_kind_que_existe():
    """O gancho é o que cola a pergunta à ausência que a motivou, e é string livre nos dois
    lados. Renomear um `kind` sem renomear o gancho não quebra teste nenhum: a pergunta
    simplesmente nunca mais aparece, e o dono nunca calibra aquela regra. Silêncio perfeito, do
    mesmo feitio que a guarda de `consome` existe para impedir.
    """
    import re
    from pathlib import Path

    from app.modules.vima import absences

    fonte = Path(absences.__file__).read_text(encoding="utf-8")
    kinds = set(re.findall(r'kind="([^"]+)"', fonte))
    assert kinds, "a varredura não achou kind nenhum — o gate ficaria verde por vacuidade"

    for p in PERGUNTAS:
        if p.classe != CALIBRACAO:
            continue
        alvo = p.gancho.removeprefix("briefing.ausencia.")
        assert alvo in kinds, f"{p.key} aponta para o kind inexistente '{alvo}'"
```

- [ ] **Step 2: Rodar e verificar que falham**

Run: `cd apps/api && <python> -m pytest tests/test_dna_catalog.py -v`

Expected: **FAIL só na contagem** (`assert 45 == 46`). O gate novo deve **passar já**, porque os 6
ganchos existentes casam com `kind` reais. Se o gate falhar agora, um dos 6 já está desalinhado —
pare e reporte: é defeito que existe hoje e não faz parte deste trabalho.

- [ ] **Step 3: Implementar a pergunta**

Em `apps/api/app/modules/dna/catalog.py`, acrescente ao fim da tupla `_CALIBRACAO`, logo depois
da pergunta `dinheiro.antecedencia_dias`:

```python
    _cal(
        "dinheiro.cobranca_antecedencia_dias", "dinheiro",
        "E de uma cobrança que você tem a receber?",
        (
            Opcao("No próprio dia", 0),
            Opcao("1 dia antes", 1),
            Opcao("3 dias antes", 3),
            Opcao("1 semana antes", 7),
        ),
        "cobranca_antecedencia_dias",
        "briefing.ausencia.financeiro.cobranca.vencendo",
    ),
```

⚠️ **Não** acrescente esta pergunta ao `NUCLEO`. Ele continua com 6 e continua sendo de Retrato:
Calibração vai por gancho, colada à ausência que a motivou, que é a inversão central do V2.

- [ ] **Step 4: Rodar e verificar que passam**

Run: `cd apps/api && <python> -m pytest tests/test_dna_catalog.py tests/test_dna_resolver.py tests/test_dna_briefing.py -v`

Expected: todos PASSAM. As duas guardas de import do catálogo rodam sozinhas ao importar o
módulo — se você tiver escrito `cobranca_antecedencia_dais` no `consome`, o import estoura com
`CatalogoError` antes de qualquer teste rodar, e essa é a mensagem que você vai ver.

- [ ] **Step 5: Commitar**

```bash
git add apps/api/app/modules/dna/catalog.py apps/api/tests/test_dna_catalog.py
git commit -m "feat: a 7ª pergunta de Calibração — a antecedência da cobrança [Vima V2]

O V2 fixou que são 6 porque existem 6 consumidores, e que qualquer número maior
seria invenção. Nasceu um consumidor real na tarefa anterior, então nasce a
sétima — este é o caso legítimo, e a primeira vez que a guarda de import é
exercitada por um consumidor novo.

Gate novo: todo gancho de Calibração tem de apontar para um \`kind\` que existe em
absences.py. Renomear um sem o outro não quebrava nada — a pergunta só nunca
mais apareceria, e o dono nunca calibraria aquela regra.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: As quatro mutações, os três comandos, e a entrada no CLAUDE.md

**Files:**
- Modify: `CLAUDE.md` (seção "Vima V2: o DNA da Empresa")

⚠️ **Restaure cada mutação por CÓPIA DE ARQUIVO, nunca por `git checkout`.** Um `checkout` sobre
arquivo com trabalho não commitado já apagou uma sessão inteira neste repositório. A cópia vai
para **fora do repo**, senão o `.bak` acaba commitado. Antes de cada mutação:

```bash
cp apps/api/app/modules/vima/absences.py "${TEMP:-/tmp}/absences.bak"
```

Depois, para restaurar:

```bash
cp "${TEMP:-/tmp}/absences.bak" apps/api/app/modules/vima/absences.py
```

O mesmo vale para `composer.py` na Mutação 1.

- [ ] **Step 1: Mutação 1 — o carry-forward**

Em `composer.py`, troque o dicionário de `marcos` por só o de hoje:

```python
        marcos={c.chave: c.dias for c in mantidas if c.chave},
```

Run: `cd apps/api && <python> -m pytest tests/test_vima_regra_do_silencio.py -q`

Expected: falham **`test_ausencia_calada_continua_calada_no_dia_seguinte`** e
**`test_ausencia_cortada_pelo_teto_preserva_o_marco`**, e nada mais. Restaure o arquivo.

- [ ] **Step 2: Mutação 2 — o ramo negativo**

Em `absences.py`, apague as duas primeiras linhas de `_proximo_marco` (o `if anterior < 0`).

Run: `cd apps/api && <python> -m pytest tests/ -q -k "cadencia or proximo_marco"`

Expected: falham `test_falou_antes_de_vencer_volta_no_vencimento` e
`test_a_cadencia_inteira_de_uma_cobranca` (no dia do vencimento). Restaure.

- [ ] **Step 3: Mutação 3 — o ramo do zero**

Em `absences.py`, apague o `if anterior == 0: return 1`.

Run: `cd apps/api && <python> -m pytest tests/ -q -k "cadencia or proximo_marco"`

Expected: falham `test_falou_no_vencimento_volta_no_primeiro_dia_de_atraso` e
`test_a_cadencia_inteira_de_uma_cobranca` (no primeiro dia de atraso). Restaure.

- [ ] **Step 4: Mutação 4 — a que compra o raio das cinco famílias**

Em `absences.py`, substitua o corpo inteiro de `_proximo_marco` por `return anterior * 2`.

Run: `cd apps/api && <python> -m pytest -q`

Expected: falham **apenas** testes de dinheiro (`test_a_cadencia_inteira_de_uma_cobranca`) e os
de `_proximo_marco`. **Se qualquer teste comercial falhar** — card parado, contato sumido, topo
seco, prazo —, a afirmação central do design ("o ramo positivo é a expressão de hoje") era falsa:
pare, restaure, e reporte. Restaure.

- [ ] **Step 5: Os três comandos**

```bash
cd apps/api && <python> -m ruff check .
cd apps/api && <python> -m pytest
cd ../.. && pnpm --filter @e1p/web test
```

Expected: os três verdes. O `ruff` é gate de CI e é o mais fácil de esquecer, porque não é teste.

- [ ] **Step 6: Escrever a entrada no CLAUDE.md**

É o passo 4 do §5 do CLAUDE.md, com o mesmo peso do teste. Escreva a partir do **código que
subiu**, não do que o plano pretendia. Na seção `## Vima V2: o DNA da Empresa (2026-08-08)`:

**(a)** Acrescente ao fim da seção um bloco novo:

```markdown
### A cobrança ganhou antecedência, e a regra do silêncio passou a valer (2026-08-09)

> Spec: `docs/superpowers/specs/2026-08-09-vima-cobranca-com-antecedencia-design.md` ·
> Plano: `docs/superpowers/plans/2026-08-09-vima-cobranca-com-antecedencia.md`

Investigar a dívida da cobrança revelou que **a regra do silêncio estava quebrada em dois
lugares**, e um deles já sangrava: uma conta a pagar em aberto aparecia todo dia do
vencimento−1 ao vencimento+2, e depois dia sim, dia não, para sempre.

- [x] **`_proximo_marco` substituiu `anterior * 2`** — três ramos: negativo devolve `0` (falou
  antes de vencer, volta no vencimento), zero devolve `1`, positivo devolve `anterior * 2`,
  **literalmente a expressão de antes**. É essa identidade que tornou seguro aplicar o conserto
  às cinco famílias de uma vez, e ela é provada por mutação: trocar a função de volta pelo
  dobro puro só pode quebrar testes de dinheiro.
- [x] **O mapa do payload deixou de ser "o que eu disse" e virou "em que ponto cada ausência
  viva parou"** (`Payload.marcos`, chave JSON `marcos`). Antes ele era montado só com as linhas
  `mantidas` e lido só do briefing anterior: a ausência calada não entrava nele, e no dia
  seguinte "sem valor anterior" era indistinguível de "nunca falei disto". **O silêncio durava
  exatamente um dia.** Os testes cobriam as duas transições de UM dia e passavam.
  - ⚠️ **`marcos_anteriores` de `absences.Coleta` NÃO é "as caladas"** — é o marco de toda
    ausência viva que já tem um. A diferença aparece no teto: dita e CORTADA pelas 12 linhas
    também preserva o marco, porque ninguém a leu. Reduzir isto às caladas reintroduz a piscada
    por outro caminho.
  - ⚠️ **`service._marcos_do_payload` lê `ausencias_ditas` como fallback, e isso é PERMANENTE.**
    Os briefings gravados em produção têm a chave antiga; sem o fallback o produto perderia
    todo o silêncio no dia do deploy e repetiria de uma vez tudo que já tinha dito.
- [x] **A cobrança a receber avisa antes de vencer** (`cobranca_antecedencia_dias`, default
  **3**, decidido pelo dono do produto e não derivado de outro número). As duas direções do
  dinheiro passaram a seguir a mesma regra, com limiares separados porque as intenções são
  diferentes: juntar dinheiro para pagar × cutucar o cliente antes de ele atrasar.
  - ⚠️ **`financeiro.cobranca.vencida` virou `financeiro.cobranca.vencendo`** — o nome antigo
    passou a ser mentira quando a linha saiu antes de vencer. Custou uma repetição no dia do
    deploy (as chaves gravadas usam o nome velho), e é o preço certo.
- [x] **7ª pergunta de Calibração** (`dinheiro.cobranca_antecedencia_dias`), com o consumidor
  nascido no mesmo passo — o único caminho legítimo para o número 6 subir. **Não entrou no
  núcleo:** Calibração vai por gancho, colada à ausência que a motivou.
  - **Gate novo:** todo gancho de Calibração tem de apontar para um `kind` que existe em
    `absences.py`. Renomear um sem o outro não quebrava teste nenhum — a pergunta só nunca mais
    apareceria, e o dono nunca calibraria aquela regra.
- **Efeito visível:** o briefing ficou mais quieto em TODAS as seções, não só na do dinheiro.
- **Achado registrado e NÃO corrigido aqui:** `dna/resolver.recalibrado_apos` usa
  `answered_at.date()` num `timestamptz`, a mesma forma que a `cadencia.py` documenta como
  errada. Aqui ela erra sempre para o lado de LIMPAR o silêncio, que é o erro barato declarado
  na própria docstring, e a varredura AST não a pega porque não é leitura de relógio.
- **Dívida:** a validação em ~360px do V2 continua pendente, e a aba "A sua empresa" ganhou uma
  linha a mais no eixo `dinheiro`. As perguntas agora são 46 e seguem sem validação com dono
  real.
```

**(b)** Na lista de **Dívidas** da seção do V2 (o último bullet), remova o trecho **"cobrança a
receber continua sem antecedência (`_dinheiro_com_data` dá aviso prévio a conta a pagar e nenhum
a cobrança, que só aparece vencida — o dono é avisado do que deve e surpreendido pelo que não
recebeu)"**. Dívida fechada e ainda escrita manda o próximo leitor resolver de novo o que já está
resolvido (§5, passo 4). As outras dívidas do bullet ficam.

**(c)** Na seção `## Vima: o Registro de Fatos e o briefing`, no bullet **"A regra do
silêncio"**, acrescente ao fim: `⚠️ **Ela só passou a valer de fato em 2026-08-09** — até lá o
silêncio durava um dia e a pendência voltava no seguinte. Ver a seção do V2.`

- [ ] **Step 7: Commitar**

```bash
git add CLAUDE.md
git commit -m "docs: registra a antecedência da cobrança e o conserto do silêncio [Vima]

Fecha a dívida do V1 que o V2 expôs, e remove o bullet dela da lista — dívida
resolvida e ainda escrita manda o próximo leitor resolver de novo.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Ao terminar

O trabalho está pronto para PR. **Não faça `git push` nem `gh pr create`** — as duas operações
são exclusivas do @devops. Reporte:

- o resultado dos três comandos, com a saída;
- o resultado das quatro mutações, dizendo **quais** testes cada uma derrubou;
- qualquer divergência entre o que o plano previa e o que o código pediu.

Título sugerido do PR: `feat: a cobrança avisa antes de vencer, e o silêncio do briefing passa a valer [Vima]`.
