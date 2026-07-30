# WhatsApp por QR Code (Evolution API) — transporte multi-tenant

**Data:** 2026-07-30
**Status:** Aprovado (brainstorming), aguardando plano de implementação
**Precedente direto:** PR #35 (credenciais + templates por tenant) e o inbox de WhatsApp
(`docs/superpowers/specs/2026-07-19-whatsapp-inbox-design.md`) — esta feature reaproveita
o domínio inteiro dos dois e troca apenas o transporte.
**Origem:** estudo comparativo com o WhatsApp do Orbitask
(`github.com/educacaocriativa/orbitask`), que já roda Evolution API em produção.

---

## 1. Problema

O e1p entrega WhatsApp pela **Meta Cloud API**, com credenciais por tenant (PR #35) e inbox
bidirecional completo (PR do inbox). O domínio está maduro: mídia nos dois sentidos, janela de
24h, templates aprovados com vínculo por propósito, lead automático, RLS, HMAC no webhook.

O que não funciona é a **porta de entrada**. Para ligar o WhatsApp, o tenant precisa:

1. criar um App em `developers.facebook.com`;
2. criar e **verificar** uma WABA (Business Verification da Meta);
3. extrair 4 credenciais (token, `phone_number_id`, `waba_id`, App Secret);
4. colar as 4 em Configurações;
5. **voltar ao painel da Meta** e configurar Callback URL + verify token do webhook;
6. criar cada template e **esperar aprovação** (minutos a horas);
7. amarrar template a propósito.

Na prática isso trava a adoção: cliente de escritório de 1 pessoa não conclui esse roteiro. O
resultado é que a integração fica desligada e **todo envio cai em `"logged"`** — a cobrança
automática, o aviso de contrato e o nó do funil nunca chegam a ninguém, sem que nada proteste.

O Orbitask resolveu o mesmo problema por outro caminho: **Evolution API self-hosted (Baileys)**,
onde conectar é escanear um QR code. Sem Meta, sem WABA, sem template, sem espera.

## 2. Decisões tomadas (brainstorming)

| Decisão | Escolha |
|---|---|
| Transporte da v1 | **Evolution (não oficial), transporte completo** — os 5 fluxos automáticos, o nó do Funil, o inbox e o lead inbound |
| Meta Cloud API | **Permanece**, vira a alternativa "oficial"; dois onboardings coexistem no produto |
| Coexistência | **Um transporte ativo por vez, por tenant**; trocar é ação explícita |
| Multi-tenancy | **Uma instância Evolution por tenant**, QR escaneado pelo próprio tenant |
| Sessão caída | **Fila segura com prazo de validade** por propósito; vencida expira e é exibida como tal |
| Infra | **Mesma VPS, com teto rígido de memória** no container da Evolution |
| IA no loop | **Não** — a IA redige, o humano envia (mantém o padrão atual do e1p) |

### Fora de escopo (decisão explícita, não esquecimento)

- **Embedded Signup / e1p como Tech Provider da Meta** — é o "segundo momento" citado pelo
  fundador; encurtaria o onboarding oficial, mas exige credenciamento e Business Verification
  nossos. Não entra nesta feature.
- **IA respondendo lead sozinha e movendo estágio sozinha** (comportamento do Orbitask).
- **Recibos de entrega/leitura** — segue fora, como já estava no inbox.
- **Campanha / disparo em lote.**
- **Migração automática de tenant Meta → Evolution.** A troca é manual e explícita.

## 3. Contexto: o que o Orbitask faz hoje (fonte do estudo)

Registrado porque justifica várias decisões abaixo por contraste.

- Evolution API (`atendai/evolution-api:latest`), integração `WHATSAPP-BAILEYS`, container no
  próprio compose com **porta 8080 publicada**.
- **Instância única e fixa** (`EVOLUTION_INSTANCE=orbitask`) — o `schema.prisma` não tem model de
  tenant/organização; é single-tenant por construção.
- Onboarding: `POST /instance/create` → manager web → escaneia QR. Zero contato com a Meta.
- Outbound: card movido, menção, prazo expirado, prazo próximo, comunicado em massa.
- Crons reais: `'0 10 * * *'` (detecta vencidos) e `'0 11 * * *'` (alerta repetido),
  `America/Sao_Paulo` — **a documentação do Orbitask diz "a cada 2 horas"; o código diz outra
  coisa.** Divergência real, registrada aqui para quem for reusar.
- Fila BullMQ/Redis, `attempts: 3`, backoff exponencial — **exceto o comunicado em massa**, que
  roda num `setImmediate` com `for` sequencial: sem retry, sem persistência, sem controle de taxa.
- Inbound: webhook `messages.upsert`, autenticado por **segredo em query string**
  (`?secret=`, comparação direta de string, sem HMAC).
- Casamento mensagem→lead em 4 estágios, os dois últimos heurísticos: score de `pushName` e
  "quem recebeu outbound nos últimos 30 minutos".
- **Sem mídia** (lê só `conversation` e `extendedTextMessage.text`), sem janela de 24h, sem
  template, sem reconexão automática (o script detecta e avisa; reconectar é humano).
- IA (Claude Sonnet 4.6) responde o lead e move o estágio **automaticamente**, sem humano.

## 4. Arquitetura — transporte plugável

`app/core/whatsapp.py` (módulo) vira pacote:

```
app/core/whatsapp/
  __init__.py            # despachante — a API pública que os 9 chamadores já usam
  capabilities.py        # o que cada transporte sabe fazer (dados, não if)
  providers/meta.py      # o core/whatsapp.py de hoje, movido sem mudança de comportamento
  providers/evolution.py # novo
```

O despachante resolve o transporte a partir do `TenantProfile` e delega.

**Invariantes do contrato** (os de hoje, promovidos a fronteira):

- `send_text` / `send_template` / `send_media` devolvem `"sent" | "logged" | "failed"` e **nunca
  propagam exceção** (fire-and-forget, degradação graciosa).
- As administrativas (`create_template`, `fetch_template_status`, `delete_template`,
  `upload_media`, `fetch_media_url`, `download_media`) **propagam** `WhatsappApiError`.
- Transporte não resolvido (`whatsapp_provider is None`) → `"logged"`, exatamente como hoje.

### Alteração nos 9 pontos de chamada

Trocam `token=` / `phone_id=` por `profile=`. Nenhuma outra mudança.

| Arquivo | Fluxo |
|---|---|
| `modules/notifications/service.py` | worker que entrega a fila |
| `modules/receivables/service.py` | cobrança (2 pontos) |
| `modules/contracts/service.py` | contrato |
| `modules/quotes/service.py` | orçamento |
| `modules/funnels/service.py` | nó do Funil |
| `modules/platform/service.py` | convite de staff |
| `modules/whatsapp_inbox/service.py` | inbox: texto, mídia, template, download |
| `modules/whatsapp_inbox/router.py` | webhook |

### Campo novo

`TenantProfile.whatsapp_provider`: `"meta" | "evolution" | None`.
`None` é o estado atual (transporte desligado). **Nenhum tenant existente muda de comportamento
na migration.**

### Capacidades — a parte que evita o bug silencioso

Os transportes diferem em regra de negócio, não só no fio: no Baileys **não existe janela de 24h
nem template aprovado**. Espalhar isso em `if` garante que alguém esqueça um dia.

```python
@dataclass(frozen=True)
class Capabilities:
    templates: bool        # a Meta exige template fora da janela; o Baileys não conhece o conceito
    session_window: bool   # janela de 24h existe?
    media: bool            # mídia nos dois sentidos
    provisioning: str      # "credentials" | "qrcode"

META      = Capabilities(templates=True,  session_window=True,  media=True, provisioning="credentials")
EVOLUTION = Capabilities(templates=False, session_window=False, media=True, provisioning="qrcode")
```

Três consumidores, todos consultando o mesmo objeto:

| Consumidor | `templates=True` | `templates=False` |
|---|---|---|
| `notifications.enqueue` | resolve o vínculo propósito→template | ignora vínculo, texto livre |
| Caixa de resposta do inbox | fora da janela → seletor de template | sempre texto livre |
| Tela de Configurações | mostra cards de Templates e Vínculos | esconde os dois |

**Mídia sai com paridade.** A Evolution suporta mídia nos dois sentidos (o Orbitask é que não
implementou). Regredir o inbox para só-texto perderia o caso de uso que originou a feature
(cardápio da Doro Eventos).

## 5. Onboarding por QR Code

Módulo novo `app/modules/whatsapp_session/` — sessão viva tem ciclo de vida próprio (conecta,
cai, reconecta, troca de número); não é campo de configuração.

**Nome da instância: `e1p-{tenant_id}`.** Nunca o slug — slug muda, `tenant_id` não, e o nome da
instância é a chave que liga o webhook ao tenant.

### Fluxo

1. Configurações → WhatsApp → "Conectar por QR Code".
2. `POST /whatsapp-session/connect` — o backend cria a instância na Evolution (idempotente),
   **configura o webhook sozinho** apontando para a URL interna com o segredo daquele tenant,
   pede o QR e devolve o base64.
3. A tela mostra o QR e faz polling de status a cada 3s (mesmo padrão do inbox, sem WebSocket).
4. Status `open` → grava `whatsapp_provider="evolution"`, guarda o número conectado, e faz o
   dual-write em `public_whatsapp_instances`.

O tenant nunca vê a Evolution, nunca cola URL, nunca escolhe evento de webhook. **Escaneia e
acabou** — é a diferença inteira em relação ao roteiro da Meta.

### Endpoints

| Endpoint | Efeito |
|---|---|
| `POST /whatsapp-session/connect` | cria instância (idempotente) + configura webhook + devolve QR |
| `GET /whatsapp-session/status` | `never \| connecting \| connected \| disconnected` |
| `POST /whatsapp-session/refresh-qr` | QR expira em ~60s |
| `DELETE /whatsapp-session` | logout na Evolution, limpa `whatsapp_provider` (usado para trocar de número) |

### Queda de sessão

O worker ganha uma **4ª etapa**: confere o status das instâncias a cada sweep. Caiu → marca no
perfil e avisa o dono **por e-mail** — o canal que não depende do que acabou de quebrar.

Reconectar exige QR novo, então é humano. **O produto não promete reconexão automática**, porque
ela não existe. (O Orbitask documenta o mesmo limite: o script detecta, a reconexão é manual.)

### Endurecimento

A API key da Evolution é **global** — quem a tem controla a instância de todos os tenants. O
Orbitask publica `8080:8080`. Aqui a Evolution **não publica porta nenhuma**: fica só na rede
interna do Docker, alcançável pela API e pelo worker, sem rota no Traefik. O manager web dela não
existe para fora.

## 6. Webhook de entrada

### Um formato normalizado, dois parsers

```python
@dataclass(frozen=True)
class InboundMessage:
    wa_message_id: str
    from_phone: str | None     # só dígitos, sem "+". None quando o WhatsApp não entrega o número
    kind: str                  # text | image | audio | document | video
    text_body: str
    media_ref: str | None      # meta_media_id, ou a referência de mídia da Evolution
    push_name: str
```

`providers/meta.parse_inbound()` e `providers/evolution.parse_inbound()` devolvem isso. De
`whatsapp_inbox/service.py` para dentro — resolver cliente, criar lead, deduplicar por
`wa_message_id`, enfileirar mídia pendente — **nada muda**.

### Rota e resolução do tenant

`POST /internal/whatsapp/evolution/webhook`, e o `internal` é literal: a Evolution só existe na
rede interna, o webhook aponta para `http://api:8000/...`, e o Traefik não publica essa rota. **O
evento nunca sai da máquina** — estruturalmente mais forte que o `?secret=` em query string do
Orbitask, que viaja pela internet e cai em log de proxy.

Como defesa em profundidade, um segredo por tenant em header, configurado no `POST /webhook/set`
da instância. **A implementação deve confirmar suporte a header customizado na versão fixada da
Evolution**; se não houver, o isolamento de rede permanece a garantia primária e o segredo entra
como segmento de path (nunca query string).

A imagem é **fixada em versão**, não `:latest` como no Orbitask — o contrato do webhook é
superfície que não pode mudar sozinha num `docker pull`.

### Tabela global nova

`public_whatsapp_instances` (sem RLS, mesmo padrão de `public_whatsapp_accounts`):

| Campo | Tipo | Observação |
|---|---|---|
| `instance_name` | string, PK | `e1p-{tenant_id}` |
| `tenant_id` | string | |
| `webhook_secret` | cifrado (`EncryptedToken`) | |

Separada de `public_whatsapp_accounts` porque a chave natural é outra (`phone_number_id` da Meta
contra nome de instância). Mesmo padrão, tabelas distintas — uma tabela com duas chaves opcionais
é a que produz "esqueci de checar qual das duas está preenchida".

### Lead no CRM

Já é o comportamento do inbox: número desconhecido vira `Client` com `source="whatsapp"` e a
conversa abre sozinha. **Não é trabalho novo** — passa a valer para quem entra por QR Code.

### O `@lid`: divergência deliberada do Orbitask

Às vezes o WhatsApp entrega `@lid` no lugar do telefone e o número não vem. O Orbitask resolve
com pontuação de `pushName` e "quem recebeu outbound nos últimos 30 minutos" — heurística que
**erra em silêncio**, colando a resposta de um lead na conversa de outro.

Aqui: **quando não dá para saber, o produto diz que não sabe.**

- `WhatsappMessage.client_id` passa a aceitar `NULL`.
- A mensagem cai numa bandeja **"Não identificados"** no topo da tela de Conversas.
- O dono liga ao cliente certo com um clique; o JID fica gravado e o resto da conversa casa
  sozinho.

Mesma decisão do Epic 8: `indisponivel` não é zero, e suprimir a afirmação é melhor que chutar.

## 7. Fila: validade, retry e freio

### Validade

`Notification` ganha `expires_at`, definido no enfileiramento pelo propósito:

| Propósito | Validade | Por quê |
|---|---|---|
| Cobrança, contrato, orçamento | fim do dia no fuso do tenant | dinheiro com data; chegar amanhã ainda serve, semana que vem não |
| Card movido, convite de staff, nó do Funil | 1 hora | aviso operacional; velho é ruído |

Vencida e ainda `pending` → status **`"expired"`**, não entrega, e **aparece na tela dizendo
isso**. Nunca sai calada, nunca sai atrasada fingindo ser de hoje.

O fuso vem de `TenantProfile.timezone`, que já existe.

### Retry — que hoje não existe

O worker atual trata falha como terminal (`attempts` e `last_error` existem, mas ninguém
reprocessa; o próprio código registra isso como dívida). Com Baileys derrubando sessão, retry
deixa de ser opcional.

`Notification` ganha `next_attempt_at`. O worker reprocessa `pending` cujo horário chegou, com
backoff exponencial **limitado pela validade** — o backoff nunca agenda tentativa depois da hora
em que a mensagem já não vale.

### Freio anti-ban (só no transporte Evolution)

**Onde ele vive:** no caminho da fila (`process_pending`). A resposta do inbox é enviada de forma
síncrona na request e **não passa pelo freio** — por desenho, não por omissão: responder quem
escreveu primeiro é o tráfego mais seguro que existe, e limitá-lo só degradaria o atendimento.
O freio existe para o tráfego que **nós** iniciamos.

1. **Espaçamento** — `process_pending` hoje entrega até 50 por sweep sem pausa; com Baileys isso
   é rajada. Passa a entregar no máximo **5 por sweep, por tenant**, com **mínimo de 3s** entre
   mensagens.
2. **Teto diário de mensagens iniciadas por nós** — e a distinção que importa: **resposta a quem
   escreveu primeiro NÃO conta no teto.**
3. **Aquecimento** — número recém-conectado começa com teto menor e sobe com os dias de conexão:

| Dias desde a conexão | Teto diário de mensagens iniciadas |
|---|---|
| 1–3 | 20 |
| 4–7 | 50 |
| 8+ | 150 |

Estes são os valores de partida e são **fixos no código**. Ajustá-los é mudança de código com
justificativa, não configuração de tenant.

Batido o teto, a mensagem fica `pending` e escorre depois — se ainda estiver na validade. A
cobrança de hoje (validade = fim do dia) **expira e aparece como "não enviada: limite diário
atingido"**.

**Os tetos são fixos, não configuráveis pelo tenant** — mesma razão da banda de conferência do
Epic 8: quem ajusta o próprio limite ajusta até ele parar de proteger, e quem paga é o número do
negócio dele.

É aqui que os dois geradores de rajada do e1p ficam contidos: o **nó de WhatsApp do Funil** e a
**régua de cobrança** passam a esbarrar num freio real em vez de despejar direto no transporte.

### Nota de risco (registrada, não mitigada além do acima)

Distribuir o volume em N números e usar o canal majoritariamente para conversa reduz muito a
probabilidade de ban. **O tamanho do estrago não muda**: o número é o do negócio do cliente — o
do cartão, do site, do Google — e o Baileys viola a política da Meta independente de volume.
Isso é consequência aceita da decisão de produto, não um problema em aberto.

## 8. Infra

> **Versão da imagem:** `v2.x.y` abaixo é marcador. A versão exata é escolhida no plano de
> implementação (a mais recente estável da linha 2.x no momento) e **fixada literalmente** no
> compose. Nunca `:latest`.

```yaml
evolution:
  image: atendai/evolution-api:v2.x.y   # versão FIXA — nunca :latest
  restart: unless-stopped
  # SEM `ports:` — nada publicado, nada no Traefik. Só a rede interna.
  mem_limit: 1g
  environment:
    AUTHENTICATION_API_KEY: ${EVOLUTION_API_KEY}
    DATABASE_PROVIDER: postgresql
    DATABASE_CONNECTION_URI: postgresql://evolution_app:...@postgres:5432/evolution_db
    REDIS_URI: redis://redis:6379/0
    DEL_INSTANCE: 'false'
  volumes: [evolution_instances:/evolution/instances]

redis:
  image: redis:7-alpine
  mem_limit: 128m
  command: redis-server --maxmemory 96mb --maxmemory-policy allkeys-lru
```

**O teto de memória é a decisão de infra materializada.** Sem `mem_limit`, sessões inchando fazem
o OOM killer escolher a vítima — e ele costuma escolher o processo maior, que é o Postgres. Com o
teto, a vítima é sempre a Evolution: o WhatsApp cai, o produto continua de pé.

**Postgres:** `evolution_db` com role `evolution_app` própria, **sem acesso às tabelas do e1p**. A
Evolution é software de terceiro rodando ao lado do nosso banco; não tem por que enxergar
`tenants`, `users` ou qualquer coisa com RLS.

**Redis** é exclusivo da Evolution. O worker do e1p continua fazendo polling no Postgres — Redis
não vira dependência do produto.

**Segredo de ambiente:** `EVOLUTION_API_KEY` chega ao container por `env_file:`, nunca por
`environment: ${VAR}` — a interpolação do Compose corrompe valor com `$` literal, em silêncio
(ver `CLAUDE.md` §9).

### O volume `evolution_instances` é item de segurança

Guarda as **credenciais de sessão do WhatsApp de todos os tenants**. Duas consequências:

- **Material sensível de primeira ordem.** Quem tem esse volume fala pelo WhatsApp de todos os
  clientes. Tratamento de segredo, não de cache.
- **Entra no backup** (`docs/RUNBOOK-BACKUP-RESTORE.md`). Perdê-lo significa **todo tenant
  reescaneando QR** — incidente de suporte multiplicado por N, causado por um `docker volume rm`
  distraído.

O mesmo fato tem lado bom: é ele que torna reinício de container sobrevivível — a Evolution volta
e as sessões reconectam sem QR novo. Só a queda do lado do WhatsApp (deslogado no celular) exige
escanear de novo.

### Medir antes de prometer

A spec **não fixa** "cabem N tenants". A memória de uma sessão Baileys varia com o histórico de
conversas do número; chutar isso vira promessa. Caminho: subir com os primeiros tenants reais,
medir consumo por sessão no Kuma, derivar o teto a partir de dado. O `mem_limit` protege o
produto no intervalo em que ainda não sabemos.

**Kuma ganha:** health da Evolution, memória do container contra o teto, contagem de instâncias
desconectadas. Alerta por Telegram, como o resto.

## 9. Testes

| Alvo | Teste |
|---|---|
| Despachante | contrato percorrendo `CAPABILITIES` inteiro — transporte novo sem resposta para algum consumidor reprova |
| Parsers | payloads reais da Evolution: texto, imagem, duplicata, `@lid` sem telefone, instância desconhecida |
| Webhook | segredo errado → 401 e nada gravado; instância de A nunca escreve no tenant B (espelha `test_whatsapp_inbox_webhook.py`) |
| Validade | expira no limite exato; expirada nunca vira `sent` |
| Retry | backoff nunca agenda tentativa depois da validade |
| Freio | teto diário bate; **resposta a inbound não conta no teto**; aquecimento por dias de conexão |
| Isolamento | RLS na resolução do webhook e no envio, com testcontainers no job `cross-tenant-rls` |
| Não-regressão | a suíte atual de Meta (`test_whatsapp*.py`) passa sem edição após o refactor |

**Gate de varredura AST:** nenhum módulo pode importar `core/whatsapp/providers/*` direto — todo
mundo passa pelo despachante. É o que impede a arquitetura escolhida de degenerar em `if`
espalhado com o tempo. Mesmo idioma de `test_money_planes.py` e `test_tenancy_guard.py`.

**Evolution mockada** via httpx, como a Graph API já é hoje.

### Validação manual obrigatória

No molde de `docs/CHECKLIST-COMPROVANTE-MOBILE.md` — nenhum destes passa por CI e todos são
caminho de produção:

1. Escanear o QR num celular real e ver o status virar `connected`.
2. Derrubar a sessão de propósito (deslogar o WhatsApp Web no celular) e conferir que o e-mail de
   aviso chega.
3. Reconectar com QR novo e verificar que a fila pendente entrega o que ainda está na validade e
   marca `expired` o resto.
4. Trocar de número (`DELETE` + novo `connect`).
5. Enviar e receber mídia (imagem e PDF) pelo transporte Evolution.
6. Conferir a bandeja "Não identificados" com uma mensagem `@lid`, se reproduzível.

## 10. Migrations

A partir de `0061`:

- `tenant_profiles.whatsapp_provider`
- `public_whatsapp_instances` (tabela global)
- `whatsapp_messages.client_id` → nullable
- `notifications.expires_at` + `notifications.next_attempt_at`

## 11. Reaproveitamento explícito (não reinventar)

- **Domínio do inbox inteiro** — resolução de cliente, criação de lead, dedupe, mídia pendente,
  conversa unificada, `PURPOSE_LABELS`: tudo já existe e não muda.
- **Padrão de provider plugável** — `core/storage.py` (S3 ou Postgres, decidido por config,
  invisível para quem chama, com degradação graciosa) é exatamente esta forma, já provada no
  projeto.
- **Snapshot global para resolver antes de autenticar** — `public_integration_keys`,
  `published_pages`, `public_whatsapp_accounts`.
- **Token cifrado em repouso** — `core/token_crypto.py::EncryptedToken`.
- **Fila resiliente com isolamento de falha (IV2)** — `notifications/service.py::process_pending`
  e o `worker.py`.
- **Storage de mídia** — `core/storage.py` + módulo de Anexos.
- **Gates de varredura AST** — `test_money_planes.py`, `test_tenancy_guard.py`.

## 12. Dívidas conhecidas ao final desta feature

- **Embedded Signup da Meta** continua não existindo; o onboarding oficial segue sendo o roteiro
  manual de 7 passos para quem escolher `provider="meta"`.
- **Reconexão automática** não existe (limitação do transporte, não do produto).
- **Sem migração assistida** entre transportes: trocar significa desconectar um e conectar o
  outro, e o histórico de conversa permanece, mas o número muda para o cliente final.
- **`concurrency` do worker** segue assumindo réplica única (sem lock distribuído) — o freio por
  tenant herda essa premissa.
- **Suporte a header customizado no webhook da Evolution** precisa ser confirmado na versão
  fixada; se ausente, o segredo vira segmento de path.

## 13. Faseamento

O escopo aqui é grande demais para um único plano de implementação. Ele decompõe em quatro ondas,
na convenção já usada pelo Epic 8. **Cada onda tem valor sozinha** e é mergeável sem a seguinte.

| Onda | Entrega | Critério de pronto |
|---|---|---|
| **0 — Costura** | `core/whatsapp` vira pacote; `providers/meta.py` recebe o código de hoje; `capabilities.py`; os 9 pontos de chamada passam a receber `profile`; gate AST | A suíte atual de Meta passa **sem edição**; comportamento externo idêntico |
| **1 — Transporte** | `providers/evolution.py` (envio de texto, mídia, upload/download), infra (container, Redis, `mem_limit`, role/DB próprios), backup do volume | Envio real por instância criada à mão, com um tenant de teste |
| **2 — Onboarding** | `modules/whatsapp_session/`, tela de QR em Configurações, `whatsapp_provider`, `public_whatsapp_instances`, 4ª etapa do worker + aviso por e-mail | Tenant conecta sozinho pelo QR e envia; queda de sessão gera e-mail |
| **3 — Entrada e freio** | Webhook interno, `parse_inbound` da Evolution, bandeja "Não identificados" (`client_id` nullable), `expires_at` + `next_attempt_at` + retry, freio e aquecimento | Cliente escreve → vira lead; sessão derrubada → fila segura, entrega o válido e expira o resto |

A Onda 0 é a que carrega o risco de regressão (mexe em tudo que já funciona) e **nenhuma
funcionalidade nova** — é justamente por isso que ela vai sozinha, com a suíte existente como
juiz.
