# Compartilhar comprovante do app do banco direto para Contas a Pagar

**Data:** 2026-07-28
**Status:** Aprovado (design)
**Módulos afetados:** `payables`, `attachments`, `settings`, `apps/web` (PWA)

## Problema

Quem paga uma conta pelo celular termina o pagamento dentro do app do banco, com o
comprovante na mão e o botão "Compartilhar" na tela. Hoje esse caminho morre ali: o e1p
não aparece na lista de destinos do compartilhamento, então a pessoa precisa salvar o
arquivo no aparelho, abrir o e1p, achar a conta, abrir o modal e escolher o arquivo
salvo.

Pior: o modal "Boleto / Contrato / Pix" (`PagarPage.tsx`) só oferece os slots `boleto` e
`contrato`. Não existe slot de comprovante — na prática o comprovante acaba anexado como
"contrato", corrompendo o significado do campo.

## Objetivo

Do comprovante aberto no app do banco até ele anexado na conta certa, em dois toques,
tanto em Android quanto em iPhone — e com a conta já marcada como paga no mesmo gesto.

## Escopo

**Dentro:**

- Contas a Pagar apenas.
- Android: entrada pelo share sheet nativo (PWA Share Target).
- iOS: entrada pelo share sheet nativo (app Atalhos + token de dispositivo).
- Tela de vinculação: escolher a conta numa lista curta, com opção de marcar como paga.
- Criar uma conta nova a partir do comprovante, quando não houver conta correspondente.
- Slot `comprovante` no modal de anexos existente.

**Fora (decidido, não é omissão):**

- Contas a Receber e anexos genéricos de outros módulos. O desenho não impede a extensão,
  mas nada será construído para eles agora.
- WhatsApp como porta de entrada. O `whatsapp_inbox` já baixa mídia e cria `Attachment`,
  então a extensão é barata — mas o WhatsApp Cloud API ainda não está configurado em
  produção. A arquitetura abaixo é escolhida para que essa porta entre depois sem
  retrabalho.
- OCR / sugestão automática da conta pelo valor e data do comprovante. A escolha é
  manual, numa lista curta.

## Decisões de produto

| Questão | Decisão |
|---|---|
| Plataformas | Android e iOS, ambas com entrada pelo share sheet nativo |
| Como o sistema sabe a conta | O usuário escolhe numa lista curta (sem IA, sem OCR) |
| Marcar como paga | Sim, por checkbox marcado por padrão — confirmável na tela |
| Contas listadas | Em aberto (vencidas primeiro), depois pagas dos últimos 30 dias |
| Conta inexistente | Botão para criar a conta ali mesmo, já paga e com o anexo |

## Arquitetura

O desenho separa **como o arquivo entra** de **o que se faz com ele**. Hoje as duas coisas
estão coladas no `<input type="file">` dentro do modal da conta, e é por isso que só existe
uma forma de anexar.

```
PORTAS DE ENTRADA                    BANDEJA                    VINCULAÇÃO
─────────────────                    ───────                    ──────────
Android: Share Target  ─┐
iOS: Atalho            ─┼─→  POST /payables/receipts  ─→  /comprovante/{id}
(futuro: WhatsApp)     ─┘     (Attachment em staging)     escolhe a conta
                                                                 ↓
                                                    anexo da conta + baixa

Upload manual dentro do modal da conta (fluxo de hoje) continua
gravando direto em owner_type="payable" — não passa pela bandeja,
porque a conta de destino já é conhecida.
```

### A bandeja não é tabela nova

Um comprovante recém-chegado é um `Attachment` com:

- `owner_type = "receipt_inbox"`
- `owner_id = <user_id>` (a bandeja é por usuário **por convenção nas rotas de `receipts`**, e
  isolada por tenant via RLS — não uma garantia forçada em toda a superfície do sistema; ver
  caveat abaixo)
- `label = "comprovante"`

Vincular à conta é um `UPDATE` de duas colunas: `owner_type = "payable"` e
`owner_id = <bill_id>`. **Os bytes não se movem**, nem no Postgres nem no S3, porque a
chave do storage é `tenants/{tenant_id}/attachments/{id}/{filename}` (`storage.build_key`)
e não carrega o dono do anexo. Nenhuma migration é necessária para a bandeja, e o
comprovante já nasce protegido pela RLS de `attachments` como qualquer outro arquivo.

**Caveat sobre "por usuário":** `receipts.get_staged` (usado por `link`/`new-bill`/descarte)
exige `owner_id == user_id` — só ali a bandeja é de fato por usuário. As rotas GENÉRICAS do
módulo `attachments` (`GET /attachments?owner_type=receipt_inbox&owner_id=<id>`,
`GET /attachments/{id}/download`, `DELETE /attachments/{id}`) não conhecem essa convenção; elas
só isolam por tenant (via RLS), então qualquer outro usuário do MESMO tenant consegue listar,
baixar ou apagar o comprovante em staging de um colega por ali. Isso é comportamento
PRÉ-EXISTENTE de todo o módulo `attachments` (nenhum owner_type tem checagem de dono nas rotas
genéricas), não uma regressão introduzida aqui, e o módulo compartilhado está fora do escopo
desta mudança — registrado como dívida deliberada abaixo.

Os campos `owner_type` e `label` são `String(24)`; `"receipt_inbox"` (13) e
`"comprovante"` (11) cabem sem alteração de schema.

Essa é a decisão que torna o WhatsApp uma extensão barata depois: o `whatsapp_inbox` já
cria `Attachment`; virar porta de entrada é gravar o `owner_type` da bandeja.

### Service worker sem cache

O service worker existe por um motivo só: o share sheet do Android entrega o arquivo via
`POST`, e uma SPA não tem como receber um POST sem ele. Ele **não implementa nenhuma
estratégia de cache** — sem Workbox, sem precache, sem runtime caching. Isso elimina por
construção a classe de bugs "deploy novo no ar, mas o celular mostra o app velho", que é o
principal risco de introduzir PWA num app que hoje é servido estaticamente por nginx.

O manifest torna o app instalável (pré-requisito do Share Target); o resto do app continua
sendo exatamente o mesmo SPA.

## Backend

### Endpoints

Todos em `apps/api/app/modules/payables/router.py`, reusando `attachments.service` para os
bytes.

| Rota | Comportamento |
|---|---|
| `POST /payables/receipts` | Multipart com `file`. Cria o `Attachment` em staging. `201 {id, filename, content_type, size}`. Única rota que as portas de entrada conhecem. |
| `GET /payables/receipts` | Bandeja do usuário autenticado: comprovantes em staging, mais recentes primeiro. |
| `GET /payables/receipts/candidates?q=` | Lista curta de contas. Sem `q`: abertas ordenadas por `due_date` ascendente (vencidas naturalmente no topo), seguidas das pagas com `paid_at` nos últimos 30 dias. Com `q`: filtra por `description` e `supplier` (case-insensitive) dentro do mesmo conjunto. Canceladas nunca aparecem. Teto de 100 itens. |
| `POST /payables/receipts/{id}/link` | Corpo `{bill_id, mark_paid}`. Vincula e, se pedido, dá baixa. Um único commit. |
| `POST /payables/receipts/{id}/new-bill` | Corpo `{description, amount_cents, category, supplier, due_date, mark_paid}`. Cria a conta e vincula, no mesmo commit. |
| `DELETE /payables/receipts/{id}` | Descarta da bandeja. Delega a `attachments.service.delete_attachment`. |

### Regras do upload

`POST /payables/receipts` aceita **apenas** `application/pdf`, `image/jpeg` e `image/png` —
mais restrito que o `ALLOWED_TYPES` global de `attachments/models.py`, que inclui
áudio/vídeo/`octet-stream` por causa da mídia do WhatsApp. Tipo fora da lista → `415`.

Limite de tamanho: o `MAX_BYTES` de 10 MB já existente. Excedido → `413`.

Teto de bandeja: no máximo **30** comprovantes em staging por usuário. Ao ultrapassar,
`409` com mensagem pedindo para vincular ou descartar os pendentes. Isso existe para
limitar o dano de um token de dispositivo vazado (ver Segurança).

### Regras da vinculação

`link` valida, nesta ordem:

1. O anexo existe, é do tenant (RLS já garante) e está com `owner_type = "receipt_inbox"`.
   Se já foi vinculado → `409` ("este comprovante já foi anexado").
2. O anexo pertence ao usuário autenticado (`owner_id == user_id`). Caso contrário → `404`.
3. A conta existe no tenant. Caso contrário → `404`.
4. Se a conta está `canceled` → `409`, e **nada** é gravado (nem o vínculo).

Com as validações passando, no mesmo commit:

- `owner_type = "payable"`, `owner_id = bill_id`, `label = "comprovante"`.
- Se `mark_paid` e a conta está `open` → chama `service.mark_paid`, que já cuida de
  `paid_at` e de fechar o evento na Agenda.
- Se `mark_paid` e a conta **já está paga** → ignora silenciosamente e retorna sucesso.
  Não é erro: o usuário está completando o registro de algo que já deu baixa.

`new-bill` chama o `create_payable` existente (que já injeta o evento de vencimento na
Agenda), sem recorrência, e depois vincula — tudo num commit. Se `mark_paid` for `true`, a
conta nasce e recebe a baixa no mesmo commit.

Ambas as rotas gravam entrada de auditoria, como o resto do módulo.

### Token de dispositivo

O Atalho do iOS não tem sessão de navegador; precisa de uma credencial própria. Ele guarda
essa credencial em texto claro dentro do atalho, no aparelho — o desenho parte do princípio
de que **ela vai vazar um dia**.

Nova tabela `device_tokens` (migration):

| Coluna | Tipo | Nota |
|---|---|---|
| `id` | `String(36)` | PK |
| `tenant_id` | `String(36)` | Coluna simples, para resolver a sessão de tenant |
| `user_id` | `String(36)` | Dono do token |
| `name` | `String(80)` | Ex.: "iPhone do Flávio" |
| `token_hash` | `String(64)` | sha256 do token cru, indexado. O cru nunca é gravado |
| `scope` | `String(32)` | Fixo em `"receipt_upload"` |
| `last_used_at` | `DateTime \| None` | Para a tela de gerenciamento |
| `revoked_at` | `DateTime \| None` | Revogação é soft |

A tabela é **global (sem `TenantMixin`, sem RLS)**, pela mesma razão que `users` é: o
tenant precisa ser resolvido *a partir* do token, antes de existir uma `tenant_session`
para consultar. Ela guarda apenas hash e metadado de credencial — nenhum dado de negócio —
e vale para ela a mesma regra já registrada no CLAUDE.md para `users`: nenhum módulo de
negócio a consulta via `get_db`.

O hash reusa `generate_reset_token` / `hash_token` de `core/security`, o mesmo par já usado
na recuperação de senha.

**Escopo travado.** O token autoriza **exclusivamente** `POST /payables/receipts`. Não lê
contas, não lista a bandeja, não baixa anexo, não vincula, não marca nada como pago. O pior
caso de um token vazado é um terceiro depositar arquivos na bandeja do dono — que ele vê e
descarta. Nenhum dado sai do sistema. O teto de 30 itens limita também o abuso de storage.

**Autenticação.** Uma dependency `receipt_uploader` aceita `Authorization: Bearer` (JWT,
usado por Android e web) **ou** `X-E1P-Device-Token` (iOS) e devolve o mesmo `CurrentUser`,
abrindo a `tenant_session` correspondente. O restante do código não distingue as duas
origens. Token revogado ou inexistente → `401`. Token com `scope` diferente de
`receipt_upload` → `403`.

**Gerenciamento.** `POST /settings/device-tokens` cria e retorna o token cru **uma única
vez**. `GET /settings/device-tokens` lista nome, criação, último uso e status.
`DELETE /settings/device-tokens/{id}` revoga.

## Frontend

### Arquivos novos em `apps/web/public/`

- `manifest.webmanifest` — `name: "e1p"`, `display: "standalone"`, `theme_color: "#5D44F8"`,
  `start_url: "/"`, ícones 192 e 512 (maskable), e:

```json
"share_target": {
  "action": "/compartilhar",
  "method": "POST",
  "enctype": "multipart/form-data",
  "params": {
    "files": [{ "name": "file",
      "accept": ["image/jpeg", "image/png", "application/pdf"] }]
  }
}
```

- `sw.js` — um handler `fetch`. Se for `POST` para `/compartilhar`: lê o `FormData`, guarda
  o `File` num IndexedDB efêmero sob chave aleatória (`crypto.randomUUID()`), e responde
  `Response.redirect("/compartilhar?k=<chave>", 303)`. Com `skipWaiting()` e
  `clients.claim()` para que todo deploy assuma imediatamente. Nenhuma outra requisição é
  interceptada.

- Ícones PNG 192×192 e 512×512, maskable, na identidade atual.

O registro do service worker vai no `main.tsx`, condicionado a `"serviceWorker" in navigator`.

### Rotas novas

**`/compartilhar`** — tela de trânsito, sem UI própria além de um spinner. Lê `?k=`, busca o
arquivo no IndexedDB, apaga a chave, faz `POST /payables/receipts` e redireciona
(`replace`) para `/comprovante/{id}`.

Dois caminhos de erro tratados explicitamente:

- Não autenticado: guarda a chave, manda para o login e retoma o fluxo automaticamente
  depois de entrar.
- Chave ausente no IndexedDB (usuário recarregou a página, ou o SW já foi consumido):
  mensagem explicando e link para a bandeja, em vez de tela em branco.

**`/comprovante/:id`** — a tela principal, dimensionada para o polegar:

- Topo: nome do arquivo, tamanho e miniatura (imagem) ou ícone (PDF), com ação "descartar".
- Campo de busca, ligado ao `?q=` de `candidates`.
- Lista de cartões altos (alvo de toque generoso): fornecedor/descrição, valor, vencimento
  e um chip de status — **Vencida** (vermelho), **A vencer**, **Paga**. Abertas primeiro,
  pagas recentes depois.
- Ao selecionar uma conta **em aberto**, aparece o checkbox "marcar como paga", marcado por
  padrão. Para conta já paga o checkbox não aparece.
- Botão "Anexar" fixo no rodapé.
- Abaixo dele, "Criar conta nova com este comprovante": formulário curto (descrição, valor,
  categoria, fornecedor, data), submetendo em `new-bill` com `mark_paid` marcado.
- Sucesso: toast e volta para Contas a Pagar.

### Alterações em telas existentes

- `PagarPage.tsx`: o modal "Boleto / Contrato / Pix" passa a ter três slots —
  `boleto`, `contrato` e **`comprovante`**. Essa é a correção do problema original de o
  comprovante ser guardado no campo de contrato.
- `PagarPage.tsx`: aviso discreto no topo quando a bandeja não está vazia —
  "N comprovantes aguardando" — levando à lista.
- Configurações: seção "Celular" com as instruções de instalar o PWA no Android e o passo a
  passo do atalho no iPhone, mais o gerenciamento dos tokens de dispositivo.

### O atalho do iPhone

Um atalho do app Atalhos **não pode ser gerado por código**. Ele precisa ser montado uma
vez, à mão, num iPhone, e publicado como link do iCloud para os demais instalarem. Os
passos são quatro:

1. Ação "Receber arquivos" do share sheet (aceitar imagens e PDFs).
2. "Obter conteúdo do URL" — `POST` multipart para `https://<domínio>/api/payables/receipts`,
   campo `file`, header `X-E1P-Device-Token`.
3. "Obter valor do dicionário" — chave `id`.
4. "Abrir URL" — `https://<domínio>/comprovante/<id>`.

O sistema entrega a página de instruções e o token; **publicar o link do iCloud é um
trabalho manual, feito uma vez**. Depois disso a instalação é um toque, e cada pessoa cola
o próprio token.

## Verificação

**Testes automatizados (pytest, `apps/api/tests`):**

- Upload em staging cria o `Attachment` com `owner_type="receipt_inbox"`.
- Tipo de arquivo recusado → `415`; acima de 10 MB → `413`; arquivo vazio → `422`.
  (Os três já são o comportamento de `attachments.service.create_attachment`; o teste
  confirma que a rota nova o propaga em vez de mascarar em `400`.)
- Teto de 30 itens na bandeja → `409`.
- `candidates` traz abertas ordenadas por vencimento e pagas dos últimos 30 dias, e **não**
  traz canceladas; `?q=` filtra por descrição e fornecedor.
- `link` sem `mark_paid` anexa e não muda o status.
- `link` com `mark_paid` anexa e dá baixa no mesmo commit (conta paga, `paid_at` setado,
  evento da Agenda concluído).
- `link` com `mark_paid` em conta já paga retorna sucesso sem alterar `paid_at`.
- `link` em conta cancelada → `409` e o anexo **permanece** na bandeja.
- `link` de um comprovante já vinculado → `409`.
- `new-bill` cria a conta, injeta o evento na Agenda e vincula, tudo num commit.
- Token de dispositivo: válido faz upload; revogado → `401`; escopo errado → `403`;
  `last_used_at` é atualizado.
- **Isolamento cross-tenant:** token do tenant A não vincula conta do tenant B (validado no
  Postgres real, como os demais testes de RLS).

**Testes automatizados (vitest, `apps/web`):**

- `/comprovante/:id`: renderiza a lista, filtra pela busca, mostra o checkbox só para conta
  em aberto, e chama `link` com o payload correto.
- Helper de IndexedDB: grava, lê e apaga a chave.
- `/compartilhar`: chave ausente cai no estado de erro tratado, não em tela branca.

**Validação manual (não automatizável — declarado, não omitido):**

- Share sheet do Android: exige aparelho real com o PWA instalado. Nem Playwright nem
  vitest conseguem disparar um Share Target.
- Atalho do iOS: exige iPhone real.

Ambas entram como checklist manual documentado no `docs/`, a ser executado uma vez antes de
considerar a entrega concluída.

## Riscos e mitigações

| Risco | Mitigação |
|---|---|
| Service worker servindo versão velha do app | O SW não faz cache algum; só intercepta o POST do share target. `skipWaiting` + `clients.claim` |
| Token de dispositivo vazado | Escopo travado num único endpoint de escrita, sem leitura; teto de 30 itens; revogação por dispositivo |
| Tabela `device_tokens` sem RLS | Global por necessidade (resolve o tenant), guarda só hash e metadado; mesma regra já aplicada a `users` |
| Comprovante anexado na conta errada | Lista curta e ordenada, chip de status visível, e a baixa é confirmável (checkbox), não automática |
| Bandeja acumulando pendências esquecidas | Aviso permanente em Contas a Pagar enquanto houver itens em staging |
| Tenant-mate lê/apaga comprovante em staging de outro usuário via `/attachments` genérico | Nenhuma ainda — pré-existente do módulo `attachments` (fora de escopo desta mudança); ver dívida abaixo |

## Dívida deliberada

- **Isolamento por usuário da bandeja depende de `/attachments` ser endurecido.** `receipts.get_staged`
  garante `owner_id == user_id`, mas as rotas genéricas de `attachments` (list/download/delete)
  só isolam por tenant — outro usuário do mesmo tenant alcança o comprovante em staging de um
  colega por elas. Quem endurecer `/attachments` (checagem de dono, não só de tenant) precisa
  saber que a receipts inbox depende disso para a garantia "por usuário" valer de ponta a ponta.
- Contas a Receber e anexos genéricos ficam fora; a bandeja é `owner_type`-agnóstica o
  bastante para receber outros destinos depois.
- WhatsApp como porta de entrada fica desenhado, não construído — depende das credenciais
  da Meta.
- Sem OCR ou sugestão automática da conta.
- Publicação do atalho do iOS permanece manual (limitação da plataforma, não do desenho).
