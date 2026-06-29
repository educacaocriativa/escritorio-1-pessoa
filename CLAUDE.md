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
   - ⚠️ **A app DEVE conectar como papel NÃO-superusuário** (`e1p_app`), senão a RLS é IGNORADA (superusuários fazem bypass, mesmo com FORCE). Configurado em `infra/docker/initdb/01-rls-enforce.sql`. **Na AWS/RDS o mesmo vale**: rode migrations e a app com um papel non-superuser dono das tabelas (ver `docs/AWS-DEPLOYMENT.md`). Validado por teste e2e no Postgres real (João não vê dados da Maria).
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
- [x] Core do backend: tenancy (RLS) + anonimizador + camada de IA + auditoria.
- [x] Shell do frontend (sidebar/topbar/layout do design "Portal") + Cockpit (esqueleto).
- [x] **Módulo auth + tenant** (register/login/me, JWT, RBAC, RLS na migration 0001). 24 testes.
- [x] **Módulo Agenda** (eventos, detecção de conflitos, CRUD, transições de status, paginação; migration 0002). 43 testes no total.
- [x] **Módulo CRM & Kanban** (clientes, estágios dinâmicos, board, mover card, segmentação; barramento de eventos `core/events`; migration 0003). 61 testes no total.
- [x] **Cockpit** (agregador read-only de Agenda + CRM: contagem do dia, críticos pendentes, funil/conversão; financeiro como placeholder). 70 testes no total. **→ Fase 1 COMPLETA.**
- [ ] Próximo: **Fase 2 — dinheiro entra/sai** (Carteira & Split → Contas a Receber → Contas a Pagar → Produtos & Checkout). O placeholder `finance` do Cockpit e o evento `crm.client.moved` já estão prontos para ligar.
- [ ] Migrar módulo **Assistente Jurídico** do app existente (`~/lex-intelligentia-app`) — Fase 5.

## 6.1 Dívida técnica / TODO de segurança (de revisão QA — endereçar antes de produção)
- **Enumeração de e-mail no /register:** retorna 409 "e-mail já cadastrado" (UX comum em signup, mas revela existência). Reavaliar quando houver fluxo de e-mail/confirmação.
- **Validação de CPF/CNPJ:** hoje só valida tamanho; falta dígito verificador + normalização + unicidade por tenant.
- **Hardening da tabela `users` (global):** não tem RLS (login por e-mail é global). Garantir que módulos de negócio NUNCA consultem `users` via `get_db` sem filtro de tenant.
- **Idle timeout LGPD (30min):** configurado mas não implementado (JWT é stateless, expira em 7 dias). Implementar tracking de atividade / refresh curto quando o frontend de auth entrar.
- **Truncagem bcrypt por bytes (72):** pode cortar caractere multibyte; documentado, aceitável.
- **Geração de tipos:** `shared-types` é mantido à mão espelhando os schemas. Avaliar gerar TS a partir do OpenAPI do FastAPI para eliminar divergência.
- **Rastro da IA não propagado (Agenda):** `CurrentUser.is_ai` é placeholder fixo `False` — nenhum evento é criado pela IA ainda (não há endpoint/ator de IA). Quando a camada de ações da IA existir, propagar `is_ai` em create/update/cancel/reschedule (Regra de Ouro nº 3).
- **Semântica de `all_day` (Agenda):** hoje o campo é só armazenado; o conflito usa starts_at/ends_at crus. Definir normalização (ex.: `[00:00, 24:00)` no fuso do tenant) quando a UI de calendário entrar.
- **Teste de isolamento cross-tenant:** RLS é Postgres-only; os testes unitários usam SQLite e não a exercem. ✅ Validado manualmente via e2e no Docker (Postgres real). TODO: automatizar com testcontainers no CI.
- **Drift de versão venv↔produção:** o venv local tinha FastAPI mais novo que o pinado (0.115.5), o que escondeu um erro de rota 204 que só quebrou no container. Agora alinhado. **Antes de confiar só nos testes locais, rode a stack Docker** (ou recrie o venv com `pip install -r requirements.txt`). Considerar CI que rode os testes na imagem.
- **Como rodar/validar localmente:** `docker compose -f infra/docker-compose.yml up -d --build` → web :5173, API :8000/docs. Testes: `cd apps/api && source .venv/bin/activate && pytest`. SSD exFAT: rodar `find . -name '._*' -delete` antes de builds Docker (AppleDouble quebra o sender).

> **Decisão de arquitetura (mantida):** seguimos RLS como ÚNICA garantia de isolamento — o código NÃO adiciona filtro manual de tenant (Regra de Ouro nº 1). Defesa-em-profundidade (filtro explícito redundante) foi considerada e rejeitada para não criar o padrão "algumas queries filtram, outras não" (onde esquecer uma vira vazamento). A RLS é fail-closed inclusive em escrita (WITH CHECK). Revisitar via ADR se necessário.

> Já corrigidos no módulo Agenda (revisão QA): validação de status/priority no update; guarda de transição (não cancelar/remarcar evento terminal); paginação obrigatória em list; `amount_cents >= 0`; duração positiva (rejeita zero); coerção de datetime naive→UTC.

**CRM & Kanban — pendências (de revisão QA):**
- **Unicidade de e-mail de cliente:** não há constraint; mesmo e-mail repetível no tenant (decisão de produto — confirmar se deve deduplicar).
- **`StageUpdate` não edita `is_won`/`is_lost`:** estágio criado com flag errada precisa ser recriado. Adicionar quando houver UI de configuração do funil.
- **Múltiplos estágios `is_won`/`is_lost`:** permitido; o consumidor do evento `crm.client.moved` deve tolerar. Avaliar regra de no máx. 1 de cada.
- **Filtro por tag carrega em memória:** feito em Python p/ portabilidade; trocar por operador JSON do Postgres (`tags @> [tag]`) em escala.
- **Validação de CPF (`document`):** reutiliza a dívida global (sem dígito verificador).

**Cockpit — pendência (de revisão QA):**
- **Janela do dia ancorada em meia-noite UTC**, não no fuso do tenant. Para -03:00 (Brasil), eventos entre 00:00–03:00 UTC caem no dia errado. O frontend deve passar `day` correto, mas o offset de 3h da janela só some quando passarmos o fuso/offset do tenant. Resolver junto com a dívida geral de fuso por tenant.

> Já corrigidos no Cockpit (revisão QA): removido efeito colateral de escrita (GET não semeia mais estágios); `today_count` via `COUNT(*)` real (não capado em 500); cancelados fora da contagem; críticos concluídos (`done`) fora do alerta; `day` malformado → 422 (tipado como `date`); CRM agregado por `GROUP BY` (não carrega todos os clientes).

> Já corrigidos no módulo CRM (revisão QA): barramento `core/events.emit` isola exceções de assinantes (não derruba o chamador pós-commit); race de seed de estágios fechada com `UNIQUE(tenant_id, name)` + retry; `create_stage` duplicado → 409; FK `RESTRICT` (impede card órfão sumir do board); filtro por tag agora ordenado/determinístico; limites de tags + birthdate não-futura. (Bug pego por teste: router não capturava `CrmError` no create_stage.)

> Já corrigidos na fundação: guarda de boot p/ JWT_SECRET fraco em produção; RLS fail-closed (valida tenant_id); IntegrityError→409 no register (race); /me revalida is_active e não reemite token; e-mail case-insensitive; alinhamento de `created_at`/`role` com shared-types.

## 7. Materiais de referência (fora do repo)
- Spec mestre: `/Volumes/Extreme SSD/2026_e1p/Configuração do software.docx`
- Design Figma exportado: `/Volumes/Extreme SSD/2026_Downloads de JUNHO/crm_export/` (PNGs do "Portal")
- App jurídico existente (a migrar): `/Users/tiagoledesmamariano/lex-intelligentia-app`

## 8. Convenções
- Idioma do produto e comentários de domínio: **PT-BR**. Código/identificadores: inglês.
- Commits: Conventional Commits (`feat:`, `fix:`, `chore:`...). Branch a partir de `main`.
- Um módulo de negócio = uma pasta em `apps/api/app/modules/` + uma em `apps/web/src/features/`.
