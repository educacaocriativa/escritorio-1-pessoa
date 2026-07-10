# e1p — "Empresa de 1 Pessoa" · Brownfield PRD — Go-Live para Produção

> **Tipo:** Brownfield Enhancement PRD (produção-readiness / go-live).
> **Escopo:** levar ao ar o produto JÁ CONSTRUÍDO (Fases 1–5). NÃO é um PRD de novas features de produto.
> **Autor:** Morgan (@pm). **Modo de execução:** YOLO (autônomo — premissas documentadas na seção final).
> **Data:** 2026-07-10.

---

## 1. Intro Project Analysis and Context

### 1.1 Existing Project Overview

#### Analysis Source
Análise fresca baseada em documentação existente no repositório (IDE-based). Fontes primárias:
- `CLAUDE.md` (memória viva — roadmap seção 6 e dívida técnica seção 6.1) — **material primário**.
- `docs/decisions/0001-stack-e-infra.md` (ADR de stack/infra).
- `docs/AWS-DEPLOYMENT.md` e `docs/HOSTINGER-DEPLOY.md` (dois caminhos de deploy documentados).
- `README.md`, `infra/` (docker-compose dev/prod/traefik, Caddyfile, `.env.prod.example`).
- Histórico git (últimos 20 commits — o mais recente, `59ff179`, adiciona o bundle de deploy Hostinger).

> **Observação:** NÃO foi executada a task `document-project`. A documentação existente (CLAUDE.md +
> ADR + guias de deploy) é rica o suficiente para dispensá-la neste ciclo. Recomenda-se rodá-la mais
> tarde se for necessário um inventário técnico formal por módulo.

#### Current Project State
e1p é um **SaaS multi-tenant white-label** (`e1p.com`) para profissionais autônomos (advogados, médicos,
consultores). Cada usuário é uma "empresa de 1 pessoa" com subdomínio próprio. Diferencial: **IA (Claude)
como funcionário invisível** atravessando todos os módulos. Modelo de negócio: **split de pagamento**
(40% produtos / 30% serviços / 20% recorrência).

**Estado de construção:** Fases 1 a 5 implementadas. Módulos entregues: Auth/Tenant (RLS), Agenda
(calendário + conflitos), CRM/Kanban, Cockpit, Super Admin (hierarquia + convites), Carteira/Split,
Contas a Pagar/Receber (boleto PDF + webhook), Produtos/Checkout, Orçamentos, Propostas (link público),
Contratos + assinatura/KYC, Ficha 360°, Marketing (Carrossel editorial, Funil de vendas com motor de
automação, Estoque, Brand Kit, Sites/Páginas), Anexos (upload real), e Assistente Jurídico (21 skills,
anonimizador + anti-alucinação). **~252 testes automatizados** + validações e2e no Postgres real.

O produto está **funcionalmente completo para uso**; o que falta é o caminho de **produção-readiness**:
integrações reais (dinheiro, comunicação), hardening de segurança/LGPD, storage durável e a esteira de
deploy/observabilidade. Já existe um **começo de esforço de deploy** (commit Hostinger: `docker-compose.prod.yml`
com Caddy próprio, `docker-compose.traefik.yml` para o Traefik compartilhado, `Caddyfile`, `.env.prod.example`,
`initdb-prod/01-rls-enforce.sh`, guia `HOSTINGER-DEPLOY.md`).

### 1.2 Available Documentation Analysis

- [x] Tech Stack Documentation — `CLAUDE.md §2` + ADR 0001
- [x] Source Tree/Architecture — `CLAUDE.md §4`, `docs/ARCHITECTURE.md`
- [x] Coding Standards — `CLAUDE.md §3, §5, §8` (Regras de Ouro, fluxo de qualidade, convenções)
- [x] API Documentation — contrato em `packages/shared-types` + OpenAPI do FastAPI (`/docs`)
- [x] External API Documentation — parcial (integrações ainda em stub: WhatsApp, gateway, Google, e-mail)
- [x] UX/UI Guidelines — design "Portal" (`packages/design-tokens`, cor `#5D44F8`)
- [x] Technical Debt Documentation — `CLAUDE.md §6.0, §6.1` (dívida por módulo + TODO de segurança QA)
- [x] Other: guias de deploy (`AWS-DEPLOYMENT.md`, `HOSTINGER-DEPLOY.md`), ADR 0001

Documentação suficiente. **Não** é necessário rodar `document-project` para este PRD de go-live.

### 1.3 Enhancement Scope Definition

#### Enhancement Type
- [x] Integration with New Systems (gateway de pagamento, WhatsApp Cloud API, provedor de e-mail, Google OAuth)
- [x] Performance/Scalability Improvements (storage durável, backups, observabilidade)
- [x] Bug Fix and Stability Improvements (hardening RLS `users`, validação CPF/CNPJ, idle timeout LGPD)
- [x] Other: **Production readiness / Go-Live** (esteira de deploy, staging, CI na imagem, monitoramento)

> Este NÃO é um "New Feature Addition". Toda a superfície de produto já existe. O enhancement é
> **operacionalizar o que existe para produção segura**, trocando stubs por integrações reais e
> fechando lacunas de segurança/compliance/infra.

#### Enhancement Description
Levar o e1p ao ar em produção com segurança: substituir os stubs por integrações reais (gateway de
pagamento, WhatsApp Cloud API, e-mail transacional), fazer o hardening de segurança/LGPD exigido pela
revisão de QA, migrar armazenamento de arquivos para storage durável, e estabelecer a esteira de
deploy/observabilidade (staging, CI testando a imagem Docker, backups offsite, monitoramento). O ponto
de partida é o bundle de deploy Hostinger já commitado (`59ff179`).

#### Impact Assessment
- [x] **Moderate to Significant Impact** — a maior parte é **aditiva** (trocar implementação por trás de
  interfaces internas já validadas: `core/whatsapp`, `core/email`, webhook do gateway, camada de storage).
  Alguns pontos exigem mudança de código existente com risco controlado: hardening de acesso à tabela
  `users`, validação de CPF/CNPJ em múltiplos pontos de entrada, migração do storage de anexos
  (bytes-no-Postgres → object storage). Nenhuma mudança arquitetural de fundo — a arquitetura (RLS,
  anonimizador, 12-factor conteinerizado) permanece.

### 1.4 Goals and Background Context

#### Goals
- Colocar o e1p no ar em produção, acessível por um domínio público com TLS, de forma estável e segura.
- Fazer o dinheiro entrar de verdade: gateway real gerando boleto/Pix registrado e recebendo webhook confiável, com split creditado na Carteira.
- Tornar verídicas as promessas de comunicação: e-mails transacionais (recuperação/convite) e notificações WhatsApp realmente entregues (hoje só `logged`).
- Fechar as lacunas de segurança e LGPD bloqueantes identificadas pela revisão de QA antes de expor dados reais de clientes.
- Estabelecer uma esteira de deploy repetível e segura (staging, CI na imagem Docker, backups offsite, monitoramento) para operar sem quebrar o que já funciona.
- Separar com clareza o que é **bloqueante para o lançamento** do que pode ir para **backlog pós-lançamento**, para permitir um go-live enxuto sem escopo inflado.

#### Background Context
Fases 1–5 estão implementadas e testadas (~252 testes), com decisões de arquitetura sólidas (RLS como
garantia única de isolamento, anonimizador antes da IA, 12-factor conteinerizado). Porém o produto foi
construído com **stubs conscientes** em pontos que exigem credenciais/infra externa: pagamentos, WhatsApp,
e-mail e Google são "logged"/manuais; anexos vivem como bytes no Postgres; e a revisão de QA catalogou uma
lista explícita de dívida de segurança (§6.1 do CLAUDE.md) marcada como "endereçar antes de produção".
O último commit (`59ff179`) já iniciou o esforço de deploy na VPS Hostinger (Caddy próprio e integração
ao Traefik compartilhado em `e1p.doroeventos.com.br`). Este PRD organiza o caminho restante até o go-live,
respeitando a Regra de Ouro nº 5 ("não quebrar o que já funciona") e o guard-rail de custo do projeto.

### 1.5 Change Log

| Change | Date | Version | Description | Author |
|---|---|---|---|---|
| Criação | 2026-07-10 | 1.0 | PRD brownfield de go-live/produção, derivado de CLAUDE.md §6/§6.1 e do bundle de deploy Hostinger | Morgan (@pm) |

---

## 2. Requirements

> Requisitos derivados da dívida técnica documentada (CLAUDE.md §6.0, §6.1) e dos guias de deploy.
> **Nada aqui é feature nova de produto** — tudo serve a operar em produção com segurança. Cada requisito
> está classificado como **[BLOQUEANTE]** (para o lançamento) ou **[BACKLOG]** (pós-lançamento) na seção 6.

### 2.1 Functional

- **FR1:** Integrar um gateway de pagamento real (Asaas ou Mercado Pago) substituindo o stub: gerar boleto/Pix **registrado** (com registro bancário, não o layout-stub atual do `core/boleto.py`), e receber o **webhook real** de compensação em `POST /receivables/webhook`, protegido por `GATEWAY_WEBHOOK_SECRET`, creditando a Carteira com split (preservando idempotência e o lock `FOR UPDATE` contra baixa dupla já existentes).
- **FR2:** Integrar um provedor de e-mail transacional (SMTP/SES) no `core/email.py`, entregando de verdade: link de recuperação de senha (`/auth/forgot-password`), senha temporária de convite de conta/funcionário (`/admin/accounts`, `/admin/accounts/{tenant_id}/users`) e demais mensagens. Em produção, **remover** o retorno de `dev_reset_token`/`temp_password` no corpo da resposta.
- **FR3:** Integrar a WhatsApp Cloud API (Meta) no `core/whatsapp.py`, entregando as notificações hoje apenas `logged` (cobrança amigável com IA, mensagens de funil, `crm.client.moved`, vencimentos), usando um **campo de telefone do owner/destinatário** real (hoje o recipient usa o e-mail como placeholder). Exige `WHATSAPP_TOKEN` + `WHATSAPP_PHONE_ID`.
- **FR4:** Implementar validação real de CPF/CNPJ (dígito verificador + normalização + unicidade por tenant), aplicada em todos os pontos de entrada: `/register`, cadastro/convite de usuário, criação de cliente no CRM (`document`) e KYC/assinatura de contrato.
- **FR5:** Fazer o hardening do acesso à tabela global `users` (sem RLS por ser login global): garantir que nenhum módulo de negócio consulte `users` via `get_db` sem escopo de tenant; e criar um **log de plataforma fora do tenant** para operações destrutivas (exclusão de conta), já que o delete purga os `audit_entries` do próprio tenant (LGPD).
- **FR6:** Implementar o idle timeout LGPD de 30 minutos (hoje configurado mas não implementado — JWT stateless expira em 7 dias), via tracking de atividade / refresh token curto no frontend de auth.
- **FR7:** Forçar troca de senha do Super Admin (Master) no primeiro login (hoje a senha semeada vale até troca manual).
- **FR8:** Mover o armazenamento de arquivos para storage durável (S3-compatível): anexos hoje são `LargeBinary` no Postgres; logo/imagens de vários módulos (Brand Kit, propostas, carrossel, sites) são por URL. Migrar para upload real em object storage, mantendo isolamento por tenant.
- **FR9:** Prover um ambiente de **staging** espelhando produção (mesma imagem, dados sintéticos) para validar cada deploy antes de promover para produção.
- **FR10:** Estabelecer **CI automatizado** que rode a suíte de testes completa **dentro da imagem Docker de produção** (não só no venv local), fechando a brecha de drift venv↔produção documentada; o CI deve ser gate obrigatório antes do deploy.
- **FR11:** Automatizar **backups do Postgres** (dump diário) com **cópia offsite** (S3/outro storage) e procedimento de **restauração testado** — hoje o guia sugere um cron, mas backup só na mesma VPS não protege contra perda do servidor.
- **FR12:** Instrumentar **monitoramento e alertas** de disponibilidade: health da API (`/health`), validade do TLS (Caddy/Traefik), disco, e reinícios de container — com alerta acionável (ex.: Uptime Kuma + notificação).

### 2.2 Non Functional

- **NFR1:** O isolamento de tenant (RLS) deve permanecer a **garantia única** de isolamento (Regra de Ouro nº 1). Em produção a app **deve** conectar como papel NÃO-superusuário `e1p_app` (o `initdb-prod/01-rls-enforce.sh` já provisiona isso na VPS; na AWS/RDS o mesmo vale). Nenhuma regressão de isolamento é aceitável.
- **NFR2:** O guard de produção (`app/config.py::_guard_production_secrets`) deve bloquear o boot com `JWT_SECRET` fraco/default (<32 chars), `ANTHROPIC_API_KEY` ausente ou `SUPER_ADMIN_PASSWORD` default. Isso deve ser verificado como parte do gate de release.
- **NFR3:** Custo deve permanecer no alvo do projeto (~US$30–45/mês no plano AWS Fase A, ou 1 VPS Hostinger). Não introduzir serviço pago sem justificar (Regra de Ouro nº 4). Preferir Graviton/ARM, cache agressivo, S3 lifecycle.
- **NFR4:** **Graceful degradation** obrigatória: módulos com integração não configurada (WhatsApp/gateway/e-mail sem chave) devem falhar fechado/`logged` e nunca derrubar a request (padrão já adotado nos stubs — deve ser preservado ao plugar os provedores reais).
- **NFR5:** Todos os ~252 testes existentes devem continuar passando; cada integração real deve vir com testes + validação e2e no Postgres real (Regra de Ouro nº 5 + fluxo de qualidade §5). Automatizar o isolamento cross-tenant no CI com testcontainers (hoje é validado só manualmente).
- **NFR6:** O webhook de pagamento deve ser **idempotente** e protegido; nenhuma baixa dupla nem crédito de split duplicado (preservar os locks `FOR UPDATE` existentes em Carteira/Contas a Receber).
- **NFR7:** A Regra de Ouro nº 2 (anonimizador antes da IA) deve permanecer intacta: nenhum dado sensível (nomes/CPF/contas/peças jurídicas) vai para a API do Claude sem anonimização — nada neste go-live pode afrouxar isso.

### 2.3 Compatibility Requirements

- **CR1 (API):** Os endpoints e o contrato existentes (`packages/shared-types`) devem permanecer retrocompatíveis. Endpoints/campos das integrações reais são **aditivos**; o webhook do gateway reusa a rota `POST /receivables/webhook` já publicada.
- **CR2 (DB schema):** Novas colunas/tabelas apenas via **migrations Alembic aditivas** (próximas após a 0029), sem mudanças destrutivas nos dados de tenant existentes; **toda nova tabela de negócio carrega `tenant_id` e política RLS** (Regra de Ouro nº 1). Ex.: campo de telefone do owner (FR3), campos de config de integração, ponteiros de object storage (FR8).
- **CR3 (UI/UX):** O design "Portal" (cor `#5D44F8`, sidebar, layout) deve ser preservado. Novas telas (ex.: config de chaves de integração, campo de telefone do owner) seguem os padrões existentes de Configurações/Brand Kit.
- **CR4 (integração):** A troca de stub por provedor real deve manter as **interfaces internas** (`core/whatsapp`, `core/email`, contrato do webhook, camada de storage) para que os chamadores e testes existentes não quebrem — a implementação muda por trás da interface.

---

## 3. User Interface Enhancement Goals

> O go-live é majoritariamente backend/infra. As mudanças de UI são pontuais e devem reusar padrões existentes.

### 3.1 Integration with Existing UI
Novos elementos de UI reusam o design "Portal" e os componentes existentes (Configurações/Brand Kit,
`Collapsible`, cards, toasts). Nenhuma revisão de design system.

### 3.2 Modified/New Screens and Views
- **Configurações → Integrações:** nova aba/seção para chaves de gateway, WhatsApp e e-mail (a própria §6.1 já lista "config de integrações (chaves) nesta tela" como dívida). Chaves sensíveis nunca expostas ao cliente; escopo de plataforma/tenant a definir.
- **Perfil da empresa / owner:** campo de **telefone do owner** (necessário para FR3 — hoje inexistente).
- **Configurações → Brand Kit e módulos com imagem:** trocar campos "URL da imagem/logo" por **upload real** (FR8), mantendo a prévia ao vivo.
- **Tela de 1º acesso (Master):** forçar troca de senha (FR7) reusando o fluxo `FirstAccessPage`/`must_reset_password` já existente para usuários comuns.
- **Auth:** tratamento de idle timeout (FR6) no `ProtectedLayout` (aviso + logout por inatividade).

### 3.3 UI Consistency Requirements
Manter cor `#5D44F8`, tipografia e espaçamento do design "Portal"; upload de arquivos reusa o componente
`components/Attachments.tsx` já validado; mensagens de erro/estado em PT-BR (convenção §8).

---

## 4. Technical Constraints and Integration Requirements

### 4.1 Existing Technology Stack
**Languages:** Python 3.13 (backend), TypeScript (frontend).
**Frameworks:** FastAPI, SQLAlchemy 2 + Alembic (backend); React 18 + Vite + Tailwind (frontend); design "Portal".
**Database:** PostgreSQL 16 com Row-Level Security (banco único, `tenant_id` em toda tabela de negócio).
**Infrastructure:** Monorepo pnpm (JS) + app Python isolado; 100% conteinerizado (Docker Compose). Deploy alvo atual: **VPS Hostinger** (Caddy próprio OU Traefik compartilhado — `e1p.doroeventos.com.br`); caminho AWS (EC2 Graviton → ECS Fargate, RDS, S3/CloudFront, SSM, SQS) documentado como evolução.
**External Dependencies:** Anthropic SDK (`claude-opus-4-8`); pendentes de integração real: gateway (Asaas/Mercado Pago), WhatsApp Cloud API (Meta), e-mail (SMTP/SES), Google OAuth (Meet/Calendar), object storage (S3-compatível). OCR (tesseract) para o Jurídico — validar no build de produção.

### 4.2 Integration Approach
**Database Integration Strategy:** migrations Alembic aditivas a partir da 0029; toda nova tabela com `tenant_id` + RLS; app roda migrations e serve como papel non-superuser `e1p_app`. Automatizar teste de isolamento cross-tenant com testcontainers (Postgres real) no CI.
**API Integration Strategy:** provedores externos plugados por trás das interfaces internas (`core/whatsapp`, `core/email`, webhook do gateway, camada de storage) — CR4. Webhook do gateway reusa `POST /receivables/webhook` protegido por `GATEWAY_WEBHOOK_SECRET`. Envios síncronos hoje no request (ex.: WhatsApp no move de card) devem migrar para fila (SQS) quando o worker durável existir.
**Frontend Integration Strategy:** novas telas em `apps/web/src/features/*` seguindo o padrão módulo-por-pasta (§8); reuso de `Attachments.tsx`, Brand Kit e componentes "Portal".
**Testing Integration Strategy:** manter `scripts/check.sh` (lint + types + testes) + os 3 agentes de QA (regression-tester, bug-hunter, dedup-checker) por mudança (§5). Adicionar CI que roda os testes **dentro da imagem Docker** (FR10) e e2e no Postgres real.

### 4.3 Code Organization and Standards
**File Structure Approach:** um módulo de negócio = uma pasta em `apps/api/app/modules/` + uma em `apps/web/src/features/`; integrações externas em `apps/api/app/core/*`.
**Naming Conventions:** código/identificadores em inglês; domínio/comentários e UI em PT-BR (§8).
**Coding Standards:** Regras de Ouro do CLAUDE.md §3 são inegociáveis (isolamento RLS, anonimizador antes da IA, rastro da IA, custo, não quebrar o existente). Conventional Commits; branch a partir de `main`.
**Documentation Standards:** atualizar `CLAUDE.md` (memória viva) e ADRs (`docs/decisions/`) quando algo estrutural mudar (ex.: escolha do gateway, decisão de storage, alvo de deploy definitivo).

### 4.4 Deployment and Operations
**Build Process Integration:** imagens Docker das 3 apps (api/web/postgres-init) buildadas no deploy; migrations rodam no start do container `api` (mesmo comando do dev). CI deve buildar e testar a imagem antes de promover (FR10).
**Deployment Strategy:** ponto de partida = bundle Hostinger (`docker-compose.prod.yml` com Caddy próprio OU `docker-compose.traefik.yml` na VPS com Traefik compartilhado). Introduzir **staging** (FR9) e um fluxo `git pull` + rebuild controlado (evoluir para CI/CD — hoje é manual na VPS). Manter o caminho AWS aberto (12-factor) sem acoplar à EC2 específica.
**Monitoring and Logging:** hoje não há monitoramento (só `docker compose logs`). Introduzir uptime/health + alertas (FR12) e, quando houver worker, o `tick` do funil precisa de cron/worker durável (hoje é endpoint manual).
**Configuration Management:** segredos via `.env.prod` (nunca commitado) na VPS / SSM Parameter Store na AWS. Guard de produção (`_guard_production_secrets`) bloqueia boot com segredo fraco/ausente (NFR2).

### 4.5 Risk Assessment and Mitigation

**Technical Risks:**
- **Vazamento cross-tenant** se a app conectar como superusuário ou se algum módulo consultar `users` sem escopo — RLS seria ignorada. É o risco mais grave (Regra de Ouro nº 1).
- **Drift venv↔produção** (documentado): versões divergentes esconderam um bug de rota 204 que só quebrou no container.
- **Baixa dupla / crédito de split duplicado** no webhook do gateway real se a idempotência não for preservada.
- **Perda de dados** — anexos como bytes no Postgres incham o banco e o backup; backup só na VPS não sobrevive à perda do servidor.
- **PII vazando para a IA** se o anonimizador for contornado ao plugar integrações reais.

**Integration Risks:**
- Credenciais reais (Asaas/Mercado Pago, Meta WhatsApp, SMTP/SES, Google OAuth) dependem de contas/aprovações externas (ex.: WhatsApp Business exige aprovação de template pela Meta) — podem atrasar o go-live.
- Boleto atual é layout-stub sem registro bancário; o boleto real exige homologação com o gateway.
- OCR (tesseract) do Jurídico precisa estar presente na imagem de produção (já em requirements — validar no build).

**Deployment Risks:**
- Caddy/Let's Encrypt exige DNS apontado ANTES do boot (HTTP-01); na VPS com Traefik compartilhado, nenhum outro serviço pode disputar 80/443.
- Wildcard por subdomínio de tenant (`*.e1p.com`) exige TLS via DNS-01 — ainda não configurado (afeta o white-label, ver premissa P4).
- Sem staging, um deploy ruim vai direto para produção.

**Mitigation Strategies:**
- Papel `e1p_app` NOSUPERUSER dono das tabelas em prod (VPS `initdb-prod`; RDS papel dedicado) + teste e2e de isolamento no CI (testcontainers).
- CI roda os testes DENTRO da imagem Docker (FR10) — mata o drift antes do deploy.
- Preservar locks `FOR UPDATE` e idempotência do webhook; cobrir com teste de baixa concorrente.
- Migrar anexos para object storage (FR8) + backup offsite testado (FR11).
- Provisionar credenciais externas cedo (iniciar aprovações Meta/gateway no começo do épico); manter graceful degradation para permitir soft-launch mesmo com uma integração ainda pendente.
- Staging (FR9) obrigatório antes de promover; runbook de rollback (`git checkout` da tag anterior + rebuild; migrations aditivas facilitam reversão).

---

## 5. Epic and Story Structure

### 5.1 Epic Approach

**Epic Structure Decision:** **Programa de Go-Live decomposto em 3 épicos bloqueantes + 1 épico de backlog pós-lançamento**, em vez de um único épico monolítico.

**Rationale (baseado na análise real do projeto):** o template brownfield favorece um épico único, mas aqui os
workstreams são **relacionados porém distintos**, cada um substancial e com donos/competências diferentes
(segurança/backend, integrações externas, infra/devops). Agrupar tudo num épico só criaria um épico gigante e
difícil de sequenciar. Ainda assim, eles compõem **um programa coeso** (o go-live) com dependências claras —
por isso "Programa de Go-Live" e não iniciativas soltas. A **criação formal dos épicos é um passo seguinte**
(via @pm `*create-epic`); aqui detalhamos o Epic 1 (o de maior risco e caminho crítico) com histórias, e
listamos os demais em alto nível.

**Sequenciamento recomendado (minimiza risco ao sistema existente):**
1. **Epic 1 — Segurança & Compliance para Produção** (bloqueante, primeiro: nada vai ao ar com dados reais sem isso).
2. **Epic 2 — Integrações Reais (Dinheiro & Comunicação)** (bloqueante: e-mail e gateway; WhatsApp em fast-follow).
3. **Epic 3 — Deploy, Storage & Observabilidade** (bloqueante: staging, CI na imagem, backups, monitoramento; parte de storage pode ser faseada).
4. **Epic 4 — Backlog Pós-Lançamento** (NÃO bloqueante: Google OAuth, dívidas menores por módulo, refinamentos).

### 5.2 Classificação: Bloqueante para lançamento vs Backlog pós-lançamento

| Item | Origem (CLAUDE.md) | Classificação | Épico |
|---|---|---|---|
| Gateway real (Asaas/MP) + boleto/Pix registrado + webhook real | §6.1 / Fase 2 | **BLOQUEANTE** (monetização) | Epic 2 |
| Provedor de e-mail (SMTP/SES) — recuperação de senha + convites | §6 recuperação/convite | **BLOQUEANTE** (onboarding/reset) | Epic 2 |
| WhatsApp Cloud API — entregar notificações hoje `logged` | §6 / Fase 4 | **BLOQUEANTE-LEVE** (degrada com graça; fast-follow) | Epic 2 |
| Validação CPF/CNPJ (dígito verificador) | §6.1 | **BLOQUEANTE** (KYC/contratos) | Epic 1 |
| Hardening RLS acesso à tabela `users` | §6.1 | **BLOQUEANTE** (segurança) | Epic 1 |
| Log de plataforma p/ exclusão de conta (LGPD) | §6.1 Super Admin | **BLOQUEANTE** (LGPD) | Epic 1 |
| Idle timeout LGPD (30 min) | §6.1 | **BLOQUEANTE** (LGPD) | Epic 1 |
| Forçar troca de senha do Super Admin no 1º login | §6.1 Super Admin | **BLOQUEANTE** (segurança) | Epic 1 |
| Guard de produção de segredos (validar no release) | §6.1 fundação | **BLOQUEANTE** (segurança) | Epic 1 |
| CI testando a imagem Docker (drift venv↔prod) | §6.1 | **BLOQUEANTE** (deploy seguro) | Epic 3 |
| Backups automatizados + offsite + restore testado | HOSTINGER-DEPLOY §6 | **BLOQUEANTE** (proteção de dados) | Epic 3 |
| Monitoramento/alertas (uptime, TLS, disco) | HOSTINGER-DEPLOY dívida | **BLOQUEANTE-LEVE** (mínimo p/ operar) | Epic 3 |
| Ambiente de staging vs produção | HOSTINGER-DEPLOY dívida | **BLOQUEANTE** (validar deploys) | Epic 3 |
| Storage S3 p/ anexos (bytes no Postgres) | §6.1 Anexos | **BLOQUEANTE-LEVE** (risco de backup; faseável) | Epic 3 |
| Upload real de logo/imagens (hoje URL) | §6 Brand Kit/Propostas/Sites | **BACKLOG** (URL funciona) | Epic 4 |
| Google Meet/Calendar OAuth | §6 / módulo API Hub | **BACKLOG** (campo manual funciona) | Epic 4 |
| Enumeração de e-mail no /register | §6.1 | **BACKLOG** (UX comum) | Epic 4 |
| Geração de tipos TS via OpenAPI (vs manual) | §6.1 | **BACKLOG** (manutenção) | Epic 4 |
| Rastro de IA propagado na Agenda | §6.1 | **BACKLOG** (sem ator de IA ainda) | Epic 4 |
| Fuso por tenant (janela do dia / all-day) | §6.1 Cockpit/Agenda | **BACKLOG** (corrigido nas bordas críticas) | Epic 4 |
| Cron/worker durável p/ tick do funil | §6 Fase 4 | **BACKLOG** (endpoint manual funciona) | Epic 4 |
| Wildcard subdomínio por tenant (DNS-01) | HOSTINGER-DEPLOY dívida | **BACKLOG** (go-live em 1 domínio; ver P4) | Epic 4 |
| Dívidas menores por módulo (estorno, OCR boleto, PDF assinado, régua de cobrança, etc.) | §6 por módulo | **BACKLOG** | Epic 4 |

---

## 6. Epic 1: Segurança & Compliance para Produção

**Epic Goal:** fechar todas as lacunas de segurança e LGPD marcadas na revisão de QA como "endereçar antes
de produção", garantindo que nenhum dado real de cliente seja exposto sem o hardening necessário — sem
regressão de isolamento nem de funcionalidade existente.

**Integration Requirements:** todo o hardening é aditivo por trás das interfaces existentes (auth, tenancy,
admin). A garantia única de isolamento (RLS + papel `e1p_app` non-superuser) deve permanecer intacta; nenhum
teste existente pode quebrar; validação e2e de isolamento no Postgres real.

### Story 1.1 — Validação real de CPF/CNPJ
As a **profissional que usa o e1p e seus clientes**,
I want **que CPF/CNPJ sejam validados de verdade (dígito verificador, normalização, unicidade por tenant)**,
so that **documentos inválidos não entrem no sistema e o KYC de contratos tenha valor**.

#### Acceptance Criteria
1. Um validador de CPF/CNPJ (dígito verificador + normalização) é aplicado em `/register`, cadastro/convite de usuário, criação de cliente no CRM (`document`) e KYC/assinatura de contrato.
2. Documentos inválidos são rejeitados com 422 e mensagem clara em PT-BR; documentos válidos são normalizados (só dígitos) antes de persistir.
3. Unicidade de `document` por tenant é garantida onde fizer sentido (owner/funcionário), respeitando a decisão de produto pendente sobre dedup de cliente (documentar a escolha).

#### Integration Verification
- IV1: Fluxos existentes de convite/assinatura continuam funcionando com documentos válidos (testes de convite/KYC passam).
- IV2: A validação não consulta `users`/dados de outro tenant (respeita RLS); teste cross-tenant intacto.
- IV3: Sem regressão de performance perceptível nos endpoints de cadastro.

### Story 1.2 — Hardening de acesso à tabela global `users` + log de exclusão (LGPD)
As a **operador da plataforma responsável por dados de clientes**,
I want **garantir que nenhum módulo de negócio acesse `users` sem escopo de tenant e que exclusões de conta deixem rastro**,
so that **não haja vazamento cross-tenant e a plataforma cumpra a LGPD mesmo em operações destrutivas**.

#### Acceptance Criteria
1. Auditoria do código confirma que nenhum módulo de negócio consulta `users` via `get_db` sem filtro de tenant; qualquer caso encontrado é corrigido (ou coberto por guarda explícita).
2. A exclusão de conta grava um **log de plataforma fora do tenant** (não purgado com os `audit_entries` do tenant), registrando quem/quando/qual tenant.
3. O comportamento de purga atômica dinâmica existente é preservado (sem conta-zumbi).

#### Integration Verification
- IV1: Delete de conta continua atômico e purga todas as tabelas de negócio do tenant (teste existente passa).
- IV2: Isolamento cross-tenant permanece (e2e no Postgres real: João não vê dados da Maria).
- IV3: O log de plataforma sobrevive à exclusão do tenant.

### Story 1.3 — Idle timeout LGPD (30 min)
As a **usuário logado no e1p**,
I want **ser deslogado após 30 minutos de inatividade**,
so that **sessões esquecidas não fiquem abertas, cumprindo a LGPD**.

#### Acceptance Criteria
1. Tracking de atividade / refresh token curto implementado; após 30 min sem atividade, a sessão é encerrada e o usuário é levado ao login.
2. O frontend (`ProtectedLayout`) trata o timeout com aviso e logout limpo; a experiência não quebra fluxos ativos legítimos.
3. A solução não afrouxa a segurança do JWT atual (7 dias) para os demais casos.

#### Integration Verification
- IV1: Login/logout e rotas protegidas continuam funcionando (testes de auth passam).
- IV2: Não há impacto em endpoints públicos (propostas/contratos/páginas) que não exigem login.
- IV3: Sem regressão de performance no fluxo de refresh.

### Story 1.4 — Forçar troca de senha do Super Admin no 1º login + validar guard de segredos
As a **administrador de plataforma (Master)**,
I want **ser obrigado a trocar a senha semeada no primeiro acesso e ter o boot bloqueado com segredos fracos**,
so that **a conta de maior privilégio não fique com credencial default em produção**.

#### Acceptance Criteria
1. O Super Admin semeado nasce com `must_reset_password=True`; o primeiro login bloqueia o app até a troca (reusa o fluxo `FirstAccessPage`/`change-password` já existente).
2. O guard de produção (`_guard_production_secrets`) é verificado no gate de release: boot recusa `JWT_SECRET` fraco/default (<32), `ANTHROPIC_API_KEY` ausente e `SUPER_ADMIN_PASSWORD` default.
3. Um item de checklist de release documenta essa verificação.

#### Integration Verification
- IV1: Login normal de usuários comuns e o fluxo de convite/1º acesso continuam funcionando.
- IV2: Em dev (sem produção), o comportamento permissivo atual é preservado (não quebra o ciclo local).
- IV3: Testes existentes de Super Admin e do guard de boot passam.

---

## 7. Epic 2: Integrações Reais (Dinheiro & Comunicação)

**Epic Goal:** trocar os stubs conscientes por provedores reais para que o dinheiro entre de fato (gateway
com boleto/Pix registrado e webhook confiável creditando o split) e as mensagens sejam realmente entregues
(e-mail transacional e WhatsApp), tornando verídicas as promessas do produto — sem quebrar a graceful
degradation nem os fluxos existentes.

**Integration Requirements:** cada provedor é plugado **por trás das interfaces internas existentes**
(`core/email.py`, `core/whatsapp.py`, contrato do webhook `POST /receivables/webhook`), preservando os
chamadores e testes atuais (CR4). Idempotência e locks `FOR UPDATE` da Carteira/Contas a Receber devem
permanecer intactos. Dependência externa (contas/aprovações Meta e gateway) deve ser iniciada cedo.

### Story 2.1 — Provedor de e-mail transacional (SMTP/SES)
As a **profissional e seus clientes/funcionários convidados**,
I want **receber de verdade os e-mails de recuperação de senha e de convite (com a senha temporária)**,
so that **o onboarding e a recuperação de acesso funcionem em produção sem expor tokens/senhas na resposta**.

#### Acceptance Criteria
1. `core/email.py` passa a enviar via provedor real (SMTP genérico ou SES), configurado por `SMTP_HOST` e credenciais em `.env.prod`/SSM; sem chave configurada, mantém o comportamento de log (graceful degradation).
2. Os fluxos existentes passam a entregar por e-mail: link de recuperação (`/auth/forgot-password`) e senha temporária de convite de conta/funcionário (`/admin/accounts`, `/admin/accounts/{tenant_id}/users`).
3. Em produção, o corpo da resposta **não** retorna mais `dev_reset_token` nem `temp_password` (só em dev).

#### Integration Verification
- IV1: Os fluxos de convite/1º acesso e recuperação de senha continuam funcionando ponta a ponta (testes existentes passam; token/senha deixam de vazar no corpo em prod).
- IV2: Sem chave de e-mail configurada, os endpoints não quebram (falham fechado/log).
- IV3: Sem regressão de latência perceptível nos endpoints de auth/convite.

### Story 2.2 — Gateway de pagamento real (Asaas / Mercado Pago)
As a **dono da empresa de 1 pessoa e a plataforma**,
I want **gerar boleto/Pix registrado de verdade e receber o webhook real de compensação**,
so that **o dinheiro entre e o split (40/30/20) seja creditado na Carteira automaticamente**.

#### Acceptance Criteria
1. Um gateway (Asaas ou Mercado Pago — decisão via ADR no início do épico) gera boleto/Pix **registrado** (substituindo o layout-stub do `core/boleto.py`), com linha digitável/QR válidos e vencimento correto.
2. `POST /receivables/webhook` recebe o webhook real de compensação, valida `GATEWAY_WEBHOOK_SECRET`, e credita a Carteira com o split, liberando o valor para saque no Financeiro.
3. A baixa é **idempotente** e protegida contra baixa dupla/crédito duplicado (preserva os locks `FOR UPDATE` existentes); pagamentos duplicados do gateway não geram dupla transação.
4. Cada ocorrência recorrente gera seu próprio boleto/cobrança registrado (mantém o comportamento de recorrência atual).

#### Integration Verification
- IV1: O efeito dominó existente (orçamento/proposta aprovada → cobrança → contrato) e a recorrência continuam funcionando com o gateway real.
- IV2: O split e os saldos da Carteira (disponível/a receber/sacado) e o `platform_earnings` batem após a baixa real (testes de Carteira/Contas a Receber passam).
- IV3: Isolamento por tenant intacto; webhook não permite cruzar tenants nem baixar cobrança de outro tenant.

### Story 2.3 — WhatsApp Cloud API
As a **dono da empresa de 1 pessoa**,
I want **que as notificações hoje apenas `logged` (cobrança com IA, funil, mover card, vencimentos) sejam entregues por WhatsApp**,
so that **a comunicação com clientes aconteça de verdade e não seja uma promessa silenciosa**.

#### Acceptance Criteria
1. `core/whatsapp.py` passa a enviar via WhatsApp Cloud API (Meta), usando `WHATSAPP_TOKEN` + `WHATSAPP_PHONE_ID`; sem chave, mantém o log (graceful degradation).
2. É adicionado um **campo de telefone do owner/destinatário** (migration aditiva) — hoje o recipient usa o e-mail como placeholder; as notificações passam a usar o telefone real.
3. As mensagens existentes (cobrança amigável com IA, mensagens de funil, `crm.client.moved`, vencimentos) são entregues com o conteúdo já gerado, respeitando o anonimizador quando a IA compõe o texto.

#### Integration Verification
- IV1: O barramento de notificações (`notifications`, `crm.client.moved`) e a "Cobrar com IA" continuam funcionando; sem chave, nada quebra (só loga).
- IV2: Nenhum PII vai para a IA sem anonimização (Regra de Ouro nº 2 preservada na composição das mensagens).
- IV3: Envio não derruba a request de origem em caso de falha do provedor (falha fechada/log; migração para fila fica no Epic 4).

---

## 8. Epic 3: Deploy, Storage & Observabilidade

**Epic Goal:** transformar o bundle de deploy Hostinger já commitado (`59ff179`) numa esteira repetível e
segura: validar cada deploy num staging antes de produção, garantir que os testes rodem dentro da imagem
Docker (matando o drift venv↔prod), proteger os dados com backups offsite testados, e ter visibilidade
mínima de disponibilidade — além de dar destino durável aos arquivos.

**Integration Requirements:** manter 12-factor para não acoplar à VPS específica (caminho AWS aberto). A app
sempre roda como papel non-superuser `e1p_app` (RLS válida). Nenhuma mudança pode quebrar os ~252 testes
existentes; o CI passa a ser gate obrigatório antes do deploy.

### Story 3.1 — Ambiente de staging espelhando produção
As a **operador do go-live**,
I want **um ambiente de staging com a mesma imagem de produção e dados sintéticos**,
so that **cada deploy seja validado antes de ir para produção, sem risco ao dado real**.

#### Acceptance Criteria
1. Existe um staging que sobe a mesma imagem/compose de produção (`docker-compose.prod.yml` ou `.traefik.yml`), com `.env` próprio e dados sintéticos (seed), isolado da produção.
2. O fluxo de release documenta: deploy em staging → validação (smoke test dos módulos-chave) → promoção para produção.
3. Staging usa segredos próprios e nunca aponta para o banco/credenciais de produção.

#### Integration Verification
- IV1: Subir o staging roda `alembic upgrade head` + seed e responde no `/health` (mesma topologia do dev/prod).
- IV2: O papel `e1p_app` non-superuser é criado no staging (RLS válida), igual à produção.
- IV3: Nenhuma configuração de staging afeta produção (redes/volumes/segredos isolados).

### Story 3.2 — CI testando a imagem Docker de produção
As a **operador do go-live**,
I want **um CI que rode a suíte de testes DENTRO da imagem Docker de produção e o e2e de isolamento cross-tenant**,
so that **o drift venv↔produção seja pego antes do deploy e o isolamento RLS seja garantido automaticamente**.

#### Acceptance Criteria
1. O CI builda a imagem de produção e roda a suíte completa (`scripts/check.sh`/pytest) **dentro** dela, não só no venv local.
2. O CI executa o teste de isolamento cross-tenant no Postgres real (testcontainers), hoje só validado manualmente.
3. O CI é **gate obrigatório**: um deploy só é promovido se o CI passar; falha bloqueia o deploy.

#### Integration Verification
- IV1: Todos os ~252 testes existentes continuam passando na imagem de produção.
- IV2: O teste de isolamento reproduz o cenário "João não vê dados da Maria" no Postgres real.
- IV3: O gate não introduz falso-positivo que trave deploys legítimos (pipeline estável).

### Story 3.3 — Backups automatizados + offsite + restore testado
As a **dono do negócio**,
I want **backups diários do Postgres copiados para fora da VPS, com restauração testada**,
so that **os dados sobrevivam à perda do servidor inteiro**.

#### Acceptance Criteria
1. Um job diário faz `pg_dump` (gzip) do banco de produção (evoluindo o cron do `HOSTINGER-DEPLOY.md`).
2. Os dumps são copiados para storage **offsite** (S3/outro), com retenção definida.
3. Um procedimento de **restauração** é executado e validado ao menos uma vez (restore em staging a partir de um dump), documentado no runbook.

#### Integration Verification
- IV1: O backup roda sem interromper a aplicação em produção.
- IV2: O restore em staging reconstrói o banco íntegro (RLS/papel `e1p_app` preservados).
- IV3: A cópia offsite existe e é acessível (não fica só na VPS).

### Story 3.4 — Monitoramento e alertas
As a **operador do go-live**,
I want **monitorar disponibilidade (health da API, TLS, disco, restart de container) com alerta acionável**,
so that **eu saiba de uma queda antes do cliente e possa reagir**.

#### Acceptance Criteria
1. Há monitoramento de uptime/health da API (`/health`) e da validade do TLS (Caddy/Traefik), com alerta (ex.: Uptime Kuma + notificação).
2. Sinais básicos de host são observados: disco e reinícios de container.
3. Um alerta chega por um canal acionável (e-mail/WhatsApp/Telegram) quando um check falha.

#### Integration Verification
- IV1: O monitoramento não impacta a performance da aplicação (checks leves).
- IV2: Um teste de queda simulada (parar o container) dispara o alerta.
- IV3: Custo do monitoramento respeita o guard-rail (NFR3) — solução barata/self-hosted preferida.

### Story 3.5 — Storage durável de anexos (object storage S3-compatível)
As a **dono do negócio**,
I want **mover os anexos de bytes-no-Postgres para object storage isolado por tenant**,
so that **o banco/backup não inche e os arquivos escalem com segurança**.

#### Acceptance Criteria
1. O módulo de Anexos passa a persistir os arquivos em object storage S3-compatível (mantendo `owner_type`/`owner_id`/`label` e o isolamento por tenant), em vez de `LargeBinary` no Postgres.
2. Upload, listagem, download e delete continuam funcionando pela mesma interface (componente `Attachments.tsx` e endpoints atuais inalterados no contrato — CR1/CR4).
3. Anexos existentes são migrados (ou plano de migração documentado); o download de anexos antigos continua funcionando.

#### Integration Verification
- IV1: Contas a Pagar/Receber (boleto/contrato) e a Agenda (anexos do evento) continuam exibindo/baixando os arquivos.
- IV2: Isolamento por tenant preservado (um tenant não acessa arquivo de outro).
- IV3: O tamanho do dump do Postgres cai após a migração (validar no backup).

---

## 9. Epic 4: Backlog Pós-Lançamento (NÃO bloqueante)

**Epic Goal:** consolidar as dívidas documentadas que **não impedem o go-live** para priorização depois do
lançamento. Nenhuma destas histórias bloqueia produção; todas têm um comportamento atual aceitável (stub,
campo manual, URL, ou endpoint manual). Escopo estritamente derivado do CLAUDE.md §6/§6.1.

**Integration Requirements:** cada item é aditivo e opcional; ao ser puxado, deve seguir o fluxo de qualidade
(§5) e não regredir o que já funciona.

### Story 4.1 — Google Meet/Calendar OAuth
As a **dono da empresa de 1 pessoa**,
I want **gerar links de Meet automaticamente via OAuth Google (Calendar API)**,
so that **eu não precise colar o link manualmente na Agenda**.

#### Acceptance Criteria
1. Fluxo OAuth Google (Cloud project + Calendar API) conecta a conta do owner quando ele fornecer as credenciais.
2. Eventos da Agenda passam a gerar Meet automaticamente (substituindo o campo manual + botão que abre `meet.google.com/new`).
3. Sem credenciais Google, o comportamento manual atual é preservado.

#### Integration Verification
- IV1: A Agenda (calendário, conflitos, detalhe do evento) continua funcionando sem Google conectado.
- IV2: Nenhuma regressão nos eventos existentes (com link manual).
- IV3: Credenciais Google tratadas como segredo (não expostas ao frontend).

### Story 4.2 — Upload real de logo e imagens
As a **dono da empresa de 1 pessoa**,
I want **subir logo e imagens de verdade (Brand Kit, propostas, carrossel, sites) em vez de colar URL**,
so that **eu não dependa de hospedar imagens externamente**.

#### Acceptance Criteria
1. Brand Kit, propostas, carrossel e sites aceitam upload real de imagem/logo (reusando a camada de storage do Epic 3.5), mantendo a prévia ao vivo.
2. Campos de URL antigos continuam aceitos (retrocompatível) durante a transição.
3. O reuso de Brand Kit (proposta/carrossel herdam cores/logo) continua funcionando com o upload real.

#### Integration Verification
- IV1: Propostas/carrosséis/sites existentes (com URL) continuam renderizando.
- IV2: Isolamento por tenant no storage preservado.
- IV3: Guarda de esquema de `<img src>` (segurança já existente) mantida.

### Story 4.3 — Worker durável + fila (tick do funil + envios assíncronos)
As a **operador da plataforma**,
I want **um worker durável (cron/SQS) que processe o `tick` do funil e os envios assíncronos**,
so that **as esperas do funil e as notificações não dependam de chamada manual nem bloqueiem a request**.

#### Acceptance Criteria
1. Um worker/cron durável dispara `POST /funnels/runs/tick` periodicamente (hoje é endpoint manual/tela), retomando esperas vencidas de forma idempotente.
2. Os envios síncronos no request (ex.: WhatsApp ao mover card) migram para fila (SQS ou equivalente barato).
3. Auto-enroll por evento (lead criado/tag aplicada via `core/events`) é avaliado como próximo passo (documentado, não obrigatório nesta story).

#### Integration Verification
- IV1: O motor de automação do funil (enroll→espera→tick→done) continua funcionando e idempotente.
- IV2: Falha de envio não derruba a request de origem.
- IV3: Custo do worker/fila respeita o guard-rail (NFR3).

### Story 4.4 — Wildcard de subdomínio por tenant (TLS DNS-01)
As a **plataforma white-label**,
I want **servir cada tenant em seu subdomínio (`joaosilva.e1p.com`) com TLS wildcard**,
so that **o white-label por subdomínio funcione em produção**.

#### Acceptance Criteria
1. TLS wildcard (`*.e1p.com`) via desafio DNS-01 (Caddy com plugin de provedor DNS) configurado.
2. O roteamento por subdomínio resolve o tenant correto (mantendo o isolamento RLS).
3. O go-live single-domain atual continua funcionando durante a transição.

#### Integration Verification
- IV1: O domínio único atual permanece acessível.
- IV2: Isolamento por tenant preservado no roteamento por subdomínio.
- IV3: Emissão/renovação de certificado wildcard validada.

### Story 4.5 — Endurecimentos e refinamentos diversos
As a **mantenedor do sistema**,
I want **fechar as dívidas menores de segurança/manutenção não bloqueantes**,
so that **o sistema fique mais robusto e coeso após o lançamento**.

#### Acceptance Criteria
1. Enumeração de e-mail no `/register` reavaliada (fluxo de confirmação de e-mail).
2. Geração de tipos TS a partir do OpenAPI do FastAPI (elimina a manutenção manual do `shared-types`).
3. Rastro da IA propagado na Agenda (`is_ai` real quando a camada de ações de IA existir) e normalização de fuso por tenant (janela do dia/`all_day`).

#### Integration Verification
- IV1: Cadastro/login e o contrato `shared-types` continuam funcionando (sem quebra do contrato).
- IV2: As correções de fuso já feitas (all-day por data de calendário) não regridem.
- IV3: Nenhuma regressão nos testes existentes.

### Story 4.6 — Dívidas menores por módulo
As a **product owner**,
I want **um repositório organizado das dívidas específicas por módulo listadas no CLAUDE.md**,
so that **elas sejam priorizadas por valor/risco após o lançamento**.

#### Acceptance Criteria
1. As dívidas por módulo do CLAUDE.md §6 são catalogadas como itens de backlog: estorno/reversão de `platform_earnings`, OCR de boleto, PDF assinado com hash/carimbo, régua de cobrança + juros/multa, antecipação de recebíveis, checkout público real, área de membros real, entrega automática de infoproduto, rate-limit em rotas públicas, PDF de orçamento, "Documentos" como conceito próprio na Ficha 360°, relatório .docx do Jurídico, versionamento de documentos jurídicos.
2. Cada item recebe classificação valor/risco para priorização (via @po).
3. Nenhum item é implementado nesta story (é catalogação); a implementação vira stories próprias quando priorizadas.

#### Integration Verification
- IV1: Nenhuma mudança de código nesta story (apenas backlog) — sem risco ao sistema existente.
- IV2: O catálogo referencia a origem exata no CLAUDE.md §6 (rastreabilidade).
- IV3: Itens já bloqueantes não são rebaixados para cá por engano (consistência com a seção 5.2).

---

## 10. Premissas e decisões do PM (modo YOLO — sem elicitação interativa)

Este PRD foi gerado autonomamente. As decisões abaixo foram tomadas pelo PM e devem ser confirmadas pelo
dono do produto; se alguma premissa estiver errada, o escopo/sequenciamento pode mudar.

- **[AUTO-DECISION] Alvo de deploy para o go-live → VPS Hostinger** (com Traefik compartilhado em
  `e1p.doroeventos.com.br`, per commit `59ff179` e `HOSTINGER-DEPLOY.md`). *Motivo:* é o esforço de deploy
  mais recente e concreto; o caminho AWS (ADR 0001) permanece documentado como evolução futura, sem
  bloquear o lançamento. Manter 12-factor para não acoplar à VPS.
- **[AUTO-DECISION] Gateway de pagamento é BLOQUEANTE para go-live monetizado.** *Motivo:* o modelo de
  negócio É o split de pagamento; sem gateway real o produto não captura receita. *Premissa:* existe a
  opção de soft-launch dos módulos operacionais (Agenda/CRM/Jurídico/documentos) antes do gateway, dada a
  graceful degradation — a decisão de faseamento fica com o dono do produto.
- **[AUTO-DECISION] E-mail transacional é BLOQUEANTE.** *Motivo:* recuperação de senha e entrega de senha
  temporária de convite dependem dele; hoje o token/senha volta no corpo da resposta (aceitável só em dev).
- **[AUTO-DECISION] WhatsApp classificado como BLOQUEANTE-LEVE (fast-follow).** *Motivo:* as notificações
  degradam com graça (`logged`); dá para ir ao ar sem entrega real e plugar logo em seguida, desde que a UI
  não prometa entrega que não acontece. Também depende de aprovação de template pela Meta (risco de prazo).
- **[AUTO-DECISION] Storage S3 para anexos classificado como BLOQUEANTE-LEVE/faseável.** *Motivo:* o prod
  compose já usa volumes nomeados (`uploads_data`, `generated_data`); anexos-como-bytes-no-Postgres funciona
  em baixo volume, mas incha o DB/backup. Recomendo migrar antes de crescer, mas não travar o go-live inicial
  se o volume for baixo — monitorar o tamanho do backup.
- **[AUTO-DECISION] Escolha específica do gateway (Asaas vs Mercado Pago) e do provedor de e-mail (SMTP
  genérico vs SES) NÃO foi decidida aqui.** *Motivo:* exige input comercial/credenciais do dono; registrar
  como decisão a formalizar em ADR no início do Epic 2.
- **[AUTO-DECISION] White-label por subdomínio de tenant (`*.e1p.com`) fica FORA do go-live inicial (P4).**
  *Motivo:* o `HOSTINGER-DEPLOY.md` faz o lançamento em 1 domínio único; wildcard TLS exige desafio DNS-01
  (backlog). Confirmar se o go-live pode ser single-domain — se o subdomínio por tenant for requisito de
  lançamento, isso vira bloqueante e sobe para o Epic 3.
- **[AUTO-DECISION] Estrutura em 3 épicos bloqueantes + 1 de backlog** (em vez de épico único). *Motivo:*
  workstreams substanciais e distintos; melhor sequenciamento e ownership. Contraria o default do template
  (épico único) conscientemente.
- **[AUTO-DECISION] `document-project` não foi executada.** *Motivo:* CLAUDE.md + ADR + guias de deploy dão
  cobertura suficiente. Recomendo rodar depois se for preciso um inventário técnico formal por módulo.

### Riscos/ambiguidades assumidos
- **Ambiguidade de alvo de deploy (AWS vs Hostinger):** resolvida assumindo Hostinger como alvo de go-live
  (P1). Se o dono preferir AWS Fase A, o Epic 3 muda de infra (mas o escopo lógico — staging, CI, backups,
  monitoramento — permanece).
- **Faseamento monetização vs soft-launch:** deixado como decisão do dono (pode ir ao ar operacional antes
  do gateway).
- **Escopo de chaves de integração (plataforma vs por tenant):** a tela de config de integrações precisa
  definir se as chaves (gateway/WhatsApp) são globais da plataforma ou por tenant white-label — decisão de
  produto pendente, sinalizada no Epic 2.
