# Quality Gate — Epic 8, Stories 8.19 e 8.20 (o saldo de abertura e a comparação degenerada)

> **Agente:** Aria (@architect) — o `quality_gate` nomeado nas duas stories · **Data:** 2026-08-07
> **Base da revisão:** `main` @ `38053aa` — o código das duas stories **já está mergeado** (PR #71,
> `deb7a1c`), então este gate revisa **produção**, não uma branch de entrega.
> **Worktree isolado:** `.claude/worktrees/gate-8-19-8-20`, branch `gate/story-8-19-8-20`.
> **Escopo:** 8.19 (AC1–AC7, IV1–IV7) e 8.20 (AC1–AC8, IV1–IV8).

---

## Veredito

| Story | Veredito |
|---|---|
| **8.19** — *O saldo de abertura é uma declaração* | ✅ **PASS** — nada a corrigir |
| **8.20** — *A comparação degenerada* | ✅ **PASS com correção aplicada** — 1 achado (**F-1**), corrigido neste gate |

**Por que este gate não é formalidade.** As duas stories mudam o comportamento de um relatório que
já roda em produção, e o arquivo central (`bank/reconciliation.py`) foi **tocado depois** do merge
delas, pela PR #78 (o fuso do tenant). O gate precisava responder duas perguntas que a leitura das
stories não responde: *os testes ainda matam os defeitos que elas corrigiram?* e *a restrição de
verdade que elas escreveram vale em todas as superfícies?* A primeira: **sim**. A segunda: **não —
faltava uma**.

---

## Os 7 quality checks

| # | Check | Resultado | Evidência |
|---|---|---|---|
| 1 | **Testes passando** | ✅ PASS | Backend, os 2 arquivos do gate: **77 passed** (20,7s). Frontend, suíte **completa**: **57 files / 528 tests** passed. A suíte backend cheia e o `rls_e2e` foram executados **pelo fundador em outra janela**, sobre o checkout principal — ver *Limites deste gate* |
| 2 | **Lint / typecheck** | ✅ PASS | `ruff check` → *All checks passed!* · `tsc --noEmit` (app web inteiro) exit 0 · `eslint --max-warnings 0` nos 4 arquivos tocados, exit 0 |
| 3 | **ACs implementados** | ⚠️ → ✅ | Todos verificados em `arquivo:linha`. **AC5 da 8.20 estava incompleto** (F-1) — corrigido neste gate |
| 4 | **Segurança / isolamento** | ✅ PASS | Nenhuma query nova nas duas stories; `opening_date` já vinha da `BankAccount` carregada. A correção do F-1 é frontend + docstring: **não toca banco, rota, schema nem query** |
| 5 | **Regressão** | ✅ PASS | `projection.py`, `money_planes.py`, `financial_intelligence/schemas.py`, `bank/models.py`, `bank/schemas.py` e `bank/router.py` fora do diff. Nenhum campo de API mudou de tipo ou de valor |
| 6 | **Qualidade dos testes (não-vácuo)** | ✅ PASS | **6 mutantes, 6 mortos** (tabela abaixo) — rodados agora, contra `main`, não contra a branch do @dev. Mais a prova de que as 2 asserções novas do F-1 **falham** antes da correção |
| 7 | **Documentação / rastreabilidade** | ✅ PASS | A docstring da dataclass documentava a razão **errada** do `saldo_banco_fonte = None` no terceiro estado — corrigida junto (ver F-1) |

---

## Mutação — os 6 mutantes, todos MORTOS

Rodados contra `main` @ `38053aa`, com a suíte de gate
(`test_bank_reconciliation_report.py` + `test_financial_intelligence_diagnostics_completude.py`,
77 testes). Reversão sempre por **cópia de arquivo**, com verificação byte a byte no fim.

| # | Story | Mutação | Resultado |
|---|---|---|---|
| M1 | 8.19 | a queda para `opening_date` some (volta ao `None` da 8.5) | **MORTO** — 7 falhas |
| M4 | 8.19 | sem `min(end, today)` — relatório de período passado conta até hoje | **MORTO** — 7 falhas |
| M1 | 8.20 | `degenerada = False` — a guarda inteira some | **MORTO** — 3 falhas |
| M2 | 8.20 | o remédio errado *"se der zero, ignore"* (`… and balance_cents == opening_balance_cents`) | **MORTO** — 1 falha, **só** o teste do ramo B |
| M3 | 8.20 | `saldo_banco_data=None` (o alinhamento estrito do §Escalado 1) | **MORTO** — 2 falhas |
| M4 | 8.20 | a nota reusada (`_note_sem_checkpoint` no caso degenerado) | **MORTO** — 2 falhas |

**O que o M1 da 8.19 e o M4 da 8.20 provam juntos:** a reescrita de `today` que a PR #78 fez neste
mesmo arquivo, **depois** do merge das duas stories, não esvaziou nenhum dos dois testes. Era a
pergunta central deste gate.

---

## F-1 — o AC5 da 8.20 enumerou três superfícies agregadas; havia uma quarta

**Severidade:** média. Afirmação falsa na tela, sem número errado. **Status: CORRIGIDO neste gate.**

### O defeito

`saldo_banco_fonte` (eixo B — a porta por onde o saldo externo entrou) é `None` nos **dois** estados
não avaliáveis. O rótulo dele, `conferencia.ts::fonteLabel`, traduzia `null` para a string literal
**`"sem saldo informado"`**, e `ConferenciaPage.tsx` a renderizava **sem guarda**. Na linha da conta
degenerada, a célula do lado do banco saía assim:

```
Não sei                  ← saldo_banco_cents = None
indisponível             ← eixo A
sem saldo informado      ← eixo B  ⚠️ FALSO: o dono informou
em 30/07/2026            ← saldo_banco_data, acrescentado pela PRÓPRIA 8.20
```

…com a nota da conta, na coluna ao lado, dizendo *"Você informou o saldo desta conta em
30/07/2026"*. **A mesma linha se contradizia.**

É exatamente a restrição que a 8.20 escreveu para si mesma, no *Contrato entregue à Story 8.16*:

> *"nenhuma superfície agregada pode voltar a afirmar 'sem saldo informado' — a conta **tem** saldo
> informado."*

A story enumerou três (`_note_total_parcial`, o motivo do `engine.py`, `avisoTotalParcial` + o
contador da tela) e corrigiu as três. A quarta não estava na lista porque não é uma frase sobre o
agregado: é um **rótulo de campo**, e ninguém procurou a mentira nessa forma.

**O mesmo rótulo atinge a linha da 8.19** (conta sem checkpoint na janela): ali `fonte` é `null` de
verdade, mas a conta **tem** saldo de partida do cadastro — e dizer *"sem saldo informado"* ao lado
de uma nota que diz *"O e1p tem o saldo de partida desta conta, informado por você em {data}"* é a
mesma afirmação sem lastro que a 8.19 removeu da nota. A 8.19 registrou `conferencia.ts:331` como
achado vizinho e **não viu** este.

### A prova (medida, não deduzida)

Sonda inserida no próprio teste da 8.20 para o caso degenerado, contra o código de produção:

```
AssertionError: expected <p class="text-xs text-neutral-400">sem saldo informado</p> to be null
```

A mesma asserção falhou também no teste do caso sem checkpoint. **Duas falhas, dois cenários** —
foi assim que as asserções entraram: falhando primeiro.

### A correção — desenho **A**, decidido pelo fundador

Três desenhos foram postos na mesa. O escolhido é o que **não reabre contrato**:

| | Linha degenerada | Linha sem checkpoint | Custo |
|---|---|---|---|
| **A** — só frontend, guardando por `fonte === null` | rótulo some | rótulo some | **nenhuma AC contrariada, nenhuma asserção mudada** |
| B — só backend (`fonte = na_janela.origin`) | *"informado por você"* | **continua mentindo** | contraria o AC1 da 8.20 + a asserção de `_assert_degenerada` |
| C — os dois, desenhados juntos | *"informado por você"* | rótulo some | o mais informativo; alarga o contrato |

**Por que A, e o argumento é de informação — não de esforço.** Na linha degenerada,
*"informado por você"* seria a **terceira cópia do mesmo fato na mesma linha**: a nota já diz
*"Você informou o saldo desta conta em 30/07/2026"* e `saldo_banco_data` já renderiza
*"em 30/07/2026"*. O eixo B existe para distinguir `manual` × `ofx`, e na Onda 1 só existe `manual`
— hoje ele não distingue nada. **Ele ganha o lugar dele ao lado de um número, não ao lado de um
"Não sei".** O desenho B compra coerência de contrato e **zero informação nova** na tela, ao preço
de reabrir uma AC e uma asserção de duas stories já mergeadas.

⚠️ **A armadilha que o desenho A evita, e que fica registrada:** empilhar a guarda do frontend
sobre a correção do backend, guardando por `saldo_banco_cents === null`, faria o campo novo do
backend virar **código morto** — carregado e nunca renderizado. É a lição do item 12 do
`CLAUDE.md` (§WhatsApp Evolution): *capacidade nova nasce com o consumidor no mesmo passo*. Se um
dia o desenho C for retomado, a guarda tem de ser `fonte === null`, nunca `cents === null`.

### O diff (5 arquivos, +49/−6) — zero lógica de negócio

| Arquivo | Mudança |
|---|---|
| `apps/web/src/features/financeiro/conferencia.ts` | `fonteLabel(fonte: string)` — o parâmetro **deixa de aceitar `null`** e o ramo que devolvia a frase falsa deixa de existir |
| `apps/web/src/features/financeiro/ConferenciaPage.tsx` | a linha do eixo B só é renderizada quando `saldo_banco_fonte !== null` |
| `apps/web/src/features/financeiro/ConferenciaPage.test.tsx` | 2 asserções — os dois estados não avaliáveis não afirmam mais sobre a porta |
| `apps/web/src/features/financeiro/conferencia.test.ts` | cai o caso `fonteLabel(null)`, com o registro do porquê |
| `apps/api/app/modules/bank/reconciliation.py` | **doc-only** — a docstring justificava o `fonte = None` do terceiro estado com *"não houve porta de entrada"*, que é **falso ali**: houve checkpoint e ele tem `origin`. Agora diz que a porta existe e é descartada de propósito, e nomeia quem renderiza |

### A guarda de regressão é o TIPO, e ela morde

O tipo estreito (`string`, não `string | null`) é o que impede a frase falsa de voltar. Verificado
por mutação, não afirmado: removida a guarda do consumidor, o `tsc` reprova.

```
src/features/financeiro/ConferenciaPage.tsx(326,61): error TS2345:
  Argument of type 'string | null' is not assignable to parameter of type 'string'.
```

Escolha deliberada: uma **asserção** de teste só protege o caminho que ela exercita; o tipo protege
todos os call sites, inclusive os que ainda não existem. É a mesma disciplina de
`payables.is_overdue` exigir `today` como parâmetro obrigatório.

---

## Limites deste gate — o que NÃO foi verificado aqui

Registrado com honestidade, porque um gate que esconde o que não cobriu é pior que nenhum gate.

1. **A suíte backend completa e o `rls_e2e` não foram executados neste worktree.** Foram rodados
   pelo fundador em outra janela, **sobre o checkout principal** — ou seja, **sem as 5 alterações
   do F-1**. O risco disso é baixo e é nomeável: a única mudança backend do F-1 é uma **docstring**,
   sem efeito em runtime. A mudança com risco real é frontend, e essa foi coberta pela suíte
   **completa** de vitest aqui (57 files / 528 tests).
2. **Os 3 agentes de QA do `CLAUDE.md` §5** (regression-tester, bug-hunter, dedup-checker) não
   foram executados. Substituídos, como nas duas stories, pelos 6 mutantes + a prova de falha das
   asserções novas.
3. **Aceite visual em ~360px não foi feito.** A correção **remove** uma linha de texto da célula,
   então não pode estourar layout que já cabia — mas isso é raciocínio, não medição. Some-se à
   dívida de 360px já registrada no `CLAUDE.md` para a tela de Conferência.
4. **`packages/shared-types/src/generated.ts`** segue defasado e sem menção a `bank` (dívida
   conhecida). Este gate não muda contrato de API, então não agrava.

---

## Achados herdados — confirmados abertos, NÃO corrigidos aqui

Nenhum é regressão destas stories; todos já estavam registrados por elas.

1. **`conferencia.ts:331`** — `if (dias === null) return "Esta conta nunca teve saldo informado."`
   virou **código morto** com a 8.19 (o backend nunca mais devolve `null`). Ramo defensivo,
   registrado pela própria 8.19 (desvio 3). **Não tocado** — removê-lo é escopo a mais e tiraria a
   defesa se algum consumidor futuro voltar a mandar `null`.
2. **`bank/router.py:624`** — o OpenAPI da rota de conferência descreve **um** dos dois motivos de
   `indisponivel`, e quem ler conclui que `indisponivel ⇒ saldo_banco_data === null`. Registrado
   pela 8.20 (achado 1); `router.py` está na lista **NÃO TOCAR** do AC7 dela. Recomendação mantida:
   é da **8.16**.
3. **`contas_sem_checkpoint`** — o nome do campo ficou impreciso (conta também as que **têm**
   checkpoint, o degenerado). O **texto** de todas as superfícies foi corrigido; o **nome do campo
   de API** não, porque renomear é campo novo. Recomendação mantida: aposentar na **8.16**.
4. **SIG-001** (a virada de mês apaga uma conferência recente) e **REL-002** (conta arquivada sai
   do relatório sem nota) continuam abertos, intocados.
5. **`days_since_last_declared_balance`** continua implementada e **sem consumidor** — e as duas
   stories **proíbem** usá-la na conferência (pergunta diferente, conjunto diferente).

---

## A lição de método que vale mais que o achado

As duas stories caçaram afirmações falsas com um rigor incomum — e a 8.20 chegou a escrever a
restrição de verdade em forma de contrato para a story seguinte. Mesmo assim, o AC5 varreu as
superfícies **em forma de frase** (`_note_total_parcial`, o motivo do motor, `avisoTotalParcial`) e
não alcançou a que estava em forma de **rótulo de campo**.

> **Regra que fica:** ao remover uma afirmação falsa, a varredura é pelo **fato afirmado**, não pela
> forma da frase. `grep` pela string é o começo — o que fecha é perguntar *quais elementos da tela
> qualificam este campo*, porque um rótulo de enum afirma tanto quanto uma sentença, e não parece
> uma sentença para quem procura.

É a mesma família da **INSTANCIAÇÃO OBRIGATÓRIA** já registrada no `CLAUDE.md`: um conjunto definido
por descrição (*"as superfícies agregadas"*) nasceu com três membros escritos e nenhum não-membro —
e o quarto membro nunca teve quem protestasse por ele.

---

## Encaminhamento

- **8.19 → `Done`.** Nada pendente.
- **8.20 → segue `InReview`** até a correção do F-1 mergear, porque o F-1 é do escopo do **AC5
  dela**, não um achado vizinho. Mergeada a correção, vai para `Done` sem novo gate.
- A correção vive na branch **`gate/story-8-19-8-20`** e precisa de **PR** — `main` é protegida
  (4 checks obrigatórios) e `git push` é exclusivo do **@devops**. **Nada foi enviado por este
  gate.**
