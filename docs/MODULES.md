# Módulos do e1p (spec resumida + ordem de construção)

Fonte: `Configuração do software.docx`. Cada módulo segue o padrão **Características → Área do Admin (config) → camada de IA**.

## Hierarquia de acesso (6 níveis)
1. **Plataforma Master** (dono) — faturamento dos splits, assinaturas, suspender usuários, saúde dos servidores.
2. **Tenant / Usuário Principal** — autônomo (CNPJ/CPF), ID único, subdomínio. Isolamento total de dados.
3. **Segurança/Auth (RBAC)** — login, senha hash, token; sub-usuários restritos; logout 30min (LGPD).
4. **Módulos** (abaixo).
5. **Cliente Final** — sem login; dados amarrados ao tenant.
6. **Motor de IA** — leitura/escrita com rastro "Ação executada pela IA".

## Os 19 módulos
| # | Módulo | Essência |
|---|--------|----------|
| 1 | **Agenda Principal** | Núcleo. Reuniões, atendimentos, prazos, contas do dia. Dashboard p/ 2ª tela. Tudo converge aqui. |
| 2 | **Contas a Pagar** | OCR de boletos, categorização IA, recorrência, alertas de vencimento. |
| 3 | **Contas a Receber** | Boleto/Pix/link, baixa por webhook, régua de cobrança, IA negocia no WhatsApp. |
| 4 | **Controle de Estoque** | Baixa automática por serviço, kits padrão, IA lê anotações/áudio p/ baixar extras. |
| 5 | **Redes Sociais & Meta Ads** | Gera carrossel, agenda posts, gestor de tráfego IA, métricas simples. |
| 6 | **Central de Integrações (API Hub)** | OAuth (Meta), seletor de ativos, monitor de saúde de API. |
| 7 | **Central de Marketing (Funil)** | Canvas drag-drop (Ações/Gatilhos/Tempo), omnichannel, IA prompt-to-canvas. |
| 8 | **CRM & Funil Kanban** | Board drag-drop, ficha 360°, colunas dinâmicas, segmentação, IA saúde do lead. |
| 9 | **Painel do Proprietário** | Gerencial: serviços vs produtos, LTV vs CAC, best-sellers, forecast IA. |
| 10 | **Assistente Jurídico** | Claude API + 21 skills lex. dje-monitor→calculadora→Agenda. **Já existe (migrar de `~/lex-intelligentia-app`).** |
| 11 | **Área de Sites** | Templates landing page, hospedagem + subdomínio, IA web copywriter + SEO. |
| 12 | **Produtos & Checkout** | Físicos + infoprodutos, links de pagamento, entrega automática, recuperação de carrinho IA. |
| 13 | **Carteira & Split** | Motor financeiro 40/30/20, wallet/saque (Pix/TED), KYC bancário, visão Master de GMV. |
| 14 | **Segurança & LGPD** | Cookies, direito ao esquecimento, AES-256, **anonimizador anti-vazamento** p/ IA. |
| 15 | **Assinatura & KYC** | Assinatura na tela, liveness+selfie c/ documento, dossiê hash SHA-256, libera fluxo. |
| 16 | **Central de Orçamentos** | PDF dinâmico, disparo WhatsApp/email, status, "efeito dominó" (cobrança+contrato+CRM). |
| 17 | **Construtor de Contratos** | Blocos drag-drop viram formulário p/ cliente; alimenta CRM; gatilho pós-assinatura (4 ações). |
| 18 | **Marketplace de Estratégias (Growth Hub)** | Campanhas por nicho, plug&play white-label, IA closer. |
| 19 | **Dashboard de Entrada (Cockpit)** | Split-screen, 4 cards de topo, gráficos, modo privacidade, "diagnóstico do dia" IA. **= design Figma "Portal".** |

## Ordem de construção sugerida (faseada)
A spec deixa claro que **tudo orbita a Agenda** e que o **core financeiro/split** é o motor de receita.
Sequência que minimiza retrabalho (cada fase entrega valor e habilita as próximas):

**Fase 0 — Fundação (em andamento)**
Monorepo, core (auth + tenancy RLS + anonimizador + ai + audit + events), shell do frontend, CI + agentes QA.

**Fase 1 — Espinha dorsal**
1. Auth/onboarding de tenant + subdomínio · 2. **Agenda** (1) · 3. **CRM & Kanban** (8) · 4. **Cockpit** (19, design Portal).

**Fase 2 — Dinheiro entra/sai**
5. **Carteira & Split** (13) · 6. **Contas a Receber** (3) · 7. **Contas a Pagar** (2) · 8. **Produtos & Checkout** (12).

**Fase 3 — Documentos & fechamento de venda**
9. **Orçamentos** (16) · 10. **Construtor de Contratos** (17) · 11. **Assinatura & KYC** (15).

**Fase 4 — Crescimento**
12. **API Hub/OAuth** (6) · 13. **Marketing/Funil** (7) · 14. **Meta Ads** (5) · 15. **Sites** (11) · 16. **Growth Hub** (18).

**Fase 5 — Especialista & gestão**
17. **Assistente Jurídico** (10, migração) · 18. **Painel do Proprietário** (9) · 19. **Estoque** (4) · 20. **Segurança & LGPD** (14, transversal — reforçar).

> Observação: módulo 14 (LGPD/anonimizador) é **transversal** — partes dele entram já na Fase 0 (anonimizador no core),
> e o resto é endurecido ao longo do caminho.
