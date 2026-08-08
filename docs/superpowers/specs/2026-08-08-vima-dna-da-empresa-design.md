# Vima — DNA da Empresa

**Data:** 2026-08-08
**Status:** Aprovado (design)
**Escopo:** V2 da visão Vima
**Módulos afetados:** `dna` (novo), `vima` (consumo dos limiares), `auth`/`settings` (permissão), `apps/web` (núcleo na entrada, ganchos, nova aba em `/config`)
**Depende de:** V0 (Registro de Fatos) e V1 (Briefing), ambos em `main` — PRs #85, #87, #90

---

## Problema

O V1 entregou um briefing que fala com todo mundo do mesmo jeito.

As cinco famílias de Ausência têm um número cada — 24 horas sem resposta, 30 dias sem falar com
o cliente, 10 dias parado na etapa — e esses números são
[defaults conservadores escolhidos por nós](../specs/2026-08-06-vima-registro-de-fatos-e-briefing-design.md),
não pelo dono. A docstring de [`absences.py`](../../../apps/api/app/modules/vima/absences.py)
já registra a dívida em voz alta:

> Os limiares são injetáveis porque o V2 (DNA da Empresa) vai substituí-los: "você gosta de
> responder rápido?" é literalmente o limiar de `contato.esperando_resposta`.

Um advogado que responde em dois dias e um social media que responde em duas horas recebem hoje
o mesmo aviso, na mesma hora. Para um, o briefing grita cedo demais; para o outro, avisa quando
já era tarde. **Pela assimetria de credibilidade que o V1 estabeleceu — um aviso errado custa
mais caro que um aviso ausente — o default conservador é a decisão certa enquanto não se sabe.
O V2 é o momento de passar a saber.**

Há um segundo problema, maior e mais adiante. O V4 (Motor de Contexto + Autonomia Progressiva)
depende de V0 **e V2**, e a razão é que um agente que age em nome do dono precisa saber o que o
dono **nunca faz**. Hoje esse conhecimento não existe em lugar nenhum do sistema. Descobri-lo
por tentativa e erro significa errar na frente do cliente.

---

## Objetivo

Um retrato do negócio, **declarado pelo dono**, que calibra o comportamento da Vima hoje e serve
de contexto aos funcionários virtuais amanhã — capturado sem nunca virar um portão de quinze
minutos na porta de entrada do produto.

### A escolha estruturante: duas classes, declaradas e verificadas

Toda pergunta pertence a uma de duas classes, e a classe não é um rótulo de organização — é um
contrato mecânico:

| Classe | Tem consumidor **hoje**? | Efeito de responder |
|---|---|---|
| **Calibração** | Sim, obrigatoriamente | Muda o comportamento do briefing no dia seguinte |
| **Retrato** | Não, por definição | É guardado. Nada muda até o V4 |

O contrato existe porque a alternativa é conhecida e ruim: sem ele, em seis meses alguém marca
uma pergunta bonita como Calibração, o dono a responde acreditando ter mudado o comportamento
do produto, e não mudou nada. **Um produto que finge ouvir é pior que um produto que não
pergunta.** As duas guardas que sustentam o contrato estão em [Guardas do catálogo](#guardas-do-catálogo).

Uma consequência desconfortável e aceita: **Calibração são apenas 6 perguntas**, porque só
existem seis consumidores. Qualquer número maior seria invenção — e o Artigo IV da Constitution
proíbe.

---

## O modelo de dados

### O catálogo é código

As perguntas vivem em `apps/api/app/modules/dna/catalog.py` como dados imutáveis em Python.
É o mesmo padrão já estabelecido no repositório por `LIMIARES_PADRAO` (`vima/absences.py`) e
`MODELO_POR_TAREFA` (`core/ai.py`): catálogo em código, com gate de teste.

```python
@dataclass(frozen=True)
class Opcao:
    rotulo: str            # o que o dono lê
    valor: int | str | None  # o que o sistema guarda e consome

@dataclass(frozen=True)
class Pergunta:
    key: str                          # "ritmo.resposta_horas"
    classe: str                       # CALIBRACAO | RETRATO
    eixo: str                         # oferta | cliente | ritmo | dinheiro | limites
    texto: str
    formato: str                      # escolha | escolha_multipla | texto
    opcoes: tuple[Opcao, ...] = ()
    consome: str | None = None        # chave de LIMIARES_PADRAO
    gancho: str | None = None         # onde a pergunta aparece sozinha
```

**Pergunta nova exige deploy, e isso é correto.** Pergunta nova de Calibração vem sempre junto
do consumidor dela, que é código de qualquer forma. Pergunta nova de Retrato não tem urgência
que justifique um editor de catálogo em banco — e um catálogo editável por tenant faria o
dossiê do V4 ter formato diferente em cada empresa, que é exatamente o que ele não pode ter.

### Guardas do catálogo

Duas verificações rodam no **import do módulo** — falham na subida do processo, não em
produção. É o mesmo espírito das duas invariantes de `facts.record`, que estouram a transação
de propósito:

1. **`CALIBRACAO` exige `consome`; `RETRATO` proíbe.** É a guarda que dá sentido à classe.
2. **`consome` precisa apontar para uma chave existente em `LIMIARES_PADRAO`.** Sem ela, um
   typo em `"card_parado_dais"` produz um silêncio perfeito: a resposta grava, o resolver monta
   o dicionário, `coletar` faz `{**LIMIARES_PADRAO, **override}`, e a chave estranha é
   simplesmente ignorada. O dono responderia e nada aconteceria — para sempre, sem erro nenhum,
   sem teste quebrando.

Uma terceira, de higiene: **`key` única** e **`key` começa com o `eixo`**, pela mesma razão que
`facts.record` exige que `kind` comece com `module` — trinta perguntas produzindo
`resposta_horas` e `ritmo.resposta_horas` convivendo é o custo de não verificar.

### A tabela `dna_answers`

| Coluna | Tipo | Nota |
|---|---|---|
| `id` | String(36) | |
| `tenant_id` | String(36) | `TenantMixin`, RLS `ENABLE` + `FORCE`, policy `tenant_isolation` |
| `question_key` | String(64) | |
| `value` | JSON, nulo | **Nulo = pulada.** Não é o mesmo que linha ausente |
| `answered_at` | timestamptz | |
| `answered_by` | String(36), nulo | id do usuário |
| `source` | String(16) | `nucleo` \| `gancho` \| `config` |

Único por `(tenant_id, question_key)`.

**É upsert, não append — o oposto de `facts`, e de propósito.** Fato é história; DNA é estado
atual. Guardar versões faria toda leitura ter que decidir qual resposta vale, e o histórico de
quem mudou o quê já é trabalho de [`core/audit.py`](../../../apps/api/app/core/audit.py), que
existe e é o lugar certo.

**`value` nulo distingue "pulei" de "nunca me perguntaram"** sem tabela nova. É o que sustenta a
quarentena de 7 dias descrita em [Cadência](#cadência-as-duas-regras-de-silêncio).

**A escrita valida contra o catálogo.** Chave desconhecida → 422. Valor fora de `opcoes` para
formato `escolha` → 422. Texto acima de 2.000 caracteres → 422. Sem isso o `value` JSON vira
depósito de qualquer coisa e o resolver quebra na leitura, longe de quem escreveu.

### O V2 não chama IA

Em nenhum ponto. Nem para redigir pergunta, nem para interpretar o texto livre dos campos
abertos — que são guardados crus até o V4. Isso mantém `core/ai.py`, o ledger `ai_usage` e o
anonimizador inteiramente fora do escopo, e é o que torna o V2 barato de operar: custo marginal
zero por tenant.

---

## O catálogo — as 45 perguntas

Formato `escolha` salva o `valor` da opção escolhida; `escolha_multipla` salva uma lista;
`texto` salva string.

### Calibração (6)

Cada uma existe porque há um número esperando por ela. O valor em **negrito** é o default de
hoje, preservado quando ninguém responde.

| `key` | Texto | Opções (`rotulo` → `valor`) | `consome` |
|---|---|---|---|
| `ritmo.resposta_horas` | "Um cliente te escreveu e ficou sem resposta. Em quanto tempo eu te aviso?" | Em 4 horas → 4 · No mesmo dia → 12 · **No dia seguinte → 24** · Depois de 2 dias → 48 | `sem_resposta_nossa_horas` |
| `cliente.esfria_dias` | "Quantos dias sem falar com um cliente já significa que ele esfriou?" | 15 · **30** · 60 · 90 | `contato_sumido_dias` |
| `ritmo.card_parado_dias` | "Uma negociação parada na mesma etapa há quanto tempo te incomoda?" | 5 · **10** · 20 · 30 | `card_parado_dias` |
| `cliente.topo_seco_dias` | "Quantos dias sem nenhum cliente novo é anormal no seu negócio?" | 3 · **5** · 15 · Não quero esse aviso → `null` | `topo_sem_lead_dias` |
| `ritmo.prazo_antecedencia_dias` | "Com quanta antecedência você quer saber de um **prazo**?" | No próprio dia → 0 · **1 dia antes → 1** · 3 dias antes → 3 · 1 semana antes → 7 | `prazo_vencendo_dias` |
| `dinheiro.antecedencia_dias` | "E de uma **conta a pagar**?" | No próprio dia → 0 · **1 dia antes → 1** · 3 dias antes → 3 · 1 semana antes → 7 | `dinheiro_com_data_dias` (novo) |

#### `dinheiro_com_data_dias` é chave nova, e por quê

Hoje `prazo_vencendo_dias` governa **duas regras diferentes**: prazo da agenda
(`absences.py:132`) e conta a pagar chegando ao vencimento (`absences.py:166`). São
antecedências distintas na cabeça de qualquer dono — prazo de entrega se quer saber em cima,
boleto se quer saber com folga para ter o dinheiro. Perguntar em voz alta é o momento em que a
fusão fica insustentável.

A separação nasce com valor `1`, idêntico ao de hoje: **é refactor puro no dia do merge**,
comportamento inalterado enquanto ninguém responde.

#### A pergunta fala só de conta a PAGAR, e isso não é descuido

`_dinheiro_com_data` trata duas direções com regras diferentes, apesar da docstring dizer *"duas
direções, uma regra"*: contas a pagar usam `due_date <= hoje + limiar` (têm antecedência),
cobranças a receber usam `due_date < hoje` (**só aparecem depois de vencidas, sem limiar
nenhum**). Um recebimento que vence amanhã não é dito por ninguém.

A assimetria é do V1 e **fica registrada como dívida, não é consertada aqui** — dar antecedência
a cobrança é decisão de produto sobre o que o briefing anuncia, não sobre como ele é calibrado.
Perguntar "e de uma conta a receber?" antes de existir a regra criaria uma resposta gravada que
não consome nada: exatamente o que as duas classes existem para impedir.

#### "Não quero esse aviso" existe em exatamente uma pergunta

Só `cliente.topo_seco_dias` oferece desligamento, e a razão é estrutural. As outras cinco regras
disparam sobre **coisa que existe** — sem cards, não há card parado; sem cobrança, não há
cobrança vencendo —, então elas se calam sozinhas em quem não usa aquilo. Topo seco dispara
sobre o **vazio**: um negócio sem entrada inbound é cutucado todo dia, para sempre. É a dívida
já registrada no `CLAUDE.md` (*"a única Ausência que lê o log, então enquanto o registro for
novo ela dispara por falta de histórico e não por falta de lead"*), e o desligamento explícito
é o conserto honesto dela.

**Mecanicamente, `null` significa regra não executada** — não "regra executada com limiar
infinito". É a mesma forma do filtro de permissão do V1, que não roda a regra em vez de calcular
e esconder o resultado, eliminando a classe inteira de bug em que o dado proibido vaza por
esquecimento no filtro de saída.

### Retrato (39)

A regra de pertencimento é dura, e ela é o que impede o catálogo de inchar:

> **Entra se um funcionário humano recém-contratado precisaria saber no primeiro dia.**

O que não passa nesse teste não entra. "Qual seu CNPJ" não entra — é dado cadastral e já mora em
`tenant_profiles`. "Qual sua cor favorita" não entra. "O que você nunca faz" entra.

#### Eixo Oferta (9)

| `key` | Texto | Formato / Opções |
|---|---|---|
| `oferta.o_que_vende` | "O que você vende?" | escolha: Serviço recorrente · Serviço por projeto · Produto físico · Produto digital · Um pouco de cada |
| `oferta.em_uma_frase` | "Se um cliente perguntar o que você faz, o que você responde?" | texto |
| `oferta.ticket_tipico` | "Quanto costuma custar um trabalho seu?" | escolha: Até R$ 500 · R$ 500 a 2 mil · R$ 2 mil a 10 mil · R$ 10 mil a 50 mil · Acima de R$ 50 mil |
| `oferta.prazo_entrega` | "Do 'sim' do cliente até a entrega, quanto tempo costuma passar?" | escolha: No mesmo dia · Até uma semana · De 2 a 4 semanas · Mais de um mês · É contínuo, não tem fim |
| `oferta.como_cobra` | "Como você costuma cobrar?" | escolha: Tudo antes · Tudo depois · Entrada e saldo · Parcelado · Mensalidade |
| `oferta.capacidade_mes` | "Quantos clientes novos você consegue atender por mês, no máximo?" | escolha: 1 ou 2 · 3 a 5 · 6 a 15 · Mais de 15 · Não tenho teto |
| `oferta.proposta_formal` | "Você manda proposta ou orçamento escrito antes de fechar?" | escolha: Sempre · Na maioria das vezes · Raramente · Nunca |
| `oferta.diferencial` | "Por que um cliente escolhe você e não o concorrente?" | texto |
| `oferta.aberta` | "Algo mais que a Vima precisa saber sobre o que você vende?" | texto |

#### Eixo Cliente (8)

| `key` | Texto | Formato / Opções |
|---|---|---|
| `cliente.quem_e` | "Quem compra de você?" | escolha: Pessoa física · Pequenas empresas · Empresas médias e grandes · Órgãos públicos · Um pouco de cada |
| `cliente.como_chega` | "Como o cliente chega até você?" | escolha_multipla: Indicação · Redes sociais · Busca no Google · Anúncio pago · Prospecção ativa · Passagem ou loja física |
| `cliente.decisao_tempo` | "Do primeiro contato até o cliente decidir, quanto tempo costuma levar?" | escolha: No mesmo dia · Poucos dias · De 1 a 4 semanas · Mais de um mês |
| `cliente.recompra` | "O mesmo cliente costuma voltar?" | escolha: É recorrente por contrato · Volta com frequência · Volta às vezes · É compra única |
| `cliente.objecao` | "O que mais faz um cliente dizer não?" | escolha: Preço · Prazo · Falta de confiança · Não era o que ele procurava · Ele some sem dizer nada |
| `cliente.canal_preferido` | "Por onde o cliente prefere falar com você?" | escolha: WhatsApp · Telefone · E-mail · Presencial · Instagram e afins |
| `cliente.sinal_de_que_fecha` | "O que te faz saber que um cliente vai fechar?" | texto |
| `cliente.aberta` | "Algo mais que a Vima precisa saber sobre seus clientes?" | texto |

#### Eixo Ritmo (7)

| `key` | Texto | Formato / Opções |
|---|---|---|
| `ritmo.dias_de_trabalho` | "Em que dias você trabalha?" | escolha_multipla: Segunda · Terça · Quarta · Quinta · Sexta · Sábado · Domingo |
| `ritmo.janela_do_dia` | "Que horas você costuma trabalhar?" | escolha: De manhã · Horário comercial · Tarde e noite · De madrugada · Varia muito |
| `ritmo.pico_do_mes` | "Tem época do mês mais cheia?" | escolha: Começo · Meio · Fim · Não tem padrão |
| `ritmo.sazonalidade` | "E do ano? Tem mês que enche e mês que esvazia?" | texto |
| `ritmo.o_que_trava` | "O que mais trava o seu dia?" | escolha: Atender cliente · Fazer o trabalho em si · Cobrar · Burocracia · Vender |
| `ritmo.sozinho` | "Você trabalha sozinho?" | escolha: Sozinho · Com ajuda pontual de freelas · Tenho 1 ou 2 pessoas · Tenho equipe |
| `ritmo.aberta` | "Algo mais que a Vima precisa saber sobre o seu ritmo?" | texto |

#### Eixo Dinheiro (8)

| `key` | Texto | Formato / Opções |
|---|---|---|
| `dinheiro.atraso_reacao` | "Cliente atrasou o pagamento. O que você faz?" | escolha: Cobro no dia seguinte · Espero alguns dias · Espero ele falar · Evito cobrar |
| `dinheiro.tolerancia_dias` | "Quantos dias de atraso você tolera antes de agir?" | escolha: 1 · 3 · 7 · 15 · 30 |
| `dinheiro.reserva` | "Você tem reserva para quantos meses parados?" | escolha: Nenhuma · Menos de um mês · De 1 a 3 meses · De 3 a 6 meses · Mais de 6 meses |
| `dinheiro.pro_labore` | "Você tira um valor fixo por mês para você?" | escolha: Sim, fixo · Sim, variável · Não separo |
| `dinheiro.sinal_de_aperto` | "O que te diz que o mês vai ser apertado?" | texto |
| `dinheiro.formas_recebimento` | "Como você recebe?" | escolha_multipla: Pix · Boleto · Cartão · Dinheiro · Transferência |
| `dinheiro.emite_nota` | "Você emite nota fiscal?" | escolha: Sempre · Quando o cliente pede · Não emito |
| `dinheiro.aberta` | "Algo mais que a Vima precisa saber sobre o seu dinheiro?" | texto |

> **`dinheiro.tolerancia_dias` parece Calibração e não é.** Tem número e tem opções fechadas,
> mas **não existe hoje regra de Ausência sobre tolerância a atraso** — `dinheiro com data` olha
> vencimento, não carência. Sem consumidor, é Retrato: a classe é definida pelo contrato, nunca
> pelo formato. Se algum dia nascer a regra, esta pergunta migra de classe junto com ela, e a
> guarda do catálogo cobra que o consumidor exista antes.

#### Eixo Limites (7)

**É o eixo mais importante e o mais fácil de esquecer.** É o único que o V4 lê para decidir o
que **não** fazer sozinho. Uma autonomia progressiva sem esta lista é um agente que descobre os
limites errando na frente do cliente.

| `key` | Texto | Formato / Opções |
|---|---|---|
| `limites.nunca_faco` | "O que você nunca faz, mesmo que o cliente peça?" | texto |
| `limites.exige_voce` | "O que só pode sair com você olhando antes?" | escolha_multipla: Proposta e preço · Mensagem para cliente · Cobrança · Contrato · Publicação · Nada disso |
| `limites.tom` | "Como você fala com cliente?" | escolha: Formal · Cordial e direto · Informal e próximo · Bem-humorado |
| `limites.desconto` | "Você dá desconto?" | escolha: Nunca · Só em caso especial · Negocio sempre · Tenho tabela fixa |
| `limites.recusa_cliente` | "Que tipo de cliente você recusa?" | texto |
| `limites.horario_contato` | "Pode falar com cliente fora do seu horário?" | escolha: Pode sempre · Só urgência · Nunca |
| `limites.aberta` | "Algo mais que a Vima precisa saber sobre os seus limites?" | texto |

**Total: 6 + 9 + 8 + 7 + 8 + 7 = 45.**

---

## As superfícies

### O núcleo não é de Calibração

Esta é a inversão central do design, e a razão é forte: *"em quanto tempo eu te aviso que
ninguém respondeu o Carlos?"* é impossível de responder bem antes de ter visto um briefing.
Perguntada no primeiro acesso, a resposta é um chute — que depois vira comportamento errado com
aparência de configuração deliberada, e o dono não tem como saber que foi ele quem pediu aquilo.

**Núcleo — 6 perguntas, no primeiro acesso, gancho `nucleo`:**

`oferta.o_que_vende` · `oferta.em_uma_frase` · `oferta.como_cobra` · `oferta.ticket_tipico` ·
`cliente.como_chega` · `limites.nunca_faco`

São respondíveis em cerca de noventa segundos por quem acabou de entrar e nunca viu o produto, e
são as que fazem o sistema parecer dele. **São puláveis** — "responder depois" é um botão, não
um beco. Roda em `EntradaDoDia`, que já é o lugar onde a porta do dia é decidida, como um
terceiro estado antes de `vima` e `cockpit`.

### Calibração vai toda por gancho, colada à ausência que a motivou

Na primeira vez que o briefing diz *"o Carlos está sem resposta há 24 horas"*, logo abaixo
daquela linha aparece *"esse é o tempo certo para você?"* com as quatro opções. A pergunta chega
no único instante em que ela é óbvia, e o efeito aparece no briefing do dia seguinte.

O gancho é `briefing.ausencia.<kind>`, com os `kind` que já existem em `absences.py`:

| Pergunta | Gancho |
|---|---|
| `ritmo.resposta_horas` | `briefing.ausencia.comercial.contato.esperando_resposta` |
| `cliente.esfria_dias` | `briefing.ausencia.comercial.contato.sumido` |
| `ritmo.card_parado_dias` | `briefing.ausencia.comercial.card.parado` |
| `cliente.topo_seco_dias` | `briefing.ausencia.comercial.topo.sem_lead` |
| `ritmo.prazo_antecedencia_dias` | `briefing.ausencia.agenda.prazo.estourado` |
| `dinheiro.antecedencia_dias` | `briefing.ausencia.financeiro.conta.vencendo` |

`financeiro.cobranca.vencida` não recebe pergunta porque **não tem limiar** — ela dispara sobre
o que já venceu, sem antecedência (ver a dívida registrada acima).

### Retrato restante

Ganchos de contexto declarados no catálogo, disparados depois da ação correspondente:
`crm.cliente.criado`, `receivables.cobranca.criada`, `quotes.orcamento.criado`,
`payables.conta.criada`, `agenda.evento.criado`.

E a aba nova **"A sua empresa"** em `/config` — que acabou de virar abas no PR #86 e tem o lugar
pronto — com os cinco eixos, o que já foi respondido e o que falta, tudo editável a qualquer
momento. É a saída para quem quiser sentar e responder as 45 de uma vez, sem que isso tenha
sido imposto a ninguém.

### Cadência: as duas regras de silêncio

1. **No máximo uma pergunta por gancho por dia, no produto inteiro.** Não uma por tela: uma. Um
   produto que interroga em três telas diferentes na mesma sessão é ignorado na quarta. É a
   Regra do Silêncio do V1 aplicada a perguntar em vez de a avisar.

   **O núcleo é a exceção declarada**, e as seis perguntas dele não contam para esse limite: ele
   é uma sequência anunciada, com fim visível, que a pessoa entrou sabendo que ia atravessar (e
   podendo pular). Interrupção não anunciada e sequência anunciada são coisas diferentes — o que
   cansa é a primeira. Consequência mecânica: no dia do primeiro acesso o gancho fica calado,
   porque o núcleo já usou a cota.
2. **Pergunta pulada não reaparece por 7 dias.** Nunca some — continua no `/config` —, mas para
   de ser empurrada. Sem isso, um "depois" acidental vira interrogatório; com quarentena
   infinita, um toque errado perde a pergunta para sempre.

**As duas são derivação de *que dia é hoje*, então saem de `hoje_do_tenant(db)`.** O módulo `dna`
entra na varredura AST de `tests/test_fuso_do_tenant.py`, junto com `app/modules/vima/`. Sem
isso, o dono no Acre é interrogado duas vezes no mesmo dia — e a regressão passaria despercebida
por meses, porque em São Paulo funciona.

**A escolha entre várias elegíveis é determinística:** a Calibração colada ao gancho vence;
empatando, a primeira não respondida na ordem do catálogo. Nada de sorteio — teste que depende
de aleatoriedade não prova nada.

---

## Consumo

### O resolver é a única porta

`apps/api/app/modules/dna/resolver.py` expõe duas funções e nada mais:

- `limiares(db) -> dict[str, int | None]` — montado **só** das respostas de Calibração, pronto
  para entrar em `absences.coletar(..., limiares=...)`. `vima/service.py` passa a chamá-lo; hoje
  ele não passa nada e o default vale para todos.
- `retrato(db) -> dict[str, Any]` — as respostas de Retrato, **sem consumidor no V2**. Existe
  para que o V4 encontre a porta pronta.

**Nenhum outro módulo lê `dna_answers` direto.** É o que mantém a classe Retrato honestamente
sem consumidor, em vez de ela vazar por um `select` esperto em algum lugar — que é como um
contrato de arquitetura morre na prática.

### Mudar um limiar limpa o registro de silêncio

Se o dono aperta "card parado" de 10 para 5 dias e o briefing continua calado porque já disse
aquilo ontem, a configuração parece quebrada — e a próxima que ele mexer, ele não acredita.

`_ja_reportadas` (em `vima/service.py`) devolve `{}` quando existe resposta de **Calibração**
gravada depois da `reference_date` do briefing anterior. Isso limpa o silêncio de **todas** as
regras, não só da que mudou. É grosso de propósito, na mesma linha do fator 2 da escalada, que o
próprio código chama de *"arbitrário e deliberadamente grosso"*: recalibrar é raro, e
discriminar por regra exigiria um mapa `kind`→limiar que existiria só para essa finalidade.

### O briefing de hoje não é regerado

Ele é idempotente por `(tenant, usuário, dia)` e já foi narrado e possivelmente enviado por
WhatsApp. A resposta vale do próximo em diante, e **a tela diz isso** ("vale a partir de
amanhã"). Dizer é mais barato que quebrar a idempotência — que é o que faz o F5 reler em vez de
pagar narração nova, e o que faz o dono reencontrar de tarde as mesmas palavras da manhã.

---

## Permissão

O DNA é **da empresa**, não da pessoa. Núcleo e ganchos só aparecem para `owner` ou para quem
tem o módulo `settings` — a mesma decisão de `require_module` (owner vê tudo; lista vazia vê
tudo). Um sub-usuário só de CRM vê o briefing normalmente, sem a pergunta embaixo da ausência.

É deliberadamente o **oposto** das preferências de briefing do V1, que foram para `users`
justamente por serem pessoais (telefone e horário diferem entre dois usuários do mesmo tenant).
Aqui, um sub-usuário recalibrando o negócio inteiro seria surpresa ruim para o dono.

**Responder não emite fato.** O feed do briefing é sobre o negócio, não sobre a configuração do
produto — e a trilha de quem mudou o quê é trabalho de `core/audit.py`.

---

## Gates

| Gate | O que quebra sem ele |
|---|---|
| `CALIBRACAO` tem `consome`, `RETRATO` não tem | A classe vira rótulo decorativo e o produto finge ouvir |
| `consome` aponta para chave real de `LIMIARES_PADRAO` | Typo produz silêncio perfeito: grava, não consome, não erra |
| `key` única e prefixada pelo `eixo` | Vocabulário divergente em seis meses (lição de `facts.kind`) |
| Toda pergunta de `escolha` tem ao menos 2 `opcoes` | Pergunta impossível de responder chega ao dono |
| Varredura AST de `app/modules/dna/` em `test_fuso_do_tenant.py` | Cadência em UTC cru: dois interrogatórios no mesmo dia fora de SP |
| Resposta fora de `opcoes` → 422 | `value` JSON vira depósito e o resolver quebra na leitura |
| `limiares()` devolve só Calibração | Retrato ganha consumidor por acidente e o contrato morre |
| Default preservado quando não há resposta | Tenant que não respondeu muda de comportamento sem ter pedido |

---

## Ondas

| Onda | Entregável | Dá para parar aqui? |
|---|---|---|
| **1** | `dna/catalog.py` com as 45 e as guardas · migration `dna_answers` (RLS `FORCE`) · rotas `GET /dna/pendente`, `PUT /dna/{key}`, `POST /dna/{key}/pular` · validação | Sim — nada visível mudou |
| **2** | `dna/resolver.py` ligado em `absences` via `vima/service.py` · `dinheiro_com_data_dias` separado de `prazo_vencendo_dias` · limpeza do silêncio | Sim — **o DNA já muda o briefing**, respondendo pela API |
| **3** | Núcleo de 6 no primeiro acesso, em `EntradaDoDia`, pulável, 360px | Sim |
| **4** | Ganchos: Calibração colada à ausência no briefing + ganchos de contexto | Sim |
| **5** | Aba "A sua empresa" em `/config`, os cinco eixos, tudo editável | Fim do V2 |

Cada onda termina com software funcionando, como as cinco do V1.

---

## Riscos e dívidas conhecidas

**As 45 perguntas são um chute educado.** Nenhuma foi validada com um dono real de empresa de
uma pessoa. A estrutura (duas classes, cinco eixos, catálogo em código) aguenta troca de
pergunta sem migration — trocar texto e opções é editar um arquivo Python —, mas **trocar o
`valor` de uma opção depois que alguém respondeu deixa a resposta gravada apontando para um
valor que não existe mais**. O resolver precisa ignorar valor desconhecido e cair no default,
com log, em vez de estourar.

**Calibração são 6 e a expectativa de "50 perguntas" era outra.** Quem ler o roadmap e depois o
produto vai achar que faltou. Não faltou: 39 das 45 são Retrato e só rendem no V4. O risco real
é o dono responder 45 perguntas e sentir que 39 não fizeram nada — **a tela precisa dizer, em
cada pergunta de Retrato, que ela está sendo guardada para depois.** Prometer efeito imediato
seria repetir exatamente o erro que as duas classes existem para impedir.

**O núcleo tem custo de ativação real.** Seis perguntas antes do primeiro uso, mesmo puláveis,
mesmo em noventa segundos, são seis telas entre a pessoa e o produto. Não há medição de
ativação no e1p hoje para saber se doeu — e essa é a dívida: o V2 não vem com forma de descobrir
se o núcleo ajudou ou atrapalhou.

**A quarentena de 7 dias e o "uma por dia" são números sem evidência**, escolhidos pelo mesmo
critério conservador dos limiares do V1: errar para menos incomoda menos que errar para mais.

**O V4 vai querer o dossiê em formato de prompt, e o V2 entrega dicionário.** A tradução — que
frases descrevem uma empresa a partir de 39 respostas — é trabalho do V4 e não foi feita aqui.
O risco é o V4 descobrir que precisava de perguntas diferentes.

**Cobrança a receber continua sem antecedência.** Descoberto ao escrever este spec e não
consertado aqui: `_dinheiro_com_data` dá aviso prévio a conta a pagar e nenhum a cobrança, que
só aparece depois de vencida. O dono é avisado do que deve e surpreendido pelo que não recebeu.
É dívida do V1, e a pergunta correspondente do DNA só pode existir depois da regra.

**Sem histórico de respostas.** Se o dono mudar "esfria em 30 dias" para 60, não há registro de
que um dia foi 30 além do `core/audit.py`. Uma análise futura do tipo "donos apertam ou afrouxam
com o tempo?" não é respondível.

---

## Fora de escopo

| Fora | Vai para |
|---|---|
| Observar comportamento para sugerir resposta (*"notamos que você responde em ~4h"*) | V2.5 |
| Qualquer uso de IA — redigir, interpretar texto livre, inferir | V4 |
| O dossiê ser efetivamente **consumido** (no V2 é guardado e mais nada) | V4 |
| DNA por usuário (é do tenant, sempre) | — |
| Histórico de versões das respostas | — |
| Editor de catálogo por tenant | — |
| Medição de ativação do núcleo | dívida de analytics |
