# Google Calendar — sincronização bidirecional (o sentido Google → e1p que faltava)

**Data:** 2026-08-26
**Status:** Aprovado (design)
**Escopo:** módulo `google_calendar` (novo `sync.py`), `agenda` (novo `kind`, ampliação do que já é
espelhado), `worker` (nova etapa)
**Depende de:** Story 4.1 (OAuth + push e1p→Google), em produção desde 11/07 e conectado de verdade
em produção AWS nesta sessão (26/08)

---

## Problema

A Story 4.1 entregou o sentido **e1p → Google**: criar/remarcar/cancelar um evento na Agenda do e1p
já propaga para o Google Calendar do tenant conectado (`create_meet_event`/`patch_meet_event`/
`delete_meet_event` em `google_calendar/service.py`, chamados por `agenda/service.py::create_event`/
`reschedule_event`/`cancel_event`). Isso já está em produção e funcionando — validado nesta sessão
criando um evento "Visita" no e1p e vendo o espelho aparecer no Google Calendar do celular.

**Não existe o sentido contrário.** Um evento criado direto no Google Calendar (do jeito rápido, no
celular, que é como o dono realmente agenda no dia a dia) nunca aparece na Agenda do e1p. Não há
polling, não há webhook, não há nada que leia o que mudou do lado do Google. Testado nesta sessão:
criar um evento "Visita" direto no app do Google Calendar não produziu nada no e1p.

Isso contradiz o motivo de existir da integração: "ao agendar o contato tudo possa ficar integrado"
só vale hoje se o agendamento nascer no e1p. Metade do fluxo real do dono (marcar pelo celular,
fora do e1p) fica invisível para o sistema — inclusive para a checagem de conflito de horário, que
é justamente o que a Agenda existe para garantir.

⚠️ **Nota sobre o CLAUDE.md:** o roadmap (§6) ainda lista "Integração Google (Meet/Calendar) —
PENDENTE" e a Story 4.1 documenta "reschedule/cancel NÃO sincronizam com o Google" como dívida
aceita. As duas afirmações estão **desatualizadas** — o código real já sincroniza reschedule/cancel
(verificado por leitura direta em `agenda/service.py:239-242` e `:278-281`). É a mesma classe de
dívida documental que o próprio CLAUDE.md descreve em outros lugares (§5, passo 4): a funcionalidade
existe, a entrada não foi atualizada. Corrigir essas duas linhas do CLAUDE.md faz parte desta
entrega.

---

## Objetivo

Que um compromisso criado, remarcado ou cancelado em **qualquer um dos dois lados** (e1p ou Google
Calendar) apareça correto no outro, com atraso de no máximo poucos minutos — sem exigir que o dono
mude o jeito como já agenda hoje.

---

## Decisões de escopo (confirmadas com o dono)

| Pergunta | Decisão |
|---|---|
| Direção | **Bidirecional completo** — criar/editar/cancelar em qualquer lado reflete no outro |
| Quais eventos do Google entram no e1p | **Todos** — inclusive pessoais (aniversário, etc.), sem filtro |
| Velocidade aceitável | **Poucos minutos** — via job periódico, não push/webhook |
| Cancelamento | **Propaga sempre nos dois sentidos** |
| Vínculo ao cliente do CRM para evento vindo do Google | **Manual** — o dono vincula depois, sem adivinhação automática |
| O que sai do e1p para o Google | **Sem mudança de critério de negócio** — continua só compromisso com horário marcado (reunião/atendimento/audiência/bloqueio); vencimento de conta/cobrança/prazo **não** vai para o Google pessoal do dono |

---

## Modelo de dados

Tudo aditivo — nenhuma coluna ou contrato existente muda de significado.

### `GoogleCredential.sync_token` (novo campo, `Text | None`)

O cursor de sincronização incremental do Google (`nextSyncToken`), um por tenant, na mesma linha
que já guarda `access_token`/`refresh_token`. `NULL` = nunca sincronizado (ou o token expirou e foi
limpo) — dispara sync completo limitado por janela na próxima rodada.

### `AgendaEvent.KIND_GOOGLE = "google"` (novo `kind`)

Para eventos que nasceram no Google e não têm nenhum tipo de negócio do e1p (não é reunião com
cliente, não é cobrança, não é prazo). Entra em `ALL_KINDS` (validação de schema) e em
`OCCUPYING_KINDS` (`agenda/models.py:33`) — ocupa horário de verdade na agenda do dono, então
participa da checagem de conflito como qualquer outro compromisso.

### Índice único `(tenant_id, google_event_id)` onde `google_event_id IS NOT NULL`

Não existe hoje. Enquanto `google_event_id` só era escrito pelo próprio e1p (push), a unicidade era
garantida pela lógica de criação (um evento e1p gera no máximo um espelho). Agora que o sync
incremental pode reprocessar uma página em caso de retry/erro parcial, uma segunda escrita do mesmo
`google_event_id` tem que ser rejeitada em vez de duplicar o evento — mesmo padrão de idempotência
já usado em `bank_transactions` (`(tenant_id, source, origin_id) WHERE origin_id IS NOT NULL`).

### Migration

Número reservado: **`0081`** (head atual confirmado: `0080_funnel_run_trigger_notes.py`).
`ALTER TABLE google_credentials ADD COLUMN sync_token TEXT NULL` + `ALTER TABLE agenda_events ADD
COLUMN` nenhuma (kind já é `String(24)`, "google" cabe) + `CREATE UNIQUE INDEX
ix_agenda_events_tenant_google_event_id ON agenda_events (tenant_id, google_event_id) WHERE
google_event_id IS NOT NULL`. Sem `UPDATE`/backfill — DDL puro, a armadilha do `FORCE RLS`
(§6.0/§Onda 2 do CLAUDE.md) não se aplica.

---

## O mecanismo: sync incremental via `syncToken`

Duas abordagens foram consideradas:

1. **`syncToken` do Google (escolhida)** — a Calendar API tem suporte nativo a sync incremental:
   guardamos o cursor, e cada rodada seguinte pede só "o que mudou desde a última vez", inclusive
   **exclusões** (o item volta com `status: "cancelled"`). Barato — a maioria das rodadas devolve
   uma resposta pequena ou vazia.
2. **Comparar a listagem inteira a cada rodada** — mais simples de escrever, mas cara (rebusca tudo
   sempre) e não detecta exclusão de forma confiável sem manter um inventário próprio para
   comparar.

Primeira rodada (sem `sync_token` ainda, ou depois de um HTTP 410 do Google avisando que o token
expirou): sync completo, limitado à janela **30 dias atrás → 6 meses à frente**
(`timeMin`/`timeMax`), com `singleEvents=true` (o Google expande recorrência em ocorrências
individuais — não precisamos entender `RRULE`). No fim da última página, o Google devolve
`nextSyncToken`, que é salvo. Rodadas seguintes usam só `syncToken` (sem `timeMin`/`timeMax` — a
API não permite combinar os dois).

⚠️ **Risco a validar em ambiente real:** não há como testar contra a API real do Google neste
sandbox (mesma limitação já registrada na Story 4.1 para o fluxo de OAuth ponta-a-ponta). A
combinação "primeira chamada com `timeMin`/`timeMax` e sem `syncToken` ainda retorna
`nextSyncToken` válido" é o comportamento documentado da API, mas fica como validação manual
obrigatória pós-deploy, com o tenant real já conectado.

---

## Fluxo de sincronização (Google → e1p)

Novo módulo `apps/api/app/modules/google_calendar/sync.py`, função `pull_changes(db, tenant_id) ->
int` (retorna quantos eventos foram tocados, para o contador do worker).

1. Busca `GoogleCredential` do tenant. Sem credencial → retorna `0` sem nenhuma chamada HTTP.
2. Renova o `access_token` se necessário (reusa `_ensure_fresh_token`, já existe em
   `google_calendar/service.py`). Sem token válido → loga e retorna `0` (mesmo princípio de
   robustez de `create_meet_event`: falha de integração externa nunca derruba o worker).
3. Chama `GET .../calendars/primary/events` com `singleEvents=true` e:
   - `syncToken=<cred.sync_token>` se existir; ou
   - `timeMin`/`timeMax` da janela inicial, se não existir.
4. Em caso de **HTTP 410** (token de sync expirado): limpa `cred.sync_token`, refaz a chamada como
   sync completo (item anterior) na mesma execução — autocorreção, sem esperar a próxima rodada.
5. Para cada item da resposta (paginando por `nextPageToken` até acabar):
   - **`status == "cancelled"`** → busca `AgendaEvent` local por `(tenant_id, google_event_id)`. Se
     existir e não estiver já em estado terminal, marca `status = STATUS_CANCELLED`. **Não** chama
     `delete_meet_event` — isso seria eco (o Google está avisando que já cancelou; tentar cancelar
     de novo no Google é chamada desperdiçada na melhor hipótese).
   - **Novo** (sem `AgendaEvent` local com esse `google_event_id`) → cria `AgendaEvent(kind=
     KIND_GOOGLE, source="google", client_id=None, ...)`, mapeando `summary→title`,
     `start/end→starts_at/ends_at` (evento de dia inteiro do Google vem em `date`, não `dateTime` →
     `all_day=True`), `location`, `description`, `hangoutLink→meeting_url`,
     `attendees[].email→guests`.
   - **Já existe** → atualiza os mesmos campos. **Não** chama `patch_meet_event` de volta (mesmo
     motivo do eco acima).
6. Ao final (só quando a última página foi processada com sucesso), salva `cred.sync_token =
   data["nextSyncToken"]` e commita.

Uma falha em qualquer ponto (rede, token, quota) é capturada, logada, e a função retorna `0` sem
alterar `sync_token` — a próxima rodada tenta de novo com o mesmo cursor (ou sem cursor, se nunca
chegou a salvar um), então nada se perde.

---

## O que já existe (push e1p → Google) e o que muda

**Não muda o mecanismo.** `create_event`/`reschedule_event`/`cancel_event` continuam chamando
`create_meet_event`/`patch_meet_event`/`delete_meet_event` exatamente como hoje.

**Muda o critério de quais `kind` são espelhados.** Hoje é `MEET_KINDS = {"reuniao", "atendimento",
"audiencia"}` (`google_calendar/service.py:43`), usado tanto para decidir *se* espelha quanto para
decidir *se gera Meet*. Os dois deixam de ser o mesmo conjunto:

- **`PUSHED_KINDS = MEET_KINDS | {"bloqueio"}`** — decide se o evento é espelhado no Google.
- **`MEET_KINDS`** continua decidindo só se a chamada pede `conferenceData` (gera link de Meet).
  Bloqueio de horário não é reunião — vira evento simples no Google, sem Meet.

`create_meet_event` ganha um parâmetro implícito: monta o corpo da requisição com `conferenceData`
apenas quando `event.kind in MEET_KINDS`; para os demais `kind` de `PUSHED_KINDS`, omite esse bloco
do payload. `agenda/service.py` troca a condição `event.kind in MEET_KINDS` por `event.kind in
PUSHED_KINDS` nos três pontos de chamada (create/reschedule/cancel).

Cobrança, conta a pagar e prazo continuam **fora** — não vão para o Google pessoal do dono (decisão
confirmada).

---

## Worker — nova etapa

`app/worker.py::run_sweep` ganha uma **Etapa 7**, no mesmo molde das seis existentes: sessão própria
por tenant, falha isolada (não trava as outras etapas nem os outros tenants), contador próprio no
dicionário de resultado (`google_events_synced`).

```python
try:
    with tenant_session_factory(tenant_id) as db:
        synced = google_calendar_sync.pull_changes(db, tenant_id=tenant_id)
    result["google_events_synced"] += synced
except Exception as exc:  # noqa: BLE001 — idem: isola a falha por tenant (IV2)
    logger.exception("[worker] sync do google calendar falhou tenant=%s", tenant_id)
    result["errors"].append(
        {"tenant_id": tenant_id, "stage": "google_calendar_sync", "error": str(exc)}
    )
```

Roda a cada sweep (hoje a cada 60s, `worker_tick_interval_seconds`). Não precisa de throttle
próprio: para um tenant sem `GoogleCredential`, a função retorna `0` sem chamada HTTP (custo zero);
para um tenant conectado com `sync_token` válido, a chamada incremental é barata mesmo sem nada
para sincronizar. Rodar a cada minuto fica **mais rápido** que o "poucos minutos" pedido, sem custo
extra de estado (nada de coluna `last_synced_at` para throttle manual).

---

## Interface

Nenhuma tela nova. O evento importado aparece na Agenda (mês/semana/dia) com `kind="google"`,
ganhando cor/rótulo próprios — mesmo padrão que reunião/atendimento/cobrança já têm hoje.

Vincular a um cliente do CRM: **já existe** (`PATCH /agenda/events/{id}` já aceita `client_id`,
`agenda/schemas.py:77`; `update_event` já grava quando informado). O trabalho aqui é conferir que o
modal de detalhe do evento no frontend mostra o seletor de cliente também para `kind="google"` (hoje
pode estar condicionado a outros `kind` — checar `AgendaPage.tsx` e ajustar se for o caso).

---

## Tratamento de erros e casos de borda

- **Token revogado/sem refresh possível** → a etapa loga e pula o tenant naquela rodada; tenta de
  novo na próxima.
- **Evento em que o dono é só convidado (não o organizador)** → sincroniza igual, nesta primeira
  versão. Diferenciar "dono vs. convidado" fica de fora por YAGNI — pode virar refinamento se
  incomodar na prática.
- **Corrida entre push e pull** → o pull nunca re-propaga o que acabou de ler (item 5 do fluxo
  acima), e o push sempre grava o `google_event_id` local antes de qualquer pull rodar. Sem loop.
  Reaplicar o mesmo dado duas vezes é inofensivo (idempotente).
- **Evento cancelado no e1p e no Google ao mesmo tempo** (raríssimo, dado o intervalo de minutos) →
  os dois lados convergem para `cancelled`/apagado; não há dado divergente possível de sobrar.

---

## Gates

- `apps/api/tests/test_google_calendar_sync.py` (novo): mocka `httpx` (mesmo padrão de
  `test_google_calendar.py` existente) — sync completo inicial grava `sync_token`; sync
  incremental usa o token salvo; item cancelado marca `AgendaEvent` local sem chamar
  `delete_meet_event` (assert not called); item novo cria `AgendaEvent(kind="google")` sem
  `client_id`; item já existente atualiza sem chamar `patch_meet_event` (assert not called); HTTP
  410 limpa o `sync_token` e refaz como sync completo; falha de rede retorna `0` e não altera
  `sync_token`.
- `apps/api/tests/test_agenda.py` — caso novo: criar `bloqueio` com Google conectado chama
  `create_meet_event` **sem** `conferenceData` no corpo (mock assert do payload).
  `test_google_calendar.py` — ajusta os testes existentes de `create_meet_event` para cobrir o
  novo parâmetro de Meet condicional.
- Migration `0081` validada contra Postgres real (mesma disciplina de qualquer migration com
  índice novo) — `rls_e2e`.
- `python -m pytest`, `ruff check .`, `pnpm --filter @e1p/web typecheck` — os três de sempre.
- **Validação manual pós-deploy, com o tenant já conectado em produção** (mesma categoria que a
  Story 4.1 já registrou para o OAuth ponta-a-ponta): criar evento no Google Calendar do celular,
  aguardar até 1 minuto, confirmar que aparece na Agenda do e1p; cancelar no e1p, confirmar que
  some do Google; cancelar no Google, confirmar que aparece cancelado no e1p.

---

## Riscos e dívidas conhecidas

- **A combinação `timeMin`/`timeMax` + `nextSyncToken` na primeira chamada** é o único ponto deste
  design sem cobertura de teste possível neste ambiente (API real do Google). Se o comportamento
  divergir do esperado, o sintoma será "primeiro sync não estabelece `sync_token`, todo sweep
  seguinte volta a fazer sync completo" — caro, mas não incorreto (idempotente). Corrigível sem
  mudança de schema.
- **`whatsapp_inbox`, `platform`, `agenda` e outros módulos que hoje leem `kind` explicitamente**
  (ex.: `next_event_map`, filtros de tela) não foram auditados um a um para confirmar que tratam
  `kind="google"` de forma neutra (não é `cobranca_receber` nem nenhum tipo com lógica de dinheiro
  associada) — verificar antes do merge, não assumido aqui.
- **Sem diferenciação dono vs. convidado** — todo evento do Google entra igual, mesmo quando o
  dono só foi convidado por outra pessoa. Aceito por decisão do dono do produto (item "todo evento
  entra").
- **Sem teto de eventos por sync completo inicial** — se o Google Calendar tiver um volume muito
  grande de eventos na janela de 6 meses à frente / 30 dias atrás, a primeira rodada pagina até o
  fim antes de salvar o `sync_token`; não há corte de segurança. Como a Calendar API pagina
  nativamente e a função processa página a página, o risco é de tempo de execução, não de estouro
  de memória — aceitável para o volume esperado (uma pessoa, um calendário).

---

## Fora de escopo

| Fora | Por quê |
|---|---|
| Vínculo automático a cliente do CRM por e-mail/nome do convidado | Decisão do dono: vínculo manual, para não arriscar vincular errado |
| Push/webhook do Google (`watch` channels) | Decisão do dono: latência de minutos já resolve; webhook exige renovação de canal a cada poucos dias e mais tratamento de erro |
| Enviar vencimento de cobrança/conta a pagar/prazo para o Google pessoal | Decisão do dono: só compromisso com horário marcado |
| Diferenciar organizador vs. convidado no evento do Google | Ninguém pediu; YAGNI |
| Suporte a múltiplos calendários do Google (hoje só `primary`) | Fora do que a Story 4.1 já construiu; ampliar é trabalho novo, não pedido aqui |
| Corrigir as duas linhas desatualizadas do CLAUDE.md sobre esta integração | Entra como parte da implementação (é atualização de documentação, não código), mas não é decisão de design |
