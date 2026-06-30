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
   - ⚠️ **O GUC do tenant é setado em escopo de SESSÃO** (`set_config(..., false)`) em `db/session.py`, não de transação. Com escopo de transação (`true`), `db.refresh()` pós-commit roda sem tenant e a RLS esconde a própria linha (erro "Could not refresh instance"). O `tenant_session` reseta o GUC no `finally` para não vazar entre requests do pool. (Bug que só aparece com RLS real — SQLite não pega.)
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
- [x] **Frontend ligado à API** (login só-acesso, telas Agenda/CRM/Cockpit funcionais, botões criam de verdade). Cor `#5D44F8` + sidebar no formato "Portal" + logout.
- [x] **Super Admin (Master)** — dashboard de plataforma: criar/listar/suspender/excluir contas; `is_platform_admin` (migration 0004); seed via env; delete atômico com purga dinâmica de tabelas de negócio. 77 testes.
- [x] **Recuperação de senha** — `/auth/forgot-password` + `/auth/reset-password` (token sha256 + expiração 1h, single-use); botão na tela de login; migration 0005. 81 testes. **Pendente: provedor de e-mail** — em dev o token volta na resposta (`dev_reset_token`); em produção precisa SMTP/WhatsApp p/ entregar o link.
- [x] **Agenda detalhada (estilo Google Agenda)** — evento com local, convidados, link de reunião (Meet/Zoom), dia-inteiro, descrição (migration 0006). **Kanban com drag-and-drop** (HTML5 nativo, move otimista). 83 testes.
- [x] **Agenda calendário** (visões Mês/Semana/Dia, navegação, clicar no dia cria evento). **Sidebar fixa** (sticky + min-w-0; Kanban rola sem mover o menu). **Etapas criar/arquivar** no Kanban (arquivar remaneja clientes; migration 0007). **Notificação WhatsApp ao mover card** (barramento `crm.client.moved` → `notifications`, stub `core/whatsapp`). 85 testes.
- [ ] **Integração WhatsApp Cloud API** — PENDENTE: hoje as notificações ficam `logged` (sem entrega). Precisa `WHATSAPP_TOKEN`+`WHATSAPP_PHONE_ID` (Meta) e um **campo de telefone do owner** (não existe ainda — recipient usa o e-mail como placeholder). Também: o envio é SÍNCRONO no request do move — mover para fila (SQS) quando o worker existir.
- [ ] **Integração Google (Meet/Calendar)** — PENDENTE: gerar Meet automaticamente exige OAuth Google (Google Cloud project + Calendar API). Hoje: campo manual + botão que abre meet.google.com/new. É o módulo 6 (API Hub) da spec — fazer quando o usuário fornecer credenciais Google.
## Fase 2 — dinheiro entra/sai (em andamento)
- [x] **Carteira & Split** — transações com split 40/30/20 (produto/serviço/recorrente), saldos (disponível/a receber/sacado), settle (libera cartão), payout (saque, com lock FOR UPDATE), painel de ganhos da plataforma p/ o Master (`platform_earnings` global). Dinheiro em centavos BigInteger. Cockpit mostra faturamento líquido real. Migration 0008. 99 testes.
  - **Dívida:** estorno (`refunded`) ainda sem caminho de execução nem reversão do `platform_earnings`. Payout real precisa integração bancária + KYC (hoje só marca withdrawn). Antecipação de recebíveis não implementada.
- [x] **Contas a Receber** — cobranças (boleto/Pix/link com código stub), baixa (`/pay` simula webhook) → cria Transaction na Carteira com split (atômico, com lock FOR UPDATE contra baixa dupla), vencimento injetado na Agenda (cobranca_receber), resumo de inadimplência (a vencer/vencido/recebido). Migration 0010. 107 testes.
  - **Dívida:** gateway real (Asaas/Mercado Pago) p/ gerar boleto/Pix de verdade + webhook real; régua de cobrança (lembretes automáticos) + juros/multa; estorno; `is_overdue`/summary usam dia em UTC (mesma dívida de fuso do Cockpit).
- [x] **Cockpit: painel de inadimplência + Cobrar com IA** — o dashboard (acima da agenda) lista clientes em atraso; botão por cliente dispara `/receivables/charges/{id}/collect`: a IA (Claude, com `[NOME]` como placeholder p/ não vazar PII; fallback template se não houver chave) escreve uma cobrança amigável e registra uma Notification de WhatsApp (rastro de IA). 110 testes.
- [x] **Contas a Pagar** — despesas (categoria, fornecedor, recorrência), vencimento na Agenda (cobranca_pagar), marcar paga (com lock), resumo (a pagar/semana/mês/pago), categorias. Cockpit "Custos do Mês" agora é real. Migration 0011. 118 testes.
  - **Dívida:** OCR de boleto (IA lê PDF e preenche fornecedor/valor/vencimento) — não implementado; auto-geração de contas recorrentes (precisa scheduler); anexo de comprovante.
- [x] **Agenda clicável + detalhe do evento** — todo evento abre um modal central; para `cobranca_receber` mostra os dados da cobrança + **histórico de mensagens** ao cliente + **Cobrar com IA** e **mensagem manual**; para `cobranca_pagar` mostra os dados da conta. Notification ganhou `client_id` (migration 0012) p/ o histórico por cliente. 122 testes.
- [x] **Produtos & Checkout** (estrutura Super Membros: Produtos / Cupons / Alunos) — produtos (físico/digital/membros), cupons (% ou fixo, único por tenant), venda aplica cupom + cria Transaction na Carteira com split de produto + matricula o Aluno (atômico); link de checkout (stub). Migration 0013. 130 testes. **→ FASE 2 COMPLETA.**
  - **Dívida:** checkout público real (página + gateway), entrega automática (infoproduto: link/arquivo; físico: baixa de estoque + tarefa de envio), área de membros real.
## Fase 3 — documentos & fechamento de venda (em andamento)
- [x] **Central de Orçamentos** — itens/quantidades/desconto com totais, status (rascunho→enviado→aprovado/recusado), enviar (notifica cliente), **efeito dominó** (aprovar gera a cobrança em Contas a Receber, ATÔMICO via `receivables.build_charge` + lock + guarda de total>0), descrição de escopo por IA. Migration 0014. 140 testes.
  - Refactor: `receivables.build_charge` (sem commit) reutilizável; `create_charge` virou wrapper.
- [x] **Construtor de proposta (estilo Super Membros)** — editor em abas **Serviços / Dados / Imagens / Cronograma / Contrato / Aparência** com prévia ao vivo, e **link público** que o cliente abre SEM login (senha opcional) e **aceita** → dispara o dominó. Migration 0015. 147 testes.
  - Link público: `quotes` tem RLS; ao salvar copiamos um SNAPSHOT só-de-exibição p/ `published_proposals` (tabela GLOBAL sem RLS) por `slug`. Rota pública lê via `get_db`; o aceite abre `tenant_session(snap.tenant_id)` (injetado por `get_tenant_session_factory`, sobrescrito nos testes) e chama `approve_quote`. QA de segurança: sem vazamento cross-tenant, senha fail-closed antes de aprovar, idempotente (FOR UPDATE). Slug `token_urlsafe(12)`; `<img src>` com guarda de esquema.
  - **Dívida:** upload real de imagem/logo (hoje por URL — precisa storage S3); PDF do orçamento; status "visualizado"; rate-limit em `/public/proposals/*`; aceite público hoje funciona em rascunho (decidir se exige "enviado"); derivar snapshot do schema `PublicProposal`.
- [x] **Construtor de Contratos + Assinatura & KYC** — contratos por **cláusulas reordenáveis (drag-and-drop)** com variáveis `[CLIENTE]/[VALOR]/[OBJETO]/[DATA]/[EMPRESA]` (auto-preenche CLIENTE/DATA/EMPRESA), **templates** padrão por tenant (Prestação de serviços, NDA), status rascunho→enviado→assinado/cancelado, e **link público de assinatura** sem login: cliente informa nome+CPF/CNPJ (KYC) + aceite → registra assinatura (nome, documento, **IP**, data) e marca assinado (idempotente, FOR UPDATE). Migration 0016. 156 testes. Mesmo padrão público das propostas (snapshot global `published_contracts` sem RLS); o **documento do KYC NÃO vai no snapshot público**.
  - **Dívida:** PDF assinado + hash/carimbo de tempo; verificação real de documento (KYC forte).
- [x] **Efeito dominó COMPLETO (Aprovação Inteligente)** — aprovar/aceitar um orçamento com a aba "Contrato" ativada gera, no MESMO commit, a **cobrança** (Contas a Receber) E o **contrato** (rascunho, ligado por `quote_id`, cláusulas vindas de itens/valor/pagamento/contract_text). `contracts.build_contract_from_quote` (sem commit) chamado por `quotes.approve_quote` (import lazy, sem ciclo). 158 testes. **→ FASE 3 COMPLETA.**
  - Validado e2e: cliente aceita no link público → cobrança + contrato nascem juntos.
- [x] **Área do Cliente / Ficha 360°** — `/crm/clients/:id`: editar dados do cliente (nome/contato/tags/obs), resumo financeiro (a vencer/vencido/recebido), e abas **Cobranças** (receber, **trocar vencimento** → move o evento da agenda junto, **protestar** vencidas), **Contratos** e **Orçamentos** do cliente (links pras fichas). Backend: filtros `?client_id=` em `/receivables/charges`, `/contracts`, `/quotes`; `POST /charges/{id}/reschedule` (atualiza `due_date` + AgendaEvent); `POST /charges/{id}/protest` (campo `protested_at`, só vencida+aberta, idempotente). Migration 0017. 166 testes. **→ FASE 3 COMPLETA.**
  - **Dívida:** "Documentos" como conceito próprio (hoje a aba mostra Contratos); histórico de conversas/agendamentos na ficha; protesto real via cartório/serviço.

## Fase 4 — Marketing & Conteúdo (em andamento)
- [x] **Gerador de Carrossel (Redes Sociais)** — `/marketing`: gera slides + **legenda + hashtags** com IA a partir de um tema (`core/ai` + fallback estruturado), 3–10 slides; **estilo EDITORIAL** (capa/editorial/accent/cta, 4:5) baseado na skill real do usuário `docs/skills/carrosseis-instagram.md` [[e1p-carrossel-skill]]: header (Powered by e1p / @handle / mês ano ®) + rodapé com numeração, título CAIXA ALTA com palavra em destaque, fotos opcionais (URL), fundo sólido/foto+overlay. **Templates personalizáveis** (Editorial/Moderno/Minimalista/Gradiente/Jurídico/Vibrante) + cores/fonte livres. **Export PNG no navegador (html2canvas)** — replica o HTML→PNG da skill (que usava Playwright), por slide ou "baixar todos", 1080×1350. Migrations 0018-0019. 173 testes.
  - **Dívida:** Unsplash (fotos automáticas) e Apify/Reddit (trends) precisam das chaves PRIVADAS do usuário — plugar depois; brand kit salvo por tenant; publicação/agendamento no Instagram; export ZIP/PDF; gestor de tráfego (Meta Ads) e métricas. (Token do Apify que veio no zip foi REDIGIDO ao salvar a skill no repo.)
- [x] **Construtor de Funil de Vendas** — `/funis`: canvas **React Flow** drag-and-drop com paleta de **88 componentes em 5 categorias** (Gatilhos/Lógica/Ações/Comunicação/Tráfego, coloridas), nós conectáveis (handles), arestas animadas, minimap/controles, **modo apresentação** (esconde UI), **export PNG** (html2canvas) e salvar/excluir. Backend `Funnel` (RLS) guarda nós+arestas no formato React Flow; `GET /funnels/components` serve o catálogo. Migration 0020. 180 testes. Fiel ao markdown [[e1p-funil-vendas]].
  - UX (commit `4cfb0f1`): painel "Configurações Rápidas" (editar rótulo/descrição, ID/chave, remover nó), clicar para adicionar, "Compartilhar" (copia link), toasts.
  - Visual (commit a seguir): nós **coloridos** com 2 formas — **páginas quadradas com mockup** (25 componentes-página: vendas/captura/checkout/obrigado/...) e **nós redondos com ícone** por categoria (63). Catálogo do backend marca `shape: page|node` (PAGE_KEYS). Páginas têm **"Modelo de página"** (Vendas/Captura/Obrigado/Checkout/Download/Webinar/Conteúdo) no editor.
  - **Conteúdo nos nós** (commit a seguir): clicar num nó abre editor de conteúdo por tipo — **e-mail** (assunto+corpo), **WhatsApp/SMS** (mensagem), genérico (texto) — com **gerar por IA** (`POST /funnels/ai-compose {kind,prompt}` → core/ai + fallback). Conteúdo salvo em `node.data.config`; nó com conteúdo mostra um ponto verde. 182 testes.
  - **Executar nó (ações REAIS internas)** (commit a seguir): `POST /funnels/run-node {action, client_id, params}` dispara a ação de verdade — `create_client` (Lead/Adicionado ao CRM → cria contato), `add_tag`, `create_quote` (Emissão de Proposta → orçamento real), `create_charge` (Emissão de Boleto/Gerou Pix → cobrança real, com split ao pagar), `send_email`/`send_message` (registra Notification + WhatsApp stub). Catálogo marca `action` por componente; front mostra "▶ Executar ação" com modal de campos + seleção de cliente. Reusa serviços validados; teto de valor R$100M (422); isolamento por RLS (db.get do client de outro tenant → None → 422). QA adversarial: SEGURO. 188 testes.
  - **Dívida:** AUTOMAÇÃO real (motor que percorre o grafo quando um lead entra) — registrada em [[e1p-funil-automacao]]; integrações externas para envio real (provedor de e-mail, WhatsApp Cloud API, gateway); link público do funil; templates de funil prontos.
- [x] **Controle de Estoque** (módulo 4 da spec) — `/estoque`: itens com quantidade/custo/mínimo/unidade, **ledger de movimentações** (entrada/saída com motivo: compra/ajuste/perda/venda), **alertas de estoque baixo** (quantidade ≤ mínimo), resumo (itens/valor total/baixos), e **baixa automática na venda** (StockItem ligado a um Produto via `product_id` → `consume_for_product` chamado por `products.sell` na MESMA transação, com FOR UPDATE). Ajustes não deixam quantidade negativa (409). Migration 0021. 194 testes.
  - **Dívida:** IA lê anotação/áudio p/ dar baixa de extras (spec); kits/composição; relatório de giro/curva ABC; baixa por serviço (não só produto).
- [x] **Configurações + Brand Kit** — `/config`: perfil da empresa (nome/CNPJ/contato/site/sobre) + **Brand Kit** (logo, cores primária/secundária/destaque/texto/fundo, fonte) com prévia ao vivo. Backend `TenantProfile` (RLS, 1 por tenant, criado sob demanda com defaults do `legal_name`/`document`); `GET/PATCH /settings/profile`. Migration 0022. 198 testes. **Reuso:** proposta nova herda logo+cores do Brand Kit; carrossel novo herda cor primária/destaque/fonte (mantendo o fundo editorial).
  - **Dívida:** upload real do logo (hoje URL); aplicar brand kit também em contratos/PDF; config de integrações (chaves) nesta tela.
- [x] **Sites / Páginas** — `/sites`: construtor de landing pages por **blocos** (título/texto/imagem/botão/formulário/vídeo/divisor), **modelos** (vendas/captura/obrigado/checkout/download/webinar/conteúdo) com template inicial, herda o **Brand Kit** (cores/fonte/logo). Editor com prévia ao vivo + reordenar blocos; **publicar** gera o snapshot público. **Página pública** sem login em `/p/:slug` (mesmo padrão de propostas: `Page` RLS + `published_pages` global; `public_view` só após publicar). **Formulário de captura → cria LEAD no CRM** (source=landing) via `tenant_session`. Migration 0023. 204 testes.
  - **Dívida:** rate-limit/anti-spam no formulário público; mais blocos (depoimentos, FAQ, preço); subdomínio/domínio próprio; ligar a página ao nó-página do funil (referência mútua); A/B; analytics.
- [ ] Migrar módulo **Assistente Jurídico** do app existente (`~/lex-intelligentia-app`) — Fase 5.

## Anexos (upload de arquivos)
- [x] **Módulo de Anexos** — `/attachments` (RLS): upload REAL de arquivos (PDF/JPEG/PNG, ≤10MB) ligados a uma entidade por `owner_type`+`owner_id` (ex.: payable, charge) e `label` (boleto/contrato/outro). Bytes no Postgres (`LargeBinary`) — simples e isolado por tenant; migrar p/ S3 é dívida. POST multipart (UploadFile), GET lista por owner, GET `/{id}/download` (Response com content-type + Content-Disposition; baixado via axios blob no front por causa do Bearer), DELETE. Migration 0025. Componente React reutilizável `components/Attachments.tsx` (upload/listar/ver/remover). 212 testes.
  - **Contas a Pagar:** modal "Boleto/Pix" agora sobe **Boleto** e **Contrato** (arquivo, não URL) + mantém o código Pix/boleto (texto). Campo `payment_code` é texto; o antigo `attachment_url` (URL) saiu da UI (coluna mantida, sem uso).
  - **Contas a Receber:** ação "Contrato" por cobrança → anexa **Contrato** (e Boleto) da cobrança.
  - **Dívida:** mover storage p/ S3 (hoje bytes no Postgres); preview inline (hoje abre em nova aba); antivírus/scan; limite por tenant.

## 6.0 Correções importantes
- **[CRÍTICO, CORRIGIDO] RLS perdia o tenant no refresh pós-commit (afetava TODOS os módulos).** A `Session` ligada à Engine devolvia a conexão ao pool no `commit()`; o `db.refresh()` seguinte pegava outra conexão sem a GUC `app.current_tenant_id` → RLS escondia a linha → 500 "Could not refresh instance". Funcionava só quando o pool reusava a mesma conexão. **Fix:** `tenant_session` agora prende a Session a UMA conexão dedicada (`engine.connect()`) por todo o request; o refresh pós-commit usa a mesma conexão (GUC setada). Validado: criar em tenant novo OK em todos os módulos + isolamento entre tenants intacto. Regra: qualquer novo helper de sessão de tenant DEVE usar conexão dedicada, nunca a Engine direto.

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

**Super Admin — pendências (de revisão QA):**
- **Log de exclusão (LGPD):** o delete de conta purga também `audit_entries` do tenant — não sobra registro da própria exclusão. Criar um log de plataforma (fora do tenant) da operação destrutiva.
- **Inconsistência de id:** `PATCH /admin/accounts/{user_id}` (id de usuário) vs `DELETE /admin/accounts/{tenant_id}` (id de tenant). Documentado; alinhar quando houver UI de sub-usuários.
- **Forçar troca de senha no 1º login** do super admin (hoje a senha semeada vale até ser trocada manualmente).

> Já corrigidos no Super Admin (revisão QA): guarda de produção p/ senha default do admin; delete ATÔMICO (transação única, sem conta-zumbi); purga de tabelas **dinâmica** (descobre subclasses de TenantMixin — módulos futuros purgados automaticamente); `WHERE tenant_id` explícito na purga (defesa-em-profundidade); `require_platform_admin` revalida no banco (não confia no claim por 7 dias); slug "platform" reservado; guard de exclusão checa qualquer admin no tenant (não só o owner).

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
