# Epic 4: Backlog Pós-Lançamento (NÃO bloqueante)

> **Classificação:** NÃO bloqueante para o go-live. **Sequenciamento:** puxar após o lançamento, priorizado
> por valor/risco (via @po). Fonte: `docs/prd.md` §9; dívida por módulo em `CLAUDE.md` §6/§6.1.

## Contexto do sistema existente (para o @sm)
Todas as histórias deste epic têm um **comportamento atual aceitável** que não impede produção: stub, campo
manual, URL de imagem, ou endpoint manual. Referências ao estado atual:
- **Google Meet/Calendar:** hoje é campo manual + botão que abre `meet.google.com/new` (é o módulo 6 / API Hub).
- **Logo/imagens:** vários módulos (Brand Kit, propostas, carrossel, sites) aceitam apenas **URL**, não upload.
- **Funil:** o motor de automação existe (`funnels/engine.py`, enroll→espera→tick→done), mas o `tick` é
  disparado por endpoint/tela (`POST /funnels/runs/tick`) — sem worker durável; envios são síncronos no request.
- **White-label por subdomínio:** o go-live é single-domain; wildcard `*.e1p.com` exige TLS via desafio DNS-01.
- **Refinamentos:** enumeração de e-mail no `/register`; `shared-types` mantido à mão (vs OpenAPI); `is_ai`
  placeholder na Agenda; janela do dia/`all_day` ancorada em meia-noite UTC (dívida de fuso por tenant).
- **Dívidas por módulo:** estorno/reversão de `platform_earnings`, OCR de boleto, PDF assinado com hash/carimbo,
  régua de cobrança + juros/multa, antecipação de recebíveis, checkout público real, área de membros real, etc.

## Epic Goal
Consolidar as dívidas documentadas que não impedem o go-live para priorização depois do lançamento. Nenhuma
destas histórias bloqueia produção.

## Integration Requirements
Cada item é aditivo e opcional; ao ser puxado, deve seguir o fluxo de qualidade (§5 do CLAUDE.md) e não
regredir o que já funciona.

---

## Story 4.1 — Google Meet/Calendar OAuth
As a **dono da empresa de 1 pessoa**,
I want **gerar links de Meet automaticamente via OAuth Google (Calendar API)**,
so that **eu não precise colar o link manualmente na Agenda**.

### Acceptance Criteria
1. Fluxo OAuth Google (Cloud project + Calendar API) conecta a conta do owner quando ele fornecer as credenciais.
2. Eventos da Agenda passam a gerar Meet automaticamente (substituindo o campo manual + botão que abre `meet.google.com/new`).
3. Sem credenciais Google, o comportamento manual atual é preservado.

### Integration Verification
- IV1: A Agenda (calendário, conflitos, detalhe do evento) continua funcionando sem Google conectado.
- IV2: Nenhuma regressão nos eventos existentes (com link manual).
- IV3: Credenciais Google tratadas como segredo (não expostas ao frontend).

## Story 4.2 — Upload real de logo e imagens
As a **dono da empresa de 1 pessoa**,
I want **subir logo e imagens de verdade (Brand Kit, propostas, carrossel, sites) em vez de colar URL**,
so that **eu não dependa de hospedar imagens externamente**.

### Acceptance Criteria
1. Brand Kit, propostas, carrossel e sites aceitam upload real de imagem/logo (reusando a camada de storage do Epic 3.5), mantendo a prévia ao vivo.
2. Campos de URL antigos continuam aceitos (retrocompatível) durante a transição.
3. O reuso de Brand Kit (proposta/carrossel herdam cores/logo) continua funcionando com o upload real.

### Integration Verification
- IV1: Propostas/carrosséis/sites existentes (com URL) continuam renderizando.
- IV2: Isolamento por tenant no storage preservado.
- IV3: Guarda de esquema de `<img src>` (segurança já existente) mantida.

## Story 4.3 — Worker durável + fila (tick do funil + envios assíncronos)
As a **operador da plataforma**,
I want **um worker durável (cron/SQS) que processe o `tick` do funil e os envios assíncronos**,
so that **as esperas do funil e as notificações não dependam de chamada manual nem bloqueiem a request**.

### Acceptance Criteria
1. Um worker/cron durável dispara `POST /funnels/runs/tick` periodicamente (hoje é endpoint manual/tela), retomando esperas vencidas de forma idempotente.
2. Os envios síncronos no request (ex.: WhatsApp ao mover card) migram para fila (SQS ou equivalente barato).
3. Auto-enroll por evento (lead criado/tag aplicada via `core/events`) é avaliado como próximo passo (documentado, não obrigatório nesta story).

### Integration Verification
- IV1: O motor de automação do funil (enroll→espera→tick→done) continua funcionando e idempotente.
- IV2: Falha de envio não derruba a request de origem.
- IV3: Custo do worker/fila respeita o guard-rail (NFR3).

## Story 4.4 — Wildcard de subdomínio por tenant (TLS DNS-01)
As a **plataforma white-label**,
I want **servir cada tenant em seu subdomínio (`joaosilva.e1p.com`) com TLS wildcard**,
so that **o white-label por subdomínio funcione em produção**.

### Acceptance Criteria
1. TLS wildcard (`*.e1p.com`) via desafio DNS-01 (Caddy com plugin de provedor DNS) configurado.
2. O roteamento por subdomínio resolve o tenant correto (mantendo o isolamento RLS).
3. O go-live single-domain atual continua funcionando durante a transição.

### Integration Verification
- IV1: O domínio único atual permanece acessível.
- IV2: Isolamento por tenant preservado no roteamento por subdomínio.
- IV3: Emissão/renovação de certificado wildcard validada.

## Story 4.5 — Endurecimentos e refinamentos diversos
As a **mantenedor do sistema**,
I want **fechar as dívidas menores de segurança/manutenção não bloqueantes**,
so that **o sistema fique mais robusto e coeso após o lançamento**.

### Acceptance Criteria
1. Enumeração de e-mail no `/register` reavaliada (fluxo de confirmação de e-mail).
2. Geração de tipos TS a partir do OpenAPI do FastAPI (elimina a manutenção manual do `shared-types`).
3. Rastro da IA propagado na Agenda (`is_ai` real quando a camada de ações de IA existir) e normalização de fuso por tenant (janela do dia/`all_day`).

### Integration Verification
- IV1: Cadastro/login e o contrato `shared-types` continuam funcionando (sem quebra do contrato).
- IV2: As correções de fuso já feitas (all-day por data de calendário) não regridem.
- IV3: Nenhuma regressão nos testes existentes.

## Story 4.6 — Dívidas menores por módulo
As a **product owner**,
I want **um repositório organizado das dívidas específicas por módulo listadas no CLAUDE.md**,
so that **elas sejam priorizadas por valor/risco após o lançamento**.

### Acceptance Criteria
1. As dívidas por módulo do CLAUDE.md §6 são catalogadas como itens de backlog: estorno/reversão de `platform_earnings`, OCR de boleto, PDF assinado com hash/carimbo, régua de cobrança + juros/multa, antecipação de recebíveis, checkout público real, área de membros real, entrega automática de infoproduto, rate-limit em rotas públicas, PDF de orçamento, "Documentos" como conceito próprio na Ficha 360°, relatório .docx do Jurídico, versionamento de documentos jurídicos.
2. Cada item recebe classificação valor/risco para priorização (via @po).
3. Nenhum item é implementado nesta story (é catalogação); a implementação vira stories próprias quando priorizadas.

### Integration Verification
- IV1: Nenhuma mudança de código nesta story (apenas backlog) — sem risco ao sistema existente.
- IV2: O catálogo referencia a origem exata no CLAUDE.md §6 (rastreabilidade).
- IV3: Itens já bloqueantes não são rebaixados para cá por engano (consistência com a seção 5.2 do PRD).
