# CRM & Kanban — ordem de entrada na etapa

**Data:** 2026-08-05
**Status:** aprovado pelo fundador, pronto para plano de implementação
**Branch:** `feat/crm-ordem-de-entrada-na-etapa` (a partir de `origin/main` @ `ee52750`)

## Problema

O Funil de clientes ordena os cards de cada coluna por **nome**:

```python
# apps/api/app/modules/crm/service.py — build_board
clients = list(db.scalars(select(Client).order_by(Client.name)).all())
```

Como a maior parte dos leads entra pelo WhatsApp sem nome resolvido, o "nome" é o telefone, e a
coluna Entrada aparece em ordem numérica de DDI — `5511978184401`, `5521983160520`,
`553172256289`. Essa ordem não tem significado nenhum para quem trabalha o funil.

O dono precisa **atender por ordem de chegada**: o card mais antigo daquela etapa no topo, e todo
card que entra vai para o fim. É uma fila FIFO por coluna.

## O fato que não existe

"Quando este card entrou nesta etapa" **não está gravado em lugar nenhum hoje**.

`Client` só tem `created_at` (nascimento do contato, não entrada na etapa atual) e `updated_at`
(muda em qualquer edição — trocar o e-mail reordenaria a fila).

E ele **não é derivável de forma confiável do `client_events`**, porque os três caminhos que
escrevem `Client.stage_id` registram coisas diferentes:

| Caminho | O que grava |
|---|---|
| `move_client` | evento `stage_move` |
| `absorb_lead` (reabertura de coluna terminal) | evento `reopened` — **kind diferente** |
| `archive_stage` | `UPDATE` em massa, **evento nenhum** |

Somado a isso, `client_events` nasceu na migration `0067` — é mais novo que a maioria dos cards.
Uma derivação em tempo de leitura devolveria posição errada para todo card movido antes disso e
para todo card remanejado por arquivamento de etapa.

### Por que isto não contradiz o precedente do `last_interaction_map`

`crm/service.last_interaction_map` recusa deliberadamente uma coluna `clients.last_interaction_at`,
citando a Onda 0 do Epic 8: valor derivado guardado dessincroniza no primeiro caminho de escrita
que alguém esquecer.

A distinção é real e vale escrever: `last_interaction_at` **é** derivável, de forma completa, de
`client_events` + `whatsapp_messages` — guardá-lo seria criar uma segunda versão de uma verdade que
já existe inteira. `stage_entered_at` **não é**: não há fonte completa da qual derivá-lo. Não é um
derivado que escolhemos materializar; é um fato primário que o sistema nunca registrou.

O risco que a coluna carrega é outro — o 4º caminho de escrita esquecer de carimbar — e é endereçado
pelo teste-portão da seção 4, não por derivação.

## Desenho

### 1. Coluna `clients.stage_entered_at`

```python
stage_entered_at: Mapped[datetime] = mapped_column(
    DateTime(timezone=True),
    default=lambda: datetime.now(UTC),
    server_default=func.now(),
    nullable=False,
)
```

**Default em Python, não só `server_default`** — mesmo motivo já documentado em
`ClientEvent.created_at`: no Postgres `now()` é o instante da **transação**, então dois carimbos no
mesmo commit sairiam com valor idêntico e o desempate cairia no `id` (uuid aleatório). O
`server_default` fica para qualquer INSERT que não passe pelo ORM.

`NOT NULL`: todo card está em algum lugar desde algum instante. Um `NULL` aqui só poderia significar
"não sei", e a fila não tem posição para "não sei".

### 2. Migration `0068` — adiciona e faz backfill

`down_revision = "0067"` (head único verificado em 2026-08-05; reconferir a cada merge de `main`
antes de abrir o PR — ver a nota de colisão de revision em memória).

Três passos, nesta ordem — a coluna é `NOT NULL` no destino, mas não pode nascer assim:

1. `add_column` **nullable**, sem `server_default`. Nascer com `server_default=now()` carimbaria
   todo card existente com o instante do deploy, e o `UPDATE` seguinte teria de desfazer isso —
   um estado intermediário em que a base inteira mente, ainda que por milissegundos.
2. Backfill, por linha, o melhor sinal disponível — **dentro de uma janela com a RLS
   desabilitada**:

```python
# ⚠️ ARMADILHA: sem esta janela, todo o UPDATE abaixo é no-op SILENCIOSO.
op.execute("ALTER TABLE clients DISABLE ROW LEVEL SECURITY")

op.execute("""
    UPDATE clients SET stage_entered_at = COALESCE(
        (SELECT MAX(e.created_at) FROM client_events e
          WHERE e.client_id = clients.id AND e.kind IN ('stage_move', 'reopened')),
        clients.created_at
    )
""")

op.execute("ALTER TABLE clients ENABLE ROW LEVEL SECURITY")
op.execute("ALTER TABLE clients FORCE ROW LEVEL SECURITY")
```

**Por que a janela.** `clients` tem `FORCE ROW LEVEL SECURITY`, e a migration roda como o papel
dono **não-superusuário** `e1p_app`, sem a GUC `app.current_tenant_id`. O `UPDATE` seria filtrado
para **zero linhas, sem erro nenhum** — e o sintoma em produção não seria uma falha de deploy, seria
"a fila continua fora de ordem", com a coluna inteira parada no default. É a mesma armadilha
documentada na `0046`, `0066` e `0067`, e a suíte SQLite é **estruturalmente incapaz** de pegá-la
(os testes unitários montam o schema por `Base.metadata.create_all`, sem passar por alembic).

DDL é transacional no Postgres e a migration roda offline, então não há janela de exposição.

3. `alter_column` para `nullable=False` **e** aplicar o `server_default=func.now()` — que a partir
   daí serve só para INSERT fora do ORM, como descrito na seção 1.

`downgrade` derruba a coluna. O dado é reconstruível pelo mesmo backfill, então a perda é do
refinamento acumulado depois do deploy, não da capacidade de voltar.

Para os 53 cards da Entrada que nasceram do WhatsApp e nunca se moveram, isso é exatamente o
instante em que chegaram — a fila nasce correta. Para card movido antes da `0067`, cai em
`created_at`: errado no detalhe, mas monotônico e sem buraco, e é o melhor que a base tem.

Migration só estrutural + `UPDATE`. Não toca em rede no boot.

### 3. Escrita — onde carimba, e onde deliberadamente não carimba

| Caminho | Ação |
|---|---|
| `create_client` | nasce com o instante da criação |
| `move_client` | recarimba (entrou numa etapa nova agora) |
| `absorb_lead`, ramo de reabertura | recarimba (a reabertura é entrada numa etapa nova) |
| `archive_stage` | **preserva o carimbo** — exceção deliberada |

**A exceção do `archive_stage`.** Arquivar uma etapa é ato administrativo do dono, não mudança na
situação do cliente. Se recarimbasse, todo card daquela coluna iria em bloco para o fim da fila de
destino: um contato que espera desde 20/07 ficaria atrás de um que chegou hoje, e a fila que existe
justamente para atender por antiguidade puniria quem esperou mais. O card muda de coluna; a
antiguidade dele é dele.

Decisão do fundador (2026-08-05), registrada para não ser re-litigada por quem ler só o código e
achar que é um esquecimento.

### 4. Teste-portão contra o 4º caminho

Varredura AST sobre `apps/api/app/modules/crm/`: toda função que atribui `Client.stage_id`
(atribuição a atributo **ou** `{Client.stage_id: ...}` num `.update()`) precisa carimbar
`stage_entered_at` na mesma função, ou constar de uma allowlist explícita com o motivo escrito.

Allowlist inicial: `archive_stage` (motivo: seção 3).

Mesmo idioma dos gates que o repo já tem — `test_tenancy_guard.py`, `test_money_planes.py`. Sem
ele, o 5º caminho de escrita que alguém adicionar daqui a dois meses quebra a ordem da fila **em
silêncio**: nenhum teste falha, nada estoura, a coluna só passa a mentir. É a mesma classe de
problema que a nota de "instanciação obrigatória" do Epic 8 descreve — um invariante sem consumidor
mecânico não protesta.

### 5. Leitura

```python
# build_board
clients = list(db.scalars(
    select(Client).order_by(Client.stage_entered_at, Client.id)
).all())
```

Desempate por `id` para ordem estável entre chamadas quando dois cards têm o mesmo instante — mesmo
padrão de `_ordered_stages` e de `find_duplicate_groups`.

### 6. Contrato e tela

`stage_entered_at` entra em **`ClientOut`**, não em `BoardClient`.

O comentário de `BoardClient` explica por que `last_interaction_at` mora lá e não em `ClientOut`:
ele só é calculado no board, então em qualquer outro endpoint o `null` significaria tanto "sem
interação" quanto "não calculei". `stage_entered_at` não tem essa ambiguidade — é coluna, sempre
presente, todo endpoint que devolve cliente pode afirmá-lo com honestidade.

No card do Kanban, **as duas datas** (escolha do fundador — nada se perde da informação que já
estava na tela):

```
⠿ 5511978184401                    ↗
  na etapa desde: 28/07
  última interação: 05/08
```

Formatação com o `useFuso()` que o `Card` já usa — o projeto vive no fuso do tenant, e data de
negócio renderizada em UTC cru é regressão conhecida (ver `lib/datetime.ts` e a PR #78).

Atualizar `packages/shared-types` à mão, como o resto do projeto (a defasagem do `generated.ts` é
dívida conhecida e registrada; não é escopo desta mudança consertá-la).

## Testes

| Caso | Espera |
|---|---|
| Card novo em coluna com cards | entra no **fim** |
| `move_client` para outra coluna | vai para o fim da coluna de **destino** |
| `move_client` de volta para a original | vai para o fim dela, não para a posição antiga |
| Reabertura via `absorb_lead` | recarimba, vai para o fim da Entrada |
| `archive_stage` remaneja | **preserva** antiguidade; card antigo continua acima de um recente |
| Dois cards com o mesmo instante | ordem estável entre chamadas (desempate por `id`) |
| Editar cliente (nome, tags, e-mail) | **não** reordena |
| Backfill da `0068` | card com `stage_move` usa o evento; card sem evento usa `created_at` |
| Gate AST | função nova que escreve `stage_id` sem carimbar **reprova** |
| Backfill sob RLS real (`rls_e2e`) | semear `clients` na `0067`, aplicar a `0068`, conferir que o backfill **não foi no-op** |

Suíte existente de `test_crm.py` deve continuar verde — o único ponto de atrito esperado são
asserções que dependam da ordem alfabética do board.

## Fora de escopo

- **Reordenação manual dentro da coluna.** A fila é puramente por entrada; arrastar continua só
  movendo entre colunas, como hoje. Requisito explícito do fundador ("sempre o que entrar ficará no
  fim"). Se um dia houver reordenação manual, ela precisa de um `position` por card e este campo
  vira só o valor inicial — desenho diferente, decisão diferente.
- `list_clients` (busca/listagem) segue ordenado por nome. Superfície diferente, propósito
  diferente.
- Consertar a defasagem de `packages/shared-types/src/generated.ts`.

## Operacional

- `main` é protegida (`GH006`): vai por PR, com os 4 checks obrigatórios.
- Checkout de trabalho: `f:\Projetos\e1p\e1p-whatsapp-evolution` (está em `main`, limpo). O irmão
  `escritorio-1-pessoa` está parado em `feat/onda2-origem-do-movimento` e não deve ser movido.
- Esse checkout não tem venv próprio — usar o de `escritorio-1-pessoa/apps/api/.venv`.
