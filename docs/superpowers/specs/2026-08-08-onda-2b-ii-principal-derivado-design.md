# Onda 2b-ii — `principal_cents` derivado (e o backfill que deixou de existir)

> **Data:** 2026-08-08 · **Epic:** 8 (Controle Bancário Nativo) · **Onda:** 2b, segunda metade
> **Sucede:** Onda 2b-i (`docs/superpowers/specs/2026-08-07-onda-2b-i-perna-bancaria-do-rendimento-design.md`)
> **Referência normativa:** `docs/prd/epic-8-controle-bancario.md` §647 (escopo original da 2b),
> §F-D7 · `docs/architecture/controle-bancario-design.md` §6.2, §6.3 · REQ-23, REQ-25, REQ-27 ·
> **R3 do fundador**

---

## 1. Por que esta onda existe, e por que ela ficou pequena

`investment_accounts.principal_cents` é um campo **digitado** (`investments/models.py:49`,
`schemas.py:19` e `:42`). O dono informa quanto tem aplicado, o e1p acredita, e **nunca mais
confere**. Um resgate feito no app do banco não muda aquele número; nada protesta. É o ponto cego
que o R3 do fundador aponta e que o ADR 0003 registra como motivo da onda
(`docs/decisions/0003-controle-bancario-nativo.md:32`).

A onda torna o principal **derivado dos movimentos da conta bancária da aplicação** — a Regra 4 do
épico (*"saldo é derivado dos movimentos, nunca coluna, nunca digitado"*) aplicada ao último lugar
do produto onde ela ainda não valia.

### 1.1 O item de maior risco do épico deixou de existir — e isso é uma decisão, não sorte

Todo documento anterior a esta spec descreve a 2b-ii como **a onda do backfill**: o único `UPDATE`
sobre dado existente do épico inteiro, exposto à armadilha do `FORCE ROW LEVEL SECURITY` da
migration 0046 (o `UPDATE` filtrado a zero linhas **em silêncio**, que o SQLite dos testes não pega).
O PRD chama isso de *"o item de maior risco do épico inteiro"* (§656-659), o F-D7 manda dar-lhe
story própria e atenção de gate, e o plano da 2b-i o reafirma como dívida em aberto.

Duas coisas o dissolveram:

1. **A 2b-i já executou os passos 1 e 2 do §6.2 — por ato do dono, não por migration.** A coluna
   `investment_accounts.bank_account_id` entrou como DDL puro (`ADD COLUMN` + `CREATE INDEX`, que a
   RLS não alcança) e a aplicação legada foi vinculada **pelo dono, na tela**. O mecanismo já foi
   validado em campo.
2. **`investment_accounts` está vazia em produção** (confirmado pelo fundador em 2026-08-08; ver
   §7, Suposição S1). Os passos 3 e 4 — a transferência sintética de aporte inicial e um movimento
   por `Charge` de rendimento legada — não têm sobre o que rodar.

**Decisão:** esta onda **não escreve `UPDATE` nenhum, e não tem migration.** No lugar do backfill,
entrega o que o próprio §6.2 já pedia junto dele — um script que *"reporta divergências sem corrigir
em silêncio"* — e deixa a correção ser **ato do dono**, exatamente como a 2b-i fez com o vínculo.

> **A regra que fica:** quando um backfill existe para reconstruir histórico que **um ato do dono
> reconstrói melhor**, o backfill é o caminho pior — ele escreve sem testemunha, num regime (`FORCE
> RLS`) onde o fracasso é silencioso. Trocar escrita retroativa por *auditoria + ato* foi a manobra
> da 2b-i; esta onda é a segunda aplicação dela, e agora é padrão.

### 1.2 O que esta onda NÃO destrava

Nada da métrica primária. **P3 fechou na 2b-i**; a leitura do gate não depende de uma linha desta
onda. Isto está escrito porque o §647 do PRD descreve os cinco entregáveis da 2b em bloco, e quem
ler o bloco pode concluir que a métrica ainda espera por eles. Não espera.

---

## 2. Escopo

### 2.1 Entra

| # | Entregável |
|---|---|
| **E1** | `principal_cents` passa a ser **calculado** dos movimentos da conta bancária vinculada |
| **E2** | A coluna `investment_accounts.principal_cents` fica **congelada** — sem leitor, sem escritor, com gate AST |
| **E3** | `create_account` e `update_account` **recusam** `principal_cents` (409), nomeando a ação real |
| **E4** | O principal excedido por resgate aparece **negativo e nomeado** na tela (REQ-25, resolvido pela leitura) |
| **E5** | `python -m app.scripts.investment_audit` — reporta divergência, **nunca corrige** |
| **E6** | `InvestimentosPage`: principal calculado (sem campo), o aviso do E4, e o **extrato da aplicação** |
| **E7** | Aceite visual em **~360px** do que o E6 acrescenta |

### 2.2 Não entra

- **Migration.** Nenhuma. Ver §1.1. O `DROP COLUMN principal_cents` é migration **posterior**, um
  ciclo depois, pelo mesmo critério que manteve `attachments.data` (Story 3.5) e
  `tenant_profiles.timezone` (migration 0073) vivas por um ciclo.
- **Cotização/liquidação em datas diferentes (REQ-26).** Duas pernas de um resgate com datas
  distintas. Não há caso em produção e o modelo de transferência atual pareia as duas pernas na
  mesma data. Fica registrado como não-feito, não como esquecido.
- **Rendimento automático por indexador.** Continua sendo lançamento explícito do dono
  (`investments/models.py:3-6`). Nada nesta onda muda isso.

### 2.3 Direção de import — pré-decidida, não escolhida aqui

`investments` **já** importa `bank.service` e `bank.origin` desde a 2b-i
(`investments/service.py:54-56`), e essa direção é a legal. O inverso — `bank` importar
`investments` — é **proibido** por gate (`test_bank_transfers_nao_importa_investments`,
`tests/test_money_planes.py`). Toda decisão da §4 respeita isso sem exceção; onde ela apertou, foi a
decisão que mudou (§4.4), nunca o gate.

---

## 3. A fórmula

```
principal_cents = opening_balance_cents da conta de aplicação
                + Σ bank_transactions daquela conta
                    WHERE source <> 'yield'
                      AND status <> 'ignored'
                      AND posted_at > opening_date
                      AND posted_at <= hoje_do_tenant
```

Três termos, e cada um está lá por um motivo que some no código:

**(a) `opening_balance_cents` entra, e o design-mãe §6.2 não dizia isso.** É o dinheiro que já
estava aplicado no dia em que o dono cadastrou a conta — principal que nunca teve movimento. Somar
só os movimentos daria **R$ 0,00 de principal numa conta com R$ 10.000 aplicados**: um número errado
com aparência de fato, que é a família de defeito que a Onda 0 existe para não repetir.

**(b) `source <> 'yield'` é o que impede a dupla contagem.** O rendimento já é contado por
`accrued_yield_cents`, e desde a 2b-i ele também gera `bank_transaction`. Sem este recorte, cada
rendimento entraria **duas vezes** no saldo total da aplicação.

**(c) O piso `posted_at > opening_date` e o teto `<= hoje` não são escolhas desta onda** — são o
`WHERE` de `_movements_sums` (`bank/service.py:557`), a **única** implementação da soma de
movimentos do repositório. O piso existe porque movimento anterior à abertura já está dentro do
`opening_balance_cents`; o teto porque `until=None` significa **hoje** desde a Story 8.10, e um
aporte agendado para o mês que vem não é principal aplicado hoje.

### 3.1 A invariante, e quem a verifica

```
derived_balance(conta_de_aplicação) == principal_cents + accrued_yield_cents
```

Vale **por construção** enquanto todo rendimento tiver perna bancária — que é o que a 2b-i garantiu
com o 409 de `register_yield`. É a invariante que o design-mãe §6.2 já pedia (*"antes de qualquer
resgate"*), agora sem a ressalva: com o rendimento gerando movimento, ela vale **depois** do resgate
também. Quebrá-la é sintoma de movimento escrito por fora da Regra da Origem.

### 3.2 Saldo de abertura desconhecido ⇒ o principal é `None`, nunca zero

A Story 8.21 (PR #94) criou `bank_accounts.opening_balance_is_known`: `false` significa *"tenho a
conta e **não sei** o saldo"*, e nesse estado `opening_balance_cents` é **placeholder, não
afirmação** (`bank/service.py:820-839`, `origem_do_saldo_derivado`).

Uma conta de aplicação nesse estado torna o principal **inafirmável**. A resposta é `None` e a tela
diz que não sabe — **não zero**. Zero seria a afirmação *"você não tem nada aplicado"*, que é falsa
e indistinguível de um saldo genuinamente zerado.

Isto **reusa** `origem_do_saldo_derivado` em vez de repetir a comparação. A Story 8.21 pagou
exatamente esse preço: a procedência estava escrita duas vezes no `router.py`, e duas leituras da
mesma conta por portas diferentes podiam divergir. **Uma decisão, um lugar.**

---

## 4. Desenho

### 4.1 E1 — onde a derivação mora

Em `investments/service.py`, como `principal_derivado(db, acc) -> int | None`. Ela pede a soma a
`bank/service.py`, que ganha o parâmetro `exclude_sources` em `_movements_sums`.

**O parâmetro entra na função existente, não numa query nova**, e a razão está escrita na docstring
dela: *"duas cópias da mesma fórmula divergiriam no dia em que uma delas ganhasse uma condição — e o
sintoma seria um saldo que muda conforme a tela que o pede"*. Uma segunda soma de movimentos no
repositório também tornaria a Regra dos Planos §1.3a inauditável.

`exclude_sources` é `frozenset[str]`, default vazio — todo chamador existente segue idêntico.

### 4.2 E2 — a coluna congelada

`principal_cents` continua na tabela e **ninguém a lê nem a escreve**. `InvestmentAccountOut.principal_cents`
passa a ser preenchido pela derivação; o ORM mantém o atributo, e é justamente por isso que o gate
existe: nada no código **quebra** se alguém voltar a ler `acc.principal_cents` — só volta a mentir.

Gate: varredura AST sobre `app/modules/` reprovando o acesso ao atributo fora da definição do model.
O script de auditoria (§4.5) o lê **de propósito**, para comparar, e vive em `app/scripts/` — fora
do alcance da varredura por construção, não por exceção escrita. Com **controle positivo**: um teste
que prova que o gate reprova quando a leitura existe. Um gate sem controle positivo é um teste que
passa e não prova nada — a família dominante da Onda 2, oito ocorrências.

Precedente exato: `tenant_profiles.timezone` (migration 0073), congelada em 2026-08-07 com
`test_ninguem_le_mais_o_fuso_do_perfil`. E a lição registrada junto: **três consumidores da coluna
antiga não apareceram na investigação inicial**, e corrigir só o caminho óbvio teria quebrado os
três em silêncio. Por isso o inventário abaixo foi levantado **antes** desta spec fechar, não
durante a implementação.

#### 4.2.1 O inventário dos leitores — nove, e um deles muda o contrato

| Leitor | O que acontece |
|---|---|
| `investments/router.py:31` | Passa a receber o derivado em vez de `a.principal_cents` |
| `investments/service.py:134` (`create_account`) | Deixa de gravar — o campo é recusado (§4.3) |
| `investments/service.py:158-159` (`update_account`) | Deixa de gravar — idem |
| `investments/service.py:362` (`rentability`) | Devolve o derivado |
| **`investments/service.py:364-365`** | **Divide por ele. Ver abaixo.** |
| `investments/schemas.py:82` (`InvestmentAccountOut`) | `int` → `int \| None` |
| `investments/schemas.py:91` (rentabilidade) | `int` → `int \| None` |
| `apps/web/.../investimentos.ts:25,40` | `number` → `number \| null` |
| `apps/web/.../InvestimentosPage.tsx:130,248` | `:130` exibe (trata `null`); `:248` é o campo do formulário, que **sai** |

**O leitor que muda o contrato.** `_pct` (`service.py:333-337`) já devolve `None` quando o principal
é `0` — divisão por zero, protegida desde a 5.6. Com o principal podendo ser `None` (§3.2) ela
levantaria `TypeError` em vez de proteger, e **com o principal podendo ser negativo** (§4.4) ela
devolveria uma rentabilidade de sinal invertido — um número plausível, e errado.

> **Decisão:** `_pct` devolve `None` para principal `None` **e** para principal `<= 0`, e não só
> para `== 0`. Rentabilidade sobre principal negativo não é um número menor: é uma pergunta sem
> sentido (*"quanto rendeu percentualmente o que você não aplicou?"*). O `None` já é renderizado
> pela tela desde a 5.6 — a superfície existe e não precisa ser inventada.

**`packages/shared-types/src/generated.ts` tem `principal_cents` em quatro lugares e está defasado
desde o PR #45**, sem check de drift no CI. É dívida conhecida do épico; esta onda **não** a fecha e
**não** finge que ela não existe. Quem regenerar, regenera; quem não, deixa como está e a lista
acima é o inventário verdadeiro.

### 4.3 E3 — a recusa, e por que ela é diferente do 409 da 2b-i

`update_account` com `principal_cents` presente → **409**:

> *"O valor aplicado agora é calculado pelos movimentos da conta. Para mudar quanto está aplicado,
> registre a transferência que você fez de verdade — da conta corrente para a aplicação (aporte) ou
> da aplicação para a corrente (resgate)."*

`create_account` com `principal_cents` diferente de zero → **409**, com a segunda metade da verdade:

> *"No cadastro, o valor já aplicado é o **saldo de abertura** da conta bancária da aplicação — é lá
> que ele é informado, uma vez."*

Duas observações que precisam estar escritas antes de alguém abrir o arquivo:

- **Este 409 é o oposto do 409 da 2b-i.** Aquele era caminho normal — o dono batia nele ao registrar
  rendimento, e por isso a tela tinha de oferecer a saída ali mesmo (sem o que ele seria beco sem
  saída, a classe do item 12 do WhatsApp). Este é **inalcançável pela tela**, porque o E6 remove o
  campo. Se disparar, é integração antiga ou defeito. Ele é guarda de contrato, **não** fluxo — e
  por isso **não** ganha `detail["acao"]`: um `acao` sem modal do outro lado seria um contrato com
  ninguém.
- **A ação que a mensagem manda fazer existe hoje, e isso foi conferido.** `investment_in` e
  `investment_out` já são `TRANSFER_KINDS` desde a Onda 2 (`bank/schemas.py:385-387`), e a tela de
  transferência já está em `ContasSaldosPage.tsx`. **Recusar apontando para uma ação inexistente é
  o defeito que esta linha existe para não cometer.**

### 4.4 E4 — REQ-25: a leitura protesta, a escrita não recusa

O banco credita o resgate **bruto**: R$ 10.500 que são R$ 10.000 de principal mais R$ 500 de
rendimento. Registrado como uma transferência de −R$ 10.500 contra um principal de R$ 10.000, o
derivado dá **−R$ 500**.

O REQ-25 manda *"pedir o `register_yield` antes de fechar o resgate"*. **Esta spec desvia disso no
tempo — de propósito, e o desvio está declarado aqui porque o Artigo IV (No Invention) exige que
divergir de um requisito seja ato, não omissão.**

Três caminhos, e por que os dois primeiros caem:

| Caminho | Por que não |
|---|---|
| Clampar em zero | Esconde. É a mentira por omissão que a Onda 0 e a 8.21 desmontaram duas vezes |
| Recusar o resgate (409) | O dinheiro **já saiu do banco**. Recusar um fato consumado é o inverso do princípio da Onda 0. E exigiria `bank/transfers.py` consultar `investments` — o gate `test_bank_transfers_nao_importa_investments` proíbe, e a saída legítima (porta de saída registrada, `Protocol` + DTO + fiação fail-closed no boot) custa mais do que o problema |
| **A tela nomeia** ✅ | O número aparece como é, e a afirmação que ele sustentaria é substituída pela ação |

A tela:

> **Principal aplicado −R$ 500,00** ⚠️
> *"Você resgatou R$ 500,00 a mais do que aportou. Se essa diferença é rendimento que ainda não foi
> lançado, registre o rendimento do período — o e1p não adivinha o valor."*

**O "não adivinha" é literal e é a metade do REQ-25 que esta spec cumpre integralmente:** o sistema
sabe que faltam R$ 500 e **não** os lança sozinho. O valor certo do rendimento é fato do banco, não
dedução do e1p.

### 4.5 E5 — o script que confere

`python -m app.scripts.investment_audit`. Para cada aplicação: o que a coluna congelada diz, o que
os movimentos dizem, e a diferença. Saída em texto, código de saída 0 sempre (é relatório, não gate
de CI).

Duas armadilhas que ele tem de evitar, as duas já pagas neste repo:

- **Silêncio que parece aprovação.** Consulta em tabela com RLS sem tenant devolve **zero linhas,
  sem erro** — foi assim que a sondagem de `phone_key` em produção quase virou um *"está tudo
  limpo"* falso. O script **itera tenants** abrindo sessão de tenant (o padrão do `app.worker`) e
  **imprime quantos varreu**. `0 aplicações em 0 tenants` e `0 aplicações em 7 tenants` são
  resultados diferentes, e o primeiro é um bug do próprio script.
- **Corrigir em silêncio.** **Não existe `--fix`.** Se existisse, alguém o rodaria no deploy sem ler
  a saída, e o `UPDATE` que esta onda existe para não fazer voltaria pela porta dos fundos.

### 4.6 E6 — a tela

`InvestimentosPage`, por aplicação:

- **Principal aplicado** — número calculado, **sem campo de edição**. Com `opening_balance_is_known
  = false`, no lugar do número vai a frase de não-saber e o caminho para declarar o saldo.
- **Rendimento acumulado** e **rentabilidade** — inalterados.
- **O aviso do E4**, quando o principal for negativo.
- **Extrato da aplicação** — aportes, resgates e rendimentos em ordem. É o *"não apenas o lançamento
  do quanto rendeu"* do R3, e o §6.3 do design-mãe.

⚠️ **O extrato já existe em outra tela** — "Ver movimentos" em `ContasSaldosPage.tsx:457` —, porque
a conta de aplicação é uma `bank_account` como qualquer outra. Esta onda cria deliberadamente a
**segunda superfície** sobre o mesmo razão (decisão do fundador, 2026-08-08), e a garantia contra
divergência é **mecânica, não disciplina**: os dois extratos chamam o **mesmo endpoint**
(`GET /bank/transactions?bank_account_id=`), sem consulta própria e sem filtro reescrito. O que
difere entre eles é apresentação. Teste em §5.

**E7 — aceite visual em ~360px é item de trabalho, não dívida.** O débito está aberto em três
lugares (8.13 AC9, 8.21, 2b-i) e **três PRs de correção de campo já foram pagos por ele** (#56, #58,
#89) — em um deles uma conta real foi marcada paga sem o dono conseguir ver o checkbox. Abri-lo uma
quarta vez é escolher pagar o quarto. E `toContain("flex-wrap")` **não** é aceite: layout só se
prova medindo.

---

## 5. Como se prova que isto não é vácuo

| # | Prova | Por que existe |
|---|---|---|
| 1 | Varredura AST: ninguém lê `principal_cents` da coluna — **com controle positivo** | A coluna congelada de 2026-08-07 tinha três leitores que a investigação inicial não achou |
| 2 | `derived_balance == principal + accrued_yield` numa conta com aporte, rendimento e resgate | A invariante do §6.2, agora com quem a verifique |
| 3 | Principal é `None` — **e um teste que falha se for `0`** | Zero é afirmação; `None` é a ausência dela (8.21) |
| 4 | Registrar rendimento **não** move o principal | Metade do recorte `source <> 'yield'` |
| 5 | Registrar aporte **move** o principal | A outra metade. **Com o caso 4 sozinho, apagar o filtro inteiro passa verde** — é o mutante `>` → `>=` da Onda 2, que sobreviveu a 58 testes por faltar o caso da borda |
| 6 | `opening_balance_cents` entra no principal | Sem ele o teste 2 falharia só em conta cadastrada com saldo — o caso do fundador |
| 7 | `create_account`/`update_account` com principal → 409, com a mensagem certa por asserção exata | Substring genérica casa demais: *"trilho"* casava *"fora do trilho"* na Onda 2 |
| 8 | Os dois extratos batem no **mesmo** endpoint | O que impede a duplicação aceita no §4.6 de virar divergência |
| 9 | O script imprime a contagem de tenants varridos | Distingue "nada errado" de "não olhei" |
| 10 | Rentabilidade é `None` com principal `None` **e** com principal negativo | Sem isso, `None` vira `TypeError` e negativo vira um percentual de sinal invertido — plausível e errado (§4.2.1) |

**Nenhum teste desta onda pode usar `date.today()`.** A comparação é com `hoje_do_tenant(db)`, e o
gate `tests/test_fuso_do_tenant.py` já reprova o contrário. A 2b-i tropeçou nisto: um teste passou
**antes** da implementação porque a janela caía fora por causa da borda de fuso.

---

## 6. Ordem de implementação

1. `exclude_sources` em `_movements_sums` (§4.1) — mudança aditiva, suíte inteira segue verde
2. `principal_derivado` + a resposta `None` do §3.2, com os testes 2/3/4/5/6
3. Os nove leitores do §4.2.1, **de uma vez** — incluindo `_pct` e os schemas de saída, com o
   teste 10. Fatiar isso deixaria a API respondendo `None` num campo tipado `int` no meio do caminho
4. A recusa do §4.3 (E3), com o teste 7
5. O gate AST do §4.2, com controle positivo — **depois** de 2, 3 e 4, senão ele reprova o próprio
   código em construção
6. O script (§4.5), com o teste 9
7. A tela (§4.6) + o aviso do §4.4, com o teste 8
8. Aceite em ~360px (E7)
9. A entrada no `CLAUDE.md` — **AC obrigatório**, §5 passo 4

**PR obrigatório:** `main` é protegida (GH006), 4 checks. Push é do `@devops`.

---

## 7. Suposições abertas e riscos

**S1 — `investment_accounts` está vazia em produção.** Confirmado pelo fundador em 2026-08-08. **É
a suposição que sustenta o §1.1 inteiro**, e é justamente a família que já custou três desenhos
neste épico (a premissa plausível sobre o estado dos dados, não verificada com o dono). Aqui foi
verificada — **e mesmo assim ela é sobre HOJE, não sobre o dia do deploy.**

> **Mitigação, e é por isso que o E5 existe:** o script roda **antes** do deploy. Se o sócio
> cadastrar uma aplicação no intervalo, ele imprime a divergência e o dono a resolve por ato
> (declarando o saldo de abertura ou registrando o aporte). Nenhum caminho desta onda depende de a
> tabela estar vazia — a ausência de backfill é uma decisão sobre **onde a correção mora**, não uma
> aposta em zero linhas.

**S2 — resgate bruto é o caso comum.** O banco não separa principal de rendimento no crédito. Se
essa suposição estiver errada e o dono sempre resgatar valores redondos de principal, o aviso do
§4.4 nunca dispara — e continua correto. Falso positivo dele é impossível; falso negativo é o dono
não ter registrado o rendimento, que é exatamente o que ele diz.

**Risco R1 — o principal negativo assusta.** Um número vermelho na tela pede explicação, e a
explicação está colada nele por construção (§4.4). O risco real é a frase ser cortada em ~360px,
deixando só o número. É o E7.

**Risco R2 — a segunda superfície de extrato diverge.** Mitigado pelo endpoint único e pelo teste 8.
Não eliminado: uma mudança futura pode dar ao `InvestimentosPage` um filtro próprio, e nada além do
teste 8 protestaria.

---

## 8. Rastreabilidade

| Requisito | Onde |
|---|---|
| REQ-23 (`principal_cents` derivado, deixa de ser digitado) | §3, §4.1, §4.2, E1/E2 |
| REQ-25 (resgate não gera receita; o sistema pede, não infere) | §4.4 — **cumprido na leitura, não na escrita; desvio declarado** |
| REQ-26 (pernas em datas diferentes) | §2.2 — **fora de escopo, declarado** |
| REQ-27 (`Charge` de rendimento no "Recebido") | Resolvido antes desta onda (filtro `_INVESTMENT_REF_PREFIX` em `receivables`) |
| R3 do fundador (*"não apenas o quanto rendeu"*) | §4.6 — o extrato |
| design-mãe §6.2 passos 1-2 | Entregues na **2b-i** |
| design-mãe §6.2 passos 3-4 (o backfill) | **Não executados — §1.1** |
| design-mãe §6.2 passo 5 (não dropar a coluna) | §4.2 — congelada, drop posterior |
| design-mãe §6.2 passo 6 (409 na edição) | §4.3 |
| design-mãe §6.2 (script de auditoria) | §4.5 |
| design-mãe §6.3 (extrato na tela) | §4.6 |
| PRD F-D7 (*"merece story própria e atenção de gate"*) | Atendido — a story existe; o gate agora julga **ausência** de backfill, com o §1.1 como justificativa escrita |
