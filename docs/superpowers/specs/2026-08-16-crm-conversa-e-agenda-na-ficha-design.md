# A ficha do contato passa a falar com Conversas e com a Agenda

**Data:** 2026-08-16
**Status:** aprovado no brainstorming, aguardando plano de implementação

## O problema

O card do Kanban leva a uma ficha 360° que sabe de cobrança, contrato, orçamento, documento
jurídico e funil — e não sabe de duas coisas que o dono usa o dia inteiro: a **conversa** que ele
está tendo com aquela pessoa e o **compromisso** que ele marcou com ela.

Os dois lados não estão no mesmo estágio:

| Elo | Hoje |
|---|---|
| contato ↔ conversa | **Existe.** `whatsapp_chats.client_id` já aponta. A tela de Conversas até mostra o `ClientTimeline` do CRM na coluna da direita. Falta o caminho de volta: da ficha para a conversa. |
| contato ↔ compromisso | **Não existe.** `agenda_events` não tem coluna de cliente. O nome que a Agenda mostra hoje é derivado da cobrança, por um caminho polimórfico via `external_ref`. |

Consequência prática: para saber "o que está combinado com essa pessoa", o dono abre três telas e
junta na cabeça. E no board ele não tem como ver quem está esperando resposta nem quem está
parado no funil sem próximo passo marcado.

## O que vamos construir

**Sinal no card, conteúdo na ficha.**

Na ficha (`/crm/clients/:id`), duas seções novas ao lado das que já existem:

- **Conversa** — janela. Mostra as últimas mensagens e leva para Conversas para responder.
- **Agenda** — ativa. Mostra os próximos compromissos e permite marcar um novo dali mesmo.

No card do board (`/crm`), dois sinais:

- ponto de **mensagem esperando resposta**, ao lado do nome;
- uma linha que diz o **próximo compromisso** ou, na falta dele, que **não há próximo passo
  marcado**.

## Decisões tomadas

| Decisão | Escolha | Por quê |
|---|---|---|
| Onde a integração mora | Sinal no card, conteúdo na ficha | O card tem 288px; cabe alerta, não conteúdo. |
| Profundidade | Conversa é janela; Agenda é ativa | Responder WhatsApp tem janela de 24h e templates — regra que não pode viver em dois lugares. Marcar compromisso é o gesto que hoje não existe em lugar nenhum. |
| Conversa vs. Histórico | Lado a lado | Histórico = a narrativa (chegou, moveu, pagou, escreveu). Conversa = o teor, as falas. |
| Compromisso passado | Vai para o Histórico, não para o bloco | O bloco responde uma pergunta só: o que está marcado. O passado é assunto da linha do tempo, que já é read model cross-módulo. |
| Vínculo Agenda↔contato | Coluna `client_id` própria | `external_ref` já é ponteiro polimórfico lido conforme o `kind`. Sobrecarregar viraria `WHERE source='crm' AND external_ref=X`, sem índice e sem garantia. |
| Cardinalidade | Um cliente por evento | YAGNI. Reunião com dois clientes é rara e o campo `guests` já existe. |
| Leitura | Cada módulo continua dono | Nenhuma regra de negócio duplicada. Fachada no CRM fica como otimização futura, se as requests doerem. |
| Limpeza do router da Agenda | Entra nesta onda | O código polimórfico morre junto com o motivo dele existir — com teste comparando os dois caminhos antes da remoção. |
| Entrega | Duas ondas | Onda 1 não toca no banco e pode ir para prod em dias. |

### Abordagens descartadas

**Fachada no CRM** (`GET /crm/clients/{id}/panorama`, tudo num payload). Uma request em vez de
oito, e há precedente — `crm/timeline.py` já lê `quotes` e `receivables` na origem. Descartada
por ora porque o CRM passaria a saber formatar conversa de WhatsApp, e aí janela de 24h, grupo
que não é cliente e `@lid` não resolvido ganhariam um segundo lugar para dar errado.
Reconsiderar se as 8 requests da ficha doerem.

**Compromisso como entrada da linha do tempo, sem bloco.** Mais barato, mas o bloco precisa ser
ativo (marcar) e o dono quer conversa separada do Histórico.

---

# Onda 1 — Conversa (sem migration)

## API

`GET /whatsapp-conversations` ganha o filtro opcional `client_id`. A implementação segue em
`whatsapp_inbox/service.py`: é o módulo dono do vocabulário de conversa.

Função nova no mesmo módulo, para o board:

```python
def unread_client_ids(db: Session) -> set[str]:
    """Contatos com mensagem esperando resposta, para o card do Kanban."""
```

Agregada, uma query para o board inteiro — no molde do `crm_service.last_interaction_map`, que
existe justamente porque valor derivado guardado dessincroniza.

**Não** dá para reusar `list_conversations` aqui: ela carrega todas as mensagens do tenant em
memória para achar a última de cada chat. A tela de Conversas tolera isso; o board, aberto a cada
navegação, não.

### O risco desta onda: duas definições de "não lida"

A regra vive hoje inline dentro de `list_conversations`:

```python
unread = (
    last_msg.direction == DIRECTION_IN
    and (chat.last_read_at is None or last_msg.created_at > chat.last_read_at)
)
```

Um agregado à parte cria uma segunda cópia dela. Elas divergem no primeiro ajuste que alguém
fizer em uma só, e o sintoma é silencioso: o card diz "esperando resposta" com a caixa de entrada
limpa.

**Guarda:** as duas funções ficam no mesmo módulo, adjacentes, e um teste afirma que concordam
sobre a mesma fixture:

```python
assert unread_client_ids(db) == {
    c["client_id"] for c in list_conversations(db, tenant_id=t)
    if c["unread"] and c["client_id"]
}
```

A fixture precisa cobrir: chat sem `last_read_at`, chat lido depois da última mensagem, chat cuja
última mensagem é `out`, grupo (que nunca tem `client_id`), e dois chats apontando para o mesmo
cliente.

## Ficha — bloco "Conversa"

Nova seção em `ClientDetailPage`, usando o `<Section>` que já existe no arquivo. Últimas ~5
mensagens em bolhas compactas e um botão que abre a conversa no lugar certo.

**Um contato pode ter mais de uma conversa.** `whatsapp_chats.client_id` não tem unique, e o
comentário no modelo explica: a mesma pessoa pode aparecer via `@lid` e via telefone, cada uma
virando chat próprio. O bloco mostra a conversa **mais recente** por inteiro e, havendo outra, uma
linha discreta "+1 outra conversa" que leva para Conversas. Fingir que é sempre uma esconderia
mensagem do dono.

Estado vazio: "Nenhuma conversa no WhatsApp." Sem botão de "iniciar conversa" — a janela de 24h da
Meta não permite abrir conversa do nada, e um botão que sempre falha é pior que nenhum.

O bloco degrada como o `ClientTimeline` já degrada: falha de carregamento vira aviso, não derruba
a ficha.

## Deep-link para a conversa

Hoje `ConversasPage` guarda o chat selecionado em `useState` — não há como apontar para uma
conversa de fora.

- Rota nova: `/conversas/:chatId`.
- `/conversas` continua válida (lista sem seleção), que é o que o menu lateral usa.
- `chatId` inexistente ou de outro tenant: cai na lista com aviso, não em tela branca.

Ganho colateral: o botão voltar do navegador e o link compartilhável passam a funcionar em
Conversas, o que hoje não acontece.

## Card do board — o ponto

`build_board` passa a chamar `unread_client_ids`. `BoardClient` ganha `unread: bool`.

Na tela: ponto ao lado do nome, mesma linguagem visual da lista de Conversas. Custo zero de
altura — o card não cresce nesta onda.

## Testes da Onda 1

| Camada | O que prova |
|---|---|
| API | Filtro `client_id` na lista de conversas; grupo nunca aparece em conversa de cliente. |
| API | **Paridade de "não lida"** entre `unread_client_ids` e `list_conversations` (fixture acima). |
| API | `build_board` devolve `unread` correto, e o número de queries não cresce com a quantidade de cards. |
| Web | Bloco de Conversa: com mensagens, vazio, com duas conversas, e com falha de rede. |
| Web | Rota `/conversas/:chatId` seleciona a conversa; id inválido cai na lista. |
| Web | Ponto no card aparece e some conforme o `unread`. |

---

# Onda 2 — Agenda (com migration)

## Migration 0078

```
agenda_events.client_id  String(36)  nullable  indexed
```

**Sem FK**, seguindo o precedente de `whatsapp_chats.client_id`, que também é `String(36)` solto:
a Agenda não deve ganhar dependência dura da tabela do CRM. Nullable é o caso normal — bloqueio de
horário, prazo interno e conta a pagar não têm cliente.

Nada muda em RLS: `agenda_events` já herda `TenantMixin` e a política é da tabela, não da coluna.

### Backfill

Todo evento `kind='cobranca_receber'` guarda no `external_ref` o id da cobrança, e a cobrança sabe
de quem é. Um `UPDATE ... FROM charges` preenche o passado inteiro: na abertura, a ficha de um
cliente antigo já mostra o histórico de compromissos sem nenhuma importação. Mesmo ganho retroativo
que o `crm/timeline.py` descreve ao ler na origem.

> ⚠️ **A armadilha da 0068 se aplica aqui, inteira.** O backfill roda como o papel dono
> não-superusuário `e1p_app`, **sem** a GUC `app.current_tenant_id`. Sob `FORCE ROW LEVEL
> SECURITY` o `UPDATE` seria filtrado a **zero linhas, em silêncio** — e o sintoma em produção não
> seria erro de deploy, seria "a ficha não mostra compromisso nenhum". A RLS é desabilitada nas
> **duas** tabelas na janela do backfill (`agenda_events` porque é o alvo, `charges` porque é a
> fonte da subconsulta) e restaurada com ENABLE + FORCE logo depois. Mesmo padrão das 0046, 0066,
> 0067 e 0068. DDL é transacional no Postgres e a migration roda offline, então não há janela de
> exposição.

O teste da migration segue o formato de `test_migration_0068_stage_order_rls.py`, que existe
exatamente para provar que o `UPDATE` não foi filtrado a zero linhas.

## API

- `client_id` entra em `EventCreate`, `EventUpdate` e `EventOut`.
- `GET /agenda/events` ganha o filtro `client_id`.
- `receivables/service.py` passa a gravar `client_id` no evento que cria.
- Função nova em `agenda/service.py`, para o board:

```python
def next_event_map(db: Session) -> dict[str, AgendaEvent]:
    """Próximo compromisso por contato, para o card do Kanban."""
```

Agregada, uma query para o board inteiro. Ignora `status='cancelled'`.

### Limpeza do router

`agenda/router.py` hoje reconstrói o nome do cliente juntando `external_ref` de dois `kind`s
diferentes, buscando cobranças e montando mapa. Com `client_id` populado isso vira um join direto.

**Ordem obrigatória:** primeiro um teste que roda os dois caminhos sobre a mesma base e afirma que
produzem o mesmo `client_name`; só depois a remoção do caminho antigo. Sem esse teste, um backfill
que errasse uma linha faria a Agenda perder nome de cliente que ela hoje mostra — e ninguém
perceberia.

## Ficha — bloco "Agenda"

Seção nova com os **próximos** compromissos e o botão **"Marcar com este cliente"**.

O modal não é escrito do zero: `NewEventModal` já existe dentro de `AgendaPage.tsx`, **com o aviso
de conflito de horário já resolvido**. Ele é extraído para `features/agenda/NewEventModal.tsx` e
passa a receber `clientId` opcional. `AgendaPage.tsx` tem 723 linhas e o modal é ~175 delas — a
extração deixa os dois arquivos menores e faz a checagem de conflito continuar existindo em um
lugar só.

Estado vazio: "Nenhum compromisso marcado", com o botão logo abaixo. É o estado mais importante do
bloco — é ele que revela o contato que vai esfriar.

## Compromisso passado vai para o Histórico

`crm/timeline.py` ganha uma quarta fonte, ao lado de `facts`, `charges` e `quotes`: eventos de
agenda já realizados, lidos na origem por `client_id`. Segue o mesmo `LIMITE_POR_FONTE` e a mesma
regra de `truncated`.

`kind` novo na saída — `agenda` — que precisa de entrada no mapa `APARENCIA` do `ClientTimeline`,
porque o vocabulário é fechado e um `kind` sem tratamento cai no ícone neutro.

> ⚠️ **Conserto de fuso, obrigatório nesta onda.** `ClientTimeline.quando()` formata com
> `toLocaleString("pt-BR", ...)` **sem `timeZone`** — ou seja, no fuso do navegador. O comentário
> ali diz "mesma convenção da ConversasPage", mas a ConversasPage foi corrigida exatamente disso: o
> mesmo histórico quebrava os dias em pontos diferentes conforme a máquina que abrisse a tela.
> Colocar compromissos com horário nessa lista sem consertar faria "reunião às 14h" aparecer em
> hora errada. Passa a usar `useFuso()` + `lib/datetime`, como o resto do sistema.

## Card do board — a linha do próximo passo

`BoardClient` ganha `next_event_at` e `next_event_title`. Na tela, **uma linha só**: diz o próximo
compromisso quando existe, e "sem próximo passo" quando não — são estados opostos da mesma
pergunta e nunca aparecem juntos.

O card fica com nome + selo de origem + tags + três linhas de rodapé ("na etapa desde", "última
interação", próximo passo).

> ⚠️ **Fuso.** "terça 14h" e a própria fronteira entre passado e futuro são calculados no fuso do
> tenant — `hoje_do_tenant(db)` no back, `useFuso()` no front. É a classe de regressão que já
> voltou três vezes neste repo. A suíte tem de rodar com `TZ=UTC` para o teste ter valor.

## Testes da Onda 2

| Camada | O que prova |
|---|---|
| Migration | Backfill sob RLS preencheu linhas (formato do `test_migration_0068_stage_order_rls.py`). |
| Migration | Evento sem cobrança e conta a pagar continuam com `client_id` nulo. |
| API | Filtro `client_id`; evento cancelado fora do `next_event_map`. |
| API | **Paridade do router**: derivação antiga e join novo produzem o mesmo `client_name` — roda antes da remoção. |
| API | `next_event_map` respeita o fuso do tenant na fronteira passado/futuro, com `TZ=UTC`. |
| API | Linha do tempo inclui compromisso realizado e respeita `LIMITE_POR_FONTE`/`truncated`. |
| Web | Bloco Agenda: com próximos, vazio, e criando compromisso (inclusive o caminho de conflito). |
| Web | `NewEventModal` extraído continua funcionando na AgendaPage — sem regressão. |
| Web | `ClientTimeline` formata no fuso do tenant. |
| E2E 360px | `crm-360.spec.ts`: o card cresceu, então volta para a régua — medindo `boundingBox`, não procurando classe CSS. |

---

## Riscos, em ordem

1. **Duas definições de "não lida"** (Onda 1). Divergência silenciosa. Mitigado pelo teste de
   paridade.
2. **Backfill filtrado a zero linhas pela RLS** (Onda 2). Falha silenciosa em produção, com
   deploy verde. Mitigado pela janela de RLS e pelo teste de migration.
3. **Limpeza do router antes de o backfill estar provado** (Onda 2). Perda de informação que hoje
   funciona. Mitigado pela ordem obrigatória: teste de paridade primeiro, remoção depois.
4. **Fuso no card e na linha do tempo.** Classe reincidente neste repo. Mitigado por rodar a
   suíte com `TZ=UTC`.
5. **Card mais alto** (Onda 2). Três linhas de rodapé em 288px. Mitigado pela régua de 360px.

## O que fica de fora

- Responder WhatsApp de dentro da ficha (janela de 24h e templates seguem só em Conversas).
- Fachada `panorama` no CRM.
- Evento com mais de um cliente.
- Sinal de conversa em card de grupo — grupo não é contato do CRM, por decisão de 2026-08-04.
