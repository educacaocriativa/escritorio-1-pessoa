# Epic 1: Segurança & Compliance para Produção

> **Classificação:** BLOQUEANTE para o lançamento. **Sequenciamento:** primeiro epic do go-live — nada vai
> ao ar com dados reais de cliente antes deste hardening.
> Fonte: `docs/prd.md` §6; dívida técnica em `CLAUDE.md` §6.1.

## Contexto do sistema existente (para o @sm)
e1p é um SaaS multi-tenant white-label (FastAPI + PostgreSQL 16 com Row-Level Security; React + Vite; design
"Portal"). O produto está funcionalmente completo (Fases 1–5, ~252 testes). O isolamento entre tenants é
garantido **apenas** por RLS no Postgres, com a app conectando como papel non-superuser `e1p_app` (super-
usuário faz bypass de RLS). A tabela global `users` **não** tem RLS (login por e-mail é global). O fluxo de
1º acesso (`must_reset_password` + `FirstAccessPage` + `POST /auth/change-password`) já existe para usuários
comuns. O guard de produção `app/config.py::_guard_production_secrets` já bloqueia boot com segredos fracos.
A revisão de QA catalogou (CLAUDE.md §6.1) um conjunto de dívidas de segurança/LGPD marcadas como "endereçar
antes de produção" — este epic as fecha.

## Epic Goal
Fechar todas as lacunas de segurança e LGPD marcadas na revisão de QA como "endereçar antes de produção",
garantindo que nenhum dado real de cliente seja exposto sem o hardening necessário — sem regressão de
isolamento nem de funcionalidade existente.

## Integration Requirements
Todo o hardening é aditivo por trás das interfaces existentes (auth, tenancy, admin). A garantia única de
isolamento (RLS + papel `e1p_app` non-superuser) deve permanecer intacta; nenhum teste existente pode
quebrar; validação e2e de isolamento no Postgres real. Regras de Ouro do CLAUDE.md §3 são inegociáveis.

---

## Story 1.1 — Validação real de CPF/CNPJ
As a **profissional que usa o e1p e seus clientes**,
I want **que CPF/CNPJ sejam validados de verdade (dígito verificador, normalização, unicidade por tenant)**,
so that **documentos inválidos não entrem no sistema e o KYC de contratos tenha valor**.

### Acceptance Criteria
1. Um validador de CPF/CNPJ (dígito verificador + normalização) é aplicado em `/register`, cadastro/convite de usuário, criação de cliente no CRM (`document`) e KYC/assinatura de contrato.
2. Documentos inválidos são rejeitados com 422 e mensagem clara em PT-BR; documentos válidos são normalizados (só dígitos) antes de persistir.
3. Unicidade de `document` por tenant é garantida onde fizer sentido (owner/funcionário), respeitando a decisão de produto pendente sobre dedup de cliente (documentar a escolha).

### Integration Verification
- IV1: Fluxos existentes de convite/assinatura continuam funcionando com documentos válidos (testes de convite/KYC passam).
- IV2: A validação não consulta `users`/dados de outro tenant (respeita RLS); teste cross-tenant intacto.
- IV3: Sem regressão de performance perceptível nos endpoints de cadastro.

## Story 1.2 — Hardening de acesso à tabela global `users` + log de exclusão (LGPD)
As a **operador da plataforma responsável por dados de clientes**,
I want **garantir que nenhum módulo de negócio acesse `users` sem escopo de tenant e que exclusões de conta deixem rastro**,
so that **não haja vazamento cross-tenant e a plataforma cumpra a LGPD mesmo em operações destrutivas**.

### Acceptance Criteria
1. Auditoria do código confirma que nenhum módulo de negócio consulta `users` via `get_db` sem filtro de tenant; qualquer caso encontrado é corrigido (ou coberto por guarda explícita).
2. A exclusão de conta grava um **log de plataforma fora do tenant** (não purgado com os `audit_entries` do tenant), registrando quem/quando/qual tenant.
3. O comportamento de purga atômica dinâmica existente é preservado (sem conta-zumbi).

### Integration Verification
- IV1: Delete de conta continua atômico e purga todas as tabelas de negócio do tenant (teste existente passa).
- IV2: Isolamento cross-tenant permanece (e2e no Postgres real: João não vê dados da Maria).
- IV3: O log de plataforma sobrevive à exclusão do tenant.

## Story 1.3 — Idle timeout LGPD (30 min)
As a **usuário logado no e1p**,
I want **ser deslogado após 30 minutos de inatividade**,
so that **sessões esquecidas não fiquem abertas, cumprindo a LGPD**.

### Acceptance Criteria
1. Tracking de atividade / refresh token curto implementado; após 30 min sem atividade, a sessão é encerrada e o usuário é levado ao login.
2. O frontend (`ProtectedLayout`) trata o timeout com aviso e logout limpo; a experiência não quebra fluxos ativos legítimos.
3. A solução não afrouxa a segurança do JWT atual (7 dias) para os demais casos.

### Integration Verification
- IV1: Login/logout e rotas protegidas continuam funcionando (testes de auth passam).
- IV2: Não há impacto em endpoints públicos (propostas/contratos/páginas) que não exigem login.
- IV3: Sem regressão de performance no fluxo de refresh.

## Story 1.4 — Forçar troca de senha do Super Admin no 1º login + validar guard de segredos
As a **administrador de plataforma (Master)**,
I want **ser obrigado a trocar a senha semeada no primeiro acesso e ter o boot bloqueado com segredos fracos**,
so that **a conta de maior privilégio não fique com credencial default em produção**.

### Acceptance Criteria
1. O Super Admin semeado nasce com `must_reset_password=True`; o primeiro login bloqueia o app até a troca (reusa o fluxo `FirstAccessPage`/`change-password` já existente).
2. O guard de produção (`_guard_production_secrets`) é verificado no gate de release: boot recusa `JWT_SECRET` fraco/default (<32), `ANTHROPIC_API_KEY` ausente e `SUPER_ADMIN_PASSWORD` default.
3. Um item de checklist de release documenta essa verificação.

### Integration Verification
- IV1: Login normal de usuários comuns e o fluxo de convite/1º acesso continuam funcionando.
- IV2: Em dev (sem produção), o comportamento permissivo atual é preservado (não quebra o ciclo local).
- IV3: Testes existentes de Super Admin e do guard de boot passam.
