# Vima V2 — a medição de ativação do núcleo (instrumentar, não analisar)

> **Sub-projeto:** Vima V2 (DNA da Empresa) — fechamento de dívida
> **Data:** 2026-08-11 · **Base:** `main @ 0d8b4ce` · **head do alembic:** `0077` · **sem migration**
> **Docs-mãe:** `docs/superpowers/specs/2026-08-08-vima-dna-da-empresa-design.md` (§"O núcleo tem custo
> de ativação real"; §Fora de escopo, *"Medição de ativação do núcleo → dívida de analytics"*) ·
> `docs/superpowers/specs/2026-08-06-vima-registro-de-fatos-e-briefing-design.md` (o roadmap V0–V6)
> **Precedentes de método:** `ai_usage` (PR #87, *"só MEDIR"*) · `app/scripts/investment_audit.py`
> (script sem `--fix`) · a sondagem de `phone_key` (RLS devolvendo zero e o silêncio parecendo aprovação)

---

## 0. O que esta onda entrega, em uma frase

O DNA passa a **deixar rastro append** de tudo que acontece com ele — respondida, pulada, núcleo aberto,
núcleo abandonado — em `audit_entries`, mais um script que lê esse rastro. **Instrumentar, não
analisar:** nenhuma tela, nenhum endpoint de métrica, nenhum limiar.

### 0.1 A dívida tem três partes, e esta onda fecha uma e meia

O enquadramento honesto, porque a tentação é vender isto como *"destrava o V4"*:

| Parte da dívida do V2 (`CLAUDE.md`) | Fecha aqui? |
|---|---|
| *"não há medição de ativação do núcleo, então não se sabe se ele ajudou ou atrapalhou"* | ✅ **fecha** |
| *"a quarentena de 7 dias e o 'uma por dia' são números sem evidência"* | ⚠️ **meia** — passa a existir evidência; ler 2 tenants não confirma número |
| *"as 46 perguntas nunca foram validadas com dono real"* | ❌ **não fecha** — não é instrumentável; é conversa com dono |

E o V4 depende de o **dossiê ser consumido** (declarado fora de escopo do V2), que é problema do V4.
**Esta onda dá chão; ela não destrava sozinha.**

### 0.2 O que NÃO entrega

- **Nenhuma tela, nenhum dashboard, nenhum endpoint de leitura.** A leitura é script (§4).
- **Nenhum limiar** de "quantos tenants bastam" (§5).
- **Nenhuma migration.** `action` (128) e `target` (255) de `audit_entries` bastam.
- **Nenhuma medição de tempo-em-tela nem latência por pergunta.** Fora de escopo: exigiria telemetria
  de interação, e a pergunta da dívida não precisa dela.
- **Nenhuma agregação cross-tenant.** Com N=2 (§1) agregar é aritmética sobre ruído.

---

## 1. A população decide o desenho, e ela é 2

**Decisão do fundador, 2026-08-11:** os tenants reais que passarão pelo núcleo nos próximos ~3 meses são
**dois** — ele e o sócio (a produção foi zerada em 05/08/2026 justamente para o sócio começar do zero).

> **Consequência que reescreve a tarefa:** *"medição de ativação"* é métrica de funil, e funil com N=2 é
> ilusão estatística — **1 de 2 pulando o núcleo é "50% de abandono" e não significa nada.** Construir
> o funil agora seria produzir um número que mede a própria escassez de população, com aparência de
> fato. É a família de erro que o Epic 8 documenta três vezes (a divergência da Onda 1 medindo a
> ausência de uma porta; `derived_balance(until=opening_date)` idêntico à âncora por construção;
> `movimentos_sem_contrapartida` contando o tamanho do extrato).

Então o desenho se parte em duas metades com naturezas diferentes:

| | Como se responde | Quando |
|---|---|---|
| *"O núcleo ajudou ou atrapalhou?"* | **perguntando às duas pessoas reais** | agora, e é conversa, não feature |
| *"Como isso será respondível quando houver população?"* | **gravando o que não se reconstrói** | agora, porque o evento é destruído no instante em que acontece |

**Esta spec entrega só a segunda metade.** E o que a justifica **não é a estatística** — é
irreconstrutibilidade, o mesmo argumento que o `ai_usage` registrou: *"o consumo passado não foi
guardado por ninguém e não tem como ser reconstruído."*

---

## 2. Os três achados que reescreveram a dívida

A dívida escrita diz *"não há medição de ativação"*. Verificado no código, o estado é pior em três
pontos — e os dois primeiros são **destruição de dado acontecendo agora**.

### 2.1 `dna_answers` é upsert, e ele apaga exatamente a evidência do núcleo

`service._gravar` (`apps/api/app/modules/dna/service.py:98-112`) faz **upsert** por
`(tenant, question_key)`: sobrescreve `value`, `answered_at`, `answered_by` **e `source`**.

Consequência: o dono responde `oferta.ticket_tipico` no núcleo (`source='nucleo'`) e, semanas depois,
edita a mesma pergunta na aba de `/config` (`source='config'`). **A linha passa a dizer que aquela
resposta nasceu no `/config`.** O fato de ela ter vindo do núcleo — e *quando* — deixa de existir.

Não é defeito de descuido: o docstring do model declara a escolha e a defende
(*"é upsert, não append — o oposto de `core/facts.py`, e de propósito"*), com razão legítima (guardar
versões faria toda leitura decidir qual resposta vale).

### 2.2 A justificativa do upsert aponta para uma rede que NÃO EXISTE

O mesmo docstring fecha assim (`apps/api/app/modules/dna/models.py:5`):

> *"…e o histórico de quem mudou o quê já é trabalho de `core/audit.py`."*

**Verificado: `audit` aparece UMA vez em todo o módulo `dna` — dentro dessa frase. Zero chamadas.**
`responder`, `pular` e o router não gravam trilha nenhuma.

> **É a classe de defeito nº 1 do Epic 8** — *o documento que afirma sobre a camada de baixo e desliga
> quem viria conferir* —, e aqui ela é mais grave que nas quatro instâncias registradas lá, porque
> **sustenta uma decisão de modelagem**: o upsert foi aceito em troca de uma rede que ninguém teceu.
> A regra que aquele épico escreveu se aplica literalmente: *uma afirmação sobre o comportamento de
> outra camada é verificável; verifique-a ou não a escreva.*

### 2.3 O abandono do núcleo inteiro não deixa rastro, e não dá para reobservar

O núcleo tem **duas saídas, e elas não são simétricas**:

| Saída | Caminho | O servidor vê? |
|---|---|---|
| Pular **uma** pergunta | `PerguntaDaVima` → `POST /dna/{key}/pular` | ✅ grava linha com `value=None` |
| **"Pular por enquanto"** (as 6 de uma vez) | `NucleoPage.sair()` (`NucleoPage.tsx:44-51`) | ❌ **`localStorage` + `navigate`. Zero chamada.** |

**O único evento que responde à pergunta da dívida é o que não deixa rastro.** E `sair()` grava
`e1p_dna_nucleo` no `localStorage`, então **o núcleo não volta naquele aparelho** — não há nem como
reobservar depois. O evento é destruído no instante em que acontece.

⚠️ **E `sair()` é também o caminho de ERRO** (`NucleoPage.tsx:34-37`): 403 de sub-usuário sem o módulo
`settings`, ou rede ruim. Hoje *"não tenho permissão"* e *"decidi não responder"* gravam a mesma marca
— e a marca é invisível para o servidor. A §3 resolve isso sem inventar um terceiro evento.

---

## 3. Onde o rastro mora, e o vocabulário

### 3.1 `audit_entries` — a escolha faz três trabalhos de uma vez

1. **Sobrevive ao upsert.** `audit` é append-only; `_gravar` sobrescreve. Editar no `/config` deixa de
   apagar a história.
2. **Faz a docstring da §2.2 virar verdade** em vez de a corrigir para menos. A alternativa — reescrever
   a frase para *"não há histórico"* — seria honesta e perderia a oportunidade: o histórico **deve**
   existir, e o lugar que a frase nomeia é o lugar certo.
3. **Zero migration.** `action` (`String(128)`) e `target` (`String(255)`) bastam.

**Alternativa rejeitada — tabela append própria (`dna_answer_events`):** semântica mais limpa, mas
custa migration e deixaria **a promessa falsa de pé ao lado de uma tabela certa** — duas fontes para a
mesma pergunta, e a de prosa é a que ninguém atualiza.

**Alternativa rejeitada — `core/facts.py`:** `facts` é a narrativa que o **briefing lê**. *"Você
respondeu uma pergunta do DNA"* não é notícia para o dono, e `facts.record` exige que o `kind` comece
pelo `module` do vocabulário de `allowed_modules` — o DNA sairia sob `settings` e poluiria a leitura.
`audit_entries` é trilha técnica (*"quem mutou o quê"*), que é exatamente o que isto é.

### 3.2 O vocabulário, e por que `source` vai no `target`

Estilo da casa, verificado (117 actions distintas): `<entidade>.<entidade>.<verbo>`, inglês, minúsculas,
pontos — `bank.account.create`, `agenda.event.cancel`, `chart_account.archive`.

| Evento | `action` | `target` | Quem emite |
|---|---|---|---|
| Núcleo exibido | `dna.nucleo.open` | `str(n)` — o número de perguntas exibidas (§3.4) | `POST /dna/nucleo/open` |
| Resposta gravada | `dna.answer.save` | `f"{source}:{key}"` | `PUT /dna/{key}` (já existe) |
| Pergunta pulada | `dna.answer.skip` | `f"{source}:{key}"` | `POST /dna/{key}/pular` (já existe) |
| Núcleo abandonado | `dna.nucleo.abandon` | `""` | `POST /dna/nucleo/abandon` |

**A rota nova é UMA, com o evento no caminho:** `POST /dna/nucleo/{evento}`, `evento ∈ {open,
abandon}` validado contra tupla declarada — porta estreita validada contra um conjunto, como
`service._validar` já faz contra o catálogo. Corpo: `{"exibidas": n}` no `open`, vazio no `abandon`.
Responde `204`, e **o front ignora a resposta** (§6.2).

⚠️ **`source` vai no `target`, nunca no `action`.** Quatro actions × três sources (`nucleo｜gancho｜
config`) seriam **doze** strings, e é assim que 117 viram 200. O repo já tem `account_deleted` — sem
pontos, fora do padrão — provando que **a convenção sozinha não segura o vocabulário**. Daí o gate da
§6.3.

**Ganho de graça:** `responder`/`pular` já recebem `source`, então a mesma chamada cobre `nucleo`,
`gancho` **e** `config` sem uma linha extra. É isso que produz a evidência sobre a quarentena de 7 dias
e o "uma por dia" (a meia dívida da §0.1) — e é por isso que a instrumentação **não** é escopada só ao
núcleo.

### 3.3 O caminho de erro grava NADA, e é isso que o torna distinguível

`dna.nucleo.open` é emitido **depois** de `GET /dna/faltantes` responder com sucesso — isto é, depois de
a pessoa ter de fato visto perguntas.

- Gravar `abandon` no caminho de erro seria **mentira**.
- Criar um terceiro evento (`dna.nucleo.unavailable`) seria categoria que ninguém pediu, e um evento
  cujo consumidor não existe.
- Com `open` condicionado ao sucesso: **ausência de `open` ⇒ a pessoa nunca entrou.** Verdade, derivada,
  sem evento novo.

> **Membro** de "abandonou o núcleo": um tenant com `dna.nucleo.open` às 09:12, dois `dna.answer.save`,
> e `dna.nucleo.abandon` às 09:14.
> **Não-membro:** um sub-usuário sem o módulo `settings` que tomou 403 no `faltantes` — **nenhum
> evento**, e o relatório não o conta como abandono.

### 3.4 O denominador é gravado; o progresso é derivado

O progresso (*"parou na 3ª de 6"*) é **derivado** dos eventos entre `open` e `abandon`. Nada de valor
derivado é guardado — mesmo princípio de `last_interaction_at` nunca ser coluna, de saldo ser derivado
e de não existir `payment_route`.

**Mas o denominador não é derivável, e por isso é gravado:**

1. `GET /dna/faltantes` devolve **só as não respondidas**. Na segunda visita ao núcleo a pessoa vê
   **4**, não 6 — e "2 de 6" seria falso sobre o que ela viu.
2. `catalog.NUCLEO` pode crescer. O eixo de Calibração **já cresceu de 6 para 7 perguntas** em
   2026-08-09; se `NUCLEO` mudar, todo "k de 6" histórico viraria "k de 7" **retroativamente**.

O número exibido é **evidência do que a pessoa viu**, no princípio do `raw_description` de
`bank_transactions`: imutável porque é prova, não porque é conveniente.

---

## 4. A leitura é script, não tela

`python -m app.scripts.nucleo_activation`, no molde de `app/scripts/investment_audit.py`.

**Sem `--fix`, e a ausência é a decisão** — a razão está registrada no precedente: com uma flag de
correção, alguém a roda no deploy sem ler a saída.

Duas obrigações herdadas de defeitos que o projeto já pagou:

1. ⚠️ **Imprime quantos tenants varreu.** `0 núcleos em 0 tenants` e `0 núcleos em 7 tenants` são
   resultados **diferentes**, e o primeiro é defeito do próprio script. Lição literal do
   `investment_audit.py`.
2. ⚠️ **Roda com o papel que faz bypass de RLS (`e1p_root`).** A sondagem de `phone_key` devolveu
   `contatos=0` porque `SessionLocal` sem tenant é **fail-closed** — e o silêncio quase virou um *"está
   tudo limpo"* falso. **Auditoria de dados em tabela com RLS precisa do papel que faz bypass.**

**Saída:** por tenant, a sequência de eventos com horário local do tenant, o denominador visto, quantas
foram respondidas e quantas puladas, e se houve `abandon`. Datas por `local_date`/`format_date_br` — o
fuso do tenant, nunca UTC cru (§6.0 do `CLAUDE.md`).

**Sem tela, sem endpoint, sem dashboard.** Medir é reversível; construir superfície não. E a Conferência
já ensinou que tela nova no menu vira peso de ERP.

---

## 5. O gatilho de leitura é contador, não data

**Nenhum limiar é escrito nesta spec.** Um *"leia quando houver 20 tenants"* seria número sem evidência
— Artigo IV, e o mesmo motivo pelo qual o V2 recusou inventar a 8ª pergunta de Calibração e a frente do
ciclo da conferência **recusou codificar os "3 ciclos"** do PRD (que são `[SUPOSIÇÃO DO @PM]`).

O script imprime a contagem de tenants varridos; **a decisão de ler é do fundador**. E enquanto a
contagem for 2, a resposta à pergunta da dívida vem de conversar com as duas pessoas (§1) — o rastro
existe para o dia em que isso deixar de ser verdade.

---

## 6. Invariantes, gates e testes

### 6.1 `db.flush()` antes de `audit.record`

Sem ele o `target` nasce **vazio**: o `id` da linha tem default **Python-side**. É o defeito **MNT-001**,
que 17 call sites do projeto têm e que o módulo `bank` **já evita** — e é o padrão a copiar.
**Teste:** após responder, existe entrada de audit com `target != ""`.

### 6.2 O beacon NUNCA tranca a porta

`NucleoPage` já tem a covardia certa para o 403 e para rede ruim: cai em `sair()`. A instrumentação tem
de ter a mesma. **Teste:** `POST /dna/nucleo/open` devolvendo 500 ⇒ a página continua exibindo as
perguntas; `POST /dna/nucleo/abandon` falhando ⇒ a navegação acontece de qualquer forma. **O núcleo não
pode trancar a entrada do produto por causa de telemetria** — o `abandon` é disparado e a saída **não o
aguarda** (nem `await` bloqueante antes do `navigate`, nem `catch` que desvie o fluxo).

### 6.3 Gate de vocabulário, com controle positivo

Toda `action` emitida pelo módulo `dna` **começa com `dna.`** e está numa tupla declarada no módulo.
`facts.record` tem guarda mecânica equivalente (o `kind` tem de começar pelo `module`) e
`audit.record` **não tem nenhuma** — e `account_deleted` é a prova de que a convenção sozinha não
segura. **Controle positivo obrigatório:** sem ele, um gate que deixasse de encontrar as strings passaria
verde por vacuidade.

### 6.4 O teste que prova que o achado §2.1 está fechado

Responder `oferta.ticket_tipico` com `source='nucleo'`, depois **editar a mesma pergunta** com
`source='config'`, e asserir que existem **duas** entradas de audit — `dna.answer.save` com
`target="nucleo:oferta.ticket_tipico"` **e** com `target="config:oferta.ticket_tipico"` —, enquanto
`dna_answers` tem **uma** linha só. É o teste de maior valor da onda: ele é a diferença entre o upsert
apagar história e o upsert ser só estado atual.

### 6.5 A derivação do progresso, com controle positivo

O script calcula *"respondeu k de N"* a partir dos eventos. **Controle positivo:** um caso em que k > 0,
senão o teste passa verde num script que devolve zero para sempre — a família do §2 do Epic 8 (*o teste
que passa e não prova nada*), e o mesmo cuidado que o `test_volume_nao_altera_a_divergencia` tomou.

### 6.6 Fuso

O script e qualquer leitura de dia usam `local_date` / `hoje_do_tenant`, **nunca** `datetime.now(UTC)`
nem `.date()` em `timestamptz`. `cadencia.py` já documenta esse erro exato, e `dna/` já está na varredura
AST de `tests/test_fuso_do_tenant.py` — a instrumentação nova entra sob o mesmo gate.

---

## 7. Consequências aceitas

- **LGPD: `audit_entries` é purgado com o tenant** pelo `delete_account` (descoberta dinâmica de
  subclasses de `TenantMixin`). Tenant que sai **leva a ativação dele**. É o comportamento correto, e
  `platform_audit_entries` **não** é usada aqui: aquela existe para operação destrutiva do Master, não
  para telemetria de produto.
- **`audit_entries` cresce.** Quatro eventos por tenant por passagem no núcleo, mais um por resposta de
  gancho. Ordem de grandeza: dezenas por tenant por ano. Irrelevante hoje; anotado para não ser
  descoberto como surpresa.
- **A marca `localStorage` continua sendo a autoridade sobre reexibir o núcleo.** Esta onda **não** a
  move para o servidor: seria mudança de comportamento embutida numa onda de medição, e misturar as
  duas tira do gate a capacidade de julgar o que quebrou o quê (o argumento que manteve SIG-001 fora da
  8.16 e separou 8.19 de 8.20). Consequência: um dono que abandonou o núcleo no celular e depois abre no
  desktop **verá o núcleo de novo**, e o rastro mostrará dois `open`. Isso é verdade sobre aparelhos, e
  o script não deve reportá-lo como duas passagens do mesmo dono sem dizer que são dispositivos.
- **Nada disto valida as 46 perguntas** (§0.1). Continua dívida aberta, e continua não sendo
  instrumentável.

---

## 8. Esforço

| Parte | `[EST.]` |
|---|---|
| `audit.record` em `responder`/`pular` + `flush` + gate de vocabulário (§6.1, §6.3) | 0,05 |
| Rota `open`/`abandon` + chamada no `NucleoPage` + teste da covardia (§6.2) | 0,08 |
| `app/scripts/nucleo_activation.py` (§4) | 0,05 |
| Entrada no `CLAUDE.md` (§5, passo 4 — o AC que ninguém pula) | 0,02 |
| **Total** | **~0,2 onda · zero migration** |

`[EST.]` calibrada contra ondas entregues; não há velocity confiável.

---

## 9. Definição de pronto

1. Responder e pular gravam `audit_entries` com `target != ""` (§6.1).
2. `dna.nucleo.open` só é emitido **depois** de `faltantes` ter sucesso; 403 não produz evento (§3.3).
3. `dna.nucleo.abandon` é emitido por "Pular por enquanto", e **falhar não impede a saída** (§6.2).
4. Editar no `/config` uma pergunta respondida no núcleo deixa **duas** entradas de audit e **uma** linha
   em `dna_answers` (§6.4).
5. O gate de vocabulário passa, com controle positivo (§6.3).
6. `python -m app.scripts.nucleo_activation` imprime **quantos tenants varreu** e roda sob `e1p_root`
   (§4).
7. Datas no fuso do tenant; a varredura AST de `test_fuso_do_tenant.py` continua verde (§6.6).
8. **A docstring de `dna/models.py:5` deixa de ser falsa** — e ganha, ao lado, a lista de call sites
   verificável por `grep` (a regra do item 12 do WhatsApp: *a lista de consumidores na docstring tem que
   ser verificável*).
9. **Entrada no `CLAUDE.md`**, escrita a partir do código que subiu.

---

## 10. Rastreabilidade (Artigo IV — No Invention)

| Afirmação desta spec | Fonte |
|---|---|
| A dívida "não há medição de ativação do núcleo" | `docs/superpowers/specs/2026-08-08-vima-dna-da-empresa-design.md` §"O núcleo tem custo de ativação real"; `CLAUDE.md` §Vima V2 |
| "Medição de ativação" está declarada fora de escopo do V2 como dívida de analytics | mesma spec, §Fora de escopo |
| O roadmap V0–V6 e a dependência do V4 em V0+V2 | `docs/superpowers/specs/2026-08-06-vima-registro-de-fatos-e-briefing-design.md` |
| O V4 exige o dossiê **consumido**, o que o V2 não faz | spec do V2, §Fora de escopo |
| `dna_answers` é upsert por `(tenant, question_key)` | `apps/api/app/modules/dna/service.py:98-112` |
| O docstring afirma que o histórico é trabalho do `core/audit.py` | `apps/api/app/modules/dna/models.py:5` |
| **`audit` tem ZERO chamadas no módulo `dna`** | `grep -rn audit apps/api/app/modules/dna/` → só a linha do docstring |
| Pular uma pergunta chama a API; "Pular por enquanto" não | `apps/web/src/features/dna/PerguntaDaVima.tsx:41-46`; `NucleoPage.tsx:44-51` |
| `sair()` também é o caminho de 403/rede | `NucleoPage.tsx:34-37` |
| `catalog.NUCLEO` tem 6 perguntas | `apps/api/app/modules/dna/catalog.py:528` |
| O eixo de Calibração cresceu de 6 para 7 perguntas | `CLAUDE.md` §"A cobrança ganhou antecedência" |
| `audit_entries` tem `action` 128 e `target` 255, e é append | `apps/api/app/core/audit.py:14-30` |
| 117 actions distintas, estilo `<entidade>.<entidade>.<verbo>`; `account_deleted` fora do padrão | varredura `grep -rhoP 'action="[a-z_.]+"'` em `apps/api/app/modules/` |
| MNT-001: `target` vazio sem `flush`, 17 call sites, `bank` já correto | `CLAUDE.md` §Onda 1 (dívidas) |
| `facts.record` tem guarda mecânica de `kind`; `audit.record` não tem | `apps/api/app/core/facts.py`; `core/audit.py` |
| `audit_entries` é purgado com o tenant; `platform_audit_entries` sobrevive e é para o Master | `apps/api/app/core/audit.py:33-45` |
| Script sem `--fix`; imprime quantos tenants varreu | `app/scripts/investment_audit.py`; `CLAUDE.md` §Onda 2b-ii |
| Auditoria sob RLS precisa do papel de bypass, senão zero linhas parecem aprovação | `CLAUDE.md` §WhatsApp item 13 (sondagem de `phone_key`) |
| "Hoje" é `hoje_do_tenant`; `.date()` em `timestamptz` é o erro | `CLAUDE.md` §6.0; `dna/cadencia.py` (docstring) |
| `dna/` já está na varredura AST de fuso | `CLAUDE.md` §Vima V2 |
| Não misturar correção de defeito existente com regra nova no mesmo diff | `CLAUDE.md` §Onda 2b-ii, §Onda 3 (SIG-001, 8.19/8.20) |
| Lista de consumidores na docstring tem de ser verificável por `grep` | `CLAUDE.md` §WhatsApp item 12 |
| `[EST.]` de esforço | **[ESTIMATIVA]** calibrada contra ondas entregues |
| **N = 2 tenants reais nos próximos ~3 meses** | **decisão do fundador, 2026-08-11** (esta sessão) |
| **O corte "instrumentar, não analisar"; os quatro eventos; `source` no `target`** | **decisão do fundador, 2026-08-11** (esta sessão) |
| O denominador gravado e o progresso derivado | **[PROPOSTA desta spec]** |
| O caminho de erro não gravar nada como discriminador | **[PROPOSTA desta spec]** |
| Os três achados da §2 | **[ACHADOS desta spec]**, verificados no código |
