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
> e/ou robustez de plataforma, com PRD próprio. Numeração de epics continua a sequência (5, 6...).

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
