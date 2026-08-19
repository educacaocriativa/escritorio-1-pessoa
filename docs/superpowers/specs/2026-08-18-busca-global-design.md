# Busca global — ligar o campo da barra de cima

**Data:** 2026-08-18
**Origem:** pedido do fundador — *"quero ligar a busca global do e1p, o campo da barra de cima que
hoje é decorativo"*.
**Base:** `f7f0b4e` (`origin/main`, contém o #125).
**Relacionada:** `2026-08-18-contas-a-pagar-recorte-design.md` §2, que separou este trabalho de
propósito e construiu o primitivo de texto que esta spec promove a utilitário compartilhado.

## 1. O problema

O campo *"Buscar cliente, projeto ou processo"* existe em `AppShell.tsx:191` e nunca funcionou. O
próprio código admite: *"A busca não tem handler nenhum — é decoração até alguém ligá-la"*
(`AppShell.tsx:185`). É um `<input>` sem `onChange`, sem estado, sem rota. Não é regressão.

O projeto não tem infraestrutura de busca: nenhum `tsvector`, nenhum `pg_trgm`, nenhuma rota de
busca unificada. Antes desta spec, os únicos `ilike` do backend inteiro estavam em
`crm/service.py:393` e `payables/service.py` — este último construído pelo #125.

**O placeholder promete o que não existe.** Não há entidade "projeto" no sistema: nenhum módulo,
nenhuma tabela, nenhuma rota. E "processo" é aproximação — o mais perto é `legal_documents`
(Assistente Jurídico), que tem `title`, `skill` e `content`, mas nenhum número de processo. O texto
do campo muda nesta entrega, independentemente do escopo escolhido: prometer e não entregar é pior
que escopo menor.

## 2. Escopo

**Dentro:** duas camadas de busca (§3) sobre sete entidades (§4), a rota `GET /search`, o dropdown
na barra de cima, a página `/busca`, o acesso no celular, e a promoção do `_escapa_curinga` do #125
a utilitário compartilhado — com a dívida equivalente do CRM paga de passagem (§8).

**Fora:** contas a pagar, cobranças e produtos. São listas sem tela de detalhe; entram depois como
entradas no registro (§7), não como reescrita. Também fora: busca por tags, correção ortográfica,
fuzzy, histórico de buscas recentes, e qualquer migration de índice — esta última porque a medição
provou que não ajudaria (§5).

## 3. As duas camadas — a decisão central

São duas perguntas diferentes, e juntá-las numa superfície só é o que faz busca global ficar lenta
e ruidosa:

| | *"me leva até a Ana"* | *"onde foi que eu falei de rescisão"* |
|---|---|---|
| Onde | dropdown da barra de cima | página `/busca` |
| O que lê | rótulo + campos de identidade | tudo, inclusive corpo de documento e mensagens |
| Custo medido | 15-25 ms | 150-270 ms |
| Resultado | uma linha, sem ler nada | trecho destacado, leitura |

A camada rasa casa em nome/título e nos campos que **identificam**: email, telefone e documento do
cliente; `client_name` e `signer_name` em orçamento e contrato; slug do site. A camada funda
acrescenta o corpo: `legal_documents.content`, `clients.notes`, `quotes.notes` e
`whatsapp_messages.text_body`.

`Enter` na barra — ou o rodapé *"ver todos os resultados"* — navega para `/busca?q=termo`. Um motor
só, com a profundidade como parâmetro da rota (§6).

**O placeholder passa a ser `Buscar cliente, contrato ou documento`.** Três exemplos, não a lista
dos sete: um placeholder que enumera tudo não cabe na largura e ainda assim mentiria por omissão no
oitavo tipo que entrar depois. O que ele não pode continuar fazendo é citar "projeto", que não
existe.

**Uma conversa é UM resultado, mesmo na camada funda.** Se o termo aparece em quarenta mensagens do
mesmo chat, sai uma linha — a conversa — com o trecho da mensagem mais recente que casou. O
contrário afogaria os outros seis tipos com repetição do mesmo diálogo, que é exatamente o risco
levantado ao escolher incluir mensagens.

## 4. As sete entidades

Critério: **só entra o que tem tela de destino**. Um resultado que não leva a lugar nenhum não é
resultado.

| Tipo | Destino | Campos rasos | Campos fundos |
|---|---|---|---|
| Cliente | `/crm/clients/:id` | `name`, `email`, `phone`, `document` | `notes` |
| Conversa | `/conversas/:chatId` | `title` **+ nome do cliente vinculado** | `whatsapp_messages.text_body` |
| Contrato | `/contratos/:id` | `title`, `signer_name` | — |
| Orçamento | `/orcamentos/:id` | `title`, `client_name` | `notes` |
| Jurídico | `/juridico/:id` | `title`, `skill` | `content` |
| Site | `/sites/:id` | `title`, `public_slug` | — |
| Funil | `/funis/:id` | `name` | — |

Os grupos aparecem nessa ordem, sempre: gente primeiro, depois o diálogo, depois compromisso e
dinheiro, depois o que se constrói.

**Conversa é a exceção, e o registro admite isso em vez de disfarçar.** `WhatsappChat.title` é
NULLABLE e curto — ninguém procura uma conversa pelo título dela; procura pelo nome da pessoa, que
mora em `clients` via `client_id` (também nullable: `@lid` sem telefone não resolve cliente, e grupo
não vira contato do CRM). A entrada de conversa carrega um predicado próprio com join, em vez de
fingir que cabe numa lista de colunas.

**E `whatsapp_messages` NÃO entra na camada rasa.** A medição mostrou 66-92 ms só em
`sender_name ILIKE` sobre essa tabela — sozinha, mais cara que os outros seis tipos somados.

## 5. A medição — e por que não há migration

Método: banco descartável no Postgres 16.14 de dev, semeado com 5.000 clientes, 2.000 documentos
jurídicos de ~8KB e 300.000 mensagens (93 MB), em três tenants — o principal com 4.000 clientes e
240.000 mensagens. RLS ativa com `FORCE`, consultas rodadas por papel **não-superusuário**:
superusuário ignora RLS e mediria outra coisa. Sanidade confirmada: sem tenant setado, zero linhas.

| Consulta | Tempo |
|---|---|
| Cliente, 4 `ILIKE` em `OR` (nome, email, telefone, documento) | 3,8-7,2 ms |
| Título de documento jurídico | 1,6-6,4 ms |
| `sender_name` sobre 240k mensagens (**descartado da camada rasa**) | 66-92 ms |
| Corpo de 240k mensagens | 140-270 ms |
| Corpo de 2.000 documentos de 8KB | ~196 ms |
| Corpo de mensagens, recorte de 12 meses | ~210 ms |
| Corpo de mensagens, recorte de 3 meses | ~55 ms |

O recorte de 12 meses quase não ajudou porque, nessa seletividade, o planejador continua varrendo a
tabela inteira; o de 3 meses ajuda porque é seletivo o bastante para ele trocar de plano.

### 5.1 O achado: a RLS impede qualquer índice de texto

Criado o `pg_trgm` com índice GIN sobre `text_body` (47 MB, metade do tamanho da tabela, 9,5 s para
construir), a mesma consulta **não usou o índice**. Nem com `enable_seqscan=off` — aí o planejador
preferiu o índice de tenant e deixou o `ILIKE` como filtro.

A mesma consulta como superusuário, com a RLS fora do caminho: **0,7 ms**. Índice GIN usado, 220x
mais rápido.

A causa está no catálogo:

```
proname     | proleakproof
texteq      | t     <- o operador =
texticlike  | f     <- ILIKE
textlike    | f     <- LIKE
ts_match_vq | f     <- o @@ do tsvector
```

Uma política RLS precisa ser avaliada ANTES de qualquer operador não-leakproof — senão o operador
poderia observar linhas que a política esconde. Como `texticlike` não é leakproof, o `ILIKE` é
rebaixado a filtro pós-segurança, e nenhum índice sobre a coluna de texto pode ser usado.

Experimento de controle, na mesma tabela e na mesma sessão: trocando `ILIKE` por `=` (`texteq`, que
É leakproof), o planejador usa o índice trigrama normalmente.

Três consequências:

1. **Não existe migration nesta entrega.** O `pg_trgm` custaria 47 MB e não aceleraria nada
   enquanto a RLS existir — seria dívida pura.
2. **`tsvector` esbarra na mesma parede**, por fato e não por preferência: `ts_match_vq` também é
   `proleakproof = false`.
3. **O piso é varrer as linhas do tenant.** A única alavanca é *quantas linhas* (§6.2).

### 5.2 Duas saídas rejeitadas

**`ALTER FUNCTION texticlike(text,text) LEAKPROOF`** destravaria o índice. Enfraquece a RLS do banco
INTEIRO — todas as tabelas, todos os tenants — em troca de uma tela de busca.

**Embrulhar a busca num `SECURITY DEFINER`** que filtre tenant à mão move o isolamento da política
para o código de aplicação. É exatamente o que `db/session.py` proíbe: *"Nenhuma query de aplicação
deve filtrar tenant manualmente"*.

As duas trocam uma garantia estrutural por milissegundos numa tela. Nenhuma entra.

## 6. A API

### 6.1 A rota

```
GET /search?q=ana&depth=shallow&limit=3
GET /search?q=rescisao&depth=deep&months=12&limit=20

-> { "groups": [ { "type": "client",
                   "has_more": true,
                   "total": 12,            // somente em depth=deep
                   "items": [ {"id","title","subtitle","route","snippet"} ] } ] }
```

`limit` é **por grupo**, não do total: `limit=3` significa até três clientes E até três contratos,
não três resultados no mundo. `snippet` só vem em `depth=deep` — na camada rasa não há corpo de onde
extrair trecho.

`depth=shallow` **não** devolve `total`. Devolve `has_more`, obtido pedindo `limit+1` linhas. Não é
preguiça: contagem exata custaria sete `count()` extras por tecla, e um booleano não tem como mentir
sobre um número. Na página funda, onde a contagem É a informação, ela é exata — a mesma disciplina
do #125, aplicada onde ela cabe.

Os grupos saem na ordem do registro (backend, um lugar só). Os rótulos em português moram no front,
onde a UI mora.

### 6.2 O recorte de 12 meses

`depth=deep` procura nas mensagens dos últimos 12 meses por padrão, com seletor visível de 3 meses /
12 meses / tudo. O custo fica anunciado em vez de escondido, e quem precisa do histórico inteiro
paga conscientemente. Recorte silencioso é a classe de defeito que o #125 acabou de consertar.

**O recorte se aplica SOMENTE às mensagens**, e o rótulo do seletor diz isso — *"mensagens dos
últimos 12 meses"*. Mensagem é a única tabela cujo volume justifica o corte; aplicar a mesma janela
a documentos jurídicos esconderia a petição de dois anos atrás, que é justamente o tipo de coisa que
se procura por texto. Cortar os seis tipos restantes para economizar milissegundos que eles não
custam seria reconstruir o defeito do #125 com filtro novo por cima.

O corte é calculado com **`hoje_do_tenant(db)`** (`settings/service.py:112`).
`datetime.now(UTC).date()` reintroduziria a classe de bug do fuso pela porta do filtro de data.

### 6.3 `q` com menos de 2 caracteres não consulta o banco

Uma letra casa com quase tudo e custaria sete varreduras por tecla. A rota devolve grupos vazios sem
tocar no banco.

## 7. O registro de entidades

`apps/api/app/modules/search/registro.py` — uma lista declarativa de sete entradas:

```python
Entidade(tipo="client", modelo=Client,
         campos_rasos=(Client.name, Client.email, Client.phone, Client.document),
         campos_fundos=(Client.notes,),
         titulo=..., subtitulo=..., rota=lambda c: f"/crm/clients/{c.id}",
         recencia=Client.updated_at)
```

Os sete modelos herdam `TimestampMixin`, então `updated_at` existe em todos e serve de desempate.

**Sete consultas independentes, uma por tipo — sem `UNION`.** Como agrupar por tipo já é a decisão
(§9), não existe ranking global a calcular e não há nada para o banco juntar. O SQL de cada entidade
fica trivial, sem cast entre modelos, idêntico em SQLite e Postgres — logo, coberto pelo `pytest -q`
inteiro, que roda SQLite (`tests/conftest.py:22`).

Acrescentar contas a pagar depois é uma entrada nessa lista.

### 7.1 Ordenação dentro do grupo

Dois degraus: casamento no INÍCIO do campo principal vem antes de casamento no meio; desempate por
`updated_at` decrescente. Dois, e não três, porque cabe num `case()` portátil e num teste que se lê.
Não há score entre tipos — o agrupamento substitui o ranking.

## 8. O primitivo compartilhado

`apps/api/app/core/textsearch.py` — novo, com `escapa_curinga()` e `padrao_ilike()`. Três chamadores:

| Chamador | Mudança |
|---|---|
| `search` | novo |
| `payables` | troca a cópia privada; `test_q_escapa_curinga_do_like` vira a rede de regressão |
| `crm` | **hoje monta `f"%{search}%"` sem escapar nada** (`crm/service.py:392-393`) |

A dívida do CRM é o mesmo defeito que o #125 documentou: `%` sem escape casa com tudo, e a busca
parece funcionar enquanto não filtra nada — o pior tipo de defeito de busca, porque não tem sintoma.
Ela é paga aqui porque construir uma busca nova ao lado dela seria escolher não olhar.

## 9. A tela

```
[lupa] Buscar cliente, contrato ou documento
+---------------------------------------------+
| CLIENTES                                    |
|  Ana Souza            ana@... 11 99999-...  |
|  Ana Paula Lima       CPF 123...            |
| CONVERSAS                                   |
|  Ana Souza            ontem                 |
| CONTRATOS                                   |
|  Assessoria mensal    Ana Souza . assinado  |
+---------------------------------------------+
|  ver todos os resultados para "ana"         |
+---------------------------------------------+
```

Seções fixas na ordem da §4, até 3 itens por seção, seção vazia some.

**Teclado:** setas para cima e para baixo atravessam grupos, `Enter` abre o item focado ou — sem
foco — vai para `/busca?q=`, `Esc` fecha e devolve o foco ao campo, clique fora fecha.
`role="listbox"` + `aria-activedescendant`. `Ctrl/Cmd+K` foca o campo.

**O estado vazio da camada rasa aponta para a funda:** *"Nada encontrado para rescisão"* com o link
*"procurar em documentos e mensagens"*. É exatamente o caso em que a resposta está na outra camada.

**No celular (abaixo de 768px)** o campo continua escondido — o PR #58 mediu que a 360px ele consome
152px da linha e vira um bolo cinza sem placeholder legível. No lugar dele, uma lupa navega para
`/busca`, que já é desenhada para caber num celular. **O botão de menu troca o ícone de lupa por
`Menu`**: hoje ele é uma lupa com `aria-label="Abrir menu"` (`AppShell.tsx:174-183`), e com uma lupa
de verdade ao lado seriam duas lupas com significados diferentes.

## 10. Testes

**O teste que reprova o código de hoje:** buscar `%` no CRM. Hoje devolve TODOS os clientes; o teste
exige zero. Falha em `main`, e é a régua da entrega.

**`pytest -q` (SQLite):** os sete tipos casando pelo campo prometido; conversa casando pelo nome do
cliente vinculado; `q` curto não consulta nada; a ordenação de dois degraus dentro do grupo; o corte
de meses avaliado em fuso NÃO-UTC.

**`pytest -m rls_e2e` (Docker/Postgres):** dois tenants, o B busca o termo que só existe no A e
recebe zero, nos sete tipos. Isolamento é segurança — não pode viver só em SQLite, onde a RLS nem
existe.

**Vitest:** `resultado.ts` (ordem dos grupos, grupo vazio some, `has_more`); teclado atravessando
grupos.

**Playwright:**

- `e2e/busca-url.spec.ts` — **mede a query string real** (`q` escapado, `depth`, `months`). É a
  fresta que o #125 descobriu: pytest monta URL crua, vitest assere params antes de serializar e o
  mock e2e devolve payload fixo — nenhum dos três vê a query string de verdade. Modelo:
  `e2e/pagar-contrato.spec.ts`.
- `e2e/busca-360.spec.ts` — a 360px, **medindo** com `boundingBox`: o campo não aparece, a lupa
  aparece e leva a `/busca`, e a página de resultados não estoura horizontalmente. Nada de
  `toContain`.

## 11. As peças

| Arquivo | Mudança |
|---|---|
| `apps/api/app/core/textsearch.py` | **novo** — `escapa_curinga()`, `padrao_ilike()` |
| `apps/api/app/modules/search/registro.py` | **novo** — as sete entidades, declarativas |
| `apps/api/app/modules/search/service.py` | **novo** — `buscar()`, uma consulta por tipo |
| `apps/api/app/modules/search/router.py` | **novo** — `GET /search` |
| `apps/api/app/modules/search/schemas.py` | **novo** — `SearchGroupOut`, `SearchItemOut` |
| `apps/api/app/modules/payables/service.py` | passa a usar o utilitário compartilhado |
| `apps/api/app/modules/crm/service.py` | passa a usar o utilitário compartilhado (dívida paga) |
| `packages/shared-types/src/index.ts` | `SearchGroup`, `SearchItem` (escritos à mão) |
| `apps/web/src/features/busca/useBusca.ts` | **novo** — debounce 250ms + `AbortController` |
| `apps/web/src/features/busca/resultado.ts` | **novo** — ordem e rótulos, sem DOM |
| `apps/web/src/features/busca/BuscaGlobal.tsx` | **novo** — campo + dropdown |
| `apps/web/src/features/busca/BuscaPage.tsx` | **novo** — `/busca?q=` |
| `apps/web/src/app/AppShell.tsx` | liga o campo; ícone do menu; lupa no celular |
| `apps/web/src/app/App.tsx` | rota `/busca` |

O `AbortController` não é enfeite: sem ele a resposta de uma consulta anterior chega depois e
sobrescreve a atual — o defeito clássico de busca incremental, que aparece como "o resultado pisca
errado" e não como erro.

## 12. Riscos conhecidos

**A camada funda cresce linear.** 150-270 ms em 300k mensagens; em 1M, perto de 1s. O recorte de 12
meses e o seletor (§6.2) são a mitigação, e ela é honesta: o usuário vê o recorte e pode desfazê-lo.
Se um dia doer de verdade, a saída NÃO é `pg_trgm` (§5) — é reduzir linhas varridas, ou reabrir a
discussão de RLS, que é decisão de arquitetura e não de tela.

**Sete round-trips por consulta rasa.** Medidos em 15-25 ms somados. Se um dia isso importar, o
registro declarativo é justamente o que torna a troca por `UNION` mecânica.
