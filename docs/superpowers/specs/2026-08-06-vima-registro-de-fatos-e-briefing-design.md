# Vima — Registro de Fatos e o Briefing

**Data:** 2026-08-06
**Status:** Aprovado (design)
**Escopo:** V0 (Registro de Fatos) + V1 (Briefing) da visão Vima
**Módulos afetados:** `crm` (absorve `client_events`), `whatsapp_inbox`, `receivables`, `payables`, `agenda`, `quotes`, `pages`, `funnels`, `auth` (preferências do usuário), `core` (novo `facts.py`, `capabilities.py`), `settings`, `apps/web` (nova feature `vima`, reorganização de `config`)

---

## Problema

O e1p já tem as mãos. Trinta módulos em produção que fazem coisas de verdade: emitir boleto,
mandar WhatsApp, agendar, mover card no CRM, gerar contrato, conciliar banco.

O que ele não tem é **memória do que aconteceu**. [`core/events.py`](../../../apps/api/app/core/events.py)
é in-process, síncrono, e o próprio comentário admite: *"Por ora não há assinantes"*. Nada é
persistido. Não existe nenhuma consulta no sistema capaz de responder "o que aconteceu desde
ontem à noite".

A consequência é que o dono de uma empresa de uma pessoa precisa **ir buscar**. Abre a agenda,
abre o CRM, abre as cobranças, abre as conversas — e monta na cabeça o quadro que o sistema
tinha condições de montar para ele. O produto organiza informação; ele não reduz decisão.

Três coisas específicas ficam invisíveis hoje:

1. **O que aconteceu enquanto ele não estava olhando.** Um formulário preenchido às 2h, um
   pagamento compensado de madrugada, um cliente que respondeu no domingo.
2. **O que *não* aconteceu.** O cliente que não respondeu, a proposta parada há doze dias, o
   boleto que vence amanhã, a landing page que faz seis dias não gera lead.
3. **A automação que quebrou em silêncio.** Uma ação de nó do funil que falha marca a `run` como
   `failed` e **não derruba a request** — por design. Ninguém é avisado. O dono descobre semanas
   depois porque um cliente reclamou.

Existe um precedente do padrão certo, e ele funciona: `client_events`, criado na spec
[2026-08-04-crm-jornada-unica-do-contato](2026-08-04-crm-jornada-unica-do-contato-design.md), é
uma linha do tempo narrativa — mas só do CRM, e só por contato. Não há equivalente para o
negócio inteiro.

---

## Objetivo

Um registro durável de fatos do negócio, e uma leitura diária que o dono recebe **sem
perguntar**.

Este documento cobre as duas primeiras camadas de uma visão maior (a "Vima"), decompostas assim:

| | Sub-projeto | Depende de |
|---|---|---|
| **V0** | **Registro de Fatos** — todo módulo grava fato durável | — |
| **V1** | **O Briefing** — a primeira aparição da Vima, só leitura | V0 |
| V2 | DNA da Empresa — as ~50 perguntas de comportamento | — |
| V3 | Memória Empresarial — "o que preciso saber antes de ligar pro João?" | V0 |
| V4 | Motor de Contexto + Planejador + Autonomia Progressiva | V0, V2 |
| V5 | Os Funcionários (Comercial, Financeiro, Secretária, Jurídico) | V4 |
| V6 | Automação por fala | V0, V4 |

**Só V0 e V1 estão especificados aqui.** V2–V6 aparecem para fixar a ordem de dependência e
justificar por que o registro vem primeiro.

### A escolha estruturante

O briefing responde por **três mecanismos determinísticos**, e a IA não participa de nenhum deles:

| Categoria | Mecanismo | Exemplo |
|---|---|---|
| **Fato** | Leitura do log | *"Pagamento de João recebido"* |
| **Ausência** | Consulta ao estado em aberto + relógio | *"Você esqueceu de responder Carlos"* |
| **Tendência** | Agregação comparada a janela anterior | *"Sua margem caiu de 24% para 18%"* |

A quarta categoria — **Inferência** (*"há oportunidade de vender para três clientes semelhantes
ao João"*) — **fica fora do V1**, e a razão é assimetria de credibilidade: um fato errado é um
bug; uma inferência errada ensina o dono a não confiar no briefing, e a partir daí ele lê por
cima mesmo quando os fatos estão certos.

**A LLM só narra.** Ela recebe um payload já calculado, já priorizado e já cortado, e devolve
prosa. Não origina número, nome, data nem ordem.

Isso não é invenção desta spec: é o padrão que
[`financial_intelligence/ai_narrator.py`](../../../apps/api/app/modules/financial_intelligence/ai_narrator.py)
já estabeleceu e provou em produção — *"a IA entra SÓ AQUI e SÓ DEPOIS de o motor puro já ter
calculado os sinais"*. O V1 generaliza esse padrão de um domínio para o negócio inteiro.

---

## V0 — O Registro de Fatos

### A tabela `facts` substitui `client_events`

Decisão: **consolidar**, não coexistir. `client_events` tem poucos registros (dois tenants, ainda
em teste) e nasceu há dois dias — é o momento mais barato que vai existir para unificar. A
`crm/timeline.py` passa a ler de `facts`.

Migration a partir de `origin/main` (head atual **0068**): **0069**.

### Colunas

| Campo | Tipo | Razão |
|---|---|---|
| `id` | `String(36)` PK | uuid, padrão do repositório |
| `tenant_id` | via `TenantMixin` | RLS `FORCE` e purga por tenant saem de graça — `platform/service.py` descobre a tabela sozinho por `issubclass(mapper.class_, TenantMixin)` |
| `module` | `String(32)` | O vocabulário de `allowed_modules`. É o eixo de permissão. |
| `kind` | `String(48)` | Taxonomia `<módulo>.<entidade>.<verbo-no-passado>` |
| `title` | `String(255)` | Texto congelado, uma linha, **sem valor monetário** |
| `body` | `Text` nullable | Texto congelado, detalhe. Nulo na maioria dos casos. |
| `client_id` | `String(36)` FK → `clients.id`, `ondelete="CASCADE"`, **nullable** | Sujeito privilegiado |
| `subject_type` / `subject_id` | `String(32)` / `String(36)`, nullable | Referência leve para os demais sujeitos (cobrança, evento, orçamento, página, jornada) |
| `actor` | `String(64)` | `user:<id>`, `client`, `system`, `ai` |
| `is_ai` | `Boolean` default `False` | Regra de Ouro nº 3 |
| `occurred_at` | `DateTime(timezone=True)` | **Distinto de `created_at`** |
| `origin` | `String(16)` default `"emitted"` | Distingue emissão de um backfill futuro sem migration |
| `created_at` / `updated_at` | via `TimestampMixin` | com a ressalva abaixo |

Índices: `(tenant_id, occurred_at DESC)` para a janela do briefing; `(tenant_id, client_id, occurred_at DESC)` para a timeline do contato; `(tenant_id, module, occurred_at DESC)` para o filtro de permissão.

### Cinco invariantes

**1. Texto congelado.** `title` e `body` são texto, não referência. Um fato gravado hoje diz
*"Movido de Em contato → Proposta"* e continua dizendo isso depois de a coluna ser renomeada ou
arquivada. Evidência não se reescreve sozinha — mesmo princípio de `bank_transactions.raw_description`.

**2. O fato não guarda dinheiro.** O fato diz *"Pagamento de João recebido"*, nunca *"Recebido
R$ 3.200"*. Copiar `amount_cents` criaria uma segunda versão da verdade sobre dinheiro — a forma
exata do bug que a Onda 0 do Epic 8 gastou uma onda inteira desfazendo. O valor é lido de
`charges`/`bank_transactions` **na composição**, não na gravação.

Esta invariante é também um **controle de segurança**: como o texto congelado nunca contém valor,
um fato de `crm` é estruturalmente incapaz de vazar um número financeiro para um sub-usuário que
só tem CRM.

**3. `created_at` com default do lado do Python**, sobrescrevendo o `server_default=func.now()`
do `TimestampMixin`. No Postgres, `now()` é o timestamp da **transação**: dois fatos gravados no
mesmo commit sairiam com instante idêntico, o desempate cairia no uuid, e a linha do tempo
mostraria "Reaberto" acima de "Voltou pelo site" — invertendo a causalidade na tela. Lição já
paga por `ClientEvent`; herdada literalmente.

**4. `occurred_at` é quando aconteceu, `created_at` é quando gravamos.** Uma mensagem recebida às
23h50 e processada às 23h55 pertence à noite de ontem. A janela do briefing usa `occurred_at`.

**5. `kind` é um registro, não string livre.** Um módulo de constantes com a convenção. Trinta
módulos emitindo string solta produzem `payment_received` e `payment.received` convivendo em seis
meses.

### Onde o fato nasce

**Na camada de serviço, dentro da mesma transação do fato de negócio.**

Não no router — rota não é o único caminho de escrita; o worker e o motor de funil também mudam
estado. E não num assinante de `core/events.py` — ele é in-process, síncrono, e um assinante que
falha faz o fato sumir em silêncio (o próprio módulo declara que reações são *best-effort*).

Mesma transação porque um fato que existe sem o negócio, ou o inverso, é pior que nenhum fato.

`core/facts.py` expõe **uma função**, não um framework:

```python
def record(db, *, module, kind, title, body=None, client_id=None,
           subject_type=None, subject_id=None, actor, is_ai=False, occurred_at=None):
    """Grava um fato narrativo. Sem retry, sem fila, sem abstração.
    Se falhar, a transação inteira falha — que é o comportamento correto."""
```

⚠️ Chamar `db.flush()` antes de usar o `id` do objeto de negócio como `subject_id` — a dívida
**MNT-001** do CLAUDE.md registra 17 call sites de `audit.record(target='')` causados exatamente
por gravar a trilha antes do `flush`.

### Quem emite na Onda 1

Oito módulos — os que produzem o material do briefing:

| Módulo | Fatos |
|---|---|
| `crm` | lead entrou, voltou, mudou de etapa, reabriu, anotação |
| `whatsapp_inbox` | mensagem recebida de contato |
| `receivables` | cobrança paga, vencida, protestada |
| `payables` | conta paga, vencendo |
| `agenda` | evento criado, cancelado, remarcado, prazo estourado |
| `quotes` | orçamento enviado, aceito, recusado |
| `pages` | formulário recebido (**com qual página converteu**), página publicada |
| `funnels` | contato inscrito, jornada retomada, jornada concluída, **jornada falhou** |

Os outros módulos entram depois, um por vez. **O registro não precisa nascer completo; precisa
nascer correto.**

**`marketing` fica de fora, e o motivo é honesto:** hoje o módulo é o gerador de carrossel.
Publicação, agendamento, Meta Ads e métricas estão como dívida, não construídos. O único fato que
ele produziria é *"você gerou um carrossel"* — o dono acabou de fazer isso. Reportar de volta uma
ação do próprio dono não é briefing, é eco. `marketing` entra quando passar a acontecer coisa sem
ele.

### Sem backfill — decisão explícita

Os fatos valem **a partir da implantação**. Nenhuma reconstrução de histórico a partir de
`audit_entries` ou de timestamps.

**Consequência aceita:** a metade narrativa da Memória Empresarial (V3) nasce vazia e só fica boa
depois de alguns meses de acúmulo.

**Consequência mitigada:** a metade **financeira** do histórico do contato continua retroativa por
construção, porque `crm/timeline.py` lê `quotes`/`charges` **na origem** — comportamento que esta
spec preserva sem mudanças. E a categoria **Ausência** do briefing (abaixo) lê estado em aberto,
não o log, então funciona **completa no dia 1**.

O campo `origin` existe para que um backfill futuro seja distinguível sem migration. Nenhuma
consulta pode assumir que o log cobre desde sempre.

### LGPD: expurgo explícito por sujeito

A referência polimórfica (`subject_type`/`subject_id`) **não cascateia**. O `client_id` cascateia
(FK real), o que resolve o caso dominante — direito ao esquecimento de um contato.

Para os demais sujeitos, uma rotina de expurgo por sujeito é chamada junto da exclusão da
entidade. É trabalho a mais e é honesto: melhor que fingir integridade que não existe.

A purga por tenant sai de graça pelo `TenantMixin`.

### `crm/timeline.py` — o que muda e o que não

**Muda:** a metade persistida passa a vir de `facts` (`WHERE client_id = ?`) em vez de
`client_events`.

**Não muda:** a metade derivada. `quotes` e `charges` continuam sendo lidos na origem, com os
valores formatados em `_brl()` no momento da leitura. A Invariante 2 continua valendo — o dinheiro
nunca entrou no log e continua não entrando.

`client_events` é dropada na mesma migration 0069, com os dados migrados para `facts`
(`module='crm'`, `origin='emitted'`, mapeando `kind` para a taxonomia nova).

---

## V1 — O Briefing

### O briefing é por usuário, não por tenant

[`auth/models.py`](../../../apps/api/app/modules/auth/models.py) tem `allowed_modules` (lista JSON;
vazia = tudo, que é o caso do `owner`), e [`core/tenancy.py`](../../../apps/api/app/core/tenancy.py)
tem `require_module(module)`.

Um sub-usuário que só tem CRM **não pode** receber fato, ausência ou tendência de outro módulo —
nem na tela, nem no WhatsApp.

Três consequências de design:

**1. O filtro decide quais regras rodam, não quais resultados aparecem.** Para um usuário só de
CRM, a regra de tendência financeira **não é executada**. Não é calculada e escondida. Mais barato,
e elimina a classe inteira de bug em que um dado proibido vaza porque alguém esqueceu de filtrar na
saída. Nos fatos isso é `WHERE module = ANY(:permitidos)` na própria consulta.

**2. O filtro vem antes da narração, nunca depois.** Narrar tudo e esconder parágrafos na tela
significaria ter **enviado os dados proibidos à Claude** em nome de um usuário sem direito a eles —
e a prosa ficaria furada. A ordem é: filtrar → compor → narrar.

**3. `require_module` não serve aqui.** Ele é guard de rota, e o briefing é *uma* rota que
atravessa oito módulos. O que falta é um filtro no nível do **dado**, usando o mesmo vocabulário.
É peça nova: `briefing/permissions.py`.

### As três categorias

#### Fato

Leitura de `facts` na janela, filtrada por permissão.

#### Ausência — estado em aberto + relógio

Cinco famílias:

| Família | Fonte | Exemplo |
|---|---|---|
| Você prometeu e não entregou | `agenda`: evento com prazo passado, status pendente (o `cockpit` já calcula "críticos pendentes") | *"Você prometeu entregar isso terça"* |
| O cliente sumiu | `whatsapp_chats`: última mensagem foi nossa há N dias; último fato do contato há N dias | *"Faz 30 dias que João não recebe contato"* |
| Você sumiu | `whatsapp_chats`: última mensagem é `in` e passaram X horas | *"Você esqueceu de responder Carlos"* |
| O dinheiro tem data | `payables` vencendo, `receivables` vencidas | *"Este boleto vence amanhã"* |
| O topo secou | nenhum `pages.formulario.recebido` há N dias; nenhum orçamento enviado há N dias; ninguém entrou na primeira coluna do Kanban há N dias; cards parados via `clients.stage_entered_at` | *"Faz 6 dias que nenhuma landing page gera lead"* · *"3 propostas paradas há 12 dias"* |

⚠️ **A família "o cliente sumiu" / "você sumiu" só vale a partir da correção de autoria.** As
mensagens gravadas antes dela entraram todas como `in` e **não têm conserto retroativo** —
`fromMe` nunca foi persistido. As regras que leem direção precisam ignorar explicitamente o
histórico anterior a essa data, senão produzem ausências falsas.

**Cards parados usa `clients.stage_entered_at`** (migration 0068), hoje usada só para ordenar a
fila do Kanban. Mesma coluna, segundo propósito, nenhum campo novo.

**O que não é possível hoje, e fica registrado:** *"a página teve 40 visitas e nenhum formulário"*.
Não existe contagem de visita em `pages` — analytics é dívida aberta. Só sabemos dizer que não veio
lead; não sabemos dizer se veio gente e não converteu. É a diferença entre "ninguém bateu na porta"
e "bateram e a porta estava emperrada".

**Os limiares.** Toda regra tem um número (30 dias sem contato, 3 dias sem resposta, 10 dias
parado). O V1 entrega **defaults conservadores**, e o V2 (DNA da Empresa) os substitui — *"você
gosta de responder rápido?"* **é** o limiar de "você esqueceu de responder Carlos". Conservadores de
propósito: pela assimetria de credibilidade, uma regra que dispara demais custa mais caro que uma
que não dispara.

**A regra do silêncio.** Uma ausência é reportada quando **cruza** o limiar, não enquanto permanece
cruzada. Reincidência só por escalada (cruzou 3 dias → agora são 10) ou após período de silêncio.
Se o briefing repetir as mesmas quatro pendências todo dia, em duas semanas virou papel de parede —
e o dono lê por cima inclusive no dia em que aparece a quinta. É a Regra 7 do Epic 8 aplicada a
outro domínio: *"dentro da banda: verde e SILÊNCIO"*, porque *"uma tela que grita por R$ 3 destrói a
confiança no sinal"*.

#### Tendência

`financial_intelligence/engine.py` já produz `Signal` com 🟢🟡🔴 e explicação numérica. O briefing
**chama o motor e inclui os sinais** — não recalcula nada.

Duas restrições herdadas: o `engine.py` é **puro** (sem I/O, sem relógio, com gates AST provando) —
o briefing não empurra I/O para dentro dele; e todo sinal financeiro tem `module='financeiro'`,
então o filtro de permissão funciona sozinho.

Tendências não-financeiras (leads por semana contra a semana anterior, conversão do funil) precisam
de duas janelas para comparar. **Tendência é a categoria que começa mais fraca e melhora com o
tempo** — inverso da Ausência.

### O Compositor

```
Fatos ──────┐
Ausências ──┼─→ FILTRO → COMPOSIÇÃO → PAYLOAD → mask → Claude → unmask → BRIEFING
Tendências ─┘  (permissão) (colapsa,                      │
                            agrega,                       └─→ falhou? → TEMPLATE
                            prioriza,
                            corta)
```

**O compositor decide o QUE entra e em que ordem. A Claude decide apenas COMO dizer.**

Se a LLM escolhesse o que importa, isso seria Inferência — a categoria deferida ao V4. A
priorização é determinística: peso fixo por `kind` mais recência. Chata e previsível, que é o ponto.

**Colapso** — dois fatos, um acontecimento. Uma tabela pequena e explícita de pares
`(kind_a, kind_b) → frase`, cinco ou seis na Onda 1:

> `pages.formulario.recebido` + `crm.lead.criado`, mesmo contato, dentro de 60 segundos
> → *"Maria preencheu o formulário da página 'Consultoria Tributária' e entrou no funil"*

Os dois fatos **continuam gravados** — a atribuição de marketing e o nascimento do contato são
informações diferentes, e o V3 vai querer as duas. O colapso é da composição, não do log.

**Agregação** — acima de três fatos do mesmo `kind`, vira contagem:

> 40 × `funnels.contato.inscrito` → *"40 contatos entraram na automação 'Boas-vindas'"*

**Corte** — teto de linhas por seção; o excedente vira *"e mais N coisas antes disso"*.

**A janela** — desde o último briefing **lido** por aquele usuário, limitada a 7 dias. Quem não
abre há três dias merece os três dias; quem volta de férias não recebe 400 fatos.

**O dinheiro entra aqui.** O fato guardado não tem valor; o compositor faz o join com
`charges`/`bank_transactions` e renderiza `R$ 3.200,00` lido da origem no momento da leitura. Mesma
mecânica do `timeline.py`. Não há segunda versão da verdade — há uma leitura.

### O payload e a narração

```
BRIEFING de 06/08/2026 para Flávio · fuso America/Sao_Paulo
Janela: desde 05/08 07:12

ACONTECEU (7)
  [financeiro] Pagamento de [CLIENTE_1] recebido — R$ 3.200,00
  [comercial]  [CLIENTE_2] respondeu no WhatsApp
  [comercial]  Maria preencheu o formulário da página "Consultoria Tributária"
  [operação]   Automação "Pós-proposta" falhou 3 vezes

PENDENTE (3)
  [comercial]  [CLIENTE_3] esperando sua resposta há 2 dias
  [financeiro] Boleto de [FORNECEDOR_1] vence amanhã — R$ 890,00

NÚMEROS
  🟡 Margem do mês em 18% (era 24% no mês anterior)
```

`anonymizer.mask` no payload (CPF, e-mail, telefone, CNPJ viram placeholders; **nomes passam** — ver
Riscos), `ai.complete`, `anonymizer.unmask` na volta. Mesmo caminho do `ai_narrator`, sem exceção.

System prompt herda as regras absolutas dele — *usar somente os números, nomes e datas presentes;
nunca inventar; manter os placeholders intactos* — mais duas específicas: **nunca sugerir uma ação
que não esteja no payload** e **nunca reordenar por importância** (a ordem recebida é a certa).

A Claude não tem uma única conta para fazer. O compositor já fez todas.

### Fallback obrigatório

Sem `ANTHROPIC_API_KEY`, com erro da API ou timeout: o template renderiza **o mesmo payload** como
lista. O briefing continua íntegro, só deixa de ser conversado.

E, seguindo o `ai_narrator`: **quando a IA não rodou, não grava rastro de IA** — porque não houve IA.

### Geração e custo

**Job agendado, em tempo real, uma narração por (usuário, dia).** Reabrir a tela relê o briefing
gravado; não narra de novo — sem isso, quem aperta F5 dez vezes paga dez narrações.

**A Batch API fica fora do V1.** A economia é ~R$ 2 por usuário/mês e o preço é real: o batch não
tem garantia de latência (documentação promete "geralmente 1 hora", teto de 24h), o que obriga a
submeter na véspera com margem — e a tela, que o usuário abre a qualquer hora, não pode esperar
batch. Revisitar quando houver escala.

Custo estimado, a R$ 5,50/US$, com `claude-opus-4-8` (US$ 5/US$ 25 por Mtok) e um payload de
~2.500 tokens de entrada / ~500 de saída: **US$ 0,025 por briefing ≈ R$ 4,10 por usuário/mês.**
Prompt caching **não ajuda** aqui (TTL de 5 minutos ou 1 hora; um briefing por dia tem cache sempre
frio) — não contar com ele.

Modelo por tipo de tarefa é dívida aberta ([`config.py`](../../../apps/api/app/config.py) tem um
`anthropic_model` global). Narrar briefing não precisa do mesmo modelo que planeja execução
autônoma. Fica registrado como pré-requisito do V4, não do V1.

### O dia em que não aconteceu nada

Não é caso de borda; é tratado. Na tela, o briefing diz que está tranquilo e mostra o que está em
aberto. **No WhatsApp, não envia.** Um "bom dia, nada aconteceu" diário é a forma mais rápida de ser
silenciado — e um canal silenciado não entrega o dia em que importa.

---

## Superfícies

### A tela

**Porta de entrada uma vez por dia, não a cada login.** O briefing é artefato diário; se aparecesse
a cada acesso, quem entra cinco vezes veria cinco vezes e a porta de entrada viraria obstáculo.

Mecanismo: `read_at` no briefing. Primeiro acesso do dia → a Vima. Já lido → o Cockpit, com um
caminho discreto de volta ao briefing de hoje.

**Sem chrome.** Roda em `ProtectedBareLayout` — sem sidebar, sem topbar, como `/compartilhar` e
`/comprovante/:id`. É um momento de atenção inteira, não uma tela dentro do app.

**Desenhada para 360px primeiro.** Este repositório já pagou caro por isso: o `AppShell` não tinha
breakpoint responsivo e uma conta real foi marcada como paga sem o dono conseguir ver o checkbox
(PR #56). "Validação em ~360px" aparece duas vezes como dívida em aberto. O briefing é uma tela de
texto que um autônomo lê no celular.

### WhatsApp — roteamento pela configuração do tenant

O despachante já resolve o transporte a partir de `capabilities.for_profile`, derivado do
`whatsapp_provider`. **Tenant Evolution sai por Evolution, tenant Meta sai por Meta.** Nada a mudar
no roteamento.

O que muda é **quantos passos** a entrega tem, e por uma regra da Meta, não por escolha nossa:
**parâmetro de template da Cloud API não aceita quebra de linha**, e às 7h o dono está sempre fora
da janela de 24h.

Mas a janela abre quando **o usuário** escreve para o negócio. Então o dono recebe o briefing
completo no WhatsApp nos dois transportes — na Meta em dois tempos:

| Transporte | Entrega |
|---|---|
| **Evolution** | Um passo. O briefing inteiro, texto livre, às 7h. |
| **Meta** | Dois passos. **(1)** Template aprovado com **botão de resposta rápida**: *"Bom dia, Flávio. Seu briefing está pronto — 4 coisas aconteceram e 2 pedem atenção."* `[Ver briefing]`. **(2)** O toque no botão é mensagem dele → a janela de 24h abre → o sistema envia o briefing inteiro como texto livre. |

Ele nunca sai do WhatsApp em nenhum dos dois. Se não tocar no botão, não recebe — e a tela continua
com o briefing intacto.

Isso vira uma capacidade nova em `core/whatsapp/capabilities.py` — `briefing_needs_optin`
(Evolution `False`, Meta `True`) — **com o consumidor escrito no mesmo passo**. É a regra que este
repositório derivou depois de o `capabilities.py` passar meses com zero call sites enquanto a
docstring afirmava ter três: *capacidade nova nasce com o consumidor no mesmo passo, e a lista de
consumidores tem que ser verificável por grep.*

**Correlação da resposta.** O toque no botão chega pelo webhook do `whatsapp_inbox` carregando o
payload do botão; é por ele que o sistema distingue "pedido de briefing" de uma mensagem qualquer,
e localiza o briefing do dia daquele usuário para enviar.

⚠️ **Guarda obrigatória: a resposta vem do telefone do próprio dono.** Pelo caminho normal de
ingestão, `absorb_lead` criaria **um contato no CRM para o dono**. Mensagem cujo telefone bate com
o `phone` de um `User` ativo do tenant não vira lead nem abre conversa de cliente. Isto vale como
guarda geral, não só para o briefing: hoje qualquer dono que mande mensagem para o próprio número
entra no próprio funil.

**Pré-requisito operacional, com dependência externa:** o template com botão precisa ser submetido
e **aprovado pela Meta**. Não depende do repositório e leva tempo. Enquanto não houver aprovação, o
tenant Meta fica sem briefing por WhatsApp — a tela segue funcionando, e a UI diz por quê em vez de
deixar o botão quebrado.

Entrega pela fila de `Notification` + worker, nunca envio síncrono. O telefone passa por
`_addressable` na fronteira do despachante, que já normaliza para o formato BR.

### Configuração

**A preferência de briefing não pode morar em `/config`**, porque aquela rota exige o módulo
`settings` e a preferência é **do usuário**, não do tenant. Um sub-usuário sem `settings` precisa
poder ligar o próprio WhatsApp e escolher o próprio horário.

Campos no `User`: `briefing_whatsapp_enabled` (default **`False`**), `briefing_hour` (default
`07:00`). Sem `phone` preenchido, a opção não pode ser ligada.

**O opt-in é o registro de consentimento.** O usuário escolher "quero no WhatsApp, às 7h" é o ato
que documenta a intenção de externalizar dados de cliente para um canal externo — mais limpo que
qualquer aviso legal enterrado. Na Evolution a mensagem sai pela própria VPS do tenant; não passa
por terceiro além do WhatsApp.

### Reorganização de `/config`

[`ConfiguracoesPage.tsx`](../../../apps/web/src/features/config/ConfiguracoesPage.tsx) tem 370
linhas e empilha **sete assuntos** numa coluna: WhatsApp (o `WhatsappSection.tsx` sozinho tem 711
linhas), Celular, Integrações, Perfil da empresa, Brand Kit, Google Calendar e Funil de entrada
padrão.

Duas entregas:

**6a — Separar `/config` em áreas.** Abas ou sub-rotas, uma por assunto: *Empresa* (perfil + brand
kit), *Canais* (WhatsApp + celular), *Integrações* (Google + demais), *Vendas* (funil de entrada).

**6b — Área de preferências do usuário**, separada e sem exigir módulo: WhatsApp do briefing,
horário. É onde a Vima se configura.

**Escopo apertado de propósito: reorganizar e separar, não redesenhar.** Nenhum campo novo, nenhuma
regra nova, nenhuma mudança de comportamento — só cada coisa no seu lugar, para o diff ser revisável
e não virar um segundo projeto dentro deste.

---

## Gates

Este repositório trata invariante como código, não como intenção. Cinco obrigatórios:

1. **Permissão** — um sub-usuário só de CRM nunca recebe fato, ausência ou tendência de outro
   módulo. Teste explícito, não confiança.
2. **Fuso** — nada no caminho do briefing usa `datetime.now(UTC).date()`; usa `hoje_do_tenant(db)`.
   UTC cru é regressão declarada neste repositório.
3. **Invariante 2** — varredura provando que nenhum `title`/`body` de fato contém valor monetário.
   Sem o gate, a invariante vira docstring.
4. **Fallback** — sem `ANTHROPIC_API_KEY`, o briefing sai íntegro por template e **não grava rastro
   de IA**.
5. **Idempotência** — reabrir a tela relê o briefing gravado; não narra de novo.

---

## Riscos e dívidas conhecidas

**O anonimizador não mascara nomes.** [`core/anonymizer.py`](../../../apps/api/app/core/anonymizer.py)
tem cinco padrões — CNPJ, CPF, e-mail, telefone, cartão. Não há padrão de nome, apesar de a docstring
afirmar *"Substitui PII (nomes, CPF/CNPJ...)"*. Nomes de clientes já vão intactos para a Claude em
toda feature de IA existente. **O briefing não cria esse problema — ele o herda, e aumenta o volume.**
Divergência entre código e documentação que vale corrigir de um lado ou do outro; decisão fora do
escopo desta spec.

**Mensagens anteriores à correção de autoria são todas `in`.** As regras de ausência que leem direção
precisam ignorar explicitamente esse histórico.

**O dono vira lead do próprio funil.** Bug pré-existente que esta spec obriga a resolver: uma
mensagem recebida do telefone do próprio dono passa por `absorb_lead` e cria um contato no CRM.
Hoje isso só acontece se ele escrever para o próprio número; com o opt-in por botão da Meta, passa
a acontecer todo dia. A guarda (telefone que bate com `User.phone` ativo do tenant não vira lead)
vale para o sistema inteiro, não só para o briefing.

**Template da Meta é dependência externa.** O template com botão de resposta rápida precisa de
aprovação da Meta, fora do controle do repositório. Tenants Meta ficam sem briefing por WhatsApp
até lá; a tela não é afetada.

**Sem contagem de visitas em `pages`.** A ausência mais valiosa do topo do funil ("veio gente e não
converteu") não é computável.

**Tendências não-financeiras precisam de duas janelas.** A categoria começa fraca por construção.

**Modelo de IA único e global.** `config.anthropic_model` serve narração e, no futuro, execução
autônoma. Roteamento por tipo de tarefa é pré-requisito do V4.

**Custo do V4, registrado agora.** Um loop de agente (V4/V5) acumula 100–150 mil tokens de entrada
por tarefa — ~US$ 0,72 sem cache, ~US$ 0,30 com prompt caching (que ali **funciona**, porque os
turnos acontecem dentro da janela de 5 minutos). A dez tarefas por dia, isso é R$ 500–1.200 por
tenant/mês. Teto de custo por tenant é requisito do V4 no mesmo nível da autonomia progressiva.

**Validação em ~360px é manual.** Bloqueia release, não bloqueia merge — mesmo padrão das telas de
Contas & Saldos e Conversas.

---

## Fora de escopo

| Fora | Vai para |
|---|---|
| Inferência (*"há oportunidade de vender para três clientes semelhantes"*) | V4 |
| A Vima executando qualquer coisa (*"posso executar?"*) | V4 |
| Conversar — o briefing não responde perguntas | V3/V4 |
| DNA da Empresa (os limiares saem de defaults conservadores) | V2 |
| Os funcionários virtuais | V5 |
| `marketing` como emissor | quando publicar/agendar existir |
| Contagem de visitas em páginas | dívida de analytics |
| Backfill histórico | decisão registrada acima |
| Batch API | quando houver escala |
| Redesenho visual de `/config` | esta spec só separa |

---

## Como saber se deu certo

- O dono lê o briefing e **não precisa abrir mais nada** para saber o que aconteceu.
- **Nenhuma linha é falsa.** A barra é zero, não "poucas".
- Ele não desliga o WhatsApp em 30 dias. Este é o teste de verdade.
