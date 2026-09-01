# Vima: ações de agenda (terceira fatia do caminho até o Jarbes)

## Por que existe

As duas fatias anteriores (`docs/superpowers/specs/2026-08-28-vima-pergunte-design.md` e
`2026-08-28-vima-canal-whatsapp-design.md`) deram à Vima um loop de tool-use e um canal de
WhatsApp, mas ela só **LÊ** — a spec do Pergunte declarou explicitamente fora de escopo: "Ações
(a Vima só LÊ nesta fatia — nenhuma ferramenta escreve nada)", e o CLAUDE.md do projeto carrega
essa dívida nomeada desde então:

> "Ações da Vima — hoje ela só LÊ; quando existir escrita, precisa do rastro 'Ação executada pela
> IA' que uma ferramenta de leitura não precisa."

A infraestrutura para isso já foi deixada pronta em `agenda/service.py`: `create_event`,
`cancel_event` e `reschedule_event` já aceitam `by_ai: bool` e já gravam auditoria com
`is_ai=by_ai` — só nunca foram chamadas com `True` porque não existe ainda um ator de IA no loop
de tool-use. Isso também fecha a **Regra de Ouro nº 3** do projeto ("propagar `is_ai` em
create/update/cancel/reschedule"), hoje congelada porque `CurrentUser.is_ai` nunca vale `True`
nesse caminho.

Esta fatia dá à Vima a primeira capacidade de **escrever**: criar, cancelar e remarcar
compromissos da Agenda, a partir de uma conversa em texto ou WhatsApp — pedido original: "quero
agendar um compromisso... falar com o Carlos às 10:30, amanhã".

## Escopo desta fatia

- **Domínio:** só Agenda. Nenhuma ferramenta de escrita para Financeiro/CRM/Jurídico/Marketing/
  Estoque nesta fatia.
- **Ações:** criar, cancelar, remarcar. As três reaproveitam os serviços determinísticos que já
  existem — nenhuma regra de negócio nova (conflito de horário, espelho no Google, RLS).
- **Confirmação obrigatória antes de escrever:** decisão do fundador. A Vima resume o que
  entendeu em texto puro e só executa a ferramenta depois que o dono confirmar explicitamente
  numa mensagem seguinte. Ver seção "Confirmação" abaixo — é disciplina de prompt + um campo
  obrigatório na ferramenta, não um mecanismo à prova de bala (mesma categoria de garantia que já
  rege "a IA só narra, nunca origina número").
- **Canais:** texto (`/vima/perguntas`) e WhatsApp self-chat, os dois de graça — ambos já passam
  por `vima/pergunta.responder`, ponto único de entrada que esta fatia estende.
- **Permissão:** mesma regra das ferramentas de leitura — `pode_ver(user, "agenda")` decide se a
  Vima sequer mostra as ferramentas de escrita à Claude. Simétrico ao que já vale na REST API
  hoje (`require_module("agenda")`, sem restrição adicional a `owner`): quem já pode criar/
  cancelar/remarcar pela tela, pode pela Vima.
- **Tipos de evento criáveis por chat:** `atendimento`, `reuniao`, `audiencia`, `bloqueio`,
  `lembrete`. Exclui `prazo`, `cobranca_receber`, `cobranca_pagar` e `google` — esses nascem
  derivados de outro módulo ou de uma sincronização externa, não faz sentido a Vima os criar do
  zero.

## Fora de escopo (declarado, não esquecido)

- Ferramentas de escrita para qualquer módulo além de Agenda.
- Editar campos livres do evento (título, local, descrição) depois de criado — só remarcar
  (data/hora) e cancelar. Renomear/editar continua exclusivo da tela manual.
- Um mecanismo de confirmação mais forte que "o prompt manda pedir e o campo obrigatório
  bloqueia se ausente" — por exemplo, um token de confirmação persistido entre chamadas HTTP.
  Contrariaria a decisão já tomada de "sem persistência de conversa entre sessões" da fatia
  anterior; ver "Alternativas consideradas".
- Vínculo automático a um evento do Google Calendar pré-existente fora do e1p (a Vima só cria/
  altera o que já é gerenciado pelo `agenda_events`; o espelho no Google continua sendo
  consequência, via `google_calendar/service.py`, exatamente como já é para a tela manual).

## Arquitetura

Mesmo loop de tool-use das fatias anteriores — três ferramentas novas na mesma lista que a
Claude já recebe, filtradas pelo mesmo `pode_ver`. Nenhum endpoint novo: `POST /vima/pergunta`
continua sendo a única porta de entrada, para os dois canais.

```
dono: "agendar às 10:30 com o Carlos, amanhã"
        │
        ▼
POST /vima/pergunta {pergunta, historico[]}
        │
        ▼
Claude decide: falta confirmação → responde em texto puro
        │        ("Confirma: reunião com o Carlos, amanhã 10:30-11:30?")
        ▼
front exibe; dono digita "sim, confirma"
        │
        ▼
POST /vima/pergunta {pergunta: "sim, confirma", historico: [...]}
        │
        ▼
Claude chama criar_compromisso(confirmado=true, ...)
        │
        ▼
tools.executar → agenda_service.create_event(by_ai=True) ──► audit.record(is_ai=True)
        │
        ▼
Claude narra o resultado ("Criado. Sem conflito." / "Criado, mas você já tem X nesse horário.")
```

Cancelar/remarcar seguem o mesmo desenho, com um passo a mais ANTES da confirmação: quando o
pedido não traz um `event_id` explícito (nunca traz — o dono fala em linguagem natural), a Vima
usa a ferramenta de leitura `consultar_agenda`, já existente, para achar o(s) candidato(s). Se
achar um só, resume e pede confirmação; se achar mais de um, pergunta qual antes de prosseguir;
se não achar nenhum, diz isso e não inventa um `event_id`.

## Backend

### Ferramentas novas (`vima/tools.py`)

| Ferramenta | Módulo (gate) | Wrapper de | Retorna |
|---|---|---|---|
| `criar_compromisso` | `agenda` | `agenda_service.create_event(by_ai=True)` | evento criado + lista de conflitos |
| `cancelar_compromisso` | `agenda` | `agenda_service.cancel_event(by_ai=True)` | evento cancelado |
| `remarcar_compromisso` | `agenda` | `agenda_service.reschedule_event(by_ai=True)` | evento remarcado + lista de conflitos |

Cada uma é um wrapper fino, no mesmo espírito das oito ferramentas de leitura: monta o
`EventCreate`/argumentos do serviço a partir da `entrada` (dict vindo da chamada de ferramenta da
Claude), resolve fuso do tenant com `tenant_timezone` + `day_window_utc` (mesmo padrão de
`_consultar_agenda`), chama o serviço síncrono existente, devolve um dict serializável.

**`criar_compromisso`** — schema de entrada:

```json
{
  "titulo": "string, obrigatório",
  "tipo": "atendimento | reuniao | audiencia | bloqueio | lembrete, obrigatório",
  "data": "AAAA-MM-DD, obrigatório",
  "hora_inicio": "HH:MM, obrigatório",
  "hora_fim": "HH:MM, opcional — omitido usa 1h de duração padrão",
  "cliente": "nome ou parte do nome, opcional — resolvido via crm_service.list_clients, mesmo caminho de consultar_cliente",
  "local": "string, opcional",
  "confirmado": "boolean, obrigatório"
}
```

Se `confirmado` não for `true`, a ferramenta NÃO chama `create_event` — devolve
`{"erro": "peça a confirmação do dono antes de chamar esta ferramenta de novo com confirmado=true"}`.
Isso vale para as três ferramentas de escrita, mesma mecânica.

**`cancelar_compromisso`** / **`remarcar_compromisso`** — recebem `event_id` (a Claude só tem
esse valor depois de ter chamado `consultar_agenda`) + `confirmado`; remarcar recebe também
`nova_data`/`nova_hora_inicio`/`nova_hora_fim`. Erros de domínio já existentes (`AgendaError` —
evento não encontrado, já finalizado/cancelado) viram `{"erro": "..."}` no `tool_result`, mesmo
tratamento que `tools.executar` já dá a qualquer exceção hoje.

### `by_ai` e auditoria

As três chamadas passam `by_ai=True` e `actor=user.user_id` (a identidade de quem PERGUNTOU,
não um ator sintético de IA — `CurrentUser.is_ai` continua sendo sobre o chamador da API, uma
dimensão diferente). Isso é literalmente o que falta hoje: `agenda/router.py` só chama esses
serviços com `by_ai=user.is_ai`, que é sempre `False` no caminho humano. Fecha a Regra de Ouro
nº 3 sem tocar em `agenda/service.py` — o parâmetro já existe, só nunca foi exercitado com
`True`.

### Prompt-sistema (`vima/pergunta.py`)

Estende o `_SYSTEM` atual com a disciplina de confirmação:

> Antes de criar, cancelar ou remarcar um compromisso, resuma o que você entendeu (o quê, quando,
> com quem) em uma mensagem de texto e peça confirmação explícita. Só chame a ferramenta de
> escrita com `confirmado=true` depois que o dono confirmar claramente numa mensagem seguinte —
> nunca no mesmo turno em que ele pediu. Para cancelar ou remarcar, primeiro use
> `consultar_agenda` para achar o compromisso certo; se houver mais de um compatível, pergunte
> qual antes de agir.

Nenhuma mudança em `ai.complete_with_tools` (o loop genérico) nem em `tools.executar` além de
registrar as três ferramentas novas na lista `FERRAMENTAS`.

## Confirmação: por que prompt + campo obrigatório, e não um mecanismo mais forte

Considerada e rejeitada: um tool de duas fases (`propor_compromisso` devolve um token de
confirmação; um segundo tool só aceita esse token). Reduziria — não eliminaria — o risco de a
Claude confirmar consigo mesma no mesmo turno (o loop de tool-use já roda várias rodadas dentro
de UMA chamada HTTP; nada estrutural impede a Claude de chamar as duas ferramentas em sequência,
sem o dono ver a proposta, a menos que o token dependesse de algo persistido ENTRE requisições
HTTP). Isso exigiria guardar estado de "proposta pendente" em algum lugar (tabela nova ou cache),
contrariando a decisão já tomada nas duas fatias anteriores — "sem persistência de conversa entre
sessões" — pelo ganho de segurança que a prática já aceita hoje como suficiente: a mesma
disciplina de prompt que sustenta "a IA só narra, nunca origina número" em todo o resto da Vima.
O campo `confirmado` obrigatório é o meio-termo: não impede a Claude de "se auto-confirmar", mas
IMPEDE a ferramenta de escrever quando ele está ausente — cobre o caso de a Claude chamar a
ferramenta cedo demais por engano, e deixa rastro auditável (`confirmado` aparece no payload da
chamada, visível em log).

## Tratamento de erro e degradação

- Sem `ANTHROPIC_API_KEY`: mesma resposta de hoje ("A Vima está sem acesso à IA agora...") — a
  Vima nunca tenta escrever sem o loop de IA rodando.
- `AgendaError` (evento não encontrado, já finalizado, kind inválido) vira `{"erro": "..."}` no
  `tool_result` — a Claude é instruída (mesma regra do `_SYSTEM` já existente) a dizer que não
  conseguiu, nunca a inventar que deu certo.
- Conflito de horário NÃO bloqueia a criação/remarcação — mesmo comportamento do endpoint REST
  hoje: cria/remarca e devolve a lista de conflitos, a Claude narra ("criei, mas você já tem X
  nesse horário").

## Testes

Mesmo padrão de `test_vima_tools.py` (unitário, uma ferramenta por vez, banco SQLite de teste) e
`test_vima_tools_rls.py` (RLS cross-tenant sob Postgres real):

- Cada ferramenta: caminho feliz (`confirmado=true` → evento criado/cancelado/remarcado,
  `by_ai=True` no registro de auditoria).
- Caminho `confirmado` ausente/`false` → erro, nenhuma escrita no banco.
- `criar_compromisso` com `hora_fim` omitido → duração de 1h.
- `criar_compromisso`/`remarcar_compromisso` com conflito → evento criado/remarcado mesmo assim,
  lista de conflitos não vazia no retorno.
- `cancelar_compromisso`/`remarcar_compromisso` com `event_id` de evento já cancelado/finalizado
  → erro, sem mudança de estado.
- RLS: dois tenants, cada um só consegue cancelar/remarcar o PRÓPRIO evento por id (evento do
  outro tenant não é encontrado, sob Postgres real — mesmo bootstrap de
  `test_vima_tools_rls.py`).
- `ferramentas_disponiveis`: usuário sem módulo `agenda` não vê as três ferramentas novas.

## Dívida (declarada, não desta fatia)

- Editar campos livres (título/local/descrição) via Vima.
- Ferramentas de escrita para outros módulos (Financeiro, CRM, Jurídico, Marketing, Estoque).
- Mecanismo de confirmação mais forte que prompt + campo obrigatório, caso o risco de
  auto-confirmação se prove real em uso (hoje é uma decisão de custo/benefício, não uma lacuna
  desconhecida).
