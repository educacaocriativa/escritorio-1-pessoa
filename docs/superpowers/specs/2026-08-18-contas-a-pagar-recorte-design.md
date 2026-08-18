# Contas a Pagar — o recorte da lista, e reativar conta cancelada

**Data:** 2026-08-18
**Origem:** pedido do fundador — *"esta tela esta um linguicao, cada vez que vai aumentando o
volume de registro fica dificil o uso, em virtude da rolagem"*, *"conseguir reativar um contas a
pagar cancelado"* e *"busca nao esta funcionando"*.

## 1. O problema

A tela abre numa lista única, sem filtro nenhum, ordenada por vencimento **crescente**. Três
consequências, e a mais grave não é a que motivou o pedido.

**A tela está ancorada no passado.** `order_by(Payable.due_date)` sem direção coloca a conta mais
antiga já paga na primeira linha. Em produção hoje isso é maio de 2026: o registro menos acionável
que existe ocupa o lugar para onde os olhos do dono vão primeiro, e o que ele veio ver — o que
vence agora — está no meio da rolagem.

**A lista cresce sozinha.** Recorrência neste sistema é **materializada**, não projetada:
`service.create_payable` grava N linhas reais, uma por ocorrência, ligadas por `recurrence_group`.
Um pró-labore mensal por doze meses são doze registros. O volume que incomoda o dono não vem de ele
lançar mais despesa; vem de ele ter lançado uma.

**E o corte acontece do lado errado, em silêncio.** `service.list_payables` tem `limit: int = 200`
com teto rígido de 500, e o router **não expõe** `limit` nem `offset`. Combinado com a ordenação
crescente, a rota devolve **as 200 mais antigas**. Passando de 200 contas no tenant, o que
desaparece da tela não é o histórico velho: são as contas **futuras, ainda por pagar**. Sem aviso,
sem contagem, sem sintoma visível. Este é o defeito mais sério dos três e ninguém o havia notado.

Somados: a rolagem é o sintoma, a ancoragem é a causa e o truncamento silencioso é o risco.

## 2. Escopo

**Dentro:** o recorte da lista de Contas a Pagar (filtros, horizonte, paginação com contagem
honesta), a correção do teto de 200 e a reativação de conta cancelada. Front e back, módulo
`payables`.

**Fora, e é uma separação deliberada:** a **busca global** da barra de cima. O campo *"Buscar
cliente, projeto ou processo"* do `AppShell` nunca foi ligado — o próprio código diz *"A busca não
tem handler nenhum — é decoração até alguém ligá-la"* (`AppShell.tsx:184`). Não é regressão; é um
`<input>` sem `onChange`. Ligá-lo exige decidir quais entidades entram, como rankear resultado de
tipos diferentes, como o RLS se aplica a uma consulta que cruza tabelas e se `pg_trgm`/`tsvector`
são necessários — o projeto inteiro não tem infra de busca, o único `ilike` do backend está em
`crm/service.py:394`. **É um segundo projeto, com spec própria**, e ele vai reusar o filtro de
texto de `payables` que esta spec constrói.

Fora também: reativar cobrança em Contas a Receber (§11), agrupamento visual por série de
recorrência, e otimização de índice para o `ilike`.

## 3. A visão padrão — a decisão central

A tela abre em **"o que eu devo"**: `status ∈ (open, scheduled)`, **sem limite inferior de data** e
com teto no fim do mês seguinte.

O "sem limite inferior" é a parte que não pode ser simplificada. Atrasado tem vencimento no
passado; qualquer piso de data esconde exatamente a conta mais urgente que existe. O horizonte
corta **só o futuro distante** — e o lugar de olhar longe continua sendo a Projeção de caixa, que
já existe para isso.

**A ordenação segue a intenção do filtro:**

| Recorte | Ordem | Por quê |
|---|---|---|
| Em aberto / agendada | `due_date` crescente | o vencimento mais próximo primeiro; atrasado no topo |
| Pago (histórico) | `due_date` **decrescente** | o mais recente primeiro; manter crescente aqui é o defeito de hoje |
| Cancelado | `due_date` decrescente | quem procura uma cancelada procura a última, não a de 2025 |

Pago e cancelado saem da visão inicial e ficam a um clique, no filtro de status.

## 4. A tela

```
Página / Contas a Pagar
Despesas
[A pagar 185.757,04] [Atrasado 0,00] [Nesta semana 18.000] [Pago no mês 5.625]
--------------------------------------------------------------------------
 buscar fornecedor ou descrição   [Em aberto v] [Até out/26 v]
                                  [Centro de custo v] [Categoria v]
 chips do filtro ativo                              limpar filtros
--------------------------------------------------------------------------
 CONTA        CATEGORIA   CENTRO   VENCIMENTO   VALOR   STATUS   (ações)
 ...
--------------------------------------------------------------------------
 Mostrando 23 de 23                            [ver mais adiante]
```

**A linha de contagem nunca mente.** `Mostrando 50 de 213`, com `carregar mais`. Se algum dia
truncar, o dono vê. O pecado do bug de hoje não é ter um teto — é o teto não se anunciar, e
qualquer solução que mantenha o silêncio reconstrói o mesmo defeito com filtro novo por cima.

**Os quatro cards de topo não seguem o filtro.** Eles são o retrato do tenant inteiro e continuam
sendo. Ganham rótulo explícito para que a lista filtrada mostrando R$ 3 mil ao lado de um card de
R$ 185 mil não pareça contradição.

**O `GanchoDaVima` desce para baixo da tabela.** Hoje o bloco *"Você emite nota fiscal?"* ocupa
cerca de 200px logo abaixo do título e empurra a tabela para fora da primeira dobra. Ele continua
sendo respondido; só para de disputar a dobra com o motivo pelo qual a tela foi aberta. Decisão
acatada pelo fundador, fora do pedido original.

**Reativar** aparece como ação nas linhas de status `Cancelado` — invisíveis na visão padrão,
alcançáveis por `Status → Cancelado`. Isso é coerente: reativar é gesto deliberado, não algo em que
se tropeça enquanto se dá baixa em contas.

## 5. A API

### 5.1 `GET /payables/bills` — recorte e total

```
GET /payables/bills
  ?status=open&status=scheduled     repetível; a visão padrão manda os dois
  &from=YYYY-MM-DD                  due_date >=   (ausente no padrão, de propósito — §3)
  &to=YYYY-MM-DD                    due_date <=   (fim do mês seguinte, no padrão)
  &q=anthropic                      ilike em description OU supplier
  &cost_center_id=... &chart_account_id=...
  &order=asc|desc  &limit=50  &offset=0
-> { "items": [PayableOut, ...], "total": 213 }
```

`status` passa de `str | None` para `list[str] | None`. A visão padrão são **dois** status, não um;
na rede o valor único de hoje continua válido, então nada existente quebra.

**`order` é decidido pelo front, não inferido pelo back.** A regra da §3 ("histórico vem
decrescente") mora em `filtros.ts` e chega ao servidor como parâmetro explícito; o backend obedece
e valida. A alternativa — o backend adivinhar a direção a partir do status pedido — esconde a regra
num lugar onde ninguém a procura e quebra assim que alguém combinar "pago + em aberto" na mesma
consulta. O padrão, se `order` vier ausente, é `asc`.

**A resposta deixa de ser lista nua e vira `{ items, total }`.** É mudança de contrato, e é
justificada: sem `total` não existe "mostrando 50 de 213", e sem isso o truncamento volta a ser
silencioso. O custo é contido — a coleção tem **um único chamador**, `PagarPage.tsx:107` (as demais
chamadas em `apps/web` são de item único ou de subrotas), e `Payable` é escrito à mão em
`packages/shared-types/src/index.ts:459`, então o TypeScript aponta o lugar exato a corrigir em vez
de deixar quebrar em runtime.

### 5.2 Buscar e contar saem do mesmo predicado

`list_payables` e `count_payables` **compartilham** um `_filtros(stmt, ...)`. Não é preferência de
estilo: dois blocos de `where` copiados divergem na primeira manutenção, e a partir daí a tela
anuncia um número que a própria lista não confirma. É um modo de falha discreto — nada quebra, o
rodapé só passa a mentir — e por isso ele ganha construtor único e teste dedicado (§8.2).

### 5.3 O `q` precisa escapar `%` e `_`

`ilike` interpreta os dois como curinga. Digitar `%` sem escape casa com tudo, e a busca parece
funcionar quando na verdade não está filtrando nada. O escape acontece antes de montar o padrão, e
tem teste próprio (§8.3) porque a implementação ingênua passa em todos os outros.

### 5.4 O horizonte é calculado no fuso do tenant

O front deriva "fim do mês seguinte" com `useFuso()` (`store/auth.tsx:115`) e `today(fuso)`
(`lib/datetime.ts:105`). `new Date()` cru reintroduziria a classe de bug do fuso pela porta do
filtro: em UTC-3, das 21h à meia-noite o horizonte pularia um dia inteiro.

### 5.5 Paginação

O teto de 500 do serviço permanece como guarda contra pedido absurdo, mas agora acompanhado do
`total` real — truncar deixa de ser invisível. O front pagina por `offset` com `carregar mais`, que
**anexa** ao que já está na tela. Esta é a primeira lista paginada do projeto; o padrão que ela
estabelece vale para as próximas.

## 6. Reativar conta cancelada

### 6.1 Rota nova, e por quê

```
POST /payables/bills/{id}/reactivate -> PayableOut
```

Reusar `POST /reverse` seria errado por **significado**, não por estilo. `reverse` quer dizer *"esta
saída não vai acontecer"*, e o trabalho dele é **apagar o movimento bancário** — o trecho com o
raciocínio mais cuidadoso do arquivo, com três alternativas rejeitadas documentadas. Reativar quer
dizer o oposto: *"esta saída volta a ser esperada"*. E como `cancel_payable` só aceita conta em
aberto, **não existe movimento bancário nem evento de Agenda para desfazer**. Fundir os dois
obrigaria um `if status == canceled: pula tudo` no meio dessa lógica, e é assim que um dos dois
caminhos deixa de receber a próxima correção.

### 6.2 O serviço

Simétrico a `cancel_payable`: trava a linha com `with_for_update()`, 404 se não existe, **409 se o
status não for `canceled`** (*"Só contas canceladas podem ser reativadas"*), põe `open`, grava
`payable.reactivate` na auditoria — seguindo o padrão `payable.<verbo>` dos outros seis — e
commita. Nada de bancário, nada de Agenda.

### 6.3 O vencimento é preservado

Uma conta cancelada que vencia 20/08, reativada em 18/09, volta como **Atrasada**, com o vencimento
original. `is_overdue` calcula isso sozinho.

As duas alternativas foram consideradas e rejeitadas. **Pedir a nova data** num diálogo cobra dois
passos toda vez, inclusive nos casos em que a data original ainda vale. **Empurrar para hoje**
automaticamente apaga o vencimento que o dono de fato contratou — e a partir daí a Projeção e o DRE
passam a contar uma data que nunca existiu. Preservar não inventa nada, e a conta reativada já é
editável (status `open`), então corrigir a data é um gesto disponível, não um gesto imposto.

## 7. As peças

| Arquivo | Mudança |
|---|---|
| `apps/api/app/modules/payables/service.py` | `_filtros()` novo; `list_payables` ganha filtros/ordem; `count_payables` novo; `reactivate_payable` novo |
| `apps/api/app/modules/payables/router.py` | query params em `GET /bills`; response model novo; rota `POST /bills/{id}/reactivate` |
| `apps/api/app/modules/payables/schemas.py` | `PayablesPageOut { items, total }` |
| `packages/shared-types/src/index.ts` | `PayablesPage` ao lado de `Payable` (escrito à mão) |
| `apps/web/src/features/pagar/FiltrosDaLista.tsx` | **novo** — a barra de filtros, isolada da página |
| `apps/web/src/features/pagar/filtros.ts` | **novo** — estado do filtro, padrões e serialização para query string; unitário, sem DOM |
| `apps/web/src/features/pagar/PagarPage.tsx` | consome `{items,total}`, costura filtros, `carregar mais`, ação Reativar, `GanchoDaVima` para baixo |

A barra e a lógica de filtro saem em arquivos próprios porque `PagarPage.tsx` já tem 660 linhas e
carrega quatro modais; empilhar mais estado ali torna o arquivo difícil de manter e de editar com
segurança. `filtros.ts` sem DOM é o que permite testar os padrões e a serialização sem montar a
página inteira.

## 8. Testes

O teste que mais importa é o que **reprova a versão atual do código**. Sem ele, "o teto de 200 foi
consertado" é opinião.

**8.1 — O teto, provado com volume.** 250 contas criadas. `limit=50&offset=0` devolve 50 itens e
`total=250`; `offset=200` devolve linhas que **hoje são inalcançáveis pela rota**. Falha no código
de hoje. É a régua da entrega.

**8.2 — Contagem casa com lista, sob cada filtro.** Para cada combinação, com `limit` folgado,
`total == len(items)`. É o alarme contra o `_filtros` divergir (§5.2).

**8.3 — `q` escapa curinga.** Com "100% Cacau" e "Anthropic" no banco, buscar `%` traz **uma**
linha. A implementação ingênua passa em todos os outros testes e falha só neste.

**8.4 — `from` ausente não engole atrasado antigo.** Conta vencida há seis meses aparece na visão
padrão. É a §3 virando asserção.

**8.5 — `status` repetível; `to` inclusivo na borda; `order` asc e desc.**

**8.6 — Reativar, matriz completa.** `canceled -> open` com vencimento intacto; `paid`, `open` e
`scheduled` -> 409; id inexistente -> 404; auditoria gravou `payable.reactivate`.

**8.7 — Reativada com vencimento passado nasce `is_overdue`**, com `hoje_do_tenant` injetado —
nunca a hora em que a suíte roda.

**8.8 — `PagarPage.test.tsx`:** o estado inicial manda dois status, `to` no fim do mês seguinte e
**`from` ausente**; digitar dispara **uma** chamada e não uma por tecla (o `debounce` de
`AccountModal.tsx:154`); `carregar mais` **anexa** em vez de substituir; "Mostrando X de Y" reflete
o `total`; linha cancelada tem "Reativar" e linha aberta não tem.

**8.9 — `filtros.test.ts`** (unitário): padrões corretos, serialização para query string,
`limpar filtros` volta ao padrão e não a vazio.

**Antes de declarar verde, três comandos e não um:** `pytest -q`; depois `TZ=UTC pytest -q` (esta
classe de quebra noturna já reincidiu duas vezes neste repositório); e `pytest -m rls_e2e` com
Docker — este porque a mudança mexe em construtor de query, e um filtro que vaze escopo de tenant é
bug de segurança, não de usabilidade. Ele fica fora do `pytest -q` por padrão, então precisa ser
pedido explicitamente.

**Não será testado:** desempenho do `ilike`. Sem volume de produção, qualquer número seria
decorativo.

## 9. 360px

`apps/web/e2e/pagar-360.spec.ts`, seguindo a convenção existente: Vite sozinho, API interceptada
por `page.route`, sem backend e sem Docker.

Mede `boundingBox` de verdade — a barra de filtros reflui em duas linhas e nada estoura os 360px —
e valida alvos de toque de 44px nos controles. **Não** `toContain("flex-wrap")`: asserção de classe
CSS já passou verde com a tela quebrada neste projeto, e a régua aqui é medida, não string.

## 10. Riscos

| Risco | Mitigação |
|---|---|
| `total` e `items` divergirem por `where` duplicado | Construtor `_filtros` único (§5.2) + teste 8.2 |
| Curinga não escapado fazer a busca parecer funcionar sem filtrar | Escape explícito + teste 8.3, que reprova a versão ingênua |
| Horizonte calculado com `new Date()` cru reintroduzir bug de fuso | `useFuso()` + `today(fuso)`, com o motivo escrito no código |
| `carregar mais` substituir em vez de anexar | Teste 8.8, escrito para este defeito específico |
| Filtro novo vazar escopo de tenant | `pytest -m rls_e2e` obrigatório antes de verde |
| Alguém "simplificar" o padrão pondo um `from` na visão inicial e sumir com o atrasado | Teste 8.4 + o motivo registrado na §3 |

## 11. Assimetria registrada

`receivables.cancel_charge` tem o mesmo beco sem saída: cobrança cancelada também não volta. Fora
de escopo por ora — não foi pedido e dobraria a superfície de teste — mas fica anotado para quando
incomodar. A rota lá seria `POST /receivables/charges/{id}/reactivate`, com a mesma forma da §6.2.

## 12. Entrada no CLAUDE.md

Último passo obrigatório: registrar que Contas a Pagar passou a abrir em "o que eu devo" (e por
quê), que `GET /payables/bills` devolve `{items,total}` com filtros, que existe `reactivate` e que
a busca da barra de cima **continua desligada** — este último para que a próxima sessão não gaste
tempo procurando um bug que não existe.
