# QA Gate — Cobertura de Caminho Feliz / Caminho Infeliz (2026-07-11)

## Objetivo

Auditar **todo o código-fonte** (`apps/api` + `apps/web` + `packages/`) e validar se cada unidade
funcional tem pelo menos **1 teste de caminho feliz** e **1 teste de caminho infeliz**, conforme
solicitado diretamente pelo dono do produto — o projeto não foi originalmente desenvolvido com essa
disciplina em mente. Este documento é o artefato do QA Gate correspondente e o catálogo de
backlog para fechar os gaps encontrados.

## Metodologia

Três agentes `@qa` (auditoria read-only, sem escrita/edição) leram o **conteúdo real** das funções
de teste (nomes + asserções principais, não apenas a existência de arquivos):

1. Backend — 10 módulos de negócio (agenda, attachments, auth, chart_of_accounts, cockpit,
   contracts, cost_centers, crm, financial_intelligence, funnels).
2. Backend — 14 módulos restantes + `app/core/*.py` + testes transversais (RLS, tenancy, config,
   seed, worker, validators, etc.).
3. Frontend — as 17 features de `apps/web/src/features/`, `apps/web/src/lib/`, e os pacotes
   `packages/design-tokens` e `packages/shared-types`.

## Veredito

| Área | Veredito | Resumo |
|---|---|---|
| **Backend** (`apps/api`) | **CONCERNS** | 24/24 módulos de negócio têm caminho feliz e infeliz reais (status codes, RLS cross-tenant, validação de input). Gaps concentrados em arquivos utilitários `core/` e scripts. |
| **Frontend** (`apps/web`) | **FAIL** | 16 de 17 features têm zero testes. Falta até a infraestrutura (`jsdom`/`@testing-library`) para testar componentes — gap estrutural, não só de escrita de teste. |

## Catálogo de gaps (17 itens)

> Classificação **proposta em modo autônomo** por Orion (aiox-master orchestrator) a partir da
> auditoria `@qa`, seguindo o mesmo processo de `docs/backlog/epic-4-dividas-por-modulo.md`.
> **Pendente de ratificação por @pm/@po** antes de qualquer item virar story de implementação —
> nenhuma implementação foi feita aqui (catalogação pura).

| # | Item | Área | Evidência da auditoria | Valor (proposto) | Risco (proposto) | Prioridade | Observação |
|---|------|------|------------------------|-------------------|-------------------|------------|------------|
| 1 | Setup de `jsdom` + `@testing-library/react` no `apps/web` | Frontend (infra) | Vitest configurado mas sem DOM testing lib — hoje só lógica pura é testável | Alto | Alto | **P1** | Pré-requisito para todos os itens de feature abaixo; sem isso nenhuma página/hook/form é testável. |
| 2 | `core/anonymizer.py` sem caminho infeliz (unmask com placeholder órfão/texto corrompido) | Backend | `test_anonymizer.py` só tem happy + edge "sem PII" | Alto | Alto | **P1** | Regra de Ouro nº 2 do projeto (anonimização antes da IA, crítico para sigilo jurídico) — função de segurança sem teste adverso. |
| 3 | Testes de RLS (`test_rls_isolation`, `test_*_rls.py`) dependem de Postgres real via testcontainers | Backend (processo) | Se Docker não sobe no ambiente/CI, esses caminhos infelizes são pulados silenciosamente | Alto | Alto | **P1** | Regra de Ouro nº 1 (isolamento de tenant é sagrado) — falso senso de segurança se o CI não garantir Docker disponível. Ação: confirmar no pipeline de CI que esses testes rodam (não skip silencioso). |
| 4 | Feature `auth` (login/registro) sem nenhum teste no frontend | Frontend | 0 arquivos de teste em `features/auth` | Alto | Alto | **P1** | Fluxo de entrada do produto; já coberto no backend, mas a camada de UI (form, validação, redirecionamento) não tem rede de segurança. |
| 5 | Features `contratos`, `pagar`, `cobrancas`, `orcamentos` sem nenhum teste no frontend | Frontend | 0 arquivos de teste nessas 4 features | Alto | Alto | **P1** | Envolvem dinheiro real e assinatura de contrato (mesma sensibilidade financeira/jurídica do backend, sem cobertura na UI). |
| 6 | `core/boleto.py` sem teste unitário direto e sem caminho infeliz | Backend | Só coberto indiretamente via `test_boleto_charge_generates_pdf_attachment`; nenhum teste de dado inválido | Médio | Médio | **P2** | Geração de boleto financeiro; fallback manual existe, mas falha silenciosa na geração não é pega. |
| 7 | `core/extract.py` só testa `.txt`; sem caminho infeliz | Backend | `pdf`/`docx`/imagem/OCR (pytesseract) não exercitados; nenhum teste de tipo não suportado/arquivo corrompido | Médio | Médio | **P2** | Alimenta o módulo Jurídico (extração para IA); falha silenciosa em PDF real (o formato mais comum de petição) não é pega hoje. |
| 8 | Features `crm`, `agenda`, `cockpit` sem nenhum teste no frontend | Frontend | 0 arquivos de teste | Alto | Médio | **P2** | Núcleo do produto (gestão de cliente/agenda/visão geral), alto uso, mas sem movimentação financeira direta. |
| 9 | `test_ledger_backfill.py` sem caminho infeliz (idempotência/dados inconsistentes) | Backend | Só valida preenchimento bem-sucedido | Médio | Médio | **P2** | Script de migração de dados financeiros (ledger); reexecução com dados parcialmente preenchidos não é testada. |
| 10 | `core/recurrence.py` sem teste unitário direto (clamp de dia 31→fev, ano bissexto) | Backend | Só coberto indiretamente via payables/receivables/projection | Médio | Médio | **P2** | Lógica de data tem casos de borda clássicos (bissexto, fim de mês) que merecem teste direto, não só indireto. |
| 11 | `settings` só tem "sem auth" como caminho infeliz | Backend | Nenhum teste de payload inválido (timezone/URL/cor malformada) | Baixo-Médio | Baixo | **P3** | Validação de input ausente, mas superfície de dano é baixa (configuração, não dinheiro). |
| 12 | Features `estoque`, `produtos`, `funis` sem nenhum teste no frontend | Frontend | 0 arquivos de teste | Médio | Médio | **P3** | Módulos de produto/venda, mas com cobertura de backend sólida já mitigando parte do risco. |
| 13 | `notifications` — único caminho infeliz "genuíno" é fraco (cliente inexistente ainda enfileira com sucesso) | Backend | Falha real só coberta em `test_notifications_queue.py`, não no módulo `notifications` em si | Médio | Baixo | **P3** | Mitigado por `test_failure_is_isolated_and_recorded` na fila. |
| 14 | `marketing` — falta caso de id inexistente em delete/update | Backend | Único negativo de input é o clamp de slides (3-10) | Baixo | Baixo | **P4** | Superfície pequena, 404 é comportamento padrão do framework mesmo sem teste explícito. |
| 15 | `core/ai.py` sem teste unitário direto (montagem de prompt, parsing de `AIResult`, fallback) | Backend | Só coberto indiretamente via mock nos endpoints que o usam | Médio | Baixo | **P4** | Risco mitigado pelo fato de todo caller já mockar e testar o próprio fallback. |
| 16 | Features `marketing`, `sites`, `config`, `admin` sem nenhum teste no frontend | Frontend | 0 arquivos de teste | Médio | Baixo | **P4** | Menor criticidade relativa (marketing/sites são geração de conteúdo; config/admin com backend sólido). |
| 16b | Feature `juridico` sem nenhum teste no frontend | Frontend | 0 arquivos de teste | Médio-Alto | Baixo | **P3** | **[@pm ajustou — desmembrado do item 16, P4 → P3]** Advogados são a persona primária do produto (§1) e o Jurídico é o módulo mais sofisticado do backend (232 testes, protocolo anti-alucinação, anonimização — Regra de Ouro nº 2). O wizard dinâmico, o anexo de peças e o download `.docx` são o fluxo central dessa persona e hoje têm **zero** rede de segurança na UI. O Risco permanece Baixo porque a segurança (anonimização) é garantida no backend; o Valor sobe porque uma quebra de UX atinge diretamente quem mais usa o produto. Fica acima do bundle marketing/sites/config/admin. |
| 17 | `test_seed.py` sem caminho infeliz (env faltando/config inválida) | Backend | Só happy + idempotência | Baixo | Baixo | **P4** | Negativo de config já vive em `test_config.py`; gap é só de organização/rotulagem. |

**Legenda de prioridade:** P1 = fazer primeiro (risco/valor mais altos) · P2 = alto valor · P3 = médio
· P4 = incremental (fallback aceitável hoje).

> **Nota (@pm 2026-07-11):** o item 16 foi **desmembrado** na ratificação — 16 (marketing/sites/config/admin, P4)
> e 16b (jurídico, P3). São **17 gaps auditados**, **18 linhas** após o ajuste. Ver "Nota de autoridade".

## Nota de autoridade

Catalogação e priorização **propostas em modo autônomo por Orion (aiox-master, modo orquestração)**
a partir da auditoria de 3 agentes `@qa` (read-only). **Classificação RATIFICADA por Morgan (@pm)
em 2026-07-11**, revisada item a item como `quality_gate` desta priorização, seguindo o mesmo
precedente de `docs/backlog/epic-4-dividas-por-modulo.md` (Story 4.6). Nenhum código foi escrito ou
alterado — catalogação pura. O @pm é dono da orquestração/priorização de produto; a ratificação
resolve a lacuna original ("pendente de ratificação") — a classificação **deixa de ser rascunho**.

**Calibragem contra o negócio (CLAUDE.md §1 e §3):** os P1 foram validados contra as Regras de Ouro.
Confirmados como corretos:
- **Item 3** (RLS/isolamento de tenant) — Regra de Ouro nº 1 ("sagrado"); o risco de *skip* silencioso
  em CI é o **maior** do catálogo (falso senso de segurança no isolamento, já sinalizado no §6.1).
- **Item 2** (anonimizador antes da IA) — Regra de Ouro nº 2 (sigilo jurídico); função de segurança
  sem teste adverso.
- **Item 1** (setup jsdom + testing-library) — infra que **desbloqueia toda** a cobertura de UI.
- **Itens 4 e 5** (fluxos de `auth` e de dinheiro/contrato na UI) — mesma sensibilidade
  financeira/jurídica já coberta no backend, sem rede de segurança na camada de UI.

Os cinco P1 estão corretos e formam a base das primeiras stories.

**Ajuste do @pm nesta revisão (1 item — item 16 desmembrado):**
- **Jurídico no frontend (novo item 16b, separado do item 16):** Valor **Médio → Médio-Alto**,
  Prioridade **P4 → P3**. Motivo: **advogados são a persona primária** do produto (§1) e o Jurídico é
  o módulo mais sofisticado do backend (anonimização + protocolo anti-alucinação, 232 testes). Estava
  diluído num bundle P4 ao lado de marketing/sites/config/admin (geração de conteúdo, menor
  criticidade). A camada de UI da persona primária merece prioridade **acima** desse bundle. O **Risco
  permanece Baixo** porque a segurança (Regra de Ouro nº 2) é garantida no backend — é elevação de
  **valor**, não de risco. É a **mesma lógica estratégica** que elevou "PDF assinado" no Epic 4 (persona
  advogado como fator de decisão).

**Revisados e mantidos (demais 16 itens):** classificações coerentes com o estado do código descrito
no CLAUDE.md §6. Registro de uma **decisão de manter deliberada** (para rastreabilidade): o
**item 7 (`core/extract.py`, que alimenta o Jurídico)** foi considerado para elevação pelo mesmo motivo
de persona, mas **mantido em Médio/Médio P2** — ele já é exercitado indiretamente e a elevação do 16b
já endereça a persona primária exatamente na camada que hoje tem **zero** cobertura (a UI). Fica como
**topo natural do P2** no sequenciamento.

**Ordem recomendada dos P1 para o @sm criar as primeiras stories** (dependência vs. risco):
1. **Item 3 — CI garante RLS no Postgres real.** Regra de Ouro nº 1; maior risco (falso senso de
   segurança no isolamento de tenant); backend/processo, **sem dependência**.
2. **Item 2 — caminho infeliz do anonimizador.** Regra de Ouro nº 2; backend, **sem dependência** —
   paralelizável com o item 3.
3. **Item 1 — setup jsdom + @testing-library.** Infra que **desbloqueia TODOS** os itens de frontend;
   fazer **antes** de 4 e 5.
4. **Item 4 — testes de UI de `auth`.** Portão de entrada do produto; **depende do item 1**.
5. **Item 5 — testes de UI dos fluxos de dinheiro/contrato** (`contratos`/`pagar`/`cobrancas`/`orcamentos`).
   Maior risco de negócio na UI; **depende do item 1**.

Itens 2 e 3 (backend) não dependem da infra e guardam as duas Regras de Ouro inegociáveis — podem ser
puxados **imediatamente/em paralelo**. O item 1 é o **pivô** que desbloqueia 4 e 5.

**Esta classificação está pronta para virar stories** (não é mais rascunho): o @sm pode iniciar
`*draft` a partir dos P1 na ordem acima. O @po pode refinar o **sequenciamento fino** quando cada item
for puxado; nenhum item é "aprovado para implementação" só por constar aqui — vira story própria com
seus próprios ACs. A criação de stories é **exclusiva do @sm/@po** por `.claude/rules/agent-authority.md`.

## Próximos passos sugeridos

1. **@pm/@po** ratificam ou ajustam a priorização acima (como fizeram no Epic 4 / Story 4.6).
2. **@sm** cria stories a partir dos itens P1 primeiro. **Os 5 P1 já têm stubs de story** no epic dedicado criado pelo @pm
   em 2026-07-11: [`docs/prd/epic-7-cobertura-de-testes.md`](../prd/epic-7-cobertura-de-testes.md) — Stories **7.1** (item 3,
   CI-RLS), **7.2** (item 2, anonimizador), **7.3** (item 1, setup jsdom/testing-library), **7.4** (item 4, UI auth) e
   **7.5** (item 5, UI dinheiro/contrato), na ordem ratificada. O @sm faz o `*draft` a partir desses stubs.
3. **@dev** implementa cada story seguindo o ciclo padrão (SDC) com QA Gate ao final.
