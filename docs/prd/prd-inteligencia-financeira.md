# e1p — Brownfield PRD — Inteligência Financeira & Robustez de Plataforma

> **Tipo:** Brownfield Enhancement PRD (features NOVAS de produto — camada financeira analítica + robustez de plataforma).
> **Escopo:** portar o *design* (não o código) de um conjunto de recursos financeiros e de plataforma do produto irmão do fundador (`AxisGov/plataforma-gestao`, sistema financeiro multi-empresa em produção) para dentro do e1p.
> **Autor:** Morgan (@pm). **Modo de execução:** YOLO (autônomo — premissas documentadas na seção final).
> **Data:** 2026-07-10.
> **Relação com `docs/prd.md`:** SEPARADO. O `docs/prd.md` é o PRD de go-live e está explicitamente escopado a "só o caminho até o go-live, sem features novas de produto". O que este PRD planeja SÃO features novas de produto — por isso ganha PRD próprio e epics numerados a partir do próximo livre (5, 6).

---

## 1. Intro Project Analysis and Context

### 1.1 Analysis Source
Análise fresca baseada em documentação do repositório (IDE-based) + comparação explícita pedida pelo fundador:
- `CLAUDE.md` (memória viva do e1p — Fases 1–5, dívida técnica) — **material primário do sistema existente**.
- `docs/prd.md` (PRD de go-live) — para NÃO sobrepor escopo (aquele é go-live; este é feature nova).
- **Análise comparativa e1p × `AxisGov/plataforma-gestao`** (o produto financeiro multi-empresa do próprio fundador, Next.js 15 + Supabase) — **fonte do "portar" (design, não código)**. Foi esse comparativo que originou o pedido: o financeiro do e1p hoje é **operacional** (dinheiro entra/sai), enquanto o plataforma-gestao tem uma camada **analítica/diagnóstica** (DRE, lucratividade por projeto, projeção de caixa, diagnóstico determinístico) que o e1p ainda não tem.

> **Nota de rastreabilidade (Constitution Art. IV — No Invention):** todo requisito abaixo rastreia a uma de três fontes reais: **(a)** o pedido literal do fundador (9 itens), **(b)** o `CLAUDE.md` do e1p (sistema existente), ou **(c)** o design de referência do `plataforma-gestao` fornecido na especificação da iniciativa. Nada foi inventado sem justificativa.

### 1.2 Current Project State (financeiro do e1p hoje)
O e1p é um SaaS multi-tenant white-label (FastAPI + PostgreSQL 16 com RLS; React + Vite; design "Portal") para profissionais autônomos, com IA (Claude) como funcionário invisível e split de pagamento (40/30/20). O financeiro atual é **OPERACIONAL, não analítico**:
- **Carteira & Split** — transações com split 40/30/20, saldos (disponível/a receber/sacado), settle, payout. Dinheiro em centavos (`BigInteger`).
- **Contas a Receber** — cobranças (boleto/Pix/link), baixa via webhook → Transaction na Carteira com split, vencimento na Agenda, resumo de inadimplência.
- **Contas a Pagar** — despesas (categoria livre em texto, fornecedor, recorrência), vencimento na Agenda, marcar paga, resumo.
- **Cockpit** — agregador read-only (faturamento líquido do dia, custos do mês).

**NÃO existe hoje** (lacunas que motivam este PRD): plano de contas DRE hierárquico; conceito de "projeto" como eixo financeiro; centro de custo; conta de investimento; projeção de caixa futura/runway; motor de diagnóstico financeiro determinístico.

**Ativos reusáveis já no e1p** (não recriar — estender):
- `core/storage.py` — storage S3-compatível com dual-write/fallback gracioso (Postgres↔S3). A varredura de órfãos DEVE reusar esta camada.
- `core/ai` (Anthropic Claude) + `core/anonymizer.py` — **anonimizador obrigatório antes de qualquer chamada à IA** (Regra de Ouro nº 2).
- RBAC básico (`owner`/`sub_user` com `allowed_modules`) — a Fila de Pagamentos (FR9) usa exatamente este mecanismo, sem estendê-lo (não há papéis financeiros próprios).
- RLS (Postgres, papel non-superuser `e1p_app`) — Regra de Ouro nº 1, vale para todo dado financeiro novo.
- `.github/workflows/ci.yml` — CI já existente (Story 3.2 do go-live: builda a imagem de produção, roda ruff+pytest dentro dela, e o e2e de isolamento RLS). O scan de segredo/SAST **estende este CI**, não cria do zero.

### 1.3 Enhancement Scope Definition

#### Enhancement Type
- [x] **New Feature Addition** — camada financeira analítica/diagnóstica inexistente (DRE, lucratividade por contrato, projeção de caixa, diagnóstico determinístico, conta de investimento, fila de pagamentos consolidada).
- [x] **Platform Robustness** — higiene de storage (varredura de órfãos) e segurança de CI (secret scan + SAST).

#### Enhancement Description
Portar (design, não código) do `plataforma-gestao` uma camada de **inteligência financeira** para o e1p: plano de contas hierárquico por grupo DRE, classificação dos lançamentos existentes por regime de competência vs caixa (três datas), DRE por categoria, lucratividade por projeto (margem de contribuição / break-even), centro de custo como 2ª dimensão, conta de investimento, projeção de fluxo de caixa 30/60/90 + runway e um **motor de diagnóstico determinístico** (sinais 🟢🟡🔴 primeiro, IA narrando depois). Em paralelo, dois recursos de **plataforma**: a rotina de varredura de órfãos no storage e o scan de segredo (gitleaks) + SAST (semgrep) no CI.

#### Impact Assessment — Classificação de risco de integração
- [x] **Moderate to Significant Impact.** A maior parte da inteligência financeira é **aditiva** (uma camada analítica que LÊ os dados operacionais existentes e novos, sem reescrever Carteira/split). Dois pontos exigem tocar dados existentes com **risco controlado**:
  1. **Três datas nos lançamentos** (FR2) — Contas a Pagar/Receber hoje têm `vencimento`; adicionar `competência` e `pagamento` + vínculo ao plano de contas é migração aditiva, mas os dashboards financeiros existentes (Cockpit) precisam continuar batendo.
  2. ~~**Fila auditável com papéis** (FR9)~~ — **redefinido**: a Fila de Pagamentos (FR9) não toca autorização — usa o RBAC (`allowed_modules`) já existente sem estendê-lo. Risco rebaixado a **baixo** (é uma agregação read-only sobre `Payable` + reuso do `mark_paid` já existente).
  Nenhuma mudança arquitetural de fundo — RLS, anonimizador e conteinerização permanecem. Os itens de plataforma (varredura de órfãos, CI) são **isolados e reversíveis** (a varredura é dry-run por padrão; o CI só adiciona jobs).

### 1.4 Goals
- Dar ao e1p a mesma **inteligência financeira** do produto irmão do fundador: enxergar resultado (DRE), lucratividade por projeto, saúde de caixa futura e diagnóstico automático — sem copiar código, só o design.
- Estabelecer o princípio de produto central: **regra determinística primeiro, IA narrando depois** — sinais confiáveis (🟢🟡🔴) calculados por um motor puro/testável; a IA só explica números que o motor já garantiu (nunca inventa).
- Trazer uma **Fila de Pagamentos** que consolida o que vence hoje e nos próximos dias num só lugar, com baixa em um clique — sem burocracia de papéis, adequado a uma empresa de 1 pessoa.
- Endurecer a **plataforma**: manter o object storage limpo (varredura de órfãos) e proteger o pipeline contra segredos vazados e vulnerabilidades (gitleaks + semgrep no CI).
- Fazer tudo **sem quebrar o financeiro operacional já existente** (Carteira/split, Contas a Pagar/Receber, Cockpit) nem o isolamento de tenant (Regra de Ouro nº 1 e nº 5).

### 1.5 Background Context
O fundador (Flávio) comparou o e1p com seu outro produto em produção (`AxisGov/plataforma-gestao`) e pediu para portar — só o design — um conjunto de recursos financeiros e de plataforma. O `plataforma-gestao` resolveu, com um plano de contas por `grupo_dre` e um motor de indicadores puro, o problema de "ver o resultado do negócio", não só o fluxo de dinheiro. O e1p tem a fundação (dados operacionais em centavos, RLS, `core/ai` com anonimizador, `core/storage`), mas ainda não tem a camada que transforma esses dados em **decisão**. Este PRD organiza esse porte respeitando as Regras de Ouro do `CLAUDE.md`.

### 1.6 Change Log
| Change | Date | Version | Description | Author |
|---|---|---|---|---|
| Criação | 2026-07-10 | 1.0 | PRD brownfield de inteligência financeira + robustez de plataforma, derivado do comparativo e1p × plataforma-gestao e do pedido do fundador | Morgan (@pm) |
| Revisão | 2026-07-10 | 1.1 | Duas ambiguidades resolvidas pelo fundador: (1) FR4 — "projeto" = `Contract` existente, não tabela nova; (2) FR9 — Fila de Pagamentos redefinida sem papéis (painel hoje/7/30 dias sobre `Payable` existente, sem RBAC novo). Impact Assessment, CR4, §4.2 e §5 atualizados em conjunto. Aplicado por Orion (@aiox-master) em execução direta (sessão do @pm/@sm limitada no momento). | Orion (@aiox-master) |

---

## 2. Requirements

> Cada requisito traz a fonte entre colchetes: **[user]** = pedido do fundador; **[e1p]** = `CLAUDE.md`; **[ref]** = design do `plataforma-gestao`.

### 2.1 Functional

- **FR1 [user·item1 / ref]:** Plano de contas **hierárquico** por `grupo_dre` (enum fixo: `RECEITA`, `CUSTO_DIRETO`, `DESPESA_FIXA`, `TRIBUTOS`, `FINANCEIRO`, `INVESTIMENTO`) + **categoria livre** dentro do grupo, por tenant.
- **FR2 [ref·enabler]:** Lançamento financeiro classificado por **conta do plano de contas** e com **três datas** — competência, vencimento e pagamento. O fluxo de caixa usa a data de **pagamento** (regime de caixa); a lucratividade/DRE usa a data de **competência** (regime de competência). Aplicado estendendo Contas a Pagar/Receber existentes (migração aditiva) sem quebrar os dashboards atuais.
- **FR3 [user·item1]:** **DRE por categoria** — relatório hierárquico (grupo → categoria) por período, em regime de competência, somando os lançamentos classificados.
- **FR4 [user·item5 / ref, redefinido pelo fundador 2026-07-10]:** **Lucratividade por contrato** — o `Contract` já existente é o eixo financeiro ("projeto"), sem tabela nova; DRE do contrato (Receita → Custo Direto → **Margem de Contribuição** R$ e %) → resultado; **break-even**; rateio de overhead do bucket "Empresa" **só na visão analítica** (nunca gravado no lançamento).
- **FR5 [user·item6 / ref]:** **Centro de custo** como **2ª dimensão nullable** de análise (cruza por sócio/área/unidade), sem obrigar quem não usa a preencher.
- **FR6 [user·item7 / ref]:** **Conta de investimento** com principal aplicado, rendimento acumulado, tipo de aplicação e indexador/taxa; o juro de aplicação é lançamento de **receita no grupo FINANCEIRO**; expõe rentabilidade.
- **FR7 [user·item2 / ref]:** **Projeção de fluxo de caixa 30/60/90 dias + runway** — em regime de caixa (data de pagamento prevista de contas a pagar/receber futuras), projetando saldo e informando o runway (meses/dias até o caixa acabar no ritmo atual).
- **FR8 [user·item3 / ref]:** **Motor de diagnóstico financeiro determinístico** — módulo **puro/testável (sem I/O)** que gera **sinais determinísticos priorizados 🟢🟡🔴** com explicação numérica (ex.: "Projeto X: margem 28%→16% em 2 meses"). **Só depois** um `LLMProvider` narra os sinais em linguagem natural. A IA **explica números confiáveis, nunca os inventa** — é o princípio central ("regra determinística primeiro, IA narrando depois").
- **FR9 [user·item4, redefinido pelo fundador 2026-07-10]:** **Fila de Pagamentos** — painel consolidado do que vence **hoje e nos próximos dias** (agrupado por janela: atrasados/hoje/7 dias/30 dias), com **baixa em um clique** direto da fila. Reusa `Payable` e `mark_paid` já existentes — **sem papéis** (o design original do `plataforma-gestao`, com solicitante/pagador/admin/visualizador, foi descartado pelo fundador por não corresponder a uma necessidade real de uma empresa de 1 pessoa) e sem tabela nova.
- **FR10 [user·item8 / e1p]:** **Rotina de varredura de órfãos no storage** — CLI que remove objetos do object storage sem referência viva no banco; **dry-run por padrão**, `--apply` para remover de fato, **filtro por idade** (dias). Reusa `core/storage.py` e o padrão de fallback gracioso.
- **FR11 [user·item9 / e1p]:** **Scan de segredo (gitleaks)** no diff do PR + **SAST (semgrep)** (TS/JS/React/OWASP) no CI, **estendendo** o `.github/workflows/ci.yml` existente (que já roda lint/typecheck/testes na imagem de produção + isolamento RLS).

### 2.2 Non Functional

- **NFR1 [e1p·Regra nº1]:** Todo dado financeiro novo carrega `tenant_id` e política **RLS**; a app segue conectando como papel non-superuser `e1p_app`. Nenhuma query analítica pode cruzar tenants. Nenhuma regressão de isolamento é aceitável.
- **NFR2 [e1p·Regra nº2]:** A narrativa de IA sobre o diagnóstico **DEVE passar pelo anonimizador** (`core/anonymizer`) se tocar dados de cliente/parte (nome de projeto, contraparte), mesmo que o diagnóstico em si seja sobre KPIs agregados. Nenhum PII vai ao Claude sem anonimização.
- **NFR3 [user·item3 / ref]:** O motor determinístico é **puro (sem I/O), determinístico e coberto por testes unitários**; os sinais 🟢🟡🔴 existem e são corretos **independentemente da IA estar disponível**. A IA é uma camada de narração posterior e opcional — **regra sólida primeiro, IA depois**, nunca o contrário.
- **NFR4 [e1p·Regra nº5]:** Não quebrar o financeiro operacional existente — Carteira & Split (40/30/20), Contas a Pagar/Receber, Cockpit — nem os ~252 testes atuais. Cada mudança roda `scripts/check.sh` + os 3 agentes de QA (regression/bug-hunter/dedup) e vem com testes novos.
- **NFR5 [e1p·Regra nº4]:** Custo no alvo do projeto — soluções baratas; o diagnóstico prioriza cálculo local (motor) e só chama a IA para narrar (economia de tokens); sem serviço pago novo sem justificar.
- **NFR6 [ref]:** **Graceful degradation** — sem `ANTHROPIC_API_KEY`, o diagnóstico ainda entrega os sinais determinísticos (só a narrativa vira um fallback/template); a varredura de órfãos sem `S3_BUCKET` configurado opera sobre o storage vigente sem quebrar (mesmo padrão dual-write/fallback do `core/storage`).
- **NFR7 [ref]:** **Rastro da IA** (Regra de Ouro nº 3) — toda narrativa gerada por IA sobre o diagnóstico grava log "Ação executada pela IA" (autor + timestamp).

### 2.3 Compatibility Requirements

- **CR1 (API):** Endpoints e o contrato `packages/shared-types` permanecem retrocompatíveis. A camada financeira analítica adiciona endpoints/campos **aditivos**; nada remove ou altera contrato dos endpoints operacionais existentes (Carteira, Contas a Pagar/Receber, Cockpit).
- **CR2 (DB schema):** Novas colunas/tabelas apenas via **migrations Alembic aditivas** (próximas na sequência), sem mudança destrutiva nos dados de tenant existentes; **toda nova tabela de negócio carrega `tenant_id` + RLS**. As colunas novas de data (competência/pagamento) e o vínculo ao plano de contas nascem **nullable/backfill** para não invalidar lançamentos legados.
- **CR3 (UI/UX):** Design "Portal" (cor `#5D44F8`, sidebar, layout) preservado; novas telas (DRE, lucratividade por projeto, projeção de caixa, diagnóstico, fila de pagamentos) reusam padrões existentes (Cockpit, cards, `Collapsible`, `components/Attachments.tsx` para comprovantes). Textos em PT-BR.
- **CR4 (integração):** Reuso obrigatório de ativos existentes: `core/storage.py` (varredura de órfãos), `core/ai` + `core/anonymizer` (narrativa do diagnóstico), o padrão de eventos `core/events`, o RBAC existente **inalterado** (a Fila de Pagamentos usa `allowed_modules` como está, sem papéis novos) e o `Contract` existente (eixo de lucratividade, FR4). O CI **estende** `.github/workflows/ci.yml`, não o substitui.

---

## 3. Technical Constraints and Integration Requirements

### 3.1 Existing Technology Stack
Python 3.13 / FastAPI / SQLAlchemy 2 + Alembic / PostgreSQL 16 com RLS (backend). React 18 + Vite + TS + Tailwind, design "Portal" (frontend). Anthropic SDK (`claude-opus-4-8`) com anonimizador. Object storage S3-compatível via `core/storage.py`. 100% conteinerizado. Dinheiro sempre em **centavos** (`BigInteger`).

### 3.2 Integration Approach
- **DB:** migrations aditivas; plano de contas, projeto financeiro, centro de custo, conta de investimento e fila de pagamentos como **novas tabelas com `tenant_id` + RLS**; três datas + FK de conta adicionadas a Contas a Pagar/Receber como colunas nullable com backfill.
- **Camada analítica:** serviços de leitura (DRE, lucratividade, projeção) que **agregam** os lançamentos — sem efeito colateral de escrita (padrão read-only do Cockpit). O rateio de overhead vive **só** na visão analítica.
- **Motor de diagnóstico:** módulo puro em `apps/api/app/modules/<financeiro-analitico>/engine.py` (sem I/O), testável isoladamente; um `LLMProvider` separado consome a saída do motor e narra (via `core/ai`, após `core/anonymizer`).
- **Plataforma:** varredura de órfãos como script CLI (`python -m app.scripts.*`) reusando `core/storage`; CI estende o `ci.yml`.

### 3.3 Code Organization
Um módulo de negócio = uma pasta em `apps/api/app/modules/` + uma em `apps/web/src/features/` (convenção §8 do `CLAUDE.md`). Código/identificadores em inglês; domínio/UI em PT-BR. Conventional Commits; branch a partir de `main`.

### 3.4 Risk Assessment and Mitigation
**Technical risks:**
- **Dashboards mentindo por data errada** — se a projeção de caixa usar competência ou a DRE usar pagamento, o número engana. *Mitigação:* FR2 fixa a regra (caixa=pagamento, competência=competência) e cada relatório declara seu regime; testes cobrem os dois eixos.
- **Regressão no Cockpit/Carteira** ao adicionar as 3 datas e o vínculo de conta. *Mitigação:* colunas nullable + backfill; IV em toda story afirmando que Cockpit/Carteira/Contas continuam batendo.
- **IA inventando número** — o risco que o princípio central existe para eliminar. *Mitigação:* motor determinístico é a fonte de verdade; a IA recebe os sinais já calculados e só narra; teste garante sinais sem IA.
- **PII vazando na narrativa** — nome de projeto/contraparte indo ao Claude. *Mitigação:* NFR2 força o anonimizador mesmo em diagnóstico agregado.
- **Vazamento cross-tenant** nas novas queries analíticas. *Mitigação:* RLS em toda tabela nova; teste de isolamento e2e no Postgres real.
- **Varredura apagando anexo vivo** (falso órfão). *Mitigação:* dry-run por padrão, `--apply` explícito, filtro por idade, e a definição de "vivo" cruza TODAS as tabelas que referenciam storage.
- **CI ruidoso** (gitleaks/semgrep com falsos positivos travando merges). *Mitigação:* baseline/allowlist versionada; semgrep em conjunto de regras curado (OWASP + TS/React); começar como gate observável antes de bloqueante.

**Integration risks:** o motor de diagnóstico depende dos dados classificados (FR1/FR2) existirem — por isso o sequenciamento coloca plano de contas e 3 datas antes do diagnóstico.

---

## 4. Epic and Story Structure

### 4.1 Epic Structure Decision — **DOIS epics** (justificado)
Decisão do PM: **dividir em 2 epics temáticos coesos**, seguindo a convenção já estabelecida no projeto (os Epics 1–4 do go-live são organizados por tema coeso: Segurança, Integrações, Deploy/Storage/Obs, Backlog).

- **Epic 5 — Inteligência Financeira** (itens 1–7): domínio financeiro analítico/diagnóstico. Competência: domínio financeiro + IA. Coeso: tudo gira em torno de "ver e diagnosticar o resultado do negócio", com forte dependência interna (o diagnóstico e a projeção dependem do plano de contas e das 3 datas).
- **Epic 6 — Robustez de Plataforma: Higiene de Storage & Segurança de CI** (itens 8–9): **não** são domínio financeiro — são plataforma/infra/CI. Competência: devops/plataforma. Misturá-los ao financeiro criaria um epic incoerente e com dois donos. Tematicamente eles seriam próximos do Epic 3 (Deploy/Storage/Obs) do go-live, mas aquele pertence ao PRD de go-live (que não devo editar) — logo, ganham um epic próprio aqui.

**Rationale:** manter a coesão temática por epic (como os 4 existentes) melhora o sequenciamento, o ownership e a leitura do @sm. Um epic único de 11 stories misturando domínio financeiro com CI/storage seria difícil de sequenciar e atribuir.

**Sequenciamento recomendado:** Epic 5 primeiro (entrega o valor de produto pedido; internamente ordenado por dependência: plano de contas → 3 datas → relatórios → diagnóstico → fila). Epic 6 é **independente** e pode correr em paralelo (não depende do financeiro).

### 4.2 Cobertura dos 9 itens pedidos (rastreabilidade)
| # | Item pedido | FR | Epic · Story |
|---|---|---|---|
| 1 | DRE por categoria (plano de contas hierárquico) | FR1, FR3 | Epic 5 · 5.1, 5.3 |
| 2 | Projeção de fluxo de caixa 30/60/90 + runway | FR7 | Epic 5 · 5.7 |
| 3 | Regra determinística primeiro, IA narrando depois | FR8 | Epic 5 · 5.8 |
| 4 | Fila de Pagamentos (hoje + próximos dias, sem papéis — redefinido pelo fundador) | FR9 | Epic 5 · 5.9 |
| 5 | Lucratividade por contrato (margem, break-even) | FR4 | Epic 5 · 5.4 |
| 6 | Centro de custo como 2ª dimensão | FR5 | Epic 5 · 5.5 |
| 7 | Conta de investimento (rendimento, rentabilidade) | FR6 | Epic 5 · 5.6 |
| 8 | Varredura de órfãos no storage | FR10 | Epic 6 · 6.1 |
| 9 | Gitleaks (secret scan) + semgrep (SAST) no CI | FR11 | Epic 6 · 6.2 |
| — | Enabler: 3 datas (competência/vencimento/pagamento) | FR2 | Epic 5 · 5.2 |

**Epics detalhados (stories completas embutidas):** [`epic-5-inteligencia-financeira.md`](./epic-5-inteligencia-financeira.md) e [`epic-6-robustez-plataforma.md`](./epic-6-robustez-plataforma.md).

---

## 5. Premissas e decisões do PM (modo YOLO — sem elicitação interativa)

- **[AUTO-DECISION] Dividir em 2 epics (Inteligência Financeira + Robustez de Plataforma)** em vez de 1. *Motivo:* coesão temática (convenção dos Epics 1–4), donos/competências distintas (financeiro vs plataforma/CI) e independência de sequenciamento. *Risco:* baixo — a divisão espelha a organização já validada do projeto.
- **[AUTO-DECISION] Incluir a "regra das 3 datas" (FR2) como story própria (enabler), embora não seja um dos 9 itens numerados.** *Motivo:* é o alicerce do design de referência ("uma data só faz um dos dois dashboards mentir") e sem ela a DRE (competência) e a projeção de caixa (pagamento) não podem coexistir sem enganar. Rastreia à fonte **[ref]**, não é invenção. *Risco:* controlado — toca Contas a Pagar/Receber existentes; mitigado por colunas nullable + backfill.
- **[AUTO-DECISION] Fila de Pagamentos fica no Epic 5 (financeiro), não na plataforma.** *Motivo:* é uma visão sobre dados de domínio financeiro (`Payable`).
- **[RESOLVIDO PELO FUNDADOR, 2026-07-10] Fila de Pagamentos redefinida sem papéis.** O desenho original (herdado do `plataforma-gestao`: solicitante/pagador/admin/visualizador + ADR de RBAC) foi **descartado**. Decisão do fundador: "na prática o que precisamos é saber o que temos a pagar no dia e nos próximos dias, para deixar já tudo agendado no banco e baixado no sistema — não precisa ser esse modelo de solicitante/pagador, porque de qualquer forma estamos falando de empresa de 1 pessoa." FR9, Epic 5 (Story 5.9) e a story formal (`docs/stories/5.9.story.md`) foram atualizados: painel consolidado hoje/7 dias/30 dias/atrasados sobre `Payable` já existente, baixa em um clique via `mark_paid` já existente, RBAC (`allowed_modules`) inalterado. **Não há mais ADR a produzir nem decisão em aberto para esta story.**
- **[AUTO-DECISION] O scan de segredo/SAST estende o `ci.yml` existente, não cria um novo pipeline.** *Motivo:* o CI já existe (Story 3.2 do go-live). Começar como gate observável e endurecer para bloqueante depois (via branch protection, follow-up @devops), evitando travar merges com falso positivo no dia 1.
- **[AUTO-DECISION] `document-project` não foi executada.** *Motivo:* `CLAUDE.md` + o design de referência dão cobertura suficiente para este PRD focado.

### Ambiguidades assumidas (confirmar com o dono)
- ~~**Escopo de "projeto"**~~ — **RESOLVIDO pelo fundador, 2026-07-10:** "projeto" = o `Contract` já existente (`apps/api/app/modules/contracts/`), não uma tabela nova. FR4, Epic 5 (Story 5.4) e `docs/stories/5.4.story.md` atualizados.
- **Rateio de overhead:** assumido só na visão analítica (nunca no lançamento), conforme o design de referência.
- ~~**Papéis da fila**~~ — **RESOLVIDO pelo fundador, 2026-07-10:** ver decisão acima (Fila de Pagamentos redefinida sem papéis).
</content>
</invoke>
