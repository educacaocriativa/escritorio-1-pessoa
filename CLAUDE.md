# e1p — "Empresa de 1 Pessoa" · Memória do Projeto

> **Este arquivo é a memória viva do projeto.** É carregado automaticamente em toda sessão do Claude Code.
> Leia-o inteiro antes de qualquer tarefa. Mantenha-o atualizado quando algo estrutural mudar.

## 1. O que é
SaaS **multi-tenant white-label** (`e1p.com`) para profissionais autônomos (advogados, médicos, consultores).
Cada usuário é uma "empresa de 1 pessoa" com subdomínio próprio (`joaosilva.e1p.com`).
Diferencial: **IA (Claude) como funcionário invisível** atravessando todos os módulos.
Modelo de negócio: **split de pagamento** — plataforma retém **40% (produtos) / 30% (serviços) / 20% (recorrência)**.

Spec mestre completa: [`docs/MODULES.md`](docs/MODULES.md). Origem: `/Volumes/Extreme SSD/2026_e1p/Configuração do software.docx`.

## 2. Stack (decidida — ver `docs/decisions/0001-stack-e-infra.md`)
- **Backend:** FastAPI (Python 3.13), SQLAlchemy 2 + Alembic, PostgreSQL 16.
- **Frontend:** React 18 + Vite + TypeScript + Tailwind. Design system "Portal" (ver `packages/design-tokens`).
- **Monorepo:** pnpm workspaces (JS) + app Python isolado. Tipos compartilhados em `packages/shared-types`.
- **Mobile (futuro):** Expo / React Native, reaproveitando API + `packages/`.
- **IA:** Anthropic SDK, modelo `claude-opus-4-8`.
- **Infra AWS:** container enxuto (EC2 Graviton + Docker) → ECS Fargate. RDS Postgres, S3+CloudFront, SSM, SQS. Ver `docs/AWS-DEPLOYMENT.md`.

## 3. Regras de ouro (NUNCA violar)
1. **Isolamento de tenant é sagrado.** Todo dado de negócio carrega `tenant_id`. Acesso a dados SEMPRE passa pela camada de tenancy (RLS no Postgres). Nunca escreva query que possa cruzar tenants. Ver `apps/api/app/core/tenancy.py`.
2. **Anonimizador antes da IA.** Dados sensíveis (nomes, CPF, contas) são substituídos por variáveis ANTES de ir para a API do Claude e reinseridos localmente depois. Crítico para o módulo Jurídico (segredo de justiça). Ver `apps/api/app/core/anonymizer.py`.
3. **Rastro da IA.** Toda ação executada pela IA grava log "Ação executada pela IA" (autor + timestamp).
4. **Custo importa.** Estamos otimizando para AWS barato. Preferir soluções serverless-baratas / Graviton/ARM / cache. Não introduzir serviço pago sem justificar.
5. **Não quebrar o que já funciona.** Toda mudança roda os agentes de QA (ver seção 5) e a suíte de testes antes de considerar concluída.

## 4. Estrutura do repositório
```
apps/api/          FastAPI — app/core (auth, tenancy, anonymizer, ai), app/modules/<modulo>, app/db
apps/web/          React+Vite — app (shell/layout), features/<modulo>, components, lib
packages/
  shared-types/    Contrato de API em TS (web + mobile)
  design-tokens/   Cores/spacing/tipografia do design "Portal"
infra/             docker-compose (dev), Dockerfiles, terraform (AWS)
docs/              ARCHITECTURE, MODULES, AWS-DEPLOYMENT, DATA-MODEL, decisions/ (ADRs)
.claude/agents/    Agentes de QA (regressão, bugs, duplicação)
scripts/           Utilitários (check, seed, etc.)
```

## 5. Fluxo de qualidade (Req. 3 — obrigatório a cada mudança)
Ao criar/alterar qualquer funcionalidade:
1. Escreva/atualize testes (`apps/api/tests`, `apps/web` vitest, e2e playwright).
2. Rode `bash scripts/check.sh` (lint + types + testes) — deve passar.
3. Rode os agentes de QA conforme a tarefa:
   - **regression-tester** — garante que o novo não quebrou o antigo.
   - **bug-hunter** — caça bugs/edge cases no código novo.
   - **dedup-checker** — encontra duplicação e código que já existe (DRY).
4. Só considere a tarefa concluída quando os 3 passarem.

## 6. Estado atual / roadmap
- [x] Fundação do monorepo, docs, agentes de QA, CI local.
- [ ] Core do backend: auth + tenancy (RLS) + anonimizador + camada de IA.
- [ ] Shell do frontend (sidebar/topbar/layout do design "Portal").
- [ ] Migrar módulo **Assistente Jurídico** do app existente (`~/lex-intelligentia-app`).
- [ ] Módulos restantes (faseados — ver `docs/MODULES.md` para ordem sugerida).

## 7. Materiais de referência (fora do repo)
- Spec mestre: `/Volumes/Extreme SSD/2026_e1p/Configuração do software.docx`
- Design Figma exportado: `/Volumes/Extreme SSD/2026_Downloads de JUNHO/crm_export/` (PNGs do "Portal")
- App jurídico existente (a migrar): `/Users/tiagoledesmamariano/lex-intelligentia-app`

## 8. Convenções
- Idioma do produto e comentários de domínio: **PT-BR**. Código/identificadores: inglês.
- Commits: Conventional Commits (`feat:`, `fix:`, `chore:`...). Branch a partir de `main`.
- Um módulo de negócio = uma pasta em `apps/api/app/modules/` + uma em `apps/web/src/features/`.
