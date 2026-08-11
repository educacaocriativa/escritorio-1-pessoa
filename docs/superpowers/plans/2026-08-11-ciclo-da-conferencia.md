# O ciclo da conferência — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Instrumentar o ciclo mínimo que faz `|divergencia_cents|` significar alguma coisa — o dono passa a ver, por mês, se o e1p conseguiu conferir tudo, e quanto se moveu na janela que produziu aquele número.

**Architecture:** Tudo é **leitura derivada**, sem migration e sem escrita. `bank/reconciliation.py` ganha o volume por conta (query em lote) e uma função nova `ciclos_da_conferencia()` que roda o relatório existente uma vez por mês e classifica cada mês como legível ou não, nomeando o motivo. Uma rota nova serve isso; a Conferência exibe; o Vima cutuca quando o saldo do mês não foi declarado.

**Tech Stack:** FastAPI + SQLAlchemy 2 (Python 3.13), pytest; React 18 + TypeScript + Vitest + `@testing-library`; Playwright para a medição de 360px.

**Spec:** `docs/superpowers/specs/2026-08-11-ciclo-da-conferencia-design.md` — leia antes da Task 1. Este plano implementa aquela spec e não a reinterpreta.

## Global Constraints

- **ANOTA, NUNCA SUBTRAI.** Nenhuma linha deste plano pode alterar `divergencia_cents`, `dentro_da_tolerancia`, `tolerancia_cents`, `total_divergencia_cents` ou `contas_fora_da_banda`. É a Regra 5 do `CLAUDE.md`.
- **A banda `max(R$ 50; 0,5%)` é FIXA.** Nada aqui a parametriza, persiste, lê de config ou expõe.
- **Zero migration, zero escrita.** Nenhum `INSERT`/`UPDATE`/`DELETE`, nenhum arquivo em `apps/api/migrations/`.
- **A string `"no banco"` é PROIBIDA** na Conferência e em qualquer código novo desta frente — ela pertence à parcela da Projeção, com outro sentido (UX-001). Nem sinônimo locacional.
- **A palavra "legível" NÃO aparece na tela.** É termo de domínio: código, docstrings e `CLAUDE.md`. Na tela é frase. Também proibidos na tela: "gate", "Onda 4", "métrica", e qualquer contagem até três.
- **"Hoje" é sempre `hoje_do_tenant(db)`** (`app/modules/settings/service.py:112`), nunca `date.today()` nem `datetime.now(UTC).date()`.
- **Dinheiro é `int` em centavos.** Nenhum `float` em nenhum caminho.
- **Isolamento por RLS e só por RLS** — nenhuma query nova filtra `tenant_id` à mão (Regra de Ouro nº 1).
- **`bank` não importa `payables`/`receivables`/`wallet`.** Os gates de `tests/test_money_planes.py` continuam apertados; nada aqui precisa de allowlist.
- Idioma: PT-BR em domínio/comentários, inglês nos identificadores. Commits: Conventional Commits com `[Epic 8]`.
- **Não faça `git push` nem abra PR.** É exclusivo do @devops.
- **NÃO conserte nada desta lista, mesmo esbarrando nela:** SIG-001 (a virada de mês apagando conferência recente — é vizinho do bloco 4 e você vai lê-lo), o estouro horizontal de 15px do `AppShell`, o índice irmão de `charges.bank_account_id`, a unicidade de `bank_accounts.name`, o drift de `generated.ts`, e contar P4 de verdade. Misturar correção de defeito existente com regra nova tira do gate a capacidade de julgar qual mudança quebrou o quê — o mesmo argumento que manteve SIG-001 fora da 8.16 e separou a 8.19 da 8.20.
- **Não meça a divergência nem opine sobre a Onda 4.** Esta frente constrói o instrumento e para.

---

## File Structure

**Backend (modificar):**
- `apps/api/app/modules/bank/reconciliation.py` — o volume por conta, `PRIMEIRO_CICLO_MEDIVEL`, `CicloDaConferencia`, `ciclos_da_conferencia()`, conserto da docstring de P4. É o arquivo onde a regra do épico já mora; espalhá-la criaria a segunda redação do mesmo fato.
- `apps/api/app/modules/bank/schemas.py` — dois campos em `ConferenciaContaOut`, `CicloDaConferenciaOut`, `CiclosDaConferenciaOut`.
- `apps/api/app/modules/bank/router.py` — dois campos no mapper, rota `GET /reconciliation-cycles`.
- `apps/api/app/main.py` — conserto do comentário de P4 (linha ~154).
- `apps/api/app/modules/vima/absences.py` — a família `financeiro.conferencia.saldo_do_mes`.

**Backend (criar):**
- `apps/api/tests/test_bank_ciclos.py` — a legibilidade, a precedência, o corte, o histórico.

**Frontend (modificar):**
- `apps/web/src/features/financeiro/conferencia.ts` — tipos + `fraseDoCiclo` (pura).
- `apps/web/src/features/financeiro/ConferenciaPage.tsx` — `CicloCard` (acima das frases) + `HistoricoDeCiclos` (abaixo da tabela).
- `apps/web/src/features/financeiro/conferencia.test.ts`, `ConferenciaPage.test.tsx`.

**Docs (modificar):** `CLAUDE.md`, `docs/HOSTINGER-DEPLOY.md`.

---

### Task 1: O volume por conta

**Files:**
- Modify: `apps/api/app/modules/bank/reconciliation.py`
- Test: `apps/api/tests/test_bank_reconciliation_report.py`

**Interfaces:**
- Consumes: `service.list_accounts`, `BankTransaction`, `STATUS_IGNORED` (já importados no arquivo).
- Produces: `ConferenciaConta.movimentos_no_periodo: int`, `ConferenciaConta.valor_movimentado_cents: int`, `reconciliation._volume_counts(db, *, accounts, start, end) -> dict[str, tuple[int, int]]`.

- [ ] **Step 1: Escreva o teste que falha — o volume conta e soma em módulo**

Em `apps/api/tests/test_bank_reconciliation_report.py`, no fim do arquivo. Use as fixtures/helpers já existentes no arquivo para criar conta e movimentos (leia o topo do arquivo antes; não invente helper novo).

```python
def test_volume_conta_movimentos_e_soma_em_modulo(db, conta):
    """R$ 5.000 entrando e R$ 5.000 saindo é um mês MOVIMENTADO, não um mês zerado.

    A soma assinada diria `0` e o denominador mentiria exatamente no mês em que ele mais precisa
    dizer "aconteceu coisa aqui" — que é a razão de o volume existir.
    """
    _movimento(db, conta, posted_at=date(2026, 7, 10), amount_cents=500_000)
    _movimento(db, conta, posted_at=date(2026, 7, 12), amount_cents=-500_000)

    r = reconciliation.reconciliation_report(
        db, start=date(2026, 7, 1), end=date(2026, 7, 31), today=date(2026, 8, 1)
    )

    assert r.contas[0].movimentos_no_periodo == 2
    assert r.contas[0].valor_movimentado_cents == 1_000_000


def test_volume_exclui_ignorados(db, conta):
    """Mesmo filtro do saldo derivado: o volume qualifica AQUELE saldo.

    Um movimento ignorado está fora de `service._movements_sums`; contá-lo aqui diria que houve
    movimento onde o saldo não viu nenhum.
    """
    _movimento(db, conta, posted_at=date(2026, 7, 10), amount_cents=100_000)
    ignorado = _movimento(db, conta, posted_at=date(2026, 7, 11), amount_cents=900_000)
    ignorado.status = STATUS_IGNORED
    db.commit()

    r = reconciliation.reconciliation_report(
        db, start=date(2026, 7, 1), end=date(2026, 7, 31), today=date(2026, 8, 1)
    )

    # O controle positivo do recorte: o movimento normal continua contado.
    assert r.contas[0].movimentos_no_periodo == 1
    assert r.contas[0].valor_movimentado_cents == 100_000


def test_volume_zero_quando_nada_se_moveu(db, conta):
    """Mês dormente: o ciclo NÃO é recusado — o denominador aparece zerado e se lê sozinho."""
    r = reconciliation.reconciliation_report(
        db, start=date(2026, 7, 1), end=date(2026, 7, 31), today=date(2026, 8, 1)
    )

    assert r.contas[0].movimentos_no_periodo == 0
    assert r.contas[0].valor_movimentado_cents == 0
```

Se `_movimento` / `conta` não existirem com esses nomes no arquivo, use os helpers reais que estiverem lá e ajuste as chamadas — **não crie fixtures paralelas**.

- [ ] **Step 2: Rode e veja falhar**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_bank_reconciliation_report.py -k volume -v`
Expected: FAIL — `AttributeError: 'ConferenciaConta' object has no attribute 'movimentos_no_periodo'`

- [ ] **Step 3: Acrescente os dois campos ao dataclass**

Em `ConferenciaConta`, **antes** de `notes` (que tem default) e depois de `movimentos_ignorados`:

```python
    # ── o denominador do bloco 1 ──────────────────────────────────────────────────────────────
    # Quanto se moveu NESTA janela, nesta conta. Existe para que `divergencia_cents` nunca seja
    # lida sem o volume que a produziu: um mês sem movimento nenhum dá divergência zero e não
    # prova nada, e o zero aqui é o que diz isso em voz alta. Mesmo princípio do consolidado que
    # nunca existe sem a decomposição por conta (F3).
    # ⚠️ **Sem default, de propósito.** São dois sites de construção (`_conferir_conta`), e um
    # terceiro que esquecesse de passá-los gravaria "não se moveu nada" em silêncio — que é
    # justamente a afirmação que o campo existe para impedir. Falhar alto é o comportamento certo.
    movimentos_no_periodo: int
    valor_movimentado_cents: int
```

- [ ] **Step 4: Escreva a query em lote**

Logo abaixo de `_ignored_counts`, no mesmo bloco "Leituras locais deste relatório":

```python
def _volume_counts(
    db: Session, *, accounts: Sequence[BankAccount], start: date, end: date
) -> dict[str, tuple[int, int]]:
    """`{bank_account_id: (nº de movimentos, Σ|amount_cents|)}` em `[start, end]`, em UMA query.

    **O denominador da divergência.** `divergencia_cents` sozinha não distingue *"nada aconteceu"*
    de *"tudo aconteceu e nada foi registrado"* — o `CLAUDE.md` registra que o sistema não faz essa
    distinção. O volume não a faz também; ele apenas **impede que o número seja lido sem ela**.

    **`func.abs` porque o volume é MOVIMENTAÇÃO, não resultado.** R$ 5.000 entrando e R$ 5.000
    saindo é um mês movimentado; a soma assinada diria `0` e o denominador mentiria exatamente no
    mês em que ele mais precisa dizer que aconteceu coisa ali.

    **`status <> 'ignored'` — o MESMO recorte de `service._movements_sums`**, e não uma escolha
    nova: o volume qualifica aquele saldo derivado, e contar aqui um movimento que o saldo não viu
    diria que houve movimento onde não houve.

    Contagem em lote pelo mesmo motivo de `_ignored_counts`: a janela é a mesma para todas as
    contas — é o período do relatório, não a data de referência de cada checkpoint. Nada aqui é
    comparado com nada, então o AC4b não está em jogo.
    """
    if not accounts:
        return {}
    stmt = (
        select(
            BankTransaction.bank_account_id,
            func.count(),
            func.coalesce(func.sum(func.abs(BankTransaction.amount_cents)), 0),
        )
        .where(
            BankTransaction.bank_account_id.in_([a.id for a in accounts]),
            BankTransaction.status != STATUS_IGNORED,
            BankTransaction.posted_at >= start,
            BankTransaction.posted_at <= end,
        )
        .group_by(BankTransaction.bank_account_id)
    )
    return {
        account_id: (int(n or 0), int(total or 0))
        for account_id, n, total in db.execute(stmt).all()
    }
```

- [ ] **Step 5: Ligue nos dois sites de construção**

Em `reconciliation_report`, logo abaixo de `ignorados = _ignored_counts(...)`:

```python
    volumes = _volume_counts(db, accounts=accounts, start=start, end=end)
```

E passe para `_conferir_conta` na list comprehension:

```python
            movimentos_ignorados=ignorados.get(account.id, 0),
            volume=volumes.get(account.id, (0, 0)),
```

Em `_conferir_conta`, acrescente o parâmetro `volume: tuple[int, int]` à assinatura (keyword-only, junto dos outros) e, **nos DOIS `return ConferenciaConta(...)`** — o do caminho não avaliável e o do avaliável:

```python
            movimentos_no_periodo=volume[0],
            valor_movimentado_cents=volume[1],
```

⚠️ O caminho **não avaliável** também recebe o volume, e isso é a decisão: o mês em que o dono não declarou saldo mas movimentou R$ 18.000 é diferente do mês em que ele não declarou nada porque nada aconteceu, e zerar ali apagaria a diferença.

- [ ] **Step 6: Rode e veja passar**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_bank_reconciliation_report.py -v`
Expected: PASS — todos, inclusive os 36 pré-existentes.

- [ ] **Step 7: O gate central — ANOTA, NUNCA SUBTRAI**

Acrescente ao mesmo arquivo de teste:

```python
def test_volume_nao_altera_a_divergencia(db, conta):
    """A Regra 5 mecanizada para esta frente.

    Congela campo a campo o que NÃO pode mudar e dá controle positivo ao que DEVE — a lição do
    `test_cockpit_e_carteira_intactos` da Onda 3, onde um teste que congelava o agregado inteiro
    reprovou a funcionalidade correta e a "correção óbvia" (apagá-lo) levaria junto a invariante.
    """
    _checkpoint(db, conta, reference_date=date(2026, 7, 31), balance_cents=250_000)
    _movimento(db, conta, posted_at=date(2026, 7, 10), amount_cents=500_000)

    r = reconciliation.reconciliation_report(
        db, start=date(2026, 7, 1), end=date(2026, 7, 31), today=date(2026, 8, 1)
    )
    c = r.contas[0]

    # Congelados: o volume não entra em nenhum deles.
    assert c.divergencia_cents == c.saldo_banco_cents - c.saldo_sistema_cents
    assert c.tolerancia_cents == reconciliation.tolerance_cents(c.saldo_banco_cents)
    assert c.dentro_da_tolerancia is (abs(c.divergencia_cents) <= c.tolerancia_cents)
    assert r.total_divergencia_cents == c.divergencia_cents
    assert [f.bank_account_id for f in r.contas_fora_da_banda] == (
        [c.bank_account_id] if c.dentro_da_tolerancia is False else []
    )

    # Controle positivo: sem ele o teste passaria com o volume devolvendo zero para sempre.
    assert c.movimentos_no_periodo == 1
    assert c.valor_movimentado_cents == 500_000
```

- [ ] **Step 8: Rode a suíte do módulo inteira**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_bank_reconciliation_report.py tests/test_money_planes.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add apps/api/app/modules/bank/reconciliation.py apps/api/tests/test_bank_reconciliation_report.py
git commit -m "feat: a divergencia passa a viajar com o volume da janela [Epic 8]"
```

---

### Task 2: O corte de P4, e o conserto da frase que o justificava

**Files:**
- Modify: `apps/api/app/modules/bank/reconciliation.py`
- Modify: `apps/api/app/main.py:150-156`
- Test: `apps/api/tests/test_bank_ciclos.py` (criar)

**Interfaces:**
- Produces: `reconciliation.PRIMEIRO_CICLO_MEDIVEL: date`

**Contexto que o implementador precisa:** `TermosDoGate` conta P1+P2 e P3 e **não conta P4**. A justificativa escrita nos dois arquivos — *"o payout só marca a solicitação como sacada"* — descrevia o `wallet.request_payout` de antes da Onda 3 e **está vencida**: o payout agora recusa sem conta principal (409) e escreve a perna bancária na mesma transação. A população continua vazia, por outro mecanismo, e **só a partir do deploy**. Deixar a frase de pé enquanto o corte se apoia nela é a classe §1 da Onda 2 (o documento que afirma sobre a camada de baixo e desliga quem viria conferir).

- [ ] **Step 1: Escreva o teste de piso**

Crie `apps/api/tests/test_bank_ciclos.py`:

```python
"""O ciclo da conferência — a legibilidade, o corte de P4 e o histórico."""
from datetime import date

from app.modules.bank import reconciliation

# A Onda 3 entrou em `main` neste dia (commit 54bb1d4). É um fato do REPOSITÓRIO, ao contrário da
# data do deploy — e é por isso que ele serve de piso.
MERGE_DA_ONDA_3 = date(2026, 8, 10)


def test_primeiro_ciclo_medivel_nao_antecede_a_onda_3():
    """O único valor deste módulo que depende de um fato fora do repositório.

    Cravá-lo cedo demais faz o e1p declarar legível um ciclo cujo termo P4 nunca foi medido — a
    leitura errada que já custou uma decisão de produto neste épico. O piso não prova que a data
    está certa (o deploy não é um fato do repo); ele impede a classe de erro barata.
    """
    assert reconciliation.PRIMEIRO_CICLO_MEDIVEL > MERGE_DA_ONDA_3


def test_primeiro_ciclo_medivel_e_primeiro_dia_do_mes():
    """O corte é por CICLO, não por dia: um mês pela metade medido não é um mês medido."""
    assert reconciliation.PRIMEIRO_CICLO_MEDIVEL.day == 1
```

- [ ] **Step 2: Rode e veja falhar**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_bank_ciclos.py -v`
Expected: FAIL — `AttributeError: module 'app.modules.bank.reconciliation' has no attribute 'PRIMEIRO_CICLO_MEDIVEL'`

- [ ] **Step 3: Declare a constante**

Em `reconciliation.py`, logo abaixo do bloco `TOLERANCE_FLOOR_CENTS`/`TOLERANCE_PCT`:

```python
# ── O corte do termo P4 ───────────────────────────────────────────────────────────────────────
#
# `TermosDoGate` conta P1+P2 e P3 e **não conta P4**. Até a Onda 3 a justificativa era que a
# população é vazia por construção — verdade por um mecanismo que **não existe mais**:
# `request_payout` marcava a solicitação como sacada sem tocar em conta real. Hoje ela continua
# vazia por outro mecanismo (409 sem conta principal + a perna bancária escrita na MESMA transação)
# e **só a partir do deploy da Onda 3**.
#
# Numa janela anterior existem saques sem perna bancária que ninguém conta, e o relatório os reporta
# como zero **por omissão**. *"Zero por ausência de medição não é zero"* é a frase que o próprio
# `_probe_termos_do_gate` usa para se RECUSAR a devolver zeros; um ciclo declarado legível sobre uma
# janela dessas seria a mesma leitura errada que já custou uma decisão de produto neste épico.
#
# ⚠️ **É o único valor deste arquivo que depende de um fato FORA do repositório** — a data em que a
# Onda 3 subiu para produção — e ele erra em silêncio, para o lado caro. Mesma forma de
# `CORTE_AUTORIA` (`vima/absences.py`): data cravada, motivo escrito ao lado, e um teste de piso
# contra a data do merge, que é um fato do repositório. **Ao mover esta data, mova o piso junto** e
# diga por quê.
PRIMEIRO_CICLO_MEDIVEL = date(2026, 9, 1)
```

- [ ] **Step 4: Conserte a frase vencida em `ConferenciaReport`**

Na docstring de `ConferenciaReport`, substitua o parágrafo que começa com `**P4 é declarado e NÃO é contado**` por:

```
    **P4 é declarado e NÃO é contado**, e a razão mudou com a Onda 3. Até ela, a população era vazia
    porque o payout só marcava a solicitação como sacada — nenhum dinheiro saía de conta real.
    Agora ela é vazia **por construção nova**: `wallet.request_payout` recusa sem conta principal
    (409) e `bank/payout.py` escreve a perna bancária na MESMA transação. Contá-la aqui continua
    exigindo alcançar o plano da plataforma a partir deste módulo, proibido pela Regra dos Planos,
    em troca de um contador sobre conjunto vazio.

    ⚠️ **A vacuidade só vale a partir do deploy da Onda 3.** Numa janela anterior existem saques sem
    perna bancária que ninguém conta, e este relatório os reporta como zero **por omissão**. Quem
    decide se uma janela é medível é `PRIMEIRO_CICLO_MEDIVEL`, no topo deste módulo — não presuma
    zero fora dele.
```

Faça a mesma correção no comentário de `TermosDoGate` (o parágrafo `P4 **não** entra: população vazia por construção hoje...`), apontando para a constante.

- [ ] **Step 5: Conserte o comentário em `main.py`**

Em `apps/api/app/main.py`, linhas ~154-156, substitua *"**P4 não é contado**: a população é vazia por construção (o payout ainda não move dinheiro de conta real)"* por:

```python
# **P4 não é contado**: desde a Onda 3 a população é vazia por construção — o payout recusa sem
# conta principal e escreve a perna bancária na mesma transação (`bank/payout.py`). A frase antiga
# ("o payout ainda não move dinheiro de conta real") descrevia o `request_payout` de antes e ficou
# falsa no merge da Onda 3. A vacuidade só vale a partir do deploy dela: ver
# `bank.reconciliation.PRIMEIRO_CICLO_MEDIVEL`.
```

- [ ] **Step 6: Rode e veja passar**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_bank_ciclos.py tests/test_payout_registrar.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add apps/api/app/modules/bank/reconciliation.py apps/api/app/main.py apps/api/tests/test_bank_ciclos.py
git commit -m "fix: a justificativa de P4 descrevia o payout de antes da Onda 3 [Epic 8]"
```

---

### Task 3: `CicloDaConferencia` e a legibilidade

**Files:**
- Modify: `apps/api/app/modules/bank/reconciliation.py`
- Test: `apps/api/tests/test_bank_ciclos.py`

**Interfaces:**
- Consumes: `reconciliation_report`, `PRIMEIRO_CICLO_MEDIVEL`, `service.list_accounts`, `_today`.
- Produces: `reconciliation.CicloDaConferencia` (dataclass frozen, campos exatos abaixo), `reconciliation.ciclos_da_conferencia(db, *, today: date | None = None) -> list[CicloDaConferencia]`, `reconciliation.MESES_DO_HISTORICO: int`.

- [ ] **Step 1: Escreva os testes que falham — as quatro condições e a precedência**

Acrescente a `apps/api/tests/test_bank_ciclos.py`. Reuse os helpers de `test_bank_reconciliation_report.py` (importe-os ou replique o mínimo — **não** monte um segundo conjunto de fixtures divergente).

```python
def test_sem_conta_ativa_o_historico_sai_vazio(db):
    """Condição (a). Sem conta, `contas == []`, `contas_sem_checkpoint == 0` e os contadores dão
    zero: as condições (b) e (c) passariam POR VACUIDADE e o e1p diria legível sobre nada."""
    assert reconciliation.ciclos_da_conferencia(db, today=date(2026, 10, 5)) == []


def test_ciclo_em_curso_nunca_e_legivel(db, conta):
    ciclos = reconciliation.ciclos_da_conferencia(db, today=date(2026, 10, 15))
    corrente = [c for c in ciclos if c.ano_mes == "2026-10"][0]
    assert corrente.fechado is False
    assert corrente.legivel is False


def test_ciclo_legivel_quando_tudo_bate(db, conta):
    """O membro. Conta ativa, saldo declarado num dia posterior à abertura, termos zerados,
    janela posterior ao corte."""
    _checkpoint(db, conta, reference_date=date(2026, 9, 30), balance_cents=250_000)
    _movimento(db, conta, posted_at=date(2026, 9, 10), amount_cents=250_000)

    ciclos = reconciliation.ciclos_da_conferencia(db, today=date(2026, 10, 5))
    setembro = [c for c in ciclos if c.ano_mes == "2026-09"][0]

    assert setembro.fechado is True
    assert setembro.legivel is True
    assert setembro.motivo_nao_legivel is None
    assert setembro.movimentos_no_periodo == 1
    assert setembro.valor_movimentado_cents == 250_000


def test_ciclo_dormente_e_legivel_com_denominador_zero(db, conta):
    """O mês sem movimento NÃO é recusado — o volume zerado é que se lê sozinho.

    Recusá-lo esconderia o número em vez de qualificá-lo, o inverso do princípio da Onda 0.
    """
    _checkpoint(db, conta, reference_date=date(2026, 9, 30), balance_cents=0)

    setembro = [
        c for c in reconciliation.ciclos_da_conferencia(db, today=date(2026, 10, 5))
        if c.ano_mes == "2026-09"
    ][0]

    assert setembro.legivel is True
    assert setembro.movimentos_no_periodo == 0
    assert setembro.valor_movimentado_cents == 0


def test_conta_sem_saldo_declarado_nomeia_a_conta(db, conta):
    """Condição (b), e o motivo NOMEIA — um motivo genérico manda o dono procurar o que já se
    sabe qual é."""
    setembro = [
        c for c in reconciliation.ciclos_da_conferencia(db, today=date(2026, 10, 5))
        if c.ano_mes == "2026-09"
    ][0]

    assert setembro.legivel is False
    assert conta.name in setembro.motivo_nao_legivel


def test_janela_anterior_ao_corte_nao_e_legivel(db, conta):
    """Condição (d). Julho tem P4 não medido, e o relatório o reporta como zero por omissão."""
    _checkpoint(db, conta, reference_date=date(2026, 7, 31), balance_cents=100_000)

    julho = [
        c for c in reconciliation.ciclos_da_conferencia(db, today=date(2026, 10, 5))
        if c.ano_mes == "2026-07"
    ]
    # Só aparece se a conta existia em julho; se não aparecer, a fixture abriu a conta depois —
    # ajuste `opening_date` da fixture em vez de afrouxar a asserção.
    assert julho and julho[0].legivel is False
    assert "saque" in julho[0].motivo_nao_legivel.lower()


def test_precedencia_do_motivo_corte_antes_de_saldo(db, conta):
    """Quando (d) e (b) falham juntas, a frase é a de (d).

    Dizer "falta o saldo" sobre um mês anterior ao corte mandaria o dono a um ato que não resolve
    aquele mês — a ordem é por acionabilidade, não por gosto.
    """
    julho = [
        c for c in reconciliation.ciclos_da_conferencia(db, today=date(2026, 10, 5))
        if c.ano_mes == "2026-07"
    ][0]
    assert "saque" in julho.motivo_nao_legivel.lower()
    assert conta.name not in julho.motivo_nao_legivel


def test_historico_tem_teto_de_seis_meses(db, conta_aberta_em_2025):
    ciclos = reconciliation.ciclos_da_conferencia(db, today=date(2026, 10, 5))
    assert len(ciclos) <= reconciliation.MESES_DO_HISTORICO
```

- [ ] **Step 2: Rode e veja falhar**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_bank_ciclos.py -v`
Expected: FAIL — `AttributeError: ... has no attribute 'ciclos_da_conferencia'`

- [ ] **Step 3: Declare o dataclass e o teto**

No bloco "O contrato de saída" de `reconciliation.py`, depois de `ConferenciaReport`:

```python
# Teto de EXIBIÇÃO do histórico, não regra de decisão. É o dobro da janela de observação que o PRD
# sugere — e o PRD marca aquele "3 ciclos" como `[SUPOSIÇÃO DO @PM]`, explicitamente *"não vem do
# design nem da pesquisa"*. Transformá-lo em constante de produto seria codificar suposição
# (Artigo IV). Seis meses é o bastante para o dono enxergar estabilidade e decidir sozinho.
MESES_DO_HISTORICO = 6


@dataclass(frozen=True)
class CicloDaConferencia:
    """UM mês de conferência, e se o número dele pode ser lido.

    **Um ciclo é um mês de calendário no fuso do tenant**, e não uma janela livre — embora
    `reconciliation_report` aceite qualquer `start`/`end`. Fronteira escolhível permitiria
    selecionar a janela que produz o número desejado: a régua andando junto com o que ela mede, que
    é exatamente o que a banda fixa da Regra 7 existe para impedir.

    `legivel` é `True` quando as quatro condições valem **e** o ciclo está fechado:

    | | Condição | Membro | Não-membro |
    |---|---|---|---|
    | a | há conta ativa | tenant com o Itaú PJ | tenant sem conta nenhuma |
    | b | toda conta avaliada | as 3 com saldo declarado no mês | a Poupança BB sem saldo no mês |
    | c | P1+P2 e P3 zerados | mês em que toda baixa informou a conta | baixa legada sem conta |
    | d | `start >= PRIMEIRO_CICLO_MEDIVEL` | setembro/2026 | julho/2026 |

    ⚠️ **(a) não é redundante com (b).** Sem conta, `contas == []`, `contas_sem_checkpoint == 0` e os
    contadores dão zero: (b) e (c) passariam **por vacuidade**. É a mesma família do 🟢 sobre razão
    vazio que a Story 8.20 desfez.

    ⚠️ **O volume NÃO entra no predicado.** Um mínimo de N movimentos seria um número inventado
    (Artigo IV), e recusar a janela **esconde** o número dela em vez de qualificá-lo — o inverso do
    princípio da Onda 0 (*suprimir a afirmação, nunca o número*). O ciclo dormente sai legível, com
    denominador zero à vista, e o zero se lê sozinho.

    `motivo_nao_legivel` traz UMA frase, nunca uma lista: uma enumeração de motivos aqui
    reconstruiria o ruído que a Regra 7 existe para evitar. A precedência é `(d) → (a) → (b) → (c)`,
    por **acionabilidade** — (d) e (a) não têm ação possível naquele mês, e (b) é um ato por conta
    enquanto (c) é um ato por lançamento.

    **ANOTA, NUNCA SUBTRAI:** nada aqui altera a divergência. `total_divergencia_cents` é copiado do
    relatório do mês, sem recálculo.
    """

    ano_mes: str  # "2026-09"
    start: date
    end: date
    fechado: bool
    legivel: bool
    motivo_nao_legivel: str | None
    total_divergencia_cents: int | None
    contas_avaliadas: int
    contas_sem_checkpoint: int
    movimentos_no_periodo: int
    valor_movimentado_cents: int
```

- [ ] **Step 4: Escreva os helpers de mês e a avaliação**

No fim do arquivo:

```python
def _fim_do_mes(d: date) -> date:
    """Último dia do mês de `d`. Sem `calendar.monthrange` para não importar por três linhas."""
    proximo = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return proximo - timedelta(days=1)


def _mes_anterior(primeiro_dia: date) -> date:
    return (primeiro_dia - timedelta(days=1)).replace(day=1)


def _motivo_nao_legivel(
    report: ConferenciaReport, *, start: date, tem_conta: bool
) -> str | None:
    """A frase única, na precedência `(d) → (a) → (b) → (c)`. `None` = legível.

    Ver a tabela na docstring de `CicloDaConferencia`. A ordem é por **acionabilidade**: mandar o
    dono declarar um saldo de um mês anterior ao corte é mandá-lo a um ato que não resolve aquele
    mês. E o vocabulário é o do UX-001 — esta frase fala do lado *"o que o banco diz"*; a string
    `"no banco"` pertence à parcela da Projeção e não entra aqui, nem sinônimo locacional.
    """
    if start < PRIMEIRO_CICLO_MEDIVEL:
        return (
            "Neste período o saque da Carteira ainda não escrevia movimento bancário, então o e1p "
            "não mediu esse pedaço — o número deste mês não serve para comparar."
        )
    if not tem_conta:
        return "Você ainda não tinha conta bancária cadastrada neste período."
    sem_saldo = [c.bank_account_name for c in report.contas if c.divergencia_cents is None]
    if sem_saldo:
        nomes = ", ".join(sem_saldo)
        plural = "s" if len(sem_saldo) > 1 else ""
        return (
            f"Faltou o saldo informado d{'as' if len(sem_saldo) > 1 else 'a'} conta{plural} "
            f"{nomes} neste mês — sem ele o e1p não consegue conferir o mês inteiro."
        )
    if report.lancamentos_sem_conta_informada:
        return (
            f"{report.lancamentos_sem_conta_informada} lançamento(s) deste mês não dizem de qual "
            "conta saíram ou entraram."
        )
    if report.rendimentos_sem_perna_bancaria:
        return (
            f"{report.rendimentos_sem_perna_bancaria} rendimento(s) de aplicação deste mês ainda "
            "não geram movimento bancário."
        )
    return None


def ciclos_da_conferencia(
    db: Session, *, today: date | None = None
) -> list[CicloDaConferencia]:
    """O histórico de ciclos, **derivado na leitura**. Read-only, sem migration, sem escrita.

    Roda `reconciliation_report` uma vez por mês, do mês da conta ativa mais antiga até o mês
    corrente, com teto de `MESES_DO_HISTORICO`. Do mais recente para o mais antigo.

    **A alternativa persistida foi rejeitada por motivo concreto, não por pureza:** um lançamento
    retroativo muda legitimamente a leitura de um ciclo passado, e um valor congelado passaria a
    discordar do recalculado — segunda verdade sobre a mesma divergência, a forma exata do bug que a
    Onda 0 desfez. É também a Regra 3 do Epic 5 (*análise não escreve*).

    **Sem conta ativa devolve `[]`**, e não um ciclo corrente de conteúdo nulo: um ciclo montado
    sobre zero conta seria a condição (a) violada pela porta dos fundos, na camada de exibição.

    ⚠️ **Conta arquivada some do histórico** (`service.list_accounts` a esconde), então arquivar uma
    conta hoje muda a leitura de um mês passado. É o preço aceito de não congelar um número que pode
    legitimamente mudar — está registrado como risco na spec.
    """
    hoje = today or _today(db)
    accounts = service.list_accounts(db)
    if not accounts:
        return []

    mes_da_conta_mais_antiga = min(a.opening_date for a in accounts).replace(day=1)
    # Anda para trás a partir do mês corrente, no máximo `MESES_DO_HISTORICO`, e nunca antes do mês
    # em que a primeira conta foi cadastrada — antes disso não havia o que conferir.
    inicios: list[date] = []
    cursor = hoje.replace(day=1)
    while len(inicios) < MESES_DO_HISTORICO and cursor >= mes_da_conta_mais_antiga:
        inicios.append(cursor)
        cursor = _mes_anterior(cursor)

    ciclos: list[CicloDaConferencia] = []
    for start in inicios:
        end = _fim_do_mes(start)
        report = reconciliation_report(db, start=start, end=end, today=hoje)
        # A conta precisa ter EXISTIDO no mês: uma conta cadastrada em 03/10 não deve fazer o e1p
        # dizer nada sobre setembro.
        tem_conta = any(a.opening_date <= end for a in accounts)
        fechado = end < hoje
        motivo = _motivo_nao_legivel(report, start=start, tem_conta=tem_conta)
        ciclos.append(
            CicloDaConferencia(
                ano_mes=f"{start.year:04d}-{start.month:02d}",
                start=start,
                end=end,
                fechado=fechado,
                # Ciclo em curso NUNCA é legível: um mês pela metade não tem o que declarar, e um
                # `True` provisório que vira `False` amanhã é pior que um `False` honesto.
                legivel=fechado and motivo is None,
                motivo_nao_legivel=motivo,
                total_divergencia_cents=report.total_divergencia_cents,
                contas_avaliadas=report.contas_avaliadas,
                contas_sem_checkpoint=report.contas_sem_checkpoint,
                movimentos_no_periodo=sum(c.movimentos_no_periodo for c in report.contas),
                valor_movimentado_cents=sum(c.valor_movimentado_cents for c in report.contas),
            )
        )
    return ciclos
```

Acrescente `timedelta` ao import de `datetime` no topo do arquivo.

- [ ] **Step 5: Rode e veja passar**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_bank_ciclos.py -v`
Expected: PASS. Se algum teste falhar por causa de `opening_date` da fixture, ajuste a **fixture** (com a docstring dizendo por que a data foi escolhida), nunca a asserção — a lição de `test_checkpoint_na_borda_do_start_serve`.

- [ ] **Step 6: Rode a suíte inteira do backend**

Run: `cd apps/api && .venv/Scripts/python -m pytest -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add apps/api/app/modules/bank/reconciliation.py apps/api/tests/test_bank_ciclos.py
git commit -m "feat: o ciclo da conferencia sabe dizer se o mes pode ser lido [Epic 8]"
```

---

### Task 4: Schemas e a rota

**Files:**
- Modify: `apps/api/app/modules/bank/schemas.py`, `apps/api/app/modules/bank/router.py`
- Test: `apps/api/tests/test_bank_ciclos.py`

**Interfaces:**
- Consumes: `reconciliation.CicloDaConferencia`, `reconciliation.ciclos_da_conferencia`.
- Produces: `GET /bank/reconciliation-cycles` → `CiclosDaConferenciaOut { ciclos: list[CicloDaConferenciaOut] }`.

- [ ] **Step 1: Escreva o teste de rota que falha**

```python
def test_rota_de_ciclos_devolve_o_historico(client, auth_headers, conta):
    r = client.get("/bank/reconciliation-cycles", headers=auth_headers)
    assert r.status_code == 200
    corpo = r.json()
    assert "ciclos" in corpo
    assert all("ano_mes" in c and "legivel" in c for c in corpo["ciclos"])


def test_rota_de_ciclos_sem_conta_devolve_lista_vazia(client, auth_headers):
    r = client.get("/bank/reconciliation-cycles", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["ciclos"] == []
```

Use os helpers reais de cliente/auth do arquivo `test_bank_reconciliation_report.py`.

- [ ] **Step 2: Rode e veja falhar**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_bank_ciclos.py -k rota -v`
Expected: FAIL — 404

- [ ] **Step 3: Acrescente os dois campos a `ConferenciaContaOut`**

Em `schemas.py`, depois de `movimentos_ignorados`:

```python
    # Quanto se moveu nesta janela, nesta conta — o denominador da divergência. Existe para que o
    # número nunca seja lido sem o volume que o produziu.
    movimentos_no_periodo: int = 0
    valor_movimentado_cents: int = 0
```

E no mapper `_conferencia_conta_out` de `router.py`:

```python
        movimentos_no_periodo=c.movimentos_no_periodo,
        valor_movimentado_cents=c.valor_movimentado_cents,
```

- [ ] **Step 4: Escreva os schemas do ciclo**

Em `schemas.py`, depois de `ConferenciaReportOut`:

```python
class CicloDaConferenciaOut(BaseModel):
    """UM mês de conferência, e se o número dele pode ser lido.

    `legivel` é `False` para todo ciclo em curso, sem exceção. `motivo_nao_legivel` traz **uma**
    frase pronta, do backend — uma redação, um lugar: duas redações do mesmo fato viram duas frases
    diferentes na tela conforme o caminho.

    `movimentos_no_periodo` e `valor_movimentado_cents` são o **denominador**: a tela não pode
    exibir `total_divergencia_cents` sem eles. Um mês com divergência zero e volume zero não prova
    nada, e é o volume que diz isso.
    """

    ano_mes: str
    start: date
    end: date
    fechado: bool
    legivel: bool
    motivo_nao_legivel: str | None
    total_divergencia_cents: int | None
    contas_avaliadas: int
    contas_sem_checkpoint: int
    movimentos_no_periodo: int
    valor_movimentado_cents: int


class CiclosDaConferenciaOut(BaseModel):
    """Resposta de `GET /bank/reconciliation-cycles`. Do mais recente para o mais antigo.

    Envelope com um campo em vez de lista nua: uma lista no topo do corpo não tem para onde crescer
    sem virar mudança quebradora de contrato.
    """

    ciclos: list[CicloDaConferenciaOut]
```

- [ ] **Step 5: Escreva a rota**

Em `router.py`, depois de `reconciliation_report`:

```python
@router.get("/reconciliation-cycles", response_model=CiclosDaConferenciaOut)
def reconciliation_cycles(
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> CiclosDaConferenciaOut:
    """*"Este número já vale?"* — um mês por linha, com o volume que produziu cada um. READ-ONLY.

    Sem parâmetro de período **de propósito**: o ciclo é o mês de calendário no fuso do tenant, e
    fronteira escolhível permitiria selecionar a janela que produz o número desejado — a régua
    andando junto com o que ela mede.

    **Derivado na leitura, nunca gravado.** Roda o relatório de conferência uma vez por mês. Um
    lançamento retroativo muda legitimamente a leitura de um ciclo passado; um valor congelado
    passaria a discordar do recalculado.

    Sem conta bancária cadastrada, `ciclos` vem **vazio** — não com um ciclo corrente de conteúdo
    nulo.
    """
    return CiclosDaConferenciaOut(
        ciclos=[
            CicloDaConferenciaOut(
                ano_mes=c.ano_mes,
                start=c.start,
                end=c.end,
                fechado=c.fechado,
                legivel=c.legivel,
                motivo_nao_legivel=c.motivo_nao_legivel,
                total_divergencia_cents=c.total_divergencia_cents,
                contas_avaliadas=c.contas_avaliadas,
                contas_sem_checkpoint=c.contas_sem_checkpoint,
                movimentos_no_periodo=c.movimentos_no_periodo,
                valor_movimentado_cents=c.valor_movimentado_cents,
            )
            for c in reconciliation.ciclos_da_conferencia(db)
        ]
    )
```

Acrescente `CiclosDaConferenciaOut` e `CicloDaConferenciaOut` ao import de schemas no topo de `router.py`.

- [ ] **Step 6: Rode e veja passar**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_bank_ciclos.py tests/test_tenancy_guard.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add apps/api/app/modules/bank/schemas.py apps/api/app/modules/bank/router.py apps/api/tests/test_bank_ciclos.py
git commit -m "feat: GET /bank/reconciliation-cycles serve o historico de ciclos [Epic 8]"
```

---

### Task 5: A frase do ciclo (frontend puro)

**Files:**
- Modify: `apps/web/src/features/financeiro/conferencia.ts`
- Test: `apps/web/src/features/financeiro/conferencia.test.ts`

**Interfaces:**
- Produces: `CicloDaConferencia` (interface TS, espelho exato do schema da Task 4), `fraseDoCiclo(c: CicloDaConferencia): string`.
- Consumes: `formatDateBR` (de `./contas`), `formatBRL` (de `./dre`) — já importados no arquivo.

- [ ] **Step 1: Escreva os testes que falham**

Em `conferencia.test.ts`:

```ts
const CICLO_BASE: CicloDaConferencia = {
  ano_mes: "2026-09",
  start: "2026-09-01",
  end: "2026-09-30",
  fechado: true,
  legivel: true,
  motivo_nao_legivel: null,
  total_divergencia_cents: 3_700,
  contas_avaliadas: 3,
  contas_sem_checkpoint: 0,
  movimentos_no_periodo: 14,
  valor_movimentado_cents: 1_840_200,
};

describe("fraseDoCiclo", () => {
  it("ciclo em curso diz quando fecha, e não afirma nada sobre o mês", () => {
    const f = fraseDoCiclo({ ...CICLO_BASE, fechado: false, legivel: false });
    expect(f).toContain("30/09/2026");
    expect(f).not.toContain("conferido");
  });

  it("ciclo legível traz o volume junto do número", () => {
    const f = fraseDoCiclo(CICLO_BASE);
    expect(f).toContain("14");
    expect(f).toContain("R$ 18.402,00");
  });

  it("mês dormente mostra o zero, e o zero aparece por extenso", () => {
    const f = fraseDoCiclo({
      ...CICLO_BASE,
      movimentos_no_periodo: 0,
      valor_movimentado_cents: 0,
      total_divergencia_cents: 0,
    });
    // O denominador zerado é a informação. Ele não pode ser omitido só porque é zero.
    expect(f).toContain("nenhum movimento");
  });

  it("ciclo não legível repete o motivo do backend, sem reescrevê-lo", () => {
    const motivo = "Faltou o saldo informado da conta Poupança BB neste mês — sem ele o e1p não consegue conferir o mês inteiro.";
    expect(fraseDoCiclo({ ...CICLO_BASE, legivel: false, motivo_nao_legivel: motivo })).toContain(motivo);
  });

  it("nunca usa o rótulo da Projeção", () => {
    // UX-001: "no banco" nomeia o saldo que o e1p CALCULOU, na outra tela. Aqui seria a ponta
    // oposta da mesma subtração.
    for (const c of [CICLO_BASE, { ...CICLO_BASE, fechado: false, legivel: false }]) {
      expect(fraseDoCiclo(c)).not.toContain("no banco");
    }
  });

  it("nunca usa o vocabulário do épico", () => {
    for (const termo of ["legív", "gate", "Onda", "métrica"]) {
      expect(fraseDoCiclo(CICLO_BASE)).not.toContain(termo);
    }
  });
});
```

- [ ] **Step 2: Rode e veja falhar**

Run: `cd apps/web && pnpm vitest run src/features/financeiro/conferencia.test.ts`
Expected: FAIL — `fraseDoCiclo is not defined`

- [ ] **Step 3: Escreva o tipo e a função**

Em `conferencia.ts`, depois de `ConferenciaReport`:

```ts
/**
 * UM mês de conferência — espelho de `CicloDaConferenciaOut` (`bank/schemas.py`).
 *
 * `legivel` responde *"este número já vale?"*, que é uma pergunta diferente de *"está batendo?"*.
 * `motivo_nao_legivel` vem **pronto do backend**: uma redação, um lugar — reescrevê-lo aqui criaria
 * duas frases para o mesmo fato conforme o caminho.
 *
 * ⚠️ `movimentos_no_periodo` e `valor_movimentado_cents` são o **denominador**, e a tela não pode
 * exibir `total_divergencia_cents` sem eles: um mês com divergência zero e volume zero não prova
 * nada, e é o volume que diz isso em voz alta.
 */
export interface CicloDaConferencia {
  ano_mes: string;
  start: string;
  end: string;
  fechado: boolean;
  legivel: boolean;
  motivo_nao_legivel: string | null;
  total_divergencia_cents: number | null;
  contas_avaliadas: number;
  contas_sem_checkpoint: number;
  movimentos_no_periodo: number;
  valor_movimentado_cents: number;
}

/**
 * A frase que enquadra tudo que vem depois dela na tela.
 *
 * **Pura e testada, nunca montada dentro do `.tsx`** — mesmo motivo de `fraseConferencia`.
 *
 * ⚠️ **A palavra "legível" não aparece aqui.** É termo de domínio (código, docstring, `CLAUDE.md`);
 * na tela é frase. E não é preciosismo: `completo` colidiria com a *completude* do Diagnóstico e
 * `comparável` já está tomado no nível da conta pela Story 8.20 ("declarado, porém não comparável").
 * A divergência D-6/UX-001 já foi paga duas vezes para separar sentidos que dividiam uma palavra.
 *
 * ⚠️ **O volume sai SEMPRE, inclusive zero.** Omiti-lo quando é zero apagaria exatamente a
 * informação que ele existe para dar: um mês em que nada aconteceu não prova que os lançamentos
 * estão completos.
 */
export function fraseDoCiclo(c: CicloDaConferencia): string {
  const mes = mesPorExtenso(c.ano_mes);
  if (!c.fechado) {
    return (
      `Este ciclo fecha em ${formatDateBR(c.end)}. ` +
      `Até lá, o e1p ainda não tem como conferir ${mes} por inteiro.`
    );
  }
  const volume =
    c.movimentos_no_periodo === 0
      ? "nenhum movimento no período"
      : `${c.movimentos_no_periodo} movimento${c.movimentos_no_periodo > 1 ? "s" : ""}, ` +
        `${formatBRL(c.valor_movimentado_cents)} movimentados`;
  if (!c.legivel) {
    return `${mesCapitalizado(mes)} fechou sem o e1p conseguir conferir o mês inteiro. ` +
      `${c.motivo_nao_legivel ?? ""} (${volume})`.trimEnd();
  }
  return (
    `${mesCapitalizado(mes)} fechou conferido: ` +
    `${c.contas_avaliadas} conta${c.contas_avaliadas > 1 ? "s" : ""}, ${volume}.`
  );
}

const MESES = [
  "janeiro", "fevereiro", "março", "abril", "maio", "junho",
  "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
];

/**
 * `"2026-09"` → `"setembro"`. **Puramente textual — nunca constrói `Date`.**
 *
 * `new Date("2026-09")` leria UTC e, em UTC−3, um mês de calendário viraria o mês anterior na
 * virada. É a mesma disciplina de `formatDay` em `lib/datetime.ts`, e a lição do saque do dia 9
 * aparecendo como dia 8 na Onda 3.
 */
function mesPorExtenso(anoMes: string): string {
  const [, mm] = anoMes.split("-");
  return MESES[Number(mm) - 1] ?? anoMes;
}

function mesCapitalizado(mes: string): string {
  return mes.charAt(0).toUpperCase() + mes.slice(1);
}
```

- [ ] **Step 4: Rode e veja passar**

Run: `cd apps/web && pnpm vitest run src/features/financeiro/conferencia.test.ts`
Expected: PASS

- [ ] **Step 5: Rode o typecheck**

Run: `cd apps/web && pnpm tsc --noEmit`
Expected: sem erros

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/features/financeiro/conferencia.ts apps/web/src/features/financeiro/conferencia.test.ts
git commit -m "feat: a frase do ciclo, pura e testada [Epic 8]"
```

---

### Task 6: `CicloCard` e o histórico na tela

**Files:**
- Modify: `apps/web/src/features/financeiro/ConferenciaPage.tsx`
- Test: `apps/web/src/features/financeiro/ConferenciaPage.test.tsx`

**Interfaces:**
- Consumes: `CicloDaConferencia`, `fraseDoCiclo` (Task 5); `GET /bank/reconciliation-cycles` (Task 4).

- [ ] **Step 1: Escreva os testes que falham**

Em `ConferenciaPage.test.tsx` (siga o padrão de mock de `api` já usado no arquivo; a tela passa a fazer **duas** chamadas — `/bank/reconciliation-report` e `/bank/reconciliation-cycles`):

```tsx
it("a qualificação do ciclo aparece ANTES das frases por conta", async () => {
  render(<ConferenciaPage />);
  const ciclo = await screen.findByTestId("ciclo-card");
  const primeiraFrase = screen.getAllByTestId("frase-conta")[0];
  // `Node.DOCUMENT_POSITION_FOLLOWING` = a frase vem DEPOIS do card.
  expect(ciclo.compareDocumentPosition(primeiraFrase) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});

it("o histórico de ciclos é lista, nunca tabela", async () => {
  render(<ConferenciaPage />);
  const historico = await screen.findByTestId("historico-de-ciclos");
  // ⚠️ ESCOPADO: a página tem um `<table>` legítimo (`TabelaContas`), e a asserção sobre a página
  // inteira falharia no caminho normal. A lição da 2b-ii: em 360px uma tabela de 3 colunas não
  // cabe, e a saída não é rolar melhor, é não precisar.
  expect(within(historico).queryByRole("table")).toBeNull();
  expect(within(historico).getByRole("list")).toBeTruthy();
});

it("controle positivo: a asserção acima ENXERGA uma tabela quando existe uma ali dentro", () => {
  render(
    <div data-testid="historico-de-ciclos">
      <table><tbody><tr><td>x</td></tr></tbody></table>
    </div>,
  );
  // Sem este teste, um seletor que deixasse de casar tornaria o gate vacuamente verde — a lição do
  // gate por `import.meta.glob` da 2b-ii.
  expect(within(screen.getByTestId("historico-de-ciclos")).queryByRole("table")).not.toBeNull();
});

it("o volume aparece mesmo quando é zero", async () => {
  // mock: um ciclo fechado, legível, com zero movimento.
  render(<ConferenciaPage />);
  expect(await screen.findByText(/nenhum movimento no período/)).toBeTruthy();
});

it("sem conta cadastrada, não renderiza ciclo nenhum", async () => {
  // mock: `ciclos: []` e `contas: []`
  render(<ConferenciaPage />);
  await screen.findByText(/ainda não tem conta bancária cadastrada/);
  expect(screen.queryByTestId("ciclo-card")).toBeNull();
});
```

Acrescente `data-testid="frase-conta"` ao `<li>`/contêiner do `FraseCard` existente.

- [ ] **Step 2: Rode e veja falhar**

Run: `cd apps/web && pnpm vitest run src/features/financeiro/ConferenciaPage.test.tsx`
Expected: FAIL — `Unable to find an element by: [data-testid="ciclo-card"]`

- [ ] **Step 3: Busque os ciclos na página**

Em `ConferenciaPage`, acrescente estado e uma segunda chamada dentro de `load` (ou num `useEffect` próprio — os ciclos **não** dependem de `range` nem de `accountId`, então um efeito separado sem dependências é mais honesto):

```tsx
  const [ciclos, setCiclos] = useState<CicloDaConferencia[]>([]);

  // Os ciclos NÃO dependem do `PeriodPicker`: o ciclo é o mês de calendário, e a janela que o dono
  // escolheu ali responde outra pergunta. Efeito próprio, sem `range` nas dependências.
  useEffect(() => {
    api
      .get<{ ciclos: CicloDaConferencia[] }>("/bank/reconciliation-cycles")
      .then((res) => setCiclos(Array.isArray(res.data?.ciclos) ? res.data.ciclos : []))
      // Painel lateral nunca derruba quem o hospeda: degrada para vazio, sem estourar. (A lição do
      // `ClientTimeline` — e `Array.isArray` é o guard certo, não `?? []`.)
      .catch(() => setCiclos([]));
  }, []);
```

- [ ] **Step 4: Escreva os dois componentes**

```tsx
/**
 * A qualificação do número, ACIMA das frases por conta.
 *
 * ⚠️ **Acima, e não abaixo.** `fraseConferencia` é por CONTA, e a tela tem um `PeriodPicker` de
 * intervalo livre: pendurar isto embaixo das frases faria parecer que qualifica aquelas frases, que
 * são de outro período. Acima, ela **enquadra** o que vem depois — a mesma disciplina de "a frase
 * vem antes da tabela", um nível acima.
 */
function CicloCard({ ciclo }: { ciclo: CicloDaConferencia }) {
  return (
    <div data-testid="ciclo-card" className="rounded-2xl bg-white p-4 shadow-sm">
      <p className="text-sm text-neutral-700">{fraseDoCiclo(ciclo)}</p>
    </div>
  );
}

/**
 * Os ciclos fechados, um por linha. `<ul>`, **nunca `<table>`** — em 360px uma tabela de 3 colunas
 * não cabe, e a saída não é fazer a rolagem funcionar melhor, é não precisar dela (lição da 2b-ii).
 *
 * O volume sai em toda linha, inclusive zero: um mês em que nada aconteceu tem divergência zero e
 * não prova nada, e é o volume que diz isso.
 */
function HistoricoDeCiclos({ ciclos }: { ciclos: CicloDaConferencia[] }) {
  const fechados = ciclos.filter((c) => c.fechado);
  if (fechados.length === 0) {
    return (
      <p data-testid="historico-de-ciclos" className="text-xs text-neutral-400">
        Nenhum mês fechado ainda — o primeiro fecha no fim deste mês.
      </p>
    );
  }
  return (
    <div data-testid="historico-de-ciclos" className="space-y-2">
      <h2 className="text-sm font-semibold text-neutral-700">Mês a mês</h2>
      <ul className="space-y-2">
        {fechados.map((c) => (
          <li key={c.ano_mes} className="rounded-xl bg-white p-3 text-sm shadow-sm">
            <p className="min-w-0 text-neutral-700">{fraseDoCiclo(c)}</p>
            {c.legivel && c.total_divergencia_cents !== null && (
              <p className="mt-1 whitespace-nowrap text-neutral-500">
                Diferença de {formatBRL(Math.abs(c.total_divergencia_cents))}
              </p>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
```

- [ ] **Step 5: Ligue os dois no JSX**

Dentro do bloco `{report && report.contas.length > 0 && (<>...`:

- `{ciclos.length > 0 && <CicloCard ciclo={ciclos[0]} />}` **antes** do `<ul>` das frases;
- `<HistoricoDeCiclos ciclos={ciclos} />` **depois** de `<TabelaContas ... />` e antes do bloco de `report.notes`.

`ciclos[0]` é o mês corrente (a lista vem do mais recente para o mais antigo).

- [ ] **Step 6: Rode e veja passar**

Run: `cd apps/web && pnpm vitest run src/features/financeiro/ && pnpm tsc --noEmit`
Expected: PASS, sem erros de tipo

- [ ] **Step 7: Commit**

```bash
git add apps/web/src/features/financeiro/ConferenciaPage.tsx apps/web/src/features/financeiro/ConferenciaPage.test.tsx
git commit -m "feat: a Conferencia mostra em que ponto do ciclo o dono esta [Epic 8]"
```

---

### Task 7: A Ausência do Vima — o saldo do mês

**Files:**
- Modify: `apps/api/app/modules/vima/absences.py`
- Test: `apps/api/tests/test_vima_absences.py`

**Interfaces:**
- Consumes: `bank.service.list_accounts`, `bank.models.BankBalanceCheckpoint`.
- Produces: `Ausencia(module="financeiro", kind="financeiro.conferencia.saldo_do_mes", subject_type="bank_account", subject_id=f"{account.id}:{YYYY-MM}")`.

**Restrições:** nenhuma chave nova em `LIMIARES_PADRAO` (senão `test_todo_limiar_tem_pergunta` exige a 8ª pergunta de Calibração, que seria um número sem evidência — Artigo IV). Nada de relógio dentro do módulo: `hoje` já é parâmetro, e o gate AST de `test_fuso_do_tenant.py` reprova o contrário.

- [ ] **Step 1: Escreva os testes que falham**

```python
def test_ausencia_do_saldo_do_mes_dispara_no_mes_fechado(db, user_owner, conta_bancaria):
    """Membro: conta ativa, setembro fechado, nenhum checkpoint em setembro."""
    coleta = absences.coletar(db, user=user_owner, hoje=date(2026, 10, 3))
    kinds = [a.kind for a in coleta.ditas]
    assert "financeiro.conferencia.saldo_do_mes" in kinds


def test_ausencia_nao_dispara_com_saldo_declarado(db, user_owner, conta_bancaria):
    """Não-membro: o saldo de 30/09 já foi declarado."""
    _checkpoint(db, conta_bancaria, reference_date=date(2026, 9, 30), balance_cents=100_000)
    coleta = absences.coletar(db, user=user_owner, hoje=date(2026, 10, 3))
    assert "financeiro.conferencia.saldo_do_mes" not in [a.kind for a in coleta.ditas]


def test_ausencia_nao_dispara_para_conta_criada_depois_do_mes(db, user_owner):
    """Não-membro: conta cadastrada em 03/10 não faz o e1p dizer nada sobre setembro."""
    _conta(db, opening_date=date(2026, 10, 3))
    coleta = absences.coletar(db, user=user_owner, hoje=date(2026, 10, 5))
    assert "financeiro.conferencia.saldo_do_mes" not in [a.kind for a in coleta.ditas]


def test_o_mes_entra_no_sujeito_e_por_isso_o_aviso_novo_nao_e_calado(db, user_owner, conta_bancaria):
    """⚠️ O ponto da chave composta.

    Com o id da conta sozinho, o marco de setembro sobreviveria à virada, `dias` voltaria a 0 e
    `_calada` engoliria o aviso de outubro — o silêncio permanente que a correção de 2026-08-09
    acabou de desfazer no eixo do dinheiro.
    """
    setembro = absences.coletar(db, user=user_owner, hoje=date(2026, 10, 3)).ditas
    a_set = [a for a in setembro if a.kind == "financeiro.conferencia.saldo_do_mes"][0]
    assert a_set.subject_id.endswith(":2026-09")

    # Simula o mapa de marcos gravado no briefing de outubro, e vira o mês.
    marcos = {f"{a_set.kind}:{a_set.subject_id}": 2}
    outubro = absences.coletar(
        db, user=user_owner, hoje=date(2026, 11, 2), ja_reportadas=marcos
    ).ditas
    a_out = [a for a in outubro if a.kind == "financeiro.conferencia.saldo_do_mes"]
    assert a_out and a_out[0].subject_id.endswith(":2026-10")


def test_ausencia_nao_roda_sem_o_modulo_financeiro(db, user_so_crm, conta_bancaria):
    """O filtro decide quais REGRAS RODAM, não quais resultados aparecem."""
    coleta = absences.coletar(db, user=user_so_crm, hoje=date(2026, 10, 3))
    assert "financeiro.conferencia.saldo_do_mes" not in [a.kind for a in coleta.ditas]
```

Use os helpers/fixtures reais do arquivo. Se não houver fixture de conta bancária lá, crie uma **local ao arquivo de teste**, com docstring dizendo a `opening_date` escolhida e por quê.

- [ ] **Step 2: Rode e veja falhar**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_vima_absences.py -k saldo_do_mes -v`
Expected: FAIL — o kind não aparece

- [ ] **Step 3: Escreva a regra**

Em `absences.py`, na seção `── Financeiro ──`, depois de `_dinheiro_com_data`:

```python
def _saldo_do_mes_nao_declarado(db: Session, hoje: date) -> list[Ausencia]:
    """O único ato recorrente que o ciclo da conferência pede do dono: declarar o saldo do mês.

    **Sem limiar, e isso é a decisão.** Um limiar exigiria a 8ª pergunta de Calibração
    (`test_todo_limiar_tem_pergunta` reprova limiar sem pergunta) e ela seria um número sem
    evidência — Artigo IV. Não precisa: a declaração retroativa existe (`reference_date` aceita data
    passada, e redeclarar o mesmo dia corrige com 200, não 409), então avisar **depois** do
    fechamento não perde nada. O dono abre o extrato e informa o saldo de 30/09 no dia 03/10.

    `dias` = dias desde o fechamento do mês, e a cadência sai de graça de `_proximo_marco`:
    `0 → 1 → 2 → 4 → 8 → 16`.

    ⚠️ **O mês entra no `subject_id`, e não é decoração.** Com o id da conta sozinho, o marco do mês
    anterior sobreviveria à virada, `dias` voltaria a `0` e `_calada` engoliria o aviso do mês novo —
    o silêncio permanente que a correção de 2026-08-09 acabou de desfazer no eixo do dinheiro.

    **Uma por conta, nomeando só o ciclo fechado mais recente.** Lacunas mais antigas vivem na tela
    de Conferência: o briefing pede **um ato por vez**, mesma filosofia do "uma pergunta por gancho
    por dia".

    Membro: Itaú PJ ativo, setembro fechado, nenhum checkpoint em setembro.
    Não-membro: a Poupança BB **arquivada** (fora de `list_accounts`); o Itaú PJ cujo saldo de 30/09
    já foi declarado; e a conta cadastrada em 03/10, que não existia em setembro.
    """
    primeiro_do_mes = hoje.replace(day=1)
    fim_do_anterior = primeiro_do_mes - timedelta(days=1)
    inicio_do_anterior = fim_do_anterior.replace(day=1)
    dias = (hoje - fim_do_anterior).days

    fora: list[Ausencia] = []
    for conta in bank_service.list_accounts(db):
        # A conta precisa ter EXISTIDO no mês fechado — senão o e1p cobraria de uma conta nova o
        # saldo de um mês em que ela não era dele.
        if conta.opening_date > fim_do_anterior:
            continue
        declarado = db.scalar(
            select(func.count())
            .select_from(BankBalanceCheckpoint)
            .where(
                BankBalanceCheckpoint.bank_account_id == conta.id,
                BankBalanceCheckpoint.reference_date >= inicio_do_anterior,
                BankBalanceCheckpoint.reference_date <= fim_do_anterior,
            )
        )
        if declarado:
            continue
        fora.append(
            Ausencia(
                module="financeiro",
                kind="financeiro.conferencia.saldo_do_mes",
                title=(
                    f"{conta.name} — o mês fechou sem o saldo informado; você ainda pode "
                    f"informar o saldo de {fim_do_anterior.strftime('%d/%m')}"
                ),
                dias=dias,
                subject_type="bank_account",
                subject_id=f"{conta.id}:{inicio_do_anterior.year:04d}-"
                f"{inicio_do_anterior.month:02d}",
            )
        )
    return fora
```

Acrescente ao topo do arquivo:

```python
from app.modules.bank import service as bank_service
from app.modules.bank.models import BankBalanceCheckpoint
```

⚠️ Importar `bank` daqui é permitido: a Regra dos Planos proíbe `bank` alcançar o plano da
plataforma, não o Vima ler o plano do banco. `list_accounts` é reusada em vez de repetir o filtro
`archived_at IS NULL` — uma segunda definição de "conta ativa" divergiria na primeira manutenção.

- [ ] **Step 4: Ligue em `coletar`**

Dentro de `if pode_ver(user, "financeiro"):`, logo depois de `_dinheiro_com_data`:

```python
        fora.extend(_saldo_do_mes_nao_declarado(db, hoje))
```

- [ ] **Step 5: Rode e veja passar**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_vima_absences.py tests/test_vima_regra_do_silencio.py tests/test_fuso_do_tenant.py tests/test_dna_catalogo.py -v`
Expected: PASS. Se `test_dna_catalogo.py` não existir com esse nome, rode `-k dna`.

- [ ] **Step 6: Rode a suíte inteira**

Run: `cd apps/api && .venv/Scripts/python -m pytest -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add apps/api/app/modules/vima/absences.py apps/api/tests/test_vima_absences.py
git commit -m "feat: o briefing cutuca quando o mes fecha sem saldo declarado [Epic 8]"
```

---

### Task 8: O aceite em 360px, a entrada no CLAUDE.md e o item de runbook

**Files:**
- Create: `onda-gate-ciclo-360px.png` (na raiz do repo, ao lado de `onda-3-payout-360px.png`)
- Modify: `CLAUDE.md`, `docs/HOSTINGER-DEPLOY.md`

**Contexto:** três dívidas de 360px já estão abertas na fila (8.13 AC9, 8.21, 2b-i) e três PRs de campo foram pagos (#56, #58, #89). A 2b-ii e a Onda 3 mediram antes de mergear, com Vite + `page.route` + `boundingBox`, sem backend. Esta frente faz o mesmo.

- [ ] **Step 1: Suba o Vite sozinho**

Run: `cd apps/web && pnpm dev`
Não suba backend. Use `127.0.0.1:5173`, **não** `localhost` (colisão de porta conhecida).

- [ ] **Step 2: Escreva o script de medição**

Salve como `medir-360px.mjs` no scratchpad (**não commite**). Ajuste o token/rota de login conforme o que `ProtectedLayout` exigir — se a tela redirecionar para `/login`, injete o estado de auth em `localStorage` antes de navegar, como os outros scripts de medição deste repo fazem.

```js
import { chromium } from "playwright";

const CICLOS = {
  ciclos: [
    { ano_mes: "2026-11", start: "2026-11-01", end: "2026-11-30", fechado: false, legivel: false,
      motivo_nao_legivel: null, total_divergencia_cents: null, contas_avaliadas: 0,
      contas_sem_checkpoint: 3, movimentos_no_periodo: 2, valor_movimentado_cents: 45_000 },
    { ano_mes: "2026-10", start: "2026-10-01", end: "2026-10-31", fechado: true, legivel: true,
      motivo_nao_legivel: null, total_divergencia_cents: -3_700, contas_avaliadas: 3,
      contas_sem_checkpoint: 0, movimentos_no_periodo: 14, valor_movimentado_cents: 1_840_200 },
    { ano_mes: "2026-09", start: "2026-09-01", end: "2026-09-30", fechado: true, legivel: true,
      motivo_nao_legivel: null, total_divergencia_cents: 0, contas_avaliadas: 3,
      contas_sem_checkpoint: 0, movimentos_no_periodo: 0, valor_movimentado_cents: 0 },
    { ano_mes: "2026-08", start: "2026-08-01", end: "2026-08-31", fechado: true, legivel: false,
      motivo_nao_legivel:
        "Faltou o saldo informado das contas Poupança BB, Aplicação CDB neste mês — sem ele o e1p não consegue conferir o mês inteiro.",
      total_divergencia_cents: 1_250_000, contas_avaliadas: 1, contas_sem_checkpoint: 2,
      movimentos_no_periodo: 9, valor_movimentado_cents: 2_310_000 },
  ],
};

const conta = (nome, div, tol, mov, val) => ({
  bank_account_id: nome, bank_account_name: nome, bank_account_kind: "checking",
  saldo_banco_cents: 250_000, saldo_banco_origem: "banco", saldo_banco_fonte: "manual",
  saldo_banco_data: "2026-10-31", saldo_sistema_cents: 250_000 - div,
  saldo_sistema_origem: "banco", divergencia_cents: div,
  dentro_da_tolerancia: Math.abs(div) <= tol, tolerancia_cents: tol,
  dias_desde_ultima_conferencia: 3, movimentos_ignorados: 0,
  movimentos_no_periodo: mov, valor_movimentado_cents: val, notes: [],
});

const RELATORIO = {
  start: "2026-10-01", end: "2026-10-31",
  contas: [
    conta("Itaú PJ", -1_234_500, 5_000, 9, 1_840_200),
    conta("Poupança BB", 0, 5_000, 3, 320_000),
    conta("Aplicação CDB", 3_700, 5_000, 2, 150_000),
  ],
  total_divergencia_cents: -1_230_800, contas_avaliadas: 3, contas_sem_checkpoint: 0,
  contas_fora_da_banda: [{ bank_account_id: "Itaú PJ", bank_account_name: "Itaú PJ",
    divergencia_cents: -1_234_500, tolerancia_cents: 5_000 }],
  notes: [], lancamentos_sem_conta_informada: 0, valor_sem_conta_informada_cents: 0,
  rendimentos_sem_perna_bancaria: 0, valor_rendimentos_sem_perna_cents: 0,
};

const json = (body) => (route) =>
  route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 360, height: 740 } });
await page.route("**/api/bank/reconciliation-report*", json(RELATORIO));
await page.route("**/api/bank/reconciliation-cycles*", json(CICLOS));
await page.goto("http://127.0.0.1:5173/financeiro/conferencia");
await page.waitForSelector('[data-testid="historico-de-ciclos"]');

const viewport = page.viewportSize().width;
const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
// Todo elemento que cruza a borda direita — é assim que "R$ 3." no lugar de "R$ 3.000,00" aparece.
const estouros = await page.evaluate((w) =>
  [...document.querySelectorAll("*")]
    .map((el) => ({ tag: el.tagName, cls: el.className?.toString?.().slice(0, 60),
                    right: el.getBoundingClientRect().right }))
    .filter((e) => e.right > w + 0.5), viewport);

console.log({ viewport, scrollWidth, estouros });
await page.screenshot({ path: "onda-gate-ciclo-360px.png", fullPage: true });
await browser.close();
```

Run: `node medir-360px.mjs`

- [ ] **Step 3: Rode e leia os números**

Critério de aceite, o mesmo da Onda 3:
- `document.scrollWidth` ≤ viewport + o estouro **pré-existente** de 15px do `AppShell` (`app/AppShell.tsx:209`) — que **não** é desta frente e não deve ser corrigido aqui;
- **nenhum valor cortado**: `R$ 18.402,00` visível por inteiro em toda linha do histórico;
- o motivo longo quebra linha em vez de rolar.

Se a medição achar corte, corrija **o layout** (empilhar, `min-w-0`, `whitespace-nowrap` no valor) — nunca a asserção. Nenhuma classe CSS prova isto: a 2b-ii mediu `overflow-x` correto, `flex-wrap` correto, e a tela errada.

- [ ] **Step 4: Escreva a entrada no CLAUDE.md**

Na seção do Epic 8, **depois** de "Onda 3 — o payout fecha o circuito", acrescente uma subseção `### O ciclo da conferência — o instrumento que torna a divergência legível`, cobrindo: o que passou a existir; a regra que fica (**o número nunca aparece sem o volume que o produziu**; a vacuidade da janela como irmã simétrica do erro de gate de julho); o corte de P4 e por que ele existe; e a dívida que sobra (`PRIMEIRO_CICLO_MEDIVEL` depender de um fato fora do repositório).

Atualize também o último item da Onda 3 (⚠️ *"O gate ainda NÃO pode ser lido..."*) para apontar para a subseção nova: o próximo passo deixou de ser "instrumentar" e passou a ser "rodar o ciclo".

- [ ] **Step 5: Acrescente o item ao runbook**

Em `docs/HOSTINGER-DEPLOY.md`, na seção de deploy, acrescente:

```markdown
- **Ao subir uma mudança do Epic 8, confira `bank.reconciliation.PRIMEIRO_CICLO_MEDIVEL`.** Ele é o
  primeiro dia do primeiro mês INTEIRAMENTE posterior ao deploy da Onda 3. Cravado cedo demais, o
  e1p declara conferido um mês cujo termo P4 nunca foi medido — e o erro é silencioso. O teste de
  piso só reprova datas anteriores ao merge; a data do deploy não é um fato do repositório.
```

- [ ] **Step 6: Rode tudo**

Run: `cd apps/api && .venv/Scripts/python -m pytest -q` e `cd apps/web && pnpm vitest run && pnpm tsc --noEmit && pnpm lint`

⚠️ **Não use `bash scripts/check.sh`** — ele resolve `ruff`/`python` do PATH (que pode não ser o do venv) e **mascara falha de frontend** com `|| true` no vitest. Rode as etapas individualmente até isso ser corrigido.

Expected: PASS em todas.

- [ ] **Step 7: Commit**

```bash
git add CLAUDE.md docs/HOSTINGER-DEPLOY.md onda-gate-ciclo-360px.png
git commit -m "docs: registra o ciclo da conferencia, com o aceite de 360px medido [Epic 8]"
```

---

## Ao terminar

Não faça `git push` e não abra PR — é exclusivo do @devops. Reporte:
- a saída real das duas suítes (números, não "passou");
- os números medidos em 360px (`scrollWidth` e o maior `boundingBox`);
- se `PRIMEIRO_CICLO_MEDIVEL` ainda é `2026-09-01` ou se o deploy da Onda 3 obrigou a movê-lo.
