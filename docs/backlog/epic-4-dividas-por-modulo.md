# Catálogo de Backlog — Dívidas menores por módulo (Epic 4 / Story 4.6)

## Objetivo

Catalogar, de forma organizada e rastreável, as **dívidas específicas por módulo** listadas no
`CLAUDE.md` §6 ("Estado atual / roadmap") que **ainda não têm story própria** no Epic 4, para que
sejam priorizadas por valor/risco **após o lançamento**. Este documento é o artefato da
**Story 4.6 — Dívidas menores por módulo**
([epic](../prd/epic-4-backlog-pos-lancamento.md#story-46--dívidas-menores-por-módulo)).

## Status

**Classificação RATIFICADA pelo @pm em 2026-07-11 (revisão final de go-live).**

Proposta originalmente por @dev em modo autônomo e revisada item a item por Morgan (@pm) como
`quality_gate` da Story 4.6. As colunas **Valor / Risco / Prioridade** foram consideradas sólidas e
rastreáveis; um único ajuste de direção estratégica foi aplicado (**Item 3 — PDF assinado**, Valor
Médio-Alto → Alto, marcado como topo do P2 — ver rationale na linha e na "Nota de autoridade").
A priorização de backlog permanece revisável pelo @po no momento em que cada item for puxado para
uma story de implementação (sequenciamento fino), mas a classificação base está aprovada — não é mais
um rascunho pendente.

> **Escopo (o que NÃO está aqui):** este catálogo cobre apenas as dívidas "soltas" do §6 que ainda
> não têm story dedicada. Itens já cobertos por stories próprias do Epic 4 **não** são duplicados aqui:
> Google OAuth (4.1), Upload real de imagem/logo (4.2), Worker/fila durável (4.3),
> Wildcard subdomínio (4.4), Endurecimentos diversos (4.5). Esta story (4.6) é o *catch-all*
> das dívidas menores restantes.

## Como este catálogo foi construído

- Cada linha transcreve a dívida **sem reformular o conteúdo técnico** e cita a **origem exata** no
  `CLAUDE.md` §6 (rastreabilidade — IV2), no formato `[Source: CLAUDE.md#{módulo}]`.
- Nenhum item foi implementado nesta story (é catalogação pura — AC3 / IV1); a implementação vira
  stories próprias quando priorizadas.

## Catálogo (13 itens)

| # | Item | Módulo | Fonte (CLAUDE.md §6) | Valor (proposto) | Risco (proposto) | Prioridade (P1-P4) | Observação |
|---|------|--------|----------------------|------------------|------------------|--------------------|------------|
| 1 | Estorno/reversão de `platform_earnings` | Carteira & Split (Fase 2) | "estorno (`refunded`) ainda sem caminho de execução nem reversão do `platform_earnings`. Payout real precisa integração bancária + KYC (hoje só marca withdrawn)." `[Source: CLAUDE.md#carteira-split]` | Alto | Alto | **P1** | Dinheiro real da plataforma; reversão incorreta pode gerar disputa financeira/contábil com o dono da conta. |
| 2 | OCR de boleto | Contas a Pagar (Fase 2) | "OCR de boleto (IA lê PDF e preenche fornecedor/valor/vencimento) — não implementado" `[Source: CLAUDE.md#contas-a-pagar]` | Médio | Baixo | **P4** | Ganho de produtividade; sem OCR o usuário preenche manualmente (fallback já existe). |
| 3 | PDF assinado com hash/carimbo de tempo | Construtor de Contratos + Assinatura & KYC (Fase 3) | "PDF assinado + hash/carimbo de tempo; verificação real de documento (KYC forte)." `[Source: CLAUDE.md#construtor-de-contratos]` | Alto | Médio | **P2 (topo)** | **[@pm ajustou Valor Médio-Alto → Alto]** Advogados são persona primária (§1) e a assinatura pública já está em produção: cada contrato assinado sem carimbo/hash acumula valor probatório fraco que **não é remediável retroativamente**. Fica no topo do P2 (fazer antes dos demais P2). KYC já registra nome/CPF/IP — não é contrato inválido, por isso fica abaixo dos P1 de dinheiro/segurança. |
| 4 | Régua de cobrança + juros/multa | Contas a Receber (Fase 2) | "régua de cobrança (lembretes automáticos) + juros/multa; estorno;" `[Source: CLAUDE.md#contas-a-receber]` | Alto | Médio | **P2** | Impacta diretamente inadimplência/receita; "Cobrar com IA" manual já mitiga parcialmente o risco hoje. |
| 5 | Antecipação de recebíveis | Carteira & Split (Fase 2) | "Antecipação de recebíveis não implementada." `[Source: CLAUDE.md#carteira-split]` | Médio | Baixo | **P4** | Feature de monetização adicional; não é esperada pelo usuário hoje (não regride nada). |
| 6 | Checkout público real | Produtos & Checkout (Fase 2) | "checkout público real (página + gateway)" `[Source: CLAUDE.md#produtos-checkout]` | Alto | Médio | **P2** | Habilita venda de produto sem intervenção manual do dono da conta — valor direto de monetização. |
| 7 | Área de membros real | Produtos & Checkout (Fase 2) | "área de membros real." `[Source: CLAUDE.md#produtos-checkout]` | Alto | Baixo | **P2** | Completa a promessa "Super Membros"; sem membros real, o produto digital fica incompleto. |
| 8 | Entrega automática de infoproduto | Produtos & Checkout (Fase 2) | "entrega automática (infoproduto: link/arquivo; físico: baixa de estoque + tarefa de envio)" `[Source: CLAUDE.md#produtos-checkout]` | Alto | Baixo | **P2** | Fecha o funil de venda de produto digital (hoje só cria a Transaction, não entrega). |
| 9 | Rate-limit em rotas públicas | Construtor de proposta (Fase 3) + Sites / Páginas (Fase 4) | "rate-limit em `/public/proposals/*`" + "rate-limit/anti-spam no formulário público" `[Source: CLAUDE.md#construtor-de-proposta]` `[Source: CLAUDE.md#sites-paginas]` | Médio | Alto | **P1** | Superfície de ataque (spam/abuso) em formulários e endpoints sem login — risco de segurança, não só de produto. Duas superfícies distintas: pode virar duas stories se as soluções técnicas divergirem. |
| 10 | PDF de orçamento | Construtor de proposta (Fase 3) | "PDF do orçamento;" `[Source: CLAUDE.md#construtor-de-proposta]` | Médio | Baixo | **P4** | Profissionalismo do documento; o orçamento já existe e funciona sem PDF exportável. |
| 11 | "Documentos" como conceito próprio na Ficha 360° | Área do Cliente / Ficha 360° (Fase 3) | "'Documentos' como conceito próprio (hoje a aba mostra Contratos);" `[Source: CLAUDE.md#area-do-cliente-ficha-360]` | Baixo-Médio | Baixo | **P4** | Organização/UX; hoje a aba "Contratos" já cobre a necessidade prática. |
| 12 | Relatório .docx do Jurídico | Assistente Jurídico (Fase 5) | "gerar relatório separado (.docx) como no lex original" `[Source: CLAUDE.md#assistente-juridico]` | Médio | Baixo | **P4** | Paridade com o app legado (`lex-intelligentia-app`); o documento principal já é exportado em .docx. |
| 13 | Versionamento de documentos jurídicos | Assistente Jurídico (Fase 5) | "editar/regenerar documento; versionamento;" `[Source: CLAUDE.md#assistente-juridico]` | Médio | Médio | **P3** | Documento jurídico sem versionamento pode gerar confusão sobre qual versão foi usada/assinada. |

**Legenda de prioridade:** P1 = fazer primeiro (risco/valor mais altos) · P2 = alto valor de negócio ·
P3 = médio · P4 = incremental (fallback aceitável hoje).

## Nota de autoridade

Classificação **proposta em modo autônomo** e **ratificada por Morgan (@pm) em 2026-07-11** na
revisão final de go-live (quality_gate da Story 4.6). O @pm é dono da orquestração do Epic 4; a
ratificação resolve a lacuna original do AC2 (a coluna não é mais um rascunho "pendente").

**Ajuste do @pm nesta revisão (1 item):**
- **Item 3 — PDF assinado com hash/carimbo:** Valor **Médio-Alto → Alto** e marcado como **topo do
  P2**. Motivo: advogados são persona primária do produto e a assinatura pública já roda em produção;
  cada contrato assinado sem carimbo/hash acumula valor probatório fraco **não remediável
  retroativamente**. Continua abaixo dos P1 (dinheiro/segurança) porque o KYC atual já registra
  nome/CPF/IP — o contrato não é inválido, apenas menos forte.

Os outros 12 itens foram revisados e mantidos como classificados (valor/risco/prioridade coerentes com
o estado atual descrito no CLAUDE.md §6). O **@po** pode refinar o **sequenciamento fino** quando cada
item virar story de implementação, mas nenhum item deve ser considerado "aprovado para implementação"
apenas por constar aqui — vira story própria com seus próprios ACs.

## Verificação de consistência com o PRD (IV3)

**Verificado em 2026-07-10:** nenhum dos 13 itens acima consta como **BLOQUEANTE** ou
**BLOQUEANTE-LEVE** na tabela de classificação `docs/prd.md` §5.2 ("Classificação: Bloqueante para
lançamento vs Backlog pós-lançamento"). O conjunto inteiro está classificado na linha agregada:

> "Dívidas menores por módulo (estorno, OCR boleto, PDF assinado, régua de cobrança, etc.) |
> §6 por módulo | **BACKLOG** | Epic 4"

`[Source: docs/prd.md#5.2-classificacao-bloqueante-para-lancamento-vs-backlog-pos-lancamento]` —
IV3 satisfeito (nenhum item bloqueante foi rebaixado para cá por engano).

## Sugestão de rastreabilidade reversa (para @pm/@po)

Este catálogo referencia o epic, mas o epic-fonte
(`docs/prd/epic-4-backlog-pos-lancamento.md`) **não** foi editado para apontar de volta — arquivos de
epic são mantidos pelo @pm (`*create-epic`/`*execute-epic` é operação exclusiva do @pm por
`.claude/rules/agent-authority.md`), e o @sm/@dev não deve alterá-los. Se um link inverso for
desejável no epic, cabe ao @pm ou @po adicioná-lo numa ação separada.
