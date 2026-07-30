# Ratificação dos desvios do Epic 8 — parecer da @architect

> **Autora:** Aria (@architect)
> **Data:** 2026-07-29
> **Branch:** `feat/controle-bancario-conferencia` (nada commitado por este parecer)
> **Objeto:** julgar os 7 desvios que os @sm escalaram ao expandir o Epic 8 em 8 stories, e corrigir o
> design onde a ratificação exigir.
> **Documentos atualizados por este parecer:**
> [`controle-bancario-design.md`](controle-bancario-design.md) (§0 cabeçalho, §1.3 + §1.3.1 novo, §2,
> §3.1.1 novo, §5.1 + §5.1.1 novo, §5.3, §6.1 + §6.1.1/§6.1.2 novos, §8, §10 D1, §12) e
> [`../decisions/0003-controle-bancario-nativo.md`](../decisions/0003-controle-bancario-nativo.md)
> (Decisão — Regra dos Planos; Adendos 1–3).
> **Nenhum arquivo `docs/stories/*.md` foi editado** — o @po está validando as stories em paralelo. As
> mudanças de story estão escritas aqui como **instruções**, para o @po ou o @dev aplicar.

---

## 0. Placar

| # | Desvio | Veredito |
|---|---|---|
| **D-1** | Supressão do runway no backend, não na UI (8.1) | ✅ **RATIFICADO** |
| **D-2** | `CompletenessInput` estendido com decomposição por conta (8.6) | ✅ **RATIFICADO COM AJUSTE** |
| **D-3** | Vocabulário de `*_origem` divergente em três seções do design | 🔧 **INCOERÊNCIA MINHA — CORRIGIDA.** A unificação dos @sm é ratificada com ajuste: **dois eixos, dois campos, 4 valores em `ORIGENS`** (não 5) |
| **D-4** | `derived_balances` vs. conferência por conta (8.2 × 8.5) | ✅ **8.5 ESTÁ CERTA.** Função em lote sobrevive **com ajuste de nome e de docstring**; a recomendação da 8.2 é revogada |
| **D-5** | `ProjectionWindow.alert` não suprimido (8.1) | ❌ **REJEITADO.** A Onda 0 **não** vai a produção afirmando janela negativa sobre a base errada |
| **D-6** | Uma migration por onda × três tabelas na Onda 1 | ✅ **RATIFICADO.** O design parou de fixar número de revision |
| **D-7** | REQ-16 (banda configurável) sem persistência | ✅ **A FORMA DA 8.5 É A CORRETA PARA A ONDA 1** — e o lugar, se persistir, está decidido: `tenant_profiles`, 2 colunas inteiras |

**Dois desvios expuseram problema mais fundo no meu design** (§9): o D-3 (dois conceitos achatados num
campo) e o D-5 (eu tratei "supressão" como um problema de tela quando é um problema de *claim*, e por
isso mapeei uma superfície de duas — e depois errei a simetria entre os dois sinais contaminados).

---

## D-1 — Supressão do runway no backend, não na UI

### Veredito: **RATIFICADO**

**Razão.** O critério de pronto que eu mesma escrevi na §6.1 é *surface-agnostic*: *"nenhum usuário vê
um runway em dias derivado de um saldo inicial cuja origem não está declarada na própria tela"*. Um
critério sobre o **usuário** exige supressão que não dependa de quantas telas existem. Meu §6.1 dizia
"deixa de ser **exibido**" porque eu havia mapeado **uma** superfície (`ProjecaoCaixaPage`) e a segunda
existe: `diagnostics.py:90` repassa `proj.runway.days` e `engine.py:128-137` emite *"Runway de N dias"*
no `/financeiro/diagnostico`. **Isso é lacuna do meu design, não desvio do @sm.** Confirmei os dois
caminhos no código nesta sessão.

Três propriedades tornam a supressão na origem estritamente superior a suprimir por consumidor:

1. **Fail-closed.** Toda superfície futura (API pública, resumo por e-mail, Cockpit) herda a supressão
   sem precisar saber que ela existe. Suprimir por consumidor é fail-open — cada consumidor novo é
   uma nova chance de vazar, e N regras precisam ficar em sincronia.
2. **`engine.py` e `diagnostics.py` ficam intocados**, porque `_runway_signal(None)` já devolve `[]`
   (silêncio, não um 🟢 falso). O comportamento correto sai **por construção**, sem segunda regra — e
   sem colisão de merge com a 8.6, que é dona desses dois arquivos. Coordenação real, não conveniência.
3. **Um dado, uma verdade.** Runway suprimido na tela e presente na API é um convite a alguém
   "consertar" a tela de volta em seis meses.

**Custos: aceitos, e são os que o @sm nomeou.** Os testes de runway da 5.7 mudam de expectativa — é
correção, não regressão (epic §11.1 já declara o AC1 da 5.7 superado), e a cobertura do cálculo se
desloca para `burn_rate_cents_per_day`, que continua exposto e continua correto (deriva de contas em
aberto, não do saldo inicial). `runway.days = None` em todo cenário com queima durante a Onda 0 é o
preço de não afirmar dias que não sabemos.

### O que eu ACRESCENTO à 8.1 (não é objeção, é fechar duas frestas)

**(a) Invariante de contrato, testável:** `days_suprimido is True ⇒ days is None`. Nenhum consumidor
deve precisar tratar "suprimido, mas com número". Idem para o `alert` (ver D-5).

**(b) A guarda do AC4 é a coisa mais importante da story, e o AC já a nomeia — mantenha-a como AC, não
a rebaixe a nota de implementação.** Trocar *"faltam 43 dias"* (falso preciso) por *"sem risco"* (falso
tranquilizador) é **pior** que o bug original: o primeiro erra um número, o segundo dá permissão para
gastar. A condição `if runway_days is None` tem de virar `if runway_days is None and not days_suprimido`.

**(c) Recomendação NÃO bloqueante sobre o nome do campo.** `days_suprimido` mistura idiomas dentro do
próprio `Runway`, cujos outros campos são `days` e `burn_rate_cents_per_day`. A convenção do projeto
(`CLAUDE.md` §8) é identificadores em inglês; o PT-BR em `saldo_inicial_*` e `*_origem` é herdado e
normativo (§1.3c), mas `Runway` não tem essa herança. **`days_suppressed`** seria mais coerente. Custo
de trocar agora: find/replace em stories `Draft` + o tipo TS. Custo de não trocar: um campo de API
pública que contradiz o irmão. **Decisão do @po — eu não bloqueio por isto**, e se ficar
`days_suprimido`, que fique consistente com `alert_suprimido` (não misture os dois estilos).

### Instrução concreta

| Onde | O que muda |
|---|---|
| `docs/architecture/controle-bancario-design.md` | ✅ **JÁ FEITO** — §6.1 ganhou o bloco `CONTRATO` das três dataclasses e a §6.1.1 nova, com as duas superfícies citadas por arquivo:linha, as três razões e os custos. §8 Onda 0 reescrita. |
| `docs/decisions/0003-...md` | ✅ **JÁ FEITO** — Adendo 2 + "Custo aceito". |
| `docs/stories/8.1.story.md` | **Nada a mudar por D-1.** A story está certa. Acrescentar apenas os dois testes de invariante da alínea (a) na Task 5. |

---

## D-2 — `CompletenessInput` com decomposição por conta

### Veredito: **RATIFICADO COM AJUSTE**

**Razão para ratificar.** O `CompletenessInput` plano do meu §5.3 é **incompatível com uma decisão do
fundador posterior a ele** (F3, 2026-07-29: várias contas PJ, possivelmente em bancos diferentes) e com
o critério de aceite da Onda 1 (*"o diagnóstico mostra o sinal de completude com o número **e aponta
qual conta**"*). Uma entrada plana não consegue nomear conta, e o dano é concreto: três contas
divergindo +R$ 1.200, −R$ 900 e +R$ 40 produzem o diagnóstico *"+R$ 340, parece saudável"* — o produto
perde exatamente a capacidade que está vendendo. O bloco era declarado ilustrativo; a extensão é
refinamento autorizado, não invenção (Art. IV: rastreia a F3 e ao epic §3.2).

**O requisito duro é respeitado.** A extensão são **dataclasses** — zero I/O, zero `Session`, zero
`core.ai`, zero acesso a `bank` dentro de `engine.py`. A decomposição chega **já montada** por
`diagnostics.py`, que é a camada de I/O criada exatamente para isso. Isso não é um limite que a extensão
tangencia: é **a razão pela qual ela é possível** sem tocar na pureza. Ratifico também a exigência da
8.6 de teste estrutural de pureza sobre `engine.py` — ela transforma a docstring "NÃO NEGOCIÁVEL" em
gate, no estilo do `test_tenancy_guard.py`.

### Forma CANÔNICA (gravada em `design §5.3`)

```python
@dataclass(frozen=True)
class CompletenessAccountInput:
    account_name: str                            # pode conter PII → anonimizado pelo NARRADOR, nunca aqui
    divergencia_cents: int | None                # None = NÃO AVALIÁVEL (sem saldo declarado utilizável) ≠ zero
    tolerancia_cents: int                        # já calculada pela conferência (§5.1); o motor NÃO recalcula banda
    dias_desde_ultima_conferencia: int | None    # None = nunca confirmado

@dataclass(frozen=True)
class CompletenessInput:
    contas: list[CompletenessAccountInput]       # [] = nenhuma conta bancária cadastrada
    movimentos_sem_contrapartida: int = 0        # 0 por construção na Onda 1; regra dormente até a Onda 3

# EngineInput: `completeness: CompletenessInput | None = None` — ÚLTIMO campo, COM default.
```

**Dois ajustes em relação ao que a 8.6 desenhou:**

**Ajuste 1 — `dias_desde_ultima_conferencia` mora na CONTA, não no relatório.** A 8.6 a mantém no
nível do `CompletenessInput` e a alimenta com o **máximo** entre as contas ("a mais desatualizada
manda"). É honesto, e ainda assim **cai na mesma armadilha do consolidado que a F3 proíbe**: perde
*qual* conta está desatualizada. Uma conta conferida ontem e outra nunca conferida não são "45 dias" —
são duas afirmações sobre duas contas. Mover para a conta simplifica a 8.6 (some o colapso por `max()`
e a justificativa da escolha conservadora) e torna o sinal de desatualização simétrico ao de
fora-da-banda: um por conta, nomeando a conta.

**Ajuste 2 — as duas regras 🟡 de "não sei" viram UMA, por conta.** A tabela do AC3 da 8.6 tem uma
linha para *"conta sem saldo declarado na janela"* e outra para *"saldo não confirmado há N dias"*.
Num tenant com 3 contas nenhuma conferida, isso produz até **seis** sinais 🟡 dizendo a mesma coisa —
ruído que treina o usuário a ignorar a tela, que é **o mesmo vício que a banda de tolerância existe
para evitar**. Regra: **uma conta gera no máximo um 🟡 de "não sei"**, cujo texto diz qual dos casos é
(*"nunca confirmado"* / *"confirmado há N dias"* / *"sem saldo declarado na janela"*). Um 🔴 de
fora-da-banda **pode** coexistir com um 🟡 de desatualização na mesma conta — são afirmações diferentes
(*"está fora da banda em R$ X"* e *"e essa medição é de 60 dias atrás"*).

A tabela completa de regras, com nível e **cardinalidade** por linha, está em `design §5.3`.

### Ratifico sem ajuste, e registro para não ser reaberto

- **`movimentos_sem_contrapartida = 0` literal, regra escrita e dormente.** A proibição de aproximar
  por "movimentos `unmatched`" está certa e o motivo está certo: essa métrica alimenta o gate do epic
  §3.1, que decide se as Ondas 3 e 4 (~4,5 ondas de trabalho) são liberadas. Número inventado ali é o
  erro mais caro possível neste epic.
- **A "precedência semântica" como ordem-de-avaliação + ressalva na UI, sem campo novo em `Signal`.**
  Ratificado. Adicionar `precedence: int` seria superfície nova em três camadas (dataclass, schema
  Pydantic, tipo TS) para um efeito que a ordem + um teste garantem. E ratifico a leitura fina que a
  8.6 fez: um 🟢 de completude **não** passa à frente de um 🔴 de outra origem — a precedência é
  **dentro** do nível, não acima da gravidade. Sem essa distinção, o sinal viraria um analgésico.
- **O motor decide por `abs(divergencia) > tolerancia`**, não pelo `dentro_da_tolerancia` da §5.1 — não
  porque o booleano esteja errado, mas para não haver **duas verdades** sobre a mesma comparação. A
  borda `abs(divergencia) == tolerancia` é **dentro** (silêncio) nos dois lugares, com teste.

### Instrução concreta

| Onde | O que muda |
|---|---|
| `design.md §5.3` | ✅ **JÁ FEITO** — bloco marcado `CONTRATO`, com as duas dataclasses, a tabela de regras com cardinalidade e as duas notas de fusão/verde. |
| `docs/stories/8.6.story.md` | **AC1:** mover `dias_desde_ultima_conferencia` de `CompletenessInput` para `CompletenessAccountInput`. **AC3:** fundir as duas linhas 🟡 numa só, "1 por conta"; acrescentar a coluna de cardinalidade. **Task 4:** remover o colapso por `max()` (passa a mapear 1:1 a partir de `ConferenciaConta.dias_desde_ultima_conferencia`). **Task 6:** trocar o teste do `max()` por um teste de "duas contas com estados de frescor diferentes → dois 🟡, cada um nomeando a sua". Manter tudo o mais. |
| `docs/stories/8.5.story.md` | Nada — a 8.5 já entrega `dias_desde_ultima_conferencia` **por conta** (AC8). O ajuste apenas para de descartar essa informação. |

---

## D-3 — Vocabulário de `*_origem`: **incoerência minha**

### Veredito: **CORRIGIDA NO DESIGN.** A unificação num único arquivo é **RATIFICADA**; a escolha da *união dos 5 valores* é **AJUSTADA para 4**.

Começo pelo que é meu: as três listas eram

| Seção | Vocabulário que eu escrevi |
|---|---|
| §1.3c | `{plataforma, banco, declarado, indisponivel}` |
| §6.1 | `{plataforma, banco, misto, indisponivel}` |
| §5.1 | `{declarado, extrato, indisponivel}` |

Não foi descuido de redação. **Sua suspeita está certa: são dois eixos diferentes achatados num só
campo.** E há uma quarta pista que ninguém citou e que fecha o diagnóstico: a §2.4 do meu próprio
design define `bank_balance_checkpoints.origin VARCHAR(12) -- manual|ofx`. Ou seja, o eixo já tinha um
vocabulário canônico numa **coluna do banco** — e a §5.1 inventou um segundo nome para os mesmos dois
valores (`declarado` ≡ `manual`, `extrato` ≡ `ofx`). A prova de que isso já estava custando: a Story
8.4 (Dev Notes, nota 3) precisou escrever a regra de tradução *"`origin='manual'` mapeia para
`ORIGEM_DECLARADO`"* — uma camada de tradução entre duas grafias do mesmo conceito, que existe **só
para satisfazer um documento incoerente**.

### A resolução: dois eixos, dois campos, dois vocabulários

| | **Eixo A — plano** | **Eixo B — porta de entrada** |
|---|---|---|
| Pergunta | *"De qual plano de dinheiro (§1.1) este número vem?"* | *"Por qual porta este saldo **externo** entrou no e1p?"* |
| Sufixo | `*_origem` | `*_fonte` |
| Vocabulário | `plataforma` \| `banco` \| `misto` \| `indisponivel` | `manual` \| `ofx` (os valores da coluna `bank_balance_checkpoints.origin`) |
| Vive em | `app/core/money_planes.py` (`ORIGEM_*`, `ORIGENS`) | `app/modules/bank/models.py` (`ORIGIN_MANUAL`, `ORIGIN_OFX`, `ORIGINS`) |
| Obrigatório em | **todo** campo de saldo (§1.3c) | só em saldo atestado por terceiro (hoje: o checkpoint) |

**`declarado` e `extrato` ficam REVOGADOS como valores de `*_origem`. `ORIGENS` tem 4 valores.** O
`{plataforma, banco, misto, indisponivel}` da §6.1 era, retrospectivamente, a lista **correta**; a
§1.3c (que trocava `misto` por `declarado`) era a errada. A união dos 5 do epic §4.1c herdou o erro:
não é superconjunto de nada, é a mistura de dois eixos — e o argumento do @sm de que "nenhum consumidor
perde valor" é verdadeiro e insuficiente, porque o custo não é perder valor, é **cinco valores num
campo cujo domínio conceitual tem quatro**, com dois deles respondendo outra pergunta.

**Onde o eixo A é degenerado, e por que isso é informação e não desperdício.** Na conferência (§5.1),
`saldo_banco` e `saldo_sistema` são **ambos** do plano 3 — o eixo A vale `banco` nos dois e não informa
nada. O que distingue os dois números é o **método de estabelecimento** (atestado pelo banco × derivado
pelo e1p), e isso já está nos **nomes dos campos**. Então o `*_origem` ali serve apenas ao invariante
mecânico e testável do §1.3c ("nenhum saldo trafega sem procedência" — um teste de contrato pode varrer
todo campo `*_cents` de saldo e exigir o irmão), enquanto a informação nova vai para o `*_fonte`.
Mantenho os dois: o invariante mecânico é o que impede o §1.1 de renascer, e ele só é auditável se não
tiver exceções.

**Sobre `extrato` na Onda 3:** a instrução dos @sm ("acrescentar a `ORIGENS` em vez de criar
vocabulário local") era a decisão certa dado o documento que eles tinham. Com o design corrigido, ela
fica **desnecessária**: `ofx` já existe no eixo B desde a §2.4, e a Onda 3 só passa a **escrever** nele.
Zero mudança de vocabulário na Onda 3 — o que é o teste de que a modelagem em dois eixos era a certa.

### Instrução concreta

| Onde | O que muda |
|---|---|
| `design.md` | ✅ **JÁ FEITO** — §1.3c reescrita (4 valores, eixo A), §1.3.1 **nova** (a tabela dos dois eixos, a revogação e a razão), §5.1 (`ConferenciaConta` com `saldo_banco_origem` ∈ `{banco, indisponivel}`, `saldo_banco_fonte` novo, `saldo_sistema_origem` explícito, e `saldo_sistema_cents`/`divergencia_cents`/`dentro_da_tolerancia` corrigidos para `| None`), §12. |
| `docs/decisions/0003-...md` | ✅ **JÁ FEITO** — Decisão (Regra dos Planos) + Adendo 1. |
| `design.md §1.3` | ✅ **JÁ FEITO** — acrescentado o **5º teste da Regra dos Planos**: `test_todo_saldo_declara_origem`, teste de **contrato** (varre os schemas de saída, exige o irmão `*_origem` ∈ `ORIGENS` para todo campo de saldo). É ele que torna o item (c) auditável sem exceções — e é a razão de manter o `*_origem` degenerado da conferência. **Dono natural: a 8.1** (é quem cria `money_planes.py`); a 8.2 pode estendê-lo. |
| `docs/stories/8.1.story.md` | **Task 1:** `core/money_planes.py` nasce com **4** constantes — `ORIGEM_PLATAFORMA`, `ORIGEM_BANCO`, `ORIGEM_MISTO`, `ORIGEM_INDISPONIVEL` — e `ORIGENS` com os quatro. **Remover `ORIGEM_DECLARADO`.** Trocar a `[AUTO-DECISION]` da Task 1 pela referência ao design §1.3.1 (a união dos 5 do epic §4.1c está superada). **AC1:** o domínio de `saldo_inicial_origem` passa a ser `{plataforma, banco, misto, indisponivel}`. **Dev Notes / "Contrato público":** a linha que instrui a 8.5 a "acrescentar `extrato` a `ORIGENS`" sai — `extrato`/`ofx` é eixo B e já existe. |
| `docs/stories/8.4.story.md` | **Dev Notes nota 3:** remover a tradução `origin='manual'` → `ORIGEM_DECLARADO`. As constantes `ORIGIN_MANUAL`/`ORIGIN_OFX`/`ORIGINS` em `bank/models.py` (Task 3) **são** o vocabulário do eixo B — ficam como estão, e são o que a 8.5 lê direto. |
| `docs/stories/8.5.story.md` | **AC2:** `saldo_banco_origem = ORIGEM_BANCO` (não `ORIGEM_DECLARADO`) **e** `saldo_banco_fonte = checkpoint.origin` (sem tradução). **AC3:** o caminho indisponível mantém `saldo_banco_origem = ORIGEM_INDISPONIVEL` e passa a ter `saldo_banco_fonte = None`. **AC4:** acrescentar `saldo_sistema_origem = ORIGEM_BANCO` ao contrato. **Task 1**, terceiro item: a nota sobre `extrato` sai. **Task 2:** as dataclasses ganham `saldo_banco_fonte: str \| None` e `saldo_sistema_origem: str`. |
| Epic §4.1c (`docs/prd/`) | **@pm:** a lista de 5 valores está superada por `design §1.3.1`. Não editei — o epic é do @pm. Não bloqueia nenhuma story se as stories forem corrigidas como acima. |

---

## D-4 — `derived_balances` vs. conferência por conta

### Veredito: **A 8.5 ESTÁ CERTA.** A função em lote **continua tendo razão de existir**, com a assinatura de um `until` único — mas **muda de nome** e ganha uma proibição na docstring. A recomendação da 8.2 é **revogada**.

**Por que a 8.5 está certa.** A conferência tem **uma data de referência por conta** — o
`reference_date` do checkpoint daquela conta. Um `until` comum compararia o saldo do banco de uma data
com o saldo do sistema de outra, que é *o* erro clássico desta classe de relatório e que a minha §5.1
manda o service **recusar**. A 8.5 recusou uma recomendação de eficiência para preservar uma regra de
correção, e nomeou o conflito em vez de escolher em silêncio. É exatamente o comportamento certo.

**Por que NÃO mudar a assinatura para um mapa `{conta: data}`.** O ganho da versão em lote é fazer
**uma** passada no banco. Com uma data por conta isso degenera em N queries — ou num `CASE` por conta
que é menos legível que o laço. **O mapa custaria complexidade para entregar zero benefício**, e pior:
convidaria o chamador a construí-lo a partir de uma data única, que é o bug de volta por outro caminho.

**Por que a função em lote sobrevive.** Ela tem um consumidor legítimo e diferente: a tela **"Contas &
Saldos"** (8.7), que mostra o saldo **de hoje** de todas as contas. Ali a data **é** uma só, e a passada
única é o comportamento correto. O erro não estava na função; estava em recomendá-la para um caso cuja
premissa (data comum) não vale.

### Assinaturas canônicas (gravadas em `design §3.1.1`)

```python
def derived_balance(db, *, bank_account_id: str, until: date | None = None) -> int: ...
#   UMA conta, UMA data. `until` é DATE (nunca datetime), INCLUSIVO. É a ÚNICA implementação da
#   fórmula da §3.1 no repositório — uma segunda torna a Regra dos Planos §1.3a inauditável.

def derived_balances_as_of(db, *, as_of: date | None = None,
                           include_archived: bool = False) -> dict[str, int]: ...
#   TODAS as contas, UMA data comum. Para TELA DE LISTA. PROIBIDA na conferência (§5.1) —
#   a docstring diz isso e diz por quê.
```

**O rename não é cosmético.** `derived_balance` e `derived_balances` diferem por **um `s` final** e são,
respectivamente, a função certa e a errada para o mesmo trabalho — e o sintoma de escolher errado é uma
divergência falsa, **silenciosa e plausível** (o relatório não quebra; ele mente um número). `as_of` no
nome e no parâmetro declara que há **uma** data para todas as contas, e o nome deixa de ser um
autocomplete de distância 1 da função correta.

### Instrução concreta

| Onde | O que muda |
|---|---|
| `design.md §3.1.1` | ✅ **JÁ FEITO** — as duas assinaturas, a proibição, o argumento contra o mapa e o argumento do nome. |
| `docs/stories/8.2.story.md` | **Task 4:** renomear `derived_balances` → `derived_balances_as_of(db, *, as_of=None, include_archived=False)`; a docstring **deve** dizer que a conferência (8.5) não pode usá-la e por quê (data por conta). **Dev Notes, "Contrato público":** atualizar a linha da função e **trocar o consumidor de "8.5" para "8.7"**. **Dev Notes, "três pontos de alinhamento", item 2: REMOVER** — a recomendação *"a 8.5 deve preferir `derived_balances` a um loop"* está revogada; substituir por: *"a conferência usa laço de `derived_balance` com o `until` de cada conta; `derived_balances_as_of` é para tela de lista"*. |
| `docs/stories/8.5.story.md` | **AC4b:** manter a decisão (laço), atualizar o nome citado para `derived_balances_as_of` e trocar a moldura de *"divergência consciente da recomendação da 8.2"* para *"assinatura canônica ratificada pela @architect (design §3.1.1)"* — não é mais divergência, é o contrato. Idem no bloco "Divergência já detectada" das Dev Notes. |
| `docs/stories/8.7.story.md` | **@po:** conferir se a story cita a função em lote; se citar, atualizar o nome. Não li a 8.7 nesta sessão. |

---

## D-5 — `ProjectionWindow.alert` na Onda 0

### Veredito: **REJEITADO.** Não é aceitável a Onda 0 ir para produção afirmando *"projeção de caixa negativa em N dias"* sobre o saldo contaminado.

O @sm marcou este como "ponto legítimo para a @architect discordar". Discordo, e o motivo é que **o
próprio argumento que sustenta o D-1 derruba o D-5**: se "suprimir na origem porque a segunda superfície
vaza" está certo para o runway, então a segunda superfície emitindo um 🔴 sem qualificação sobre **o
mesmo número contaminado** é o mesmo defeito. A assimetria precisaria de uma justificativa que
sobrevivesse ao código — e nenhuma das três sobrevive.

**Razão (i) — "o design pede supressão do runway em dias, não do sinal direcional".** Verdade literal, e
é um apelo à letra de um documento que o **D-1 acabou de provar incompleto**. Meu §6.1 falava de "runway
em dias" porque eu havia mapeado uma superfície de duas; não é evidência de que eu tinha decidido sobre
o `alert` — é evidência de que eu não olhei. Não vale como ratificação.

**Razão (ii) — "`alert` é direção, não precisão; o vício de precisão espúria não se aplica".** **Esta é
a que não sobrevive.** O código:

```python
saldo = saldo_inicial + inflows[i] - outflows[i]     # projection.py:187
ProjectionWindow(..., alert=saldo < 0)               # projection.py:189
```

O termo contaminado é **aditivo**, e `alert` é um **cruzamento de limiar** sobre essa soma. Erro no
saldo inicial vira erro de **veredito**, nas duas direções:

| Perfil | `available_cents` | `alert` |
|---|---|---|
| Nunca saca | acumula todo o faturamento líquido histórico e **nunca diminui quando uma conta é paga** (`payables` não toca a Carteira — `payables/models.py:4`) | `saldo_inicial` inflado, **monotonicamente** → **falso negativo**: silêncio sobre um aperto de caixa real |
| Saca tudo | ≈ 0 enquanto o dinheiro está no banco | **falso positivo**: 🔴 "caixa negativo em 30 dias" para quem tem R$ 80k na conta |

E o perfil **não é uma incógnita**: `request_payout` (`wallet/service.py:227`) **só marca `withdrawn`**
— não existe transferência real, ninguém saca de fato. Logo, para todo tenant real, `available_cents` é
a figura que só cresce, e este `alert` é sistematicamente uma **máquina de falso negativo**. Um sinal
que se cala exatamente quando deveria falar não é "direcionalmente aproximado": é ruído com selo de
vermelho. É pior que o runway, não melhor — o runway ao menos errava para os dois lados.

**Razão (iii) — "suprimir os dois deixa a Projeção sem sinal nenhum na Onda 0".** Esta é a objeção
**legítima**, e é a única que precisa de resposta em vez de refutação. A resposta é que ela pressupõe
que suprimir o sinal = esconder o número. Não precisa ser:

> **Suprima a AFIRMAÇÃO, nunca o NÚMERO.** `alert = False` + `alert_suprimido = True` +
> nota — e **`saldo_projetado_cents` continua exposto e continua sendo exibido** em cada janela, com o
> rótulo de origem ao lado, junto com `burn_rate_cents_per_day` e a trajetória.

Com isso:

- O dono **continua vendo** os três saldos projetados e a trajetória. O que desaparece é o e1p
  **afirmando** *"seu caixa vai ficar negativo"* — afirmação para a qual ele não tem lastro. Mostrar o
  número com a premissa rotulada respeita o teto de simplicidade (§0: *confirmar*, não *construir*);
  gritar vermelho sobre premissa falsa não.
- **O dono não perde nada que tinha.** No perfil real (nunca saca) ele **já** não recebia esse 🔴 — o
  falso negativo é o estado atual em produção. Suprimir não remove informação: remove um alarme que só
  disparava quando estava errado.
- O vazio é preenchido **de propósito** pelo sinal de completude (8.6): 🟡 *"Nenhuma conta bancária
  cadastrada — não sei se os seus lançamentos estão completos"*. Essa é a mensagem certa para este
  estado, e é **acionável** (cadastre a conta), o que *"caixa negativo em 30 dias"* derivado de um
  número errado não é. A própria 8.6 já assume esse papel nas Dev Notes.

**Sobre "a Onda 0 pode ficar sozinha em produção por semanas":** isso **agrava**, não atenua. Onda 1 são
7 stories / ~1,5 onda, com `main` sob proteção de branch (PR + 4 checks por mudança). Semanas é o
cenário provável, meses é possível. E o dano do falso negativo cresce com o tempo, porque
`available_cents` cresce monotonicamente: quanto mais tempo a Onda 0 fica sozinha, **mais** inflado o
saldo inicial e mais garantido o silêncio.

**Mecanismo (é o do D-1, e é isso que torna a correção barata).** Com `alert=False`,
`engine._projection_window_signals` não emite nada — o 🔴 desaparece do `/financeiro/diagnostico`
**por construção**, sem editar `engine.py` nem `diagnostics.py`. **A propriedade de zero colisão com a
8.6 é preservada**, que era a virtude principal do D-1. Custo total: ~10 linhas em `projection.py`, um
campo em `ProjectionWindowOut`, o `WindowCard`/`TrajectoryChart` deixando de pintar vermelho (já
recebem `alert` — `ProjecaoCaixaPage.tsx:112-137,153-154`), e 2 testes.

### O que a 8.1 precisa fazer

1. **`ProjectionWindow` ganha `alert_suprimido: bool`.** Calcular `alert` exatamente como hoje e,
   **depois**, aplicar: se `saldo_inicial_origem == ORIGEM_PLATAFORMA` → `alert = False`,
   `alert_suprimido = True`; senão `alert_suprimido = False`.
   ⚠️ **Diferente do runway, a condição NÃO inclui `burn_rate > 0`** — o `alert` é por janela e não
   depende de queima média; a contaminação do saldo inicial vale para qualquer janela.
2. **Nova `_NOTE_ALERT_SUPRIMIDO`**, adicionada a `notes` só quando houver alguma janela suprimida:
   dizer que os saldos projetados **são exibidos**, mas que o e1p não afirma se o caixa fica negativo
   porque o saldo de partida não é o da conta bancária.
3. **`ProjectionWindowOut` ganha `alert_suprimido: bool`;** `_projection_out` repassa;
   `projecao.ts` (`Window`) ganha `alert_suprimido: boolean`.
4. **`ProjecaoCaixaPage.tsx`:** `WindowCard` deixa de pintar vermelho / mostrar `AlertTriangle` /
   escrever *"Caixa fica negativo nesta janela"* quando suprimido — e **continua mostrando
   `formatBRL(cents)`**, com o rótulo de origem. `TrajectoryChart` mantém a cor Portal (`anyAlert`
   passa a ignorar janelas suprimidas, o que sai de graça porque `alert` já é `False`).
5. **AC6 estendido:** *nenhum* `Signal` de `source="projecao"` sai de `diagnostics.compute_signals`
   enquanto a origem for `plataforma` — nem runway, nem janela negativa. O teste do AC6 que a story já
   tem passa a asserir os dois.
6. **Invariante testável:** `alert_suprimido is True ⇒ alert is False`.
7. **`engine.py` e `diagnostics.py` continuam intocados** — a promessa da story para a 8.6 se mantém
   integralmente. Isto é requisito, não recomendação.
8. **A 8.8 restaura os dois:** com `origem` em `{misto, banco}`, `days_suprimido` e `alert_suprimido`
   voltam a `False`. Registrar no contrato público da 8.1 e na 8.8.
9. **Remover** a seção *"Resíduo conhecido e deliberadamente NÃO endereçado aqui"* das Dev Notes da
   8.1 e substituir por um resumo do §6.1.2 do design. O resíduo deixou de existir.

| Onde | O que muda |
|---|---|
| `design.md` | ✅ **JÁ FEITO** — §6.1 (`ProjectionWindow` no bloco `CONTRATO`), §6.1.2 **nova** (a tabela dos dois perfis, o fato do `request_payout`, "suprima a afirmação, nunca o número"), §8 Onda 0 AC2/AC4/AC6. |
| `docs/decisions/0003-...md` | ✅ **JÁ FEITO** — Adendo 2. |
| `docs/stories/8.1.story.md` | Os 9 itens acima. Impacto de esforço: pequeno (a story já toca todos os arquivos envolvidos); impacto de escopo: **nenhuma tabela, nenhuma migration, nada fora de `projection.py`/`schemas.py`/`router.py`/`projecao.ts`/`ProjecaoCaixaPage.tsx`** — o AC7 ("a fórmula não muda") continua valendo, porque `saldo_projetado_cents` não muda: só o veredito é calado. |

---

## D-6 — Uma migration por onda × três tabelas na Onda 1

### Veredito: **RATIFICADO.** Os @sm estão certos, e o design estava errado em dois pontos, não um.

Errado (1): *"uma migration por onda"*. A granularidade real é **uma migration por story que cria
tabela** — a Onda 1 cria três tabelas em três stories (8.2 `bank_accounts`, 8.3 `bank_transactions`,
8.4 `bank_balance_checkpoints`) e portanto consome **três** revisions. Forçar uma migration só para
"cumprir o mapa" acoplaria três stories a um arquivo, com três `@dev` disputando o mesmo diff.

Errado (2): **fixar o número**. Um design que carimba `0058` fica desatualizado no primeiro merge de
qualquer outra frente de trabalho, e o custo de acreditar nele é um `multiple heads` que quebra
`alembic upgrade head` — precisamente a lição que a `0049_investments.py` já traz na docstring. A
disciplina de "confirmar o head no momento da implementação" da Task 1 da 8.2 é a correta e deve ser
copiada por toda story deste epic que crie tabela.

Head reconfirmado nesta sessão: **`0057_device_tokens.py`** (`ls apps/api/migrations/versions/`). Isso
não muda o veredito — o head de hoje é um fato, não um contrato.

### Instrução concreta

| Onde | O que muda |
|---|---|
| `design.md §2` | ✅ **JÁ FEITO** — o bullet de numeração foi reescrito: nenhum revision fixado, "uma migration por story que cria tabela", e a razão (`multiple heads`). |
| `design.md §8` | ✅ **JÁ FEITO** — a nota de abertura e a tabela-resumo passam a contar **quantas** revisions cada onda consome, não quais; a coluna virou "Migrations". |
| `docs/decisions/0003-...md` | ✅ **JÁ FEITO** — Adendo 3. |
| `docs/stories/8.2.story.md` | **Dev Notes, "Numeração de migration":** trocar *"registrado como contradição, não resolvido por conta própria"* por *"resolvido pela @architect: design §2 não fixa mais revision; uma migration por story que cria tabela"*. A Task 1 fica **como está** — é a prática correta. |
| Epic §5 e §"Contexto" (`docs/prd/`) | **@pm:** a coluna "Migration" (`0058`/`0059`/…) deve ser lida como **ordem**, não identificador, e a frase "0058, uma migration por onda" está superada por `design §2`. Não editei o epic. **Atenção:** a 8.5 (Dev Notes) e a 8.4 citam *"a migration 0058"* como se fosse uma vaga única — corrigir a redação para "a migration da story dona da tabela" evita que alguém tente empilhar três tabelas num revision. |

---

## D-7 — REQ-16: onde a banda de tolerância mora, se for persistida

### Veredito sobre a forma da Onda 1: **a decisão da 8.5 (função pura parametrizada, sem persistir) é a CORRETA** — e por uma razão melhor do que "não tem migration".

A justificativa que a 8.5 deu é de custo (persistir exige coluna → migration → fora do escopo). Ela é
verdadeira e é a mais fraca das disponíveis. **A razão forte é que a banda fixa é uma propriedade do
experimento**: a Onda 1 existe, segundo o epic §3.1, como **instrumento de medição** — o número dela é
o gate que libera ou mata as Ondas 3 e 4 (~4,5 ondas de trabalho). Se cada tenant pode mover a banda, a
régua muda junto com o que ela mede e a leitura do gate perde sentido. Uma banda **fixa e conhecida**
durante a janela de observação é rigor, não limitação.

Sobre a letra do REQ-16 (*"deve existir banda de tolerância **configurável** abaixo da qual a
divergência é ignorada ativamente"*): o rastreio do próprio REQ é C2 (conferência, não fechamento
contábil) + I-15 do estudo. **O que é load-bearing no REQ-16 é a existência da banda e o silêncio dentro
dela** — é isso que protege a confiança no sinal. "Configurável" é propriedade de segunda ordem, e a
função pura com `floor_cents`/`pct` **já** a satisfaz no sentido de "não está cravada no meio de uma
expressão". Se o @po/fundador ler "configurável" como "pelo tenant, na tela", então é GAP — e a resposta
está abaixo. **A decisão de escopo é do @po/fundador; eu registro que não recomendo persistir na Onda 1,
com o argumento do gate acima.**

### Veredito sobre o LUGAR, se persistir: **`tenant_profiles`, duas colunas inteiras, por tenant — não por conta**

| Opção | Veredito |
|---|---|
| **`tenant_profiles`** (`apps/api/app/modules/settings/models.py`) — 1 linha por tenant, RLS, criada sob demanda com defaults, e **já carrega configuração operacional**, não só brand kit (`timezone`, `default_entry_funnel_id`, credenciais de WhatsApp) | ✅ **ESCOLHIDA.** Reusa a tabela de configuração que existe, com o padrão default-on-demand já testado em produção. Custo: 2 colunas, migration aditiva, zero backfill (⇒ zero exposição à armadilha do FORCE RLS) |
| Tabela `bank_settings` nova, 1:1 com tenant | ❌ É `tenant_profiles` com outro nome, para dois escalares. Uma tabela por conjunto de preferências é como se chega a quinze tabelas de uma linha |
| Coluna em `bank_accounts` (banda **por conta**) | ❌ **agora**, ✅ **como extensão futura.** O componente percentual **já** adapta a banda ao tamanho de cada conta — é exatamente o que faz um ajuste único servir para a corrente de R$ 80k e para a "Caixinha" de R$ 300. Banda por conta só se justifica quando aparecer **evidência** de uma conta com regime de ruído próprio; então entra como coluna **nullable de override** em `bank_accounts`, com fallback no default do tenant. Fazer antes é inventar requisito (Art. IV) |
| YAML / env var | ❌ É configuração de **negócio por tenant**, não de infraestrutura. SaaS multi-tenant não configura tenant por deploy |

**Forma das colunas — sem float no banco:**
`bank_tolerance_floor_cents BIGINT NOT NULL DEFAULT 5000` e
`bank_tolerance_bps INTEGER NOT NULL DEFAULT 50` (basis points; 50 bps = 0,5%). O percentual entra como
**inteiro em pontos-base**, não `float`/`NUMERIC`: mantém a disciplina "dinheiro e taxas de dinheiro em
inteiro" do projeto e o cálculo fica `round(abs(saldo) * bps / 10_000)` — determinístico, sem
arredondamento de binário flutuante persistido. A função pura continua sendo **o único lugar da
fórmula**; o que muda é de onde vêm os dois parâmetros (uma linha em `reconciliation.py`).

**Dono da migration: NÃO a story do `bank_accounts`.** `tenant_profiles` não é tabela do módulo `bank`;
enfiar `ALTER TABLE tenant_profiles` no revision que cria `bank_accounts` mistura dois domínios num
arquivo e torna o `downgrade` mais arriscado do que precisa. Se o REQ-16 exigir persistência, ela é
**story própria com revision própria** — e, graças ao D-6, não há "vaga de 0058" a disputar.

| Onde | O que muda |
|---|---|
| `design.md §5.1.1` | ✅ **JÁ FEITO** — nova seção com a tabela de opções, a forma das colunas, o dono da migration e o argumento do gate. |
| `design.md §10 D1` e `§8` (resumo) | ✅ **JÁ FEITO** — o default de D1 passa a citar §5.1.1; a tabela de ondas ganha a linha condicional da banda persistida. |
| `docs/stories/8.5.story.md` | **AUTO-DECISION da banda:** manter a decisão, e **trocar a justificativa**: a razão principal é o gate do epic §3.1 (banda fixa = propriedade do instrumento de medição), não a ausência de migration. Na nota "⚠️ Para o @po/@architect", trocar *"pertence à migration 0058 (Story 8.2) ou a um follow-up"* por *"pertence a uma story própria, com revision própria, em `tenant_profiles` — design §5.1.1; **nunca** à migration do `bank_accounts`"*. |
| @po / fundador | Decisão de escopo: a forma parametrizada satisfaz o REQ-16 na Onda 1 (**minha recomendação: sim**), ou entra como story de follow-up? Se entrar, o lugar já está resolvido e o esforço é ~0,25 onda. |

---

## 9. O que estes desvios expuseram no meu design

Três coisas, em ordem de gravidade. As duas primeiras são minhas.

**(1) Eu escrevi um campo antes de terminar de modelar o conceito (D-3).** `*_origem` nasceu como "todo
saldo declara procedência" — uma regra boa — e eu a apliquei a três lugares que respondiam a **duas**
perguntas diferentes, produzindo três vocabulários incompatíveis no mesmo documento. O sintoma que
deveria ter me alertado estava na página: a §2.4 já tinha `origin manual|ofx` numa coluna, e a §5.1
inventou `declarado|extrato` para os mesmos dois valores. **Regra que tiro disto e que vale para o resto
deste design:** quando o mesmo conceito aparece com dois vocabulários em duas seções, o problema quase
nunca é redação — é que são dois conceitos. Um documento longo esconde isso; duas stories escritas em
paralelo o encontram em um dia. Esse é o valor real deste ciclo.

**(2) Eu especifiquei uma supressão em termos de superfície, e não de afirmação (D-1 + D-5).** *"Deixa
de ser exibido"* é uma frase sobre tela. A pergunta certa era *"o produto tem lastro para fazer esta
afirmação?"* — e, feita assim, ela se aplica igualmente ao runway **e** ao alerta de janela negativa,
e a resposta não depende de quantas telas existem. Foi por especificar em termos de superfície que eu
(a) mapeei uma de duas e (b) criei uma assimetria entre dois sinais igualmente contaminados. **Regra:
um critério de pronto que fala do usuário exige uma regra que viva na origem do dado.** É também um
sinal de que o `*_origem` do §1.3c precisa de um irmão conceitual: *o que o sistema tem o direito de
afirmar dado o valor daquele campo*. A §6.1.1/§6.1.2 são a primeira aplicação disso; se aparecer uma
terceira inferência sobre `saldo_inicial`, ela nasce com a mesma pergunta.

**(3) O `saldo_inicial` contaminado tem MAIS consumidores do que a §6.1 lista — e a Onda 0 é a hora de
varrer.** Encontramos dois (`runway.days`, `ProjectionWindow.alert`). Não afirmo que sejam os únicos: eu
mesma tinha mapeado **um**, e o `alert` só apareceu porque um @sm foi ler o `engine.py`. **Instrução
para o gate da 8.1:** antes de aprovar, varrer os consumidores de `CashProjection` (hoje: `router.py`,
`diagnostics.py`, `ProjecaoCaixaPage.tsx`, e a suíte) e confirmar que **nenhuma outra inferência** —
não número bruto, mas *inferência* — deriva do `saldo_inicial`. `trajectoryPoints`/`TrajectoryChart` é o
próximo candidato a examinar: a trajetória **é** o número (legítimo de exibir com rótulo), mas se
alguma superfície tirar dela uma conclusão de "quando cruza o zero", é a mesma classe de defeito.
`cockpit.finance_summary` está fora — usa `available_cents` como **faturamento líquido**, que é uso
correto (§6.5) e não deve mudar.

**Uma nota sobre o que NÃO estava errado.** A qualidade dos sete escalonamentos é alta: cada um traz
`arquivo:linha`, o custo da alternativa e o que quebra. O D-5 em particular foi marcado pelo @sm como
"ponto legítimo para a @architect discordar" — e é o único dos sete que eu rejeitei. Escalar em vez de
decidir em silêncio, e **nomear onde a própria decisão é frágil**, é o comportamento que fez este
parecer possível em uma sessão em vez de em um post-mortem.

---

## 10. Resumo das instruções por arquivo (para @po / @dev)

> Nenhuma story foi editada por mim. Aplicar na ordem: 8.1 primeiro (é dona do vocabulário e do
> contrato da Onda 0), depois 8.2, 8.4, 8.5, 8.6.

| Story | Mudanças | Bloqueia implementação? |
|---|---|---|
| **8.1** | `ORIGENS` com **4** valores (sai `ORIGEM_DECLARADO`); AC1 com o domínio novo; **suprimir também `ProjectionWindow.alert`** (`alert_suprimido`, nota, schema, router, `projecao.ts`, `WindowCard`/`TrajectoryChart`, AC6 estendido, 2 invariantes); sai a seção "Resíduo conhecido"; sai a instrução de acrescentar `extrato` a `ORIGENS`; **+ `test_todo_saldo_declara_origem`** (5º teste da Regra dos Planos, design §1.3) | **SIM** — D-5 muda escopo (pequeno) e D-3 muda um contrato consumido por 4 stories |
| **8.2** | `derived_balances` → `derived_balances_as_of(as_of=…)` + docstring proibindo o uso na conferência; consumidor passa a ser 8.7; **remover** o ponto de alinhamento nº 2; "Numeração de migration" passa de "contradição não resolvida" a "resolvida" | **SIM** (rename de contrato público) |
| **8.4** | Remover a tradução `origin='manual'` → `ORIGEM_DECLARADO`; `ORIGIN_MANUAL`/`ORIGIN_OFX` **são** o vocabulário do eixo B; ajustar a redação "migration 0058" | **SIM** (contrato consumido pela 8.5) |
| **8.5** | `saldo_banco_origem = ORIGEM_BANCO` + `saldo_banco_fonte = checkpoint.origin` + `saldo_sistema_origem`; dataclasses com os 2 campos novos; AC4b atualizado (nome + "contrato ratificado", não "divergência"); justificativa da banda passa a ser o gate §3.1; nota do @po aponta `tenant_profiles` | **SIM** |
| **8.6** | `dias_desde_ultima_conferencia` migra para `CompletenessAccountInput`; fundir as duas regras 🟡 numa (1 por conta); coluna de cardinalidade na tabela do AC3; Task 4 sem `max()`; Task 6 com o teste novo | **SIM** |
| **8.3 / 8.7 / 8.8** | Nada identificado por este parecer. **@po:** se a 8.7 citar a função de saldo em lote, atualizar o nome; se a 8.8 tocar `days_suprimido`, acrescentar `alert_suprimido` na restauração | Não |
| **Epic 8** (`docs/prd/`) | **@pm:** §4.1c (lista de 5 valores → design §1.3.1) e §5 + §"Contexto" (coluna Migration = ordem, não identificador). Não editei — é artefato do @pm e nada nele bloqueia as stories corrigidas | Não |
