# Epic 6: Robustez de Plataforma — Higiene de Storage & Segurança de CI

> **Classificação:** FEATURE NOVA (pós-go-live) — plataforma/infra/CI (NÃO é domínio financeiro).
> **Sequenciamento:** **independente** do Epic 5 (inteligência financeira) — pode correr em paralelo; não
> depende de nenhum dado financeiro.
> **Por que epic próprio:** os itens 8–9 do pedido são de plataforma/manutenção/CI, não de domínio financeiro.
> Tematicamente seriam próximos do Epic 3 (Deploy/Storage/Observabilidade) do go-live, mas aquele pertence ao
> PRD de go-live (`docs/prd.md`, que não deve ser editado). Manter a coesão temática por epic (convenção dos
> Epics 1–4) pede um epic separado do financeiro.
> Fonte: PRD [`prd-inteligencia-financeira.md`](./prd-inteligencia-financeira.md); design de referência `AxisGov/plataforma-gestao`; `CLAUDE.md` (sistema existente).

## Contexto do sistema existente (para o @sm)
O e1p é 100% conteinerizado (FastAPI + PostgreSQL 16 com RLS; React + Vite). Dois ativos são centrais para este epic:

- **Storage S3-compatível dos Anexos** (`app/core/storage.py`): wrapper fino sobre `boto3` com `endpoint_url` configurável (AWS S3 real OU MinIO/B2/Wasabi). **Dual-write/dual-read com fallback gracioso**: se `S3_BUCKET` está vazio (dev/CI), tudo fica no Postgres (`LargeBinary`) exatamente como antes; se configurado, anexos novos sobem pro bucket (`storage_key` setado, `data=None`), e a leitura resolve a origem por linha. Isolamento de tenant também no path da chave: `tenants/{tenant_id}/attachments/{id}/{filename}` via `build_key`, em complemento à RLS do metadado. Anexos são referenciados por `owner_type` + `owner_id` (ex.: payable, charge) na tabela `attachments` (RLS). Existe backfill idempotente `python -m app.scripts.migrate_attachments_to_s3`.
- **CI existente** (`.github/workflows/ci.yml`): dois jobs — `test-in-prod-image` (builda a imagem de produção e roda `ruff check` + `pytest` DENTRO dela, pegando drift venv↔produção) e `cross-tenant-rls` (sobe `postgres:16-alpine` via testcontainers e valida "João não vê dados da Maria" como papel non-superuser `e1p_app`). Roda em `push`/`pull_request` para `main`. Hoje **não há** secret scan nem SAST no pipeline.

**Regras de Ouro relevantes:** nº 1 (isolamento por RLS + path por tenant no storage), nº 4 (custo — preferir ferramentas gratuitas/self-hosted), nº 5 (não quebrar o que funciona — rodar `scripts/check.sh` + os 3 agentes de QA).

## Epic Goal
Endurecer a plataforma em dois pontos que o produto irmão (`plataforma-gestao`) já resolve: manter o object storage **limpo** (remover anexos órfãos sem referência viva no banco, com segurança) e proteger o **pipeline** contra segredos vazados e vulnerabilidades de código (gitleaks + semgrep), estendendo o CI existente — sem risco ao dado nem falso positivo travando o time.

## Integration Requirements
A varredura de órfãos **reusa `core/storage.py`** e o padrão de fallback gracioso (não recria storage); é **dry-run por padrão** e só remove com `--apply` explícito. O scan de segredo/SAST **estende** `.github/workflows/ci.yml` (não substitui os jobs existentes). Custo respeita o guard-rail (ferramentas gratuitas/open-source). Nenhuma mudança quebra os ~252 testes existentes nem o isolamento de tenant.

---

## Story 6.1 — Rotina de varredura de órfãos no storage
As a **operador da plataforma**,
I want **uma rotina CLI que encontre e remova objetos do object storage sem referência viva no banco (órfãos), em dry-run por padrão**,
so that **o storage não acumule lixo (uploads abortados, anexos de registros já excluídos) sem risco de apagar arquivo em uso**.

### Acceptance Criteria
1. Uma CLI (`python -m app.scripts.*`, no padrão do `migrate_attachments_to_s3` existente) lista os objetos do object storage sob o prefixo dos anexos e identifica como **órfão** todo objeto cujo `storage_key` **não** tem referência viva na tabela `attachments` (nem em qualquer outra tabela que referencie storage) — reusando `core/storage.py` e o padrão de fallback gracioso.
2. **Dry-run por padrão** (só relata o que removeria); `--apply` remove de fato; `--older-than <dias>` filtra por idade do objeto (não toca em uploads recentes que possam estar em voo).
3. Sem `S3_BUCKET` configurado, a rotina opera sobre o storage vigente sem quebrar (mesmo padrão dual-write/fallback); a definição de "vivo" cruza **todas** as tabelas que referenciam storage para não gerar falso órfão.

### Integration Verification
- IV1: A varredura **não** apaga nenhum objeto referenciado por um anexo vivo (Contas a Pagar/Receber — boleto/contrato — e Agenda continuam baixando seus anexos) — coberto por teste com objeto vivo + objeto órfão.
- IV2: O escopo por tenant do path (`tenants/{tenant_id}/...`) é respeitado — a rotina não mistura nem vaza objetos entre tenants; a identificação de referências respeita a RLS do metadado.
- IV3: Em dry-run (padrão), nenhum efeito colateral; `--apply` só remove os confirmados como órfãos; `scripts/check.sh` + os 3 agentes de QA passam.

## Story 6.2 — Secret scan (gitleaks) + SAST (semgrep) no CI
As a **mantenedor da plataforma**,
I want **scan de segredo (gitleaks) no diff do PR e SAST (semgrep, TS/JS/React/OWASP) no CI, estendendo o pipeline existente**,
so that **segredos vazados e vulnerabilidades conhecidas sejam pegos antes do merge, sem travar o time com falsos positivos**.

### Acceptance Criteria
1. `.github/workflows/ci.yml` ganha um job de **gitleaks** que faz secret scan (no diff do PR e no push para `main`), com **baseline/allowlist versionada** para conviver com achados legítimos já tratados (ex.: o token do Apify que foi redigido, documentado no `CLAUDE.md`).
2. `.github/workflows/ci.yml` ganha um job de **semgrep (SAST)** cobrindo TS/JS/React + regras OWASP, escaneando o código relevante do monorepo, com conjunto de regras curado para reduzir ruído.
3. Os jobs novos **coexistem** com os existentes (`test-in-prod-image`, `cross-tenant-rls`) sem quebrá-los; começam como gate **observável** (visível no PR) e a promoção para **bloqueante** (branch protection) fica como follow-up de @devops, documentado — evitando travar merges com falso positivo no dia 1.

### Integration Verification
- IV1: Os jobs existentes (`test-in-prod-image`, `cross-tenant-rls`) continuam passando e inalterados; o CI segue rodando em `push`/`pull_request` para `main`.
- IV2: Ferramentas gratuitas/open-source (gitleaks e semgrep têm modo OSS) — sem custo novo (Regra de Ouro nº 4); as actions são fixadas por versão.
- IV3: Um segredo de teste plantado no diff é **detectado** pelo gitleaks e um padrão inseguro conhecido é **sinalizado** pelo semgrep (validação de que os scans funcionam), sem gerar enxurrada de falso positivo no código atual (allowlist/baseline calibrada).
</content>
