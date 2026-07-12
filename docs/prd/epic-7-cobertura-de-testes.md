# Epic 7: Cobertura de Testes — Caminho Feliz / Caminho Infeliz (P1)

> **Classificação:** DÍVIDA DE QUALIDADE (pós-go-live) — cobertura de testes/infra de testes/CI (NÃO é domínio de negócio novo).
> **Sequenciamento:** **independente** dos Epics 5 (inteligência financeira) e 6 (robustez de plataforma) — pode correr
> em paralelo; não depende de dado financeiro nem de storage. **Item 3/Story 7.1 tem adjacência temática com o Epic 6**
> ("Segurança de CI"): as duas mexem no `.github/workflows/ci.yml` — coordenar com @devops para não conflitar jobs.
> **Por que epic próprio:** os 5 itens P1 nascem de **uma única auditoria** (o QA Gate de cobertura,
> `docs/qa/test-coverage-gate-2026-07-11.md`) e compartilham **um tema coeso**: o projeto não foi originalmente construído
> com a disciplina de "1 caminho feliz + 1 caminho infeliz" por unidade funcional, e este epic fecha esse gap de forma
> rastreável. Diluí-los no Epic 6 (Higiene de Storage & Segurança de CI) quebraria a coesão temática por epic — a mesma
> convenção (Epics 1–4) que o próprio Epic 6 invocou para não se misturar ao epic financeiro.
> Fonte: **QA Gate** [`../qa/test-coverage-gate-2026-07-11.md`](../qa/test-coverage-gate-2026-07-11.md) (17 itens auditados
> por 3 agentes `@qa`, ratificado por @pm em 2026-07-11); `CLAUDE.md` (sistema existente).

## Contexto do sistema existente (para o @sm)
O e1p é 100% conteinerizado (FastAPI + PostgreSQL 16 com RLS; React 18 + Vite + TypeScript + Vitest). A auditoria de
cobertura apontou dois veredictos e cinco P1:

- **Backend — CONCERNS:** 24/24 módulos de negócio têm caminho feliz e infeliz reais (status codes, RLS cross-tenant,
  validação de input). Os gaps P1 estão em **duas funções de segurança** (Regras de Ouro nº 1 e nº 2), não nos módulos.
- **Frontend — FAIL:** 16 de 17 features têm **zero** testes; falta até a **infraestrutura de DOM** (`jsdom` +
  `@testing-library`) para testar componentes — hoje só lógica pura é testável no `apps/web`.

Ativos centrais para este epic:
- **CI existente** (`.github/workflows/ci.yml`): jobs `test-in-prod-image` (builda a imagem de produção e roda `ruff` +
  `pytest` dentro dela) e `cross-tenant-rls` (sobe `postgres:16-alpine` via testcontainers e valida "João não vê dados
  da Maria" como papel non-superuser `e1p_app`). **Story 7.1 endurece este pipeline** para que os caminhos infelizes de
  RLS **nunca** sejam pulados em silêncio.
- **Anonimizador** (`apps/api/app/core/anonymizer.py`): substitui PII por placeholders ANTES de ir ao Claude e reinsere
  na volta (Regra de Ouro nº 2, crítico para o módulo Jurídico / segredo de justiça). `test_anonymizer.py` tem happy +
  edge "sem PII", mas **nenhum caminho infeliz** (unmask com placeholder órfão / texto corrompido).
- **Vitest no `apps/web`**: configurado, mas **sem DOM testing lib** — nenhuma página/hook/form é testável hoje.

**Regras de Ouro relevantes:** nº 1 (isolamento por RLS — Story 7.1), nº 2 (anonimizador antes da IA — Story 7.2),
nº 5 (não quebrar o que funciona — rodar `scripts/check.sh` + os 3 agentes de QA a cada mudança).

## Epic Goal
Fechar os **5 gaps P1** do QA Gate de cobertura, na ordem ratificada pelo @pm (risco vs. dependência): garantir que os
caminhos infelizes das **duas Regras de Ouro de segurança** (RLS e anonimizador) estejam realmente exercitados e não
puláveis, e **desbloquear + iniciar** a cobertura de testes do frontend (que hoje é zero), começando pelos fluxos de
maior risco de negócio (entrada/`auth` e dinheiro/contrato). Sem quebrar os ~252 testes existentes nem o isolamento de
tenant.

## Integration Requirements
Story 7.1 **estende** `.github/workflows/ci.yml` (coordenar com Epic 6 / @devops — mesmo arquivo) sem substituir os jobs
existentes. Story 7.2 adiciona testes ao `apps/api/tests` sem alterar a assinatura pública do `core/anonymizer`. Story
7.3 adiciona **apenas** dev-dependencies e config de teste ao `apps/web` (nenhuma dependência de runtime, nenhum bundle
de produção afetado). Stories 7.4 e 7.5 dependem de 7.3 (a infra de DOM). Custo respeita o guard-rail (ferramentas
open-source; Regra de Ouro nº 4). Nenhuma mudança quebra os testes existentes nem o isolamento de tenant (Regra nº 5).

---

## Story 7.1 — CI garante os caminhos infelizes de RLS no Postgres real (sem skip silencioso)
> Origem: QA Gate item **3** (P1, Alto/Alto — Regra de Ouro nº 1). Adjacência com Epic 6 (Segurança de CI) — mesmo `ci.yml`.

As a **mantenedor da plataforma**,
I want **que os testes de isolamento de tenant (`test_rls_isolation`, `test_*_rls.py`) FALHEM o CI quando o Postgres real
(testcontainers/Docker) não subir, em vez de serem pulados em silêncio**,
so that **o isolamento de tenant (Regra de Ouro nº 1, "sagrado") nunca tenha um falso senso de segurança — um caminho
infeliz de RLS que não roda é pior do que um que falha visivelmente**.

### Acceptance Criteria (alto nível — @sm detalha no `*draft`)
1. O job `cross-tenant-rls` (ou equivalente) garante, de forma explícita, que os testes de RLS **executaram de fato**
   (ex.: falha dura se o Postgres/testcontainers não subir; nenhum `skip` silencioso mascarando ausência de cobertura).
2. Um marcador/contagem confirma que o conjunto de testes marcados como "RLS/Postgres-only" foi **coletado e rodado**
   (não zero) — o CI vira vermelho se esse conjunto for pulado por indisponibilidade de Docker.
3. Coexiste com os jobs existentes (`test-in-prod-image`, `cross-tenant-rls`) sem quebrá-los; documenta a garantia para
   o @devops promover a bloqueante em branch protection.

### Integration Verification
- IV1: Os jobs existentes continuam passando e o CI segue rodando em `push`/`pull_request` para `main`.
- IV2: Ferramentas já em uso (testcontainers/`postgres:16-alpine`) — sem custo novo (Regra de Ouro nº 4).
- IV3: Simular indisponibilidade do Postgres faz o CI **falhar** (não passar com testes pulados); `scripts/check.sh` +
  os 3 agentes de QA passam localmente.

## Story 7.2 — Caminho infeliz do anonimizador (unmask com placeholder órfão / texto corrompido)
> Origem: QA Gate item **2** (P1, Alto/Alto — Regra de Ouro nº 2).

As a **responsável pela segurança do módulo Jurídico**,
I want **testes de caminho infeliz para o `core/anonymizer` (desanonimização com placeholder órfão, mapa incompleto,
texto corrompido/adulterado no retorno da IA)**,
so that **a função que protege o segredo de justiça (Regra de Ouro nº 2) tenha rede de segurança contra vazamento de PII
ou corrupção de documento, não só o caminho feliz + o edge "sem PII" que já existem**.

### Acceptance Criteria (alto nível — @sm detalha no `*draft`)
1. Testes adversariais cobrem: placeholder presente no texto de volta **sem** entrada no mapa (órfão); mapa parcial
   (nem todo placeholder resolve); texto de retorno adulterado/truncado — o comportamento esperado é **fail-safe** (não
   reinsere PII errada, não estoura silenciosamente).
2. Confirma que **nenhuma PII real** escapa quando o par mask/unmask é inconsistente (invariante de segurança explícito).
3. Não altera a assinatura pública do `core/anonymizer`; só adiciona testes em `apps/api/tests`.

### Integration Verification
- IV1: Os testes existentes de `test_anonymizer.py` (happy + "sem PII") continuam passando.
- IV2: O fluxo do módulo Jurídico (anonimiza → IA → desanonimiza) permanece intacto (nenhuma regressão de comportamento).
- IV3: `scripts/check.sh` + os 3 agentes de QA passam.

## Story 7.3 — Setup de `jsdom` + `@testing-library/react` no `apps/web` (desbloqueio)
> Origem: QA Gate item **1** (P1, Alto/Alto — pré-requisito de TODO o frontend). **Bloqueia 7.4 e 7.5.**

As a **desenvolvedor do frontend**,
I want **a infraestrutura de teste de componentes (`jsdom` + `@testing-library/react` + config no Vitest) instalada e um
teste-piloto verde**,
so that **páginas, hooks e formulários do `apps/web` passem a ser testáveis — hoje só lógica pura é, e sem isso nenhum
item de cobertura de UI (7.4, 7.5 e os P2–P4 do catálogo) pode começar**.

### Acceptance Criteria (alto nível — @sm detalha no `*draft`)
1. `apps/web` ganha, como **dev-dependencies**, o ambiente `jsdom` + `@testing-library/react` (+ `user-event` /
   `jest-dom` conforme o padrão), com a config do Vitest apontando para o ambiente DOM.
2. Um **teste-piloto** renderiza um componente real simples e faz uma asserção de DOM (verde) — prova que a infra funciona
   ponta a ponta e serve de modelo para as próximas stories.
3. Nenhuma dependência de **runtime** nem o bundle de produção são afetados; `pnpm --filter @e1p/web build` segue igual.

### Integration Verification
- IV1: O build de produção do `apps/web` (nginx estático) permanece inalterado; nada novo entra no bundle final.
- IV2: Ferramentas open-source (jsdom/testing-library) — sem custo novo (Regra de Ouro nº 4).
- IV3: `scripts/check.sh` (lint + types + testes) passa com o teste-piloto incluído.

## Story 7.4 — Testes de UI da feature `auth` (login/registro)
> Origem: QA Gate item **4** (P1, Alto/Alto — portão de entrada). **Depende de 7.3.**

As a **usuário do produto**,
I want **testes de caminho feliz e infeliz na UI de `auth` (formulário, validação de campos, redirecionamento pós-login,
erro de credencial, troca de senha no 1º acesso)**,
so that **o portão de entrada do produto — já coberto no backend, mas sem rede na camada de UI — não regrida em silêncio
e ninguém fique impossibilitado de entrar por um bug de front**.

### Acceptance Criteria (alto nível — @sm detalha no `*draft`)
1. Caminho feliz: login válido renderiza/redireciona corretamente; caminho infeliz: credencial inválida e validação de
   formulário exibem o erro esperado sem quebrar a tela.
2. Cobre o fluxo de **1º acesso** (`must_reset_password` → bloqueio até troca de senha), que é parte do portão de entrada.
3. Usa a infra de 7.3; mocka a API (sem depender do backend real) no padrão de teste de componente.

### Integration Verification
- IV1: As telas de `auth` continuam funcionando em runtime (nenhuma regressão introduzida pelos testes).
- IV2: Os testes não dependem de rede/backend vivo (determinísticos no CI).
- IV3: `scripts/check.sh` + os 3 agentes de QA passam.

## Story 7.5 — Testes de UI dos fluxos de dinheiro/contrato (`contratos`, `pagar`, `cobrancas`, `orcamentos`)
> Origem: QA Gate item **5** (P1, Alto/Alto — maior risco de negócio na UI). **Depende de 7.3.**

As a **dono da conta (advogado/médico/consultor) que movimenta dinheiro e assina contratos pelo produto**,
I want **testes de caminho feliz e infeliz na UI das 4 features financeiras/contratuais (criar cobrança, pagar conta,
gerar/assinar contrato, aprovar orçamento — com seus erros de validação)**,
so that **os fluxos de maior sensibilidade financeira e jurídica — que envolvem split de pagamento e assinatura — tenham
rede de segurança na camada de UI, equivalente à cobertura que o backend já tem**.

### Acceptance Criteria (alto nível — @sm detalha no `*draft`)
1. Para cada uma das 4 features, pelo menos **1 caminho feliz** (ação principal bem-sucedida na UI) e **1 caminho
   infeliz** (validação/erro exibido sem quebrar a tela).
2. Prioriza as interações que tocam dinheiro/assinatura (valor, vencimento, split, aceite/KYC) — não cobertura cosmética.
3. Usa a infra de 7.3 e mocka a API; pode ser dividida em mais de uma story pelo @sm/@po se o volume das 4 features pedir.

### Integration Verification
- IV1: As 4 telas continuam funcionando em runtime (nenhuma regressão).
- IV2: Testes determinísticos, sem backend vivo, no CI.
- IV3: `scripts/check.sh` + os 3 agentes de QA passam.

---

## Nota de autoridade (para @sm/@po)
Este epic foi criado por Morgan (@pm) em 2026-07-11 como desdobramento do QA Gate de cobertura
(`docs/qa/test-coverage-gate-2026-07-11.md`, ratificado no mesmo dia). Contém **apenas os 5 itens P1** (stubs de story,
não stories completas — `*draft` é do @sm). Os itens **P2–P4** do catálogo (incluindo o item 16b — Jurídico no frontend,
elevado a P3 na ratificação) **ainda não** têm stub aqui; entram como novas stories deste epic quando puxados. A criação
de epic é operação exclusiva do @pm (`.claude/rules/agent-authority.md`); a escrita das stories e o sequenciamento fino
ficam com @sm/@po. **Coordenação com o Epic 6:** a Story 7.1 e a Story 6.2 mexem no mesmo `.github/workflows/ci.yml` —
alinhar com @devops para evitar conflito de jobs.
