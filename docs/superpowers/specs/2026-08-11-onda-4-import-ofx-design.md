# Onda 4 — a importação de extrato (OFX), e o que a tornaria desnecessária

> **Épico:** 8 — Controle Bancário e Conferência
> **Data:** 2026-08-11 · **Base:** `main @ 54bb1d4` (PR #104, Onda 3) · **head do alembic:** `0077`
> **Docs-mãe:** `docs/architecture/controle-bancario-design.md` §4 (pipeline), §2.5, §9, §11 ·
> `docs/architecture/controle-bancario-onda2-design.md` §4.2 (futuro), §4.5 (estorno), §10 (ordem) ·
> `docs/prd/epic-8-controle-bancario.md` §3.1.2 (o gate) · `docs/decisions/0003-controle-bancario-nativo.md`
> (Consequências 1 e 3; Revisão futura a–e) · `docs/research/2026-07-29-controle-bancario-requisitos-e-viabilidade.md`
> **Antecessoras diretas:** Onda 2 (a Regra da Origem), 2b-i (P3), 2b-ii (principal derivado), 3 (P4)

> ## ⚠️ ESTA ONDA NÃO ESTÁ LIBERADA
>
> Esta é uma **spec de design escrita antes da autorização**, de propósito. O gate que a autoriza —
> `|divergencia_cents|` por conta — **não pode ser lido hoje**: a produção foi zerada em 05/08/2026 e a
> métrica exige um ciclo de uso real. Com P1–P4 fechados (Ondas 2, 2b-i, 3), a obstrução deixou de ser
> de código e passou a ser **de dado**.
>
> **Um número medido sobre base vazia não é gate.** Foi esse erro que quase liberou esta onda em julho
> de 2026, com número grande na mão. Nada neste documento autoriza implementação; ele existe para que,
> **no dia em que o gate abrir**, a decisão já esteja tomada e as armadilhas já estejam nomeadas — e
> para que, se o gate mandar parar, exista um registro do que foi decidido e por quê.
>
> A leitura do gate está sendo instrumentada por uma frente paralela. Quem retomar esta spec **começa
> pela §1**, não pela §3.

---

## 0. O que esta onda entrega, em uma frase

O extrato do banco entra no e1p **como arquivo OFX**, sem terceiros, e as linhas que o e1p já conhecia
**não duplicam** — elas passam a ter duas testemunhas. O que sobra dos dois lados vira a única leitura
honesta que a onda produz: *o que o banco diz e o e1p não sabe explicar*, e *o que o e1p afirma e o
banco não confirmou*.

### 0.1 O que esta onda NÃO entrega — e o corte é a decisão

O pipeline do design-mãe §4 tem dez passos. **Esta onda entrega [1]–[7]. Os passos [8], [9] e [10]
ficam fora, e §4.6/§4.7 aparecem aqui como o muro que a onda não atravessa, não como escopo.**

| Passo | Conteúdo | Nesta onda? |
|---|---|---|
| [1] upload | arquivo → `attachments` (`owner_type='bank_import'`) | ✅ |
| [2] detecção | `sniff` dos primeiros bytes → `parser_id` + encoding | ✅ |
| [3] parse | `StatementParser.parse(bytes) → ParsedStatement`, **puro** | ✅ |
| [4] normalização | centavos, data de calendário, descrição, contraparte por **regex** | ✅ |
| [5] dedupe | `dedup_hash` por linha; colisão ⇒ pula | ✅ |
| [6] enriquecimento | linha nova que casa com movimento de sistema ⇒ **enriquece**, não insere | ✅ |
| [7] persistência | INSERT + lote + checkpoint do `<LEDGERBAL>`, **um commit só** | ✅ |
| [8] sugestão | matcher determinístico → IA ranqueando → `bank_reconciliations` | ❌ **Onda 5** |
| [9] confirmação | `confirmed_at` por ato do dono | ❌ **Onda 5** |
| [10] baixa | `Payable` liberada; `Charge` **bloqueada** | ❌ **Onda 5 / Onda 6** |

Também **não** entrega:

- **CSV.** Decisão desta spec (§4.4). A onda é OFX 1.x e 2.x, e nada mais.
- **`bank_reconciliations`.** A tabela não é criada aqui. Sem os passos [8]–[10] ela não teria escritor,
  e tabela sem escritor é a mesma classe de `bank_audit.py`, citado como ativo existente em três
  documentos e que **nunca existiu**.
- **`_refresh_status`.** Continua sendo pré-requisito da Onda 5, como o ADR 0003 (Adendo 5) corrigiu.
  O `status` de `bank_transactions` continua sendo escrito só onde já é hoje.
- **Nenhuma chamada nova de IA.** §4.5 explica por que a ausência é a decisão, e não uma economia.

---

## 1. O critério de liberação, escrito para ser executado

> Esta seção é a razão de a spec existir antes da onda. **É o único artefato deste documento cujo
> consumidor é um humano num ciclo futuro** — todo o resto tem consumidor mecânico que protesta: a
> função é chamada na página seguinte, o índice é criado por migration, a invariante ganha teste no CI.
> Critério de decisão não levanta `TypeError`. Por isso a **Regra da Instanciação Obrigatória** é
> aplicada aqui em cada conjunto definido por descrição: **um membro E um não-membro, no mesmo
> parágrafo.**

### 1.1 O número, a medição e a janela

| | |
|---|---|
| **O número** | `\|divergencia_cents\|` do **bloco 1** de `GET /bank/reconciliation-report` |
| **A granularidade** | **por conta bancária**, nunca o consolidado |
| **A régua** | a banda fixa `max(R$ 50, 0,5%)`; a borda `==` é **dentro** |
| **A janela** | **3 ciclos mensais LEGÍVEIS** (§1.2). Um ciclo é **um mês de calendário no fuso do tenant**, nunca uma janela livre |
| **A autoridade** | `CicloDaConferencia` / `GET /bank/reconciliation-cycles` — **o código vence este documento** (§1.2.1) |
| **Quem decide** | o fundador, com o número na mão |

**Por que por conta, e não consolidado.** Três contas divergindo +R$ 1.200, −R$ 900 e +R$ 40 somam
+R$ 340: o consolidado parece saudável e esconde dois problemas. A topologia real do tenant do fundador
é **várias contas PJ, possivelmente em bancos diferentes** (decisão F3, 2026-07-29).

**Por que a banda é fixa e não configurável por tenant.** A divergência **é o instrumento de medição do
gate**. Régua ajustável pelo tenant invalidaria a leitura — é a Regra 7 do `CLAUDE.md`, e ela existe
literalmente para proteger esta decisão. A banda tem trabalho nomeado: **absorver os termos 1 e 3** da
decomposição (resíduo estrutural: tarifa/IOF/débito automático; e erro de data — pagou dia 12, o banco
compensou dia 13).

**O que a janela de 3 ciclos é.** `[SUPOSIÇÃO DO @PM, herdada do epic §3.1.2]` — não vem do design nem
da pesquisa. Ajustar quando houver mais tenants usando. Está marcada como suposição porque o número
**parece** derivado e não é. ⚠️ **E é por isso que o instrumento NÃO o codifica:** o endpoint devolve
até **6** ciclos, e seis é teto de **exibição**, não regra. Contar até três é ato do fundador olhando os
ciclos lado a lado — a tela não conta por ele, e não diz "gate" nem "Onda 4".

### 1.2 A pré-condição (normativa) — com membro e não-membro

A leitura do gate é válida num ciclo **se e somente se**, na janela conferida, **não existe evento
conhecido pelo e1p que moveu dinheiro numa conta real do dono sem ter gerado o `bank_transaction`
correspondente.** Operacionalmente, quatro termos, todos fechados hoje:

| # | População | Predicado | Fechado em |
|---|---|---|---|
| **P1** | Baixa de Contas a Pagar sem conta informada | `Payable`, `status ∈ {paid, scheduled}`, `paid_at::date` na janela, `bank_account_id IS NULL` | Onda 2 (8.12) |
| **P2** | Recebimento fora do trilho sem conta | `Charge`, `status ∈ {paid, scheduled}`, `paid_at::date` na janela, `transaction_id IS NULL`, `bank_account_id IS NULL`, **e** `_not_investment_yield()` | Onda 2 (8.15) |
| **P3** | Rendimento de aplicação sem perna bancária | `Charge` com `external_ref LIKE 'investment:%'` sem `bank_transaction` | Onda 2b-i |
| **P4** | Payout da Carteira liquidado sem perna bancária | ⚠️ **não é predicado de janela** — ver §1.2.1 | Onda 3, **a partir do deploy** |

> **Membro:** um `Payable` pago em 12/07 com `bank_account_id IS NULL` — cai em P1, e **o gate não
> abre**.
>
> **Não-membro:** uma `Charge` paga pelo webhook do Asaas em 12/07 — ela tem `transaction_id`, o
> dinheiro dela está na **Carteira** e não numa conta do dono, e pela **Invariante do Trilho** ela
> **nunca** terá `bank_account_id`. **Não conta — por construção, não por omissão.**

⚠️ **A exclusão do não-membro é a Regra dos Planos, não uma lacuna de preenchimento.** Foi exatamente
lê-la como lacuna que produziu a redação insatisfazível de julho (*"toda cobrança recebida precisa ter
conta informada"*), que fechava o gate **para sempre** — porque o trilho é o caminho normal do produto.
A frase era razoável **e** impossível, e nada entre as duas disparava.

⚠️ **O `_not_investment_yield()` de P2 é IMPORTADO de `receivables/service.py`, nunca reescrito.** Duas
cópias já divergiram uma vez entre dois @sm. Sem ele, a `Charge` sintética de rendimento cai inteira na
população e o gate não abre para nenhum tenant que registre rendimento — e o defeito não se anunciaria
como defeito: se anunciaria como *"a pré-condição ainda não foi satisfeita, continue corrigindo
lançamentos"*, para sempre.

### 1.2.1 ⚠️ CORREÇÃO — a §1.2 acima está INCOMPLETA, e o instrumento é a autoridade

> **Escrita em 2026-08-11, horas depois do merge desta spec (PR #107), contra o código que a frente
> paralela do gate mergeou no mesmo dia** (`bank/reconciliation.py`, `CicloDaConferencia`,
> `GET /bank/reconciliation-cycles`). **Não apague a §1.2** — ela é a genealogia da regra; esta
> subseção é o que vale.

A §1.2 diz que a leitura é válida quando **P1–P4 = ∅** na janela. **Isso é necessário e não é
suficiente**, e a lacuna é de um tipo que esta própria spec passa a §2 inteira denunciando.

**As quatro condições que o código exige** (`legivel == True` **e** o ciclo fechado):

| | Condição | Membro | Não-membro |
|---|---|---|---|
| **a** | há conta ativa | tenant com o Itaú PJ | tenant sem conta nenhuma |
| **b** | toda conta avaliada | as 3 com saldo declarado no mês | a Poupança BB sem saldo naquele mês |
| **c** | **P1+P2 e P3** zerados | mês em que toda baixa informou a conta | baixa legada sem conta |
| **d** | `start >= PRIMEIRO_CICLO_MEDIVEL` (**`2026-09-01`**) | setembro/2026 | julho/2026 |

**Os três erros da §1.2, nomeados:**

1. **P4 não é predicado de janela, e tratá-lo como tal é o erro assinatura deste épico.** A população
   de P4 é vazia **por construção nova** (409 sem conta principal + a perna bancária na mesma
   transação) — mas **só a partir do deploy da Onda 3**. Numa janela anterior existem saques sem perna
   **que ninguém conta**, e o relatório os reporta como zero **por omissão**. Um leitor da §1.2 sozinha
   conferiria julho/2026, veria P4 = 0, e leria como fato o que é ausência de medição. **É o mesmo
   defeito que a §2 desta spec denuncia, cometido pela §1 desta spec.** O código o resolve com um corte
   de data, não com um contador.
2. **Faltavam (a) e (b).** E **(a) não é redundante com (b)**: sem conta, `contas == []`,
   `contas_sem_checkpoint == 0` e os contadores dão zero — **(b) e (c) passariam por vacuidade**. É a
   família do 🟢 sobre razão bancário vazio que a Story 8.20 desfez, e a §1.2 a reintroduzia.
3. **"3 ciclos" não é codificável**, e o instrumento acertou em não codificar (ver §1.1).

⚠️ **`PRIMEIRO_CICLO_MEDIVEL` é o único valor do módulo que depende de um fato FORA do repositório** (a
data do deploy), e **erra em silêncio para o lado caro**. Tem teste de piso contra a data do merge
(2026-08-10), que é fato do repo — o deploy não é. **Ao mover a data, mova o piso junto**, e há item no
`docs/HOSTINGER-DEPLOY.md`. Consequência prática para esta onda: **nenhum ciclo anterior a setembro/2026
serve para decidir a Onda 4**, por mais limpo que o número pareça.

> **A lição, e ela é sobre esta spec.** O bloco de abertura da §1 diz que critério de decisão é *"o
> único artefato cujo consumidor é um humano num ciclo futuro"* e que por isso ninguém o contradiz.
> A §1.2 foi escrita **sem** consumidor mecânico e ficou incompleta em três pontos. Horas depois
> ganhou um — `CicloDaConferencia` —, e **ele discordou em três pontos**. A regra que fica:
> **quando existir código que decide a mesma coisa que um documento, o documento aponta para o código
> e para de repetir a regra.** A §1.2 vale como genealogia; `legivel` vale como verdade.

### 1.3 O que libera, e o que mata

| Leitura, nos 3 ciclos | Decisão |
|---|---|
| O ciclo **não é legível** (`legivel == False`, §1.2.1 — inclui P1–P4, mas não só) | **O gate não abre.** Nenhuma onda é liberada nem morta com base neste ciclo. P1/P2 se corrigem com trabalho do dono e o ciclo seguinte já vale; (d) não se corrige com trabalho nenhum |
| Divergência **dentro** da banda e estável | **MATA a Onda 4 e a Onda 5.** Para depois da Onda 3. Desfecho **bom**, não fracasso |
| Divergência **fora** da banda, recorrente, e o dono **não consegue explicar** de onde vem | **LIBERA a Onda 4** — o furo precisa ser *localizado*, não só quantificado. Sujeita também ao §1.4 |
| Divergência fora da banda **explicada** por causa conhecida e pontual — inclusive agendamento que não saiu (termo 5) | Corrigir a causa. **Não** libera |

> **Membro do "libera":** uma conta com divergência de R$ 1.847 em três ciclos seguidos, sem causa
> nomeada por ninguém.
>
> **Não-membro:** a mesma divergência de R$ 1.847 num ciclo, explicada por um agendamento que o banco
> recusou — é o termo 5 da decomposição, ele tem dono e tem correção. **Não** libera.

⚠️ **"Desfecho bom, não fracasso" está escrito porque quem ler *"o gate matou a onda"* em 2027 vai ler
como derrota.** O ADR 0003, Revisão futura (a), chama esse resultado de bom: significa que o problema
era menor do que se supunha.

### 1.4 O segundo termo: D6 não está verificado, e documentação não verifica

**Novo nesta spec.** Os dois termos são **conjuntivos**: divergência alta com D6 não verificado **não**
libera a onda — libera uma investigação de trinta minutos baixando arquivos.

> **O termo:** ao menos **um arquivo OFX real, baixado pelo fundador da conta real dele, em cada
> instituição que ele usa**, parseando e com o `<MEMO>` inspecionado à mão.
>
> **Membro:** o OFX do Itaú PJ dele abrindo e produzindo `ParsedStatement` com contraparte legível.
>
> **Não-membro:** o artigo de KB do Conta Azul dizendo que o Itaú exporta OFX. **Isso é desk research,
> e não é verificação.**

**Por que isso é um termo do gate e não um detalhe de implementação.** A pesquisa do @analyst de 29/07 é
honesta sobre o próprio alcance e escreve, sobre o conteúdo do `<MEMO>` de Pix: *"isto precisa ser
verificado empiricamente com arquivos reais antes de qualquer promessa de auto-classificação"*. Ela
também deixa **duas lacunas nomeadas**: C6 PJ não confirmado, e a API da Cora não confirmada. E o
precedente do próprio repositório é caro: no WhatsApp Evolution, **seis bugs consecutivos** vieram de
confiar no formato de request/response de um terceiro por suposição — cada um só apareceu depois que o
anterior foi corrigido e uma tentativa real avançou um passo. A regra que ficou é do `CLAUDE.md`:
*nunca confie no formato de uma API de terceiro por suposição — teste ao vivo ou leia a fonte real dela.*

**O que a pesquisa dá, e é bastante:** das 11 instituições verificadas, **9 exportam OFX**, incluindo
Itaú, Inter, Nubank **PJ**, Cora, Stone e o próprio **Asaas** (que já é integração do produto). Nubank
**PF** não exporta; C6 **PJ** é conflitante. OFX é spec aberta e royalty-free (FDX/OFX Work Group,
última versão funcional 2.3 de 2020) — **não há terceiro, contrato nem custo recorrente**, o que satisfaz
a restrição C5 sem discussão. O público-alvo é PJ, e é por isso que a cobertura basta.

---

## 2. O que esta onda mede quando o sistema está incompleto

> **A regra de método do §8 do `CLAUDE.md`:** antes de usar um número como gate, pergunte **o que ele
> mede quando o sistema está incompleto**. Se a resposta for *"mede a própria incompletude"*, ele não é
> gate — é termômetro do que ainda não foi construído, e vai sempre pedir mais construção.

Aplicada a esta onda, a resposta é pior do que "mede a própria incompletude". **É circular.**

### 2.1 A circularidade, nomeada

A **métrica secundária do épico** é `movimentos_sem_contrapartida` — a contagem que responde
literalmente ao REQ-13 (*"quantos lançamentos faltantes foram encontrados"*), e que a métrica primária
não entrega, porque a conferência mede o **tamanho em R$** do furo, não a **contagem** dos lançamentos
que faltam.

Essa métrica são os **blocos 2 e 3** da conferência. E:

1. **Antes da Onda 4 ela não existe.** `bank/reconciliation.py:85-88` declara os dois blocos fora de
   escopo com o motivo escrito: sem conciliação, **todo** movimento é `unmatched` por definição, e o
   bloco 2 devolveria *"todos os movimentos"*.
2. **Depois da Onda 4 e antes da Onda 5 ela continua degenerada**, porque `bank_reconciliations` e
   `_refresh_status` são da Onda 5. Toda linha importada permanece sem contrapartida.
3. Logo, medida **dentro** da Onda 4, ela conta **o tamanho do extrato importado** — não o tamanho do
   furo.

> **Consequência NORMATIVA: `movimentos_sem_contrapartida` NUNCA pode ser o gate da Onda 5.**
>
> Se for, repetimos com precisão o erro de julho de 2026: um número grande, aparentemente sólido,
> argumentando pela construção da feature seguinte — e a onda que produz o número é a onda cujo sucessor
> ele autorizaria. **A onda traz a própria régua que a julgaria.**

Esta é a terceira instância do mesmo padrão no épico (a divergência da Onda 1 medindo a ausência de uma
porta; `derived_balance(until=opening_date)` sendo idêntico ao saldo de abertura por construção; esta).
Elas não se parecem na superfície e são a mesma coisa: **um número que mede a própria incompletude com
aparência de fato.**

### 2.2 O que os blocos 2 e 3 podem dizer sem matcher nenhum

Existe **uma** definição de "contrapartida" que não exige matcher: **o resultado do enriquecimento**
(§5). Uma linha do OFX que enriqueceu um movimento de sistema está casada **por construção** — é a mesma
linha do banco de dados, com duas testemunhas. Daí sai uma leitura honesta:

| Estado | Significado |
|---|---|
| Linha importada que **enriqueceu** um movimento de sistema | casada, provada por construção |
| Linha importada que entrou como **INSERT** | **o banco diz, e o e1p não sabe explicar** |
| Movimento de sistema **não enriquecido**, com `posted_at` **dentro** de `[period_start, period_end]` do lote | **o e1p afirma, e o banco não confirmou** |
| Movimento de sistema não enriquecido, com `posted_at` **fora** daquele intervalo | **nada** — o arquivo não cobria esse dia |

⚠️ **A quarta linha é a que evita a acusação falsa.** Fora do período coberto pelo arquivo, ausência de
linha bancária significa *"o extrato não alcança esse dia"*, e a tela precisa dizer isso. Sem esse
recorte, importar julho faria o produto acusar todo movimento de junho. É a mesma disciplina do
`indisponivel` da Onda 1: **o sistema declara que não sabe, e `None` nunca é zero.**

⚠️ **E o número do bloco 2 no dia 1 é o extrato inteiro.** A tela **precisa dizer isso em texto**, não
exibir "43 movimentos sem contrapartida" com aparência de achado. Uma tela que grita 43 no primeiro
import destrói a confiança no sinal antes de ele ter significado — é a Regra 7 (*dentro da banda: verde
e silêncio*) aplicada a um contador em vez de a um saldo.

### 2.3 O gate da Onda 5, não-circular

Se `movimentos_sem_contrapartida` não pode decidir a Onda 5, alguma coisa tem de decidir. A proposta
desta spec é **o esforço manual medido**, que a Onda 4 produz de graça em contadores de lote:

> Quantas linhas o dono resolve **à mão** por ciclo, usando as ações por linha (§6), depois que o
> enriquecimento fez o trabalho dele?

- **Membro do "constrói o matcher":** 43 linhas resolvidas à mão por ciclo, três ciclos seguidos.
- **Não-membro:** 3 linhas por ciclo. Aí um matcher probabilístico — que **erra**, e cada erro numa
  conta a pagar exige um estorno — é troca ruim, e a Onda 5 morre pelo mesmo critério de custo que
  poderia matar a 4.

Isso não é circular porque o esforço manual é medido **sobre o conjunto que o enriquecimento já
reduziu**, e o enriquecimento é determinístico. Não é o tamanho do extrato: é o tamanho do resíduo.

---

## 3. Arquitetura: o parser como strategy, e a manutenção perpétua

### 3.1 A forma

Contrato único, `ParsedStatement`, com os parsers **puros** — nenhum acesso a `Session`, nenhum I/O.
Mesma disciplina de `financial_intelligence/engine.py`, e pela mesma razão: testável com um `bytes` de
fixture, sem banco, sem rede. **Zero chamada de rede em todo o pipeline** é critério de aceite.

```python
# app/modules/bank/parsers/base.py — ILUSTRATIVO (design-mãe §4.1)
class ParsedLine(NamedTuple):
    posted_at: date
    amount_cents: int          # com sinal
    raw_description: str
    fitid: str | None
    balance_after_cents: int | None
    counterparty_name: str
    counterparty_document: str
    pix_end_to_end_id: str | None

class StatementParser(Protocol):
    id: str
    def sniff(self, filename: str, head: bytes) -> int: ...   # 0 = não sei; 1..100 = confiança
    def parse(self, raw: bytes) -> ParsedStatement: ...
```

Duas implementações, e só duas:

| | OFX 1.x (`ofx-sgml`) | OFX 2.x (`ofx-xml`) |
|---|---|---|
| Cabeçalho | `OFXHEADER:100`, linhas `CHAVE:VALOR` até linha em branco | `<?xml …?>` + `<?OFX OFXHEADER="200" …?>` |
| Corpo | SGML: **fechamento opcional**, valor até a próxima tag | XML bem-formado |
| Estratégia | parser tolerante próprio: separa header, tokeniza `<TAG>valor`, monta pilha **ignorando fechamentos ausentes** | `xml.etree` com **resolução de entidade desligada** (defesa XXE) |

Campos lidos: `<STMTTRN>` → `<DTPOSTED>`, `<TRNAMT>`, `<FITID>`, `<MEMO>`, `<NAME>`, `<TRNTYPE>`;
`<LEDGERBAL>` → `<BALAMT>`, `<DTASOF>`; `<BANKACCTFROM>` → `<BANKID>`, `<BRANCHID>`, `<ACCTID>`. **A
superfície necessária é essa, não a spec inteira do OFX.**

### 3.2 Parser próprio, e `ofxparse` rejeitada com o motivo escrito

| Opção | Veredito |
|---|---|
| `ofxtools` | **Fora.** GPL-3.0 num SaaS proprietário |
| `ofxparse` (MIT) | **Rejeitada.** Tem tokenizador SGML surrado por arquivos reais, mas está **inativa**: adotá-la significa fork na primeira divergência, e o fork herda abstrações que não mapeiam para `ParsedStatement`. **É parser próprio com passos extras** |
| **Parser próprio mínimo** | **Escolhida.** OFX 1.x é SGML tolerante e raso; a superfície é a da §3.1. Zero dependência, zero questão de licença |

⚠️ **A rejeição está escrita porque *"por que não usar a lib?"* volta como sugestão daqui a seis meses**,
e sem o motivo registrado a resposta seria refeita do zero — ou aceita.

### 3.3 O que acontece quando um banco muda o layout

**O strategy protege contra troca de FORMATO. O que quebra na prática é deriva de DIALETO dentro do
OFX** — e essa distinção é a razão de esta subseção existir. Um banco que passa a omitir `<TRNTYPE>`, ou
que troca CP1252 por UTF-8, **não pede classe nova**: passa reto pelo `sniff`, entra no parser certo, e
então há três modos de falha:

| Modo | Comportamento | Veredito |
|---|---|---|
| `sniff` não reconhece nada | recusa o arquivo, **nada é gravado**, mensagem acionável | barulhento e **seguro** |
| `sniff` reconhece, `parse` estoura | lote `failed` + `error_message`, **zero linha** | barulhento e **seguro** |
| **`sniff` reconhece, `parse` "funciona" e produz dado errado** | grava lixo em `raw_description`, que é **imutável** | **o único perigoso** |

O terceiro modo é encoding e formato de data. Quatro defesas:

1. **Cadeia de encoding declarada:** `CHARSET/ENCODING do header → cp1252 → latin-1 → utf-8-sig`, e o
   encoding **efetivamente usado é gravado no lote**.
2. **Fail-loud de mojibake:** se a decodificação produzir caractere de substituição (`�`) em **mais de
   1%** do texto, o import **falha** com mensagem acionável (*"o arquivo parece estar em outra
   codificação"*) em vez de gravar lixo. `raw_description` é imutável — lixo ali é lixo **para sempre**.
3. **`<DTPOSTED>` usa só os 8 primeiros dígitos.** O campo vem como `YYYYMMDDHHMMSS[±h:TZ]`; hora e
   offset são **ignorados**. Converter para UTC e voltar é exatamente o bug que fez eventos sumirem da
   Agenda; aqui a conversão não é feita, e `posted_at` já é `Date` e não `DateTime` justamente para o
   tipo não permitir o erro.
4. **`posted_at` futuro ⇒ 422**, e é normativo (design da Onda 2 §4.2):
   > *O e1p pode afirmar o futuro do que ele mesmo agendou; não pode afirmar o futuro do que outro
   > atestou.* Um OFX descreve o que já aconteceu. Data futura num arquivo importado é erro de parser ou
   > arquivo corrompido — **não é fato**. Se um dia aparecer caso legítimo (débito pré-autorizado
   > exibido no extrato), o tratamento honesto é **recusar e mandar um humano olhar**, nunca aceitar em
   > silêncio uma afirmação sobre o futuro vinda de uma fonte que não pode conhecê-lo.

   Isto cai naturalmente da regra que já existe: `SOURCES_EXTERNA` recusa futuro, `SOURCES_SISTEMA`
   aceita. `ofx` já está em `SOURCES_EXTERNA` desde a `0059`, então **nenhuma regra precisa mudar** —
   é a terceira vez no épico em que escrever contra o conjunto, e nunca contra o valor solto, paga.

### 3.4 O corpus de regressão é entregável, não conveniência

**Novo nesta spec.** As quatro defesas acima cobrem *"o arquivo mudou de um jeito que quebra"*. Nenhuma
cobre *"o arquivo mudou de um jeito que passa"*. O que cobre é um **corpus de arquivos OFX reais,
versionado no repositório como fixture, com gate no CI**.

- Cada instituição verificada no §1.4 contribui **pelo menos um arquivo real**, anonimizado.
- O gate roda os parsers sobre o corpus inteiro e compara com um `ParsedStatement` esperado, campo a
  campo. Uma mudança no tokenizador que "melhora" um dialeto e quebra outro reprova no CI.
- **O corpus é o ativo de manutenção da onda.** Sem ele, cada correção de dialeto é uma aposta.

⚠️ **Anonimização do corpus é obrigatória e é trabalho manual.** Um OFX real carrega nome e
frequentemente documento de contraparte — pessoas que nunca contrataram com a e1p (§4). Um arquivo real
commitado sem tratamento é vazamento de PII **no repositório**, permanente e público no histórico do
git. O corpus é sanitizado à mão, com `[NOME]`/`[DOC]` no lugar, e a fixture guarda **o formato**, que é
o que se quer testar.

### 3.5 O custo, sem eufemismo

Do ADR 0003, Consequência 1, citada porque a spec não deve amaciá-la:

> OFX 1.x é SGML pré-XML com dialetos por instituição; encoding varia; formato de data varia. Cada banco
> novo suportado é trabalho novo, **para sempre**, e o trabalho é **reativo** — o banco muda o layout e a
> e1p descobre pelo relato de um usuário, depois que o import quebrou.
> `[ESTIMATIVA: 2 a 3 rodadas de correção por banco novo]`

Isto é o preço direto de *"não podemos ficar contando com serviços de terceiros"*: a e1p troca um custo
**monetário e previsível** por um custo **de engenharia, recorrente e imprevisível**. A troca é legítima
e foi feita de olhos abertos — mas **não é de graça, e chamar de graça seria desonesto.**

**Gatilho de desistência (ADR, Revisão futura (c)):** passar de **~1 correção por trimestre** ⇒ congelar
em **um** formato canônico e aceitar cobertura parcial. Está no §8 desta spec como condição nomeada.

---

## 4. A IA: onde é proibida, e por que o anonimizador volta a ser obrigatório

### 4.1 A tabela do §4.6, com o muro desta onda aplicado

| Etapa | O design-mãe §4.6 permite? | **Nesta onda** |
|---|---|---|
| Escolher o parser / decodificar | **Não** — determinístico | **Não**, e é passo desta onda |
| Extrair contraparte do `raw_description` | Sim, **sugerindo** | **Não.** Só a regex determinística (§4.2) |
| Classificar (`chart_account_id`, `cost_center_id`) | Sim, sugerindo | **Fora de escopo** (passo [8]) |
| Ranquear candidatos de vínculo | Sim, sugerindo | **Fora de escopo** (passo [8]) |
| **Confirmar** um vínculo | **NÃO** — `confirmed_at` só por ato de usuário autenticado | **Fora de escopo** (passo [9]) |
| **Dar baixa** em `Payable` | **NÃO** — reversível, mas é ato de dono | **Fora de escopo** (passo [10]) |
| **Dar baixa** em `Charge` | **NÃO — e nem o usuário** | **Bloqueada** (§4.6 desta spec) |
| Narrar a conferência | Sim | **Sim, com uma contenção** (§4.4) |

### 4.2 Por que a IA fica INTEIRA fora, e a ausência é a decisão

Com os passos [8]–[10] fora, `suggested_by='ai'` **não tem consumidor**. Escrever a extração de
contraparte por IA aqui seria construir capacidade que nada lê — e esse é o defeito que este repositório
já pagou **quatro vezes**:

- `core/whatsapp/capabilities.py` existiu desde a Onda 0 com **zero call sites em produção**, e a
  docstring **afirmava** que três consumidores o consultavam. Nenhum dos três havia sido escrito.
- `app/scripts/bank_audit.py` foi citado como ativo existente em **três documentos** e nunca existiu; o
  epic mandava *"não recriar"* um script inexistente.
- `days_since_last_declared_balance` foi implementada **sem consumidor**.
- `service.set_primary` existia desde a Story 8.7 com docstring dizendo para quem foi escrita, **sem
  rota, sem botão e sem um único chamador** — o dono não conseguia eleger conta principal, e o defeito
  só apareceu quando a Onda 3 precisou dela.

> **A regra que fica, e que esta seção aplica:** **capacidade nasce com o consumidor no mesmo passo.**
> A IA na Onda 4 não é economia de custo — é a recusa de criar a quinta instância.

A extração de contraparte fica **100% regex determinística** sobre o `<MEMO>`/`<NAME>`, gravando
`counterparty_name`/`counterparty_document`. O que a regex não extrair fica **vazio**, e vazio é honesto:
não há placeholder, não há palpite.

### 4.3 Onde a IA fica PROIBIDA por razão que não é escopo

Duas proibições sobrevivem a qualquer onda, e estão aqui para não serem reabertas quando a Onda 5 chegar:

1. **A IA nunca escreve `confirmed_at`.** Confirmação é ato de usuário autenticado. Não é uma questão de
   confiança no modelo: é que a confirmação é o **único** ponto do pipeline que autoriza mexer em
   dinheiro, e um ato do dono é o que distingue *"o sistema achou"* de *"o dono decidiu"*.
2. **A IA nunca dá baixa.** Nem em `Payable` (reversível, mas é ato de dono), nem em `Charge` — que está
   bloqueada até para o usuário (§4.6).

### 4.4 O anonimizador volta a ser obrigatório — e por que na Onda 2 não era

Esta onda **não faz nenhuma chamada nova de IA** (§4.2) e **mesmo assim** o anonimizador volta ao centro.
O contraste com a Onda 2 é o argumento:

| | Onda 2 | **Onda 4** |
|---|---|---|
| Campos novos de texto | `operation_nature` (vocabulário sugerido), `user_description` | `raw_description`, `counterparty_name`, `counterparty_document` |
| Quem escreveu | **o dono**, sobre o próprio negócio | **o banco**, sobre um **terceiro** |
| Mutabilidade | editável | **`raw_description` é imutável** — é evidência |
| PII de quem nunca contratou com a e1p | não | **sim** (ADR 0003, Consequência 3) |

Por isso a Regra de Ouro nº 2 se aplica com força aqui e não se aplicava lá. O consumidor de IA que já
existe e que **alcança** esses campos é o narrador da conferência (`financial_intelligence/ai_narrator.py`).
No dia em que o bloco 2 for narrado, nome de contraparte entra no payload que vai para o Claude.

### 4.5 A verdade desconfortável: o anonimizador não mascara nome

**Não basta escrever *"passa pelo `core/anonymizer` e está resolvido"*.** `core/anonymizer.py` é **100%
regex sobre PII estrutural** — CPF/CNPJ, e-mail, telefone, cartão. **Sem NER.** Nome próprio, razão
social e nome de contraparte **passam intactos**. É a dívida 🔴 do `CLAUDE.md` §6.1, com risco residual
**aceito pelo fundador em 2026-07-11** sob gate escrito: *não expor com `ANTHROPIC_API_KEY` real em
produção sem o hardening (story própria, escopo Financeiro + Jurídico) ou aceite adicional por escrito.*

Consequências desta spec, e a segunda é a que tem dente:

1. **O anonimizador é obrigatório em todo caminho que toque `raw_description`/`counterparty_*`**, com
   teste de espião no `core/ai`. Isso permanece — e o `counterparty_document`, que é o campo com CPF de
   terceiro, **é justamente o que o regex cobre bem**.
2. ⚠️ **O bloco 2 NÃO é narrado por IA enquanto o hardening do anonimizador não existir.** A frase do
   bloco 2 é **template determinístico**. O padrão já existe duas vezes no produto (sem
   `ANTHROPIC_API_KEY` o briefing sai íntegro por template; `ai_narrator` só reformula o que o motor
   determinístico calculou), então **custa zero**.
3. ⚠️ **O teste de espião prova ausência de PII ESTRUTURAL, não de nome** — e a spec diz isso em vez de
   deixar um teste verde sugerir cobertura que não existe. É a família do §2 da Onda 2: *um teste que
   passa e não prova nada.* Aqui ele prova algo real e menor do que o nome dele sugere.

**Alternativa registrada e não escolhida:** aceitar o risco residual também aqui, como em 2026-07-11, e
narrar o bloco 2 por IA. Foi considerada e recusada por uma diferença de população: em 2026-07-11 o dado
exposto era **nome de contrato e nome de aplicação do próprio dono**; aqui é **nome de terceiros que
nunca contrataram com a e1p**, em volume de dezenas por mês e crescendo com o uso. O aceite anterior não
cobre esta população, e estendê-lo por analogia seria decidir por ele.

### 4.6 O bloqueio duro: baixa de `Charge` a partir do extrato

Fora de escopo desta onda por construção (não há passo [10]) — e **bloqueada também para a Onda 5**, pelo
motivo que não é de escopo:

> `platform_earnings` (o ledger global de GMV do Master) **não guarda vínculo de volta** à
> `Transaction`/`Charge` de origem. Pagar → estornar → pagar de novo reportaria GMV duplicado: reverter e
> repagar 3× uma cobrança de R$ 100 reportaria R$ 400 de GMV. O estorno de Contas a Receber foi
> **implementado, revisado duas vezes e removido antes do merge** por isso.

**Hoje não existe caminho seguro de DESFAZER uma baixa de cobrança.** E um match de extrato **vai**
produzir baixas indevidas — é estatística, não pessimismo. Portanto a baixa automática ou semiautomática
de `Charge` a partir de um movimento bancário fica bloqueada até o vínculo
`platform_earnings → transaction` existir. Pré-requisito absoluto da Onda 6, e o mesmo que destravaria o
estorno de cobranças.

**O que É permitido, e entrega quase todo o valor** (quando a Onda 5 chegar): vínculo **informativo**
movimento ↔ `charge` já paga; e **sinalizar** na conferência *"esta cobrança está em aberto há 47 dias e
existe um crédito de mesmo valor no extrato — o cliente pagou por fora?"*. Informação **neutra ao dono, e
nunca reportada ao Master** (decisão D7): recebimento fora do trilho é vazamento de receita da
plataforma, e transformar o sinal em produto de plataforma mudaria a relação com o usuário.

---

## 5. Dedupe, idempotência, e o defeito que o §4.5 do design-mãe não vê

### 5.1 Os dois índices, e por que não colidem

Conferido contra o código (`bank/models.py:297-351`):

| Índice | Forma | Garante |
|---|---|---|
| `uq_bank_transactions_dedup` | `(tenant_id, bank_account_id, dedup_hash)`, único, **total** | idempotência **do arquivo** — é o que esta onda usa |
| `uq_bank_transactions_origin` | `(tenant_id, source, origin_id)` único **parcial**, `WHERE origin_id IS NOT NULL` | idempotência **da origem** |

⚠️ **A idempotência da Regra da Origem é o índice parcial, NUNCA o `dedup_hash`.** No manual,
`_manual_dedup_hash` chaveia no **UUID da própria linha**, único por construção: **nunca deduplica
nada**. Ele existe para satisfazer o `NOT NULL` até que este pipeline chegue. E
`origin_dedup_hash = sha256(f"{source}|{origin_id}")` é **sem** `bank_account_id`, de propósito — trocar
a conta de um lançamento é **UPDATE da mesma linha**, e com a conta no hash deixaria de ser.

`tenant_id` é a primeira coluna dos dois porque **índice único é global e não respeita RLS**: sem ele o
tenant B receberia violação inexplicável causada por dado do tenant A — bug **e** vazamento de
existência. Lição já paga na Story 8.2.

### 5.2 A fórmula do `dedup_hash` da importação

```
se fitid presente:   dedup_hash = sha256(f"{bank_account_id}|fitid|{fitid}")
senão:               dedup_hash = sha256(f"{bank_account_id}|c|{posted_at}|{amount_cents}"
                                         f"|{normaliza(raw_description)}|{ordinal_no_dia}")
```

- `normaliza` = upper, colapsa espaços, remove pontuação — o mesmo lançamento reexportado varia em
  espaçamento.
- `ordinal_no_dia` = índice entre as linhas **idênticas** (mesma data, mesmo valor, mesma descrição
  normalizada). Sem ele, **dois Pix de R$ 50 para a mesma pessoa no mesmo dia colidiriam e o segundo
  sumiria — um furo criado pelo próprio sistema**, exatamente o que a onda existe para combater.
- ⚠️ **O ordinal é calculado contra o que JÁ EXISTE no banco naquele dia, não só contra o arquivo** —
  senão um extrato parcialmente sobreposto reinseriria duplicatas.
- A **constraint única é a garantia final**: mesmo que a lógica falhe, o banco recusa. Fail-closed, no
  espírito da RLS.

**Reimportar o mesmo arquivo:** `file_sha256` já existente ⇒ **`200`** com `{lines_new: 0,
lines_duplicate: N}` e *"este extrato já foi importado em DD/MM"*. **Não é erro** — é o comportamento
esperado de quem não lembra se importou. **Período sobreposto é o caminho normal, não o excepcional:** o
usuário **vai** importar 01–31/jul depois de 15/jun–15/jul, e só 16–31/jul entra.

### 5.3 O enriquecimento cobre TRÊS das cinco origens — e deveria cobrir cinco

O design-mãe §4.5 manda procurar movimento existente com `source in ('transfer','yield','payout')`.
**Faltam `payable` e `charge`**, que são de longe as origens mais frequentes — a Onda 2 existe para
produzi-las. A razão é histórica e não é um erro de julgamento: **o §4.5 foi escrito antes de a Onda 2
existir**, quando só três origens de sistema eram previstas.

> **A correção: a regra é escrita contra `SOURCES_SISTEMA`, nunca contra valores soltos de `source`.**
> É a regra que o repositório já tem, e é a terceira vez que ela paga — em 2b-i, `SOURCE_YIELD` já
> estava no conjunto desde a `0059` e **nenhuma regra precisou mudar**; na Onda 3, o mesmo com
> `SOURCE_PAYOUT`.

O predicado do enriquecimento, então: movimento na **mesma conta**, `source in SOURCES_SISTEMA`,
`status <> 'ignored'`, `fitid IS NULL`, **mesmo `amount_cents`**, `posted_at` dentro de **± 3 dias**.

- **Exatamente um candidato** ⇒ **enriquece** e **não insere**; conta em `lines_enriched`.
- **Mais de um candidato** ⇒ **não adivinha**: insere a linha e marca ambas com `user_description`
  sinalizando *"possível duplicata"*. O dono resolve. É o tipo de decisão que a §4 diz que a máquina não
  toma sozinha.
- **A janela de ±3 dias reusa a constante da guarda de contagem dupla da Onda 2**, que foi escolhida
  igual **de propósito**: *"dois números para 'estas duas linhas são o mesmo dinheiro?' seriam duas
  respostas quando o matcher chegar."* `[SUPOSIÇÃO parametrizável, herdada do §4.5]` — cobre TED/Pix
  agendado que compensa no dia útil seguinte.

### 5.4 O defeito: `sync_origin_movement` desfaz o enriquecimento

**Achado desta spec, verificado no código.** `sync_origin_movement` é o **escritor único** de
`SOURCES_SISTEMA` e, a cada ressincronização, **reescreve `raw_description`** (`bank/origin.py:298`) **e
`dedup_hash`** (`bank/origin.py:303`). A docstring diz por quê, e está correta no próprio escopo: numa
linha de sistema *"quem disse foi o próprio e1p, e a Regra da Origem (c) manda o movimento espelhar o
lançamento"*.

Estenda o enriquecimento a `payable`/`charge` (§5.3) e as duas regras colidem:

1. O import grava o texto do banco e o hash do OFX numa linha `source='payable'`.
2. A **próxima mutação** daquela conta a pagar — *baixar, trocar conta, trocar data, estornar, repagar,
   **cancelar*** — chama o sincronizador, que **sobrescreve os dois**.
3. **Efeito A:** a prova documental do banco é apagada e substituída pela descrição que o e1p mesmo
   escreveu. `raw_description` é imutável **contra o usuário e contra a IA**, não contra o
   sincronizador.
4. **Efeito B, pior:** com o `dedup_hash` de volta ao `origin_dedup_hash`, **reimportar o mesmo arquivo
   não colide e insere a linha duplicada.** E o §5.2 declara reimportar como o caminho **normal**.

⚠️ **O Efeito B é silencioso e a duplicata é indistinguível de um furo real na conferência** — um
movimento a mais no banco sem contrapartida no sistema tem exatamente a aparência do que a onda existe
para achar. **É a onda produzindo o próprio falso positivo.**

⚠️ **E a lista de caminhos de mutação já falhou uma vez como garantia.** O design §3.3 enumera **cinco**;
o gate achou o **sexto** (cancelar) da pior forma — cancelar uma conta a pagar agendada deixava o
movimento órfão, e `test_cache_de_movimento_nunca_diverge_do_origin_id` **passava**, porque cobria
exatamente os cinco enumerados. **A lista era a garantia, e a garantia estava incompleta.** Quem
implementar esta onda **não** deve escrever a correção contra a lista de caminhos: deve escrevê-la no
sincronizador, que é o ponto por onde todos passam.

**As três saídas, e a escolhida:**

| Saída | Veredito |
|---|---|
| Coluna nova para o texto do banco | **Rejeitada.** Migration + quarto campo de texto, e cria **duas versões da descrição** — a classe "segunda fonte de verdade" que o épico combate desde a Onda 0 |
| **`sync_origin_movement` não sobrescreve `raw_description`/`dedup_hash` quando a linha já foi enriquecida (`fitid IS NOT NULL`)** | **ESCOLHIDA.** Zero migration; **uma condição no escritor único**, que já tem allowlist de chamadores e gate próprio |
| Linha enriquecida vira `source='ofx'`, `origin_id=NULL` | **Rejeitada.** Quebra o cache `payables.bank_transaction_id`, que `test_cache_de_movimento_nunca_diverge_do_origin_id` guarda; e destrói o vínculo com o lançamento |

**O nome da decisão, no vocabulário que o épico já tem:** *enriquecida, a linha passa a ter **duas
testemunhas**, e na descrição vence **"o que o banco diz"**.* É a mesma separação que a correção UX-001
fez nas colunas da Conferência.

**O gate:** ressincronizar uma linha enriquecida (pelos seis caminhos) e asserir que o texto do banco e o
`dedup_hash` do OFX **sobrevivem** — com **controle positivo**, senão o teste passa verde numa
implementação que nunca enriquece nada.

⚠️ **Isto significa que a Onda 4 toca o escritor único da Regra da Origem.** Não é mudança de passagem: é
a função guardada por allowlist, com gates de AST e de texto cru em volta. Quem implementar deve tratá-la
como o item de maior risco da onda — o lugar do risco **mudou de lugar** em relação ao que todo documento
anterior supunha (era o parser).

### 5.5 O único lugar onde `source` legitimamente vira `'ofx'`

Não é o enriquecimento — é o **desligamento da origem**, e o design da Onda 2 §4.5 já o desenhou:

> O estorno **APAGA** o movimento, porque um movimento bancário é a afirmação *"este dinheiro saiu"* e,
> estornado, o sistema não afirma mais isso. **Mas o DELETE só acontece enquanto a linha for puramente
> sintética** — `fitid IS NULL`, `import_batch_id IS NULL`. Se a Onda 4 já a **enriqueceu**, o estorno
> **não apaga**: ele **desliga a origem** (`origin_id = NULL`, `source = 'ofx'`, `status = 'unmatched'`)
> e a linha volta a ser movimento **órfão do extrato** — o que é **verdade**: o dinheiro saiu mesmo, e
> agora o sistema não sabe por quê. **Degradação honesta.**

A coerência com o §5.4 é exata: **o `source` vira `'ofx'` quando a origem é desligada, nunca quando a
linha é confirmada pelo banco.** E "confirmada pelo banco" **não precisa de coluna**: é derivado de
`fitid IS NOT NULL` / `import_batch_id IS NOT NULL`. O produto já recusou rótulos materializados que
podem divergir do fato — não existe coluna `payment_route`, e `bank_transfers.kind` é derivado.

⚠️ **Nota de alcance:** hoje o ramo *"origem desliquidada → apaga"* é **inalcançável** para `yield`
(não há estorno de rendimento) e para `payout` (não há estorno de saque) — declarado nas duas ondas em
vez de fingir cobertura. Esta onda **não** muda isso; ela ativa o **segundo** ramo (desligar em vez de
apagar) para `payable` e `charge`, que é onde há estorno de verdade.

---

## 6. Superfícies

**A porta de entrada.** `POST /bank/accounts/{id}/imports` **está revogado como porta primária** (design
da Onda 2 §1.2, a varredura do REQ-12): o arquivo entra pela infraestrutura de anexo que já existe
(`owner_type='bank_import'`, `owner_id=<batch_id>`, via `core/storage.py` com fallback Postgres), e **a
conta é escolhida DEPOIS do upload**. Reusa a bandeja que o comprovante mobile já provou em produção, e
mantém a prova documental da importação.

**A tabela nova é uma só:** `bank_import_batches` (design-mãe §2.5) — `file_sha256`, `parser_id`,
`encoding`, `period_start/end`, `lines_total/new/duplicate/enriched`, `status ∈ {parsed, applied,
failed}`, `error_message`. RLS `FORCE`, `tenant_id` na frente de todo índice. **`ADD TABLE` é DDL puro,
sem `UPDATE`** — a armadilha do backfill silencioso sob `FORCE RLS` (`0046`/`0066`–`0069`/`0073`) **não a
alcança**, e essa é a quarta onda seguida com essa propriedade.

**A tela.** Continua sendo `/financeiro/conferencia`, **fora da sidebar**, alcançada pelo sinal do
Diagnóstico — conferência é resposta a um sinal, não tarefa de rotina; vira item de menu, vira peso de
ERP. **A frase vem antes da tabela.** O import é uma ação **dentro** dela, não uma tela nova.

**As ações por linha** (o que substitui o matcher nesta onda): criar conta a pagar **já baixada**,
marcar como transferência, ignorar, editar `user_description`/`operation_nature`. Todas manuais, todas
já existentes ou triviais sobre o que existe.

⚠️ **`operation_nature` não entrou em `BankTransactionUpdate`** (dívida verificada aberta na Onda 2):
preencher a natureza de um movimento pela tela de edição **não é possível hoje**. Como esta onda cria
dezenas de movimentos externos por mês, a dívida deixa de ser cosmética — **fechá-la é pré-requisito da
utilidade das ações por linha**, e a spec a nomeia em vez de descobri-la na implementação.

⚠️ **Aceite em ~360px é obrigatório, medido, com screenshot, ANTES do merge.** A lição da 2b-ii é
específica e se aplica com força a uma tela de extrato: *em 360px uma tabela de 3 colunas não cabe, e a
saída não é fazer a rolagem funcionar melhor — é não precisar dela.* Num extrato o **valor é a
informação**, e informação que exige rolagem lateral para existir é informação que o dono não lê. Lista
(`<ul>`), nunca `<table>`; data e descrição empilhadas num bloco `min-w-0`, valor à direita com
`whitespace-nowrap`. **Nenhuma asserção de classe CSS pega isto** — `toContain("flex-wrap")` passou com
a `FilaPagamentosPage` quebrada em produção por duas sessões, e três PRs de campo (#56, #58, #89) foram
pagos por isso. **Mede-se com Vite + `page.route` + `boundingBox`, sem backend.**

---

## 7. Riscos

| Risco | Prob. | Impacto | Mitigação |
|---|---|---|---|
| **Parser por banco vira manutenção perpétua** | **Certeza, não risco** | Médio | Strategy; começar com **2** formatos; corpus de regressão (§3.4); gatilho de congelamento (§3.5) |
| **`sync_origin_movement` desfazendo o enriquecimento** (§5.4) | **Alta se não corrigido** | **Alto — a duplicata parece um furo real** | Condição no escritor único + gate com controle positivo sobre os **seis** caminhos |
| **Dupla contagem movimento sintético × linha do extrato** | **Alta** | Alto | Enriquecimento contra `SOURCES_SISTEMA` (não contra três valores) + constraint única + *"possível duplicata"* quando ambíguo |
| **Mojibake permanente em `raw_description`** | Média | Alto (imutável) | Cadeia de encoding + fail-loud >1% de `�` |
| **PII de terceiro vazando para a IA** | Média | Alto (LGPD) | Anonimizador obrigatório + **bloco 2 não narrado** até o hardening (§4.5) |
| **PII de terceiro vazando no REPOSITÓRIO** pelo corpus | **Alta se esquecido** | **Alto e permanente** (histórico do git) | Sanitização manual obrigatória do corpus (§3.4) |
| **`movimentos_sem_contrapartida` virando o gate da Onda 5** | **Alta** — é a leitura natural | **Alto — repete o erro de julho** | Proibição normativa (§2.1) + o gate alternativo (§2.3) |
| **O contador do bloco 2 no dia 1 lido como achado** | Alta | Médio (destrói confiança no sinal) | Texto antes do número (§2.2) |
| **Produto virar ERP contábil** | Média | **Existencial para a tese** | Tela fora da sidebar; a frase antes da tabela; a conferência funciona **sem** import |
| **Extrato de 60 dias impedindo carga histórica** | **Certeza** | Baixo | Não é defeito: impõe **cadência**. A onda não promete histórico |
| **Valor cortado em 360px** | **Média — já aconteceu 3×** | Alto | Lista em vez de tabela; aceite medido com screenshot (§6) |

---

## 8. O que faria esta onda NÃO valer a pena

> Esta seção é gêmea da §1: se a §1 diz o que libera, esta diz o que **desautoriza**, inclusive **depois**
> de liberada. Cinco condições vêm do ADR 0003 (Revisão futura a–e); **duas são desta spec.**

1. **Divergência dentro da banda e estável por 3 ciclos.** O problema era menor do que se supunha. Para
   depois da Onda 3. **Desfecho bom.**
2. **Nenhum banco relevante do público-alvo exportando OFX.** O caminho de arquivo morre; as Ondas 0–3
   sobrevivem porque não dependem de arquivo. **Membro:** o fundador abrir o internet banking do Itaú PJ
   e o botão de exportar OFX não existir. **Não-membro:** um artigo de KB dizendo que existe.
3. **Manutenção passando de ~1 correção por trimestre.** Congelar em um formato canônico e aceitar
   cobertura parcial.
4. **A tela de extrato virar a mais acessada do financeiro.** O teto de simplicidade foi rompido e o
   produto virou contábil. Ação: rebaixar a tela, reforçar a frase. **Isso é observável e deve ser
   observado** — o design-mãe §9 já nomeia esse sintoma.
5. **Aparecer obrigação legal exigindo conciliação formal fechando em zero.** O design continua
   servindo, mas o teto muda por força externa e a decisão vira *"atender obrigação"*, não *"dar
   clareza"* — reabre a conversa de **posicionamento**, não só de escopo.
6. **(desta spec) O caminho comprovante + OCR fechar o termo 4 antes.** Aqui a onda não fica "cara
   demais": ela fica **sem trabalho**. Ver §9.
7. **(desta spec) O conjunto órfão medido na própria Onda 4 estabilizar em poucas linhas por ciclo.**
   Isso **mata a Onda 5**, não a 4 — e é o gate não-circular da §2.3.

---

## 9. A alternativa barata, e por que ela pode bastar

**O que já se consegue HOJE, sem import nenhum:**

1. **A conferência de um número** — bloco 1, por conta, com banda. É o **pedido literal do fundador**
   (R1: *"de saldo batendo é uma conferência para achar possível furos"*), e está em produção desde a
   Onda 1. Ela **quantifica** o furo.
2. **A Onda 2 já eliminou por construção a maior população de furo.** Toda baixa de Contas a Pagar
   escreve o movimento bancário na mesma transação; recebimento fora do trilho também. O que sobra para
   o import achar é o **termo 4** da decomposição — *contas pagas fora do e1p e nunca cadastradas em
   lugar nenhum*.
3. **A captura na origem já está em produção.** O comprovante entra pelo **share sheet do celular**: o
   dono compartilha direto do app do banco e a rota `link` **anexa e dá baixa num commit só**. Isso é o
   gatilho (b) do ADR 0003 (*"a resposta para completude passa a ser captura na origem"*) — e o custo
   para o dono é **um toque, no momento em que ele já está no app do banco**, contra os ~5 minutos por
   mês baixando OFX, que o design-mãe §9 chama de **"o pedido mais caro do design"** e o único item que
   **constrói** em vez de **confirmar**.
4. **Localização parcial já existe sem parser:** o `debito_nao_confirmado` do Diagnóstico nomeia o débito
   suspeito quando o valor casa com a divergência (`|valor − divergência| <= max(R$ 50, 10%)`).

**O que falta para (3) fechar o termo 4:** OCR/IA lendo o comprovante e sugerindo fornecedor, valor e
data — **dívida já registrada em Contas a Pagar**, estimada em `~0,5 onda`, **sem dependência externa
perpétua** e **sem PII de terceiro entrando no banco de dados**. Compare com as `~2,5 ondas` da Onda 4
mais o custo permanente.

> **A frase que decide:** **se o termo 4 for pequeno, a alternativa barata basta e a Onda 4 é
> over-engineering.**
>
> E há uma assimetria que favorece a alternativa barata mesmo quando o termo 4 é grande: o comprovante
> resolve o furo **no momento em que ele acontece**, e o import o resolve **um mês depois**. A onda cara
> compra *localização retroativa*; a barata compra *ausência do furo*. **Um mutirão mensal de
> reconciliação é um sintoma, não um recurso.**

⚠️ **O que a alternativa barata NÃO resolve, e é honesto declarar:** ela depende de o dono se lembrar de
compartilhar o comprovante. O import não depende de memória nenhuma — o extrato traz o que aconteceu,
inclusive o que o dono esqueceu **e não sabe que esqueceu**. Essa é a única vantagem estrutural da Onda 4
sobre a captura na origem, e é uma vantagem real. **O tamanho dela é exatamente o termo 4**, e é por isso
que o gate mede o que mede.

---

## 10. Esforço

| Parte | `[EST.]` |
|---|---|
| `bank_import_batches` + upload/porta de entrada | 0,3 onda |
| `StatementParser` + `OfxSgmlParser` + `OfxXmlParser` + encoding fail-loud | 0,8 onda |
| Corpus de regressão sanitizado + gate no CI | 0,3 onda |
| Dedupe (§5.2) | 0,3 onda |
| Enriquecimento sobre `SOURCES_SISTEMA` + a correção do §5.4 | 0,5 onda |
| Blocos 2 e 3 + o recorte de período (§2.2) | 0,4 onda |
| Ações por linha + `operation_nature` no update | 0,3 onda |
| Aceite medido em 360px | 0,1 onda |
| **Total** | **~3,0 ondas** |

Contra as **2,5** que o design-mãe estimava. A diferença tem duas causas nomeadas: o **corpus** (que o
design-mãe não previa) e a **correção do §5.4** (que ele não via). **Menos CSV**, que saiu do escopo.
`[EST.]` calibrada contra as ondas já entregues; não há velocity confiável.

**E o custo que não está na tabela é o permanente** (§3.5).

---

## 11. Definição de pronto

1. OFX 1.x e 2.x reais importam; o encoding usado é gravado no lote; arquivo ilegível **falha com
   mensagem acionável** e **não grava lixo**.
2. Reimportar o mesmo arquivo ⇒ `lines_new = 0`, `200`, sem erro.
3. Importar período sobreposto ⇒ só o incremento entra.
4. **Dois lançamentos idênticos no mesmo dia ⇒ DOIS movimentos**, nunca um.
5. Movimento de **cada uma das cinco** origens de sistema, lançado antes do import, **não duplica** após
   o import (`lines_enriched >= 1` em cada caso). Cinco casos, não três.
6. **Ressincronizar uma linha enriquecida, pelos seis caminhos de mutação, preserva o texto do banco e o
   `dedup_hash` do OFX** — com controle positivo (§5.4).
7. Estornar um `payable` cuja linha foi enriquecida **desliga a origem** em vez de apagar a linha (§5.5).
8. Os blocos 2 e 3 listam os órfãos dos dois lados, **com o recorte de período**, e a tela diz em texto
   que no primeiro import o bloco 2 é o extrato inteiro.
9. **`posted_at` futuro num arquivo ⇒ 422.**
10. **Zero chamada de rede** em todo o pipeline (teste).
11. **Zero chamada nova de IA** no pipeline (teste com espião no `core/ai` — e o teste sabe que prova
    ausência de PII **estrutural**, não de nome).
12. Aceite em ~360px **medido, com screenshot**, sem valor cortado.
13. **Entrada no `CLAUDE.md`** escrita a partir do código que subiu — o AC que ninguém pula (§5, passo 4).

---

## 12. Rastreabilidade (Artigo IV — No Invention)

| Afirmação desta spec | Fonte |
|---|---|
| O gate é `\|divergencia_cents\|` por conta vs. banda, 3 ciclos pós-pré-condição | `docs/prd/epic-8-controle-bancario.md` §3.1.2 |
| As quatro condições de legibilidade e a precedência `(d)→(a)→(b)→(c)` | `apps/api/app/modules/bank/reconciliation.py` (`CicloDaConferencia`, docstring) |
| `PRIMEIRO_CICLO_MEDIVEL = 2026-09-01`, e o piso contra a data do merge | `bank/reconciliation.py:131`; `docs/superpowers/specs/2026-08-11-ciclo-da-conferencia-design.md` |
| Ciclo é mês de calendário no fuso do tenant; teto de 6 é exibição | `CLAUDE.md` §"O ciclo da conferência" |
| A §1.2 estava incompleta em três pontos | **[CORREÇÃO desta spec, §1.2.1]**, contra o código mergeado em 2026-08-11 |
| P1–P4, seus predicados e as ondas que os zeram | epic §3.1.2; `CLAUDE.md` (Ondas 2, 2b-i, 3) |
| P1–P4 estão todos fechados | `CLAUDE.md` §Onda 3 (PR #104) |
| A produção foi zerada em 05/08/2026 e o gate precisa de ciclo real | `CLAUDE.md` §Onda 3, aviso final |
| Blocos 2 e 3 não existem e devolveriam "todos os movimentos" | `apps/api/app/modules/bank/reconciliation.py:85-88` |
| `movimentos_sem_contrapartida` é a métrica secundária, só a partir da Onda 4 | epic §3.1 |
| `uq_bank_transactions_dedup` é `(tenant_id, bank_account_id, dedup_hash)`, total | `bank/models.py:307-313` |
| `uq_bank_transactions_origin` é parcial e é a idempotência da origem | `bank/models.py:343-351` |
| `_manual_dedup_hash` chaveia no UUID e nunca deduplica | `bank/service.py:1082-1100` |
| `sync_origin_movement` reescreve `raw_description` e `dedup_hash` | `bank/origin.py:298,303` (docstring em `:234-239`) |
| O enriquecimento do §4.5 cobre só `transfer`/`yield`/`payout` | `docs/architecture/controle-bancario-design.md` §4.5 |
| Estorno de linha enriquecida desliga a origem em vez de apagar | `docs/architecture/controle-bancario-onda2-design.md` §4.5 |
| `posted_at` futuro em `SOURCES_EXTERNA` é recusado, normativo | design da Onda 2 §4.2 |
| `ofx`/`csv` já estão em `SOURCES_EXTERNA` desde a `0059` | `bank/models.py:133-134,168` |
| A lista de caminhos de mutação tinha cinco e o sexto foi achado por gate | `CLAUDE.md` §Onda 2, item 8 |
| Anonimizador é 100% regex, sem NER; risco aceito em 2026-07-11 sob gate | `CLAUDE.md` §6.1 |
| `operation_nature` não está em `BankTransactionUpdate` | `CLAUDE.md` §Onda 2, item 8 |
| Baixa de `Charge` bloqueada por `platform_earnings → transaction` | design-mãe §4.7; `docs/superpowers/specs/2026-07-27-estornar-conta-paga-design.md` |
| Sinal de recebimento fora do trilho é neutro ao dono, nunca ao Master | decisão **D7**; `CLAUDE.md` §Onda 2, item 7 |
| 9 de 11 instituições exportam OFX; Nubank PF não; C6 PJ conflitante | `docs/research/2026-07-29-controle-bancario-requisitos-e-viabilidade.md` §2.2 |
| OFX é spec aberta e royalty-free (FDX); `ofxtools` é GPL-3.0; `ofxparse` é MIT e inativa | pesquisa §2.1, §2.3 |
| CSV é *n* parsers para sempre; nunca manter catálogo de layouts por banco | pesquisa §2.4 (recomendação) |
| Conteúdo do `<MEMO>` de Pix não verificado empiricamente | pesquisa §5 (lacunas honestas) |
| Manutenção perpétua, 2–3 rodadas por banco novo | ADR 0003, Consequência 1 |
| PII de terceiro entra no produto com esta onda | ADR 0003, Consequência 3 |
| Os cinco gatilhos de reversão | ADR 0003, Revisão futura (a)–(e) |
| Import é o único item que "constrói" no lugar de "confirmar" | design-mãe §9 |
| A porta `POST /bank/accounts/{id}/imports` foi revogada como primária | design da Onda 2 §1.2 (varredura do REQ-12) |
| Em 360px tabela de 3 colunas não cabe; medir com Playwright | `CLAUDE.md` §Onda 2b-ii (aceite medido) |
| Capacidade sem consumidor: `capabilities.py`, `bank_audit.py`, `days_since_...`, `set_primary` | `CLAUDE.md` §WhatsApp item 12, §Onda 2 item 8, §Onda 3 |
| CSV fora da Onda 4; mapeamento por tenant é onda posterior | **decisão do fundador, 2026-08-11** (esta sessão) |
| O corte [1]–[7] com §4.6/§4.7 como muro | **decisão do fundador, 2026-08-11** (esta sessão) |
| O segundo termo do gate (arquivos OFX reais) | **[PROPOSTA desta spec]**, derivada da pesquisa §5 e da lição da Evolution |
| A proibição de `movimentos_sem_contrapartida` como gate da Onda 5 | **[PROPOSTA desta spec]**, derivada da regra de método do §8 |
| O gate da Onda 5 por esforço manual medido | **[PROPOSTA desta spec]** |
| O corpus de regressão como entregável | **[PROPOSTA desta spec]** |
| A contenção do bloco 2 não narrado por IA | **[PROPOSTA desta spec]**, derivada da dívida 🔴 do §6.1 |
| A correção do §5.4 (não sobrescrever linha enriquecida) | **[ACHADO desta spec]**, verificado em `bank/origin.py` |
| ±3 dias no enriquecimento | **[SUPOSIÇÃO parametrizável]**, herdada do design-mãe §4.5 |
| 3 ciclos de observação | **[SUPOSIÇÃO DO @PM]**, herdada do epic §3.1.2 |
| Esforço de ~3,0 ondas | **[EST.]** calibrada contra ondas entregues |
