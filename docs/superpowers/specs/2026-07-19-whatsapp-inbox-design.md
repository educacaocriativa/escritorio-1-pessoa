# Inbox de WhatsApp (conversa de verdade com clientes)

**Data:** 2026-07-19
**Status:** Aprovado (brainstorming), aguardando plano de implementação
**Precedente direto:** PRs #35 (credenciais + templates por tenant) e a issue #36 (webhook de
aprovação de template) — esta feature reaproveita boa parte da infraestrutura das duas.

## 1. Problema

Hoje o e1p só manda WhatsApp (outbound): credenciais por tenant + templates aprovados pela Meta
(PR #35), usados no nó do funil e em 5 fluxos automáticos (cobrança, contrato, orçamento,
convite de staff, aviso de card movido). Não existe nenhum jeito de **receber** o que o cliente
responde, nem de ter uma conversa de ida-e-volta dentro do produto — o dono responde direto no
celular dele, fora do e1p, e esse histórico se perde pro sistema.

Motivador concreto: o primeiro cliente real (Doro Eventos) precisa mandar **cardápio** (imagem/
PDF) pelos WhatsApp dos clientes dele, e o atendente humano precisa ver a conversa inteira
(incluindo os avisos automáticos que o sistema já manda) pra ter contexto completo antes de
responder.

## 2. Escopo (o que foi decidido no brainstorming)

- **Inbox de verdade dentro do CRM** (não só "avisar que o cliente respondeu") — dono e
  funcionários (sub_users) leem e respondem de dentro do e1p.
- **Inbox compartilhada, sem atribuição formal** — qualquer atendente vê e responde qualquer
  conversa. Sem fila, sem "pegar atendimento".
- **Número desconhecido vira lead automaticamente** — mesmo padrão já usado pra captura de lead
  externa (`source=api`), aqui com `source=whatsapp`.
- **Atualização por polling** (5-10s), sem WebSocket — mais simples, mesmo espírito de custo do
  projeto (Golden Rule §4).
- **Mídia completa nos dois sentidos** — cliente manda foto/áudio/documento e aparece de
  verdade (não só "cliente enviou uma imagem"); atendente também consegue MANDAR mídia de volta
  (essencial pro caso de uso do cardápio).
- **Janela de 24h detectada automaticamente** — dentro da janela, texto/mídia livre; fora,
  troca sozinha pro seletor de template aprovado (mesmo componente já usado no funil).
- **Conversa unificada** — o fio mostra tanto as mensagens da inbox quanto os avisos automáticos
  já existentes (cobrança, contrato, etc.), sem migrar nada: é uma leitura combinada, não uma
  tabela nova pros dados antigos.
- **Cada tenant tem seu próprio App na Meta** (auto-atendimento, mesmo modelo da PR #35) — não
  somos "Tech Provider" da Meta. Implica: cada tenant configura o próprio webhook no painel dele.

### Fora de escopo (decisão explícita, não esquecimento)

- Recibos de entrega/leitura (`statuses` do webhook — "entregue"/"visto") — não pedido, fica
  pra depois.
- Atribuição de conversa a um atendente específico / fila — inbox compartilhada resolve por
  ora.
- "Não-lida" por atendente individual — é compartilhado (lida por qualquer um = lida pra todos).
- Onboarding automatizado do webhook na Meta (Embedded Signup) — o tenant cola a URL e o
  verify_token manualmente no painel dele, uma vez.

## 3. Arquitetura

```
Cliente manda WhatsApp
        │
        ▼
Meta Cloud API ──POST──▶ /public/whatsapp/webhook
        │                         │
        │                  valida assinatura (app_secret do tenant, achado via phone_number_id)
        │                         │
        │                  cliente já existe (por telefone)? não → cria lead (source=whatsapp)
        │                         │
        │                  grava WhatsappMessage (direction=in); mídia fica "pendente"
        │                         │
        │                  responde 200 rápido pra Meta
        │
        ▼
Worker (já existe) baixa mídia pendente em background
        │
        ▼
Tela "Conversas" no CRM (polling 5-10s)
   • fio = WhatsappMessage + Notification(channel=whatsapp) do mesmo client_id, mesclados por data
        │
   atendente responde (texto / mídia / template, conforme janela de 24h)
        │
        ▼
grava WhatsappMessage (direction=out)
```

## 4. Credenciais (extensão da PR #35)

`TenantProfile` ganha 2 campos novos, além dos 3 já existentes (`whatsapp_token`,
`whatsapp_phone_id`, `whatsapp_waba_id`):

- `whatsapp_app_secret` (cifrado, mesmo padrão do token) — usado só pra validar a assinatura do
  webhook (`X-Hub-Signature-256`).
- `whatsapp_verify_token` (texto simples, não é segredo) — gerado automaticamente na primeira
  vez que o tenant salva as credenciais; mostrado na UI pra ele colar no painel de configuração
  do webhook da Meta, junto com a URL (`https://{domínio}/api/public/whatsapp/webhook`).

Uma tabela GLOBAL nova (sem RLS, mesmo padrão de `public_integration_keys`/`published_pages`):
`public_whatsapp_accounts` (`phone_number_id` único, `tenant_id`, `app_secret`,
`verify_token`) — mantida em sincronia (dual-write) toda vez que o tenant salva/altera as
credenciais em Configurações. É essa tabela que resolve "de qual tenant é esse evento?" e "qual
app_secret usar pra validar a assinatura?" ANTES de qualquer sessão de tenant existir.

## 5. Modelo de dados novo

### `WhatsappMessage` (RLS, por tenant)

| Campo | Tipo | Observação |
|---|---|---|
| `client_id` | string | cliente da conversa |
| `direction` | `in` \| `out` | quem mandou |
| `kind` | `text`\|`image`\|`audio`\|`document`\|`video` | tipo de conteúdo |
| `text_body` | text, nullable | texto ou legenda |
| `media_attachment_id` | string, nullable | link pro módulo de Anexos já existente (reaproveita storage S3/Postgres) |
| `media_status` | `none`\|`pending`\|`downloaded`\|`failed` | só relevante pra mídia `in` (download assíncrono pelo worker) |
| `wa_message_id` | string, unique por tenant | ID da própria Meta — evita duplicata de webhook reentregue |
| `status` | string | só relevante pra `out` (`sent`\|`logged`\|`failed`, mesmo vocabulário de sempre) |

### `WhatsappConversationState` (RLS, por tenant) — 1 linha por cliente com atividade

| Campo | Tipo |
|---|---|
| `client_id` | string |
| `last_read_at` | datetime, nullable |

Usado só pra calcular "não lida" (qualquer mensagem `in` mais nova que `last_read_at` = não
lida). Marcar como lida é um PATCH simples quando a conversa é aberta — compartilhado entre
toda a equipe do tenant (sem granularidade por atendente).

## 6. Webhook de entrada

- `GET /public/whatsapp/webhook`: handshake de verificação da Meta (`hub.mode`,
  `hub.verify_token`, `hub.challenge`) — confere o token contra `public_whatsapp_accounts`,
  ecoa `hub.challenge` se bater.
- `POST /public/whatsapp/webhook`:
  1. Extrai `phone_number_id` do payload (`entry[].changes[].value.metadata.phone_number_id`).
  2. Busca `tenant_id` + `app_secret` em `public_whatsapp_accounts`.
  3. Valida `X-Hub-Signature-256` (HMAC-SHA256 do corpo CRU, comparação de tempo constante) —
     falha = 403, não processa nada.
  4. Abre `tenant_session(tenant_id)`. Pra cada mensagem no payload: resolve/cria o `Client`
     pelo telefone; grava `WhatsappMessage(direction=in, ...)` (mídia entra com
     `media_status=pending`, sem baixar ainda); ignora se `wa_message_id` já existe.
  5. Responde 200 rápido (a Meta exige resposta em poucos segundos).
- Um novo tick do worker já existente (`app.worker`) varre `WhatsappMessage` com
  `media_status=pending`, baixa o arquivo (média_id → URL temporária → bytes → `core/storage.py`)
  e atualiza pra `downloaded`/`failed` — mesmo princípio de isolamento de falha (IV2) já usado
  na fila de notificações.

## 7. Fluxo de resposta

- **Janela de 24h**: calculada a partir do `WhatsappMessage(direction=in)` mais recente daquele
  cliente. Dentro → texto/mídia livres. Fora (ou nunca houve mensagem `in`) → só template.
- **Texto livre**: reaproveita `whatsapp.send_text` (já ciente do tenant, desde a PR #35).
- **Mídia** (novo): upload pra Meta a cada envio (`POST /{phone_id}/media` → `media_id`
  temporário, sem cache — validade curta) + envio referenciando esse ID.
- **Template** (fora da janela): reaproveita o MESMO seletor de template + variáveis já
  construído pro nó do funil — não duplica esse componente.
- Endpoint novo: `POST /whatsapp-conversations/{client_id}/messages` (texto, upload
  multipart, ou `template_id`+variáveis).

## 8. Frontend — tela de Conversas

Duas colunas, novo item de menu:
- **Esquerda**: lista de conversas por cliente, ordenada pela mensagem mais recente, indicador
  de não-lida (via `WhatsappConversationState`).
- **Direita**: fio da conversa — `WhatsappMessage` + `Notification(channel=whatsapp)` do mesmo
  `client_id`, mesclados por data/hora numa lista só; mensagem automática ganha uma etiqueta
  (reaproveita `PURPOSE_LABELS` já criado na Fase 2 — ex: "🤖 Lembrete de cobrança").
- **Caixa de resposta**: dentro da janela de 24h → texto + botão de anexo; fora da janela →
  troca sozinha pro seletor de template.
- **Atualização**: polling a cada 5-10s, sem WebSocket.

## 9. Erros e testes

- Assinatura inválida → 403, log de tentativa suspeita, nada processado.
- Falha ao baixar mídia → fica `failed`, isolada (não trava outras mensagens da fila).
- Mensagem duplicada da Meta → ignorada via `wa_message_id`.
- Testes: mock da Graph API (envio de texto/mídia/upload); payloads de exemplo reais da
  documentação da Meta pro webhook (texto, imagem, duplicata, assinatura inválida, tenant
  desconhecido); isolamento de tenant (RLS) na resolução do webhook e no endpoint de conversas;
  detecção correta da janela de 24h (limite exato, sem mensagem `in` nenhuma, mensagem `in`
  antiga).

## 10. Reaproveitamento explícito (não reinventar)

- Credenciais/token cifrado: `core/token_crypto.py::EncryptedToken` (já existe).
- Storage de mídia: `core/storage.py` + módulo de Anexos (já existe).
- Padrão global-snapshot-pra-resolver-antes-de-autenticar: mesmo de
  `integration_keys`/`public_integration_keys` (PR #32) e `published_pages`/`Page`.
- Seletor de template + variáveis: o mesmo componente já construído pro nó do funil (PR #35).
- Fila assíncrona resiliente (IV2): o worker e o padrão de isolamento de falha já usados em
  `notifications/service.py::process_pending`.
- Rótulos de propósito automático: `PURPOSE_LABELS` (Fase 2 da PR #35).
