# DRE em matriz mensal (meses × categorias)

**Data:** 2026-07-21
**Status:** Aprovado para planejamento
**Módulo:** `financial_intelligence` (backend) / `features/financeiro` (frontend)

## Contexto

A DRE por categoria atual (`DrePage.tsx`, Story 5.3) mostra **um único período** por vez
(seletor de mês, com paginação ◀ ▶) e cada grupo (Receita/Custo Direto/Despesa Fixa/Tributos/
Financeiro/Investimento) expande para revelar suas categorias. Para enxergar a evolução mês a
mês hoje é preciso trocar de mês repetidamente.

Referência trazida pelo usuário: uma tela de "Despesas & receitas" que mostra todos os meses do
período escolhido lado a lado (colunas), com categorias em linha, subtotais por grupo e um total
geral — sem precisar navegar mês a mês.

## Objetivo

Substituir a DrePage atual por uma visão em matriz: linhas = categorias (agrupadas por grupo DRE
OU por centro de custo, alternável), colunas = um mês por coluna dentro do período escolhido,
com subtotais de grupo e uma linha de total geral. Período escolhido por um dropdown com atalhos
(Este mês/Mês anterior/Este trimestre/Este ano/Últimos 12 meses/Tudo/Personalizado).

## Decisões (confirmadas com o usuário)

1. **Substitui** a `DrePage.tsx` atual (não é uma tela nova em paralelo).
2. Agrupamento alternável: **por grupo DRE** (como hoje) **ou por centro de custo** — toggle na
   tela, ambos suportados desde o início (não é um "depois").
3. Seletor de período com as mesmas opções do print de referência.
4. Grupos **sempre expandidos** (sem colapsar/expandir por clique) — mais simples, sem estado de
   UI por grupo.

## Arquitetura

### Backend — novo endpoint, mesma convenção de sinal e regime de competência

`GET /financial-intelligence/dre/matrix?start&end&group_by=dre|cost_center[&cost_center_id=...]`

Reaproveita integralmente a convenção de sinal e as exclusões já ratificadas em `dre.py`
(sinal pela tabela de origem — Charge=+/Payable=−; INVESTIMENTO fora do resultado; bucket
`SEM_CATEGORIA` fora do resultado; regime de competência via `COALESCE(competence_date, due_date)`;
`GROUP BY` no banco, nunca soma em Python sobre linhas individuais).

A única mudança estrutural é **adicionar o mês ao GROUP BY**: em vez de agrupar só por
`chart_account_id` (e opcionalmente `cost_center_id`), agrupa por
`(date_trunc('month', competence), chart_account_id[, cost_center_id])`. Uma query por tabela de
origem (Charge/Payable/Transaction), como hoje — nunca um loop em Python chamando a agregação
uma vez por mês.

```python
@dataclass
class DreMatrixRow:
    label: str                  # categoria
    monthly_cents: list[int]    # alinhado a `months`, mesmo tamanho
    total_cents: int

@dataclass
class DreMatrixGroup:
    key: str                     # grupo_dre code, OU cost_center_id ("_unassigned" p/ Não atribuído)
    label: str
    kind: str                    # "result" | "informational" | "uncategorized" — mesmos 3 kinds de hoje
    rows: list[DreMatrixRow]
    subtotal_cents: list[int]
    subtotal_total: int

@dataclass
class DreMatrixReport:
    months: list[str]            # ["2026-01", ..., "2026-12"], sempre contíguo
    groups: list[DreMatrixGroup]
    grand_total_cents: list[int] # só soma os grupos "result" (mesma regra do resultado hoje)
    grand_total: int
    notes: list[str]             # mesmas notas de hoje (competência, investimento, sem categoria)
```

- `group_by=dre`: mesma função de hoje (`dre_report`), com o eixo de mês adicionado. Grupos na
  ordem canônica de `GROUP_ORDER` (mesmo os vazios), na mesma ordem/label de hoje.
  `cost_center_id` continua filtro opcional (mantém o dropdown "Todos os centros de custo" já
  existente para este modo).
- `group_by=cost_center`: novo. Groups = cada centro de custo (ordem alfabética, arquivados só se
  tiverem lançamento no período — mesma regra de `by_cost_center_report`) + bucket "Não
  atribuído" por último. Dentro de cada grupo, as linhas são as **categorias do plano de contas**
  (não o grupo DRE) — precisa estender `_sum_by_cost_center_and_account` para agrupar também por
  `chart_account_id` (hoje só resolve o grupo; passa a resolver `(grupo, categoria)` para poder
  etiquetar a linha e decidir se entra no resultado). `cost_center_id` como filtro não se aplica
  nesse modo (já é a própria dimensão de agrupamento) — o dropdown de centro de custo some da UI
  quando `group_by=cost_center`.
- Meses sem nenhum lançamento aparecem com `0` em todas as células (não somem colunas) — mesma
  filosofia de "mostrar os 6 grupos mesmo vazios" que a DRE já aplica hoje.
- Período "Tudo" ou ranges muito longos (ex.: vários anos) simplesmente geram mais colunas; a
  tabela rola horizontalmente (ver Frontend). Não há também nenhum teto artificial de meses.

### Frontend — `DrePage.tsx` reescrita como tabela

- Dropdown de período com as opções: Este mês, Mês anterior, Este trimestre, Este ano, Últimos 12
  meses, Tudo, Personalizado (abre dois `<input type="month">` de início/fim). Cada opção resolve
  para um `{start, end}` enviado direto ao endpoint — sem loop de meses no cliente.
- Toggle "Por grupo DRE" / "Por centro de custo" troca `group_by` e refaz a query.
- Tabela: 1ª coluna fixa (sticky) com o rótulo da linha (categoria), 1 coluna por mês em
  `formatBRL`, dentro de um container `overflow-x-auto` (mesmo padrão já usado em tabelas largas
  do app, ex. Contas a Pagar).
  - Cada grupo: linha de cabeçalho (label do grupo/centro de custo, sem clique — sempre aberto),
    linhas de categoria, linha de subtotal em negrito.
  - Linha final `TOTAL GERAL` (só soma grupos "result", mesma regra do `resultado_cents`).
  - Grupo `kind="informational"` (Investimento) e `kind="uncategorized"` (Sem categoria) mantêm o
    badge/estilo (âmbar) que já existe hoje, mas fora da soma do `TOTAL GERAL`.
- O card "Resultado do período" no topo passa a mostrar `formatBRL(grand_total)` do período
  selecionado (não mais um único mês) — mesmo texto de rodapé explicativo de hoje.
- `contratoDre.ts`/`ContratoDrePage.tsx` (DRE por contrato) **não são afetados** — é um
  relatório diferente (Story 5.4), fora do escopo desta mudança.

## Fora de escopo (explicitamente)

- Não mexe na DRE por contrato (`ContratoDrePage.tsx`/`profitability.py`).
- Não adiciona exportação (CSV/PDF) da matriz.
- Não adiciona gráfico/visualização — só a tabela.
- Não pagina nem trunca meses no período "Tudo" — resolve por scroll horizontal.

## Testes

- Backend: `test_financial_intelligence_dre.py` ganha casos para `group_by=cost_center`, meses
  contíguos com buracos (mês sem lançamento = zeros), e paridade byte-a-byte do `group_by=dre`
  sem `cost_center_id` com o relatório antigo somado ao longo dos meses. RLS: reaproveita
  `test_financial_intelligence_dre_rls.py`.
- Frontend: `dre.test.ts` (puro, sem jsdom) ganha os novos tipos/transformação da matriz.
