# Epic 7: Cobertura de Testes — Caminho Feliz / Caminho Infeliz (P1–P4)

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

## Ampliação do escopo — itens P2–P4 do mesmo QA Gate (2026-07-11)
> **Autorização:** o dono do produto autorizou fechar os **13 itens restantes** (P2+P3+P4) do **mesmo** catálogo
> de cobertura (`docs/qa/test-coverage-gate-2026-07-11.md`), agora que os 5 P1 (Stories 7.1–7.5) estão **Done**.
> Entram como Stories **7.6–7.18**, na ordem ratificada de prioridade (P2 → P3 → P4), **agrupadas em 3 trilhas
> paralelizáveis** — cada stub carrega sua nota de **Trilha** para o @sm/@po sequenciarem em paralelo.
>
> **Convenção mantida** (mesma dos stubs 7.1–7.5): são **stubs de story**, não stories completas — o `*draft` é do
> @sm. Toda evidência é **literal da auditoria** do QA Gate (Article IV — sem invenção). `quality_gate: "@architect"`
> em **todas** as 13: 7.6–7.14 tocam infra de teste/scripts de backend; 7.15–7.18 são componentes de UI seguindo o
> padrão de teste estabelecido pela Story 7.3 (já Done).
>
> | Trilha | Foco | Executor | Stories | Dependência |
> |---|---|---|---|---|
> | **A** | Backend financeiro/dados | @dev | 7.6, 7.7, 7.8, 7.9 | Nenhuma — paralelizável |
> | **B** | Backend menor | @dev | 7.10, 7.11, 7.12, 7.13, 7.14 | Nenhuma — paralelizável |
> | **C** | Frontend | @dev | 7.15, 7.16, 7.17, 7.18 | **Infra da Story 7.3 (já Done)** |

### Trilha A — Backend financeiro/dados (executor: @dev — sem dependência, paralelizável)

## Story 7.6 — Teste unitário direto + caminho infeliz do gerador de boleto (`core/boleto.py`)
> Origem: QA Gate item **6** (P2, Médio/Médio). **Trilha A — Backend financeiro/dados** (executor @dev, sem dependência).

As a **dono da conta que emite boletos financeiros**,
I want **testes unitários diretos do `core/boleto.py`, incluindo o caminho infeliz (dado inválido na geração), e não só
a cobertura indireta atual via `test_boleto_charge_generates_pdf_attachment`**,
so that **uma falha silenciosa na geração do PDF de boleto (hoje não pega) seja detectada — o fallback manual existe,
mas não sinaliza o erro**.

### Acceptance Criteria (alto nível — @sm detalha no `*draft`)
1. Teste unitário direto de `core/boleto.py` cobre o caminho feliz (gera o PDF com beneficiário/pagador/valor/vencimento/
   linha digitável) de forma **isolada**, não só via o teste de integração da cobrança.
2. Caminho infeliz: dado inválido/faltante na geração (ex.: valor/vencimento ausente ou malformado) produz erro
   **explícito**, não uma falha silenciosa que o fallback manual mascara.
3. Não altera a assinatura pública de `core/boleto.py`; só adiciona testes em `apps/api/tests`.

### Integration Verification
- IV1: O fluxo existente (cobrança `method=boleto` gera e anexa o PDF) segue funcionando; `test_boleto_charge_generates_pdf_attachment` continua verde.
- IV2: Ferramenta já em uso (`fpdf2`) — sem custo novo (Regra de Ouro nº 4).
- IV3: `scripts/check.sh` + os 3 agentes de QA passam.

## Story 7.7 — Caminho infeliz da extração de documentos (`core/extract.py`: pdf/docx/imagem/OCR)
> Origem: QA Gate item **7** (P2, Médio/Médio — "topo natural do P2"; alimenta o módulo Jurídico). **Trilha A — Backend financeiro/dados** (executor @dev, sem dependência).

As a **responsável pelo módulo Jurídico (extração de peças para a IA)**,
I want **testes que exercitem `core/extract.py` além do `.txt` — `pdf`/`docx`/imagem/OCR (pytesseract) — e o caminho
infeliz (tipo não suportado, arquivo corrompido)**,
so that **uma falha silenciosa ao extrair um PDF real (o formato mais comum de petição) seja detectada, não apenas o
caminho feliz de `.txt` que já existe**.

### Acceptance Criteria (alto nível — @sm detalha no `*draft`)
1. Caminho feliz estendido: extração de `pdf` e `docx` (e, quando aplicável, imagem via OCR/`pytesseract`) é exercitada,
   não só `.txt`.
2. Caminho infeliz: tipo de arquivo **não suportado** e arquivo **corrompido/ilegível** produzem erro/tratamento
   explícito, não uma extração silenciosamente vazia.
3. Não altera a assinatura pública de `core/extract.py`; adiciona testes em `apps/api/tests`. Se o OCR exigir `tesseract`
   no ambiente, o caso é isolável/skipável de forma **explícita** (sem skip silencioso mascarando ausência de cobertura).

### Integration Verification
- IV1: O caminho feliz de `.txt` existente e o fluxo do Jurídico (anexo → extração → anonimização → IA) permanecem intactos.
- IV2: Ferramentas já em uso (`pdfplumber`/`python-docx`/`pytesseract`) — sem custo novo (Regra de Ouro nº 4).
- IV3: `scripts/check.sh` + os 3 agentes de QA passam.

## Story 7.8 — Caminho infeliz do backfill de ledger (`test_ledger_backfill.py`: idempotência/dados inconsistentes)
> Origem: QA Gate item **9** (P2, Médio/Médio). **Trilha A — Backend financeiro/dados** (executor @dev, sem dependência).

As a **operador que roda a migração de dados financeiros (ledger)**,
I want **testes de caminho infeliz para o backfill de ledger — reexecução (idempotência) e dados parcialmente
preenchidos/inconsistentes — além do preenchimento bem-sucedido que já é validado**,
so that **rodar o script de novo sobre dados já parcialmente migrados não corrompa nem duplique lançamentos, já que
hoje só o caminho feliz é coberto**.

### Acceptance Criteria (alto nível — @sm detalha no `*draft`)
1. **Idempotência:** reexecutar o backfill sobre dados já (parcialmente) preenchidos não duplica nem corrompe
   lançamentos — resultado estável entre execuções.
2. **Dados inconsistentes/parciais:** o script trata (ou falha de forma explícita e segura) registros incompletos, sem
   deixar o ledger em estado inconsistente.
3. Adiciona os casos ao `test_ledger_backfill.py` existente sem alterar a semântica do script de migração.

### Integration Verification
- IV1: O teste de preenchimento bem-sucedido existente continua passando.
- IV2: Usa a suíte de testes existente — sem custo novo (Regra de Ouro nº 4).
- IV3: `scripts/check.sh` + os 3 agentes de QA passam.

## Story 7.9 — Teste unitário direto de `core/recurrence.py` (clamp de dia, ano bissexto)
> Origem: QA Gate item **10** (P2, Médio/Médio). **Trilha A — Backend financeiro/dados** (executor @dev, sem dependência).

As a **mantenedor da lógica de recorrência financeira (Contas a Pagar/Receber)**,
I want **testes unitários diretos do `core/recurrence.py` para os casos de borda clássicos de data (clamp de dia
31→fevereiro, ano bissexto, fim de mês), e não só a cobertura indireta via payables/receivables/projection**,
so that **os cantos de data — historicamente propensos a bug — sejam validados isoladamente, não só no fluxo de ponta a ponta**.

### Acceptance Criteria (alto nível — @sm detalha no `*draft`)
1. Teste unitário direto de `core/recurrence.advance` (ou equivalente) cobre o clamp de dia (ex.: 31 → último dia de
   fevereiro), ano bissexto e viradas de fim de mês.
2. Caminho feliz e casos de borda são exercitados de forma **isolada**, não apenas via payables/receivables/projection.
3. Não altera a assinatura pública de `core/recurrence.py`; adiciona testes em `apps/api/tests`.

### Integration Verification
- IV1: A geração de ocorrências recorrentes (Contas a Pagar/Receber, com clamp de dia) segue idêntica em runtime.
- IV2: Sem custo novo (Regra de Ouro nº 4).
- IV3: `scripts/check.sh` + os 3 agentes de QA passam.

### Trilha B — Backend menor (executor: @dev — sem dependência, paralelizável)

## Story 7.10 — Validação de payload inválido em `settings` (timezone/URL/cor malformada)
> Origem: QA Gate item **11** (P3, Baixo-Médio/Baixo). **Trilha B — Backend menor** (executor @dev, sem dependência).

As a **usuário que configura o perfil/Brand Kit da empresa**,
I want **testes de caminho infeliz de payload inválido no módulo `settings` (timezone, URL, cor malformada), além do
único negativo atual ("sem auth")**,
so that **entradas malformadas de configuração sejam rejeitadas de forma previsível, fechando o gap de validação de
input do módulo (superfície de dano baixa — configuração, não dinheiro — mas ainda um gap real)**.

### Acceptance Criteria (alto nível — @sm detalha no `*draft`)
1. Testes de payload inválido cobrem pelo menos **timezone inválido**, **URL malformada** e **cor malformada** —
   retornando o erro de validação esperado (não 500 nem persistência de lixo).
2. Complementa o caminho infeliz "sem auth" já existente, sem removê-lo.
3. Adiciona testes ao módulo `settings` em `apps/api/tests` sem alterar o contrato público dos endpoints.

### Integration Verification
- IV1: `GET/PATCH /settings/profile` (perfil + Brand Kit) segue funcionando; a herança de Brand Kit por propostas/carrossel permanece intacta.
- IV2: Sem custo novo (Regra de Ouro nº 4).
- IV3: `scripts/check.sh` + os 3 agentes de QA passam.

## Story 7.11 — Caminho infeliz genuíno do módulo `notifications` (destinatário/cliente inexistente)
> Origem: QA Gate item **13** (P3, Médio/Baixo). **Trilha B — Backend menor** (executor @dev, sem dependência).

As a **mantenedor do módulo de notificações**,
I want **um caminho infeliz genuíno no próprio módulo `notifications` — hoje enfileirar para um cliente inexistente
ainda retorna sucesso, e a única falha real coberta vive em `test_notifications_queue.py`, não no módulo em si**,
so that **o módulo tenha rede de segurança própria contra entrada inválida, não só a isolação de falha da fila
(`test_failure_is_isolated_and_recorded`)**.

### Acceptance Criteria (alto nível — @sm detalha no `*draft`)
1. Teste de caminho infeliz **no módulo `notifications`**: enfileirar/registrar notificação para um cliente inexistente
   (ou destinatário inválido) tem comportamento esperado **explícito** (rejeição ou marcação apropriada), não um
   "sucesso" silencioso.
2. Cobre o gap sem duplicar o que já existe em `test_notifications_queue.py` (isolação de falha na entrega).
3. Adiciona testes ao módulo `notifications` sem alterar seu contrato público.

### Integration Verification
- IV1: O fluxo de notificação existente (mover card do CRM → enfileira → worker entrega) segue funcionando; `test_failure_is_isolated_and_recorded` continua verde.
- IV2: Sem custo novo (Regra de Ouro nº 4).
- IV3: `scripts/check.sh` + os 3 agentes de QA passam.

## Story 7.12 — Caso de id inexistente em delete/update do módulo `marketing`
> Origem: QA Gate item **14** (P4, Baixo/Baixo). **Trilha B — Backend menor** (executor @dev, sem dependência).

As a **mantenedor do módulo de marketing (gerador de carrossel)**,
I want **testes de id inexistente em delete/update no módulo `marketing`, além do único negativo de input atual (clamp
de slides 3–10)**,
so that **o 404 — hoje comportamento padrão do framework, mas sem teste explícito — fique coberto e não regrida em silêncio**.

### Acceptance Criteria (alto nível — @sm detalha no `*draft`)
1. `delete`/`update` de um recurso de `marketing` com **id inexistente** retorna o 404 esperado, com teste explícito.
2. Complementa o negativo de input existente (clamp de slides 3–10), sem removê-lo.
3. Adiciona testes ao módulo `marketing` sem alterar seu contrato público.

### Integration Verification
- IV1: A geração/edição de carrossel existente segue funcionando (slides, legenda, hashtags, export).
- IV2: Sem custo novo (Regra de Ouro nº 4).
- IV3: `scripts/check.sh` + os 3 agentes de QA passam.

## Story 7.13 — Teste unitário direto de `core/ai.py` (prompt, parsing de `AIResult`, fallback)
> Origem: QA Gate item **15** (P4, Médio/Baixo). **Trilha B — Backend menor** (executor @dev, sem dependência).

As a **mantenedor da camada de IA (`core/ai.py`)**,
I want **testes unitários diretos de `core/ai.py` — montagem de prompt, parsing de `AIResult` e fallback — em vez de só
a cobertura indireta via mock nos endpoints que a usam**,
so that **a camada compartilhada por todos os módulos de IA tenha teste próprio, sem depender de cada caller exercitar o fallback**.

### Acceptance Criteria (alto nível — @sm detalha no `*draft`)
1. Teste unitário direto cobre a **montagem do prompt**, o **parsing de `AIResult`** e o **caminho de fallback** (ex.:
   sem `ANTHROPIC_API_KEY` / erro da API) de `core/ai.py`.
2. Caminho feliz (resposta parseada) e caminho infeliz (fallback) exercitados **isoladamente**, não só via os endpoints consumidores.
3. Não altera a assinatura pública de `core/ai.py`; adiciona testes em `apps/api/tests`.

### Integration Verification
- IV1: Os módulos que usam a IA (cobrança com IA, carrossel, funil, jurídico) seguem com seu comportamento de fallback intacto.
- IV2: Sem custo novo — os testes não chamam a API real (usam mock/fallback) (Regra de Ouro nº 4).
- IV3: `scripts/check.sh` + os 3 agentes de QA passam.

## Story 7.14 — Caminho infeliz do seed (`test_seed.py`: env faltando/config inválida)
> Origem: QA Gate item **17** (P4, Baixo/Baixo). **Trilha B — Backend menor** (executor @dev, sem dependência).

As a **mantenedor do bootstrap/seed da aplicação**,
I want **cobertura de caminho infeliz para o seed (env faltando/config inválida) rotulada junto ao `test_seed.py`, além
do happy + idempotência que já existem**,
so that **o gap — hoje só de organização/rotulagem, já que o negativo de config vive em `test_config.py` — fique fechado
e explícito no lugar esperado**.

### Acceptance Criteria (alto nível — @sm detalha no `*draft`)
1. O caminho infeliz de config do seed (env obrigatória faltando / config inválida) é exercitado e fica **rastreável a
   partir do `test_seed.py`** (referência/rotulagem ou caso próprio), sem duplicar desnecessariamente o que já vive em `test_config.py`.
2. Mantém os testes de happy path + idempotência do seed existentes.
3. Não altera a lógica do seed; é mudança de cobertura/organização de teste.

### Integration Verification
- IV1: O seed no boot (usado pela API ao subir) segue funcionando; os testes existentes continuam verdes.
- IV2: Sem custo novo (Regra de Ouro nº 4).
- IV3: `scripts/check.sh` + os 3 agentes de QA passam.

### Trilha C — Frontend (executor: @dev — depende da infra da Story 7.3, já Done)

## Story 7.15 — Testes de UI do núcleo do produto (`crm`, `agenda`, `cockpit`)
> Origem: QA Gate item **8** (P2, Alto/Médio). **Trilha C — Frontend** (executor @dev). **Depende da infra da Story 7.3 — já Done.**

As a **usuário que gere clientes, agenda e a visão geral do negócio**,
I want **testes de caminho feliz e infeliz na UI das 3 features de núcleo (`crm`, `agenda`, `cockpit`), hoje com zero
testes no frontend**,
so that **o núcleo de maior uso do produto — ainda que sem movimentação financeira direta — tenha rede de segurança na
camada de UI, equivalente à cobertura sólida do backend**.

### Acceptance Criteria (alto nível — @sm detalha no `*draft`)
1. Para cada uma das 3 features, pelo menos **1 caminho feliz** (interação principal na UI) e **1 caminho infeliz**
   (validação/erro exibido sem quebrar a tela).
2. Usa a infra de teste de componentes da Story 7.3 (`jsdom` + `@testing-library/react`) e mocka a API (determinístico,
   sem backend vivo).
3. Pode ser dividida em mais de uma story pelo @sm/@po se o volume das 3 features pedir.

### Integration Verification
- IV1: As telas de `crm`/`agenda`/`cockpit` seguem funcionando em runtime (nenhuma regressão).
- IV2: Testes determinísticos, sem backend vivo, no CI.
- IV3: `scripts/check.sh` + os 3 agentes de QA passam.

## Story 7.16 — Testes de UI de produto/venda (`estoque`, `produtos`, `funis`)
> Origem: QA Gate item **12** (P3, Médio/Médio). **Trilha C — Frontend** (executor @dev). **Depende da infra da Story 7.3 — já Done.**

As a **usuário que gere estoque, produtos e funis de venda**,
I want **testes de caminho feliz e infeliz na UI das features `estoque`, `produtos` e `funis`, hoje sem nenhum teste no frontend**,
so that **os módulos de produto/venda — cujo risco já é parcialmente mitigado pela cobertura sólida de backend — tenham
também rede de segurança na camada de UI**.

### Acceptance Criteria (alto nível — @sm detalha no `*draft`)
1. Para cada uma das 3 features, pelo menos **1 caminho feliz** e **1 caminho infeliz** na UI (validação/erro sem quebrar a tela).
2. Usa a infra da Story 7.3 e mocka a API (determinístico). Para `funis` (canvas React Flow), prioriza as **interações
   de negócio** (criar/configurar nó, salvar) sobre detalhes cosméticos do canvas.
3. Pode ser dividida pelo @sm/@po se o volume das 3 features pedir.

### Integration Verification
- IV1: As telas de `estoque`/`produtos`/`funis` seguem funcionando em runtime (nenhuma regressão).
- IV2: Testes determinísticos, sem backend vivo, no CI.
- IV3: `scripts/check.sh` + os 3 agentes de QA passam.

## Story 7.17 — Testes de UI da feature `juridico` (persona primária)
> Origem: QA Gate item **16b** (P3, Médio-Alto/Baixo — desmembrado do item 16 pelo @pm; persona primária = advogados). **Trilha C — Frontend** (executor @dev). **Depende da infra da Story 7.3 — já Done.**

As a **advogado (persona primária do produto) que usa o Assistente Jurídico**,
I want **testes de caminho feliz e infeliz na UI da feature `juridico` — wizard dinâmico, anexo de peças e download
`.docx` — hoje com zero testes no frontend**,
so that **o fluxo central da persona que mais usa o produto tenha rede de segurança na UI, mesmo que a segurança
(anonimização, Regra de Ouro nº 2) já seja garantida no backend**.

### Acceptance Criteria (alto nível — @sm detalha no `*draft`)
1. **Caminho feliz:** escolher uma skill → preencher o wizard dinâmico (form vindo do `wizard_config`) → gerar/baixar o
   documento renderiza e conclui na UI. **Caminho infeliz:** validação do wizard e falha graciosa de geração (ex.: sem
   chave → status `failed`) são exibidas sem quebrar a tela.
2. Cobre as interações centrais da persona: **wizard dinâmico**, **anexo de peças** (PDF/Word/imagem/txt) e **download `.docx`**.
3. Usa a infra da Story 7.3 e mocka a API (determinístico; **nenhuma PII/documento real** no teste).

### Integration Verification
- IV1: A tela `/juridico` (catálogo de skills, wizard, geração, download) segue funcionando em runtime.
- IV2: Testes determinísticos, sem backend vivo nem chamada real ao Claude.
- IV3: `scripts/check.sh` + os 3 agentes de QA passam.

## Story 7.18 — Testes de UI de conteúdo/config/admin (`marketing`, `sites`, `config`, `admin`)
> Origem: QA Gate item **16** (P4, Médio/Baixo). **Trilha C — Frontend** (executor @dev). **Depende da infra da Story 7.3 — já Done.**

As a **usuário que gere marketing, sites, configurações e administração**,
I want **testes de caminho feliz e infeliz na UI das features `marketing`, `sites`, `config` e `admin`, hoje sem nenhum
teste no frontend**,
so that **as features de menor criticidade relativa (geração de conteúdo em marketing/sites; config/admin com backend
sólido) fechem o último gap de cobertura de UI do catálogo**.

### Acceptance Criteria (alto nível — @sm detalha no `*draft`)
1. Para cada uma das 4 features, pelo menos **1 caminho feliz** e **1 caminho infeliz** na UI (validação/erro sem quebrar a tela).
2. Usa a infra da Story 7.3 e mocka a API (determinístico). Prioriza as **interações reais de negócio** (ex.: gerar
   carrossel, publicar página, editar Brand Kit, ações do Super Admin) sobre cobertura cosmética.
3. Pode ser dividida pelo @sm/@po se o volume das 4 features pedir.

### Integration Verification
- IV1: As telas de `marketing`/`sites`/`config`/`admin` seguem funcionando em runtime (nenhuma regressão).
- IV2: Testes determinísticos, sem backend vivo, no CI.
- IV3: `scripts/check.sh` + os 3 agentes de QA passam.

---

## Nota de autoridade (para @sm/@po)
Este epic foi criado por Morgan (@pm) em 2026-07-11 como desdobramento do QA Gate de cobertura
(`docs/qa/test-coverage-gate-2026-07-11.md`, ratificado no mesmo dia). **Cobre agora os 17 itens auditados (18 linhas
após o desmembramento do item 16):** os 5 P1 (Stories **7.1–7.5**, já **Done**) e os 13 restantes P2–P4 (Stories
**7.6–7.18**), adicionados por @pm em 2026-07-11 sob autorização do dono do produto (ver "Ampliação do escopo" acima),
agrupados em 3 trilhas paralelizáveis. Todos são **stubs de story**, não stories completas — o `*draft` é do @sm. A
criação de epic e a ampliação de escopo são operações do @pm (`.claude/rules/agent-authority.md`); a escrita das stories
e o sequenciamento fino ficam com @sm/@po. **Coordenação com o Epic 6:** a Story 7.1 e a Story 6.2 mexem no mesmo
`.github/workflows/ci.yml` — alinhar com @devops para evitar conflito de jobs.
