# A jornada única do contato: um card por pessoa, um histórico por pessoa

**Data:** 2026-08-04
**Status:** Aprovado (design)
**Módulos afetados:** `crm`, `pages`, `integrations`, `whatsapp_inbox`, `funnels`, `core` (novo `phone.py`), `apps/web` (`crm`, `conversas`)

## Problema

O mesmo contato vira vários cards no Kanban. Na tela do fundador, "Flavio Kato" aparece
quatro vezes, todos com a tag `vindo-do-site`.

A causa é direta: `pages/service.py::public_submit` e `integrations/service.py::capture_lead`
chamam `crm_service.create_client` **incondicionalmente**. Nenhum dos dois procura se aquela
pessoa já existe. Cada envio de formulário cria um card novo.

Enquanto isso, `whatsapp_inbox/service.py::_get_or_create_client` **já deduplica**, procurando
por `Client.phone` antes de criar. O resultado é incoerente por porta de entrada: o mesmo
contato vira um card se chega pelo WhatsApp e N cards se chega pelo site.

Três consequências, além da poluição visual:

1. **O histórico se parte.** A conversa de junho está num card, a cobrança de julho em outro,
   a proposta de agosto num terceiro. Não existe lugar onde a história daquela pessoa esteja
   inteira.
2. **A jornada no funil não continua.** `funnels/automation.py::on_client_created` só assina
   `crm.client.created`. Um lead que volta não reentra em jornada nenhuma — e como ele virou
   um card novo, também não há como saber que ele voltou.
3. **`notes` é sobrescrito.** O texto que a pessoa preencheu no formulário vai para
   `Client.notes` via `update_client`, que substitui o valor. Não existe registro acumulado
   de "o que ela disse de cada vez", e nenhum lugar para escrever a decisão que foi tomada.

O que existe hoje e não resolve: `audit_entries` é trilha técnica (`crm.client.create`), não
narrativa — e a dívida **MNT-001**, registrada no CLAUDE.md, diz que o módulo `crm` grava
`audit.record(target='')` porque `client.id` ainda é `None` quando o `audit.record` roda logo
após o `db.add()`. A trilha do CRM aponta para lugar nenhum. Não dá para reconstruir "quem
moveu o quê" a partir dela.

## Objetivo

Uma pessoa, um card, um histórico. Quem volta complementa o que já existe — com data nova e
texto novo — em vez de abrir um card paralelo. E, ao abrir a conversa, ter do lado direito a
história inteira daquele contato: como chegou, por onde andou no funil, o que foi cobrado, o
que foi decidido.

## Escopo

**Dentro:**

- Deduplicação de lead na entrada, por telefone normalizado e e-mail, unificando as três
  portas (formulário de página, API de integração, WhatsApp).
- Tabela `client_events`: a linha do tempo narrativa do contato.
- Timeline de leitura que mescla os eventos narrativos com os fatos financeiros
  (`quotes`/`charges`), lidos na origem.
- Anotação/decisão escrita pelo dono.
- Reabertura do card quando o retorno chega e ele estava em coluna terminal.
- Reinscrição no funil de vendas, com guarda contra jornada duplicada.
- Painel de histórico na `ConversasPage` e aba "Histórico" na ficha 360°.
- Data da última interação no card do Kanban.

**Fora (decidido, não é omissão):**

- **Mesclar os cards duplicados que já existem.** Decisão do fundador: a correção vale daqui
  para frente. Os quatro "Flavio Kato" continuam quatro cards. Consequência aceita: eles
  compartilharão o mesmo `phone_key` após o backfill, e a regra de desempate da
  §"Múltiplos candidatos" define em qual deles um envio futuro cai.
- **Ligar uma conversa não identificada a um contato pela tela.** O balde "Não identificados"
  do `whatsapp_inbox` fica como está.
- **Marcar histórico como lido / badge de novidade.** O card mostra a data da última
  interação; não há estado de "visto".
- **Grupo de WhatsApp virar contato do CRM.** Decisão do fundador de 2026-08-04, mantida: o
  painel de histórico simplesmente não se aplica a conversa de grupo.
- **Constraint `UNIQUE` sobre `phone_key`.** Ver §"Múltiplos candidatos".

## Decisões

### 1. Identidade: telefone normalizado, e-mail como segundo critério

Duas pessoas são a mesma quando o telefone normalizado bate. Se o lead não trouxe telefone
(ou o telefone não normaliza), o e-mail em minúsculas é o segundo critério. CPF não entra:
raramente aparece em formulário de captura.

Esse critério é o que o `whatsapp_inbox` já usa de fato (telefone), então alinhar o site a
ele unifica as portas em vez de criar uma terceira convenção.

### 2. Histórico híbrido: narrativa persistida, dinheiro derivado

`client_events` guarda apenas os fatos **narrativos**, que hoje não têm casa nenhuma: como o
contato chegou, quando voltou e com que texto, para onde foi no Kanban, o que foi decidido.

Os fatos **financeiros** — orçamento, cobrança, pagamento — **não são copiados** para lá.
Continuam vivendo só em `quotes` e `charges`, e são lidos na hora de montar a timeline.

O motivo é o mesmo que a Onda 0 do Epic 8 gastou uma onda inteira para corrigir: valor
guardado em segundo lugar diverge do primeiro. Copiar `amount_cents` de uma cobrança para
dentro de um evento cria uma segunda versão da verdade sobre dinheiro, e a divergência só
aparece quando alguém compara. Como `quotes` e `charges` já têm `client_id` e datas, ler de
lá é barato — e traz **retroativamente** o histórico financeiro dos contatos que já existem,
sem migration de dados.

Duas alternativas foram consideradas e recusadas:

- **Tudo materializado** (cada módulo escreve seu evento, inclusive os financeiros): uma
  consulta só, mas duplica dinheiro, nasce vazia e exige que todo módulo futuro lembre de
  escrever lá.
- **Tudo derivado** (sem tabela nova, montando de `audit_entries` + `charges` + `quotes` +
  mensagens): não duplica nada e é retroativo, mas esbarra na dívida MNT-001 descrita no
  Problema — a trilha do CRM aponta para `target=''` — e não dá casa para anotação manual.

O preço da híbrida: o endpoint de leitura junta duas fontes e ordena. É complexidade contida
num lugar só.

### 3. Card que volta: fica onde está, exceto se estava em coluna terminal

Retorno de contato que está numa coluna do meio (`Em contato`, `Proposta`) **não move o
card**. Puxá-lo de volta para `Entrada` apagaria trabalho já feito.

Retorno de contato em coluna terminal — `is_won` **ou** `is_lost` — **move para a primeira
coluna ativa** e grava um evento `reopened`. Quem foi perdido e voltou sozinho é oportunidade
nova; quem já comprou e voltou é lead recorrente querendo comprar de novo (decisão explícita
do fundador). A história da venda anterior não se perde porque os eventos anteriores continuam
na timeline.

## Modelo de dados

### Tabela nova: `client_events`

Herda `TenantMixin` e `TimestampMixin`. RLS `FORCE` na migration, como toda tabela de negócio.
Por herdar `TenantMixin`, entra automaticamente na purga dinâmica de `delete_account`.

| Coluna | Tipo | Notas |
|---|---|---|
| `id` | `String(36)` PK | `default=_uuid` |
| `tenant_id` | via `TenantMixin` | |
| `client_id` | `String(36)`, indexado, **NOT NULL** | FK para `clients.id`, `ON DELETE CASCADE` |
| `kind` | `String(24)` NOT NULL | vocabulário fechado, abaixo |
| `title` | `String(140)` NOT NULL | a frase curta, congelada |
| `body` | `Text` default `""` | o texto longo (formulário, decisão escrita) |
| `actor` | `String(64)` NOT NULL | `"pagina:lead"`, `"sistema:auto-enroll"`, e-mail do usuário |
| `is_ai` | `Boolean` default `False` | Regra de Ouro nº 3 (rastro da IA) |
| `created_at` | via `TimestampMixin` | o instante do fato |

**`title` e `body` são texto congelado, não referências.** Um movimento gravado hoje diz
`"Movido de Em contato → Proposta"` como texto, não como `from_stage_id`/`to_stage_id`. Se a
coluna "Em contato" for renomeada ou arquivada depois, o histórico continua contando o que de
fato aconteceu naquele dia. É o mesmo princípio do `raw_description` de `bank_transactions`:
o registro é evidência, e evidência não se reescreve sozinha. O custo aceito é não poder
filtrar a timeline por estágio depois — ninguém pediu isso.

**Não há coluna `meta` JSON nem `ref_type`/`ref_id`.** Seriam o gancho para pendurar qualquer
coisa, e viram depósito. Se um caso concreto exigir, entra depois com nome próprio.

**Não há coluna `occurred_at` separada de `created_at`.** Para todos os seis `kind` atuais o
fato acontece no momento em que a linha é gravada. Se um dia houver importação de histórico
externo, aí sim se justifica.

`kind` — vocabulário fechado, seis valores (define ícone e cor na tela):

| `kind` | Quando | Quem grava |
|---|---|---|
| `lead_created` | contato nasce | `crm_service.create_client` |
| `lead_return` | contato conhecido volta pelo formulário/API | `crm_service.absorb_lead` |
| `stage_move` | card muda de coluna (inclusive o drag-and-drop do board, que já passa por aqui) | `crm_service.move_client` |
| `reopened` | retorno reabriu card em coluna terminal | `crm_service.absorb_lead` |
| `note` | dono escreve uma decisão | `POST /crm/clients/{id}/notes` |
| `funnel` | contato inscrito numa jornada | `funnels/automation.py` |

### Coluna nova: `clients.phone_key`

`String(16)`, nullable, **indexada**, **sem constraint de unicidade**.

`phone` continua guardando exatamente o que a pessoa digitou (`(11) 99999-8888`). `phone_key`
é a forma comparável (`5511999998888`). Mesmo par `raw_description`/`user_description` de
`bank_transactions`: o que chegou é evidência, o derivado é para a máquina.

E-mail **não** ganha coluna espelho. A comparação é `func.lower(Client.email)`. Normalizar
e-mail é um `.lower().strip()`; coluna nova se justifica onde a normalização tem regra própria
que vale congelar — o que é o caso do telefone e não é o caso do e-mail. Consequência aceita:
a busca por e-mail é um seq scan, irrelevante na escala de um profissional autônomo.

### Contrato de saída (novo em `packages/shared-types`)

```ts
interface ClientTimelineEntry {
  id: string;        // id da linha, ou sintético: "charge:{id}:paid"
  kind: "lead_created" | "lead_return" | "stage_move" | "reopened"
      | "note" | "funnel" | "quote" | "charge" | "payment";
  title: string;
  body: string;
  actor: string;
  is_ai: boolean;
  at: string;        // ISO — o instante do fato
}

interface ClientTimelineOut {
  entries: ClientTimelineEntry[];
  truncated: boolean;
}
```

O campo é `at`, não `created_at`, de propósito: para a cobrança paga o instante do fato é
`paid_at`, não quando a linha nasceu. Um nome, um significado, para as duas fontes poderem
ser ordenadas juntas.

**Limite:** cada fonte devolve no máximo 100 entradas; a mescla devolve as 100 mais recentes
por `at` decrescente; `truncated` fica `true` quando qualquer fonte bateu no teto. A tela
avisa em vez de fingir que aquilo é tudo.

## `core/phone.py` — normalização

Módulo novo, irmão de `core/validators.py` (que já hospeda `normalize_document`). Função
`normalize_br(raw: str | None) -> str | None`:

1. Só dígitos.
2. Se começa com `55` e o que sobra tem 10 ou 11 dígitos, tira o `55` (código de país
   presente).
3. Sobrou DDD (2 dígitos) + local (8 ou 9 dígitos). Qualquer outro tamanho → `None`.
4. Local com 8 dígitos começando em `6`–`9` é celular no formato pré-2016 → insere o `9`.
   Local começando em `2`–`5` é fixo → fica com 8.
5. Devolve `"55" + DDD + local`.

O passo 4 é o que evita um erro sério. A alternativa óbvia — "compara os últimos 8 dígitos" —
casaria o fixo `11 3333-4444` com o celular `11 9 3333-4444`: duas pessoas viram um card só.
Como celular e fixo se distinguem pelo primeiro dígito do número local (regra da Anatel), dá
para normalizar sem chute e sem colisão.

Entrada que não encaixa em nenhum formato (número internacional, string curta, vazio) devolve
`None`, e o contato simplesmente não é deduplicável por telefone. Não se adivinha.

## `crm_service.absorb_lead` — a porta única de entrada

```python
def absorb_lead(
    db: Session, *, tenant_id: str, actor: str, data: ClientCreate,
) -> tuple[Client, bool]:  # (client, is_new)
```

**Busca.** Por `phone_key` (quando `normalize_br(data.phone)` devolve algo); se não achar e
houver e-mail, por `func.lower(Client.email)`.

**Não achou** → `create_client(...)` como hoje, que passa a gravar também o `lead_created`.
Retorna `(client, True)`.

**Achou** → complementa, sem sobrescrever:

- Preenche apenas os campos que estavam **vazios** no card (chegou com e-mail e o card não
  tinha e-mail → preenche; o card já tinha **outro** e-mail → não toca, e a divergência
  aparece no corpo do evento).
- Grava `lead_return` com a data e o texto que a pessoa preencheu desta vez.
- Se o estágio atual é terminal (`is_won` ou `is_lost`) → move para a **primeira coluna
  ativa**, que é `_ordered_stages(db)[0]` — a mesma que `create_client` já usa como padrão —
  e grava um `reopened` separado (evento distinto de `stage_move`: é o que merece atenção).
- Emite `crm.client.returned` no barramento `core/events`.
- Retorna `(client, False)`.

### Múltiplos candidatos

`phone_key` **não é único e não deve ser**. Marido e mulher compartilham telefone, e os quatro
"Flavio Kato" que já existem passarão a compartilhar `phone_key` depois do backfill.

Regra: quando a busca devolve mais de um, `absorb_lead` **pega o mais antigo**
(`ORDER BY created_at ASC, id ASC`) e **nunca mescla os outros**. Sem essa regra, o quinto
envio do formulário cairia num card imprevisível e o histórico se partiria entre os quatro.

Nada de constraint `UNIQUE`: dedup aqui é uma busca, não uma invariante do banco — e uma
constraint quebraria a criação manual legítima de dois contatos com o mesmo telefone.

### Chamadores

- `pages/service.py::public_submit` — troca `create_client` por `absorb_lead`.
- `integrations/service.py::capture_lead` — idem.
- `whatsapp_inbox/service.py::_get_or_create_client` — passa a comparar por `phone_key` em
  vez de `Client.phone == phone` cru, e a gravar `phone_key` ao criar.

Esse terceiro item não é opcional. Sem ele o conserto fica pela metade: o site guardaria
`(11) 99999-8888`, o WhatsApp guardaria `5511999998888`, e a mesma pessoa continuaria virando
dois cards — agora por um motivo mais difícil de enxergar.

Mensagem de WhatsApp recebida **não** gera `lead_return`: a própria mensagem já é o registro,
e ela aparece na conversa ao lado da timeline.

### Texto de chegada: `notes` e evento

Na criação, o texto do formulário continua indo para `Client.notes` (comportamento atual,
`_format_fields`) **e também** para o `body` do `lead_created`. A duplicação de uma string
curta é justificada: `notes` é editável pelo dono e vira o campo de trabalho dele; o evento é
imutável e é evidência. Mesma separação de `raw_description`/`user_description`.

No **retorno**, o texto vai **apenas** para o `body` do `lead_return`. `notes` não é tocado —
era exatamente o comportamento que apagava o que o dono tinha escrito.

## Reinscrição no funil

`funnels/automation.py` passa a assinar também `crm.client.returned`, com a mesma restrição de
`source` de hoje (`AUTO_ENROLL_SOURCES = {"landing", "api"}`) e o mesmo tratamento de falha
(loga e segue, nunca derruba o publicador).

Com uma guarda que o `enroll` não tem: **se já existe uma `FunnelRun` com status `running` ou
`waiting` para aquele `client_id` naquele `funnel_id`, não inscreve de novo.** Quem já está
andando na jornada não recomeça do zero por ter preenchido o formulário duas vezes. Se a
última terminou (`done`, `failed` ou `cancelled`), inscreve, e isso grava um evento `funnel`.

A guarda fica em `automation.py`, **não** dentro de `engine.enroll`: inscrição manual pela
tela do funil continua fazendo exatamente o que o usuário mandar, sem recusar em silêncio.

## Superfícies

### Endpoints novos

- `GET /crm/clients/{client_id}/timeline` → `ClientTimelineOut`
- `POST /crm/clients/{client_id}/notes` → grava um evento `note`, devolve a entrada criada

Ambos exigem autenticação e passam pela `tenant_session` como todo o resto do CRM. Cliente
inexistente → 404 (via `crm_service.get_client`, que já levanta `CrmError(404)`).

### Componente compartilhado

`<ClientTimeline clientId={...} />` — um componente, três lugares.

**1. Painel direito da `ConversasPage`.** Hoje a tela é lista (`w-80`) + thread. Entra uma
terceira coluna com o histórico do contato daquela conversa.

**Abaixo de `lg` o painel não é coluna: é uma gaveta** aberta por um botão no cabeçalho da
conversa, sobreposta ao thread, fechando ao trocar de conversa. Uma terceira coluna fixa de
~320px num aparelho de 360px repete exatamente o incidente do PR #56 — o `AppShell` sem
breakpoint que escondeu o checkbox "marcar como paga" e fez uma conta real ser baixada sem o
dono ver.

**Conversa de grupo** (`client_id` nulo) mostra, em texto, "conversa de grupo — não ligada a
um contato do CRM". Não aparece vazia como se não houvesse nada.

**A timeline não entra no polling de 7s** da `ConversasPage`. Carrega ao selecionar a conversa
e recarrega ao gravar uma nota. Repuxar o histórico inteiro a cada 7 segundos é custo sem
ganho.

**2. Ficha 360° (`/crm/clients/:id`).** Ganha "Histórico" como **primeira** aba, antes de
Cobranças / Contratos / Orçamentos. Mesmo componente. As abas existentes ficam como estão: a
timeline conta a história, as abas dão a operação (trocar vencimento, protestar).

**3. Card do Kanban.** Passa a mostrar **"última interação: 04/08"**.

O cálculo **não** usa coluna `last_interaction_at` em `clients`. Seria um valor derivado
guardado como coluna — a forma exata do bug que a Onda 0 do Epic 8 corrigiu — e
dessincronizaria no primeiro caminho de escrita que alguém esquecesse. Em vez disso, o
endpoint do board faz **duas consultas agrupadas** (`MAX(created_at) GROUP BY client_id` sobre
`client_events` e sobre `whatsapp_messages`) e toma a maior das duas em Python. Duas queries
para o board inteiro, correto por construção, zero coluna nova.

## Migration

Uma migration, três operações:

1. `CREATE TABLE client_events` + índices + `ENABLE ROW LEVEL SECURITY` / `FORCE` + política
   de tenant, no molde das demais tabelas de negócio.
2. `ALTER TABLE clients ADD COLUMN phone_key VARCHAR(16)` + índice.
3. **Backfill** de `phone_key` a partir de `phone` para as linhas existentes.

### O backfill precisa desabilitar a RLS na sua janela

`clients` tem RLS `FORCE`. Uma migration rodando como `e1p_app` (não-superusuário, sem GUC
`app.current_tenant_id` setada) executa `UPDATE clients SET phone_key = ...` e atualiza **zero
linhas, sem erro nenhum**.

É a armadilha registrada no CLAUDE.md para a migration 0046, e que a 0066 contornou
desabilitando a RLS na própria janela do backfill. **E o SQLite dos testes unitários não pega
isso** — lá o backfill "funciona" perfeitamente.

Portanto: a migration desabilita a RLS de `clients` imediatamente antes do backfill e a
restaura logo depois, no mesmo molde da 0066.

O backfill é **aditivo e não-destrutivo**: preenche uma coluna nova, não altera `phone`, não
mescla card nenhum. Está coerente com a decisão de "só daqui para frente".

## Testes

Na ordem em que provam alguma coisa:

- **`normalize_br`**, tabela de casos. O caso que justifica a regra do 9º dígito:
  `11 3333-4444` (fixo) e `11 93333-4444` (celular) **têm que produzir chaves diferentes**.
  Mais: com e sem `+55`, com e sem máscara, 8 e 9 dígitos, entrada inválida → `None`.
- **`absorb_lead`**: lead novo cria; lead conhecido por telefone não cria; por e-mail não
  cria; campo já preenchido não é sobrescrito; grava `lead_return`; reabre de `is_won`; reabre
  de `is_lost`; **não** move quem está em coluna do meio; com múltiplos candidatos, escolhe o
  mais antigo.
- **O teste que amarra as duas portas:** contato chega pelo site como `(11) 99999-8888`,
  depois manda mensagem no WhatsApp como `5511999998888` → **um** card. Sem este teste dá para
  "consertar" o site e continuar duplicando pelo WhatsApp sem ninguém notar.
- **Reinscrição no funil:** run `running` → não cria segunda; run `done` → cria; `source`
  fora de `AUTO_ENROLL_SOURCES` → não inscreve.
- **Timeline:** mescla persistido + derivado em ordem decrescente por `at`; `truncated` fica
  `true` quando corta; cliente inexistente → 404.
- **Isolamento cross-tenant de `client_events`** (RLS `FORCE`, fail-closed sem GUC).
- **Migration contra Postgres real** — no molde de `tests/test_receipts_rls.py`
  (`pytest.mark.rls_e2e`, testcontainers, `alembic upgrade head` como `e1p_app`), com linhas
  de `clients` semeadas antes: prova que o backfill **não** foi no-op. Entra no job
  `cross-tenant-rls` do CI.
- **Front (vitest):** timeline mesclada renderiza na ordem certa; conversa de grupo mostra o
  texto de "não ligada a um contato"; nota gravada aparece sem recarregar a página.

### Aceite manual (não é coisa que vitest prove)

- **Painel de histórico em ~360px**: vira gaveta, abre pelo botão do cabeçalho, fecha ao
  trocar de conversa, e nenhum controle fica fora da área visível. É exatamente onde o PR #56
  doeu.

## Riscos

| Risco | Mitigação |
|---|---|
| Backfill do `phone_key` vira no-op silencioso por RLS | Desabilitar/restaurar RLS na janela + teste `rls_e2e` contra Postgres real com linhas semeadas |
| Dedup casa duas pessoas diferentes (fixo × celular) | Regra do 9º dígito por faixa Anatel, com teste dedicado |
| Quinto envio cai num card imprevisível (duplicados legados) | Desempate determinístico pelo mais antigo |
| Terceira coluna quebra a tela no celular | Gaveta abaixo de `lg` + aceite manual em 360px |
| Timeline pesada no polling de 7s | Timeline fora do ciclo de polling |
| Reinscrição duplica jornada no funil | Guarda de `running`/`waiting` em `automation.py` |

## Consequências para o CLAUDE.md

Ao concluir a implementação, registrar:

- A porta única `absorb_lead` e a regra de identidade (telefone normalizado → e-mail).
- Que `phone_key` é derivado e `phone` é o que a pessoa digitou.
- Que `client_events` **não** guarda dinheiro, e por quê.
- A regra de reabertura (terminal → Entrada; meio → não move).
- Que os duplicados legados **não** foram mesclados, e a regra de desempate que os governa.
