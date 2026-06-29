# Arquitetura — e1p

## Visão geral
Monorepo. Backend FastAPI multi-tenant + Frontend React SPA + pacotes compartilhados.
Tudo conteinerizado para rodar igual em dev (docker-compose) e produção (AWS).

```
                       ┌─────────────────────────────┐
  *.e1p.com  ──CDN──▶  │  CloudFront + S3 (web SPA)   │
                       └──────────────┬──────────────┘
                                      │ /api
                       ┌──────────────▼──────────────┐
                       │  FastAPI (container)         │
                       │  core: auth · tenancy(RLS)   │
                       │        anonymizer · ai · audit│
                       │  modules: agenda, crm, ...   │
                       └───┬───────────┬───────────┬──┘
                           │           │           │
                    ┌──────▼──┐  ┌─────▼─────┐  ┌──▼─────────┐
                    │ Postgres│  │ S3 (files)│  │ SQS (jobs) │
                    │  (RLS)  │  └───────────┘  └────────────┘
                    └─────────┘
        externos: Claude API · Meta · WhatsApp Cloud · gateway pagamento
```

## Princípios
- **API-first.** O frontend (e a futura mobile) consomem a mesma API REST. Contrato em `packages/shared-types`.
- **Modular.** Cada módulo de negócio é isolado: `apps/api/app/modules/<modulo>` (router + service + models +
  schemas) e `apps/web/src/features/<modulo>`. Acoplam-se via eventos/serviços do core, não por import direto.
- **12-factor.** Config por ambiente (env), stateless, logs para stdout, processos descartáveis.
- **Custo-consciente.** Graviton/ARM, um banco com RLS, S3+CloudFront para estáticos, SQS em vez de
  broker dedicado, SSM Parameter Store (free) em vez de Secrets Manager quando possível.

## Camada core (o coração)
- `core/auth.py` — JWT, hash de senha, sessão, RBAC (sub-usuários com escopo por módulo), logout por inatividade.
- `core/tenancy.py` — resolve o tenant (subdomínio/JWT), aplica `SET LOCAL app.current_tenant_id` na conexão,
  garante RLS. Toda request autenticada passa por aqui.
- `core/anonymizer.py` — substitui PII (nomes, CPF, contas) por variáveis antes de chamar a IA e reinsere depois.
- `core/ai.py` — wrapper do Anthropic SDK; SEMPRE recebe texto já anonimizado; registra consumo de tokens.
- `core/audit.py` — trilha de auditoria; ações da IA gravam "Ação executada pela IA".
- `core/events.py` — barramento interno simples para integração entre módulos (ex.: contrato assinado →
  cobrança + agenda + kanban).

## Multi-tenancy (RLS)
- Toda tabela de negócio tem coluna `tenant_id UUID NOT NULL`.
- Política RLS no Postgres filtra por `current_setting('app.current_tenant_id')`.
- A dependência de tenancy abre a transação com o `tenant_id` correto. Nenhuma query de aplicação
  filtra tenant manualmente — o banco garante.

## Assíncrono / jobs
Chamadas longas (IA, OCR, disparos WhatsApp, webhooks) vão para uma fila (SQS em prod, fila local em dev)
processada por um worker. Webhooks de pagamento são **idempotentes** (chave de idempotência por evento).

## Frontend
- Shell (sidebar + topbar do design "Portal") + roteamento por módulo.
- Estado de auth em contexto + storage. Chamadas via cliente axios tipado com `shared-types`.
- Design tokens de `packages/design-tokens` (sem cores hardcoded).
