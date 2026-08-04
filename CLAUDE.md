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
  - [x] **Área de usuários (hierarquia, "ver/editar/excluir todos os usuários")** — `GET /admin/users` devolve a **hierarquia**: cada escritório (Admin/dono = `role=owner`) → **funcionários** (`role=sub_user`) → **clientes** (compradores, agregados de `Enrollment` por e-mail/nome com contagem de compras). Contas internas da plataforma (Master) são omitidas. O Master **cadastra funcionário** (`POST /admin/accounts/{tenant_id}/users` — name/email/senha + `allowed_modules`; vazio = acesso a tudo), **edita** (`PATCH /admin/users/{id}` — nome/ativo/módulos) e **exclui** (`DELETE /admin/users/{id}`) qualquer usuário; o **dono** (owner) só sai com a conta inteira (`delete_account`); o Master nunca é editável/excluível por aqui. Sem migration (reusa `users`/`tenants`/`enrollments`). Front **reorganizado p/ menos poluição** (`features/admin/AdminDashboard.tsx` + `PlatformUsers.tsx`): configurações (split/ganhos) numa **caixa recolhível** (`Collapsible`), **busca** + **um cartão por escritório recolhido por padrão** que expande ao clicar (Admin + funcionários add/suspender/excluir + clientes read-only + excluir conta). Tabela flat antiga removida (não duplica mais). Validado e2e no Postgres.
  - [x] **Convite de usuário (cadastro completo + senha por e-mail/WhatsApp + troca no 1º acesso)** — **TODO novo usuário** (funcionário E dono de conta) exige **nome completo, CPF (`document`), endereço, e-mail e WhatsApp (`phone`)** + canal `delivery` (email|whatsapp); a plataforma **gera senha temporária**, marca `must_reset_password=True` e a **envia** (`core/email.py` stub + `core/whatsapp.py`; em dev viram log). Funcionário: `POST /admin/accounts/{tenant_id}/users` → `StaffInviteOut`. Conta/dono: `POST /admin/accounts` agora é por **convite** → `AccountInviteOut` (não pede mais senha na tela). Ambos trazem `temp_password` (mostrada uma vez ao Master) + `delivery_status`. **1º acesso:** login com a temporária → `must_reset_password` no token/`/me` → o front (`ProtectedLayout` → `FirstAccessPage`) bloqueia o app até `POST /auth/change-password {new_password}` (limpa o flag). Migration 0029 (users: document/address/phone/must_reset_password). `config.smtp_host` (vazio=log). 252 testes. Validado e2e (convite de conta/funcionário → login temp → troca → temp 401 / nova 200).
  - [x] **/admin redesenhado em ABAS** (`AdminDashboard.tsx`): **Escritórios** (cartões recolhíveis: Admin + funcionários add/suspender/excluir + excluir conta; clientes saíram daqui, vira só contador), **Clientes** (`PlatformCustomers.tsx` — `GET /admin/customers` lista plana de todos os compradores com escritório de origem; **cards com avatar colorido por iniciais**, e-mail, escritório e nº de compras, com busca) e **Configurações** (split/ganhos). **Dívida:** cliente comprador ainda NÃO é `User` de login (vive em Enrollment); Admin (dono) sem tela PRÓPRIA de equipe (só o Master cadastra hoje); provedores REAIS de e-mail (SMTP/SES) e WhatsApp Cloud API; convite por link em vez de senha visível ao Master.
- [x] **Recuperação de senha** — `/auth/forgot-password` + `/auth/reset-password` (token sha256 + expiração 1h, single-use); botão na tela de login; migration 0005. 81 testes. **Pendente: provedor de e-mail** — em dev o token volta na resposta (`dev_reset_token`); em produção precisa SMTP/WhatsApp p/ entregar o link.
- [x] **Agenda detalhada (estilo Google Agenda)** — evento com local, convidados, link de reunião (Meet/Zoom), dia-inteiro, descrição (migration 0006). **Kanban com drag-and-drop** (HTML5 nativo, move otimista). 83 testes.
- [x] **Agenda calendário** (visões Mês/Semana/Dia, navegação, clicar no dia cria evento). **Sidebar fixa** (sticky + min-w-0; Kanban rola sem mover o menu). **Etapas criar/arquivar** no Kanban (arquivar remaneja clientes; migration 0007). **Notificação WhatsApp ao mover card** (barramento `crm.client.moved` → `notifications`, stub `core/whatsapp`). 85 testes.
- [ ] **Integração WhatsApp Cloud API** — PENDENTE: hoje as notificações ficam `logged` (sem entrega). Precisa `WHATSAPP_TOKEN`+`WHATSAPP_PHONE_ID` (Meta) e um **campo de telefone do owner** (não existe ainda — recipient usa o e-mail como placeholder). O envio ao mover card NÃO é mais síncrono no request (Story 4.3): `on_client_moved` só enfileira uma `Notification` `pending`; o worker (`app.worker`) entrega depois, fora da request.
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
  - [x] **Motor de automação (executa o funil inteiro a partir de um gatilho)** — `funnels/engine.py`: **estado por contato** (`FunnelRun`, RLS: status running/waiting/done/failed/cancelled, `current_node_id`, `resume_at`, `steps` log) + **runtime do grafo** (`_drive` anda pelos edges executando a AÇÃO REAL de cada nó via o `run_node` já validado) + **espera** (nó `esperar` pausa até `resume_at`; delay configurável min/horas/dias) + **agendador** (`POST /funnels/runs/tick` retoma esperas vencidas — idempotente, chamável por cron OU pela tela; sem worker em background ainda, ver core/events.py) + **condicional** (`se-ou`: ramo Sim/Não por condição simples — tem-tag / pagou / sempre, via `sourceHandle` 'sim'/'nao' ou ordem). Gatilho = **inscrição** (`POST /funnels/{id}/enroll {client_id, start_node_id?}`; entrada = nó sem aresta chegando). Guarda anti-ciclo (100 passos); falha de ação → run `failed` com a mensagem, sem derrubar a request; `create_client` com contato já inscrito → pulado. Endpoints: enroll, `GET /funnels/{id}/runs`, `GET/POST /funnels/runs[...]` (list/tick/get/cancel). Params da ação vêm do `node.data.config` (valor/método/tag/delay/condição — configuráveis no painel "Configurações Rápidas" do builder). **Front:** botão "Automação" abre drawer (inscrever contato + lista de jornadas com status + "processar esperas agora" + linha do tempo dos passos). **Integração:** Ficha 360° do CRM mostra "Jornadas no funil" do contato. Migration 0028. 242 testes. Validado e2e no Postgres (enroll→espera→tick→done + isolamento RLS).
  - **Dívida:** envio REAL (provedor de e-mail, WhatsApp Cloud API, gateway) — hoje as ações usam os serviços internos + stubs; ~~cron/worker durável para o tick~~ **FEITO (Story 4.3):** worker durável (`app.worker`, serviço `worker` nos docker-compose) dispara o tick periodicamente e processa a fila de notificações (`notifications` com `status=pending`) fora do request; pendente agora é só o auto-enroll por evento (lead criado/tag aplicada via core/events) em vez de inscrição manual; fan-out (um contato seguir múltiplos ramos); condições mais ricas; link público do funil; templates prontos.
- [x] **Controle de Estoque** (módulo 4 da spec) — `/estoque`: itens com quantidade/custo/mínimo/unidade, **ledger de movimentações** (entrada/saída com motivo: compra/ajuste/perda/venda), **alertas de estoque baixo** (quantidade ≤ mínimo), resumo (itens/valor total/baixos), e **baixa automática na venda** (StockItem ligado a um Produto via `product_id` → `consume_for_product` chamado por `products.sell` na MESMA transação, com FOR UPDATE). Ajustes não deixam quantidade negativa (409). Migration 0021. 194 testes.
  - **Dívida:** IA lê anotação/áudio p/ dar baixa de extras (spec); kits/composição; relatório de giro/curva ABC; baixa por serviço (não só produto).
- [x] **Configurações + Brand Kit** — `/config`: perfil da empresa (nome/CNPJ/contato/site/sobre) + **Brand Kit** (logo, cores primária/secundária/destaque/texto/fundo, fonte) com prévia ao vivo. Backend `TenantProfile` (RLS, 1 por tenant, criado sob demanda com defaults do `legal_name`/`document`); `GET/PATCH /settings/profile`. Migration 0022. 198 testes. **Reuso:** proposta nova herda logo+cores do Brand Kit; carrossel novo herda cor primária/destaque/fonte (mantendo o fundo editorial).
  - **Dívida:** upload real do logo (hoje URL); aplicar brand kit também em contratos/PDF; config de integrações (chaves) nesta tela.
- [x] **Sites / Páginas** — `/sites`: construtor de landing pages por **blocos** (título/texto/imagem/botão/formulário/vídeo/divisor), **modelos** (vendas/captura/obrigado/checkout/download/webinar/conteúdo) com template inicial, herda o **Brand Kit** (cores/fonte/logo). Editor com prévia ao vivo + reordenar blocos; **publicar** gera o snapshot público. **Página pública** sem login em `/p/:slug` (mesmo padrão de propostas: `Page` RLS + `published_pages` global; `public_view` só após publicar). **Formulário de captura → cria LEAD no CRM** (source=landing) via `tenant_session`. Migration 0023. 204 testes.
  - **Dívida:** rate-limit/anti-spam no formulário público; mais blocos (depoimentos, FAQ, preço); subdomínio/domínio próprio; ligar a página ao nó-página do funil (referência mútua); A/B; analytics.
## Fase 5 — Assistente Jurídico (em andamento)
- [x] **Assistente Jurídico** (módulo do `~/lex-intelligentia-app` migrado para dentro do e1p) — `/juridico`: catálogo de **21 skills jurídicas** em 5 categorias (essenciais/magistratura/pesquisa/automação/criação). O usuário escolhe a skill → preenche um **wizard dinâmico** (formulário vindo do `wizard_config` JSON) → opcionalmente **anexa peças** (PDF/Word/imagem/txt, texto extraído por `core/extract.py` — reusa pdfplumber/python-docx/pytesseract) → a **IA redige o documento** usando o `SKILL.md` da skill como prompt-sistema + **protocolo anti-alucinação** (jurisprudência classificada em 3 níveis, nunca inventa números). **Regra de Ouro nº 2:** todo o texto (respostas + anexos) é **anonimizado** (`core/anonymizer`) ANTES de ir ao Claude e desanonimizado localmente na volta — segredo de justiça. A resposta é separada em **corpo + seção METADADOS** (frameworks, jurisprudências citadas, avisos de revisão). Documento gerado (`LegalDocument`, RLS) com tokens, status, e **vínculo opcional ao cliente do CRM** (`client_id`). Download em **.docx** (`export.py`, markdown-leve→Word, unicode nativo). Sem `ANTHROPIC_API_KEY` a geração falha graciosamente (status=failed, 201). **Integração:** Ficha 360° do cliente (`/crm/clients/:id`) mostra a seção "Documentos jurídicos" vinculados. Resources (`modules/juridico/resources/`): 21 `wizard_configs/*.json` + 21 `skills/**/SKILL.md`. Migration 0027. 232 testes.
  - **Dívida:** gerar **relatório** separado (.docx) como no lex original; persistir/baixar os anexos enviados (hoje só o texto extraído é usado, arquivo é descartado); editar/regenerar documento; versionamento; export PDF; OCR exige tesseract instalado no container (já em requirements, validar no build de produção); skills com `references/` extras não são carregadas (só o SKILL.md raiz).

## Anexos (upload de arquivos)
- [x] **Módulo de Anexos** — `/attachments` (RLS): upload REAL de arquivos (PDF/JPEG/PNG, ≤10MB) ligados a uma entidade por `owner_type`+`owner_id` (ex.: payable, charge) e `label` (boleto/contrato/outro). Bytes no Postgres (`LargeBinary`) — simples e isolado por tenant; migrar p/ S3 é dívida. POST multipart (UploadFile), GET lista por owner, GET `/{id}/download` (Response com content-type + Content-Disposition; baixado via axios blob no front por causa do Bearer), DELETE. Migration 0025. Componente React reutilizável `components/Attachments.tsx` (upload/listar/ver/remover). 212 testes.
  - **Contas a Pagar:** modal "Boleto/Pix" agora sobe **Boleto** e **Contrato** (arquivo, não URL) + mantém o código Pix/boleto (texto). Campo `payment_code` é texto; o antigo `attachment_url` (URL) saiu da UI (coluna mantida, sem uso).
  - **Contas a Receber:** ação "Contrato" por cobrança → anexa **Contrato** (e Boleto) da cobrança.
  - **Dívida:** preview inline (hoje abre em nova aba); antivírus/scan; limite por tenant.

## Anexos: storage durável S3-compatível (Story 3.5)
- [x] **Storage S3-compatível dos Anexos** — os bytes podem sair do Postgres para um object storage S3 (`app/core/storage.py`, wrapper fino sobre `boto3` com `endpoint_url` configurável: AWS S3 real OU MinIO/B2/Wasabi barato, sem trocar código). **Dual-write/dual-read com fallback gracioso:** se `S3_BUCKET` está vazio (dev/CI/staging sem bucket), tudo continua no Postgres exatamente como antes (mesmo padrão fail-safe de WhatsApp/SMTP). Se configurado, anexo novo sobe pro bucket (`storage_key` setado, `data=None`); a leitura resolve a origem por linha, então anexo legado (pré-migração) continua baixando. Isolamento de tenant também no path da chave (`tenants/{tenant_id}/attachments/{id}/{filename}` via `build_key`), em complemento à RLS do metadado. Contrato HTTP dos 4 endpoints de `/attachments` e o componente `Attachments.tsx` **inalterados** (só persistência mudou). Migration 0039 (só estrutural: `storage_key` + `data` nullable — não toca em rede no boot). Backfill idempotente `python -m app.scripts.migrate_attachments_to_s3` (documentado em `docs/HOSTINGER-DEPLOY.md`, roda numa janela após configurar as envs). Faseável/não-bloqueante para o deploy.
  - **Dívida:** remover a coluna `data` (limpeza só depois do backfill 100% em produção); validação real contra um bucket S3/MinIO de verdade é manual (sem testcontainers p/ S3 no CI, mesma lacuna do RLS/Postgres).

## Anexos: comprovante pelo share sheet do celular
- [x] **Compartilhar comprovante do app do banco → Contas a Pagar** — o comprovante entra pelo
  compartilhamento nativo do celular, sem salvar arquivo antes. **Bandeja de staging** sem tabela
  nova: `Attachment` com `owner_type="receipt_inbox"`, `owner_id=<user_id>`; vincular é só trocar
  `owner_type`/`owner_id` para `payable` (os bytes não se movem — a `storage.build_key` não
  carrega o dono). A bandeja é **por usuário só por convenção nas rotas de `receipts`**
  (`get_staged` exige `owner_id == user_id`) **e isolada por tenant via RLS** — não é uma garantia
  do sistema como um todo: as rotas GENÉRICAS de `/attachments` (`GET /attachments?owner_type=
  receipt_inbox&owner_id=<id>`, `GET /attachments/{id}/download`, `DELETE /attachments/{id}`) não
  conhecem esse convênio, então outro usuário do MESMO tenant consegue listar/baixar/descartar o
  comprovante em staging de um colega (ver dívida abaixo). Rotas em `/payables/receipts` (upload,
  bandeja, `candidates`, `link`, `new-bill`, descarte). `link` anexa e dá baixa **num commit só**,
  o que exigiu extrair `apply_paid` e `build_payable` (versões sem commit) de
  `mark_paid`/`create_payable` — mesmo padrão do `receivables.build_charge`; a suíte
  `tests/test_payables.py` ficou verde sem precisar editar. **Android:** PWA instalável com
  `share_target` no `manifest.webmanifest`; o `public/sw.js` é um service worker que **não faz
  cache de nada** (só intercepta o POST do share target) — de propósito, para não introduzir a
  classe de bug "deploy novo, app velho em cache". ⚠️ `nginx.conf` ganhou `location = /sw.js` com
  `no-cache`: o regex de estáticos daria `immutable` 30d ao service worker (a mesma `location`
  também isola o `types {}` do manifest num escopo próprio — um `types {}` no nível `server`
  substituiria, em vez de estender, o `mime.types` herdado, quebrando o Content-Type de TODO o
  resto do app). **iOS:** app Atalhos + `device_tokens` (migration 0057, tabela GLOBAL sem RLS —
  mesma situação de `users`), com escopo travado em `POST /payables/receipts` — um token vazado
  só consegue depositar arquivo na bandeja do dono, nunca ler. Isolamento vem de filtro explícito
  por `user_id` do JWT (allowlist documentada em `apps/api/tests/test_tenancy_guard.py`; a tabela
  guarda só o **hash sha256** do token cru + metadado, nunca o token em si — não é criptografia,
  é hash; não é o padrão de tenant-por-token de `whatsapp_inbox`). Slot `comprovante` adicionado
  ao modal (antes o comprovante ia no campo "Contrato"). **Deslogado:** `ProtectedLayout` guarda a
  rota de origem (`state={{ from: location }}`) ao redirecionar para `/login`, e `LoginRoute`
  retoma essa origem no sucesso em vez de sempre ir para `/` — genérico para qualquer rota
  protegida, não só `/compartilhar`/`/comprovante/:id` (sem isso a chave do comprovante, que só
  existe na URL, era destruída pelo `replace` e o arquivo ficava perdido no IndexedDB).
  - **Dívida:** Contas a Receber e anexos genéricos fora de escopo; WhatsApp como porta de entrada
    fica desenhado mas não construído (o `whatsapp_inbox` já cria `Attachment` — falta apontar o
    `owner_type` para a bandeja) e depende das credenciais da Meta; sem OCR/sugestão automática da
    conta; publicação do atalho do iOS é manual, uma vez só (limitação da plataforma, não dá para
    gerar por código); ícones do PWA (192/512) são placeholder — quadrado na cor da marca com
    "e1p" em fonte padrão do PIL, maskable-safe mas para trocar por um logo real. **O isolamento
    por usuário da bandeja depende de `/attachments` ser endurecido**: hoje um tenant-mate
    consegue alcançar o comprovante em staging de outro usuário pelas rotas genéricas (ver acima);
    quem for endurecer `/attachments` (checar dono, não só tenant) precisa saber que a receipts
    inbox depende disso.
  - **Validação manual obrigatória:** `docs/CHECKLIST-COMPROVANTE-MOBILE.md` — só o share sheet
    do Android e o Atalho do iOS seguem genuinamente manuais (exigem aparelho real). O isolamento
    cross-tenant do `link` **já está automatizado** em `apps/api/tests/test_receipts_rls.py`
    (`pytest.mark.rls_e2e`, testcontainers, roda `alembic upgrade head` como o papel não-superusuário
    `e1p_app` contra um Postgres real — o mesmo teste exercita de fato a migration 0057) e no job
    `cross-tenant-rls` do CI.
  - **[CORRIGIDO pós-deploy, achado testando em Android real] `AppShell` nunca teve breakpoint
    responsivo nenhum** — sidebar de 256px fixos (`w-64 shrink-0`, sem `md:`/`sm:`) espremia
    QUALQUER tela do app num aparelho de ~360px; nesta feature isso deixou o checkbox "marcar
    como paga" fora da área visível e uma conta real foi marcada paga sem o usuário conseguir
    ver/desmarcar. Fix: abaixo de `md` a sidebar nasce fechada e abre sobreposta (`fixed` +
    backdrop, fecha ao navegar); `/compartilhar` e `/comprovante/:id` passaram a rodar em
    `ProtectedBareLayout` (mesma proteção via `useAuthGate` compartilhado, sem sidebar/topbar).
    **Só o shell + as 2 telas do comprovante foram auditados — nenhuma outra tela do app foi
    verificada quanto ao mesmo padrão.** (PR #56)
  - **[CORRIGIDO pós-deploy, 2ª rodada de teste em campo]** Mesmo com o shell responsivo, o
    checkbox "marcar como paga" vivia num bloco SEPARADO do botão Anexar — quem selecionava a
    conta e tocava Anexar sem rolar nunca via o checkbox, e a baixa saía com o padrão (marcado)
    sem confirmação visível. Fix: checkbox + resumo da conta escolhida (nome, valor) movidos pra
    DENTRO da mesma barra fixa do Anexar — fisicamente inseparáveis da ação que os torna
    efetivos. Achado no mesmo incidente: a tabela de `PagarPage` usava `overflow-hidden` (corta)
    em vez de `overflow-x-auto` (rola, mesmo padrão de `DrePage`/`LucratividadePage`) — em tela
    estreita a coluna Status e os botões de ação (Editar/Marcar paga/**Estornar**) ficavam
    invisíveis, sem jeito de conferir ou desfazer uma baixa incorreta. (PR #58)
  - **[CORRIGIDO] `docs/HOSTINGER-DEPLOY.md` §5 estava errado** — mandava `docker-compose.prod.yml`
    sem `--env-file`, mas a VPS real (`e1p.doroeventos.com.br`) roda `docker-compose.traefik.yml`
    e EXIGE `--env-file .env.prod`, senão falha por `POSTGRES_ROOT_PASSWORD` ausente. Custou
    confusão em 2 deploys seguidos até a forma certa ser encontrada em
    `docs/RUNBOOK-BACKUP-RESTORE.md`. Corrigido e já verificado na prática (PR #57 + deploys
    seguintes rodaram §5 sem ajuste). **`main` ganhou proteção de branch nesta janela** (4 checks
    obrigatórios) — push direto agora é REJEITADO (`GH006`), toda mudança precisa de PR.

## Financeiro: boleto gera arquivo + pagamento automático (sem marcar à mão)
- [x] **Boleto gera o arquivo (PDF) e anexa** — criar cobrança com `method=boleto` (escolhido no próprio formulário de Nova cobrança) gera um **PDF de boleto** (`core/boleto.py`, fpdf2) com beneficiário/pagador/valor/**vencimento**/linha digitável, e o anexa à cobrança (`Attachment` label=boleto). Aparece na Agenda no dia do vencimento e nos anexos do evento. Cada ocorrência recorrente gera seu próprio boleto.
- [x] **Pagamento reconhecido AUTOMATICAMENTE (sem botão "marcar pago")** — removidos os botões "Marcar paga" de Cobranças e Ficha 360°. Pagamento entra por `POST /receivables/webhook` (gateway: Pix/cartão/boleto compensado), público, protegido por `GATEWAY_WEBHOOK_SECRET` (vazio em dev = aberto p/ teste; definido em prod = só o gateway confirma). A baixa credita a Carteira (split) e libera p/ **saque** no Financeiro. O dono só saca o que o sistema reconhece como pago.
  - Dev/teste: link discreto "simular pgto" nas cobranças chama o webhook (some quando o segredo for definido em prod). Endpoint `/pay` mantido só para testes internos.
  - **Dívida:** gateway real (Asaas/Mercado Pago) — gerar boleto/Pix com registro e receber o webhook de verdade; boleto atual é layout-stub sem registro bancário.

## Financeiro: recorrência + nome do cliente na agenda
- [x] **Recorrência gera ocorrências** — Contas a Pagar e a Receber: ao marcar recorrência (semanal/mensal/anual) define-se **quantas vezes repete** (`recurrence_count`, 1–60). O backend GERA uma conta/cobrança por período (`core/recurrence.advance` com clamp de dia no mês), cada uma com **seu vencimento, seu evento na Agenda e seu boleto** — assim cada repetição recebe o boleto certo. Ocorrências ligadas por `recurrence_group`. Charges ganharam `recurrence`/`count`/`group` (antes só payables tinha o tipo, sem gerar). Migration 0026.
- [x] **Nome do cliente no card da Agenda** — `EventOut.client_name` resolvido no `list/get` (cobrança→cliente, conta a pagar→fornecedor); o chip da agenda mostra o nome quando houver, senão o título.

## Financeiro: editar + agenda (reverberar)
- [x] **Editar cobrança e conta a pagar** (botão "Editar" por linha, só em aberto): `PATCH /receivables/charges/{id}` (descrição/valor/vencimento) e `PATCH /payables/bills/{id}` (descrição/categoria/fornecedor/valor/vencimento/recorrência + boleto/Pix). **Reverbera na Agenda**: ao mudar o vencimento o evento MOVE junto; valor e título do evento também sincronizam. Pago/cancelado não edita (409).
- [x] **Detalhe do evento na Agenda** mostra a descrição completa + **anexos (boleto/contrato)** via o componente `Attachments` (owner = charge/payable do `external_ref`); para conta a pagar mostra também o código Pix/boleto.
- [x] **Estornar conta paga (só Contas a Pagar)** (botão "Estornar" por linha, só em "Pago"): `POST /payables/bills/{id}/reverse` volta o status para `open`/`paid_at=None`, reabrindo a edição completa (dados + anexos) e devolvendo o evento da Agenda de "concluído" para pendente. Confirmação via `confirm()` do navegador. Contas a Pagar nunca move dinheiro (não passa pela Carteira), então o estorno é uma troca de status simples e segura.
  - **Decisão de escopo:** a mesma capacidade foi implementada e revisada para Contas a Receber, mas **descartada antes do merge**: pagar → estornar → pagar de novo (o fluxo principal do estorno) duplicaria o `PlatformEarning` da venda no painel do Master (GMV/taxas globais), porque esse ledger não guarda vínculo de volta à `Transaction`/`Charge` de origem — reverter e repagar 3x uma cobrança de R$100 reportaria R$400 de GMV. Corrigir isso direito exige uma migration ligando `platform_earnings` à transação de origem; decisão do usuário foi não introduzir esse efeito colateral agora. Se o estorno de cobranças for retomado, resolver esse vínculo é pré-requisito (ver `docs/superpowers/specs/2026-07-27-estornar-conta-paga-design.md`).

## Financeiro: Controle Bancário e Conferência (Epic 8 — Ondas 0 e 1)
> Docs: `docs/prd/epic-8-controle-bancario.md` · `docs/architecture/controle-bancario-design.md` + `...-ratificacao.md` · `docs/decisions/0003-controle-bancario-nativo.md` · `docs/qa/epic-8-onda-0-1-gate-2026-07-30.md` · pesquisa em `docs/research/2026-07-29-*`

**Por que existe.** Receber tem três testemunhas independentes (gateway, webhook, o dinheiro entrando). **Pagar não tem nenhuma**: se o dono paga pelo app do banco e não lança, nada protesta — e o silêncio de uma despesa não lançada é indistinguível do silêncio de um mês sem despesa. Sem âncora externa, DRE infla lucro, Lucratividade distorce e a Projeção mente. O banco é a testemunha que faltava. **O objetivo é achar furos, não fazer escrituração** — não é competir com o contador.

### As 7 regras que impedem o próximo bug (leia antes de mexer em qualquer coisa com saldo)

1. **A Regra dos Planos.** Três planos de dinheiro que NÃO se cruzam: **plataforma** (`transactions`, split 40/30/20, `platform_earnings`), **negócio** (`charges`, `payables`), **banco** (`bank_*`). O único contato legítimo entre plataforma e banco é o payout da Carteira (Onda 6, não construída). **Foi misturar plano de plataforma com plano de banco que produziu o bug de origem.** Gates estruturais em `apps/api/tests/test_money_planes.py` reprovam a reintrodução.
2. **Dois eixos de proveniência, nunca achatados num campo.** `*_origem` = **plano** (`plataforma｜banco｜misto｜indisponivel`, em `app/core/money_planes.py`); `*_fonte` = **porta de entrada** (`manual｜ofx`, em `bank/models.py`). Os valores `declarado` e `extrato` foram **revogados** — eram o eixo B disfarçado.
3. **Todo campo de saldo em schema de saída declara sua proveniência.** Comparar saldos só é legítimo quando ambos são do mesmo plano.
4. **Saldo é DERIVADO dos movimentos, nunca coluna, nunca digitado.**
5. **O checkpoint NUNCA corrige o saldo derivado.** Se corrigisse, a divergência iria a zero por construção e a métrica que justifica o épico morreria. Testado em `test_bank_checkpoints.py`.
6. **A conferência é POR CONTA, com a mesma data de referência dos dois lados** (o `reference_date` do checkpoint daquela conta — não "hoje", não uma data comum). `derived_balances_as_of` é **PROIBIDA** na conferência: recebe um `as_of` só, e usá-la ali compara saldos de datas diferentes. Seu consumidor legítimo é a tela de lista. Varredura AST reprova a chamada.
7. **Dentro da banda: verde e SILÊNCIO.** Banda `max(R$ 50, 0,5%)`, borda `==` é dentro. **Fixa de propósito** — a Onda 1 é o instrumento que mede o gate de decisão das Ondas 3 e 4; régua ajustável pelo tenant invalidaria a leitura. Uma tela que grita por R$ 3 destrói a confiança no sinal.

### Onda 0 — o saldo inicial parou de mentir
- [x] **A Projeção de Caixa semeava `saldo_inicial` com `wallet_summary()["available_cents"]`** — saldo da **carteira da plataforma**, não da conta bancária do dono. Errada desde sempre, independente de lançamento esquecido. Agora declara `saldo_inicial_origem` e **suprime no backend** (não na UI) toda afirmação sem lastro: `runway.days=None` + `days_suprimido`, `ProjectionWindow.alert=False` + `alert_suprimido`, ícone de tendência neutro. **Princípio: suprimir a afirmação, nunca o número** — o saldo continua visível.
  - Suprimir na origem, e não na tela, porque o mesmo saldo alimentava **três** superfícies: a Projeção, o sinal de runway do Diagnóstico (`engine._runway_signal`) e o ícone do `WindowCard`. O design mapeava uma.
  - O `alert` era **máquina de falso negativo**: como `request_payout` só marca `withdrawn` (saque real não existe) e `payables` não toca a Carteira, `available_cents` **só cresce** — o alerta ficava silencioso justamente quando deveria disparar.
  - **Supersede o AC1 e o AC2 da Story 5.7**, que mandavam partir do saldo da Carteira. É correção, não regressão — não "conserte de volta".

### Onda 1 — o controle bancário
- [x] **`bank_accounts`** (migration 0058) — N contas por tenant (corrente/poupança/aplicação/caixa), saldo de abertura, RLS `FORCE`. `platform_wallet` é rejeitado como `kind`: é a Regra dos Planos em forma de validação.
- [x] **`bank_transactions`** (0059) — `amount_cents` assinado, `posted_at` como `DATE`, `raw_description` **imutável** (é evidência; a edição do usuário vai em `user_description`). Colunas de dedupe (`fitid`, `dedup_hash` + unique) já criadas para a Onda 3. `status <> 'ignored'` é aplicado **dentro** do saldo derivado — quem consome não refiltra.
- [x] **`bank_balance_checkpoints`** (0060) — "o saldo desta conta no fim deste dia era X". Redeclarar o mesmo dia **corrige** (200), não dá 409.
- [x] **Conferência** (`bank/reconciliation.py`, read-only) — `GET /bank/reconciliation-report`. Divergência **por conta**; o consolidado nunca aparece sem a decomposição. Sem checkpoint na janela → `indisponivel`, e o relatório **diz que não sabe** (`None` ≠ zero).
- [x] **Sinal de completude no `/financeiro/diagnostico`** — 🟢🟡🔴, **um sinal por conta** (3 contas nenhuma conferida = 3 sinais, não 6), com precedência semântica sobre margem/runway: se o produto não sabe se os lançamentos estão completos, qualquer afirmação sobre margem é feita sobre base possivelmente furada. `engine.py` permanece **puro** (sem I/O, sem relógio) — gates AST + varredura de texto garantem.
  - **Decisão do fundador:** o 🟡 "nenhuma conta bancária cadastrada" aparece para **todos** os tenants, sem opt-in e sem dispensa. O sinal é verdadeiro, e escondê-lo seria a mesma mentira por omissão que a Onda 0 corrigiu.
- [x] **Projeção com `origem="misto"`** — saldo bancário + carteira, com as **duas parcelas sempre expostas separadamente**. Somar sim; esconder a composição, nunca. Sem conta cadastrada, cai no fallback da Onda 0 — e a restauração do runway/alert/ícone acontece **por construção** (a supressão sempre foi condicionada à origem; o componente não tem condicional própria).
- [x] **Telas** — `/financeiro/contas` ("Contas & Saldos", na sidebar) e `/financeiro/conferencia` (**fora** da sidebar, alcançada pelo sinal do Diagnóstico: conferência é resposta a um sinal, não tarefa de rotina — vira item de menu, vira peso de ERP). **A frase vem antes da tabela.**
  - Dois recortes rotulados e distintos: **"Total em contas"** (todas as ativas) × **"Disponível como caixa"** (exclui aplicação — é a parcela que a Projeção soma). A string `"no banco"` é proibida nesta tela; pertence à Projeção, com outro sentido.

**Restrição de produto (decisão do fundador):** **sem agregador de Open Finance** — Pluggy, Belvo e Klavi vetados. Formato de arquivo (OFX/CSV) é aceitável porque é formato, não serviço. E **não posicionar como conformidade tributária**: a LC 214/2025 tem obrigação **documental** (NFS-e) e o split payment não alcança o Simples com DAS unificado, que é o regime da sociedade unipessoal de advocacia. A justificativa é conferência e controle interno.

**Ponto de parada legítimo:** se a divergência medida na Onda 1 for pequena e estável, as Ondas 3 (import OFX) e 4 (match por IA) são over-engineering. A Onda 1 é o instrumento que decide isso. **Onda 5** (baixa automática de Contas a Receber) está **bloqueada** pelo vínculo ausente `platform_earnings → transaction` — o mesmo pré-requisito do estorno de cobranças descartado acima.

- **Dívida:** **validação visual em ~360px NÃO foi feita** na tela de Contas & Saldos — aceite manual pendente; bloqueia release, não bloqueia merge. Cinco pontos listados no artefato de QA.
- **[CORRIGIDO — UX-001]** `"no banco"` nomeava sentidos **opostos** em duas telas: na Projeção é o saldo que o e1p **calculou**; na Conferência era o que o **banco atestou** — as duas pontas exatas da comparação, com a mesma palavra. **A correção foi do lado da Conferência** (decisão do fundador): as colunas viraram **"O que o banco diz"** × **"O que o e1p calculou"**, pareadas sob uma legenda comum e numa faixa visual compartilhada, e a frase da tela passou a usar o mesmo par. **`ROTULO_BANCO` da Projeção foi mantido de propósito:** ali o rótulo diz *onde está o dinheiro* (a parcela irmã é `ROTULO_PLATAFORMA`, outro **lugar**, não outra testemunha), e qualquer sinônimo locacional encostaria em `TOTAL_EM_CONTAS_LABEL`/`DISPONIVEL_CAIXA_LABEL` — trocando esta colisão por aquela que a divergência D-6 já pagou para separar. **A garantia é a invariante, não o nome:** `"no banco"` tem **um** consumidor (a parcela da Projeção), e agora tanto `ContasSaldosPage` quanto `ConferenciaPage` têm teste provando que não a reusam. Regra que fica: **nunca use "no banco" para nomear um saldo que o e1p não calculou** (checkpoint declarado, `<LEDGERBAL>` de OFX) — para esse lado o vocabulário é "o que o banco diz". Ver `docs/stories/8.7.story.md` (seção UX-001).
- **Dívida:** a virada de mês apaga uma conferência recente e bem-sucedida — a janela do Diagnóstico é o mês da DRE, então um saldo declarado em 28/06 que bateu exato vira 🟡 em 01/07. O motor tem o número de dias e não o usa (SIG-001).
- **Dívida:** `audit.record(target='')` em **17 call sites** — `acc.id` ainda é `None` quando `audit.record` roda logo após `db.add()`. O módulo `bank` faz `db.flush()` antes e está correto; `chart_of_accounts`, `cost_centers` e `crm` gravam trilha apontando para lugar nenhum (MNT-001).
- **Dívida:** `test_tenancy_guard.py` só varre `*/router.py` — um `service.py` que abrisse sessão global passaria batido. Auditado nesta onda: **nenhuma violação hoje**.
- **Dívida:** o gate global `test_todo_saldo_declara_origem` (varredura de contrato exigindo par de proveniência para todo campo de saldo) foi **adiado com registro formal** — hoje a cobertura é por instância. Inventário no artefato de QA: 14 campos `saldo_*_cents`, 6 sem irmão, mais 8 campos de saldo que o regex nem alcança.
- **Dívida:** `days_since_last_declared_balance` implementada e **sem consumidor**.
- **Dívida:** `packages/shared-types/src/generated.ts` defasado desde o PR #45, com **zero** menções a `bank` e sem check de drift no CI.
- **Dívida:** `scripts/check.sh` resolve `ruff`/`python` do PATH (que pode não ser o do venv) e **mascara falha de frontend** com `|| true` no vitest — rode as etapas individualmente até isso ser corrigido.
- **Dívida:** o **Epic 5 (Inteligência Financeira) nunca foi documentado aqui.** DRE, DRE em matriz, Lucratividade por contrato, Projeção de Caixa, Diagnóstico, Plano de Contas, Centros de Custo e Investimentos **existem e estão em produção**, mas quem lê só este arquivo conclui que não. Ver `docs/prd/epic-5-inteligencia-financeira.md`.

## WhatsApp Evolution: em produção de verdade (deploy 2026-08-04)

O transporte Evolution (Onda 0-3, ver `[[e1p-whatsapp-evolution-merged]]` na memória / PR #62)
foi **implantado e validado ponta-a-ponta em produção** nesta sessão: Evolution+Redis subiram na
VPS, um tenant real escaneou o QR, conectou de verdade, recebeu mensagem de texto E mídia de um
contato real, e respondeu — via UI, não via teste automatizado. **Cada etapa achou um bug real que
nenhum teste local pegava**, porque cada um dependia de infraestrutura viva (rede da VPS, a
Evolution real, o schema real da resposta dela) que o CI/testes locais não têm como exercitar.
Lição geral que se repetiu 6 vezes: **nunca confie no formato de request/response de uma API de
terceiro por suposição — teste ao vivo ou leia o código-fonte real dela** (`evolution-foundation/
evolution-api` no GitHub; ver padrão de investigação com `gh api`/`WebFetch` nos PRs abaixo).

**Bugs achados e corrigidos, nesta ordem** (cada um só apareceu depois que o anterior foi resolvido
e uma tentativa real de conexão avançou mais um passo):
1. **PR #63** — `mem_limit` da Evolution reduzido de 1g→512m só no `docker-compose.traefik.yml` (VPS compartilhada com pouca memória livre); `docker-compose.prod.yml` (VPS dedicada) ficou em 1g.
2. **PR #64** — imagem `atendai/evolution-api` não existe mais; o registro real é `evoapicloud/evolution-api`.
3. **PR #65** — `REDIS_URI` não é a env var certa; é `CACHE_REDIS_ENABLED`+`CACHE_REDIS_URI` (+`CACHE_LOCAL_ENABLED=false`). Sem isso, cache cai pra filesystem em silêncio + loop de erro nos logs.
4. **PR #66** — `evolution` só estava na rede `db_internal` (`internal: true`, sem saída pra internet — isola Postgres/Redis de propósito). O Baileys precisa alcançar a internet de verdade (servidores do WhatsApp); sem isso, DNS externo falhava dentro do container e a conexão entrava num loop silencioso de reinício, nunca completando o handshake do QR. Fix: `evolution` entra também na rede `edge` (mesmo mecanismo que já dá saída ao `api`), sem label de Traefik — continua inalcançável de fora.
5. **PR #67** — `/instance/fetchInstances` da v2.3.7 devolve os campos direto no item (`name`/`connectionStatus`), não aninhado (`instance.instanceName`/`instance.status`, formato de uma versão mais antiga que nosso código assumia). `get_status()`/`confirm()` sempre viam "desconectado" mesmo já conectado.
6. **PR #68** — `POST /webhook/set/{instance}` espera o corpo **aninhado** sob `"webhook"` (`{webhook: {enabled, url, byEvents, events, base64}}`), não solto. Sem isso, nenhum webhook era configurado — mensagens recebidas nunca chegavam na plataforma.
7. **PR #69** — mídia recebida (imagem/áudio/documento/vídeo) nunca tinha sido implementada, só texto. Payload real capturado ao vivo confirmou `imageMessage`/`audioMessage`/`documentMessage`/`documentWithCaptionMessage` (este último embrulha um nível a mais) e o mecanismo: com `webhook.base64=true`, a Evolution baixa e decifra a mídia (ela tem a `mediaKey`) e injeta em `message.base64` — evita reimplementar a criptografia de mídia do WhatsApp na mão. `ingest_webhook_payload` agora cria o `Attachment` **sincronamente** pra mídia da Evolution (ela não tem endpoint de resolução separado como a Meta — o worker assíncrono existente é Meta-only).
8. **PR #70** — despachante (`core/whatsapp/__init__.py`) nunca tinha sido de fato adaptado pra Evolution em `send_text`/`send_media`/`upload_media`: sempre chamava com `token=`/`phone_id=` (parâmetros da Meta), que a Evolution não aceita (`instance=`, credencial global). `TypeError` ao tentar responder qualquer conversa real — só apareceu porque foi a PRIMEIRA resposta de verdade enviada por um tenant Evolution.
9. **PR #72** — UX: miniatura de imagem inline (busca o blob autenticado, `<img src={objectURL}>`) em vez de só um link "Ver imagem".
10. **A conversa não tinha autor nem relógio** (achado usando a tela com conversas reais). `ingest_webhook_payload` fixava `direction=DIRECTION_IN` para TODA mensagem do webhook, e `evolution.parse_inbound` nem lia `key.fromMe` — mas o Baileys espelha no MESMO evento `messages.upsert` o que o contato mandou **e** o que o dono digitou no WhatsApp do celular dele. Resultado: as duas pontas da conversa entravam como recebidas, e a tela pintava tudo cinza-à-esquerda. Fix: `InboundMessage.from_me` (default `False` — a Meta nunca entrega mensagem própria em `messages`, só status em `statuses`) → `direction="out"` no ingest. **Três efeitos colaterais que vinham junto e foram corrigidos no mesmo passo:** (a) `is_within_session_window` conta só `DIRECTION_IN`, então mensagem NOSSA reabria a janela de 24h e liberava resposta livre onde a Meta exigiria template; (b) `unread` na lista marcava como não-lida a conversa em que quem falou por último fomos nós; (c) `pushName` de mensagem espelhada é o do **próprio dono** — batizava o cliente novo com o nome do dono (agora só nomeia quando o contato escreveu, senão cai no telefone). A trilha de auditoria ganhou ação própria (`...message.mirrored`): registrar "received" numa mensagem que o dono escreveu é trilha que mente. UI: cabeçalho com nome/telefone do contato, separador de dia (Hoje/Ontem/`dom., 19/07/2026`), horário em toda bolha e a marca **"Você ·"** nas nossas — autoria em TEXTO, não só por cor e lado.
    - ⚠️ **As mensagens já gravadas antes deste fix continuam erradas** (todas `in`) e **não têm conserto retroativo**: `fromMe` nunca foi persistido, e nada no que está no banco distingue as duas pontas. Só vale daqui pra frente.

**Duas armadilhas operacionais da VPS** (não são bug de código, são do processo de deploy):
- Depois de mudar a config do webhook via `/webhook/set` numa instância **já conectada**, a mudança pode não valer pro processo em memória (cache do canal Baileys carregado na conexão) — precisou **reiniciar o container `evolution`** (não só recriar) pra pegar a config nova. Sessões reconectam sozinhas (credenciais persistidas no Postgres/Redis), sem precisar de novo QR.
- `docker compose up -d --build <serviço>` só reconstrói o serviço **nomeado**. Rebuildar só `api` depois de um PR que também mudou frontend deixa o `web` com o build antigo, **em silêncio** (sem erro, só o comportamento antigo persistindo). Depois de qualquer merge, checar QUAIS serviços mudaram no diff antes de escolher o que rebuildar — ou rebuildar todos (`up -d --build` sem nome, como o `reference_e1p_prod_deploy` já recomendava).

**Estado atual:** conectado e funcionando ponta-a-ponta pro tenant `70c1f435-a21e-4148-a8c6-32a7e346a818` (flaviokato76@gmail.com) — QR, texto recebido, mídia recebida (imagem com miniatura inline), resposta de texto enviada, tudo validado com conversas reais em produção.

## 6.0 Correções importantes
- **[CORRIGIDO] Agenda não mostrava cobranças/contas a pagar (bug de fuso).** Eventos de dia inteiro (cobranca_receber/cobranca_pagar/prazo) são gravados à **meia-noite UTC** da data de vencimento. A Agenda casava o evento ao dia com `new Date(starts_at)` (horário LOCAL) → em fuso negativo (Brasil UTC-3) o evento "voltava" um dia e, nas bordas do mês, caía fora do range → sumia. Fix (frontend, `AgendaPage.tsx`): eventos all-day casam por **data de calendário** (`starts_at.slice(0,10)` = data UTC) e o range da busca usa fronteiras **UTC-date** (`${ymd}T00:00:00Z`), não local→UTC. Idem para a cor "atrasado". Backend sempre injetou o evento corretamente (validado). **Lição (reverberar): toda data de negócio que vira evento all-day deve ser comparada por data de calendário, nunca por horário local.**
- **[CRÍTICO, CORRIGIDO] RLS perdia o tenant no refresh pós-commit (afetava TODOS os módulos).** A `Session` ligada à Engine devolvia a conexão ao pool no `commit()`; o `db.refresh()` seguinte pegava outra conexão sem a GUC `app.current_tenant_id` → RLS escondia a linha → 500 "Could not refresh instance". Funcionava só quando o pool reusava a mesma conexão. **Fix:** `tenant_session` agora prende a Session a UMA conexão dedicada (`engine.connect()`) por todo o request; o refresh pós-commit usa a mesma conexão (GUC setada). Validado: criar em tenant novo OK em todos os módulos + isolamento entre tenants intacto. Regra: qualquer novo helper de sessão de tenant DEVE usar conexão dedicada, nunca a Engine direto.

## 6.1 Dívida técnica / TODO de segurança (de revisão QA — endereçar antes de produção)
- **Enumeração de e-mail no /register:** retorna 409 "e-mail já cadastrado" (UX comum em signup, mas revela existência). Reavaliar quando houver fluxo de e-mail/confirmação.
- **Validação de CPF/CNPJ:** ~~hoje só valida tamanho; falta dígito verificador~~ — **desatualizado, corrigido em 2026-07-30.** `apps/api/app/core/validators.py` **já valida dígito verificador** e normaliza, e é usado por `auth`, `crm`, `contracts`, `platform` e `bank`. O que resta em aberto é só a **unicidade por tenant**. (Esta entrada induziu a Story 8.2 a especificar validação fraca; o @dev conferiu o código, viu que a premissa era falsa e seguiu o padrão real — comportamento correto: **quando uma instrução se apoiar em premissa que você verificar ser falsa, siga o repo e documente**.)
- **Hardening da tabela `users` (global):** não tem RLS (login por e-mail é global). Garantir que módulos de negócio NUNCA consultem `users` via `get_db` sem filtro de tenant.
- **Idle timeout LGPD (30min):** configurado mas não implementado (JWT é stateless, expira em 7 dias). Implementar tracking de atividade / refresh curto quando o frontend de auth entrar.
- **Truncagem bcrypt por bytes (72):** pode cortar caractere multibyte; documentado, aceitável.
- **Geração de tipos:** `shared-types` é mantido à mão espelhando os schemas. Avaliar gerar TS a partir do OpenAPI do FastAPI para eliminar divergência.
- **Rastro da IA não propagado (Agenda):** `CurrentUser.is_ai` é placeholder fixo `False` — nenhum evento é criado pela IA ainda (não há endpoint/ator de IA). Quando a camada de ações da IA existir, propagar `is_ai` em create/update/cancel/reschedule (Regra de Ouro nº 3).
- **Semântica de `all_day` (Agenda):** hoje o campo é só armazenado; o conflito usa starts_at/ends_at crus. Definir normalização (ex.: `[00:00, 24:00)` no fuso do tenant) quando a UI de calendário entrar.
- **Teste de isolamento cross-tenant:** RLS é Postgres-only; os testes unitários usam SQLite e não a exercem. ✅ Validado manualmente via e2e no Docker (Postgres real). TODO: automatizar com testcontainers no CI.
- **Drift de versão venv↔produção:** o venv local tinha FastAPI mais novo que o pinado (0.115.5), o que escondeu um erro de rota 204 que só quebrou no container. Agora alinhado. **Antes de confiar só nos testes locais, rode a stack Docker** (ou recrie o venv com `pip install -r requirements.txt`). Considerar CI que rode os testes na imagem.
- **Como rodar/validar localmente:** `docker compose --env-file .env -f infra/docker-compose.yml up -d --build` → web :5173, API :8000/docs. **`--env-file .env` é obrigatório** (achado 2026-07-12): com só `-f infra/docker-compose.yml`, o Compose v5 resolve o `.env` relativo ao diretório do PRIMEIRO `-f` (`infra/`), não à raiz do repo, e ignora silenciosamente vars da raiz sem erro nenhum (afeta `ANTHROPIC_API_KEY`/`JWT_SECRET`, que seguem via `${VAR:-default}` em `environment:`). Testes: `cd apps/api && source .venv/bin/activate && pytest`. SSD exFAT: rodar `find . -name '._*' -delete` antes de builds Docker (AppleDouble quebra o sender).
  **Credenciais reais (SMTP/gateway de pagamento) usam `env_file: ../.env` no `docker-compose.yml`** (não `environment: ${VAR}`) porque o Compose interpola `${...}` inclusive DENTRO do valor final de uma variável — se o valor tiver `$` literal (ex.: API key da Asaas, formato `$aact_...`), o Compose tenta expandir isso como referência de outra variável e o valor vira string vazia, silenciosamente (sem erro, só um warning fácil de não notar: `"X variable is not set. Defaulting to a blank string"`). Regra: qualquer segredo real com `$` no valor precisa estar escapado como `$$` no `.env`, OU (melhor) chegar ao container só via `env_file:` (lido cru, sem interpolação) — nunca via `${VAR}` em `environment:`. Mesmo padrão já usado em `docker-compose.prod.yml` (`env_file: .env.prod`).
  **Logging da API (achado 2026-07-12):** `app/main.py` não tinha `logging.basicConfig()` (ao contrário de `app/worker.py`, que já tinha) — o root logger ficava sem handler, então `logger.info`/`logger.exception` de `core/email.py`, `core/whatsapp.py`, `core/payment_gateway.py` etc. nunca apareciam em `docker logs`, mesmo em caminhos de sucesso ou erro. Corrigido — se voltar a acontecer (logs "somem"), é o primeiro lugar a checar.

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

## 9. Como rodar local (e troubleshooting) — IMPORTANTE
**Topologia de dev:** o front local é o **Vite dev server** (`pnpm --filter @e1p/web dev`) em **http://localhost:5173**, que faz **proxy de `/api` → `:8000`** (ver `apps/web/vite.config.ts`). A **API** é o container `infra-api-1` em `:8000` e o **Postgres** é `infra-postgres-1` em `:5432`.
- O **container web do Docker** (`infra-web-1`) é o **build de PRODUÇÃO** (nginx estático, SEM proxy `/api` — `apps/web/nginx.conf`) e agora expõe a **porta 8081** (não a 5173), justamente para NUNCA disputar a porta do Vite. Se você acessar o 8081 as chamadas `/api` não funcionam (é estático); use-o só para inspecionar o build. **Histórico:** ele ficava em `5173:80` com `restart: unless-stopped` e voltava sozinho após reinícios do Docker, roubando a 5173 do Vite → a app "caía" (todo `/api` voltava HTML). Corrigido movendo p/ 8081.
- **Subir o stack:** `docker start infra-postgres-1 infra-api-1` (reusa containers existentes) + `pnpm --filter @e1p/web dev`. A API roda `alembic upgrade head` + seed no boot, então leva alguns segundos até o `/health` responder.
- **Bug do Docker Desktop no macOS com SSD externo + espaço no nome** ("Extreme SSD"): **recriar** containers que tenham **bind mount** desse caminho falha com `error while creating mount source path ... mkdir /host_mnt/Volumes/Extreme SSD: file exists`. Por isso o bind mount `./docker/initdb` do Postgres está **desativado (comentado)** no `infra/docker-compose.yml` — ele só servia no 1º boot (o papel RLS `e1p_app` já vive no volume nomeado `infra_postgres_data`). **Evite o botão "Start" do Docker Desktop** (recria containers e reintroduz o bug); prefira `docker start <nome>` (não recria) ou `docker compose up -d postgres api`. Dados ficam no volume nomeado — recriar o container do Postgres NÃO os apaga (só `down -v` apagaria).
  **Máquina nova / volume `infra_postgres_data` genuinamente vazio (achado 2026-07-12):** como o bind mount está desativado, o papel `e1p_app` NUNCA é criado automaticamente no 1º boot — a API sobe mas toda query falha com `password authentication failed for user "e1p_app"`. Rode uma vez, manualmente, o conteúdo de `infra/docker/initdb/01-rls-enforce.sql` contra o Postgres (`docker exec infra-postgres-1 psql -U e1puser -d e1pdb -c "CREATE ROLE e1p_app WITH LOGIN PASSWORD 'e1ppass' NOSUPERUSER; GRANT ALL PRIVILEGES ON DATABASE e1pdb TO e1p_app; GRANT ALL ON SCHEMA public TO e1p_app;"`), depois `docker restart infra-api-1`.
- A imagem do `infra-api-1` é estática (sem bind mount do código): mudanças no backend exigem **rebuild** (`docker compose build api`) — ou, para teste rápido, `docker cp` dos arquivos para dentro do container (some no rebuild).
