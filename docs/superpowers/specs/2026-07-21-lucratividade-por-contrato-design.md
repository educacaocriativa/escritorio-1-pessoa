# Lucratividade por Contrato (ranking + ledger de lançamentos)

**Data:** 2026-07-21
**Status:** Aprovado para planejamento
**Módulo:** `financial_intelligence` (backend) / `features/financeiro` (frontend)

## Contexto

Hoje a lucratividade por contrato (Story 5.4, `profitability.py`) só existe como uma tela
**por contrato** (`ContratoDrePage.tsx`, rota `/financeiro/contratos/:id/dre`): margem de
contribuição, break-even e overhead rateado de UM contrato de cada vez — é preciso já ter o
`id` do contrato (ex.: vindo da Ficha 360° do cliente) para chegar lá.

Falta uma visão de **ranking**: todos os contratos assinados lado a lado, ordenados por margem,
para comparar rapidamente quem está performando bem. E falta uma forma de ver os **lançamentos
individuais** (não agregados por categoria) de um contrato — um extrato cronológico, tipo
extrato bancário.

## Objetivo

1. Nova página `/financeiro/lucratividade`: lista todos os contratos assinados (mesmo os sem
   movimento no período) com Receita/Custo Direto/Margem/Margem%/Overhead/Resultado, ordenada
   por margem descendente, com um toggle global de rateio de overhead e o mesmo seletor de
   período usado na matriz da DRE (ver spec relacionado abaixo).
2. Botão "Detalhes" por linha abre um **drawer** (novo padrão de UI, lateral direito) com o
   extrato cronológico de lançamentos (Payable/Charge) daquele contrato no período.

Relacionado: `2026-07-21-dre-matriz-mensal-design.md` (mesmo seletor de período compartilhado).

## Decisões (confirmadas com o usuário)

1. Ranking lista **todos os contratos com `status="signed"`**, mesmo com R$ 0,00 no período —
   não lista rascunho/enviado/cancelado, não esconde contrato assinado sem movimento.
2. Overhead **não vem rateado por padrão**: um checkbox global acima da tabela (mesmo texto/UX
   do checkbox já existente na `ContratoDrePage`) liga o rateio pra todas as linhas de uma vez,
   recalculando Overhead e Resultado.
3. O drawer usa **apenas Payable+Charge** (não `Transaction`, que não tem `contract_id`) —
   mesmo escopo que a margem de contribuição já usa hoje. Ordenado por `competence_date`
   (mesma data usada em toda a DRE/lucratividade — regime de competência, consistente com o
   resto do módulo).

## Arquitetura

### Backend — dois endpoints novos, mesmo módulo `financial_intelligence`

Ambos reaproveitam a convenção de sinal e o regime de competência já ratificados em
`profitability.py`/`dre.py` (Charge=+/Payable=−; `COALESCE(competence_date, due_date)`;
cancelados fora; `GROUP BY` no banco quando aplicável). Nenhum dos dois grava nada
(SOMENTE LEITURA, mesma garantia dos relatórios existentes).

#### 1. Ranking — `GET /financial-intelligence/contracts-dre?start&end&include_overhead=false`

```python
@dataclass
class ContractDreSummary:
    contract_id: str
    title: str
    client_name: str | None
    receita_cents: int
    custo_direto_cents: int
    margem_contribuicao_cents: int
    margem_contribuicao_pct: float | None
    overhead_allocated_cents: int
    resultado_cents: int

def contracts_dre_report(
    db: Session, *, start: date, end: date, include_overhead: bool = False
) -> list[ContractDreSummary]:
    """Lista TODOS os contratos status='signed' do tenant (reusa contracts.service.list_contracts
    com status='signed') e chama contract_dre(...) para cada um, no MESMO período. Contrato sem
    lançamento no período aparece com todos os campos zerados (não é filtrado). SOMENTE LEITURA,
    mesma garantia do contract_dre individual."""
```

Implementação: busca a lista de contratos assinados uma vez (`contracts.service.list_contracts`
já filtra por `status`), depois chama `contract_dre()` para cada um — server-side, uma única
requisição HTTP para N contratos (nunca N chamadas do frontend). `contract_dre()` já é barata (2
queries agregadas por contrato + o mapa de contas do plano); com um número razoável de contratos
por tenant isso é aceitável sem otimização adicional. Se o `account_map` (leitura de
`ChartAccount`) se mostrar redundante por chamada durante os testes de carga, é um refactor
interno trivial (parâmetro opcional pré-carregado) — não bloqueia a primeira versão.

O router expõe via `ContractDreSummaryOut` (Pydantic, espelhando o dataclass acima); ordenação
por margem fica no frontend (mesmo padrão de `buildDreView`/`buildContractDreView` — transformação
pura e testável, sem `@testing-library`).

#### 2. Ledger — `GET /financial-intelligence/contracts/{contract_id}/ledger?start&end`

```python
@dataclass
class LedgerEntry:
    id: str
    source: str          # "charge" | "payable"
    date: date            # COALESCE(competence_date, due_date) — mesma convenção do resto do módulo
    description: str
    categoria: str         # via chart_account_id -> ChartAccount.categoria; "Sem categoria" se não resolver
    status: str
    amount_cents: int      # JÁ assinado (Charge=+, Payable=−)

def contract_ledger(
    db: Session, *, contract: Contract, start: date, end: date
) -> list[LedgerEntry]:
    """Extrato cronológico (não agregado) dos lançamentos de UM contrato no período de
    competência: Charge (+ ) e Payable (−), cancelados fora, ordenado por `date` ascendente.
    NÃO inclui Transaction (sem contract_id — mesma exclusão do contract_dre). SOMENTE LEITURA."""
```

Implementação: duas queries `select(...)` (uma por tabela, sem `GROUP BY` — aqui queremos as
linhas individuais, não a soma) filtradas por `contract_id`, `competence BETWEEN start AND end`,
`status != canceled`; resolve `categoria` pelo mesmo `account_map` de `chart_account_id ->
categoria` usado em `profitability.py`; concatena as duas listas e ordena por `date` em Python
(lista pequena — um contrato, um período — sem necessidade de `UNION` no banco).

Contrato resolvido pelo router do mesmo jeito que o endpoint de DRE por contrato já faz hoje
(`contracts_service.get_contract`, 404 fail-closed se não existir/não for do tenant).

### Frontend

- **Período**: extraio o seletor de período (Este mês/Mês anterior/Este trimestre/Este ano/
  Últimos 12 meses/Tudo/Personalizado) construído para a matriz da DRE em um componente/hook
  compartilhado (`usePeriodRange` ou `<PeriodPicker>`, local a definir na implementação) —
  ambas as telas usam exatamente a mesma lógica de resolução de atalho → `{start, end}`.
- **`LucratividadePage.tsx`** (rota `/financeiro/lucratividade`, nova entrada de nav em
  "Análise & Configuração Financeira", ícone a escolher — ex. `BarChart3` ou `Percent`, distinto
  dos já usados):
  - Card de KPIs no topo: Receita Total, Custo Direto (somas simples de todas as linhas),
    Margem % Média (**ponderada**: `Σmargem_contribuicao_cents / Σreceita_cents`, não a média
    aritmética das porcentagens — evita que um contrato pequeno distorça a média), Overhead,
    Resultado (somas simples).
  - Checkbox "Ratear overhead da empresa" acima da tabela — liga/desliga `include_overhead` e
    refaz a query (recalcula Overhead e Resultado de todas as linhas).
  - Tabela ordenada por `margem_contribuicao_cents` descendente: Contrato (título + cliente),
    Receita, Custo Direto, Margem (R$), Margem %, Overhead, Resultado, botão "Detalhes".
- **`components/Drawer.tsx`** (novo — não existe padrão de slide-over hoje, só o `Modal.tsx`
  centralizado): painel ancorado à direita (`fixed inset-y-0 right-0`), mesmo modelo de
  open/onClose/clique-no-backdrop-fecha do `Modal.tsx`, mas deslizando da direita em vez de
  centralizado. Reutilizável por outras telas no futuro (não é single-use).
  - Conteúdo: título do contrato + período, lista cronológica dos `LedgerEntry` — data,
    descrição + categoria, badge de status (mesma paleta de cores já usada em Cobranças/Contas a
    Pagar para aberto/pago/cancelado/vencido), valor colorido (verde positivo / vermelho
    negativo via `formatBRL`).

## Fora de escopo (explicitamente)

- Não inclui `Transaction` (carteira) no ledger — limitação já existente no modelo de dados
  (sem `contract_id`); adicionar essa coluna seria uma migration nova, não pedida aqui.
- Não pagina o ledger nem o ranking — período típico (mês/trimestre/ano) e número de contratos
  por tenant não justificam paginação na primeira versão.
- Não adiciona edição/ação (marcar pago, editar lançamento) a partir do drawer — é somente
  leitura, mesmo padrão de toda a `financial_intelligence`.
- Não muda `ContratoDrePage.tsx` (tela de um contrato só) — continua existindo como está, o
  "Detalhes" do ranking abre o drawer novo, não essa página.

## Testes

- Backend: novos testes em `test_financial_intelligence_profitability.py` para
  `contracts_dre_report` (contrato signed sem lançamento aparece zerado; contrato draft/enviado/
  cancelado não aparece; `include_overhead` recalcula todas as linhas) e para `contract_ledger`
  (sinal correto por fonte, ordenação por data, cancelados fora, `Transaction` nunca aparece).
  RLS: espelha `test_financial_intelligence_profitability_rls.py` para os dois endpoints novos.
- Frontend: transformação pura testável (ex. `lucratividade.ts` + `.test.ts`) para ordenação por
  margem e cálculo da margem % média ponderada — mesmo padrão sem jsdom já usado em
  `dre.test.ts`/`contratoDre.test.ts`.
