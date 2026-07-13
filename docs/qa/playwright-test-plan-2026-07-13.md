# Plano de Teste E2E (Playwright, manual via MCP) — 2026-07-13

## Objetivo
Navegar e exercitar manualmente (via Playwright MCP, sem escrever specs ainda — ver "Próximo passo")
todas as telas e fluxos de cadastro do e1p, catalogando bugs e quebras de continuidade como issues
no GitHub (`educacaocriativa/escritorio-1-pessoa`).

## Contexto do ambiente (achado antes de testar)
- **API:** container `infra-api-1`, `http://localhost:8000` — no ar.
- **Web:** dev server do e1p **não estava rodando**; iniciado nesta sessão (`pnpm --filter @e1p/web dev`).
- ⚠️ **Colisão de porta 5173:** outro projeto do usuário (`NexusGestao`, PID do Vite dele) já escutava
  em `[::1]:5173` (IPv6-only). O Vite do e1p subiu em `0.0.0.0:5173`/`[::]:5173`. Como `localhost`
  resolve para `::1` primeiro neste ambiente, `http://localhost:5173` abre o app ERRADO
  (branding "NexusPública"). **Usar sempre `http://127.0.0.1:5173`** para testar o e1p enquanto os
  dois projetos rodarem ao mesmo tempo. Registrado como issue de ambiente (ver catálogo).
- **Login seed:** `admin@e1p.com` / senha default `trocar-no-primeiro-acesso` (troca forçada no 1º
  acesso — `must_reset_password`). Se já trocada em sessão anterior, senha real é desconhecida.

## Escopo (rotas descobertas em `apps/web/src/app/App.tsx`)
Público (sem login): `/login`, `/orcamento/:slug`, `/contrato/:slug`, `/p/:slug`.
Protegido (`ProtectedLayout`): `/`, `/agenda`, `/crm`, `/crm/clients/:id`, `/financeiro` (+8 subrotas),
`/cobrancas`, `/pagar`, `/produtos`, `/estoque`, `/config`, `/sites` (+builder), `/orcamentos` (+builder),
`/contratos` (+builder), `/marketing` (+builder), `/juridico` (+wizard/doc), `/funis` (+builder), `/admin`.

## Clusters de teste
| # | Cluster | Telas | Prioridade |
|---|---------|-------|-----------|
| 1 | Auth & 1º acesso | login, esqueci senha, reset, first-access (troca obrigatória), idle timeout | P1 |
| 2 | Admin/Master | `/admin` (Escritórios/Clientes/Config), convite de conta, convite de funcionário, suspender/excluir | P1 |
| 3 | Cockpit + Agenda | `/`, `/agenda` (Mês/Semana/Dia), criar evento, detalhe/modal, drag-and-drop Kanban | P1 |
| 4 | CRM | `/crm` (Kanban), criar cliente, mover card, `/crm/clients/:id` (Ficha 360°) | P1 |
| 5 | Cobranças & Pagar | `/cobrancas`, `/pagar`, criar cobrança/conta, boleto/Pix, editar, reagendar, protestar | P1 (dinheiro) |
| 6 | Orçamentos & Contratos | `/orcamentos`, builder, link público (`/orcamento/:slug`), `/contratos`, builder, link público (`/contrato/:slug`) + KYC | P1 (dinheiro/jurídico) |
| 7 | Produtos & Estoque | `/produtos` (produto/cupom/aluno), `/estoque` (item/movimentação) | P2 |
| 8 | Financeiro (painel gerencial) | `/financeiro` + 8 subrotas (plano de contas, centros de custo, investimentos, DRE, projeção, fila, diagnóstico) | P2 |
| 9 | Marketing & Funis | `/marketing` (carrossel), `/funis` (canvas, automação) | P2 |
| 10 | Jurídico | `/juridico` (catálogo de skills), wizard, geração de documento, download .docx | P2 (persona primária) |
| 11 | Sites & Config | `/sites` (builder), página pública `/p/:slug`, `/config` (perfil + brand kit) | P2 |

## Metodologia por tela
1. Navegar via `127.0.0.1:5173`; capturar snapshot + console (`browser_console_messages`, level=error).
2. Exercitar o "caminho feliz" principal (criar/editar/excluir quando aplicável).
3. Tentar 1 caminho infeliz óbvio (campo obrigatório vazio, id inexistente) quando barato de testar.
4. Registrar: tela, passos, esperado vs. observado, severidade, evidência (screenshot/console).
5. Bug real e reproduzível → issue no GitHub com label de módulo + severidade.

## Próximo passo (fora deste plano manual)
Gap já catalogado em `docs/qa/test-coverage-gate-2026-07-11.md` (#1, #4, #5): não existe suíte
Playwright automatizada nem infra de teste de componente no frontend. Esta sessão é uma auditoria
manual E2E; a automação (specs reais em `apps/web/e2e/`) é trabalho de story separado, a cargo de @qa/@dev.

## Achados

### Clusters cobertos
| # | Cluster | Resultado |
|---|---------|-----------|
| 1 | Auth & 1º acesso | ✅ Login, logout, troca obrigatória de senha, esqueci senha, reset — todos OK |
| 2 | Admin/Master | ✅ Convite conta/funcionário, suspender/reativar, excluir conta — OK. Validação de CPF (dígito verificador) funcionando corretamente |
| 3 | Cockpit + Agenda | ⚠️ Cockpit OK. **Bug de fuso horário em eventos com hora específica** (#23) |
| 4 | CRM | ✅ Kanban, criar cliente, Ficha 360° — OK |
| 5 | Cobranças & Pagar | ⚠️ Criar/editar cobrança e conta a pagar OK. **"simular pgto" falha silenciosamente (401)** (#24) |
| 6 | Orçamentos & Contratos | ✅ Builder, link público, aceite (efeito dominó), assinatura com KYC — fluxo completo OK |
| 7 | Produtos & Estoque | ✅ Smoke test OK, sem erros de console |
| 8 | Financeiro (painel gerencial) | ⚠️ Todas as 8 subrotas carregam sem erro. **DRE (`/financeiro/dre`) é uma feature órfã sem link de navegação** (#25) |
| 9 | Marketing & Funis | ✅ Smoke test OK (builders carregam, sem testar geração por IA — sem `ANTHROPIC_API_KEY` neste ambiente) |
| 10 | Jurídico | ✅ Catálogo de 21 skills, wizard dinâmico, geração de documento — falha graciosa esperada sem `ANTHROPIC_API_KEY` (comportamento documentado, não é bug) |
| 11 | Sites & Config | ✅ Builder de página, publicação, página pública, salvar configurações (branch atual corrige o bug antigo de "config-save-blank-page" — confirmado resolvido) |

### Issues abertas
| Issue | Severidade | Resumo |
|-------|-----------|--------|
| [#23](https://github.com/educacaocriativa/escritorio-1-pessoa/issues/23) | Alta | Evento de Agenda criado às 09:00 é salvo/exibido às 06:00 (bug de fuso horário no formulário, não na exibição) |
| [#24](https://github.com/educacaocriativa/escritorio-1-pessoa/issues/24) | Média | "simular pgto" falha com 401 sem feedback quando `GATEWAY_WEBHOOK_SECRET` está configurado |
| [#25](https://github.com/educacaocriativa/escritorio-1-pessoa/issues/25) | Média | Tela DRE por categoria funcional mas sem nenhum link de navegação (órfã) |
| [#26](https://github.com/educacaocriativa/escritorio-1-pessoa/issues/26) | Baixa | Pluralização incorreta em contadores ("1 funcionários", "1 cobranças") |

### Nota de ambiente (não é bug de código, mas afetou o teste)
A porta 5173 estava ocupada por outro projeto do usuário (`NexusGestao`, escutando em `[::1]:5173`). O Vite do e1p subiu em `0.0.0.0:5173`, e como `localhost` resolve para `::1` primeiro neste ambiente, `http://localhost:5173` abria o app errado. Testado com sucesso via `http://127.0.0.1:5173`. Se isso confundir outros desenvolvedores na mesma máquina, vale considerar fixar uma porta alternativa dedicada no `vite.config.ts` do e1p.

### Dados de teste criados (ambiente de dev, não removidos)
- Cliente CRM "Cliente QA Playwright"
- Evento de Agenda "QA Teste - Reunião Playwright" (13/07, demonstra o bug #23)
- Cobrança "QA Teste - Serviço Playwright" (boleto) + cobrança gerada pelo efeito dominó do orçamento
- Conta a pagar "QA Teste - Conta Fornecedor"
- Orçamento "QA Teste - Proposta Playwright" (aceito publicamente)
- Contrato "QA Teste - Contrato Playwright" (assinado publicamente)
- Página "QA Teste - Landing Page" (publicada em `/p/qa-teste-landing-page-ZEbdre2Kaw4`)
- Documento jurídico (Calculadora Processual, geração falhou graciosamente por falta de `ANTHROPIC_API_KEY`)
- Escritório de teste em `/admin` foi criado E excluído durante o teste (cleanup completo, não deixou resíduo)
