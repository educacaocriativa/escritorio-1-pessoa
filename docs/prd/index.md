# e1p — Brownfield PRD (Go-Live) — Índice de Epics

> Shard do PRD `docs/prd.md` (Brownfield Enhancement PRD — Go-Live para Produção).
> Cada arquivo de epic é **autocontido**: traz o contexto do sistema existente, o goal do epic e as stories
> completas com Acceptance Criteria + Integration Verification. O @sm deve ler **apenas o arquivo do epic**
> para gerar cada story formal via `create-next-story.md`.

## Resumo do produto
SaaS multi-tenant white-label (`e1p.com`) para profissionais autônomos, com IA (Claude) como funcionário
invisível e modelo de split de pagamento (40% produtos / 30% serviços / 20% recorrência). Fases 1–5
implementadas e testadas (~252 testes). Este PRD trata **exclusivamente do caminho até o go-live** do que já
foi construído — não há features novas de produto.

## Stack (resumo)
FastAPI (Python 3.13) + SQLAlchemy 2/Alembic + PostgreSQL 16 com Row-Level Security (isolamento de tenant).
React 18 + Vite + TS + Tailwind (design "Portal", cor `#5D44F8`). Monorepo pnpm + app Python. 100%
conteinerizado (Docker). Alvo de deploy do go-live: VPS Hostinger (Caddy próprio ou Traefik compartilhado);
caminho AWS documentado como evolução.

## Regras de Ouro (inegociáveis — valem para toda story)
1. Isolamento de tenant é sagrado (RLS; app conecta como papel non-superuser `e1p_app`).
2. Anonimizador antes da IA (nenhum PII vai para o Claude).
3. Rastro da IA (toda ação da IA é logada).
4. Custo importa (soluções baratas; sem serviço pago sem justificar).
5. Não quebrar o que já funciona (testes + agentes de QA a cada mudança).

## Epics

| Epic | Arquivo | Classificação | Stories |
|---|---|---|---|
| Epic 1 — Segurança & Compliance para Produção | [epic-1-seguranca-compliance.md](./epic-1-seguranca-compliance.md) | BLOQUEANTE | 4 |
| Epic 2 — Integrações Reais (Dinheiro & Comunicação) | [epic-2-integracoes-reais.md](./epic-2-integracoes-reais.md) | BLOQUEANTE | 3 |
| Epic 3 — Deploy, Storage & Observabilidade | [epic-3-deploy-storage-observabilidade.md](./epic-3-deploy-storage-observabilidade.md) | BLOQUEANTE | 5 |
| Epic 4 — Backlog Pós-Lançamento | [epic-4-backlog-pos-lancamento.md](./epic-4-backlog-pos-lancamento.md) | NÃO bloqueante | 6 |

**Sequenciamento recomendado:** Epic 1 → Epic 2 → Epic 3 → (Epic 4 pós-lançamento).
PRD completo (com Requirements FR/NFR/CR, constraints técnicas e premissas do PM): [`../prd.md`](../prd.md).

---

## Iniciativas pós-go-live

> Estas iniciativas **não** fazem parte do PRD de go-live (`docs/prd.md`) — são **features novas de produto**
> e/ou robustez de plataforma, com PRD próprio. Numeração de epics continua a sequência (5, 6, 7, 8...).

### Inteligência Financeira & Robustez de Plataforma
Porte (design, não código) de recursos financeiros analíticos e de plataforma do produto irmão do fundador
(`AxisGov/plataforma-gestao`) para o e1p: DRE por categoria (plano de contas DRE), projeção de caixa 30/60/90
+ runway, motor de diagnóstico determinístico (🟢🟡🔴 primeiro, IA narrando depois), fila auditável de
pagamentos com papéis, lucratividade por projeto, centro de custo, conta de investimento, varredura de órfãos
no storage e secret scan (gitleaks) + SAST (semgrep) no CI.
PRD: [`prd-inteligencia-financeira.md`](./prd-inteligencia-financeira.md).

| Epic | Arquivo | Classificação | Stories |
|---|---|---|---|
| Epic 5 — Inteligência Financeira | [epic-5-inteligencia-financeira.md](./epic-5-inteligencia-financeira.md) | FEATURE NOVA (pós-go-live) | 9 |
| Epic 6 — Robustez de Plataforma (Storage & CI) | [epic-6-robustez-plataforma.md](./epic-6-robustez-plataforma.md) | PLATAFORMA (pós-go-live) | 2 |

**Sequenciamento recomendado:** Epic 5 (interno: 5.1 → 5.2 → 5.3–5.7 → 5.8 → 5.9); Epic 6 é independente e
pode correr em paralelo. Cobre os 9 recursos pedidos pelo fundador sem omissão (rastreabilidade na §4.2 do PRD).

### Cobertura de Testes (caminho feliz / caminho infeliz)
Fechamento dos 5 gaps **P1** do QA Gate de cobertura (`docs/qa/test-coverage-gate-2026-07-11.md`, 17 itens
auditados por 3 agentes `@qa`, ratificado por @pm em 2026-07-11): caminhos infelizes das duas Regras de Ouro de
segurança (RLS e anonimizador) realmente exercitados e não puláveis no CI, e desbloqueio + início da cobertura de
testes do frontend (hoje zero). Não é domínio de negócio novo — é dívida de qualidade.

| Epic | Arquivo | Classificação | Stories |
|---|---|---|---|
| Epic 7 — Cobertura de Testes (P1–P4) | [epic-7-cobertura-de-testes.md](./epic-7-cobertura-de-testes.md) | DÍVIDA DE QUALIDADE (pós-go-live) | 5 (P1) |

**Sequenciamento recomendado:** independente dos Epics 5 e 6 (pode correr em paralelo). Interno: 7.1 → 7.2 → 7.3
(desbloqueio) → 7.4/7.5. **Coordenar 7.1 com @devops/Epic 6** — as duas mexem no mesmo `.github/workflows/ci.yml`.

### Controle Bancário e Conferência
O **plano 3 do dinheiro** (o extrato real da conta do usuário) como entidade de primeira classe, com saldo
**derivado** dos movimentos, e uma **conferência que localiza furos**: saldo do banco × saldo do sistema, **por
conta**, resumido em uma frase. Nasce da assimetria estrutural entre receber (três testemunhas independentes:
gateway, webhook, dinheiro entrando) e pagar (nenhuma). Sem agregador de Open Finance e sem custo recorrente novo.
Design-mãe: [`../architecture/controle-bancario-design.md`](../architecture/controle-bancario-design.md)
(**parcialmente supersedido**); design da Onda 2:
[`../architecture/controle-bancario-onda2-design.md`](../architecture/controle-bancario-onda2-design.md);
ADR: [`../decisions/0003-controle-bancario-nativo.md`](../decisions/0003-controle-bancario-nativo.md)
(**Adendo 4**).

| Epic | Arquivo | Classificação | Stories |
|---|---|---|---|
| Epic 8 — Controle Bancário e Conferência | [epic-8-controle-bancario.md](./epic-8-controle-bancario.md) | FEATURE NOVA (pós-go-live) | 18 (8 ✅ Ondas 0–1 · 10 delimitadas na Onda 2) |

**Estado (2026-07-30):** **Ondas 0 e 1 ✅ em produção** (PR #61, `7dba286`, migrations 0058/0059/0060).
**Onda 2 — "a origem do movimento" — LIBERADA** pelo fundador em 2026-07-30, com 10 stories delimitadas
(8.9–8.18). Onda 2b e Ondas 3–5 planejadas, não liberadas; **Onda 6 bloqueada** pelo pré-requisito
`platform_earnings → transaction`.
**Sequenciamento:** depende do Epic 5 (entregue) — estende `financial_intelligence`, `payables`, `receivables` e
`investments`; independente dos Epics 6 e 7. Interno: 8.1 ✅ → 8.2–8.8 ✅ → **8.11 → 8.9 → 8.10 → 8.12 → 8.13 →
8.14 → 8.15 → 8.16 → 8.17 → 8.18** (ordem de merge da §6.1 do epic).

> ⚠️ **AS ONDAS FORAM RENUMERADAS EM 2026-07-30 — os números 2 a 6 mudaram de significado.** Tabela de-para na
> §11.5 do epic. Uma **Onda 2 nova** (a origem do movimento) entra após a Onda 1; a Onda 2 antiga vira **2b**; o
> payout sobe de 6 para **3**; a importação desce de 3 para **4**; o match vira **5**; a baixa de Receber
> (bloqueada) vira **6**. Critério: **dependência externa crescente**.

**Por que a Onda 2 existe:** o design modelou uma direção só — **extrato → sistema** — e nunca modelou
**sistema → banco**. Quando o dono marca uma conta como paga, o e1p já sabe valor, data e fornecedor; faltava
saber de qual conta saiu. Resultado em produção: 45 contas pagas, saldo derivado R$ 0,00, e o único caminho seria
redigitar as 45. *"É um sistema integrado, não tem o motivo de tudo começar do zero"* (fundador).

⚠️ **A §3.1 do epic foi CORRIGIDA:** ela definia a divergência da **Onda 1** como o instrumento do gate que libera
ou mata as ondas caras. Medida **antes da Onda 2**, essa divergência é enorme **por construção** — porque mede a
**ausência de uma porta**, não o furo — e teria argumentado, com número na mão, para liberar a onda mais cara.
A leitura do gate só é válida **a partir do primeiro ciclo completo posterior à Onda 2**, com a pré-condição de
que toda conta paga e toda cobrança recebida na janela tenham conta bancária informada.

O epic **supersede** o AC1 da Story 5.7 (saldo inicial da projeção) e, quando a **Onda 2b** for liberada, o AC1
da Story 5.6 (`principal_cents` vira derivado).
