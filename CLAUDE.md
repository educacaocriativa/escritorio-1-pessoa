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
- **IA:** Anthropic SDK. **Não há modelo global** — cada tarefa tem o seu em `core/ai.MODELO_POR_TAREFA`, e toda chamada é contabilizada (ver §Contabilidade de IA).
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
4. **Escreva a entrada NESTE arquivo** — o que passou a existir, a regra que fica para quem mexer
   nisso depois, e a dívida que sobrou. Escrita a partir do **código que subiu**, não do que a story
   pretendia. Dívida que esta mudança FECHOU sai daqui: dívida resolvida e ainda escrita manda o
   próximo leitor resolver de novo o que já está resolvido.
5. Só considere a tarefa concluída quando os 3 agentes passarem **E** a entrada existir.

> **Por que o passo 4 tem o mesmo peso do teste.** Documentar como último passo é documentar o que
> vai ser cortado — a sessão acaba, o CI fica verde, o fundador diz "sobe", e a entrada nunca é
> escrita. Não dói na hora: a funcionalidade funciona. Dói depois, e sempre no mesmo lugar — quem lê
> só este arquivo conclui que a funcionalidade **não existe**. Foi exatamente assim que o **Epic 5
> inteiro** (9 stories, em produção desde julho) ficou invisível aqui por um mês.
>
> Por isso toda story carrega, como **último AC numerado**, a entrada no CLAUDE.md — mesma régua do
> teste: um AC que ninguém pula. Quem valida: `story-draft-checklist` §7 (no draft, pelo @sm/@po) e
> `story-dod-checklist` item 7 (antes de "Ready for Review", pelo @dev). Refactor puro não some com
> o AC: satisfaz com uma linha explícita dizendo que nada mudou para o próximo leitor, e por quê.

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
  - **Dívida:** gateway real (Asaas/Mercado Pago) p/ gerar boleto/Pix de verdade + webhook real; régua de cobrança (lembretes automáticos) + juros/multa; estorno; ~~`is_overdue`/summary usam dia em UTC~~ — **corrigido em 2026-08-05** (ver §6.0 "o sistema inteiro passou a viver no fuso do tenant").
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

## Financeiro: Inteligência Financeira (Epic 5 — Stories 5.1–5.9 ✅ em produção desde 2026-07-11)
> Docs: `docs/prd/epic-5-inteligencia-financeira.md` · stories `docs/stories/5.1`–`5.9` · a DRE em
> matriz e a tela de Lucratividade vieram **fora do fluxo de story** (PRs #46–#52, 2026-07-23/24) e
> estão em `docs/runlogs/financeiro-dre-matriz-lucratividade-RUN-LOG.md`.

**Por que existe.** Contas a Pagar/Receber dizem o que entrou e o que saiu. Nenhuma delas responde
**se dá lucro, de onde vem o lucro, e se o caixa aguenta até lá**. O Epic 5 é a camada analítica
**só-leitura** sobre os dados operacionais que já existiam — não um módulo de escrituração, e não
concorre com o contador. O Epic 8 (abaixo) veio depois para ancorar essa camada no banco: sem
âncora, DRE infla lucro, Lucratividade distorce e a Projeção mente.

### As 4 regras que nenhum relatório deste módulo pode violar
1. **O sinal vem da TABELA DE ORIGEM, nunca do `grupo_dre`.** `Charge` (entrada) = **+1**;
   `Payable` (saída) = **−1**. O grupo é só rótulo de exibição — **nunca derive nem inverta o sinal
   a partir dele**. O total de um grupo é a soma **já-com-sinal**; o resultado é a **SOMA** dos
   grupos de resultado (todos menos `INVESTIMENTO`; `SEM_CATEGORIA` fica fora).
   Isto **generaliza** `RECEITA − CUSTO − DESPESA − TRIBUTOS ± FINANCEIRO`, **não é idêntico a ela**:
   `chart_account_id` é livre nas duas tabelas, então existe `Charge` em `CUSTO_DIRETO` (nota de
   crédito) e `Payable` em `RECEITA` (reembolso). Nesses casos as duas divergem, e é o **sinal
   natural que está certo** — o estorno *reduz* o grupo em vez de inflá-lo.
   **Footgun:** os totais já vêm assinados (custo é NEGATIVO). Quem fizer `receita − custo`
   esperando custo positivo faz dupla-negação. Consuma `resultado_cents`, não re-derive.
   Regra canônica escrita por extenso no docstring de `financial_intelligence/dre.py` — é lá que o
   próximo relatório do módulo deve ler antes de somar qualquer coisa.
2. **Duas datas, dois regimes — nunca inverter.** DRE e lucratividade usam **`competence_date`**
   (competência); caixa e projeção usam **`paid_at`** (o dinheiro mudando de mão), e enquanto o
   item está em aberto a projeção usa `due_date` como pagamento *previsto*. Fixado na 5.2, no
   docstring dos models de `payables`/`receivables`.
3. **Análise não escreve.** Rateio de overhead, baldes da fila, células da matriz, rentabilidade —
   tudo calculado na leitura, nada persistido no lançamento original. Cada serviço tem teste que
   compara snapshot antes/depois de duas chamadas.
4. **Regra determinística primeiro, IA narrando depois.** Os sinais 🟢🟡🔴 existem e estão corretos
   **sem `ANTHROPIC_API_KEY`** — a IA só reformula texto, nunca origina número.

### O que existe (tudo com item no menu, grupo "Análise & Configuração Financeira")
| Tela | Rota | Backend |
|---|---|---|
| **Plano de contas** (5.1) | `/financeiro/plano-contas` | `chart_of_accounts/` · migration **0045** |
| **DRE** + **DRE em matriz** (5.3 + PRs #49–#52) | `/financeiro/dre` | `financial_intelligence/dre.py` · `GET /dre`, `/dre/matrix`, `/dre/matrix/entries` |
| **Lucratividade** por contrato (5.4 + PR #47) | `/financeiro/lucratividade` e `/financeiro/contratos/:id/dre` | `profitability.py` · `GET /contracts-dre`, `/contracts/{id}/dre`, `/contracts/{id}/ledger` · migration **0047** |
| **Centros de custo** (5.5) | `/financeiro/centros-custo` | `cost_centers/` · `GET /by-cost-center` · migration **0048** |
| **Investimentos** (5.6) | `/financeiro/investimentos` | `investments/` · migration **0049** |
| **Projeção de caixa** (5.7) | `/financeiro/projecao-caixa` | `projection.py` · `GET /projection` |
| **Diagnóstico** (5.8) | `/financeiro/diagnostico` | `engine.py` + `diagnostics.py` + `ai_narrator.py` · `GET /diagnostics` |
| **Fila de pagamentos** (5.9) | `/financeiro/fila-pagamentos` | `payables.payment_queue()` · `GET /payables/queue` · sem migration |

- **Fundação (5.1/5.2).** `ChartAccount` (RLS): `grupo_dre` num enum fixo (`RECEITA`, `CUSTO_DIRETO`,
  `DESPESA_FIXA`, `TRIBUTOS`, `FINANCEIRO`, `INVESTIMENTO`) + categoria livre única por grupo;
  arquivar não apaga histórico. A **0046** acrescentou `competence_date`/`paid_at`/`chart_account_id`
  a `charges` e `payables` — tudo **nullable**, nada legado invalidado, competência com backfill a
  partir do vencimento. Não classificado cai no bucket **"sem categoria"**, que aparece no relatório
  em vez de sumir.
  - ⚠️ **A armadilha que a 0046 pagou por nós, e que qualquer migration futura com `UPDATE` vai
    encontrar de novo:** o backfill rodava como **no-op silencioso** no Postgres real. As tabelas têm
    `FORCE ROW LEVEL SECURITY` e a migration roda como `e1p_app` (non-superuser) **sem**
    `app.current_tenant_id` setado → a política filtra o `UPDATE` a **zero linhas**, sem erro. **O
    SQLite dos testes unitários não pega isso.** Fix: desabilitar a RLS só durante o backfill e
    restaurar (`ENABLE` + `FORCE`) — DDL é transacional no Postgres, sem janela de exposição.
    **Regra: migration que faz `UPDATE` em tabela com FORCE-RLS precisa ser validada contra Postgres
    real, não contra a suíte.**
- **DRE em matriz** (a tela que o menu chama de "DRE"): meses nas colunas, grupos/categorias nas
  linhas, agrupável por **DRE** ou por **centro de custo** (`group_by`). Clicar numa célula abre o
  drawer com os lançamentos analíticos daquela categoria naquele mês. `TOTAL GERAL` aparece antes do
  Investimento, e há uma linha `TOTAL GERAL + INVESTIMENTO` (gasto do período incluindo capex) —
  somada por `kind="informational"`, não pelo grupo nomeado, porque no modo centro de custo as linhas
  de investimento ficam espalhadas e não têm seção própria.
- **Lucratividade (5.4).** O eixo "projeto" é o **`Contract`** que já existia — `contract_id`
  nullable em `charges`/`payables`; sem vínculo, o lançamento cai no bucket implícito **"Empresa"**
  (overhead). Calcula margem de contribuição (R$ e %), break-even e o **rateio do overhead só na
  leitura**. Divisão por zero coberta nos três pontos (margem sem receita, break-even sem margem
  positiva, rateio sem receita) — retorna `None`/0, nunca 500.
- **Investimentos (5.6) — o único caminho de escrita novo no modelo de dinheiro.** Registrar
  rendimento cria uma **`Charge` já nascida `paid`** (com `external_ref="investment:{id}"`,
  `chart_account_id` no grupo `FINANCEIRO`) **sem** passar por `mark_paid`/`build_transaction` —
  logo **não gera `Transaction` nem `PlatformEarning`**: rendimento é receita financeira, não venda
  com split. Como nasce paga, um webhook posterior é no-op idempotente. Em troca, ela é **filtrada
  na leitura** de `receivables.list_charges` e do `paid` do summary
  (`coalesce(external_ref,'') NOT LIKE 'investment:%'` — o `coalesce` é obrigatório: sem ele o `NOT
  LIKE` sobre NULL avalia NULL e some com tudo), para não poluir a tela de Cobranças. Aparece na DRE
  no grupo FINANCEIRO, que é onde deve aparecer.
- **Projeção (5.7).** 30/60/90 dias + runway, em regime de caixa. **Itens vencidos e ainda em aberto
  entram em todas as janelas** — decisão da @architect contra a implementação original: esconder
  obrigação vencida deixa a projeção otimista exatamente para quem já está apertado. A incerteza é
  comunicada **por transparência** (`overdue_inflow_cents`/`overdue_outflow_cents` expostos à parte),
  nunca por exclusão silenciosa. ⚠️ **O `saldo_inicial` desta projeção mudou no Epic 8** (Ondas 0 e
  2): não é mais o saldo da Carteira — leia a seção do Epic 8 abaixo antes de mexer nele.
- **Diagnóstico (5.8).** `engine.py` é **puro** (sem I/O, sem relógio) e determinístico; `diagnostics.py`
  faz a leitura; `ai_narrator.py` narra em PT-BR **depois** de passar o texto pelo `core/anonymizer`
  e grava rastro "Ação executada pela IA" (Regras de Ouro nº 2 e nº 3). Os sinais de hoje: margem,
  runway, janela de projeção, rentabilidade — mais completude, off-rail e débito suspeito, que o
  Epic 8 acrescentou. A pureza do `engine.py` é garantida por **gate AST**, não por convenção.

### Dívida (verificada contra o código, 2026-08-07)
- 🔴 **O anonimizador não cobre nome livre, e o Diagnóstico manda nome livre.** `core/anonymizer.py`
  é 100% regex sobre PII estrutural (CPF/CNPJ/e-mail/telefone/cartão) — **sem NER**. Duas regras do
  motor injetam nome cru no payload que vai ao Claude: `_margin_signals` usa `contract.title` (e
  título de contrato carrega nome de contraparte rotineiramente) e `_investment_signals` usa
  `inv.name`. **É débito transversal do core, não defeito da 5.8** — o Jurídico, em produção e sob
  segredo de justiça, tem exatamente a mesma lacuna. O fundador **aceitou o risco residual em
  2026-07-11**; o gate registrado é: **não expor isto com `ANTHROPIC_API_KEY` real em produção sem o
  hardening do anonimizador (story própria, escopo Financeiro + Jurídico) ou um aceite adicional por
  escrito.** Ver `docs/stories/5.8.story.md` §"PENDÊNCIA FORMAL A ABRIR" e §6.1 abaixo.
- **Duas fórmulas de "resultado" convivem.** A tela de contrato segue o AC2 (margem de contribuição =
  só `RECEITA` + `CUSTO_DIRETO`; outros grupos do contrato ficam fora, sinalizados por uma `note`);
  a regra geral da 5.3 somaria todos os grupos de resultado. A divergência foi declarada pelo @dev e
  nunca reconciliada. Quem for unificar: decida qual é a canônica **antes** de escrever a terceira.
- **Bucket "sem categoria" mostra a soma líquida** (receber − pagar) numa linha só; separar entradas
  de saídas se virar ruído.
- **Sem observabilidade do fallback `COALESCE(competence_date, due_date)`** — contar quantas linhas
  caem no fallback denunciaria backfill incompleto da 0046. Hoje ninguém conta.
- **`kind`/`index_rate_label` do investimento são rótulos livres** — nenhuma integração com CDI/IPCA
  reais; rentabilidade é sobre o que foi digitado.
- **Os cortes da fila (hoje / 7 / 30 dias) são convenção da 5.9**, não do PRD — bordas inclusivas à
  direita, cobertas por teste em cada borda.
- **Seletor "vincular a contrato" só existe nos modais de CRIAÇÃO** de Pagar/Cobranças (o relink por
  `PATCH` funciona e é testado, só não tem UI); e a Ficha 360° do cliente não tem link "Ver DRE".
- **`paid_at` não aparece em lugar nenhum da tela de DRE** (nem na matriz, nem no drawer). Follow-up
  identificado e não pedido.
- **Render-test de DOM das telas do Epic 5.** As stories registraram isto como limitação de tooling
  ("o projeto não tem jsdom") — **a premissa não vale mais**: `jsdom` + `@testing-library` entraram
  desde então e outras telas já têm `.test.tsx`. O que falta agora é escrever os testes de
  `DrePage`, `ContratoDrePage`, `DiagnosticoPage`, `InvestimentosPage`, `PlanoContasPage` e
  `CentrosCustoPage` — a lógica pura já é coberta pelos `.ts` irmãos.
- **Nenhuma das 5 waves da DRE em matriz / Lucratividade tem story formal** em `docs/stories/`.
  Dívida de rastreabilidade registrada 5 vezes no RUN-LOG e nunca fechada. Foi assim que uma
  feature inteira ficou pronta numa worktree órfã por semanas sem ninguém saber — ver o RUN-LOG.

## Financeiro: Controle Bancário e Conferência (Epic 8 — Ondas 0, 1 e 2 ✅ em produção)
> Docs: `docs/prd/epic-8-controle-bancario.md` · `docs/architecture/controle-bancario-design.md` + `...-ratificacao.md` · `docs/decisions/0003-controle-bancario-nativo.md` · `docs/qa/epic-8-onda-0-1-gate-2026-07-30.md` · pesquisa em `docs/research/2026-07-29-*`
> Onda 2: `docs/architecture/controle-bancario-onda2-design.md` + `...-onda2-ratificacao.md` · `docs/qa/epic-8-onda-2-gate-2026-08-04.md` (veredito **CONCERNS**) · `docs/qa/epic-8-gate-8.19-8.20-2026-08-07.md`

**Por que existe.** Receber tem três testemunhas independentes (gateway, webhook, o dinheiro entrando). **Pagar não tem nenhuma**: se o dono paga pelo app do banco e não lança, nada protesta — e o silêncio de uma despesa não lançada é indistinguível do silêncio de um mês sem despesa. Sem âncora externa, DRE infla lucro, Lucratividade distorce e a Projeção mente. O banco é a testemunha que faltava. **O objetivo é achar furos, não fazer escrituração** — não é competir com o contador.

### As 7 regras que impedem o próximo bug (leia antes de mexer em qualquer coisa com saldo)

1. **A Regra dos Planos.** Três planos de dinheiro que NÃO se cruzam: **plataforma** (`transactions`, split 40/30/20, `platform_earnings`), **negócio** (`charges`, `payables`), **banco** (`bank_*`). O único contato legítimo entre plataforma e banco é o payout da Carteira (**Onda 3**, não construída). **Foi misturar plano de plataforma com plano de banco que produziu o bug de origem.** Gates estruturais em `apps/api/tests/test_money_planes.py` reprovam a reintrodução.
2. **Dois eixos de proveniência, nunca achatados num campo.** `*_origem` = **plano** (`plataforma｜banco｜misto｜indisponivel`, em `app/core/money_planes.py`); `*_fonte` = **porta de entrada** (`manual｜ofx`, em `bank/models.py`). Os valores `declarado` e `extrato` foram **revogados** — eram o eixo B disfarçado.
3. **Todo campo de saldo em schema de saída declara sua proveniência.** Comparar saldos só é legítimo quando ambos são do mesmo plano.
4. **Saldo é DERIVADO dos movimentos, nunca coluna, nunca digitado.**
5. **O checkpoint NUNCA corrige o saldo derivado.** Se corrigisse, a divergência iria a zero por construção e a métrica que justifica o épico morreria. Testado em `test_bank_checkpoints.py`.
6. **A conferência é POR CONTA, com a mesma data de referência dos dois lados** (o `reference_date` do checkpoint daquela conta — não "hoje", não uma data comum). `derived_balances_as_of` é **PROIBIDA** na conferência: recebe um `as_of` só, e usá-la ali compara saldos de datas diferentes. Seu consumidor legítimo é a tela de lista. Varredura AST reprova a chamada.
7. **Dentro da banda: verde e SILÊNCIO.** Banda `max(R$ 50, 0,5%)`, borda `==` é dentro. **Fixa de propósito** — a divergência é o instrumento que mede o gate de decisão das ondas de importação, e régua ajustável pelo tenant invalidaria a leitura. ⚠️ **Mas leia a correção do gate acima antes de usar esse número para decidir qualquer coisa**: a leitura só vale a partir do primeiro ciclo completo posterior à Onda 2 (a origem do movimento). Antes disso a divergência mede a própria incompletude do sistema. Uma tela que grita por R$ 3 destrói a confiança no sinal.

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

**⚠️ CORREÇÃO (2026-07-30, mesmo dia): a leitura do gate abaixo estava ERRADA e quase custou a decisão de produto.**

A versão anterior deste parágrafo dizia: *"se a divergência medida na Onda 1 for pequena e estável, as Ondas de import são over-engineering; a Onda 1 é o instrumento que decide isso."* **Isso é falso**, e o erro é instrutivo.

A Onda 1 mede a divergência com o razão bancário **vazio**, porque nada no sistema escrevia nele — baixar uma conta a pagar não gerava movimento bancário. Então a divergência medida ali é enorme **por construção**: ela mede a **ausência de uma porta**, não o furo. E teria argumentado, com número grande e aparentemente sólido, para liberar justamente a onda mais cara e a única com dependência externa perpétua (import de OFX). **A feature que faltava teria pedido a construção da feature mais cara.**

**A leitura do gate só é válida a partir do primeiro ciclo completo posterior à Onda 2**, e sob a pré-condição de que toda conta paga e todo recebimento da janela tenham conta bancária informada. Antes disso, o número não significa nada.

⚠️ **E mesmo isto é otimista demais — a ratificação da Onda 2 corrigiu esta frase.** Lida ao pé da letra, a pré-condição acima é **insatisfazível** (uma cobrança do trilho nunca terá conta bancária, pela Invariante do Trilho), e reescrita em termos executáveis ela se parte em quatro, cada um zerado por uma onda diferente. **O gate não abre "depois da Onda 2" em geral: abre para um tenant cujos únicos eventos que movem conta real na janela sejam baixa de Contas a Pagar e recebimento fora do trilho.** Quem registra rendimento de aplicação precisa da Onda **2b**; quando o payout virar real, da **3**. Ver a seção da Onda 2 abaixo, item 5.

**Regra de método que fica** (vale para qualquer métrica que decida escopo): antes de usar um número como gate, pergunte **o que ele mede quando o sistema está incompleto**. Se a resposta for "mede a própria incompletude", ele não é gate — é termômetro do que ainda não foi construído, e vai sempre pedir mais construção.

**⚠️ REGRA — INSTANCIAÇÃO OBRIGATÓRIA** (derivada no mesmo dia, depois de a mesma seção quebrar duas vezes de formas opostas — primeiro medindo a própria incompletude, depois virando insatisfazível):

> Todo conjunto definido por **descrição** num documento de arquitetura nasce com **pelo menos um membro E um não-membro escritos, no mesmo parágrafo**. Sem o membro, o conjunto é vazio e você descobre tarde. Sem o não-membro, a condição é trivial e não decide nada. **Em critério de decisão é obrigatória.**

Por que o critério de decisão é onde mais se erra: todo o resto do design tem **consumidor mecânico** que protesta — a função é chamada na página seguinte, o índice é criado por uma migration, a invariante ganha teste no CI. **O critério de decisão é o único artefato cujo consumidor é um humano num ciclo futuro** — e humano não levanta `TypeError`. Quem lê *"toda cobrança recebida precisa ter conta informada"* assente, porque a frase é razoável; e ela é razoável **e** insatisfazível, sem nada entre as duas que dispare. Não erra por ser difícil: erra por ser a única seção sem ninguém para contradizê-la.

Custo de aplicar, medido nos quatro casos reais que teria pego: 2 a 5 segundos cada. Nenhum exigia mais análise — todos exigiam **um exemplo**.

**Ondas** (renumeradas — a numeração antiga em qualquer doc anterior a 30/07/2026 aponta para outro conteúdo): `0 ✅ → 1 ✅ → 2 ✅ (origem do movimento) → 2b (aplicação) → 3 (payout) → 4 (import OFX) → 5 (match) → 6 (baixa de Contas a Receber, **bloqueada** pelo vínculo ausente `platform_earnings → transaction`, mesmo pré-requisito do estorno de cobranças descartado acima)`. Critério da ordem: **dependência externa crescente** — 2, 2b e 3 não dependem de nada fora do repositório.

**A Regra da Origem** (Onda 2, `docs/architecture/controle-bancario-onda2-design.md`): todo evento que o sistema já emite e que move dinheiro no banco **escreve o movimento bancário**; a porta manual e a importação existem para o **resíduo**, e só o resíduo justifica o custo delas. Antes de desenhar a porta de entrada de um plano de dados novo, enumere os eventos que o sistema já emite e ligue-os primeiro — foi não fazer isso que produziu o erro do gate acima.

- **Dívida:** **validação visual em ~360px NÃO foi feita** na tela de Contas & Saldos — aceite manual pendente; bloqueia release, não bloqueia merge. Cinco pontos listados no artefato de QA.
- **[CORRIGIDO — UX-001]** `"no banco"` nomeava sentidos **opostos** em duas telas: na Projeção é o saldo que o e1p **calculou**; na Conferência era o que o **banco atestou** — as duas pontas exatas da comparação, com a mesma palavra. **A correção foi do lado da Conferência** (decisão do fundador): as colunas viraram **"O que o banco diz"** × **"O que o e1p calculou"**, pareadas sob uma legenda comum e numa faixa visual compartilhada, e a frase da tela passou a usar o mesmo par. **`ROTULO_BANCO` da Projeção foi mantido de propósito:** ali o rótulo diz *onde está o dinheiro* (a parcela irmã é `ROTULO_PLATAFORMA`, outro **lugar**, não outra testemunha), e qualquer sinônimo locacional encostaria em `TOTAL_EM_CONTAS_LABEL`/`DISPONIVEL_CAIXA_LABEL` — trocando esta colisão por aquela que a divergência D-6 já pagou para separar. **A garantia é a invariante, não o nome:** `"no banco"` tem **um** consumidor (a parcela da Projeção), e agora tanto `ContasSaldosPage` quanto `ConferenciaPage` têm teste provando que não a reusam. Regra que fica: **nunca use "no banco" para nomear um saldo que o e1p não calculou** (checkpoint declarado, `<LEDGERBAL>` de OFX) — para esse lado o vocabulário é "o que o banco diz". Ver `docs/stories/8.7.story.md` (seção UX-001).
- **Dívida:** a virada de mês apaga uma conferência recente e bem-sucedida — a janela do Diagnóstico é o mês da DRE, então um saldo declarado em 28/06 que bateu exato vira 🟡 em 01/07. O motor tem o número de dias e não o usa (SIG-001).
- **Dívida:** `audit.record(target='')` em **17 call sites** — `acc.id` ainda é `None` quando `audit.record` roda logo após `db.add()`. O módulo `bank` faz `db.flush()` antes e está correto; `chart_of_accounts`, `cost_centers` e `crm` gravam trilha apontando para lugar nenhum (MNT-001).
- **Dívida:** `test_tenancy_guard.py` só varre `*/router.py` — um `service.py` que abrisse sessão global passaria batido. Auditado nesta onda: **nenhuma violação hoje**.
- **Dívida:** o gate global `test_todo_saldo_declara_origem` (varredura de contrato exigindo par de proveniência para todo campo de saldo) foi **adiado com registro formal** — hoje a cobertura é por instância. Inventário no artefato de QA: 14 campos `saldo_*_cents`, 6 sem irmão, mais 8 campos de saldo que o regex nem alcança.
- **Dívida:** `days_since_last_declared_balance` implementada e **sem consumidor**.
- **Dívida:** `packages/shared-types/src/generated.ts` defasado desde o PR #45, com **zero** menções a `bank` e sem check de drift no CI.
- **Dívida:** `scripts/check.sh` resolve `ruff`/`python` do PATH (que pode não ser o do venv) e **mascara falha de frontend** com `|| true` no vitest — rode as etapas individualmente até isso ser corrigido.
- ~~**Dívida:** o Epic 5 nunca foi documentado aqui.~~ **FECHADA em 2026-08-07** — ver a seção
  "Financeiro: Inteligência Financeira (Epic 5)" acima. A camada que o Epic 8 ancora agora está
  escrita. E a causa raiz foi fechada junto: a entrada no CLAUDE.md virou **AC obrigatório de toda
  story** (§5, passo 4) — documentar deixou de ser o último passo, que é o passo que se corta.

### Onda 2 — a origem do movimento (Stories 8.9–8.20, PR #71, 2026-08-04)

Antes dela o razão bancário era livro em branco: **nada no e1p escrevia nele**, e baixar uma conta a
pagar não gerava movimento bancário nenhum. É por isso que a divergência da Onda 1 media a ausência
de uma porta e não o furo (a correção do gate acima). A Onda 2 abre a porta: **todo evento que o
sistema já emite e que move dinheiro numa conta real escreve o movimento, na mesma transação**, e a
porta manual e a importação passam a existir só para o **resíduo**.

⚠️ **As migrations desta onda são a `0064` e a `0065` — não a `0061`/`0062`.** As stories e o gate de
QA dizem `0061`/`0062`; foram renumeradas no merge, porque as frentes de WhatsApp (`0062`, `0063`,
`0066`–`0072`) e do fuso do tenant (`0073`) entraram no meio. A 8.18 exigia ler `alembic heads`
**programaticamente** antes de escrever o `down_revision` e por isso não quebrou; as que copiaram o
número do documento erraram **todas as vezes**. Vale para a baseline de testes também: as stories
declararam `1051/22/304` da 8.9 até a 8.20, contra `1451/38/476` medidos pelo gate. **O repo vence o
documento, e a divergência se mede antes de começar, nunca depois de o CI ficar vermelho.**

#### 1. A classe de defeito que mais custou: o documento que afirma sobre a camada de baixo

**Quatro vezes neste épico um comentário ou docstring descreveu o comportamento de outro módulo, e
nenhuma das quatro tinha código atrás.** Não são descuidos isolados — é uma classe, e é a que produz
os defeitos mais caros porque *desliga quem viria conferir*:

- **A docstring que matou 36 testes.** `_validate_reference_date` dizia que declarar o saldo na data
  de abertura é *"o caso mais sadio que existe"* e que **"a comparação vale"**. A premissa está
  certa — a data pode ser gravada sem inconsistência, que era a pergunta **da 8.4**. A conclusão
  responde a pergunta **da 8.5** (*"esta comparação detecta alguma coisa?"*), cuja resposta é **não**,
  pelo mesmo motivo. **Duas perguntas, uma resposta, sinal trocado.** Consequência: dos 36 testes de
  `test_bank_reconciliation_report.py`, **zero** exercitavam o caso de propósito — quem foi escrever
  o teste leu que o caso era o mais sadio que existe e foi testar outra coisa. E havia uma **segunda
  ponta** repetindo a frase (a docstring de `test_data_igual_a_abertura_e_aceita`), que confirmaria o
  erro para quem fosse conferir. Corrigido pela 8.20; hoje um teste assere que a docstring **não**
  contém `"a comparação vale"` e **contém** `"tautológica"`.
- **A Regra da Origem (d) existia só em prosa.** A 8.9 escreveu *"movimento de origem do sistema não é
  editável nem ignorável"* na docstring, e o comentário em `update_transaction` afirmava que a edição
  *"é impedida antes, pela Regra da Origem (d)"* — **sem nada no código**. Nem `update_transaction` nem
  `ignore_transaction` olhavam para `tx.source`. Qualquer perna de transferência e todo movimento de
  `payable`/`charge` desde a 8.12 podiam ser **ignorados pela tela**, e ignorar uma das duas pernas de
  uma transferência produz na Conferência uma divergência com a aparência exata de lançamento
  faltante. A 8.18 teve de implementar a guarda que deveria herdar (`_recusa_se_origem_do_sistema`,
  `bank/service.py:1167`, escrita contra `SOURCES_SISTEMA`, nunca contra `'transfer'` solto).
- **`app/scripts/bank_audit.py` era citado como ativo existente em três documentos e nunca existiu.**
  O epic mandava "não recriar" um script inexistente. Sem o `grep` do @po, o @dev o teria criado
  inteiro — escopo inventado. A obrigação virou **teste**, não script.
- A quarta é a entrada de CPF/CNPJ do §6.1 deste arquivo, que induziu a 8.2 a especificar validação
  fraca.

> **A regra que fica:** *"o valor é bem definido"* e *"o valor é informativo"* são afirmações
> diferentes, e a primeira **não implica** a segunda. Toda vez que uma docstring de validação (que
> responde *"posso gravar isto?"*) opina sobre o **consumo** do dado (*"e serve para X"*), a opinião
> está fora da jurisdição de quem a escreveu — e **não vai ter teste, porque o teste dela mora no
> outro módulo**. Uma afirmação sobre o comportamento de outra camada é verificável; verifique-a ou
> não a escreva.

#### 2. O teste que passa e não prova nada — oito ocorrências independentes

Foi a família dominante da onda. Quase toda armadilha cara aqui foi **teste verde sobre código
errado**, e o mutante foi o único instrumento que as achou. As formas, todas reais:

- **Afirma o mecanismo, não o efeito.** `expect(linha.className).toContain("flex-wrap")` passou com a
  `FilaPagamentosPage` **quebrada em produção por duas sessões**: `flex-wrap` sozinho não quebra a
  linha quando a descrição é `min-w-0 flex-1` (`flex: 1 1 0%` encolhe até caber, e o wrap nunca age).
  Duas auditorias estruturais deram confiança; a terceira sessão — a primeira com stack de dev viva —
  viu a tela. Custou o **terceiro** PR de fix de campo por 360px (#89, 2026-08-06), depois dos #56 e
  #58 que o epic já contabilizava. **Layout só se prova medindo.**
- **Par de recortes complementares sem caso na borda.** O mutante `posted_at > since` → `>=`
  **sobreviveu a 58 testes verdes**: todos os cenários usavam data futura, e a borda era o único lugar
  onde os dois recortes podem se sobrepor. Regra: **um teste em cada lado passa com os dois
  operadores** — a invariante tem de ser escrita como partição (`(…, hoje]` e `(hoje, …)`, sem
  sobreposição e sem buraco).
- **`and` de duas condições com um caso só.** A guarda `fitid IS NULL AND import_batch_id IS NULL`
  era testada com as duas setadas juntas; remover metade mantinha a linha viva pelo outro marcador.
  **Uma condição, um caso.**
- **Asserção por substring genérica.** `"trilho" in detail` casava também com *"fora do trilho"*, e a
  guarda podia ser removida sem ninguém notar. A distinção importa fora do teste: mandar quem tem
  dinheiro na Carteira para *"use a edição da cobrança"* leva o dono a um lugar que não resolve.
- **O cenário não produzia o estado que o teste dizia medir.** Um teste de dupla contagem de agendada
  agendava *"para hoje"* — e a borda é estrita (`paid_on == hoje ⇒ paid`), então **não havia
  `scheduled` nenhum no banco**. Verde, medindo o vazio. Hoje a pré-condição (`status == "scheduled"`)
  é asserida **antes** de o número ser medido.
- **Um teste caía no caso degenerado por acidente e passava por causa do bug.**
  `test_checkpoint_na_borda_do_start_serve` usava `opening_date` e `reference_date` iguais. Consertado
  **na fixture**, com a docstring dizendo **por que** a data foi afastada — senão a próxima pessoa
  "simplifica" de volta.
- **Gate estático não vê o que não é import.** Uma anotação `-> "Payable | None"` **em string, sem
  import nenhum**, passa nos dois gates da 8.9 (AST *e* texto cru). Só morre com um gate que proíba a
  **string** em qualquer posição. E o mutante `importlib.import_module("app.modules." + "pay" +
  "ables")` **sobreviveu ao gate de QA** — teto conhecido de qualquer gate estático, registrado como
  INFO e não como falha.
- **O remédio óbvio cobre um ramo e deixa o outro.** *"Se a divergência der zero, ignore"* resolve o
  🟢 falso e **deixa vivo** o ramo em que as duas declarações discordam e o produto manda o dono caçar
  um lançamento que não existe. Só o teste do segundo ramo mata o mutante.

> **A regra que fica, escrita na 8.9 e reconfirmada na 8.14:** **um mutante que nenhum teste mata não
> é um teste faltando — é um teste do TIPO ERRADO.** E: restaure mutação por **cópia de arquivo, nunca
> por `git checkout`** — um `checkout` sobre arquivo com trabalho não commitado já apagou uma sessão
> inteira nesta onda.

#### 3. O épico quase se auto-aprovou, duas vezes

`derived_balance(until=opening_date) ≡ opening_balance_cents` **por construção** (`_movements_sums`
usa `posted_at > opening_date`, estrito). Então declarar o saldo no dia da abertura produz
`divergencia_cents == 0` com qualquer tolerância, satisfaz `todas_batendo` e emite **🟢 "Está tudo
batendo"** para um tenant com 45 contas pagas e razão bancário **vazio**. É a mesma família do erro do
gate: **um número que mede a própria incompletude com aparência de fato.**

- **A correção é "não avaliável no bloco 1, VÁLIDO no bloco 4"** — o degenerado é a **comparação**, não
  a **declaração**. *"O saldo da conta no dia em que ela abriu"* é verdade, e recusá-la com 422
  apagaria uma afirmação verdadeira: o inverso do princípio da Onda 0. **Rejeitado também "aceitar e
  apenas anotar ao lado"** — é a pior das três: **uma nota que convive com o verde perde para o
  verde.**
- **A segunda porta era materializar o saldo de abertura como checkpoint** (a direção "natural", e o
  que a 8.19 quase fez). Injetaria exatamente o mesmo 🟢, agora **no dia do cadastro**. A diferença que
  importa: um checkpoint que o dono declara **por ato** pode valer qualquer número; o materializado
  **não pode** — ele é literalmente a âncora do derivado. **Um checkpoint que a conferência precisa
  ignorar não é um checkpoint.**
- **Por isso a 8.20 tinha de mergear ANTES da 8.16** (epic §6.1): a 8.16 consome o bloco 1 para o sinal
  de completude, e com a comparação degenerada de pé o épico ganha um caminho para emitir 🟢 no mesmo
  ciclo em que a nota do bloco 4 diria que o gate ainda não pode ser lido.
- **O 🟢 é segurado por `divergencia_cents is not None`, não pelo contador de dias** — sutileza que a
  8.19 poderia ter quebrado sem perceber ao fazer o contador nunca mais ser `None`.

#### 4. A premissa sobre o dado que ninguém verificou com o dono — três em três semanas

A 8.19 nasceu com **duas premissas falsas**, as duas mortas por uma frase do fundador:

- a heurística `opening_balance_cents != 0` para separar *"digitou"* de *"aceitou o default"* — morta
  por *"o zero é pq cadastrei a conta com saldo zero no dia de hoje… então o zero é consciente"*. A
  regra excluía **exatamente quem deveria incluir**, com falso negativo **silencioso**;
- *"a Projeção está afirmando sem lastro em produção"* — morta por *"é o saldo real hoje"*. Com R$ 0,00
  real e ~R$ 18.000/mês de saída, *"Caixa no limite (0 dias)"* e os 4 críticos eram **verdadeiros**. A
  tela estava certa; a story é que estava errada.

Custou dois desenhos e reduziu a story de *"entra na frente de toda a Onda 2"* para **três arquivos de
leitura**. Com o epic §1.2 (a falha de escopo) e a §3.1.1 (o erro do gate), são **três em três
semanas** do mesmo padrão: uma premissa plausível sobre o estado dos dados, **não verificada com o
dono**, que quase virou construção. É a origem da **regra da instanciação obrigatória** acima.

⚠️ **Risco operacional que fica, e que nenhum sinal do produto avisa:** entre recuar a `opening_date`
de uma conta e terminar de repagar as contas legadas, `derived_balance(hoje)` semeia a Projeção com o
saldo antigo **apresentado como saldo de hoje** — runway longo demais e alerta de janela negativa
**calado**. Faça recuo e repagamento **na mesma sessão**; se partir em dias, **Projeção e Diagnóstico
não devem ser lidos no intervalo.** O sistema não distingue *"conta dormente"* de *"tudo aconteceu e
nada foi registrado"*. A ordem do mutirão também não é negociável: recuar a abertura declarando o
saldo daquele dia → estornar → repagar informando conta e data. Invertida, deixa contas estornadas e
**nenhuma repagável** (o piso de `_validate_posted_at` recusa com 422).

#### 5. O gate NÃO abre "depois da Onda 2" — corrige o que este arquivo dizia

A pré-condição, lida ao pé da letra (*"toda cobrança recebida precisa ter conta informada"*), era
**insatisfazível**: pela Invariante do Trilho uma `Charge` do trilho tem `transaction_id` e **nunca**
terá `bank_account_id` — e o trilho é o caminho normal do produto. A ratificação a reescreveu em
quatro termos, cada um com o predicado que o decide e a **onda que o zera**: **P1** baixa de Contas a
Pagar sem conta (Onda 2) · **P2** recebimento fora do trilho sem conta (Onda 2) · **P3** rendimento de
aplicação sem perna bancária (**Onda 2b-i** ✅, ver abaixo) · **P4** payout da Carteira (**Onda 3**, hoje vazio por
construção — `request_payout` só marca `withdrawn`).

**Consequência que muda a leitura do épico:** o gate abre depois da Onda 2 **apenas para um tenant
cujos únicos eventos que movem conta real sejam P1 e P2**. Quem registra rendimento de aplicação
precisava da **2b-i** — ✅ **entregue**, ver a seção dela abaixo; quando o payout virar real,
precisa da **3**. Não é escopo novo — P3 e P4 sempre foram termos da divergência.

⚠️ **O achado A-1, que teria fechado a métrica primária do épico para sempre.** A `Charge` sintética
de rendimento (`investments/service.py`, Story 5.6) nasce `paid` com `transaction_id=NULL` **e**
`bank_account_id=NULL` — caía **inteira** na população do termo P2. Para quem tem conta de
investimento (o fundador tem), o gate **nunca abriria**, e o defeito não se anunciaria como defeito:
se anunciaria como *"a pré-condição ainda não foi satisfeita, continue corrigindo lançamentos"*, para
sempre. **Dois @sm trabalhando em paralelo: a 8.15 lembrou o predicado `_not_investment_yield()`, a
8.16 esqueceu.** O predicado é **importado de `receivables/service.py`, nunca reescrito** — a guarda de
lógica ternária SQL (`coalesce(external_ref, '')`) que ele carrega é o que um reescritor perderia,
excluindo **todas** as cobranças normais em silêncio.

#### 6. O acoplamento invisível que segura a Projeção (leia antes de tocar em `projection.py`)

O recorte que impede a dupla contagem no dia agendado tira a agendada de `_window_sums` **confiando**
que o movimento já está no `saldo_inicial`. Isso só é verdade porque **`_saldo_inicial` passa
`until=today`**. Trocado por `None` ou por `SEM_CORTE`, a agendada futura passa a contar **nos dois
lugares**, em silêncio, pelo lado oposto — num arquivo que a story do recorte declara **não tocar**.
O comentário que já existia ali dizia **por que** o argumento existe, mas **não dizia o que quebra** —
e o que quebra está noutro arquivo. Hoje há um espião sobre `active_balance_total` capturando o kwarg
`until`: **é o que torna o recorte auditável, e não só correto hoje.**

Pelo mesmo motivo `active_balance_total` **manteve** o default antigo quando `derived_balance` e
`derived_balances_as_of` mudaram o significado de `until=None` para "hoje". A assimetria é
**deliberada e testada** (`test_active_balance_total_so_e_chamada_com_until_explicito`); uniformizar as
três é decisão de Onda 2b/3 e **exige revisitar esta seção junto** — não é limpeza de passagem.

#### 7. Decisões cujo motivo some no código

- **A idempotência é o índice único parcial `(tenant_id, source, origin_id) WHERE origin_id IS NOT
  NULL` — NUNCA o `dedup_hash`.** No manual, `_manual_dedup_hash` chaveia no **UUID da própria linha**,
  único por construção: **nunca deduplica nada**. Ele existe para o pipeline de importação. E
  `origin_dedup_hash = sha256(f"{source}|{origin_id}")` é **sem** `bank_account_id`, de propósito —
  trocar a conta de um lançamento é **UPDATE da mesma linha**, e com a conta no hash deixaria de ser.
  ⚠️ A justificativa escrita no AC da 8.9 para a cláusula parcial era **falsa** (`NULL` é distinto de
  `NULL` em índice único por padrão) e o mutante que a removia **sobreviveu**. A cláusula fica por
  tamanho/intenção e por não depender de um comportamento que é **configurável desde o PG15**
  (`NULLS NOT DISTINCT`).
- **`tenant_id` é a PRIMEIRA coluna do índice único** porque **índice único é global e não respeita
  RLS**: sem isso o tenant B receberia violação inexplicável causada por dado do tenant A — bug **e**
  vazamento de existência. Lição já paga na 8.2.
- **`origin_id` é `VARCHAR(64)`, não 36 nem 48.** Ele não é "o id do lançamento": é **chave de
  origem** — perna única = id; multi-perna = `f"{id}:{perna}"`. Em Postgres `VARCHAR(n)` é
  armazenamento variável (64 e 36 custam o mesmo em disco), mas errar para menos custa `ALTER COLUMN`
  **sobre tabela com dado sob `FORCE RLS`**. Só a transferência quebraria, e só em produção:
  `f"{uuid}:out"` tem 40 chars. `test_origin_id_cabe_na_coluna` varre **cada forma de chave** do
  repositório e reprova em CI, não no `ALTER`.
- **Transferência = duas pernas `:out`/`:in` pareadas por `transfer_id`.** A forma "o mesmo `origin_id`
  nas duas + índice relaxado" **destrói a idempotência onde ela mais importa**: um retry move o
  dinheiro duas vezes. E a alternativa "coluna `leg` no índice" destruiria a garantia para **todas** as
  origens em silêncio, porque `leg` seria `NULL` em toda origem de perna única.
- **`scheduled` é estado próprio, não `paid` com data futura** — rejeitado por **bug verificado**, não
  por gosto: com `paid`+futuro a conta sai dos fluxos de saída **e** o movimento não entra no saldo, e
  os R$ 5.000 agendados **somem por completo da Projeção**. A máquina de falso negativo da Onda 0
  ressuscitada, na mesma tela que a Onda 0 consertou. O estado é **derivado da data** (`scheduled ⟺
  paid_at.date() > hoje`), a API nunca aceita `status` do cliente, e **o worker não é componente da
  aritmética**: o movimento nasce com `posted_at` na data agendada e o saldo é função da data — entra
  sozinho quando o dia chega. O worker só move o `status`.
- **O estorno APAGA o movimento.** Um movimento bancário é a afirmação *"este dinheiro saiu"*;
  estornado, o sistema não afirma mais isso. Rejeitados: **contrapartida `+valor`** (inventa um crédito
  que nunca existiu, e na Onda 4 a importação acharia dois órfãos irreconciliáveis) e
  **`status='ignored'`** (é julgamento do dono, não estado de sistema — e **colide com o índice único**
  no repagamento).
- **Não existe coluna `payment_route`.** A rota é **derivada** dos dois ponteiros; um rótulo separado
  pode divergir do fato e vira a terceira fonte de verdade. Gate de AST reprova o nome em qualquer
  posição, **inclusive como kwarg**.
- **`bank` não importa `payables`/`receivables` — e a saída não é import lazy nem SQL cru.** Os dois
  seriam **evasão**, e *"evadir um gate é pior do que quebrá-lo às claras"*. A forma é **porta de saída
  registrada**: `Protocol` + DTO com `referencia_id` **opaco** (o campo não pode nem **nomear** um
  conceito do outro módulo), implementação no módulo de negócio, fiação em `app/main.py`. **O gate fica
  verde porque a dependência sumiu.**
- **Fail-closed é de BOOT, não de request.** A app **não sobe** sem o probe registrado. *"Um erro de
  fiação é condição de startup"* — e um 500 numa ação legítima do dono (lançar uma tarifa de R$ 2,90)
  é o pior lugar imaginável para descobrir que o `main.py` não ligou um `Protocol`. Precedente: a
  guarda do `JWT_SECRET` fraco. E o probe não registrado faz o relatório **recusar**, nunca devolver
  zero: **zero por ausência de medição não é zero**, e a tela diria por omissão *"nenhum termo
  pendente"* — a leitura errada que já custou uma decisão de produto neste épico.
- **`SEM_CORTE = date.max` é feio de propósito, e a feiura é a funcionalidade.** Não existe
  `incluir_futuro=True`: um booleano seria discreto, e discrição é o que não se quer num campo que
  inclui o futuro num saldo. Assim a decisão fica **visível no diff** e uma busca por `SEM_CORTE` lista
  todos os lugares que a tomaram.
- **Conta de outro tenant devolve 404, não 409** — 409 vazaria existência. Com zero contas próprias
  todo id recebe 409; com contas próprias, um id alheio recebe 404.
- **O seletor de conta e a data vivem DENTRO da mesma barra fixa do botão**, com teste de co-localização
  por ancestral comum — porque **dois PRs de fix já foram pagos** por elemento fora da área visível, e
  numa delas uma conta real foi marcada paga sem o usuário conseguir ver o checkbox. Pré-selecionar a
  conta primária **não** torna o campo opcional: o AC exige o nome da conta **no próprio botão**
  (*"Anexar e dar baixa · sai do Itaú PJ"*), porque um default invisível é na prática um campo pulado.
  Sem conta primária, **nada** é pré-selecionado e a ação fica desabilitada — **silêncio, nunca um
  palpite.**
- **Nomear um débito inocente é pior do que ficar calado.** O critério de casamento do débito suspeito
  é `|valor − divergência| <= max(R$ 50, 10%)`, não `[0,5×, 2×]` — o fator 2 casaria um débito de
  R$ 5.000 com uma divergência de R$ 2.500. **Um sinal por relatório, não por cobrança**, e sem opção
  de desligar: *"o dono que mais precisa é o que desliga"*. E **nenhuma palavra** sobre split, taxa ou
  receita da e1p no texto: recebimento fora do trilho é vazamento de receita da plataforma, mas a
  decisão é informação **neutra ao dono, nunca reportada ao Master**.
- **O nome "agendamento suspeito" foi banido por varredura de texto.** Depois que o worker promove
  `scheduled → paid`, **nada no dado distingue** *"agendei e o banco não executou"* de *"paguei no
  caixa e o banco não compensou"* — o adjetivo não sobrevive ao worker. Virou `debito_nao_confirmado`,
  e uma varredura reprova o **radical "agendad"** no motor e na tela, para a renomeação não ser
  desfeita por um *"voltei o nome antigo, ficou mais claro"* daqui a três meses.
- **A natureza do lançamento manual não é whitelist rígida** — texto curto, vocabulário sugerido,
  *"Outro (descreva)"* sempre aceito: *"o extrato está cheio de coisas que não imaginamos; recusar um
  fato bancário legítimo porque não está na lista recria a incompletude que a onda combate"*. A
  obrigatoriedade é **de UI**; a API segue aceitando `null`, senão todo movimento legado quebraria.

#### 8. O que ficou aberto

- **Dívida:** ⚠️ **`charges.bank_account_id` continua SEM o índice irmão.** `payables` tem
  `ix_payables_bank_account`; `charges` não tem, e o caminho de leitura do gate filtra por essa coluna
  a cada diagnóstico. Assimetria sem justificativa escrita — **verificada ainda aberta em 07/08**.
- **Dívida:** ⚠️ **o débito suspeito casa conta por `bank_account_name`**, e `bank_accounts` **não tem
  unicidade de `name` por tenant** (o único índice único é `(tenant_id, institution_code, branch,
  number) WHERE number <> ''`). **Duas contas "Itaú" no mesmo tenant fazem o débito de uma explicar a
  divergência da outra** — e o produto nomeia a conta errada, que é o modo de falha que o próprio
  epic diz ser *"pior do que ficar calado"*. Resolver exige `bank_account_id` em
  `CompletenessAccountInput`. **Verificada ainda aberta em 07/08** (`engine.py:480`).
- **Dívida:** **a lista de caminhos de mutação do design §3.3 ainda tem CINCO** — *baixar, trocar
  conta, trocar data, estornar, repagar*. O gate achou o sexto (**cancelar**) da pior forma: cancelar
  uma conta a pagar agendada deixava o movimento bancário **órfão**, e
  `test_cache_de_movimento_nunca_diverge_do_origin_id` **passava**, porque cobria exatamente os cinco
  enumerados. **A lista era a garantia, e a garantia estava incompleta.** O defeito está **corrigido**
  (`cancel_payable` recusa `scheduled` com 409, regressão em `test_payables.py:185`), mas **a lista
  não foi para seis**. Quem enumerar casos como prova de completude: a enumeração é o teto da
  cobertura, não a cobertura.
- **Dívida:** **`operation_nature` não entrou em `BankTransactionUpdate`** — preencher a natureza de um
  movimento legado **pela tela de edição não é possível hoje**. Verificada aberta.
- **Dívida:** ⚠️ a validação em ~360px da tela **Contas & Saldos** segue pendente (a dívida da Onda 1,
  logo acima) **e o `TotaisCard` usa `flex-wrap` puro** — exatamente o padrão que a 8.13 provou
  insuficiente sozinho. Não é só "não validada": está escrita com o padrão que dá falso verde.
- **Dívida:** `contas_sem_checkpoint` virou **nome impreciso** — passou a contar também as contas com
  checkpoint degenerado. O **texto** de todas as superfícies foi corrigido para *"não avaliada(s)"*; o
  **nome do campo de API** não. Decisão consciente: renomear campo de contrato por precisão semântica,
  com a nota já dizendo a verdade na tela, custa mais do que ganha.
- **Dívida:** o OpenAPI da rota de conferência descreve **um** dos dois motivos de `indisponivel` —
  quem ler a doc conclui que `indisponivel ⇒ saldo_banco_data === null`, e o discriminador é
  justamente o contrário.
- **Dívida:** o 🟡 do Diagnóstico diz *"sem comparação avaliável no período"* nos **dois** motivos, sem
  distingui-los. A **severidade está certa**; falta a precisão do texto, e a nota por conta na tela já
  a tem.
- **Dívida:** `"Agendado para entrar"` nasce **sem consumidor visível** (só ganha valor com recebimento
  fora do trilho com data futura), e `app.worker` **não registra o probe** de contagem dupla — hoje
  inofensivo porque nenhum caminho do worker chama `create_transaction`, com a guarda de boot como
  rede se um dia chamar.
- **Dívida:** SIG-001 (a virada de mês apagando conferência recente) segue aberto e é **vizinho do
  bloco 4** — quem mexer no bloco 4 deve lê-lo antes. Foi mantido **fora** da 8.16 de propósito: fundir
  correção de regra existente com regras novas no mesmo diff tira do gate a capacidade de julgar qual
  mudança quebrou o quê. Mesmo argumento que manteve 8.19 e 8.20 separadas.
- **Dívida:** `generated.ts` **cresceu** nesta onda (duas rotas novas, `bank_transfers`, os campos de
  agendado) e continua sem check de drift no CI.

#### 9. O que foi construído

- [x] **A Regra da Origem** (`bank/origin.py::sync_origin_movement`, migration `0064`) — **a única
  função do repositório que escreve `source ∈ SOURCES_SISTEMA`**, guardada por allowlist de call sites.
  Não commita: movimento e lançamento entram na **mesma transação**. Toda regra é escrita contra os
  **conjuntos** `SOURCES_SISTEMA`/`SOURCES_EXTERNA`, nunca contra valor solto de `source` — porque
  `source` mistura dois eixos desde a `0059` e consertar exigiria reescrever coluna sob `FORCE RLS` por
  estética. **Alimenta `saldo_sistema`, NUNCA `saldo_banco`**: a divergência cair porque o sistema
  passou a saber mais é o objetivo; cair porque um lado foi ajustado contra o outro continua proibido.
- [x] **`until=None` passa a significar hoje** em `derived_balance`/`derived_balances_as_of` —
  pré-requisito de tudo com data futura. Sem ele, um agendamento entra no "Total em contas".
- [x] **Baixa de Contas a Pagar com conta bancária obrigatória** e data editável (default no
  vencimento, por decisão do fundador: *"se estiver fazendo retroativo, é pq não deu certo no dia"*).
  409 acionável `{"acao":"cadastrar_conta"}`, com cadastro embutido que **retoma a baixa**.
- [x] **`scheduled`** — agendar sem sumir da Projeção. Cabe em `String(12)`, e é por isso que **não há
  migration**.
- [x] **Recebimento fora do trilho** (`settle_off_rail`) — o dono declara o Pix que caiu direto na
  conta dele. **Nunca** toca a Carteira, **nunca** cria `Transaction`/`PlatformEarning`. Guardado pela
  **Invariante do Trilho**: para toda `Charge` paga, **exatamente um** de `transaction_id` e
  `bank_account_id` é não-nulo. O caminho do gateway mantém `paid_at = now()` e **não é editável** —
  fato externo atestado por terceiro; editá-lo transformaria uma testemunha em opinião.
- [x] **Diagnóstico e conferência aprendem a onda** — 🟡 de recebimento fora do trilho, desambiguação
  do débito não confirmado, e até **três notas** no bloco 4, uma por termo não-zero, **cada uma
  nomeando a onda que a fecha**. Achatá-las prometeria na tela *"isso some quando você terminar o
  mutirão"* sobre um termo que não some. Zero termos ⇒ zero notas, e **é esse silêncio que sinaliza que
  o gate pode ser lido**. A nota **ANOTA, nunca SUBTRAI** (Regra 5).
- [x] **Manual curado + guarda de contagem dupla** — o formulário pergunta **para que serve**
  (`operation_nature`, coluna que já existia, zero migration); lançar à mão um débito que já tem conta
  a pagar correspondente (mesmo valor, ±3 dias) dá **409 com escolha**, `confirmar_avulso=true` para
  insistir. A janela e o valor exato são **deliberadamente os mesmos** do enriquecimento da Onda 4 —
  dois números para *"estas duas linhas são o mesmo dinheiro?"* seriam duas respostas quando o matcher
  chegar.
- [x] **Transferência entre contas próprias** (`bank_transfers`, migration `0065`) — DRE-neutra por
  construção, com snapshot campo a campo provando; **zero acoplamento com `investments`** (dois gates,
  AST e texto cru); `kind` **derivado** dos dois seletores, sem terceiro campo que possa discordar
  deles. `DELETE` apaga as duas pernas — sem ele, a única correção possível seria a contrapartida que o
  design rejeita nominalmente.

### Onda 2 (correção) — "tenho a conta e NÃO sei o saldo" (Story 8.21, PR #94, 2026-08-07)

**O defeito.** `bank_accounts.opening_balance_cents` é `NOT NULL DEFAULT 0` e o formulário
pré-preenchia `"0,00"` — então *"informei zero"* e *"não informei nada"* eram **a mesma linha**. Uma
conta cadastrada por quem não sabia o saldo virava elegível e a Projeção de Caixa afirmava runway e
alerta sobre um saldo que **ninguém informou**. `ORIGEM_INDISPONIVEL` existia em `core/money_planes.py`
desde a Onda 0 **sem gatilho nenhum**; esta story é o gatilho.

- [x] **`bank_accounts.opening_balance_is_known`** (migration `0074`) — o **ATO** de declarar, ao lado
  do **VALOR**. `false` ⇒ `opening_balance_cents` é **placeholder, não afirmação**.
  - **`opening_balance_cents` anulável foi REJEITADA** pela @architect: quebraria
    `_validate_opening_date_recuo` (Story 8.11), cujo mecanismo inteiro é *"presença é a única coisa
    que a API consegue distinguir de 'não mudou'"* — com a coluna anulável o `None` do `Update`
    passaria a significar duas coisas e a guarda morreria em silêncio. Ela também é a âncora da
    fórmula do §3.1, e `None` ali se propagaria por toda a leitura de saldo.
  - ⚠️ **Migration SEM backfill, e é por isso que é segura.** As armadilhas das `0046`/`0066`/`0067`/
    `0068`/`0069`/`0073` são todas a mesma: `UPDATE` de backfill filtrado em silêncio pela RLS, com
    **sucesso aparente**. `ADD COLUMN` é **DDL, não DML** — a RLS não o alcança. O `server_default=true`
    cobre o legado e **cai no mesmo `upgrade`**: mantido, todo `INSERT` que omitisse a coluna gravaria
    *"eu sei o saldo"* em silêncio. Mesma disciplina de `ai.complete` exigir `db`/`tenant_id`/`task`.
  - ⚠️ **O nome trip um gate estrutural, e isso foi resolvido pelo lado certo.**
    `opening_balance_is_known` contém a substring `"balance"` e faz
    `test_saldo_derivado_nao_e_coluna_no_modelo` falhar — gate que existe para impedir saldo
    MATERIALIZADO. **A exceção lá é nominal e justificada** (um booleano não pode divergir dos
    movimentos); **renomear a coluna para fugir da substring foi rejeitado**: seria deixar o teste
    ditar o vocabulário do domínio.
- [x] **BASTA UMA conta elegível desconhecida para calar a Projeção inteira** (veredito da @architect).
  Somar só as conhecidas erraria nas **duas** direções, e nada na tela diria em qual: como
  `opening_balance_cents` **pode ser negativo** (cheque especial), a parcela que falta tanto subestima
  (alerta grita sem motivo — Regra 7) quanto **superestima** (alerta CALADO quando deveria soar — a
  máquina de falso negativo que a Onda 0 desmontou, atingindo quem tem cheque especial).
  - **As duas obrigações que vêm junto**, sem as quais a escolha seria pior que a rejeitada: **(a)** o
    número continua visível e a composição continua fechando (*suprimir a afirmação, nunca o número*);
    **(b)** a supressão **NOMEIA a saída** via `CashProjection.notes`, dizendo **quais** contas faltam.
    Sem (b) o dono vê o runway sumir e não descobre o que fazer — o beco sem saída do WhatsApp item
    12(b). `notes` já existia e já era renderizado: **zero campo novo**.
  - `_ORIGENS_SEM_LASTRO` (`projection.py`) — **um conjunto, três consumidores.** As duas supressões
    comparavam `== ORIGEM_PLATAFORMA` em três pontos; acrescentar `indisponivel` repetindo a comparação
    deixaria um deles para trás algum dia, e o sintoma seria o defeito desta story sobrevivendo à
    própria correção.
- [x] **A procedência é decidida em UM lugar** — `service.origem_do_saldo_derivado(account)`. Ela
  estava escrita duas vezes no `router.py`, uma por rota que expõe saldo derivado: a **mesma conta**
  por duas portas, e divergindo uma diria `banco` e a outra `indisponivel`. **É a classe que
  `whatsapp.__init__._resolve` já pagou** (item 12 abaixo) — achado pelo `dedup-checker` no gate.
  Gate por varredura AST do router, com controle positivo.
- [x] **O formulário força a escolha nos DOIS modos** (`AccountModal`). Só o cadastro deixaria o
  caminho *"descobri o saldo depois"* sem UI — capacidade de backend sem consumidor. E o backend
  recusa (422) o PATCH que informa saldo numa conta *"não sei"* sem declarar o ato: sem isso o dono
  digita o saldo real, salva, e a Projeção continua calada **sem explicação**. Pior que não ter saída:
  é uma saída que **parece funcionar**.
- **Lição de processo que custou 4 rodadas de validação:** a story levou **três NO-GOs do @po**, todos
  da mesma família — *o artefato descrevia o backend corretamente e não verificava quem o alcança*
  (o router sobrescrevendo o default do schema; o flag sem caminho de tela; o nome da coluna vs. o
  gate). **Nenhum apareceu lendo a story; os três lendo o código ao lado dela.** O que quebrou o ciclo
  foi um **spike de 20 minutos** do @dev, que confirmou os três e ainda revelou que o bloqueio de
  numeração de migration havia caído sozinho. **Regra: quando duas validações de documento seguidas
  falham pelo mesmo motivo, a terceira não deve ser de documento.**
- **Dívida:** **aceite visual em ~360px NÃO foi feito** (a escolha é elemento novo) — mesma dívida do
  AC9 da 8.13. E: conta `is_known=false` + recuo de data pede um saldo cujo campo está escondido no
  formulário; tem saída (marcar *"sei o saldo"* revela o campo), mas a mensagem de erro pede algo que
  não está visível.

### Onda 2b-i — a perna bancária do rendimento (o termo P3 fecha)

> Spec: `docs/superpowers/specs/2026-08-07-onda-2b-i-perna-bancaria-do-rendimento-design.md` ·
> Plano: `docs/superpowers/plans/2026-08-07-onda-2b-i-perna-bancaria-do-rendimento.md`

**A Onda 2b foi PARTIDA EM DUAS, e o recorte é a decisão.** O §647 do PRD descreve cinco
entregáveis; só dois tocam o gate, e o mais arriscado do épico inteiro (o backfill de
`principal_cents` sob `FORCE RLS`) não é nenhum dos dois. **2b-i** entrega o vínculo e o movimento;
**2b-ii** fica com o principal derivado, o backfill, o 409 de edição e o extrato na tela. Manter o
backfill colado ao destravamento da métrica primária refaria o acoplamento que o épico já desfez
uma vez ao separar a 2b da Onda 2.

#### O achado que motivou o recorte, e que teria custado a onda inteira

`receivables.contar_rendimentos_sem_perna_bancaria` **não verificava se existia perna bancária** —
nenhum join, nenhum `NOT EXISTS`. Contava todo rendimento da janela. Pré-2b era inofensivo, porque
*"todos os rendimentos"* e *"os sem perna"* eram o mesmo conjunto. Ligado o movimento, eles se
separam e P3 seguiria contando o que passou a ter perna: **o gate não abriria nem depois da onda que
existe para destravá-lo**, e a nota continuaria dizendo *"este termo só fecha na Onda 2b"* sobre uma
onda já fechada. O único teste que tocava a função afirmava que ela era `callable`.

> **A regra que fica (reverberar): função cujo NOME promete um filtro tem de tê-lo, mesmo quando o
> filtro é hoje redundante.** Ela esteve certa **por coincidência de população** durante uma onda
> inteira. A coincidência não deixa rastro no código, não quebra teste ao terminar, e o dia em que
> ela termina é exatamente o dia em que a função vira defeito. É a família do §2 desta seção (o
> teste que passa e não prova nada) com um agravante: **aqui o teste correto não podia sequer ser
> escrito** no caminho de produção — o membro que o mataria era inconstruível.

#### O que foi construído

- [x] **`investment_accounts.bank_account_id`** (migration `0075`) — ligação 1:1 com a
  `bank_account` `kind='investment'`. `investment_accounts` **não** é absorvida: ela é a faceta de
  PRODUTO (rentabilidade, indexador), a `bank_account` é ONDE o dinheiro está. Índice único parcial
  com `tenant_id` na FRENTE (índice único é global e não respeita RLS — lição da 8.2). **Sem
  `UPDATE`:** `ADD COLUMN`/`CREATE INDEX` são DDL e a RLS não os alcança; a aplicação que já existia
  é vinculada pelo dono, **por ato**, na tela. Validada contra Postgres real via `rls_e2e`.
- [x] **`register_yield` sem vínculo recusa com 409 acionável** (`{"acao":"cadastrar_conta"}`,
  terceira cópia da string, sincronia por teste). **É isso que põe P3 em zero POR CONSTRUÇÃO** — o
  mesmo mecanismo pelo qual a 8.12 zerou P1. A degradação graciosa da Onda 3 (*"nada acontece, nada
  quebra"*) foi rejeitada aqui, e a diferença é **quem está na sala**: o payout é disparado pelo
  sistema, sem humano a quem perguntar; o rendimento é o dono digitando um valor agora.
- [x] **`register_yield` gera `bank_transaction` `source='yield'`** pelo mesmo
  `sync_origin_movement`, na mesma transação, nascido conciliado. **`SOURCE_YIELD` já estava em
  `SOURCES_SISTEMA` desde a `0059`** — como nenhuma regra do repo é escrita contra `source` solto,
  todas já cobriam `yield` sem uma linha de mudança. Precisa de `db.flush()` antes: o id da `Charge`
  tem default **Python-side** e sem ele o `origin_id` nasceria vazio (o defeito MNT-001).
  **A IV1 da 5.6 NÃO foi relaxada:** `bank_transactions` é o plano do BANCO,
  `Transaction`/`PlatformEarning` são o da PLATAFORMA, e continuam intocados.
- [x] **`posted_at` = data do rendimento, não o instante do registro** — que erraria sempre que o
  dono lançasse com atraso. O resíduo (competência 31/07 × crédito 01/08) é o **termo 3** da
  decomposição da divergência, que a banda de tolerância existe para absorver. **A escolha só é
  barata porque o predicado de P3 é `NOT EXISTS`:** ele pergunta *"existe perna?"*, não *"a perna
  caiu nesta janela?"*. Se a data fosse o eixo do termo, isto seria decisão de gate.
- [x] **Data futura: 422** — a decisão que `bank/transfers.py:185` exigia que a 2b tomasse **em vez
  de copiar**. A razão não é a da transferência: um rendimento que ainda não caiu não é um
  rendimento, e não teria para onde ir — não existe `scheduled` para rendimento, nem superfície,
  nem caminho de promoção (Art. IV). Comparação com `hoje_do_tenant`, nunca com `now(UTC)`.
- [x] **A nota de P3 deixou de nomear uma onda e passou a nomear a AÇÃO** (*"Vincule a aplicação à
  conta bancária dela"*). Ela fica mesmo inalcançável no caminho normal: se disparar, é linha legada
  ou defeito, e apagá-la deixaria a 2b-ii sem quem avise se os dados voltarem inconsistentes.
- [x] **A tela vincula** — seletor único para os dois modais, e no 409 o modal vincula e **reenvia o
  rendimento sem o dono redigitar valor e data**. Sem esta parte o 409 seria um beco: backend
  pedindo um vínculo que não tinha onde ser criado (a classe do item 12 do WhatsApp).

#### Três coisas que só apareceram implementando

- **O gate da allowlist do `sync_origin_movement` pegou o chamador novo, e é para isso que ele
  existe.** `investments/service.py` entrou em `_CHAMADORES_PERMITIDOS` **com a justificativa** —
  que é o que faz a revisão acontecer, e não uma linha na lista.
- **Um teste meu passou ANTES da implementação, pelo motivo errado.** `register_yield` grava
  `paid_at = now()` (o instante do registro) enquanto `posted_at` usa a competência informada: uma
  janela em julho não continha o `paid_at` de um rendimento registrado em agosto, e P3 dava `(0,0)`
  por vacuidade. Corrigido com **controle positivo** (o mesmo rendimento sem perna, que conta).
- **`date.today()` é a data LOCAL e `paid_at` é `now(UTC)`** — às 23h em UTC−3 as duas já são dias
  diferentes, e uma janela de teste de um dia só perdia o rendimento pela borda, em silêncio.

- **Dívida:** o ramo *"origem desliquidada → apaga"* de `sync_origin_movement` é **inalcançável**
  para `source='yield'` (não existe estorno nem exclusão de rendimento; o router só expõe
  `register_yield`). Está na docstring para não parecer esquecimento na 2b-ii.
- **Dívida:** **aceite visual em ~360px do campo de vínculo NÃO foi feito** — mesma dívida da 8.13
  AC9 e da 8.21. Bloqueia release, não bloqueia merge.
- **Dívida:** a 2b-ii continua com o único backfill do épico, e ele continua sendo o item de maior
  risco.


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

11. **Grupo não tinha onde existir** (achado no mesmo ciclo de uso real, logo após o item 10). Sintoma: *"mensagem de grupo não aparece o texto/imagem da conversa e nem o nome do grupo"*, e **todo grupo aparecia como "Não identificados"**. Eram três defeitos empilhados, e o terceiro é o estrutural: (a) `parse_inbound` só reconhecia `@s.whatsapp.net`, então todo `@g.us` virava `from_phone=None`; (b) sem telefone não havia `client_id` — e `client_id` era a ÚNICA identidade de conversa que existia, então TODOS os grupos colapsavam num balde só; (c) esse balde tinha `client_id: null` e a tela usava esse nulo como chave de rota, então clicar nele não abria nada (o painel voltava para "Selecione uma conversa"). **A causa raiz é que a caixa de entrada era indexada por cliente do CRM**, e grupo não é cliente.
    - **Decisão do fundador:** grupo aparece em Conversas e **NÃO vira contato do CRM** (senão o funil de vendas e o painel de inadimplência enchem de grupo), **mas é respondível** — não é só leitura.
    - Fix: **`whatsapp_chats`** (migration 0066) — a conversa como entidade própria, chaveada por `chat_jid` (o `key.remoteJid`, que é também o endereço de volta no envio). `client_id` desce de chave para **enriquecimento opcional** da conversa direta. `whatsapp_messages` ganha `chat_id` + `sender_phone`/`sender_name` (em grupo, sem o autor por mensagem o fio vira um muro de balões anônimos). O estado de leitura migra para `whatsapp_chats.last_read_at` — e isso **dissolveu por construção** a corrida de `IntegrityError` que `mark_read` precisava tratar: não há mais INSERT, só UPDATE de uma linha que já existe.
    - **Dois achados do payload real** (capturado ao vivo, v2.3.7 — o assunto do grupo NÃO vem na mensagem, só o JID; é buscado à parte em `/group/findGroupInfos` e cacheado em `title`, com `title_checked_at` limitando a 1 tentativa/6h para não consultar a rede a cada mensagem): **`key.participantAlt`** traz o telefone real de quem falou no grupo mesmo com `participant` mascarado como `@lid`; e **`key.remoteJidAlt`** traz o telefone real em conversa DIRETA que chegou como `@lid` — eram 60 mensagens em 12h caindo em "Não identificados" por não lermos esse campo. `chat_jid` é **canônico** (sempre `{telefone}@s.whatsapp.net` quando o telefone é conhecido): sem isso o mesmo contato viraria duas conversas, uma por modo de endereçamento, partindo o histórico no meio.
    - Grupo **ignora a janela de 24h** (é regra da Cloud API da Meta, que nem tem grupos — exigi-la deixaria o grupo mudo por engano, e nem template existiria para destravar) e **recusa template**.
    - `@lid` **nunca** é tratado como telefone (`_phone_from_jid` devolve `None`): parece um número e não é. Sem contato conhecido a conversa existe e abre; o rótulo diz "Contato não identificado" em vez de inventar nome.
    - **Migration validada contra Postgres REAL** (container descartável, rodando como o papel não-superusuário `e1p_app`, com dados legados semeados): backfill preservou as 7 mensagens de teste, 0 ficaram sem conversa, `last_read_at` migrou, RLS `FORCE` restaurada nas 4 tabelas e isolamento cross-tenant fail-closed conferido (sem GUC → 0 linhas). O backfill **desabilita a RLS na sua janela** — sem isso ele seria um no-op silencioso (armadilha da `0046`, que o SQLite dos testes não pega).
    - **Dívida:** `whatsapp_conversation_states` fica órfã (o estado de leitura mudou de casa); não foi dropada porque `DROP TABLE` é irreversível e vale manter um ciclo para conferência — dropar numa migration posterior.

12. **As regras da Meta seguiam valendo sob a Evolution, porque `capabilities.py` não tinha
    consumidor nenhum.** Sintoma reportado: o nó de WhatsApp do funil respondia *"Selecione um
    template de WhatsApp aprovado"* num tenant conectado por QR code — que não tem template
    nenhum e não consegue criar (a Evolution recusa templates por design). **Template aprovado e
    janela de 24h são artefatos da Cloud API da Meta**, e o módulo que já codificava exatamente
    isso (`app/core/whatsapp/capabilities.py`, `EVOLUTION.templates=False`,
    `session_window=False`) existia desde a Onda 0 com **zero call sites em produção** — só o
    próprio teste unitário. Sua docstring **afirmava** que 3 consumidores o consultavam; nenhum
    dos 3 tinha sido escrito.
    - **A lição de método:** um módulo de capacidades sem consumidor não protege ninguém — ele
      documenta uma intenção, e a docstring que descreve consumidores inexistentes *impede* que
      alguém note a lacuna (é a mesma classe de erro da **INSTANCIAÇÃO OBRIGATÓRIA** do Epic 8:
      conjunto definido por descrição, sem membro escrito, sem consumidor mecânico que proteste).
      **Regra que fica: capacidade nova nasce com o consumidor no mesmo passo**, e a lista de
      consumidores na docstring tem que ser verificável por grep.
    - **Três instâncias do mesmo defeito**, todas corrigidas aqui: (a) o nó do funil exigindo
      template (`funnels/service.py::run_node` → agora texto livre sob Evolution, com
      `{{cliente.*}}` resolvido; `engine._params` passou a carregar `config.body` até a ação, sem
      o que a jornada automática continuaria muda); (b) `is_within_session_window` aplicando a
      janela de 24h — **beco sem saída**, porque fora da janela a única saída oferecida é
      template, que ali não existe: a conversa emudeceria 24h após a última mensagem do contato;
      (c) achado durante a implementação — **os 5 pontos do domínio que resolvem vínculo
      propósito→template no ENFILEIRAMENTO** (quotes, contracts, receivables, platform,
      `on_client_moved`) não sabem por qual transporte a mensagem sai, então um tenant que usou a
      Meta e migrou pro QR mantinha os vínculos e cada notificação chamaria `send_template` →
      falha garantida + retry com backoff até expirar. Guarda posta no **ponto de entrega**
      (`process_pending`), onde o transporte é conhecido: cai em `send_text` sem perder conteúdo,
      porque `notification.message` já é o template renderizado.
    - **`_resolve` do despachante agora DERIVA de `capabilities.for_profile`** em vez de repetir
      a comparação `whatsapp_provider == "evolution"`. Se divergissem, um consumidor concluiria
      "posso mandar texto livre" enquanto o despachante entregaria pela Meta — e a falha
      apareceria no worker, longe de quem poderia relacionar as duas decisões. Gate em
      `tests/test_whatsapp_capabilities.py::test_capabilities_e_despachante_nunca_divergem`.
    - Frontend espelha o mesmo dado em `apps/web/src/lib/whatsappCapabilities.ts` (o builder lê
      `GET /settings/profile` uma vez e passa o transporte aos dois modais). Conversas **não
      precisou mudar**: o backend passou a responder `within_session_window: true` e a caixa de
      texto livre que já existia aparece sozinha.
    - **Dívida:** o espelho do TS é mantido à mão (mesma dívida geral de `shared-types`) — se
      surgir um 3º transporte, os dois arquivos precisam mudar juntos, e nada no CI reprova o
      esquecimento.

13. **"Mensagem registrada" e nada chegava: o telefone ia sem código do país.** Achado logo após
    o deploy do item 12 — o funil parou de dar 422, completou a jornada, gravou
    *"Mensagem registrada para Flavio Kato (whatsapp)"* e **nenhuma mensagem chegou**. A
    `Notification` ficou `failed` com `last_error` VAZIO (o provider devolve `"failed"` sem
    levantar, então nada preenchia o campo) e o worker logava só `400 Bad Request`.
    - **Causa:** o contato estava gravado como `43984074017` — o que o dono digitou, sem o `55`.
      A sondagem de `/chat/whatsappNumbers` em produção fechou o caso: `43984074017` →
      `exists:false`; `5543984074017` → `exists:true`. **A forma correta JÁ existia no banco**
      (`clients.phone_key`, calculado por `normalize_br` na PR #76) — o caminho de envio é que
      usava `clients.phone`, o cru.
    - **Por que a resposta no inbox sempre funcionou e isto não:** contato criado pelo webhook
      nasce com o telefone que veio do WhatsApp, já completo. Contato digitado/importado, não.
    - **Fix na FRONTEIRA (`whatsapp.__init__._addressable`), não em cada call site:** são **seis**
      caminhos que resolvem destinatário de campo de telefone cru (funil, alerta pra equipe,
      convite de funcionário, orçamento, cobrança, contrato) e só `Client` tem gêmeo
      normalizado — consertar um por um deixaria quatro quebrados. O despachante é por onde todo
      envio passa (mesma razão de `capabilities` viver lá). O que está GUARDADO não muda:
      `clients.phone` segue sendo a evidência do que a pessoa digitou.
    - **Nem todo `to` é telefone** e reescrever os outros trocaria falha visível por entrega no
      lugar errado: grupo é JID `@g.us`, não identificado é `@lid`, `_owner_recipient` cai em
      e-mail e o funil cai no NOME do contato. Guarda explícita para `@`; o resto sai intacto
      porque `normalize_br` devolve `None` fora do formato BR.
    - ⚠️ **Suposição BR-only, decidida pelo fundador** (coerente com CPF/CNPJ, boleto, Pix): um
      celular estrangeiro de 10-11 dígitos É reescrito como brasileiro e a mensagem iria para
      outra pessoa — pior que falhar. Por isso **toda reescrita é logada em INFO**: o caso
      estrangeiro precisa aparecer. Se um dia houver contato internacional, este é o ponto.
    - **[CORRIGIDO]** `crm.update_client` fazia `setattr` genérico e **não recalculava
      `phone_key`** — editar o telefone de um contato deixava a chave velha. Não afetava o envio
      (a fronteira normaliza), mas quebrava a deduplicação: o efeito não aparece na tela de
      edição e sim no PRÓXIMO lead, como card duplicado. `phone_key` é derivado e não está no
      `ClientUpdate` (nem deve: derivado não é campo de entrada), então o laço genérico nunca o
      alcançava. Apagar o telefone agora apaga a chave junto — chave órfã casaria um lead futuro
      com um contato que já não tem aquele número. **Verificado em produção antes de corrigir:
      55 contatos, 0 com chave divergente** — nenhum backfill necessário. ⚠️ A primeira sondagem
      devolveu `contatos=0` e quase virou um "está tudo limpo" falso: `clients` tem RLS e
      `SessionLocal` sem tenant é fail-closed. **Auditoria de dados em tabela com RLS precisa do
      papel que faz bypass (`e1p_root`), senão a consulta não vê linha nenhuma e o silêncio
      parece aprovação.**
    - **Lacuna de diagnóstico fechada junto:** `providers/evolution.py` chamava
      `raise_for_status()` e logava só o código — o CORPO da resposta da Evolution, que já
      explicava o erro, era descartado. Investigar exigiu sondar a API à mão em produção. Agora
      `send_text`/`send_media` logam a resposta (truncada em 400 chars). **Regra: ao integrar
      terceiro, o corpo do erro dele faz parte do log — o status sozinho não diagnostica nada.**

**⚠️ `migrations/env.py` silenciava o logging de TODA a aplicação** (achado no mesmo ciclo, por um
teste que passava sozinho e falhava na suíte inteira). `fileConfig()` tem
`disable_existing_loggers=True` por PADRÃO: ele marca `disabled=True` em todo logger já
existente e não nomeado no `alembic.ini` — `e1p.whatsapp`, `e1p.notifications`, `e1p.worker`.
Depois disso `logger.info`/`logger.exception` viram no-op silencioso pelo resto do processo.
Produção escapa **por acidente de topologia** (o compose roda `sh -c "alembic upgrade head &&
uvicorn ..."`, processos separados); dentro do pytest, um único teste que aplica migrations
silencia os testes seguintes. Corrigido com `disable_existing_loggers=False`. É a mesma família
do bug já registrado abaixo ("logs que somem" por falta de `basicConfig`) — **quando um log
sumir, verifique também quem chamou `fileConfig`/`dictConfig` antes**, não só handler ausente.

14. **A mensagem saiu, chegou no celular e mesmo assim não apareceu em Conversas.** Achado
    testando a #79 em campo. Duas causas independentes, e a segunda é estrutural:
    - **O webhook só assinava `MESSAGES_UPSERT`**, que é o que CHEGA (mensagem do contato e a
      que o dono digita no próprio celular, espelhada pelo Baileys). O que sai pela API da
      Evolution vem em **`SEND_MESSAGE`** — evento diferente. Sem ele, tudo que o produto dispara
      sozinho (funil, cobrança, contrato) era entregue de verdade e **não ficava registrado na
      conversa**: o fio mostrava só um lado. Nomes conferidos por `grep` no dist da imagem que
      roda em produção, não na documentação. Duplicar não é risco: `ingest_webhook_payload` é
      idempotente por `wa_message_id`.
    - **O contato do funil não era o contato da conversa.** Seis cards "Flavio Kato" com o mesmo
      `phone_key`: o funil inscreveu `8a75cf66` (`source=api`, zero conversas) e a conversa real
      estava em `4804f5c5` (`source=whatsapp`). `get_timeline` ancora os avisos automáticos em
      `chat.client_id` — cards diferentes, metade da história em cada.
    - **`crm/merge.py`** (+ `app.scripts.merge_duplicate_clients`, dry-run por padrão) fecha a
      dívida que a PR #76 deixou aberta. Descobre as tabelas com `client_id` pelo REGISTRY, não
      por lista escrita à mão (mesmo motivo da purga dinâmica de tenant: lista esquece o módulo
      seguinte, e esquecer aqui deixa cobrança apontando para card apagado). Sobrevivente = o
      mais antigo, **o mesmo critério de `_find_existing`** — se divergisse, `absorb_lead`
      escolheria um card e a mescla outro, e o próximo lead recriaria a divisão.
    - ⚠️ **O guarda que impede a mescla errada:** agrupa por telefone **E nome**. `phone_key` não
      é único de propósito (marido e mulher compartilham telefone) — agrupar só por telefone
      juntaria duas PESSOAS num card, que é pior que o duplicado.
    - **O 9º dígito era a segunda forma de o histórico se partir:** o JID real do contato pode
      não ter o 9 (`554384074017@s.whatsapp.net`, conta pré-2016) enquanto tudo que enviamos
      passa por `normalize_br`, que o acrescenta. `_get_or_create_chat` ganhou busca secundária
      por telefone normalizado, só no caminho de miss — mesma classe que o `chat_jid` canônico já
      resolvera para `@lid` × `@s.whatsapp.net`.
    - **UX:** "Descrição" do nó virou "Anotação (só no desenho)". Duas caixas multilinha
      conviviam na mesma tela e só uma era enviada; o fundador escreveu na errada um texto que
      parecia mensagem e esperou que fosse entregue. Nada na tela dizia o contrário.
    - **Operacional:** mudar a config do webhook numa instância JÁ conectada exige reaplicar o
      `/webhook/set` **e reiniciar o container `evolution`** (armadilha já registrada abaixo) —
      o processo em memória mantém a config carregada na conexão.

**Duas armadilhas operacionais da VPS** (não são bug de código, são do processo de deploy):
- Depois de mudar a config do webhook via `/webhook/set` numa instância **já conectada**, a mudança pode não valer pro processo em memória (cache do canal Baileys carregado na conexão) — precisou **reiniciar o container `evolution`** (não só recriar) pra pegar a config nova. Sessões reconectam sozinhas (credenciais persistidas no Postgres/Redis), sem precisar de novo QR.
- `docker compose up -d --build <serviço>` só reconstrói o serviço **nomeado**. Rebuildar só `api` depois de um PR que também mudou frontend deixa o `web` com o build antigo, **em silêncio** (sem erro, só o comportamento antigo persistindo). Depois de qualquer merge, checar QUAIS serviços mudaram no diff antes de escolher o que rebuildar — ou rebuildar todos (`up -d --build` sem nome, como o `reference_e1p_prod_deploy` já recomendava).

**Estado atual:** conectado e funcionando ponta-a-ponta pro tenant `70c1f435-a21e-4148-a8c6-32a7e346a818` (flaviokato76@gmail.com) — QR, texto recebido, mídia recebida (imagem com miniatura inline), resposta de texto enviada, tudo validado com conversas reais em produção.

## CRM: a jornada única do contato (um card por pessoa)

> Spec: `docs/superpowers/specs/2026-08-04-crm-jornada-unica-do-contato-design.md` ·
> Plano: `docs/superpowers/plans/2026-08-04-crm-jornada-unica-do-contato.md`

O mesmo contato virava vários cards no Kanban (quatro "Flavio Kato" na tela do fundador):
`pages/service.py::public_submit` e `integrations/service.py::capture_lead` chamavam
`create_client` incondicionalmente. O WhatsApp já deduplicava — por telefone cru —, então o
comportamento era incoerente por porta de entrada.

- [x] **Porta única `crm_service.absorb_lead`** — as três portas (página pública, API de
  integração, WhatsApp) convergem nela. Identidade: **telefone normalizado primeiro, e-mail em
  segundo**. Quem já existe é COMPLEMENTADO (campos vazios preenchidos, nunca sobrescritos) e
  ganha um `lead_return` com a data e o texto daquele envio. `notes` do dono não é tocado no
  retorno — era exatamente o que apagava o que ele tinha escrito.
- [x] **`core/phone.normalize_br` + `clients.phone_key`** (migration 0067) — `phone` guarda o
  que a pessoa digitou, `phone_key` a forma comparável. **A regra do 9º dígito por faixa da
  Anatel** (local de 8 dígitos começando em 6–9 é celular e ganha o 9; 2–5 é fixo e não ganha)
  é o que impede o fixo `11 3333-4444` de colidir com o celular `11 93333-4444` — a alternativa
  "compara os últimos 8 dígitos" juntaria duas pessoas num card só.
- [x] **`phone_key` NÃO é único, de propósito** — marido e mulher compartilham telefone, e os
  duplicados legados (não mesclados, decisão do fundador) compartilham chave depois do
  backfill. `absorb_lead` desempata pelo **mais antigo** (`created_at ASC, id`); sem isso o
  próximo retorno cairia num card imprevisível e a história se partiria. ⚠️ Quando o
  `created_at` EMPATA (mesma transação no Postgres, mesmo segundo no SQLite) "o mais antigo"
  deixa de ser um fato observável e a garantia entregue é só **estabilidade** — a mesma
  escolha em toda chamada, via `id` como segundo critério. O teste que cobria isso passava por
  sorte até ser corrigido; ver `test_multiplos_candidatos_*` em `tests/test_lead_absorb.py`.
- [x] **Reabertura** — retorno em coluna terminal (`is_won` **ou** `is_lost`) move o card para
  a primeira coluna ativa e grava `reopened`. Coluna do meio **não** se move (puxar de volta
  apagaria trabalho em andamento). Ganho reabre porque lead recorrente querendo comprar de
  novo é oportunidade nova (decisão do fundador).
- [x] **`client_events`** — a linha do tempo NARRATIVA (`lead_created`, `lead_return`,
  `stage_move`, `reopened`, `note`, `funnel`). **Dinheiro não entra aqui:** orçamento, cobrança
  e pagamento continuam sendo lidos de `quotes`/`charges` por `crm/timeline.py`. Copiar
  `amount_cents` criaria uma segunda versão da verdade sobre dinheiro — a forma exata do bug
  que a Onda 0 do Epic 8 desfez. Ler da origem também deu o histórico financeiro
  **retroativo** de graça. `title`/`body` são texto CONGELADO (renomear a coluna do Kanban não
  reescreve o passado), no princípio do `raw_description` de `bank_transactions`.
  - ⚠️ **`client_events` NÃO EXISTE MAIS** (migration 0069, 2026-08-06): foi absorvida por
    `facts` e dropada. Tudo o que este item descreve continua valendo — mudou a tabela, não
    a regra. `crm/timeline.py` lê de `facts`. Ver §Vima abaixo.
- [x] **`ClientEvent.created_at` tem default do lado do PYTHON**, sobrescrevendo o
  `server_default=func.now()` do `TimestampMixin`. No Postgres `now()` é o timestamp da
  TRANSAÇÃO: `lead_return` e `reopened`, gravados no mesmo commit por `absorb_lead`, sairiam
  com instante idêntico e o desempate cairia no uuid — a timeline mostraria "Reaberto" acima
  de "Voltou pelo site", invertendo a causalidade na tela. **Regra que fica: coluna de tempo
  usada para ORDENAR eventos da mesma transação não pode vir de `func.now()`.**
- [x] **Reinscrição no funil** — `crm.client.returned` reinscreve no funil de entrada, com
  guarda de jornada `running`/`waiting` em `automation.py` (não dentro de `engine.enroll`:
  inscrição manual pela tela continua fazendo o que o usuário mandar).
- [x] **Superfícies** — `<ClientTimeline>` na ficha 360° (primeira `<Section>`) e como painel
  direito de Conversas (**gaveta sobreposta abaixo de `lg`**, pela lição do PR #56). Card do
  Kanban mostra "última interação", calculada por **duas consultas agrupadas** no endpoint do
  board — nunca uma coluna `last_interaction_at`, que seria valor derivado guardado.
- [x] **A coluna do Kanban é uma FILA por ordem de entrada na etapa** (`clients.stage_entered_at`,
  migration 0068). Antes ordenava por `Client.name`, e como a maioria dos leads entra pelo
  WhatsApp sem nome resolvido o "nome" é o telefone — a Entrada aparecia em ordem numérica de
  DDI. Agora o mais antigo fica no topo e quem entra vai para o fim, para o dono atender por
  ordem de chegada. **É coluna e não derivação de `client_events`** (ao contrário de
  `last_interaction_at`, logo acima) porque o log não registra troca de etapa de forma
  completa: `move_client` grava `stage_move`, a reabertura do `absorb_lead` grava `reopened`,
  e **`archive_stage` remaneja em massa sem evento nenhum** — não é derivado materializado, é
  fato primário que não tinha onde morar. O preço da coluna é o gate AST
  (`tests/test_crm_stage_order_gate.py`): um quarto caminho de escrita que esquecesse o
  carimbo não quebraria teste nenhum, a fila só passaria a mentir. **`archive_stage` preserva
  a antiguidade de propósito** (allowlist do gate): arquivar é ato administrativo do dono, e
  recarimbar jogaria a coluna inteira, em bloco, para o fim da fila de destino.
  - ⚠️ **Backfill precisa abrir a RLS de toda tabela que a consulta toca, não só do alvo.** A
    primeira versão da 0068 desabilitava a RLS só de `clients` (alvo do `UPDATE`) e deixava
    `client_events` (fonte da subconsulta) protegida. A RLS filtra **SELECT** também: a
    subconsulta devolvia `NULL` para todos, o `COALESCE` caía no `created_at` e o backfill
    **completava com sucesso aparente**, tendo perdido justamente a informação de
    movimentação que existe para recuperar. É pior que a armadilha conhecida do "zero linhas
    afetadas" (`0046`/`0066`/`0067`), porque a contagem de linhas fica **certa** e só o valor
    é que está errado — nada na saída do deploy denuncia. Achado por
    `tests/test_migration_0068_stage_order_rls.py` no primeiro uso, e provado por mutação.
- **Grupo de WhatsApp não tem histórico de CRM** — `client_id` é nulo e o painel diz isso em
  texto, mantendo a decisão de 2026-08-04 de que grupo não vira contato.

**Armadilha de JS que custou uma depuração e vale para qualquer setter de estado:** o
`ClientTimeline` derrubava a **página inteira** de Conversas quando o endpoint respondia fora
do formato. A causa não era `undefined`: com `data = []`, `data.entries` é
`Array.prototype.entries` — uma **função** —, então `data?.entries ?? []` deixava passar, e um
setter do React que recebe função a trata como updater e a **executa**. O guard correto é
`Array.isArray`. Componente de painel lateral também nunca deve poder derrubar quem o hospeda:
`load` degrada para aviso em vez de estourar.

**Dívida:** os cards duplicados que já existiam **não foram mesclados** (decisão do fundador:
a correção vale daqui para frente) — quem for mesclá-los depois precisa juntar `facts`
(ex-`client_events`), `charges`, `quotes`, `contracts` e `whatsapp_chats` do card absorvido, e não só apagar a linha.
Não há ferramenta de mescla na tela. Também não há "ligar conversa não identificada a um
contato" nem marcação de histórico como lido. **Validação manual em ~360px do painel de
Conversas ainda não foi feita** — bloqueia release, não bloqueia merge.

## Vima: o Registro de Fatos e o briefing (PRs #85 e #90, 2026-08-06/07)

> Spec: `docs/superpowers/specs/2026-08-06-vima-registro-de-fatos-e-briefing-design.md` ·
> Plano: `docs/superpowers/plans/2026-08-06-vima-registro-de-fatos-e-briefing.md`

`core/events.py` é in-process e síncrono, e nada era persistido — nenhuma consulta respondia
"o que aconteceu desde ontem à noite", então o dono abria cinco telas e montava o quadro na
cabeça. **`facts` é a memória narrativa do negócio inteiro**, e o briefing é a leitura dela.

- [x] **`core/facts.py` + migration 0069** — tabela `facts` (RLS), taxonomia
  `<módulo>.<entidade>.<verbo>`. **Absorveu `client_events`, que foi DROPADA** — se você
  procurar aquela tabela, é esta. `crm/timeline.py` lê daqui.
  - ⚠️ **Duas invariantes viraram guarda mecânica em `facts.record`**, não disciplina: (1) o
    `kind` precisa começar com o `module` (senão trinta módulos produzem `payment_received` e
    `payment.received` convivendo em seis meses); (2) o `title` **não pode conter dinheiro** —
    o valor é lido de `charges`/`payables`/`quotes` na composição, nunca copiado. Violar
    qualquer uma levanta `FactError` e estoura a transação de propósito.
  - **`module` é o vocabulário de `User.allowed_modules`**, NÃO o nome da pasta: `quotes` e
    `pages` emitem sob `comercial`. É o eixo de permissão do briefing.
  - `occurred_at` (quando aconteceu) é distinto de `created_at` (quando gravamos). A janela do
    briefing usa o primeiro.
- [x] **Oito módulos emitem** — `crm` · `whatsapp_inbox` · `receivables` · `payables` ·
  `agenda` · `quotes` · `pages` · `funnels`. Onde há vários caminhos para o mesmo
  acontecimento, um helper concentra a emissão (`_registra_recebimento`, `_marca_falha`):
  espalhar `facts.record` deixaria mudo o quinto caminho que alguém acrescentar depois, **sem
  quebrar teste nenhum**.
  - Das quatro formas de marcar cobrança paga, `update_payment` **não** emite (corrigir a data
    de uma baixa não é receber de novo), e liquidação `scheduled` também não — dinheiro com
    data futura ainda não entrou, e anunciá-lo no briefing seria mentira.
- [x] **`GET /vima/briefing`** (+ `POST /vima/briefing/{id}/read`), migration 0070. Idempotente
  por `(tenant, usuário, dia)`: F5 relê o gravado em vez de pagar narração nova, e o dono
  reencontra de tarde as mesmas palavras da manhã.
  - **A IA só NARRA.** Fato, Ausência e Tendência são determinísticos; o compositor decide *o
    que* entra e em que ordem, a Claude decide só *como* dizer. Inferência ("há oportunidade de
    vender para 3 clientes semelhantes") ficou para o V4 por assimetria de credibilidade: fato
    errado é bug, inferência errada ensina o dono a não confiar no briefing.
  - **Sem `ANTHROPIC_API_KEY` o briefing sai íntegro** por template — e nesse caso **não grava
    rastro de IA**, porque não houve IA. Mesmo padrão de `financial_intelligence/ai_narrator.py`.
  - **Ausência é o que faz funcionar no dia 1:** ela lê estado em aberto + relógio, não o log,
    então não depende de backfill (e **não houve backfill** — os fatos valem da implantação em
    diante). Cinco famílias: prazo estourado, dinheiro com data, ninguém respondeu, contato
    sumido, card parado, topo seco. Limiares injetáveis porque o V2 (DNA da Empresa) vai
    substituí-los.
  - **A regra do silêncio:** ausência é reportada ao CRUZAR o limiar, não enquanto permanece
    cruzada — só volta quando os dias dobram. Sem isso o briefing vira papel de parede em duas
    semanas e o dono lê por cima, inclusive no dia em que aparece a quinta pendência. É a Regra
    7 do Epic 8 ("dentro da banda: verde e SILÊNCIO") em outro domínio.
  - **`vazio` significa "nada ACONTECEU", não "nenhuma linha".** Um tenant recém-criado sempre
    tem pendência e tendência (topo sem lead, o 🟡 de completude do Epic 8), então um flag que
    olhasse `linhas` nunca seria verdadeiro.
  - **A agregação tem como eixo a FRASE repetida** (`kind` + `title`), não o `kind`: quarenta
    vezes a mesma sentença é uma notícia, cinquenta notas diferentes são cinquenta
    acontecimentos, e fundi-las por `kind` seria omitir, não resumir.
  - **O filtro de permissão decide quais REGRAS RODAM, não quais resultados aparecem** — para
    um funcionário só de CRM a regra financeira não é executada, não é calculada e escondida.
    Elimina a classe inteira de bug em que um dado proibido vaza porque alguém esqueceu o
    filtro na saída. A decisão é a MESMA de `require_module` (owner vê tudo; lista vazia vê
    tudo) — divergir daria dois significados a `allowed_modules`.
  - Gate em `tests/test_fuso_do_tenant.py`: varredura AST sobre `app/modules/vima/` separando
    carimbar um INSTANTE (legítimo) de derivar QUE DIA É HOJE (regressão). `absences`,
    `composer` e `permissions` são puros e não podem ler o relógio nem para instante.
- **Dívida:** `occurred_at` das mensagens de WhatsApp cai no default em vez do `messageTimestamp`
  real (`InboundMessage` não carrega o campo) — janela de erro de segundos na virada do dia;
  expurgo dos sujeitos polimórficos (LGPD) não tem rotina, só `client_id` cascateia;
  `comercial.topo.sem_lead` é a única Ausência que lê o log, então enquanto o registro for novo
  ela dispara por falta de histórico e não por falta de lead; o anonimizador não mascara nomes
  apesar da docstring dizer que sim (pré-existente, o briefing herda).

### Onda 4 — as superfícies (PR #90, 2026-08-07)

O dono passou a **ver o briefing na tela** e a **recebê-lo no WhatsApp**, nos dois transportes.

- [x] **Preferência por USUÁRIO** (migration 0072: `users.briefing_whatsapp_enabled`,
  `users.briefing_hour`; rotas `GET/PATCH /auth/me/preferences`). Mora em `users`, e **não** em
  `TenantProfile`, porque dois usuários do mesmo tenant têm telefones e horários diferentes — no
  perfil da empresa um sobrescreveria o outro. É também o que permite editá-la **sem o módulo
  `settings`**: um sub-usuário sem ele precisa poder ligar o próprio WhatsApp.
- [x] **A tela é porta de entrada UMA VEZ POR DIA, não a cada login.** Mecanismo: `read_at`.
  `EntradaDoDia` guarda o dia decidido em `localStorage` **no fuso do tenant** — poupa uma ida ao
  servidor por visita e, principalmente, **quebra o laço** de quem toca "Ir para o painel" antes
  de a marcação de leitura chegar. A autoridade continua sendo o `read_at` do servidor. Roda em
  `ProtectedBareLayout` (sem shell), desenhada para 360px.
- [x] **Job no horário de cada usuário** (`vima/scheduler.tick`, etapa 6 do sweep). O relógio é
  INJETADO e a comparação é com a hora LOCAL do tenant: às 07:05 UTC ainda são 04:05 em São
  Paulo, e comparar em UTC entregaria o briefing das 7h às 4 da manhã, todo dia. Assinatura **por
  tenant** (e não `tick(db_factory)`): o worker já itera tenants com isolamento de falha por
  etapa. A entrega só sai quando o tick GEROU o briefing — é o que impede a mesma mensagem a cada
  passada do sweep até a meia-noite, sem coluna nova.
- [x] **Dia sem novidade: a tela diz que está tranquilo, o WhatsApp NÃO sai.** Um "bom dia, nada
  aconteceu" diário é a forma mais rápida de ser silenciado — e canal silenciado não entrega o
  dia em que importa.
- [x] **Evolution em um passo, Meta em dois.** `capabilities.briefing_needs_optin` — e **o
  consumidor nasceu no mesmo passo** (`scheduler._entregar_no_whatsapp`), pela lição do item 12
  acima. Meta: parâmetro de template da Cloud API **não aceita quebra de linha** e às 7h o dono
  está sempre fora da janela de 24h, então sai um template curto **com botão**, o toque abre a
  janela e o texto inteiro vai depois, livre.
- ⚠️ **`send_template` passou a enviar o COMPONENTE de botão.** Sem ele, a Meta devolve no toque o
  **rótulo que o tenant escreveu no console dela** (texto livre: "Ver resumo", "Bora", "Sim") — e
  não haveria constante para casar do lado de cá. O payload é derivado do `purpose` em
  `process_pending`, sem coluna nova. Formato do webhook **conferido contra a documentação da
  Meta**, não suposto (`type:"button"` + `button:{payload,text}`; e `interactive.button_reply`).
- ⚠️ **O reconhecimento do toque fica DEPOIS do registro da mensagem e FORA do bloco de `facts`.**
  Aquele bloco é pulado quando a mensagem vem do telefone do time (`_e_telefone_da_equipe`), e o
  toque vem SEMPRE de lá — dentro dele, o opt-in seria descartado junto e o briefing nunca sairia.
  A guarda vale nos dois sentidos: o dono não vira lead do próprio funil, e um estranho que repita
  o payload não destrava briefing nenhum.
- **Dependência EXTERNA, fora do repositório:** o template com botão precisa de **aprovação da
  Meta**. Enquanto não houver, o tenant Meta fica sem briefing por WhatsApp — e a UI de
  preferências **diz por quê** em vez de oferecer um switch que liga e não entrega nada
  (`vima/delivery.avaliar`, o mesmo veredito que o scheduler usa; divergirem faria a tela dizer
  "ligado" e o job não mandar nada).
- **Dívida:** **validação manual em ~360px da tela do briefing ainda não foi feita** — bloqueia
  release, não bloqueia merge; quem gera o briefing abrindo o app antes do próprio horário não
  recebe o WhatsApp daquele dia (a tela já marcou como lido — troca deliberada, ver a docstring
  de `scheduler.tick`).

## Contabilidade de IA e roteamento de modelo por tarefa (PR #87, 2026-08-06)

O produto já gastava IA em produção e **não sabia quanto, nem por quem**: seis módulos chamavam
`ai.complete` e cinco descartavam os tokens que a Anthropic devolvia. A conta chegava pela fatura.

- [x] **Ledger `ai_usage`** (migration 0071, RLS `FORCE`) — tenant, usuário, tarefa, **o modelo
  que realmente rodou** (não o configurado) e quatro contadores de token. Cache tem colunas
  próprias porque tem **preço próprio** (leitura ~0,1× do input, escrita ~1,25×): achatá-lo em
  `input_tokens` daria conta errada.
- [x] **`db`, `tenant_id` e `task` são OBRIGATÓRIOS em `ai.complete`** — é o que torna
  impossível chamar a IA sem contabilizar. Esquecer vira `TypeError` na hora, não uma linha
  faltando na conta seis meses depois. Mesma disciplina de `payables.is_overdue`, que exige
  `today` pela mesma razão. Tudo keyword-only (`db` inclusive), ao contrário de
  `facts.record(db, *, ...)`: vários testes de narrador mockam `ai.complete` com `lambda **kw`.
- ⚠️ **A regra de gravação do ledger é o OPOSTO da de `facts.record`** — quem ler por analogia
  vai concluir errado. `facts` falha junto com a transação de propósito. Aqui não: quando o
  ledger grava, a chamada à Anthropic **já aconteceu e já custou dinheiro**; derrubar a
  transação perderia o documento que o usuário esperou 40 segundos para receber, e o gasto
  teria ocorrido do mesmo jeito. É best-effort com `logger.exception`.
  - **E `try/except` sozinho NÃO entrega essa promessa.** Um `flush()` que falha deixa a
    `Session` em rollback pendente: o `except` engole a exceção e o **commit do CHAMADOR** morre
    depois, longe dali, com mensagem que não menciona IA. `begin_nested()` (SAVEPOINT) delimita
    a falha. Provado por mutação — sem ele, o teste quebra com `PendingRollbackError` apontando
    para `facts.module`. **Se mexer nessa função, mantenha o savepoint.**
- [x] **`MODELO_POR_TAREFA` substituiu o `anthropic_model` global** (`ANTHROPIC_MODEL` saiu do
  `.env`). O critério é o **custo do erro**, não o tamanho do texto: `claude-haiku-4-5` onde a
  IA só reescreve o que um motor determinístico calculou (`vima.briefing`,
  `financeiro.diagnostico`, `receivables.cobranca`); `claude-sonnet-5` onde ela redige
  (`quotes.escopo`, `funnels.compose`, `marketing.carrossel`); `claude-opus-5` onde alucinar tem
  consequência jurídica (`juridico.documento`).
  - **Tarefa desconhecida cai no default, e o default é o modelo mais CAPAZ, não o mais barato**
    — roteada por engano para Haiku degradaria em silêncio; para Opus, só custa mais, e o
    excedente aparece no ledger.
  - `claude-opus-5` custa **o mesmo** que o `claude-opus-4-8` que estava global ($5/$25 por
    Mtok): foi ganho de capacidade sem centavo a mais.
  - Gate `test_toda_tarefa_roteada_usa_um_modelo_conhecido`: um typo num ID viraria 404 só em
    produção, na primeira chamada real daquela tarefa.
- **Escopo:** só MEDIR. Sem cobrança, tela ou teto de gasto — medir é reversível, decisão de
  preço não é, e ela não foi tomada. **Sem backfill:** o consumo passado não foi guardado por
  ninguém e não tem como ser reconstruído. **Dívida:** `LegalDocument.input_tokens` continua
  guardando tokens na linha do documento, agora em paralelo ao ledger (não foi removido).

## 6.0 Correções importantes
- **[CORRIGIDO 2026-08-05] O sistema inteiro passou a viver no fuso do tenant (era UTC).** O sintoma que o fundador viu foi a linha do tempo do Funil exibindo `Aguardando até 2026-08-05T11:11:32.812731+00:00` — formato de máquina e 3h adiantado. A investigação achou **três** defeitos com a mesma raiz: existia infra de fuso (`core/tz.py` + `tenant.timezone`, migration 0044) mas só 3 módulos a consumiam.
  1. **Texto para humano com UTC cru.** `funnels/engine.py` interpolava `resume_at.isoformat()` na mensagem; `contracts/service.py` montava a variável `{{DATA}}` com `datetime.now(UTC)` — um contrato criado às 22h saía datado do dia seguinte, e essa é a data que vale juridicamente.
  2. **"Hoje" ancorado em UTC em 21 pontos** (`payables`, `receivables`, `bank`, `projection`, `wallet`, `quotes`, `products`, `cockpit`). Das 21h à meia-noite em UTC−3 o "hoje" do servidor já era amanhã: vencimento, atraso, projeção de caixa e saldo deslizavam um dia **toda noite**.
  3. **Frontend sem fuso e sem helper.** ~25 telas chamavam `toLocale*` sem `timeZone`, formatando no fuso do NAVEGADOR — certo por acidente num PC brasileiro, "Greenwich" em qualquer máquina em UTC. E o Cockpit pedia `?day=` com `toISOString()`, ou seja, o dia UTC.

  **Como ficou (reverberar):**
  - `core/tz.py` ganhou `local_date`, `tenant_today(tz, *, now=)`, `format_datetime_br` e `format_date_br` — **puras, com relógio injetável**, mesma disciplina de `core/scheduling.py`.
  - `settings/service.py` ganhou os resolvedores: `tenant_timezone(db)` (sessão RLS), `timezone_of(db, tenant_id)` (rotas de auth, que rodam em sessão crua) e **`hoje_do_tenant(db)` — a única âncora de "hoje" do sistema**. Cada `_today()` de módulo delega para ela. ⚠️ **`timezone_of` não funcionava de verdade até o PR #91** — ver a correção logo abaixo.
  - `is_overdue` (payables **e** receivables) passou a exigir `today` como parâmetro **obrigatório**. Um default que lê o relógio é exatamente por onde o fuso errado volta.
  - `TenantOut` carrega `timezone`: a sessão entrega o fuso ao frontend. **Não** use `GET /settings/profile` para isso — aquela rota exige o módulo `settings`, que nem todo usuário tem.
  - Frontend: `lib/datetime.ts` é a ÚNICA porta de formatação, e separa as duas espécies de data — **instante** (`formatDateTime`/`formatDate`/`formatTime`, convertem de fuso) e **data de calendário** (`formatDay`, puramente textual, nunca constrói `Date`). `useFuso()` (em `store/auth.tsx`) dá o fuso e, ao contrário de `useAuth`, **não lança** fora do provider: fuso é exibição, e derrubar a tela por causa dele seria uma troca ruim.
  - **Lição (reverberar): `isoformat()` em texto que um humano lê é bug, não estilo.** Para persistir/trafegar, ISO em UTC; para exibir, a borda converte. E "hoje" **nunca** é `datetime.now(UTC).date()` — é `hoje_do_tenant(db)`.
  - Gates: `tests/test_fuso_do_tenant.py` (backend), `src/lib/datetime.test.ts` + o teste do `?day=` em `CockpitPage.test.tsx` (frontend).
- **[CORRIGIDO 2026-08-07, PR #91] O fuso da sessão era SEMPRE o padrão — a correção acima estava pela metade.** `/auth/login`, `/auth/register`, `/auth/me` e `/auth/change-password` rodam em sessão **crua** (`get_db`, sem a GUC de tenant) e `timezone_of` lia `tenant_profiles`, que tem `FORCE ROW LEVEL SECURITY` desde a 0022. **A policy filtra o SELECT inteiro:** o `WHERE tenant_id = ...` explícito não ajudava, porque o problema nunca foi *qual* linha trazer e sim *conseguir enxergar alguma*. Todo tenant recebia `America/Sao_Paulo`, e o `useFuso()` do frontend inteiro sai desse valor. É a mesma armadilha do backfill da `0068` ("a RLS filtra SELECT também"), do outro lado do produto.
  - **O fuso mudou de casa (migration 0073): mora em `tenants.timezone`**, tabela GLOBAL sem RLS que as rotas de auth já leem naturalmente. Fuso é **identidade do tenant**, não brand kit. Elimina a classe do problema em vez de contorná-la com uma sessão extra por login ou um bypass de RLS (as duas alternativas consideradas — a segunda foge da decisão de que a RLS é a garantia única).
  - ⚠️ **`tenant_profiles.timezone` NÃO foi dropada e está CONGELADA** (um ciclo de conferência, como a 0066 fez). Quem a ler recebe o valor do dia da migration, não o que o dono configurou depois. Use `tenant_timezone(db)` (sessão de tenant) ou `timezone_of(db, tenant_id)` (sessão crua) — **nunca** `get_profile(...).timezone`. Gate: `tests/test_settings_timezone.py::test_ninguem_le_mais_o_fuso_do_perfil` (varredura AST, validado por mutação). Dropar a coluna numa migration posterior.
  - ⚠️ **`tenants` não tem RLS**, então toda leitura precisa de filtro explícito por id — mesma exceção documentada de `users`. Gate: `test_auth_timezone_rls.py::test_o_fuso_NAO_atravessa_tenants`. Trocar um bug de fuso por um vazamento entre tenants seria infinitamente pior.
  - **O achado que valeu mais que o bug: TRÊS consumidores liam a coluna do perfil** e não apareceram na investigação inicial — Agenda (evento de dia inteiro), Cockpit (janela do dia) e validade das notificações. Corrigir só o `timezone_of` teria consertado o login e **quebrado os três em silêncio**: a coluna existe, tem valor, a leitura funciona, e nenhum teste protestaria. **Regra (reverberar): ao mover um dado de casa, faça o grep dos leitores ANTES de assumir que a mudança é local — e deixe um gate mecânico no lugar.**
  - **Por que ninguém tinha notado:** a tela `/config` **não tem seletor de fuso**. O campo existe na API e valida, mas nenhum componente o escreve — então todo tenant estava no default, que é justamente o valor que o código quebrado devolvia. Era armadilha armada para quem fosse adicionar o seletor: o `PATCH` responderia com o valor novo e o login continuaria entregando São Paulo.
  - **Só o Postgres reproduz** (o SQLite dos testes não exercita RLS): o gate de regressão é `tests/test_auth_timezone_rls.py`, `rls_e2e`, com controle positivo em cada asserção.
- **[CORRIGIDO] Agenda não mostrava cobranças/contas a pagar (bug de fuso).** Eventos de dia inteiro (cobranca_receber/cobranca_pagar/prazo) são gravados à **meia-noite UTC** da data de vencimento. A Agenda casava o evento ao dia com `new Date(starts_at)` (horário LOCAL) → em fuso negativo (Brasil UTC-3) o evento "voltava" um dia e, nas bordas do mês, caía fora do range → sumia. Fix (frontend, `AgendaPage.tsx`): eventos all-day casam por **data de calendário** (`starts_at.slice(0,10)` = data UTC) e o range da busca usa fronteiras **UTC-date** (`${ymd}T00:00:00Z`), não local→UTC. Idem para a cor "atrasado". Backend sempre injetou o evento corretamente (validado). **Lição (reverberar): toda data de negócio que vira evento all-day deve ser comparada por data de calendário, nunca por horário local.**
- **[CRÍTICO, CORRIGIDO] RLS perdia o tenant no refresh pós-commit (afetava TODOS os módulos).** A `Session` ligada à Engine devolvia a conexão ao pool no `commit()`; o `db.refresh()` seguinte pegava outra conexão sem a GUC `app.current_tenant_id` → RLS escondia a linha → 500 "Could not refresh instance". Funcionava só quando o pool reusava a mesma conexão. **Fix:** `tenant_session` agora prende a Session a UMA conexão dedicada (`engine.connect()`) por todo o request; o refresh pós-commit usa a mesma conexão (GUC setada). Validado: criar em tenant novo OK em todos os módulos + isolamento entre tenants intacto. Regra: qualquer novo helper de sessão de tenant DEVE usar conexão dedicada, nunca a Engine direto.

## 6.1 Dívida técnica / TODO de segurança (de revisão QA — endereçar antes de produção)
- **Enumeração de e-mail no /register:** retorna 409 "e-mail já cadastrado" (UX comum em signup, mas revela existência). Reavaliar quando houver fluxo de e-mail/confirmação.
- **Validação de CPF/CNPJ:** ~~hoje só valida tamanho; falta dígito verificador~~ — **desatualizado, corrigido em 2026-07-30.** `apps/api/app/core/validators.py` **já valida dígito verificador** e normaliza, e é usado por `auth`, `crm`, `contracts`, `platform` e `bank`. O que resta em aberto é só a **unicidade por tenant**. (Esta entrada induziu a Story 8.2 a especificar validação fraca; o @dev conferiu o código, viu que a premissa era falsa e seguiu o padrão real — comportamento correto: **quando uma instrução se apoiar em premissa que você verificar ser falsa, siga o repo e documente**.)
- 🔴 **Anonimizador sem NER — nome livre chega CRU ao Claude (Regra de Ouro nº 2).** `core/anonymizer.py` é 100% regex e mascara só PII **estrutural** (CPF/CNPJ/e-mail/telefone/cartão). Nome próprio, razão social, título de contrato e nome de aplicação passam intactos. Atinge **dois módulos em produção**: o **Jurídico** (peças sob segredo de justiça) e o **Diagnóstico Financeiro** (`_margin_signals` manda `contract.title`; `_investment_signals` manda `inv.name`). Risco residual **aceito pelo fundador em 2026-07-11**, com gate: não expor com `ANTHROPIC_API_KEY` real em produção sem hardening (story própria cobrindo os dois módulos) ou aceite adicional por escrito. Cuidado ao corrigir: estender para nomes tem risco de **over-masking** quebrar o Jurídico. Ver `docs/stories/5.8.story.md`.
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
- ~~**Janela do dia ancorada em meia-noite UTC**, não no fuso do tenant.~~ — **corrigido em 2026-08-05.** A janela já usava `day_window_utc(day, profile.timezone)`; o que faltava era o `day` **default**, que vinha de `datetime.now(UTC).date()` no backend e de `new Date().toISOString()` no frontend. Ambos agora são o dia do tenant. Ver §6.0.

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
