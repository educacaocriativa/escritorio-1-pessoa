# Vima — a cobrança a receber ganha antecedência, e a regra do silêncio passa a valer

**Data:** 2026-08-09
**Status:** Aprovado (design)
**Escopo:** dívida do V1 exposta pelo V2, e o defeito da regra do silêncio que ela revelou
**Módulos afetados:** `vima` (`absences`, `composer`, `service`), `dna` (`catalog`)
**Depende de:** V0, V1 e V2, todos em `main` — PRs #85, #87, #90, #101

---

## Problema

São dois, e o segundo só apareceu porque o primeiro foi investigado.

### O dono é avisado do que deve e surpreendido pelo que não recebeu

`_dinheiro_com_data` guarda as duas direções do dinheiro na mesma função e as trata por regras
opostas. Conta a pagar tem antecedência (`due_date <= hoje + limiar`). Cobrança a receber só
aparece **depois** de vencida (`due_date < hoje`, sem limiar nenhum).

A docstring da função já registra a dívida em voz alta:

> Um recebimento que vence amanhã não é dito por ninguém — dívida registrada no spec do V2, e o
> motivo de a pergunta do DNA falar só de conta a pagar.

Numa empresa de uma pessoa, essa é a assimetria errada. O dinheiro que entra é o único dos dois
em que um toque **antes** do vencimento muda o resultado: lembrar o cliente na véspera evita o
atraso, enquanto lembrar o próprio dono de uma conta a pagar só antecipa um pagamento que ele já
faria. O produto dá folga justamente para a direção que menos precisa dela.

### A regra do silêncio não se sustenta em ausência com data

Investigar o primeiro problema mostrou que a antecedência não pode ser simplesmente ligada para a
cobrança, porque o mecanismo que a receberia está quebrado — e já está quebrado hoje, para a conta
a pagar.

A regra do silêncio do V1 promete: *reportada ao CRUZAR o limiar, não enquanto permanece cruzada;
volta quando os dias dobram.* Ela é implementada por `_ja_dita`, que compara `dias < anterior * 2`
contra um mapa `{kind}:{subject_id} → dias` lido do briefing anterior. Dois defeitos:

**1. `dias` negativo inverte a escalada.** Com antecedência, `dias = (hoje - due_date).days` é
negativo antes do vencimento. Uma conta que vence amanhã entra com `dias = -1`, e o limiar de
retorno vira `-2` — um número que `dias` nunca mais alcança, porque só cresce. O fator 2 foi
desenhado para intensidade que sobe a partir de 1; sobre negativo ele aponta para o lado errado, e
a ausência deixa de ser calada para sempre.

**2. Ausência calada some do mapa e volta no dia seguinte.** `Payload.ausencias_ditas` é montado
só a partir das linhas `mantidas`, e `service._ja_reportadas` lê **apenas o briefing anterior**.
Uma ausência calada não entra no mapa daquele dia — então no dia seguinte não há valor anterior, e
ela é dita de novo. O silêncio dura exatamente um dia. Card parado sai no dia 10, cala no 11, volta
no 12, cala no 13.

Os testes de `test_vima_absences.py` cobrem as duas transições de **um** dia
(`test_ausencia_ja_reportada_nao_reincide` e `test_ausencia_reincide_quando_escala`) e passam. Nenhum
atravessa três dias, que é onde a sequência quebra. É a mesma classe do `toContain("flex-wrap")`
que já custou duas sessões a este repositório: a asserção está correta e não prova o comportamento.

O efeito combinado, hoje, em produção: **uma conta a pagar em aberto aparece todo dia do vencimento
menos um até o vencimento mais dois, e depois dia sim, dia não, para sempre.** É exatamente o papel
de parede que a regra existe para impedir.

---

## Objetivo

Que o dono saiba de uma cobrança **antes** de ela vencer, e que toda ausência do briefing fale nos
momentos em que é notícia e cale no resto — inclusive as que já falam demais hoje.

---

## A cadência

Uma cobrança de R$ 2.000 que vence em 20/08, com antecedência de 3 dias:

| Dia | O briefing |
|---|---|
| 17/08 | **fala** — "vence em 20/08" (cruzou o limiar) |
| 18–19/08 | silêncio |
| 20/08 | **fala** — "vence hoje" |
| 21/08 | **fala** — "venceu há 1 dia" |
| 22/08 | **fala** — "venceu há 2 dias" |
| 23/08 | silêncio |
| 24/08 | **fala** — "venceu há 4 dias" |
| 25–27/08 | silêncio |
| 28/08 | **fala** — "venceu há 8 dias" |
| 05/09 | **fala** — "venceu há 16 dias" |

Sete aparições ao longo de três semanas, em três momentos que são notícia de verdade: **dá para agir**,
**venceu**, **está piorando**. A mesma cadência vale para conta a pagar — a simetria entre as duas
direções do dinheiro é o ponto do trabalho, e hoje a conta a pagar é a que mais fala.

---

## A solução

### `_proximo_marco` — uma função que atravessa o zero

`_ja_dita` vira `_calada`, e `anterior * 2` vira:

```python
def _proximo_marco(anterior: int) -> int:
    """Em que intensidade esta ausência volta a ser notícia."""
    if anterior < 0:
        return 0          # falou antes de vencer → só volta no vencimento
    if anterior == 0:
        return 1          # falou no vencimento → volta no primeiro dia de atraso
    return anterior * 2   # o comportamento de hoje, intacto
```

A comparação passa a ser `dias < _proximo_marco(anterior)`.

⚠️ **O ramo positivo é literalmente a expressão de hoje.** Não é uma reescrita equivalente "na
prática" — é a mesma multiplicação, no mesmo lugar. É essa identidade que torna seguro aplicar o
conserto às cinco famílias de ausência de uma vez: card parado dito no dia 10 continua voltando no
dia 20, sem uma linha de comportamento novo. O que muda para as famílias comerciais não é a
escalada; é o mapa deixar de esquecê-las.

Foi preferida a duas alternativas:

- **Normalizar a intensidade** (converter `dias` para sempre positivo somando o limiar, mantendo a
  razão): a razão fica degenerada em zero, o mapeamento passa a depender do limiar vigente, e
  recalibrar muda o significado dos valores já gravados. Mais partes móveis para o mesmo resultado.
- **Cadência declarada por família** (cada regra publica a própria lista de marcos): espalha por
  cinco lugares uma decisão que hoje mora em um só, para atender uma variação que ninguém pediu.

### O mapa passa a ser de marcos, não de ditas

`coletar` hoje filtra e devolve só o que sobrou. Passa a devolver também o que ficou para trás:

```python
@dataclass(frozen=True)
class Coleta:
    ditas: list[Ausencia]
    marcos_anteriores: dict[str, int]   # chave → marco, de TODA ausência viva que já tem um
```

⚠️ **`marcos_anteriores` não é a lista das caladas.** Carrega o valor anterior de toda ausência que
existe hoje e já foi dita alguma vez — calada **ou** dita. A diferença importa por causa do teto:
uma ausência **dita e cortada** pelas 12 linhas também precisa preservar o marco, porque ninguém a
leu. Hoje ela some do mapa e volta no dia seguinte, contrariando a docstring do próprio `Payload`,
que já diz que isso não deveria acontecer.

A decisão de calar continua morando em `absences.py`, onde está a semântica de ausência. O
compositor não aprende a regra do silêncio: recebe um dicionário pronto e continua fazendo só o que
já faz — ordenar, cortar e montar.

`coletar` deixa de devolver `list[Ausencia]`, então todos os testes que hoje fazem
`[a.kind for a in coletar(...)]` passam a ler `.ditas`. É mudança mecânica e ampla — vale contá-la
no esforço, e vale fazê-la num commit próprio, separado do commit que muda comportamento, para que
a revisão consiga ver o que de fato mudou.

No compositor, uma linha substitui a de hoje:

```python
marcos = {**coleta.marcos_anteriores, **{c.chave: c.dias for c in mantidas if c.chave}}
```

Os quatro casos caem certos sem nenhum `if`:

| Situação | Resultado |
|---|---|
| Calada hoje | preserva o marco anterior — para de piscar |
| Dita e mostrada | atualiza para o `dias` de hoje |
| Dita e cortada pelo teto | preserva o anterior — ninguém leu, ninguém foi calado |
| Resolvida (paga, card movido) | não está na coleta, cai do mapa — limpeza automática |

### Os dois nomes que ficaram errados

`Payload.ausencias_ditas` deixa de significar "ditas" e vira `Payload.marcos`. A chave no JSON vira
`marcos`, e `service._ja_reportadas` lê `marcos` com fallback para `ausencias_ditas` — mesma forma
do `Linha.kind` com default `""` no V2. **O fallback é permanente:** os briefings gravados em
produção têm a chave antiga, e removê-lo exigiria migração de payload para não calar ninguém errado
no dia do deploy.

---

## A cobrança a receber

### O limiar

`LIMIARES_PADRAO` ganha `cobranca_antecedencia_dias`, e `_dinheiro_com_data` passa a ler
`Charge.due_date <= hoje + timedelta(days=lim["cobranca_antecedencia_dias"])` no lugar de
`Charge.due_date < hoje`. A conta a pagar não muda de query — ela já tem antecedência; o que muda
para ela é a cadência.

**O default nasce em 3, decidido pelo dono do produto.** É o único número deste design que não é
derivado de outro: cutucar um cliente pede mais folga que juntar dinheiro para pagar um boleto, e
três dias é o prazo em que um lembrete ainda evita o atraso em vez de constatá-lo. Registrado aqui
como escolha, não como cálculo.

### As três vozes da linha

| Estado | Texto |
|---|---|
| `dias < 0` | `Mensalidade agosto — R$ 2.000,00 vence em 20/08` |
| `dias == 0` | `Mensalidade agosto — R$ 2.000,00 vence hoje` |
| `dias > 0` | `Mensalidade agosto — R$ 2.000,00 venceu há 3 dia(s) e não foi paga` (inalterado) |

A voz de vencido continua distinta de propósito — "não foi paga" é o estado que muda o que o dono
faz. Os dois primeiros ramos copiam a forma da conta a pagar, que aparece na mesma seção.

Mudar o título é seguro: o eixo da frase repetida vale para **fato**, não para ausência. A chave da
ausência é `kind:subject_id`, então o mapa de marcos atravessa a mudança de texto sem se perder.

### O `kind` que virou mentira

`financeiro.cobranca.vencida` passa a sair antes de vencer. Vira **`financeiro.cobranca.vencendo`**,
simétrico ao `financeiro.conta.vencendo` que mora ao lado.

Consequência, e ela dura um dia: as chaves gravadas nos briefings antigos usam o nome velho, então
toda cobrança vencida em aberto fala uma vez a mais no dia do deploy. É aceitável, e defensável —
o comportamento dela de fato mudou.

O renome é seguro no resto do sistema, verificado contra o código: `_PESOS` não contém `kind` de
ausência (todas pesam `_PESO_PADRAO`), `_chave_de_ordem` não usa `dias`, e o front monta o gancho
genericamente a partir do `kind` (`BriefingPage.tsx`, `briefing.ausencia.${primeiroKind(linhas)}`).

### A 7ª pergunta de Calibração

```python
_cal(
    "dinheiro.cobranca_antecedencia_dias", "dinheiro",
    "E de uma cobrança que você tem a receber?",
    (Opcao("No próprio dia", 0), Opcao("1 dia antes", 1),
     Opcao("3 dias antes", 3), Opcao("1 semana antes", 7)),
    "cobranca_antecedencia_dias",
    "briefing.ausencia.financeiro.cobranca.vencendo",
)
```

O V2 fixou que **são 6 de Calibração porque só existem 6 consumidores**, e que qualquer número
maior seria invenção. Nasce um consumidor real, então nasce a sétima pergunta — este é o caso
legítimo, e é a primeira vez que a guarda de import é exercitada por um consumidor novo.

A guarda cobre o erro caro: `consome` precisa apontar para chave real de `LIMIARES_PADRAO`, então
um typo em `cobranca_antecedencia_dais` impede o módulo de carregar, em vez de gravar a resposta do
dono para sempre sem efeito nenhum.

⚠️ **A pergunta não entra no núcleo.** `NUCLEO` continua com 6 e continua sendo de Retrato.
Calibração vai por gancho, colada à ausência que a motivou — a inversão central do V2. Na prática o
dono vê essa pergunta na primeira vez que uma cobrança aparece no briefing dele, que é o único
momento em que ela é respondível.

---

## Gates

O primeiro commit é um teste que **falha**: a sequência de três dias sobre `coletar` + `compor`,
encadeando o mapa de um dia na entrada do seguinte. Ele prova a piscada que até aqui só foi
afirmada por leitura de código. **Se ele passar de primeira, a leitura estava errada e este design
volta para a mesa antes de qualquer conserto.**

Depois dele, quatro provas do comportamento novo:

| Prova | O que fixa |
|---|---|
| Linha do tempo de 17/08 a 05/09 sobre uma cobrança | A cadência inteira: −3 → 0 → 1 → 2 → 4 → 8 |
| Card parado dito no dia 10, calado até o 20 | O ramo positivo não mudou para as famílias comerciais |
| Ausência cortada por `teto=1` preserva o marco | O bug irmão do teto, que o `Payload` já prometia |
| Briefing gravado só com `ausencias_ditas` é lido | O fallback do payload antigo, que é o que existe em produção |

### As quatro mutações

As afirmações deste spec só valem se quebrarem quando violadas. Cada uma tem que derrubar **um**
teste identificável:

- Trocar `{**marcos_anteriores, **hoje}` por só `hoje` → quebra a sequência de três dias, e nada mais.
- Apagar o ramo `anterior < 0` → quebra a linha do tempo no dia do vencimento, e nada mais.
- Apagar o ramo `anterior == 0` → quebra no primeiro dia de atraso.
- Trocar `_proximo_marco` de volta por `anterior * 2` puro → quebra **só** os testes de dinheiro.

A quarta é a que compra o raio das cinco famílias, e é a primeira a ser rodada: se ela quebrar
algum teste comercial, a afirmação de que o ramo positivo é idêntico era falsa.

### Os três de sempre

`ruff check .`, `pytest`, `pnpm --filter @e1p/web test` — os três, mesmo sem mudança de front.

`absences.py` e `resolver.py` continuam puros, sem leitura de relógio, então a varredura AST de
`test_fuso_do_tenant.py` continua verde sem exceção nova.

**Sem migration.** `dna_answers` é chave/valor e o catálogo é código, então não há head para
reconferir e a colisão de numeração que já mordeu este repositório três vezes não se aplica.

---

## Riscos e dívidas conhecidas

- **O briefing fica mais quieto em todas as seções no dia do deploy.** É a mudança pretendida, mas
  é visível: pendências que hoje aparecem dia sim, dia não passam a aparecer só nos marcos. Vale
  avisar quem estiver na semana de primeiro uso.
- **Responder a pergunta nova zera o silêncio de todas as regras.** A limpeza de
  `recalibrado_apos` é grossa de propósito (decisão do V2), então no dia em que o dono responder,
  o briefing fala alto uma vez. Comportamento desenhado, com um gatilho a mais.
- **Achado não consertado aqui:** `resolver.recalibrado_apos` compara `linha.answered_at.date() >=
  quando`, usando `.date()` num `timestamptz` — a mesma forma que o V2 documenta como errada em
  `cadencia.py`. Aqui ela erra sempre para o lado de **limpar** o silêncio, que é o erro barato
  declarado na própria docstring, e a varredura AST não a pega porque não é leitura de relógio.
  Fica registrado; mexer nisso é outra frente.
- **As perguntas do DNA passam a ser 46 e continuam sem validação com dono real.** Esta é a única
  com consumidor nascido no mesmo passo.
- **A validação manual em ~360px do V2 continua bloqueando release** e não é tocada aqui. A aba
  "A sua empresa" ganha uma linha a mais no eixo `dinheiro` — vale medir junto quando for feita.

---

## Fora de escopo

| Fora | Por quê |
|---|---|
| V3 (Memória Empresarial) | `facts` não teve backfill e vale de 06/08 em diante; narraria um log quase vazio |
| V4 (Motor de Contexto e Autonomia) | Bloqueado por uma decisão não tomada — o teto de gasto por tenant |
| Cobrar o cliente automaticamente | A Vima só narra. Executar é V4 |
| Mudar o texto da linha de conta a pagar | Só a cadência dela muda; a voz fica |
| Cadências diferentes por família de ausência | Ninguém pediu variação; uma função serve as cinco |
| Migrar os payloads gravados para a chave `marcos` | O fallback custa uma linha e resolve para sempre |
