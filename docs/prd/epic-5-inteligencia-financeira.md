# Epic 5: Inteligência Financeira

> **Classificação:** FEATURE NOVA (pós-go-live) — camada financeira analítica/diagnóstica.
> **Sequenciamento:** independente do go-live (Epics 1–4). Internamente ordenado por dependência de dados:
> plano de contas → 3 datas → relatórios (DRE/lucratividade/projeção/investimento) → diagnóstico → fila.
> Fonte: PRD [`prd-inteligencia-financeira.md`](./prd-inteligencia-financeira.md); design de referência `AxisGov/plataforma-gestao`; `CLAUDE.md` (sistema existente).

## Contexto do sistema existente (para o @sm)
O e1p é um SaaS multi-tenant white-label (FastAPI + PostgreSQL 16 com **Row-Level Security**; React + Vite; design "Portal", cor `#5D44F8`). Isolamento entre tenants é garantido **apenas** por RLS, com a app conectando como papel non-superuser `e1p_app` (superusuário faz bypass). Dinheiro é sempre em **centavos** (`BigInteger`).

O financeiro atual é **OPERACIONAL, não analítico**:
- **Carteira & Split** — transações com split 40/30/20 (produto/serviço/recorrência), saldos (disponível/a receber/sacado), settle, payout. `platform_earnings` global para o Master.
- **Contas a Receber** — cobranças (boleto/Pix/link), baixa via `POST /receivables/webhook` → cria Transaction na Carteira com split (atômico, lock `FOR UPDATE`), vencimento injetado na Agenda, resumo de inadimplência. Recorrência gera ocorrências (`recurrence_group`).
- **Contas a Pagar** — despesas (categoria em **texto livre**, fornecedor, recorrência), vencimento na Agenda, marcar paga (com lock), resumo. Cada ocorrência recorrente tem seu vencimento/boleto.
- **Cockpit** — agregador **read-only** (faturamento líquido do dia, custos do mês). Padrão: GET não semeia dados; janela do dia ancorada em meia-noite UTC (dívida de fuso conhecida).

**NÃO existe hoje:** plano de contas DRE, "projeto" como eixo financeiro, centro de custo, conta de investimento, projeção de caixa/runway, diagnóstico determinístico.

**Ativos a reusar (não recriar):**
- `core/ai` (Anthropic Claude) + **`core/anonymizer` (obrigatório antes de qualquer chamada à IA — Regra de Ouro nº 2)**.
- `core/events` (barramento pós-commit que isola exceções de assinantes).
- `components/Attachments.tsx` + módulo de Anexos (comprovantes).
- Padrão read-only do Cockpit (agregação sem efeito colateral de escrita).
- RBAC básico (`owner`/`sub_user` com `allowed_modules`).

## Epic Goal
Dar ao e1p a camada de **inteligência financeira** do produto irmão do fundador (`plataforma-gestao`): ver o resultado (DRE por categoria), a lucratividade por contrato, a saúde de caixa futura (projeção 30/60/90 + runway) e um **diagnóstico determinístico** (sinais 🟢🟡🔴 primeiro, IA narrando depois), além de conta de investimento, centro de custo e uma fila de pagamentos com visão consolidada do que vence hoje e nos próximos dias — **sem quebrar o financeiro operacional existente** nem o isolamento de tenant.

## Integration Requirements
Camada majoritariamente **aditiva e read-only** que agrega os lançamentos existentes e novos. Novas tabelas (plano de contas, centro de custo, conta de investimento) carregam `tenant_id` + **RLS** (Regra de Ouro nº 1); "projeto" (5.4) e a fila de pagamentos (5.9) **não** criam tabela nova — reusam `Contract` e `Payable` já existentes, respectivamente. As três datas e o vínculo de conta/contrato entram em Contas a Pagar/Receber como colunas **nullable + backfill** (não invalidam lançamentos legados). O motor de diagnóstico é **puro/sem I/O** (a fonte de verdade); a IA só narra os sinais já calculados, **sempre após o anonimizador**. Nenhum dos ~252 testes existentes pode quebrar; cada story roda `scripts/check.sh` + os 3 agentes de QA e traz testes novos + validação e2e de isolamento no Postgres real.

---

## Story 5.1 — Plano de contas hierárquico por grupo DRE
As a **dono da empresa de 1 pessoa**,
I want **um plano de contas hierárquico por grupo DRE (RECEITA, CUSTO_DIRETO, DESPESA_FIXA, TRIBUTOS, FINANCEIRO, INVESTIMENTO) com categorias livres dentro de cada grupo**,
so that **eu possa classificar cada lançamento e enxergar o resultado do negócio por categoria, não só o fluxo de caixa**.

### Acceptance Criteria
1. Existe uma entidade **plano de contas** (nova tabela com `tenant_id` + RLS) com `grupo_dre` restrito ao enum fixo (`RECEITA`, `CUSTO_DIRETO`, `DESPESA_FIXA`, `TRIBUTOS`, `FINANCEIRO`, `INVESTIMENTO`) e uma **categoria** livre (nome) dentro do grupo, única por tenant dentro do grupo.
2. CRUD por tenant (criar/listar/editar/arquivar categoria), com um conjunto-semente opcional de categorias comuns por grupo; arquivar não apaga histórico já classificado.
3. A hierarquia é exposta por endpoint (grupo → categorias) reusando o padrão de módulo do e1p; textos em PT-BR.

### Integration Verification
- IV1: Contas a Pagar/Receber continuam funcionando **sem** classificação obrigatória nesta story (a categoria em texto livre existente segue válida; o vínculo formal vem na 5.2) — nenhum fluxo operacional quebra.
- IV2: A nova tabela respeita RLS; teste e2e no Postgres real confirma que um tenant não vê o plano de contas de outro (João × Maria).
- IV3: Cockpit/Carteira/split inalterados; `scripts/check.sh` + os 3 agentes de QA passam.

## Story 5.2 — Classificação de lançamentos + três datas (competência/vencimento/pagamento)
As a **dono da empresa de 1 pessoa**,
I want **classificar cada conta a pagar/receber por uma conta do plano de contas e registrar três datas (competência, vencimento, pagamento)**,
so that **o fluxo de caixa use o pagamento (regime de caixa) e a DRE/lucratividade use a competência (regime de competência) — para que uma data não faça um dos dashboards mentir**.

### Acceptance Criteria
1. Contas a Pagar e a Receber ganham (migration aditiva, colunas **nullable**): vínculo a uma **conta do plano de contas** (FR1) e as datas de **competência** e **pagamento** (o `vencimento` já existe). A data de pagamento é preenchida quando a baixa acontece (webhook/mark-paid).
2. Lançamentos legados continuam válidos: a competência faz **backfill** a partir do vencimento (ou data de criação) e o vínculo de conta fica opcional/inferível; nenhum registro existente é invalidado.
3. Fica documentada a regra determinística: **fluxo de caixa = data de pagamento; DRE/lucratividade = data de competência** — e essa regra é a base das stories 5.3, 5.4 e 5.7.

### Integration Verification
- IV1: A baixa via `POST /receivables/webhook` e o "marcar paga" de Contas a Pagar continuam creditando a Carteira com split (lock `FOR UPDATE` intacto) e agora também gravam a data de pagamento — sem baixa dupla.
- IV2: Cockpit (faturamento do dia / custos do mês) continua batendo com os dados atuais; a agenda de vencimentos (all-day por data de calendário) não regride.
- IV3: RLS intacto; teste cross-tenant no Postgres real passa; os ~252 testes existentes continuam verdes.

## Story 5.3 — DRE por categoria
As a **dono da empresa de 1 pessoa**,
I want **um relatório de DRE por categoria (hierárquico: grupo DRE → categoria) por período**,
so that **eu veja receita, custos, despesas, tributos e resultado do negócio classificados, não só entradas e saídas de caixa**.

### Acceptance Criteria
1. Endpoint/serviço **read-only** que agrega os lançamentos classificados (5.1/5.2) por período em **regime de competência** (data de competência), somando por `grupo_dre` e por categoria, e calcula o resultado (Receita − Custos − Despesas − Tributos ± Financeiro).
2. A tela (feature em `apps/web/src/features/*`, design "Portal") mostra a DRE hierárquica com totais por grupo e drill nas categorias, valores em R$ (centavos formatados), período selecionável.
3. Lançamentos ainda não classificados aparecem num bucket "sem categoria" (não somem), incentivando a classificação sem travar o relatório.

### Integration Verification
- IV1: O relatório **não** escreve nada (padrão read-only do Cockpit) — nenhum efeito colateral sobre Carteira/Contas.
- IV2: Isolamento por tenant preservado (agregação sob RLS; teste cross-tenant no Postgres real).
- IV3: Cockpit e os dashboards operacionais existentes continuam funcionando; testes novos cobrem a soma por grupo/categoria.

## Story 5.4 — Lucratividade por projeto (margem de contribuição, break-even)
As a **dono da empresa de 1 pessoa**,
I want **um "projeto" como eixo financeiro e a DRE do projeto (Receita → Custo Direto → Margem de Contribuição R$/% → resultado) com break-even**,
so that **eu saiba quais projetos dão lucro de verdade, com o overhead da empresa rateado só na análise, nunca no lançamento**.

### Acceptance Criteria
1. Existe a entidade **projeto** (nova tabela com `tenant_id` + RLS); lançamentos de Contas a Pagar/Receber podem ser vinculados a um projeto (campo nullable — quem não usa não é obrigado). Há um bucket implícito "Empresa" para o que não é de projeto (overhead).
2. Serviço read-only calcula a **DRE do projeto** em regime de competência: Receita → Custo Direto → **Margem de Contribuição** (R$ e %) → resultado; e o **break-even** (ponto em que a margem cobre os custos fixos atribuídos).
3. O **rateio de overhead** do bucket "Empresa" aparece **só na visão analítica** (opcional, por critério configurável) e **nunca** é gravado no lançamento original.

### Integration Verification
- IV1: Lançamentos sem projeto continuam funcionando normalmente (Cockpit/Contas inalterados); o vínculo é aditivo/nullable.
- IV2: O rateio não altera nenhum dado persistido — é calculado na leitura; verificável comparando o lançamento antes/depois (idêntico).
- IV3: RLS por tenant nas tabelas de projeto e nas queries; teste cross-tenant no Postgres real passa.

## Story 5.5 — Centro de custo como 2ª dimensão de análise
As a **dono da empresa de 1 pessoa**,
I want **um centro de custo opcional (2ª dimensão) por lançamento, cruzável por sócio/área/unidade**,
so that **eu analise o financeiro por uma segunda ótica sem obrigar quem não usa a preencher**.

### Acceptance Criteria
1. Existe a entidade **centro de custo** (nova tabela com `tenant_id` + RLS); Contas a Pagar/Receber ganham um campo **nullable** de centro de custo (migration aditiva).
2. Os relatórios (DRE 5.3, lucratividade 5.4) podem ser **filtrados/cruzados** por centro de custo como 2ª dimensão, sem quebrar a visão padrão (sem centro de custo).
3. Lançamentos sem centro de custo aparecem como "não atribuído"; a dimensão é sempre opcional.

### Integration Verification
- IV1: Fluxos existentes (criar conta a pagar/receber) funcionam sem informar centro de custo — campo opcional, nenhum fluxo quebra.
- IV2: O cruzamento por centro de custo respeita RLS (não cruza tenants); teste cross-tenant no Postgres real.
- IV3: Cockpit e os relatórios sem a 2ª dimensão continuam idênticos; testes cobrem o filtro por centro de custo.

## Story 5.6 — Conta de investimento (rendimento, rentabilidade)
As a **dono da empresa de 1 pessoa**,
I want **registrar contas de investimento (principal aplicado, rendimento acumulado, tipo de aplicação, indexador/taxa) com o juro entrando como receita financeira**,
so that **eu acompanhe a rentabilidade das aplicações dentro do mesmo painel financeiro**.

### Acceptance Criteria
1. Existe a entidade **conta de investimento** (nova tabela com `tenant_id` + RLS) com: principal aplicado, rendimento acumulado, tipo de aplicação e indexador/taxa. Valores em centavos.
2. O **rendimento (juro) da aplicação é registrado como lançamento de receita no grupo `FINANCEIRO`** (integra com o plano de contas 5.1 e entra na DRE 5.3), preservando a coerência do regime de competência.
3. A conta expõe a **rentabilidade** (rendimento sobre o principal, e no período), exibida na tela financeira (design "Portal").

### Integration Verification
- IV1: A criação de receita financeira do rendimento reusa o caminho de lançamento existente sem afetar Carteira/split de vendas (é receita financeira, não venda com split de plataforma) — comportamento documentado e coberto por teste.
- IV2: RLS na tabela de investimento e nas queries de rentabilidade; teste cross-tenant no Postgres real.
- IV3: Cockpit/DRE continuam batendo com o rendimento incluído no grupo FINANCEIRO; nenhum teste existente quebra.

## Story 5.7 — Projeção de fluxo de caixa 30/60/90 dias + runway
As a **dono da empresa de 1 pessoa**,
I want **uma projeção de fluxo de caixa para 30/60/90 dias e o runway**,
so that **eu saiba se e quando o caixa aperta e possa agir antes, em regime de caixa**.

### Acceptance Criteria
1. Serviço read-only projeta o **saldo de caixa** para 30/60/90 dias a partir das contas a pagar/receber futuras, usando a **data de pagamento prevista** (regime de caixa — FR2/5.2), partindo do saldo disponível atual da Carteira.
2. Calcula e exibe o **runway** (meses/dias até o caixa acabar no ritmo atual — burn), com sinal claro quando a projeção fica negativa em alguma janela.
3. A tela (design "Portal") mostra as três janelas e o runway; recorrências futuras (`recurrence_group`) entram na projeção.

### Integration Verification
- IV1: A projeção é **read-only** (não escreve; não cria contas) — Carteira/Contas inalteradas.
- IV2: Usa a data de **pagamento** (caixa), nunca a de competência — coberto por teste que compara os dois regimes.
- IV3: RLS por tenant na agregação; teste cross-tenant no Postgres real; ~252 testes seguem verdes.

## Story 5.8 — Motor de diagnóstico determinístico + narrativa por IA
As a **dono da empresa de 1 pessoa**,
I want **sinais de diagnóstico financeiro determinísticos (🟢🟡🔴) calculados por um motor puro e testável, e só depois uma narrativa em linguagem natural pela IA**,
so that **eu confie nos alertas (números sólidos primeiro) e a IA apenas explique o que já é verdade, nunca inventando dados**.

### Acceptance Criteria
1. Existe um **motor de indicadores puro (sem I/O), determinístico e coberto por testes unitários** que consome os dados classificados (DRE 5.3, lucratividade 5.4, projeção 5.7, investimento 5.6) e emite **sinais priorizados 🟢🟡🔴** com explicação **numérica** (ex.: "Projeto X: margem 28%→16% em 2 meses", "Runway < 60 dias").
2. Os sinais existem e estão corretos **independentemente da IA** (sem `ANTHROPIC_API_KEY`, o diagnóstico ainda entrega 🟢🟡🔴 — só a narrativa vira fallback/template) — o princípio "regra determinística primeiro, IA narrando depois".
3. Um `LLMProvider` separado recebe os sinais **já calculados** e narra em PT-BR via `core/ai`, **após passar pelo `core/anonymizer`** (nomes de projeto/contraparte anonimizados, mesmo em KPIs agregados — Regra de Ouro nº 2); a narrativa grava rastro "Ação executada pela IA" (Regra de Ouro nº 3).

### Integration Verification
- IV1: A IA **nunca** origina números — teste garante que os sinais são idênticos com e sem IA (a IA só reformula texto); nenhum dado é inventado.
- IV2: Nenhum PII vai ao Claude sem anonimização (teste verifica que o texto enviado passou pelo anonimizador); a desanonimização acontece localmente na volta.
- IV3: Sem chave de IA, o módulo não quebra (graceful degradation); RLS intacto nas leituras que alimentam o motor; teste cross-tenant no Postgres real.

## Story 5.9 — Fila de Pagamentos (hoje + próximos dias, sem papéis)
> **Redefinida em 2026-07-10 pelo fundador.** O design original do `plataforma-gestao` usa papéis (solicitante/pagador/admin/visualizador) porque lá várias pessoas cuidam do caixa de várias empresas. No e1p (empresa de 1 pessoa) isso não se aplica — o pedido real é apenas **enxergar num só lugar o que vence hoje e nos próximos dias, já agendado (recorrência existente), e baixar (marcar pago) rápido**. Esta story substitui o desenho anterior (ciclo solicitado→pago→comprovado com 4 papéis e ADR de RBAC) por uma versão sem papéis, que reusa o que já existe em vez de introduzir um segundo mecanismo de autorização.

As a **dono da empresa de 1 pessoa**,
I want **um painel único que mostra o que tenho a pagar hoje e nos próximos dias (já agendado pela recorrência existente), com baixa rápida em um clique**,
so that **eu não precise caçar vencimentos espalhados entre Contas a Pagar e a Agenda — vejo tudo junto e registro o pagamento sem fricção**.

### Acceptance Criteria
1. Existe um endpoint/tela de **fila de pagamentos** que lista `Payable`s em aberto ordenados por `due_date`, agrupados em **Hoje / Próximos 7 dias / Próximos 30 dias / Atrasados** (reaproveita os dados que já existem — nenhuma tabela nova; `Payable` + recorrência já geram as ocorrências futuras com seus próprios vencimentos, conforme `CLAUDE.md` §"Financeiro: recorrência + nome do cliente na agenda").
2. Cada item da fila permite **marcar como pago em um clique** direto da lista (reaproveita `payables.mark_paid` já existente — mesmo lock `FOR UPDATE`), sem sair da tela e sem fluxo de aprovação separado.
3. **Sem papéis novos.** Qualquer usuário com acesso ao módulo financeiro (RBAC/`allowed_modules` já existente, camada única e inalterada) pode ver e marcar como pago — não há solicitante/pagador/admin/visualizador, nem ADR de autorização a produzir. `paid_by`/timestamp de quem marcou como pago continuam sendo registrados (auditoria mínima já coberta pelo padrão de log existente), mas sem gate de permissão por ação.

### Integration Verification
- IV1: A fila é uma **visão nova sobre dados existentes** (`Payable`) — não cria fluxo paralelo a Contas a Pagar nem duplica o "marcar paga" atual; ambas as telas continuam consistentes (marcar pago em uma reflete na outra).
- IV2: RLS/isolamento de tenant existente preservado (sem tabela nova, sem camada de autorização nova); teste cross-tenant no Postgres real confirma que a fila de um tenant não mostra `Payable`s de outro.
- IV3: `scripts/check.sh` + os 3 agentes de QA passam; nenhum teste existente quebra (Cockpit, Contas a Pagar, Agenda).
</content>
