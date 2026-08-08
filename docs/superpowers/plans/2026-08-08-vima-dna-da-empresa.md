# Vima V2 — DNA da Empresa · Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dar ao e1p um retrato do negócio declarado pelo dono, que calibra o comportamento do briefing hoje e serve de contexto aos funcionários virtuais no V4.

**Architecture:** Um catálogo de 45 perguntas em código (`dna/catalog.py`), dividido em duas classes com contrato verificado no import: Calibração (6, cada uma com consumidor real em `LIMIARES_PADRAO`) e Retrato (39, guardadas sem consumidor até o V4). As respostas vão para uma tabela `dna_answers` em upsert, e um resolver é a única porta de leitura — `limiares(db)` entra em `absences.coletar`, `retrato(db)` fica esperando o V4. A captura é progressiva: um núcleo de 6 no primeiro acesso e o resto por ganchos declarados, com cadência de uma pergunta por dia.

**Tech Stack:** FastAPI · SQLAlchemy 2 · Alembic · PostgreSQL 16 (RLS `FORCE`) · React 18 + Vite + TypeScript + Tailwind · Vitest + Testing Library · pytest

**Spec:** [`docs/superpowers/specs/2026-08-08-vima-dna-da-empresa-design.md`](../specs/2026-08-08-vima-dna-da-empresa-design.md)

**Branch:** `feat/vima-dna-da-empresa`, worktree `.claude/worktrees/vima-dna` (criada de `origin/main`, head `c46b79f`)

---

## Global Constraints

Valem para **toda** tarefa deste plano.

- **Isolamento de tenant é RLS, não filtro manual.** Nenhuma query nova adiciona `WHERE tenant_id`. `DnaAnswer` herda `TenantMixin` e a migration dá `ENABLE` + `FORCE ROW LEVEL SECURITY` + policy `tenant_isolation`.
- **"Hoje" é `hoje_do_tenant(db)`** de `app.modules.settings.service`. `datetime.now(UTC).date()` / `date.today()` em lógica de negócio é regressão declarada neste repositório. **Neste plano, só o router chama `hoje_do_tenant`** — `cadencia.py` recebe `hoje` por parâmetro.
- **`app/modules/dna/` entra na varredura AST** de `tests/test_fuso_do_tenant.py` (Task 7). `catalog.py`, `resolver.py` e `cadencia.py` são PUROS: não podem ler o relógio nem para instante.
- **Texto para humano nunca usa `isoformat()`.** Backend: `format_datetime_br` / `format_date_br` de `app.core.tz`. Frontend: `lib/datetime.ts`.
- **O V2 não chama IA em ponto nenhum.** Nada de `core/ai.py`, nada de `anonymizer`, nenhuma linha em `ai_usage`.
- **A migration é a `0076`.** ⚠️ A `0075` **já está tomada** por `0075_investment_bank_account.py`, de uma frente paralela (worktree `onda-2b-i`) que ainda não mergeou. **Reconfira o head com `ls apps/api/migrations/versions/ | tail -3` a cada merge de `main`, não só agora** — é a lição já paga pela `0072`, cujo plano dizia `0071`.
- **Só DDL, sem backfill.** Não existe resposta anterior a esta migration, então a armadilha da RLS no backfill (INSERT ... SELECT que grava zero linhas em silêncio) não se aplica.
- **Idioma:** domínio, docstrings e comentários em PT-BR; identificadores em inglês quando já for a convenção do arquivo.
- **Commits:** Conventional Commits. `main` é protegida — todo trabalho vai por PR.
- **Rodar antes de considerar concluído:** `cd apps/api && pytest` e `pnpm --filter @e1p/web test`. Não confie em `scripts/check.sh` isoladamente — ele mascara falha de frontend com `|| true` no vitest (dívida registrada).

---

## Estrutura de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `apps/api/app/modules/dna/__init__.py` | **Criar.** Vazio. |
| `apps/api/app/modules/dna/catalog.py` | **Criar.** `Pergunta`, `Opcao`, as 45, `NUCLEO`, e as guardas que rodam no import. PURO. |
| `apps/api/app/modules/dna/models.py` | **Criar.** `DnaAnswer`. |
| `apps/api/app/modules/dna/service.py` | **Criar.** `responder`, `pular`, `respostas`. Escreve — pode carimbar instante. |
| `apps/api/app/modules/dna/cadencia.py` | **Criar.** `pendente(db, *, gancho, hoje)`. PURO: `hoje` entra por parâmetro. |
| `apps/api/app/modules/dna/resolver.py` | **Criar.** `limiares(db)` e `retrato(db)`. A única porta de leitura. PURO. |
| `apps/api/app/modules/dna/schemas.py` | **Criar.** Contrato HTTP. |
| `apps/api/app/modules/dna/router.py` | **Criar.** `GET /dna/pendente`, `GET /dna/respostas`, `PUT /dna/{key}`, `POST /dna/{key}/pular`. |
| `apps/api/migrations/versions/0076_dna_answers.py` | **Criar.** Tabela + RLS. |
| `apps/api/app/db/registry.py` | **Modificar.** Importar `DnaAnswer`. |
| `apps/api/app/modules/__init__.py` | **Modificar.** Registrar `dna_router`. |
| `apps/api/app/modules/vima/absences.py` | **Modificar.** `dinheiro_com_data_dias` separado de `prazo_vencendo_dias`. |
| `apps/api/app/modules/vima/service.py` | **Modificar.** Passa `limiares=resolver.limiares(db)`; `_ja_reportadas` respeita recalibração. |
| `apps/api/tests/test_fuso_do_tenant.py` | **Modificar.** Varredura AST sobre `app/modules/dna/`. |
| `packages/shared-types/src/index.ts` | **Modificar.** `DnaPergunta`, `DnaOpcao`, `DnaPendente`. |
| `apps/web/src/features/dna/PerguntaDaVima.tsx` | **Criar.** O componente único de pergunta, usado por todos os ganchos. |
| `apps/web/src/features/dna/GanchoDaVima.tsx` | **Criar.** Busca a pendente do gancho e renderiza (ou nada). |
| `apps/web/src/features/dna/NucleoPage.tsx` | **Criar.** As 6 do núcleo em sequência, pulável. |
| `apps/web/src/features/dna/EmpresaDnaTab.tsx` | **Criar.** A aba "A sua empresa" com os cinco eixos. |
| `apps/web/src/features/vima/EntradaDoDia.tsx` | **Modificar.** Terceiro estado: `nucleo`. |
| `apps/web/src/features/vima/BriefingPage.tsx` | **Modificar.** Gancho colado à linha de ausência. |
| `apps/web/src/features/config/ConfiguracoesPage.tsx` | **Modificar.** Quinta aba. |
| `apps/web/src/app/App.tsx` | **Modificar.** Rota `/dna/nucleo`. |

---

## Ondas

| Onda | Entregável | Tarefas |
|---|---|---|
| **1** | O DNA existe e é respondível pela API. Nada visível mudou. | 1–5 |
| **2** | **O DNA muda o briefing.** Limiar separado, resolver ligado, silêncio limpo ao recalibrar. | 6–7 |
| **3** | O núcleo de 6 no primeiro acesso. | 8–9 |
| **4** | Os ganchos: Calibração colada à ausência + ganchos de contexto. | 10–11 |
| **5** | A aba "A sua empresa" em `/config`. | 12 |

Pode-se parar depois de qualquer onda com software funcionando.

---

# ONDA 1 — O registro do DNA nasce

### Task 1: `dna/catalog.py` — as 45 perguntas e as duas guardas

**Files:**
- Create: `apps/api/app/modules/dna/__init__.py` (vazio)
- Create: `apps/api/app/modules/dna/catalog.py`
- Test: `apps/api/tests/test_dna_catalog.py`

**Interfaces:**
- Consumes: nada (módulo puro, sem imports do projeto)
- Produces: `Opcao(rotulo: str, valor: int | str | None)`, `Pergunta(key, classe, eixo, texto, formato, opcoes, consome, gancho)`, `CatalogoError`, constantes `CALIBRACAO = "calibracao"` / `RETRATO = "retrato"`, `FORMATO_ESCOLHA = "escolha"` / `FORMATO_MULTIPLA = "escolha_multipla"` / `FORMATO_TEXTO = "texto"`, `PERGUNTAS: tuple[Pergunta, ...]` (45 itens), `POR_KEY: dict[str, Pergunta]`, `NUCLEO: tuple[str, ...]` (6 keys), `EIXOS: tuple[str, ...]`

- [ ] **Step 1: Escrever os testes que falham**

```python
# apps/api/tests/test_dna_catalog.py
"""O catálogo do DNA: as duas guardas que dão sentido às classes.

Estes testes são o contrato. Sem eles, "Calibração" vira rótulo decorativo e o produto passa a
fingir que ouviu.
"""
import pytest

from app.modules.dna import catalog
from app.modules.dna.catalog import (
    CALIBRACAO,
    FORMATO_ESCOLHA,
    NUCLEO,
    PERGUNTAS,
    POR_KEY,
    RETRATO,
    CatalogoError,
    Opcao,
    Pergunta,
)
from app.modules.vima.absences import LIMIARES_PADRAO


def test_calibracao_exige_consome_e_retrato_proibe():
    for p in PERGUNTAS:
        if p.classe == CALIBRACAO:
            assert p.consome, f"{p.key} é Calibração e não declara consumidor"
        else:
            assert p.consome is None, f"{p.key} é Retrato e declara consumidor"


def test_consome_aponta_para_limiar_que_existe():
    """Um typo aqui produz silêncio perfeito: grava, não consome, não erra."""
    for p in PERGUNTAS:
        if p.consome:
            assert p.consome in LIMIARES_PADRAO, (
                f"{p.key} consome '{p.consome}', que não existe em LIMIARES_PADRAO"
            )


def test_todo_limiar_tem_pergunta():
    """O outro lado: um limiar sem pergunta é um número que ninguém pode calibrar."""
    cobertos = {p.consome for p in PERGUNTAS if p.consome}
    assert cobertos == set(LIMIARES_PADRAO)


def test_key_unica_e_prefixada_pelo_eixo():
    vistas = set()
    for p in PERGUNTAS:
        assert p.key not in vistas, f"key duplicada: {p.key}"
        vistas.add(p.key)
        assert p.key.startswith(f"{p.eixo}."), (
            f"{p.key} não começa com o eixo '{p.eixo}' — é a lição de facts.kind"
        )


def test_pergunta_de_escolha_tem_ao_menos_duas_opcoes():
    for p in PERGUNTAS:
        if p.formato == FORMATO_ESCOLHA:
            assert len(p.opcoes) >= 2, f"{p.key} é escolha com {len(p.opcoes)} opção(ões)"


def test_o_catalogo_tem_45_perguntas_sendo_6_de_calibracao():
    assert len(PERGUNTAS) == 45
    assert sum(1 for p in PERGUNTAS if p.classe == CALIBRACAO) == 6


def test_nucleo_aponta_para_perguntas_que_existem_e_nenhuma_e_calibracao():
    """'Em quanto tempo eu te aviso?' é irrespondível antes de ter visto um briefing."""
    assert len(NUCLEO) == 6
    for key in NUCLEO:
        assert key in POR_KEY, f"núcleo cita {key}, que não está no catálogo"
        assert POR_KEY[key].classe == RETRATO


def test_toda_calibracao_tem_gancho_de_ausencia():
    for p in PERGUNTAS:
        if p.classe == CALIBRACAO:
            assert p.gancho and p.gancho.startswith("briefing.ausencia."), (
                f"{p.key} é Calibração e precisa vir colada à ausência que a motivou"
            )


def test_a_guarda_recusa_calibracao_sem_consumidor():
    """A guarda precisa ser executável sobre um catálogo arbitrário, não só sobre o real."""
    with pytest.raises(CatalogoError, match="consumidor"):
        catalog.verificar(
            (
                Pergunta(
                    key="ritmo.qualquer", classe=CALIBRACAO, eixo="ritmo",
                    texto="?", formato=FORMATO_ESCOLHA,
                    opcoes=(Opcao("a", 1), Opcao("b", 2)),
                ),
            )
        )


def test_a_guarda_recusa_consome_inexistente():
    with pytest.raises(CatalogoError, match="LIMIARES_PADRAO"):
        catalog.verificar(
            (
                Pergunta(
                    key="ritmo.qualquer", classe=CALIBRACAO, eixo="ritmo",
                    texto="?", formato=FORMATO_ESCOLHA,
                    opcoes=(Opcao("a", 1), Opcao("b", 2)),
                    consome="card_parado_dais",  # typo de propósito
                    gancho="briefing.ausencia.comercial.card.parado",
                ),
            )
        )
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd apps/api && pytest tests/test_dna_catalog.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'app.modules.dna'`

- [ ] **Step 3: Criar o pacote**

```bash
mkdir -p apps/api/app/modules/dna && touch apps/api/app/modules/dna/__init__.py
```

- [ ] **Step 4: Escrever o catálogo**

Criar `apps/api/app/modules/dna/catalog.py`:

```python
"""O catálogo do DNA da Empresa — as 45 perguntas, em código.

Catálogo em código pelo mesmo critério de `LIMIARES_PADRAO` (vima/absences.py) e
`MODELO_POR_TAREFA` (core/ai.py): o que precisa de gate de teste mora onde o teste alcança.
Pergunta nova exige deploy, e isso é correto — pergunta de Calibração vem sempre junto do
consumidor dela, que é código de qualquer forma.

**As duas classes são um contrato, não uma etiqueta de organização:**

- `CALIBRACAO` tem consumidor HOJE. Responder muda o briefing de amanhã.
- `RETRATO` não tem, por definição. É guardado para o V4.

A guarda abaixo roda no IMPORT do módulo. Sem ela, em seis meses alguém marca uma pergunta
bonita como Calibração, o dono a responde acreditando ter mudado o comportamento do produto, e
não mudou nada — um produto que finge ouvir é pior que um produto que não pergunta.

Este módulo é PURO: não lê relógio, não toca no banco. Ver o gate em
`tests/test_fuso_do_tenant.py`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.modules.vima.absences import LIMIARES_PADRAO

CALIBRACAO = "calibracao"
RETRATO = "retrato"

FORMATO_ESCOLHA = "escolha"
FORMATO_MULTIPLA = "escolha_multipla"
FORMATO_TEXTO = "texto"

EIXOS = ("oferta", "cliente", "ritmo", "dinheiro", "limites")

# Teto do campo aberto. Não é limite de banco (a coluna é JSON) — é o ponto em que o texto
# deixou de ser resposta e virou documento, e o V4 vai ter que resumi-lo de qualquer forma.
MAX_TEXTO = 2000


class CatalogoError(ValueError):
    """Violação do contrato das classes. Estoura no import, não em produção."""


@dataclass(frozen=True)
class Opcao:
    rotulo: str          # o que o dono lê
    valor: int | str | None  # o que o sistema guarda e consome


@dataclass(frozen=True)
class Pergunta:
    key: str
    classe: str
    eixo: str
    texto: str
    formato: str
    opcoes: tuple[Opcao, ...] = field(default_factory=tuple)
    consome: str | None = None
    gancho: str | None = None


def verificar(perguntas: tuple[Pergunta, ...]) -> None:
    """As guardas. Pública para que o teste as exercite sobre catálogo arbitrário.

    Um teste que só olhasse `PERGUNTAS` provaria que o catálogo de hoje está certo, não que a
    guarda funciona — e a guarda é o que protege o catálogo de amanhã.
    """
    vistas: set[str] = set()
    for p in perguntas:
        if p.key in vistas:
            raise CatalogoError(f"key duplicada: {p.key}")
        vistas.add(p.key)

        if p.eixo not in EIXOS:
            raise CatalogoError(f"{p.key}: eixo '{p.eixo}' não existe")
        if not p.key.startswith(f"{p.eixo}."):
            raise CatalogoError(f"{p.key} não começa com o eixo '{p.eixo}'")

        if p.classe == CALIBRACAO:
            if not p.consome:
                raise CatalogoError(
                    f"{p.key} é Calibração e não declara consumidor — a classe existe "
                    "justamente para impedir pergunta sem efeito"
                )
            if p.consome not in LIMIARES_PADRAO:
                raise CatalogoError(
                    f"{p.key} consome '{p.consome}', ausente de LIMIARES_PADRAO. Um typo aqui "
                    "grava a resposta, não consome nada e nunca falha."
                )
        elif p.classe == RETRATO:
            if p.consome:
                raise CatalogoError(f"{p.key} é Retrato e declara consumidor '{p.consome}'")
        else:
            raise CatalogoError(f"{p.key}: classe '{p.classe}' não existe")

        if p.formato == FORMATO_ESCOLHA and len(p.opcoes) < 2:
            raise CatalogoError(f"{p.key} é escolha com menos de duas opções")


def _cal(key, eixo, texto, opcoes, consome, gancho) -> Pergunta:
    return Pergunta(
        key=key, classe=CALIBRACAO, eixo=eixo, texto=texto, formato=FORMATO_ESCOLHA,
        opcoes=opcoes, consome=consome, gancho=gancho,
    )


def _esc(key, eixo, texto, opcoes, gancho=None) -> Pergunta:
    return Pergunta(
        key=key, classe=RETRATO, eixo=eixo, texto=texto, formato=FORMATO_ESCOLHA,
        opcoes=opcoes, gancho=gancho,
    )


def _mult(key, eixo, texto, opcoes, gancho=None) -> Pergunta:
    return Pergunta(
        key=key, classe=RETRATO, eixo=eixo, texto=texto, formato=FORMATO_MULTIPLA,
        opcoes=opcoes, gancho=gancho,
    )


def _txt(key, eixo, texto, gancho=None) -> Pergunta:
    return Pergunta(
        key=key, classe=RETRATO, eixo=eixo, texto=texto, formato=FORMATO_TEXTO, gancho=gancho,
    )


# --- Calibração (6) --------------------------------------------------------------------
# Cada uma existe porque há um número esperando por ela. São SEIS porque só existem seis
# consumidores — qualquer número maior seria invenção.

_CALIBRACAO: tuple[Pergunta, ...] = (
    _cal(
        "ritmo.resposta_horas", "ritmo",
        "Um cliente te escreveu e ficou sem resposta. Em quanto tempo eu te aviso?",
        (
            Opcao("Em 4 horas", 4),
            Opcao("No mesmo dia", 12),
            Opcao("No dia seguinte", 24),
            Opcao("Depois de 2 dias", 48),
        ),
        "sem_resposta_nossa_horas",
        "briefing.ausencia.comercial.contato.esperando_resposta",
    ),
    _cal(
        "cliente.esfria_dias", "cliente",
        "Quantos dias sem falar com um cliente já significa que ele esfriou?",
        (Opcao("15 dias", 15), Opcao("30 dias", 30), Opcao("60 dias", 60), Opcao("90 dias", 90)),
        "contato_sumido_dias",
        "briefing.ausencia.comercial.contato.sumido",
    ),
    _cal(
        "ritmo.card_parado_dias", "ritmo",
        "Uma negociação parada na mesma etapa há quanto tempo te incomoda?",
        (Opcao("5 dias", 5), Opcao("10 dias", 10), Opcao("20 dias", 20), Opcao("30 dias", 30)),
        "card_parado_dias",
        "briefing.ausencia.comercial.card.parado",
    ),
    _cal(
        "cliente.topo_seco_dias", "cliente",
        "Quantos dias sem nenhum cliente novo é anormal no seu negócio?",
        (
            Opcao("3 dias", 3),
            Opcao("5 dias", 5),
            Opcao("15 dias", 15),
            # A ÚNICA regra que pode ser desligada: é a única que dispara sobre o VAZIO. As
            # outras cinco se calam sozinhas em quem não usa aquilo — sem cards, não há card
            # parado. `None` = regra não executada (mesma forma do filtro de permissão do V1,
            # que não roda a regra em vez de calcular e esconder).
            Opcao("Não quero esse aviso", None),
        ),
        "topo_sem_lead_dias",
        "briefing.ausencia.comercial.topo.sem_lead",
    ),
    _cal(
        "ritmo.prazo_antecedencia_dias", "ritmo",
        "Com quanta antecedência você quer saber de um prazo?",
        (
            Opcao("No próprio dia", 0),
            Opcao("1 dia antes", 1),
            Opcao("3 dias antes", 3),
            Opcao("1 semana antes", 7),
        ),
        "prazo_vencendo_dias",
        "briefing.ausencia.agenda.prazo.estourado",
    ),
    _cal(
        "dinheiro.antecedencia_dias", "dinheiro",
        "E de uma conta a pagar?",
        (
            Opcao("No próprio dia", 0),
            Opcao("1 dia antes", 1),
            Opcao("3 dias antes", 3),
            Opcao("1 semana antes", 7),
        ),
        "dinheiro_com_data_dias",
        "briefing.ausencia.financeiro.conta.vencendo",
    ),
)

# --- Retrato (39) ----------------------------------------------------------------------
# Regra de pertencimento: entra se um funcionário humano recém-contratado precisaria saber no
# primeiro dia. "Qual seu CNPJ" não entra (é cadastro, mora em tenant_profiles).

_OFERTA: tuple[Pergunta, ...] = (
    _esc(
        "oferta.o_que_vende", "oferta", "O que você vende?",
        (
            Opcao("Serviço recorrente", "servico_recorrente"),
            Opcao("Serviço por projeto", "servico_projeto"),
            Opcao("Produto físico", "produto_fisico"),
            Opcao("Produto digital", "produto_digital"),
            Opcao("Um pouco de cada", "misto"),
        ),
    ),
    _txt(
        "oferta.em_uma_frase", "oferta",
        "Se um cliente perguntar o que você faz, o que você responde?",
    ),
    _esc(
        "oferta.ticket_tipico", "oferta", "Quanto costuma custar um trabalho seu?",
        (
            Opcao("Até R$ 500", "ate_500"),
            Opcao("R$ 500 a 2 mil", "500_2k"),
            Opcao("R$ 2 mil a 10 mil", "2k_10k"),
            Opcao("R$ 10 mil a 50 mil", "10k_50k"),
            Opcao("Acima de R$ 50 mil", "acima_50k"),
        ),
        gancho="quotes.orcamento.criado",
    ),
    _esc(
        "oferta.prazo_entrega", "oferta",
        "Do 'sim' do cliente até a entrega, quanto tempo costuma passar?",
        (
            Opcao("No mesmo dia", "mesmo_dia"),
            Opcao("Até uma semana", "semana"),
            Opcao("De 2 a 4 semanas", "mes"),
            Opcao("Mais de um mês", "mais_de_um_mes"),
            Opcao("É contínuo, não tem fim", "continuo"),
        ),
    ),
    _esc(
        "oferta.como_cobra", "oferta", "Como você costuma cobrar?",
        (
            Opcao("Tudo antes", "antes"),
            Opcao("Tudo depois", "depois"),
            Opcao("Entrada e saldo", "entrada_saldo"),
            Opcao("Parcelado", "parcelado"),
            Opcao("Mensalidade", "mensalidade"),
        ),
    ),
    _esc(
        "oferta.capacidade_mes", "oferta",
        "Quantos clientes novos você consegue atender por mês, no máximo?",
        (
            Opcao("1 ou 2", "1_2"),
            Opcao("3 a 5", "3_5"),
            Opcao("6 a 15", "6_15"),
            Opcao("Mais de 15", "mais_15"),
            Opcao("Não tenho teto", "sem_teto"),
        ),
    ),
    _esc(
        "oferta.proposta_formal", "oferta",
        "Você manda proposta ou orçamento escrito antes de fechar?",
        (
            Opcao("Sempre", "sempre"),
            Opcao("Na maioria das vezes", "maioria"),
            Opcao("Raramente", "raramente"),
            Opcao("Nunca", "nunca"),
        ),
        gancho="quotes.orcamento.criado",
    ),
    _txt("oferta.diferencial", "oferta", "Por que um cliente escolhe você e não o concorrente?"),
    _txt("oferta.aberta", "oferta", "Algo mais que a Vima precisa saber sobre o que você vende?"),
)

_CLIENTE: tuple[Pergunta, ...] = (
    _esc(
        "cliente.quem_e", "cliente", "Quem compra de você?",
        (
            Opcao("Pessoa física", "pf"),
            Opcao("Pequenas empresas", "pequenas"),
            Opcao("Empresas médias e grandes", "grandes"),
            Opcao("Órgãos públicos", "publico"),
            Opcao("Um pouco de cada", "misto"),
        ),
        gancho="crm.cliente.criado",
    ),
    _mult(
        "cliente.como_chega", "cliente", "Como o cliente chega até você?",
        (
            Opcao("Indicação", "indicacao"),
            Opcao("Redes sociais", "social"),
            Opcao("Busca no Google", "busca"),
            Opcao("Anúncio pago", "ads"),
            Opcao("Prospecção ativa", "outbound"),
            Opcao("Passagem ou loja física", "fisico"),
        ),
    ),
    _esc(
        "cliente.decisao_tempo", "cliente",
        "Do primeiro contato até o cliente decidir, quanto tempo costuma levar?",
        (
            Opcao("No mesmo dia", "mesmo_dia"),
            Opcao("Poucos dias", "dias"),
            Opcao("De 1 a 4 semanas", "semanas"),
            Opcao("Mais de um mês", "meses"),
        ),
        gancho="crm.cliente.criado",
    ),
    _esc(
        "cliente.recompra", "cliente", "O mesmo cliente costuma voltar?",
        (
            Opcao("É recorrente por contrato", "contrato"),
            Opcao("Volta com frequência", "frequente"),
            Opcao("Volta às vezes", "as_vezes"),
            Opcao("É compra única", "unica"),
        ),
    ),
    _esc(
        "cliente.objecao", "cliente", "O que mais faz um cliente dizer não?",
        (
            Opcao("Preço", "preco"),
            Opcao("Prazo", "prazo"),
            Opcao("Falta de confiança", "confianca"),
            Opcao("Não era o que ele procurava", "fit"),
            Opcao("Ele some sem dizer nada", "some"),
        ),
    ),
    _esc(
        "cliente.canal_preferido", "cliente", "Por onde o cliente prefere falar com você?",
        (
            Opcao("WhatsApp", "whatsapp"),
            Opcao("Telefone", "telefone"),
            Opcao("E-mail", "email"),
            Opcao("Presencial", "presencial"),
            Opcao("Instagram e afins", "social"),
        ),
    ),
    _txt("cliente.sinal_de_que_fecha", "cliente", "O que te faz saber que um cliente vai fechar?"),
    _txt("cliente.aberta", "cliente", "Algo mais que a Vima precisa saber sobre seus clientes?"),
)

_RITMO: tuple[Pergunta, ...] = (
    _mult(
        "ritmo.dias_de_trabalho", "ritmo", "Em que dias você trabalha?",
        (
            Opcao("Segunda", "seg"), Opcao("Terça", "ter"), Opcao("Quarta", "qua"),
            Opcao("Quinta", "qui"), Opcao("Sexta", "sex"), Opcao("Sábado", "sab"),
            Opcao("Domingo", "dom"),
        ),
    ),
    _esc(
        "ritmo.janela_do_dia", "ritmo", "Que horas você costuma trabalhar?",
        (
            Opcao("De manhã", "manha"),
            Opcao("Horário comercial", "comercial"),
            Opcao("Tarde e noite", "tarde_noite"),
            Opcao("De madrugada", "madrugada"),
            Opcao("Varia muito", "varia"),
        ),
    ),
    _esc(
        "ritmo.pico_do_mes", "ritmo", "Tem época do mês mais cheia?",
        (
            Opcao("Começo", "comeco"), Opcao("Meio", "meio"),
            Opcao("Fim", "fim"), Opcao("Não tem padrão", "sem_padrao"),
        ),
    ),
    _txt("ritmo.sazonalidade", "ritmo", "E do ano? Tem mês que enche e mês que esvazia?"),
    _esc(
        "ritmo.o_que_trava", "ritmo", "O que mais trava o seu dia?",
        (
            Opcao("Atender cliente", "atender"),
            Opcao("Fazer o trabalho em si", "executar"),
            Opcao("Cobrar", "cobrar"),
            Opcao("Burocracia", "burocracia"),
            Opcao("Vender", "vender"),
        ),
    ),
    _esc(
        "ritmo.sozinho", "ritmo", "Você trabalha sozinho?",
        (
            Opcao("Sozinho", "sozinho"),
            Opcao("Com ajuda pontual de freelas", "freelas"),
            Opcao("Tenho 1 ou 2 pessoas", "pequena"),
            Opcao("Tenho equipe", "equipe"),
        ),
    ),
    _txt("ritmo.aberta", "ritmo", "Algo mais que a Vima precisa saber sobre o seu ritmo?"),
)

_DINHEIRO: tuple[Pergunta, ...] = (
    _esc(
        "dinheiro.atraso_reacao", "dinheiro", "Cliente atrasou o pagamento. O que você faz?",
        (
            Opcao("Cobro no dia seguinte", "imediato"),
            Opcao("Espero alguns dias", "espero"),
            Opcao("Espero ele falar", "passivo"),
            Opcao("Evito cobrar", "evito"),
        ),
        gancho="receivables.cobranca.criada",
    ),
    # ⚠️ Parece Calibração e NÃO é: tem número e opções fechadas, mas não existe hoje regra de
    # Ausência sobre tolerância a atraso (`dinheiro com data` olha vencimento, não carência).
    # A classe é definida pelo contrato, nunca pelo formato. Se a regra nascer, esta pergunta
    # migra de classe junto com ela — e a guarda cobra que o consumidor exista antes.
    _esc(
        "dinheiro.tolerancia_dias", "dinheiro",
        "Quantos dias de atraso você tolera antes de agir?",
        (
            Opcao("1 dia", 1), Opcao("3 dias", 3), Opcao("7 dias", 7),
            Opcao("15 dias", 15), Opcao("30 dias", 30),
        ),
    ),
    _esc(
        "dinheiro.reserva", "dinheiro", "Você tem reserva para quantos meses parados?",
        (
            Opcao("Nenhuma", "nenhuma"),
            Opcao("Menos de um mês", "menos_1"),
            Opcao("De 1 a 3 meses", "1_3"),
            Opcao("De 3 a 6 meses", "3_6"),
            Opcao("Mais de 6 meses", "mais_6"),
        ),
    ),
    _esc(
        "dinheiro.pro_labore", "dinheiro", "Você tira um valor fixo por mês para você?",
        (
            Opcao("Sim, fixo", "fixo"),
            Opcao("Sim, variável", "variavel"),
            Opcao("Não separo", "nao_separo"),
        ),
    ),
    _txt("dinheiro.sinal_de_aperto", "dinheiro", "O que te diz que o mês vai ser apertado?"),
    _mult(
        "dinheiro.formas_recebimento", "dinheiro", "Como você recebe?",
        (
            Opcao("Pix", "pix"), Opcao("Boleto", "boleto"), Opcao("Cartão", "cartao"),
            Opcao("Dinheiro", "dinheiro"), Opcao("Transferência", "transferencia"),
        ),
        gancho="receivables.cobranca.criada",
    ),
    _esc(
        "dinheiro.emite_nota", "dinheiro", "Você emite nota fiscal?",
        (
            Opcao("Sempre", "sempre"),
            Opcao("Quando o cliente pede", "sob_demanda"),
            Opcao("Não emito", "nao"),
        ),
        gancho="payables.conta.criada",
    ),
    _txt("dinheiro.aberta", "dinheiro", "Algo mais que a Vima precisa saber sobre o seu dinheiro?"),
)

# O eixo mais importante e o mais fácil de esquecer: é o único que o V4 lê para decidir o que
# NÃO fazer sozinho. Autonomia progressiva sem esta lista é um agente que descobre os limites
# errando na frente do cliente.
_LIMITES: tuple[Pergunta, ...] = (
    _txt("limites.nunca_faco", "limites", "O que você nunca faz, mesmo que o cliente peça?"),
    _mult(
        "limites.exige_voce", "limites", "O que só pode sair com você olhando antes?",
        (
            Opcao("Proposta e preço", "proposta"),
            Opcao("Mensagem para cliente", "mensagem"),
            Opcao("Cobrança", "cobranca"),
            Opcao("Contrato", "contrato"),
            Opcao("Publicação", "publicacao"),
            Opcao("Nada disso", "nada"),
        ),
    ),
    _esc(
        "limites.tom", "limites", "Como você fala com cliente?",
        (
            Opcao("Formal", "formal"),
            Opcao("Cordial e direto", "cordial"),
            Opcao("Informal e próximo", "informal"),
            Opcao("Bem-humorado", "humorado"),
        ),
    ),
    _esc(
        "limites.desconto", "limites", "Você dá desconto?",
        (
            Opcao("Nunca", "nunca"),
            Opcao("Só em caso especial", "especial"),
            Opcao("Negocio sempre", "sempre"),
            Opcao("Tenho tabela fixa", "tabela"),
        ),
        gancho="quotes.orcamento.criado",
    ),
    _txt("limites.recusa_cliente", "limites", "Que tipo de cliente você recusa?"),
    _esc(
        "limites.horario_contato", "limites", "Pode falar com cliente fora do seu horário?",
        (
            Opcao("Pode sempre", "sempre"),
            Opcao("Só urgência", "urgencia"),
            Opcao("Nunca", "nunca"),
        ),
        gancho="agenda.evento.criado",
    ),
    _txt("limites.aberta", "limites", "Algo mais que a Vima precisa saber sobre os seus limites?"),
)

PERGUNTAS: tuple[Pergunta, ...] = (
    _CALIBRACAO + _OFERTA + _CLIENTE + _RITMO + _DINHEIRO + _LIMITES
)

# A guarda roda AGORA, no import. Falha na subida do processo, não em produção.
verificar(PERGUNTAS)

POR_KEY: dict[str, Pergunta] = {p.key: p for p in PERGUNTAS}

# O núcleo do primeiro acesso. NENHUMA é de Calibração, e essa é a inversão central do design:
# "em quanto tempo eu te aviso que ninguém respondeu o Carlos?" é impossível de responder bem
# antes de ter visto um briefing. A resposta seria um chute que depois vira comportamento
# errado com aparência de configuração deliberada.
NUCLEO: tuple[str, ...] = (
    "oferta.o_que_vende",
    "oferta.em_uma_frase",
    "oferta.como_cobra",
    "oferta.ticket_tipico",
    "cliente.como_chega",
    "limites.nunca_faco",
)
```

- [ ] **Step 5: Rodar os testes**

Run: `cd apps/api && pytest tests/test_dna_catalog.py -v`
Expected: PASS, **exceto** `test_consome_aponta_para_limiar_que_existe` e `test_todo_limiar_tem_pergunta`, que falham porque `dinheiro_com_data_dias` ainda não existe em `LIMIARES_PADRAO` — ele nasce na Task 6.

- [ ] **Step 6: Antecipar só a chave do limiar**

O catálogo depende de uma chave que a Onda 2 vai usar. Adicionar **apenas a chave** agora, com o mesmo valor que `prazo_vencendo_dias` tem hoje, mantém a Task 1 verde sem mudar comportamento nenhum (nada lê essa chave ainda — a leitura entra na Task 6).

Modificar `apps/api/app/modules/vima/absences.py`, no dicionário `LIMIARES_PADRAO`:

```python
LIMIARES_PADRAO: dict[str, int] = {
    "sem_resposta_nossa_horas": 24,
    "contato_sumido_dias": 30,
    "card_parado_dias": 10,
    "topo_sem_lead_dias": 5,
    "prazo_vencendo_dias": 1,
    # Nasce com o MESMO valor de `prazo_vencendo_dias` porque hoje as duas regras dividem
    # aquele número. Quem passa a lê-lo é a Task 6 — aqui a chave só existe para o catálogo do
    # DNA poder apontar para ela.
    "dinheiro_com_data_dias": 1,
}
```

- [ ] **Step 7: Rodar a suíte inteira**

Run: `cd apps/api && pytest tests/test_dna_catalog.py tests/test_vima_absences.py -v`
Expected: PASS em tudo. `test_vima_absences.py` não muda de comportamento — a chave nova não é lida por ninguém.

- [ ] **Step 8: Commit**

```bash
git add apps/api/app/modules/dna/ apps/api/tests/test_dna_catalog.py apps/api/app/modules/vima/absences.py
git commit -m "feat: o catálogo do DNA da Empresa e as duas guardas de classe [V2]"
```

---

### Task 2: `DnaAnswer` e a migration 0076

**Files:**
- Create: `apps/api/app/modules/dna/models.py`
- Create: `apps/api/migrations/versions/0076_dna_answers.py`
- Modify: `apps/api/app/db/registry.py`
- Test: `apps/api/tests/test_dna_models.py`

**Interfaces:**
- Consumes: `app.db.base.Base`, `TenantMixin`, `TimestampMixin`, `_uuid`
- Produces: `DnaAnswer` com campos `id`, `tenant_id`, `question_key`, `value` (JSON, nulo), `answered_at` (datetime), `answered_by` (str | None), `source` (str); constantes `SOURCE_NUCLEO = "nucleo"`, `SOURCE_GANCHO = "gancho"`, `SOURCE_CONFIG = "config"`

- [ ] **Step 1: Escrever o teste que falha**

```python
# apps/api/tests/test_dna_models.py
"""A linha de resposta do DNA: upsert por (tenant, pergunta), e nulo significa 'pulei'."""
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.modules.dna.models import SOURCE_CONFIG, DnaAnswer


def test_grava_e_le(db: Session):
    db.add(
        DnaAnswer(
            tenant_id="t1", question_key="oferta.o_que_vende", value="servico_projeto",
            answered_at=datetime.now(UTC), answered_by="u1", source=SOURCE_CONFIG,
        )
    )
    db.commit()
    linha = db.query(DnaAnswer).one()
    assert linha.value == "servico_projeto"
    assert linha.id  # uuid gerado pelo default


def test_valor_nulo_e_estado_valido_e_significa_pulada(db: Session):
    """'Pulei' precisa ser distinguível de 'nunca me perguntaram', sem tabela nova."""
    db.add(
        DnaAnswer(
            tenant_id="t1", question_key="limites.nunca_faco", value=None,
            answered_at=datetime.now(UTC), answered_by="u1", source=SOURCE_CONFIG,
        )
    )
    db.commit()
    linha = db.query(DnaAnswer).one()
    assert linha.value is None


def test_valor_aceita_lista_para_escolha_multipla(db: Session):
    db.add(
        DnaAnswer(
            tenant_id="t1", question_key="cliente.como_chega", value=["indicacao", "busca"],
            answered_at=datetime.now(UTC), answered_by="u1", source=SOURCE_CONFIG,
        )
    )
    db.commit()
    assert db.query(DnaAnswer).one().value == ["indicacao", "busca"]
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd apps/api && pytest tests/test_dna_models.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'app.modules.dna.models'`

- [ ] **Step 3: Escrever o modelo**

Criar `apps/api/app/modules/dna/models.py`:

```python
"""A resposta do DNA — estado atual, não história.

**É upsert, não append — o oposto de `core/facts.py`, e de propósito.** Fato é história; DNA é
estado atual. Guardar versões faria toda leitura ter que decidir qual resposta vale, e o
histórico de quem mudou o quê já é trabalho de `core/audit.py`.

`value` nulo NÃO é ausência de linha: é "o dono viu a pergunta e pulou". A distinção sustenta a
quarentena de 7 dias em `cadencia.py` sem tabela nova.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantMixin, TimestampMixin, _uuid

SOURCE_NUCLEO = "nucleo"
SOURCE_GANCHO = "gancho"
SOURCE_CONFIG = "config"


class DnaAnswer(Base, TenantMixin, TimestampMixin):
    """Uma resposta do dono sobre o próprio negócio."""

    __tablename__ = "dna_answers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    question_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # `int | str | list | None` — o formato é decidido pelo catálogo, e a validação acontece no
    # serviço, contra ele. A coluna é frouxa; a porta de entrada é estreita.
    value: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    answered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # A resposta é do TENANT, mas a autoria importa quando há sub-usuário.
    answered_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
```

- [ ] **Step 4: Registrar no metadata**

Modificar `apps/api/app/db/registry.py`, na lista de imports em ordem alfabética (entre `device_tokens` e `funnels`):

```python
from app.modules.dna.models import DnaAnswer  # noqa: F401
```

- [ ] **Step 5: Rodar o teste**

Run: `cd apps/api && pytest tests/test_dna_models.py -v`
Expected: PASS (3 testes)

- [ ] **Step 6: Conferir o head do Alembic antes de escrever a migration**

Run: `ls apps/api/migrations/versions/ | sort | tail -3`
Expected: a maior revision é `0075_investment_bank_account.py`. **Se for maior que 0075, use o número seguinte ao que apareceu e ajuste `down_revision`** — a frente paralela pode ter avançado.

- [ ] **Step 7: Escrever a migration**

Criar `apps/api/migrations/versions/0076_dna_answers.py`:

```python
"""DNA da Empresa — respostas do dono

Revision ID: 0076
Revises: 0075
Create Date: 2026-08-08

⚠️ A `0075` já estava tomada por `investment_bank_account`, de uma frente paralela — mesma
armadilha que a `0072` documentou. Duas revisions com o mesmo id fazem o `alembic upgrade head`
escolher uma em silêncio.

Sem backfill: não existe resposta anterior a esta migration, então a armadilha da RLS no
backfill (ver 0046/0066/0067/0068/0069) não se aplica. Só DDL.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0076"
down_revision: str | None = "0075"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dna_answers",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("question_key", sa.String(length=64), nullable=False),
        sa.Column("value", sa.JSON(), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("answered_by", sa.String(length=36), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        # O upsert depende desta constraint: uma resposta por pergunta por tenant.
        sa.UniqueConstraint("tenant_id", "question_key", name="uq_dna_answer"),
    )
    op.create_index("ix_dna_answers_question_key", "dna_answers", ["question_key"])

    op.execute("ALTER TABLE dna_answers ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE dna_answers FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON dna_answers
            USING (tenant_id = current_setting('app.current_tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true))
        """
    )


def downgrade() -> None:
    op.drop_table("dna_answers")
```

- [ ] **Step 8: Verificar que a migration sobe e desce**

Run: `cd apps/api && alembic upgrade head && alembic downgrade -1 && alembic upgrade head`
Expected: três comandos sem erro. Se o banco local não estiver de pé, subir com `docker compose up -d db` na raiz (porta 5433 no host — ver `docker-compose.yml`).

- [ ] **Step 9: Commit**

```bash
git add apps/api/app/modules/dna/models.py apps/api/migrations/versions/0076_dna_answers.py apps/api/app/db/registry.py apps/api/tests/test_dna_models.py
git commit -m "feat: tabela dna_answers com RLS [V2]"
```

---

### Task 3: `dna/service.py` — responder, pular e ler, validando contra o catálogo

**Files:**
- Create: `apps/api/app/modules/dna/service.py`
- Test: `apps/api/tests/test_dna_service.py`

**Interfaces:**
- Consumes: `catalog.POR_KEY`, `catalog.FORMATO_*`, `catalog.MAX_TEXTO`, `DnaAnswer`, `SOURCE_*`
- Produces: `DnaError(message, status_code)`, `responder(db, *, tenant_id, key, valor, user_id, source) -> DnaAnswer`, `pular(db, *, tenant_id, key, user_id, source) -> DnaAnswer`, `respostas(db) -> dict[str, Any]` (só as respondidas — `value` não nulo), `linhas(db) -> dict[str, DnaAnswer]` (todas, inclusive as puladas)

- [ ] **Step 1: Escrever os testes que falham**

```python
# apps/api/tests/test_dna_service.py
"""A porta de escrita do DNA: valida contra o catálogo, faz upsert, e pular é gravar nulo."""
import pytest
from sqlalchemy.orm import Session

from app.modules.dna import service
from app.modules.dna.models import SOURCE_CONFIG, SOURCE_GANCHO, DnaAnswer

TENANT = "t1"


def test_responder_grava_e_commita(db: Session):
    service.responder(
        db, tenant_id=TENANT, key="oferta.o_que_vende", valor="servico_projeto",
        user_id="u1", source=SOURCE_CONFIG,
    )
    linha = db.query(DnaAnswer).one()
    assert linha.value == "servico_projeto"
    assert linha.answered_by == "u1"


def test_responder_de_novo_faz_upsert_e_nao_cria_segunda_linha(db: Session):
    """DNA é estado atual, não história — duas linhas fariam toda leitura ter que escolher."""
    service.responder(
        db, tenant_id=TENANT, key="oferta.o_que_vende", valor="servico_projeto",
        user_id="u1", source=SOURCE_CONFIG,
    )
    service.responder(
        db, tenant_id=TENANT, key="oferta.o_que_vende", valor="produto_digital",
        user_id="u1", source=SOURCE_CONFIG,
    )
    assert db.query(DnaAnswer).count() == 1
    assert db.query(DnaAnswer).one().value == "produto_digital"


def test_chave_desconhecida_e_recusada(db: Session):
    with pytest.raises(service.DnaError, match="não existe"):
        service.responder(
            db, tenant_id=TENANT, key="oferta.inventada", valor="x",
            user_id="u1", source=SOURCE_CONFIG,
        )


def test_valor_fora_das_opcoes_e_recusado(db: Session):
    """Sem isso o JSON vira depósito e o resolver quebra na leitura, longe de quem escreveu."""
    with pytest.raises(service.DnaError, match="opções"):
        service.responder(
            db, tenant_id=TENANT, key="oferta.o_que_vende", valor="nao_existe",
            user_id="u1", source=SOURCE_CONFIG,
        )


def test_escolha_multipla_aceita_lista_e_recusa_item_invalido(db: Session):
    service.responder(
        db, tenant_id=TENANT, key="cliente.como_chega", valor=["indicacao", "busca"],
        user_id="u1", source=SOURCE_CONFIG,
    )
    assert db.query(DnaAnswer).one().value == ["indicacao", "busca"]

    with pytest.raises(service.DnaError, match="opções"):
        service.responder(
            db, tenant_id=TENANT, key="cliente.como_chega", valor=["indicacao", "telepatia"],
            user_id="u1", source=SOURCE_CONFIG,
        )


def test_texto_longo_demais_e_recusado(db: Session):
    with pytest.raises(service.DnaError, match="longo"):
        service.responder(
            db, tenant_id=TENANT, key="limites.nunca_faco", valor="x" * 2001,
            user_id="u1", source=SOURCE_CONFIG,
        )


def test_calibracao_aceita_none_so_onde_a_opcao_existe(db: Session):
    """Topo seco pode ser desligado; as outras cinco não têm opção de desligamento."""
    service.responder(
        db, tenant_id=TENANT, key="cliente.topo_seco_dias", valor=None,
        user_id="u1", source=SOURCE_CONFIG,
    )
    assert db.query(DnaAnswer).one().value is None

    with pytest.raises(service.DnaError, match="opções"):
        service.responder(
            db, tenant_id=TENANT, key="ritmo.card_parado_dias", valor=None,
            user_id="u1", source=SOURCE_CONFIG,
        )


def test_pular_grava_linha_com_valor_nulo(db: Session):
    service.pular(
        db, tenant_id=TENANT, key="limites.nunca_faco", user_id="u1", source=SOURCE_GANCHO,
    )
    linha = db.query(DnaAnswer).one()
    assert linha.value is None
    assert linha.source == SOURCE_GANCHO


def test_respostas_ignora_puladas_mas_linhas_as_inclui(db: Session):
    """A distinção que sustenta a quarentena: 'pulei' não é resposta, mas é registro."""
    service.responder(
        db, tenant_id=TENANT, key="oferta.o_que_vende", valor="misto",
        user_id="u1", source=SOURCE_CONFIG,
    )
    service.pular(db, tenant_id=TENANT, key="limites.nunca_faco", user_id="u1",
                  source=SOURCE_CONFIG)

    assert service.respostas(db) == {"oferta.o_que_vende": "misto"}
    assert set(service.linhas(db)) == {"oferta.o_que_vende", "limites.nunca_faco"}


def test_responder_nao_emite_fato(db: Session):
    """O feed do briefing é sobre o NEGÓCIO, não sobre a configuração do produto.

    Um "você respondeu uma pergunta" no resumo de amanhã seria ruído auto-referente. A trilha de
    quem mudou o quê é trabalho de `core/audit.py`.
    """
    from app.core.facts import Fact

    service.responder(
        db, tenant_id=TENANT, key="oferta.o_que_vende", valor="misto",
        user_id="u1", source=SOURCE_CONFIG,
    )
    assert db.query(Fact).count() == 0


def test_pular_e_depois_responder_vira_resposta(db: Session):
    service.pular(db, tenant_id=TENANT, key="oferta.o_que_vende", user_id="u1",
                  source=SOURCE_GANCHO)
    service.responder(
        db, tenant_id=TENANT, key="oferta.o_que_vende", valor="misto",
        user_id="u1", source=SOURCE_CONFIG,
    )
    assert db.query(DnaAnswer).count() == 1
    assert service.respostas(db) == {"oferta.o_que_vende": "misto"}
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd apps/api && pytest tests/test_dna_service.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'app.modules.dna.service'`

- [ ] **Step 3: Escrever o serviço**

Criar `apps/api/app/modules/dna/service.py`:

```python
"""Escrita e leitura crua do DNA. A validação contra o catálogo mora aqui.

A coluna `value` é JSON frouxo de propósito — o formato é decidido pelo catálogo, e é aqui que
o catálogo é cobrado. Sem esta porta estreita, o JSON vira depósito de qualquer coisa e o
resolver quebra na leitura, longe de quem escreveu.

Este módulo NÃO é puro: carimba `answered_at` com o instante. Carimbar INSTANTE é legítimo;
derivar QUE DIA É HOJE é o que o gate de `test_fuso_do_tenant.py` proíbe — e essa derivação
mora em `cadencia.py`, que recebe `hoje` por parâmetro.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.dna import catalog
from app.modules.dna.models import DnaAnswer


class DnaError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def responder(
    db: Session,
    *,
    tenant_id: str,
    key: str,
    valor: Any,
    user_id: str | None,
    source: str,
) -> DnaAnswer:
    """Grava a resposta, validando contra o catálogo. Commita."""
    pergunta = _pergunta(key)
    _validar(pergunta, valor)
    return _gravar(db, tenant_id=tenant_id, key=key, valor=valor, user_id=user_id, source=source)


def pular(
    db: Session, *, tenant_id: str, key: str, user_id: str | None, source: str
) -> DnaAnswer:
    """Registra que o dono viu e pulou. `value` nulo é o registro — não é linha ausente."""
    _pergunta(key)
    return _gravar(db, tenant_id=tenant_id, key=key, valor=None, user_id=user_id, source=source)


def respostas(db: Session) -> dict[str, Any]:
    """Só o que foi de fato respondido. Puladas ficam de fora."""
    return {
        linha.question_key: linha.value
        for linha in db.scalars(select(DnaAnswer)).all()
        if linha.value is not None
    }


def linhas(db: Session) -> dict[str, DnaAnswer]:
    """Todas as linhas, inclusive as puladas — é o que a cadência precisa ver."""
    return {linha.question_key: linha for linha in db.scalars(select(DnaAnswer)).all()}


def _pergunta(key: str) -> catalog.Pergunta:
    pergunta = catalog.POR_KEY.get(key)
    if pergunta is None:
        raise DnaError(f"a pergunta '{key}' não existe no catálogo", status_code=404)
    return pergunta


def _validar(pergunta: catalog.Pergunta, valor: Any) -> None:
    if pergunta.formato == catalog.FORMATO_TEXTO:
        if not isinstance(valor, str):
            raise DnaError(f"'{pergunta.key}' espera texto")
        if len(valor) > catalog.MAX_TEXTO:
            raise DnaError(
                f"texto longo demais ({len(valor)} caracteres, máximo {catalog.MAX_TEXTO})"
            )
        return

    permitidos = {o.valor for o in pergunta.opcoes}

    if pergunta.formato == catalog.FORMATO_MULTIPLA:
        if not isinstance(valor, list):
            raise DnaError(f"'{pergunta.key}' espera uma lista")
        invalidos = [v for v in valor if v not in permitidos]
        if invalidos:
            raise DnaError(f"{invalidos} não está entre as opções de '{pergunta.key}'")
        return

    if valor not in permitidos:
        raise DnaError(f"'{valor}' não está entre as opções de '{pergunta.key}'")


def _gravar(
    db: Session, *, tenant_id: str, key: str, valor: Any, user_id: str | None, source: str
) -> DnaAnswer:
    """Upsert por `(tenant, pergunta)` — a unique constraint da 0076 é o que o garante."""
    linha = db.scalar(select(DnaAnswer).where(DnaAnswer.question_key == key))
    if linha is None:
        linha = DnaAnswer(tenant_id=tenant_id, question_key=key)
        db.add(linha)
    linha.value = valor
    linha.answered_at = datetime.now(UTC)
    linha.answered_by = user_id
    linha.source = source
    db.commit()
    db.refresh(linha)
    return linha
```

- [ ] **Step 4: Rodar os testes**

Run: `cd apps/api && pytest tests/test_dna_service.py -v`
Expected: PASS (10 testes)

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/modules/dna/service.py apps/api/tests/test_dna_service.py
git commit -m "feat: escrita do DNA validada contra o catálogo [V2]"
```

---

### Task 4: `dna/cadencia.py` — uma pergunta por dia, quarentena de 7 dias

**Files:**
- Create: `apps/api/app/modules/dna/cadencia.py`
- Test: `apps/api/tests/test_dna_cadencia.py`

**Interfaces:**
- Consumes: `catalog.PERGUNTAS`, `catalog.NUCLEO`, `service.linhas`
- Produces: `QUARENTENA_DIAS = 7`, `GANCHO_NUCLEO = "nucleo"`, `pendente(db, *, gancho, hoje) -> catalog.Pergunta | None`, `faltantes(db) -> list[catalog.Pergunta]`

**⚠️ Este módulo é PURO.** `hoje` entra por parâmetro; ele nunca chama `now()`, `today()` nem `hoje_do_tenant`. O gate da Task 7 cobra isso.

- [ ] **Step 1: Escrever os testes que falham**

```python
# apps/api/tests/test_dna_cadencia.py
"""A cadência: uma pergunta por dia, pulada em quarentena, escolha determinística."""
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.orm import Session

from app.modules.dna import cadencia, catalog, service
from app.modules.dna.models import SOURCE_GANCHO, DnaAnswer

TENANT = "t1"
HOJE = date(2026, 8, 8)
GANCHO_CARD = "briefing.ausencia.comercial.card.parado"


def _linha(db: Session, key: str, *, valor, quando: datetime) -> None:
    db.add(
        DnaAnswer(
            tenant_id=TENANT, question_key=key, value=valor,
            answered_at=quando, answered_by="u1", source=SOURCE_GANCHO,
        )
    )
    db.commit()


def test_devolve_a_pergunta_do_gancho_quando_nada_foi_respondido(db: Session):
    p = cadencia.pendente(db, gancho=GANCHO_CARD, hoje=HOJE)
    assert p is not None
    assert p.key == "ritmo.card_parado_dias"


def test_nao_devolve_pergunta_ja_respondida(db: Session):
    _linha(db, "ritmo.card_parado_dias", valor=5,
           quando=datetime(2026, 7, 1, tzinfo=UTC))
    assert cadencia.pendente(db, gancho=GANCHO_CARD, hoje=HOJE) is None


def test_uma_pergunta_por_dia_no_produto_inteiro(db: Session):
    """Qualquer resposta de HOJE cala todos os ganchos — não é uma por tela, é uma."""
    _linha(db, "oferta.o_que_vende", valor="misto",
           quando=datetime(2026, 8, 8, 9, 0, tzinfo=UTC))
    assert cadencia.pendente(db, gancho=GANCHO_CARD, hoje=HOJE) is None


def test_resposta_de_ontem_nao_cala_hoje(db: Session):
    _linha(db, "oferta.o_que_vende", valor="misto",
           quando=datetime(2026, 8, 7, 23, 0, tzinfo=UTC))
    assert cadencia.pendente(db, gancho=GANCHO_CARD, hoje=HOJE) is not None


def test_pulada_fica_em_quarentena_por_7_dias(db: Session):
    _linha(db, "ritmo.card_parado_dias", valor=None,
           quando=datetime(2026, 8, 5, tzinfo=UTC))
    assert cadencia.pendente(db, gancho=GANCHO_CARD, hoje=HOJE) is None


def test_pulada_volta_depois_da_quarentena(db: Session):
    """Some por uma semana, não para sempre: um 'depois' acidental não pode perder a pergunta."""
    _linha(db, "ritmo.card_parado_dias", valor=None,
           quando=datetime(2026, 7, 20, tzinfo=UTC))
    p = cadencia.pendente(db, gancho=GANCHO_CARD, hoje=HOJE)
    assert p is not None and p.key == "ritmo.card_parado_dias"


def test_escolha_e_deterministica_pela_ordem_do_catalogo(db: Session):
    """Duas elegíveis no mesmo gancho: vence a primeira do catálogo, sempre a mesma."""
    gancho = "quotes.orcamento.criado"
    primeira = cadencia.pendente(db, gancho=gancho, hoje=HOJE)
    assert primeira is not None
    assert primeira.key == "oferta.ticket_tipico"
    assert cadencia.pendente(db, gancho=gancho, hoje=HOJE).key == primeira.key


def test_gancho_desconhecido_devolve_nada(db: Session):
    assert cadencia.pendente(db, gancho="tela.inventada", hoje=HOJE) is None


def test_nucleo_devolve_as_seis_na_ordem_declarada(db: Session):
    faltando = cadencia.faltantes(db, gancho=cadencia.GANCHO_NUCLEO)
    assert [p.key for p in faltando] == list(catalog.NUCLEO)


def test_nucleo_encolhe_conforme_responde(db: Session):
    """O núcleo é sequência anunciada: não obedece ao 'uma por dia' e some item a item."""
    service.responder(db, tenant_id=TENANT, key="oferta.o_que_vende", valor="misto",
                      user_id="u1", source="nucleo")
    faltando = cadencia.faltantes(db, gancho=cadencia.GANCHO_NUCLEO)
    assert "oferta.o_que_vende" not in [p.key for p in faltando]
    assert len(faltando) == 5
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd apps/api && pytest tests/test_dna_cadencia.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'app.modules.dna.cadencia'`

- [ ] **Step 3: Escrever a cadência**

Criar `apps/api/app/modules/dna/cadencia.py`:

```python
"""Quando perguntar — a Regra do Silêncio do V1 aplicada a perguntar em vez de a avisar.

Duas regras, e nenhuma delas é sobre CONTEÚDO:

1. **Uma pergunta por gancho por dia, no produto inteiro.** Não uma por tela: uma. Um produto
   que interroga em três telas diferentes na mesma sessão é ignorado na quarta.
2. **Pulada fica 7 dias em quarentena.** Nunca some — continua no `/config` —, mas para de ser
   empurrada. Sem quarentena, um "depois" acidental vira interrogatório; com quarentena
   infinita, um toque errado perde a pergunta para sempre.

**O núcleo é a exceção declarada** e não passa por aqui: é uma sequência anunciada, com fim
visível, que a pessoa entrou sabendo que ia atravessar. Interrupção não anunciada e sequência
anunciada não cansam igual — o que cansa é a primeira.

⚠️ **Módulo PURO.** `hoje` entra por parâmetro, sempre. Quem o deriva é o router, com
`hoje_do_tenant(db)`. Um default que lesse o relógio aqui é exatamente por onde o dono no Acre
passa a ser interrogado duas vezes no mesmo dia — e a regressão passaria meses despercebida,
porque em São Paulo funciona.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.modules.dna import catalog, service

QUARENTENA_DIAS = 7
GANCHO_NUCLEO = "nucleo"


def pendente(db: Session, *, gancho: str, hoje: date) -> catalog.Pergunta | None:
    """A pergunta a fazer neste gancho hoje, ou `None` se for dia de silêncio."""
    if gancho == GANCHO_NUCLEO:
        faltando = faltantes(db, gancho=GANCHO_NUCLEO)
        return faltando[0] if faltando else None

    registro = service.linhas(db)

    # Regra 1: qualquer registro de hoje já gastou a cota do dia.
    if any(_dia(linha.answered_at) == hoje for linha in registro.values()):
        return None

    for pergunta in catalog.PERGUNTAS:
        if pergunta.gancho != gancho:
            continue
        linha = registro.get(pergunta.key)
        if linha is None:
            return pergunta
        if linha.value is None and (hoje - _dia(linha.answered_at)).days >= QUARENTENA_DIAS:
            return pergunta  # saiu da quarentena
    return None


def faltantes(db: Session, *, gancho: str) -> list[catalog.Pergunta]:
    """As perguntas do gancho ainda sem RESPOSTA — puladas contam como faltantes.

    Sem cadência: é o que a tela do núcleo e a aba de `/config` usam, onde a pessoa escolheu
    estar e a interrupção não existe.
    """
    respondidas = set(service.respostas(db))
    if gancho == GANCHO_NUCLEO:
        return [
            catalog.POR_KEY[key] for key in catalog.NUCLEO if key not in respondidas
        ]
    return [
        p for p in catalog.PERGUNTAS if p.gancho == gancho and p.key not in respondidas
    ]


def _dia(quando) -> date:
    """A data do carimbo. Não deriva 'hoje' — lê o dia de um instante que já existe."""
    return quando.date()
```

- [ ] **Step 4: Rodar os testes**

Run: `cd apps/api && pytest tests/test_dna_cadencia.py -v`
Expected: PASS (10 testes)

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/modules/dna/cadencia.py apps/api/tests/test_dna_cadencia.py
git commit -m "feat: cadência do DNA — uma por dia, pulada em quarentena [V2]"
```

---

### Task 5: `dna/router.py` — o contrato HTTP

**Files:**
- Create: `apps/api/app/modules/dna/schemas.py`
- Create: `apps/api/app/modules/dna/router.py`
- Modify: `apps/api/app/modules/__init__.py`
- Test: `apps/api/tests/test_dna_router.py`

**Interfaces:**
- Consumes: `cadencia.pendente`, `cadencia.faltantes`, `cadencia.GANCHO_NUCLEO`, `service.responder`, `service.pular`, `service.respostas`, `service.DnaError`, `hoje_do_tenant`, `require_module`, `get_tenant_db`, `get_current_user`
- Produces: rotas `GET /dna/pendente?gancho=`, `GET /dna/faltantes?gancho=`, `GET /dna/respostas`, `PUT /dna/{key}`, `POST /dna/{key}/pular`; schemas `OpcaoOut`, `PerguntaOut`, `RespostaIn`

- [ ] **Step 1: Escrever os testes que falham**

```python
# apps/api/tests/test_dna_router.py
"""O contrato HTTP do DNA — incluindo quem NÃO pode responder."""
import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token

REGISTER = {
    "email": "dono@exemplo.com",
    "password": "senha-forte-123",
    "tenant_name": "Estúdio de Uma Pessoa",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def tenant_id(client: TestClient, headers: dict[str, str]) -> str:
    return client.get("/auth/me", headers=headers).json()["user"]["tenant_id"]


@pytest.fixture()
def headers_sub_crm(tenant_id: str) -> dict[str, str]:
    """Sub-usuário só de CRM: vê o briefing, mas o DNA é da EMPRESA e não é dele."""
    token = create_access_token(
        {
            "sub": "sub-crm",
            "tenant_id": tenant_id,
            "role": "member",
            "allowed_modules": ["comercial"],
        }
    )
    return {"Authorization": f"Bearer {token}"}


def test_nucleo_devolve_as_seis(client: TestClient, headers):
    corpo = client.get("/dna/faltantes", params={"gancho": "nucleo"}, headers=headers).json()
    assert len(corpo) == 6
    assert corpo[0]["key"] == "oferta.o_que_vende"
    assert corpo[0]["opcoes"][0]["rotulo"] == "Serviço recorrente"


def test_responder_e_ler_de_volta(client: TestClient, headers):
    r = client.put(
        "/dna/oferta.o_que_vende", json={"valor": "servico_projeto", "source": "nucleo"},
        headers=headers,
    )
    assert r.status_code == 200
    assert client.get("/dna/respostas", headers=headers).json()["oferta.o_que_vende"] == (
        "servico_projeto"
    )


def test_valor_invalido_devolve_400(client: TestClient, headers):
    r = client.put(
        "/dna/oferta.o_que_vende", json={"valor": "telepatia", "source": "config"},
        headers=headers,
    )
    assert r.status_code == 400


def test_chave_inexistente_devolve_404(client: TestClient, headers):
    r = client.put(
        "/dna/oferta.inventada", json={"valor": "x", "source": "config"}, headers=headers
    )
    assert r.status_code == 404


def test_pular_registra_sem_responder(client: TestClient, headers):
    assert client.post(
        "/dna/limites.nunca_faco/pular", json={"source": "gancho"}, headers=headers
    ).status_code == 200
    assert "limites.nunca_faco" not in client.get("/dna/respostas", headers=headers).json()


def test_pendente_por_gancho(client: TestClient, headers):
    corpo = client.get(
        "/dna/pendente",
        params={"gancho": "briefing.ausencia.comercial.card.parado"},
        headers=headers,
    ).json()
    assert corpo["key"] == "ritmo.card_parado_dias"


def test_dia_de_silencio_devolve_nulo(client: TestClient, headers):
    """Respondeu uma hoje: o gancho se cala até amanhã."""
    client.put(
        "/dna/oferta.o_que_vende", json={"valor": "misto", "source": "nucleo"}, headers=headers
    )
    corpo = client.get(
        "/dna/pendente",
        params={"gancho": "briefing.ausencia.comercial.card.parado"},
        headers=headers,
    ).json()
    assert corpo is None


def test_sub_usuario_sem_settings_nao_alcanca_o_dna(client: TestClient, headers_sub_crm):
    """O DNA é da EMPRESA. Um sub-usuário recalibrando o negócio seria surpresa ruim."""
    assert client.get(
        "/dna/pendente", params={"gancho": "nucleo"}, headers=headers_sub_crm
    ).status_code == 403
    assert client.put(
        "/dna/oferta.o_que_vende", json={"valor": "misto", "source": "config"},
        headers=headers_sub_crm,
    ).status_code == 403
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd apps/api && pytest tests/test_dna_router.py -v`
Expected: FAIL — todas as rotas devolvem 404, porque o router não existe.

- [ ] **Step 3: Escrever os schemas**

Criar `apps/api/app/modules/dna/schemas.py`:

```python
"""Contrato HTTP do DNA.

A pergunta viaja INTEIRA para o front (texto e opções), em vez de o front ter uma cópia do
catálogo: duas cópias divergem no primeiro ajuste de texto, e a versão errada é sempre a que o
dono está lendo.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.modules.dna import catalog


class OpcaoOut(BaseModel):
    rotulo: str
    valor: Any | None


class PerguntaOut(BaseModel):
    key: str
    classe: str
    eixo: str
    texto: str
    formato: str
    opcoes: list[OpcaoOut]


class RespostaIn(BaseModel):
    valor: Any | None = None
    source: str


class PularIn(BaseModel):
    source: str


def to_out(pergunta: catalog.Pergunta) -> PerguntaOut:
    return PerguntaOut(
        key=pergunta.key,
        classe=pergunta.classe,
        eixo=pergunta.eixo,
        texto=pergunta.texto,
        formato=pergunta.formato,
        opcoes=[OpcaoOut(rotulo=o.rotulo, valor=o.valor) for o in pergunta.opcoes],
    )
```

- [ ] **Step 4: Escrever o router**

Criar `apps/api/app/modules/dna/router.py`:

```python
"""Rotas do DNA da Empresa.

⚠️ **`require_module("settings")` aqui, e não filtro no dado.** É o oposto da decisão do
`vima/router.py`, e de propósito: lá o recorte é por LINHA (o funcionário recebe o briefing do
que ele pode ver); aqui a superfície inteira é da empresa, então bloquear a rota é a resposta
certa. `require_module` já dá owner-vê-tudo e lista-vazia-vê-tudo.

**`hoje_do_tenant(db)` é chamado AQUI**, e a data desce por parâmetro até `cadencia`. É o que
mantém aquele módulo puro e o gate de fuso satisfeito.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.tenancy import CurrentUser, get_tenant_db, require_module
from app.modules.dna import cadencia, catalog, service
from app.modules.dna.schemas import PerguntaOut, PularIn, RespostaIn, to_out
from app.modules.settings.service import hoje_do_tenant

router = APIRouter(prefix="/dna", tags=["dna"])


@router.get("/pendente", response_model=PerguntaOut | None)
def pendente(
    gancho: str = Query(...),
    user: CurrentUser = Depends(require_module("settings")),
    db: Session = Depends(get_tenant_db),
) -> PerguntaOut | None:
    """A pergunta deste gancho hoje — ou nada, que é o caso na maioria dos dias."""
    achada = cadencia.pendente(db, gancho=gancho, hoje=hoje_do_tenant(db))
    return to_out(achada) if achada else None


@router.get("/faltantes", response_model=list[PerguntaOut])
def faltantes(
    gancho: str = Query(...),
    user: CurrentUser = Depends(require_module("settings")),
    db: Session = Depends(get_tenant_db),
) -> list[PerguntaOut]:
    """Sem cadência: a sequência anunciada do núcleo e a lista da aba de configurações."""
    return [to_out(p) for p in cadencia.faltantes(db, gancho=gancho)]


@router.get("/respostas")
def respostas(
    user: CurrentUser = Depends(require_module("settings")),
    db: Session = Depends(get_tenant_db),
) -> dict[str, Any]:
    return service.respostas(db)


@router.put("/{key}", response_model=PerguntaOut)
def responder(
    key: str,
    corpo: RespostaIn,
    user: CurrentUser = Depends(require_module("settings")),
    db: Session = Depends(get_tenant_db),
) -> PerguntaOut:
    try:
        service.responder(
            db, tenant_id=user.tenant_id, key=key, valor=corpo.valor,
            user_id=user.user_id, source=corpo.source,
        )
    except service.DnaError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return to_out(catalog.POR_KEY[key])


@router.post("/{key}/pular", response_model=PerguntaOut)
def pular(
    key: str,
    corpo: PularIn,
    user: CurrentUser = Depends(require_module("settings")),
    db: Session = Depends(get_tenant_db),
) -> PerguntaOut:
    try:
        service.pular(
            db, tenant_id=user.tenant_id, key=key, user_id=user.user_id, source=corpo.source
        )
    except service.DnaError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return to_out(catalog.POR_KEY[key])
```

- [ ] **Step 5: Registrar o router**

Modificar `apps/api/app/modules/__init__.py`: adicionar o import junto aos outros (ordem alfabética) e a entrada em `ALL_ROUTERS`:

```python
from app.modules.dna.router import router as dna_router
```

```python
ALL_ROUTERS: list[APIRouter] = [
    # ... entradas existentes ...
    dna_router,
]
```

- [ ] **Step 6: Rodar os testes**

Run: `cd apps/api && pytest tests/test_dna_router.py -v`
Expected: PASS (8 testes)

- [ ] **Step 7: Rodar a suíte inteira da Onda 1**

Run: `cd apps/api && pytest`
Expected: PASS. Nenhum teste existente muda — a Onda 1 não altera comportamento nenhum.

- [ ] **Step 8: Commit**

```bash
git add apps/api/app/modules/dna/ apps/api/app/modules/__init__.py apps/api/tests/test_dna_router.py
git commit -m "feat: rotas do DNA da Empresa, restritas a quem configura a empresa [V2]"
```

---

# ONDA 2 — O DNA muda o briefing

### Task 6: `dinheiro_com_data_dias` deixa de dividir número com o prazo da agenda

**Files:**
- Modify: `apps/api/app/modules/vima/absences.py:166`
- Test: `apps/api/tests/test_vima_absences.py`

**Interfaces:**
- Consumes: `LIMIARES_PADRAO["dinheiro_com_data_dias"]` (a chave nasceu na Task 1)
- Produces: nenhuma assinatura nova — `_dinheiro_com_data` passa a ler a chave própria

**Refactor puro no dia do merge:** a chave nasce com `1`, idêntico ao `prazo_vencendo_dias` de hoje. Nenhum comportamento muda enquanto ninguém responde.

- [ ] **Step 1: Escrever o teste que falha**

Acrescentar a `apps/api/tests/test_vima_absences.py`:

```python
def test_conta_a_pagar_usa_o_limiar_proprio_e_nao_o_do_prazo(db: Session, dono):
    """Prazo de entrega se quer saber em cima; boleto, com folga para ter o dinheiro.

    Um número só para as duas coisas é a fusão que o DNA torna insustentável ao perguntar em
    voz alta.
    """
    hoje = date(2026, 8, 8)
    db.add(
        Payable(
            tenant_id=TENANT_ID, description="Aluguel", amount_cents=250000,
            due_date=hoje + timedelta(days=5), status=PAYABLE_ABERTA,
        )
    )
    db.commit()

    # Antecedência curta: a conta de daqui a 5 dias ainda não é notícia.
    curto = absences.coletar(
        db, user=dono, hoje=hoje,
        limiares={"prazo_vencendo_dias": 7, "dinheiro_com_data_dias": 1},
    )
    assert not [a for a in curto if a.kind == "financeiro.conta.vencendo"]

    # Antecedência longa: agora é.
    longo = absences.coletar(
        db, user=dono, hoje=hoje,
        limiares={"prazo_vencendo_dias": 0, "dinheiro_com_data_dias": 7},
    )
    assert [a for a in longo if a.kind == "financeiro.conta.vencendo"]
```

> **Nota para quem implementa:** o arquivo de teste já tem fixtures de tenant e usuário — reutilize as existentes (`TENANT_ID`, a fixture do dono) em vez de criar novas. Abra o arquivo e siga o padrão dos testes vizinhos para os imports de `Payable`/`PAYABLE_ABERTA`.

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd apps/api && pytest tests/test_vima_absences.py -k limiar_proprio -v`
Expected: FAIL — a conta aparece no caso "curto", porque a regra ainda lê `prazo_vencendo_dias`.

- [ ] **Step 3: Trocar a chave lida**

Modificar `apps/api/app/modules/vima/absences.py`, dentro de `_dinheiro_com_data`, na linha do `limite`:

```python
def _dinheiro_com_data(db: Session, hoje: date, lim: dict[str, int]) -> list[Ausencia]:
    """Conta a pagar e cobrança a receber que a data alcançou.

    ⚠️ As duas direções NÃO seguem a mesma regra, apesar de morarem juntas: conta a pagar tem
    antecedência (`due_date <= hoje + limiar`), cobrança a receber só aparece DEPOIS de vencida
    (`due_date < hoje`, sem limiar). Um recebimento que vence amanhã não é dito por ninguém —
    dívida registrada no spec do V2, e o motivo de a pergunta do DNA falar só de conta a pagar.
    """
    limite = hoje + timedelta(days=lim["dinheiro_com_data_dias"])
```

- [ ] **Step 4: Rodar os testes**

Run: `cd apps/api && pytest tests/test_vima_absences.py -v`
Expected: PASS, inclusive os testes antigos — o default `1` preserva o comportamento anterior.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/modules/vima/absences.py apps/api/tests/test_vima_absences.py
git commit -m "refactor: conta a pagar ganha limiar próprio, separado do prazo da agenda [V2]"
```

---

### Task 7: O resolver liga o DNA ao briefing, e recalibrar limpa o silêncio

**Files:**
- Create: `apps/api/app/modules/dna/resolver.py`
- Modify: `apps/api/app/modules/vima/service.py` (a chamada a `absences.coletar` e `_ja_reportadas`)
- Modify: `apps/api/tests/test_fuso_do_tenant.py`
- Test: `apps/api/tests/test_dna_resolver.py`, `apps/api/tests/test_dna_briefing.py`

**Interfaces:**
- Consumes: `service.respostas`, `catalog.PERGUNTAS`, `LIMIARES_PADRAO`, `DnaAnswer`
- Produces: `limiares(db) -> dict[str, int | None]`, `retrato(db) -> dict[str, Any]`, `recalibrado_apos(db, quando: date) -> bool`

- [ ] **Step 1: Escrever os testes do resolver**

```python
# apps/api/tests/test_dna_resolver.py
"""O resolver é a ÚNICA porta de leitura do DNA."""
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app.modules.dna import resolver, service
from app.modules.dna.models import SOURCE_CONFIG, DnaAnswer
from app.modules.vima.absences import LIMIARES_PADRAO

TENANT = "t1"


def test_sem_resposta_devolve_dicionario_vazio(db: Session):
    """Vazio, não os defaults: quem mescla é `coletar`, e duas fontes de default divergem."""
    assert resolver.limiares(db) == {}


def test_calibracao_respondida_vira_limiar(db: Session):
    service.responder(db, tenant_id=TENANT, key="ritmo.card_parado_dias", valor=5,
                      user_id="u1", source=SOURCE_CONFIG)
    assert resolver.limiares(db) == {"card_parado_dias": 5}


def test_retrato_nunca_entra_nos_limiares(db: Session):
    """O contrato das classes vive ou morre aqui."""
    service.responder(db, tenant_id=TENANT, key="oferta.o_que_vende", valor="misto",
                      user_id="u1", source=SOURCE_CONFIG)
    assert resolver.limiares(db) == {}
    assert resolver.retrato(db) == {"oferta.o_que_vende": "misto"}


def test_calibracao_nunca_entra_no_retrato(db: Session):
    service.responder(db, tenant_id=TENANT, key="ritmo.card_parado_dias", valor=5,
                      user_id="u1", source=SOURCE_CONFIG)
    assert resolver.retrato(db) == {}


def test_desligar_topo_seco_vira_none_e_nao_some(db: Session):
    """`None` = regra não executada. Sumir do dicionário faria o default de 5 dias voltar."""
    service.responder(db, tenant_id=TENANT, key="cliente.topo_seco_dias", valor=None,
                      user_id="u1", source=SOURCE_CONFIG)
    assert resolver.limiares(db) == {"topo_sem_lead_dias": None}


def test_valor_que_saiu_do_catalogo_cai_no_default(db: Session):
    """Trocar o `valor` de uma opção deixa resposta órfã. Ela não pode derrubar o briefing."""
    db.add(
        DnaAnswer(
            tenant_id=TENANT, question_key="ritmo.card_parado_dias", value=999,
            answered_at=datetime.now(UTC), answered_by="u1", source=SOURCE_CONFIG,
        )
    )
    db.commit()
    assert "card_parado_dias" not in resolver.limiares(db)


def test_toda_chave_devolvida_existe_em_limiares_padrao(db: Session):
    service.responder(db, tenant_id=TENANT, key="ritmo.card_parado_dias", valor=5,
                      user_id="u1", source=SOURCE_CONFIG)
    assert set(resolver.limiares(db)) <= set(LIMIARES_PADRAO)


def test_recalibrado_apos_olha_so_calibracao(db: Session):
    """Responder Retrato não pode limpar o silêncio — nada no comportamento mudou."""
    service.responder(db, tenant_id=TENANT, key="oferta.o_que_vende", valor="misto",
                      user_id="u1", source=SOURCE_CONFIG)
    assert resolver.recalibrado_apos(db, date(2026, 1, 1)) is False

    service.responder(db, tenant_id=TENANT, key="ritmo.card_parado_dias", valor=5,
                      user_id="u1", source=SOURCE_CONFIG)
    assert resolver.recalibrado_apos(db, date(2026, 1, 1)) is True
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd apps/api && pytest tests/test_dna_resolver.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'app.modules.dna.resolver'`

- [ ] **Step 3: Escrever o resolver**

Criar `apps/api/app/modules/dna/resolver.py`:

```python
"""A única porta de leitura do DNA.

Duas funções, e nada mais. Nenhum outro módulo lê `dna_answers` direto — é o que mantém a
classe Retrato honestamente SEM consumidor até o V4, em vez de ela vazar por um `select`
esperto em algum lugar, que é como um contrato de arquitetura morre na prática.

⚠️ **Módulo PURO:** não lê relógio. `recalibrado_apos` recebe a data de comparação por
parâmetro.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.dna import catalog
from app.modules.dna.models import DnaAnswer
from app.modules.vima.absences import LIMIARES_PADRAO

_CALIBRACAO_POR_KEY = {
    p.key: p for p in catalog.PERGUNTAS if p.classe == catalog.CALIBRACAO
}


def limiares(db: Session) -> dict[str, int | None]:
    """Só as respostas de Calibração, prontas para `absences.coletar(..., limiares=...)`.

    Devolve **só o que foi respondido**, nunca os defaults: quem mescla é `coletar`, com
    `{**LIMIARES_PADRAO, **override}`. Uma segunda fonte de default divergiria da primeira no
    dia em que alguém mudasse um número em só um dos lugares.
    """
    fora: dict[str, int | None] = {}
    for linha in db.scalars(select(DnaAnswer)).all():
        pergunta = _CALIBRACAO_POR_KEY.get(linha.question_key)
        if pergunta is None or pergunta.consome not in LIMIARES_PADRAO:
            continue
        # A resposta precisa continuar sendo uma das opções. Trocar o `valor` de uma opção
        # depois de alguém responder deixa a linha órfã — e uma resposta órfã tem que cair no
        # default, não derrubar o briefing do dia.
        if linha.value not in {o.valor for o in pergunta.opcoes}:
            continue
        fora[pergunta.consome] = linha.value
    return fora


def retrato(db: Session) -> dict[str, Any]:
    """O dossiê. **Sem consumidor no V2** — existe para que o V4 encontre a porta pronta."""
    return {
        linha.question_key: linha.value
        for linha in db.scalars(select(DnaAnswer)).all()
        if linha.value is not None and linha.question_key not in _CALIBRACAO_POR_KEY
    }


def recalibrado_apos(db: Session, quando: date) -> bool:
    """Houve resposta de CALIBRAÇÃO depois desta data?

    É o gatilho da limpeza do silêncio em `vima/service._ja_reportadas`. Só Calibração conta:
    responder Retrato não muda comportamento nenhum, e limpar o silêncio por causa disso faria
    o briefing repetir pendências sem motivo.
    """
    for linha in db.scalars(select(DnaAnswer)).all():
        if linha.question_key in _CALIBRACAO_POR_KEY and linha.answered_at.date() > quando:
            return True
    return False
```

- [ ] **Step 4: Rodar os testes do resolver**

Run: `cd apps/api && pytest tests/test_dna_resolver.py -v`
Expected: PASS (8 testes)

- [ ] **Step 5: Escrever os testes de integração com o briefing**

```python
# apps/api/tests/test_dna_briefing.py
"""O DNA chegando ao briefing — a ponta que justifica a onda inteira."""
import pytest
from fastapi.testclient import TestClient

REGISTER = {
    "email": "dono@exemplo.com",
    "password": "senha-forte-123",
    "tenant_name": "Estúdio de Uma Pessoa",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_desligar_topo_seco_cala_a_ausencia_no_briefing(client: TestClient, headers, monkeypatch):
    """A ponta a ponta: responder muda o que o dono lê amanhã."""
    from app.core import ai

    monkeypatch.setattr(
        ai, "complete",
        lambda **kw: type("R", (), {"text": "prosa", "input_tokens": 1, "output_tokens": 1})(),
    )

    antes = client.get("/vima/briefing", headers=headers).json()
    assert any("lead" in linha["texto"].lower() or "cliente novo" in linha["texto"].lower()
               for linha in antes["linhas"]), "o tenant novo deveria ter topo seco"

    client.put(
        "/dna/cliente.topo_seco_dias", json={"valor": None, "source": "gancho"}, headers=headers
    )

    # O briefing de HOJE não é regerado (idempotente por dia) — a resposta vale de amanhã.
    depois = client.get("/vima/briefing", headers=headers).json()
    assert depois["id"] == antes["id"]
```

> **Nota para quem implementa:** este teste depende de o tenant recém-criado disparar
> `comercial.topo.sem_lead`. Confirme rodando `pytest tests/test_vima_briefing.py -v` primeiro e
> olhando o payload de `test_dia_sem_nada_devolve_briefing_vazio_e_nao_falha`. Se o tenant novo
> **não** disparar aquela ausência, ajuste a asserção do `antes` para a ausência que ele de fato
> produz e mantenha o resto do teste — o que se está provando é que a resposta chega ao
> `coletar` e que o briefing do dia não é regerado.

- [ ] **Step 6: Ligar o resolver no serviço da Vima**

Modificar `apps/api/app/modules/vima/service.py`, na chamada a `absences.coletar` dentro de `gerar_ou_ler`:

```python
        ausencias=absences.coletar(
            db, user=user, hoje=dia, agora=agora,
            limiares=dna_resolver.limiares(db),
            ja_reportadas=_ja_reportadas(db, user=user),
        ),
```

E o import, junto aos outros:

```python
from app.modules.dna import resolver as dna_resolver
```

- [ ] **Step 7: Limpar o silêncio quando o dono recalibra**

Modificar `_ja_reportadas` em `apps/api/app/modules/vima/service.py`:

```python
def _ja_reportadas(db: Session, *, user: CurrentUser) -> dict[str, int]:
    """As ausências que o briefing anterior deste usuário já disse — a regra do silêncio.

    ⚠️ **Recalibrar zera o registro.** Se o dono aperta "card parado" de 10 para 5 dias e o
    briefing continua calado porque já disse aquilo ontem, a configuração parece quebrada — e a
    próxima que ele mexer, ele não acredita.

    A limpeza é GROSSA de propósito: derruba o silêncio de todas as regras, não só da que
    mudou. Mesma linha do fator 2 da escalada, "arbitrário e deliberadamente grosso".
    Discriminar por regra exigiria um mapa `kind`→limiar que existiria só para isto, e
    recalibrar é raro.
    """
    anterior = db.scalar(
        select(Briefing)
        .where(Briefing.user_id == user.user_id)
        .order_by(Briefing.reference_date.desc())
        .limit(1)
    )
    if anterior is None:
        return {}
    if dna_resolver.recalibrado_apos(db, anterior.reference_date):
        return {}
    try:
        dados = json.loads(anterior.payload)
    except (TypeError, ValueError):  # payload corrompido não pode calar o briefing de hoje
        return {}
    return {str(k): int(v) for k, v in (dados.get("ausencias_ditas") or {}).items()}
```

- [ ] **Step 8: Estender o gate de fuso ao módulo `dna`**

Modificar `apps/api/tests/test_fuso_do_tenant.py`, depois do bloco da Vima:

```python
DNA_DIR = pathlib.Path(__file__).resolve().parents[1] / "app" / "modules" / "dna"

# Puros por contrato: recebem `hoje` por parâmetro e não podem tocar no relógio nem para
# instante. `service.py` PODE carimbar instante (`answered_at`) e não pode derivar "hoje".
DNA_PUROS = {"catalog.py", "cadencia.py", "resolver.py"}


@pytest.mark.parametrize("caminho", sorted(DNA_DIR.glob("*.py")), ids=lambda p: p.name)
def test_dna_nunca_deriva_hoje_do_relogio_do_servidor(caminho: pathlib.Path):
    arvore = ast.parse(caminho.read_text(encoding="utf-8"))
    puro = caminho.name in DNA_PUROS

    for forma, no in _chamadas_de_relogio(arvore):
        if forma in {"today", "utcnow"} or _vira_data(arvore, no):
            pytest.fail(
                f"{caminho.name}:{no.lineno} deriva 'hoje' do relógio do servidor. "
                "A cadência do DNA é por DIA — em UTC−3 isso interroga o dono duas vezes."
            )
        if puro:
            pytest.fail(
                f"{caminho.name}:{no.lineno} lê o relógio, e este módulo é PURO: "
                "`hoje` entra por parâmetro, e quem o deriva é o router."
            )


def test_o_gate_do_dna_tem_o_que_varrer():
    """A instanciação obrigatória: um conjunto vazio passaria calado para sempre."""
    arquivos = {p.name for p in DNA_DIR.glob("*.py")}
    assert DNA_PUROS <= arquivos
    assert "service.py" in arquivos
```

- [ ] **Step 9: Rodar a suíte inteira do backend**

Run: `cd apps/api && pytest`
Expected: PASS. Se `test_dna_briefing.py` falhar na asserção do `antes`, siga a nota do Step 5.

- [ ] **Step 10: Commit**

```bash
git add apps/api/app/modules/dna/resolver.py apps/api/app/modules/vima/service.py apps/api/tests/test_dna_resolver.py apps/api/tests/test_dna_briefing.py apps/api/tests/test_fuso_do_tenant.py
git commit -m "feat: o DNA calibra o briefing, e recalibrar limpa a regra do silêncio [V2]"
```

---

# ONDA 3 — O núcleo no primeiro acesso

### Task 8: Tipos compartilhados e o componente único de pergunta

**Files:**
- Modify: `packages/shared-types/src/index.ts`
- Create: `apps/web/src/features/dna/PerguntaDaVima.tsx`
- Test: `apps/web/src/features/dna/PerguntaDaVima.test.tsx`

**Interfaces:**
- Consumes: `api` de `../../lib/api`
- Produces: tipos `DnaOpcao`, `DnaPergunta`; componente `PerguntaDaVima({ pergunta, source, onPronto, onPular })` — `onPronto` dispara depois do PUT, `onPular` depois do POST de pular

- [ ] **Step 1: Acrescentar os tipos**

Modificar `packages/shared-types/src/index.ts`, ao lado das interfaces `Briefing`:

```typescript
export interface DnaOpcao {
  rotulo: string;
  valor: string | number | null;
}

/** Uma pergunta do DNA da Empresa. Viaja INTEIRA do backend — o front não tem cópia do
 *  catálogo, porque duas cópias divergem no primeiro ajuste de texto. */
export interface DnaPergunta {
  key: string;
  /** "calibracao" muda o briefing de amanhã; "retrato" é guardado para depois. A tela DIZ
   *  isso — prometer efeito imediato ao Retrato seria o erro que as classes existem para
   *  impedir. */
  classe: "calibracao" | "retrato";
  eixo: "oferta" | "cliente" | "ritmo" | "dinheiro" | "limites";
  texto: string;
  formato: "escolha" | "escolha_multipla" | "texto";
  opcoes: DnaOpcao[];
}
```

- [ ] **Step 2: Escrever o teste que falha**

```tsx
// apps/web/src/features/dna/PerguntaDaVima.test.tsx
import type { DnaPergunta } from "@e1p/shared-types";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import PerguntaDaVima from "./PerguntaDaVima";

vi.mock("../../lib/api", () => ({
  api: { put: vi.fn().mockResolvedValue({ data: {} }), post: vi.fn().mockResolvedValue({ data: {} }) },
  apiErrorMessage: (e: unknown) => String(e),
}));

const ESCOLHA: DnaPergunta = {
  key: "ritmo.card_parado_dias",
  classe: "calibracao",
  eixo: "ritmo",
  texto: "Uma negociação parada há quanto tempo te incomoda?",
  formato: "escolha",
  opcoes: [
    { rotulo: "5 dias", valor: 5 },
    { rotulo: "10 dias", valor: 10 },
  ],
};

const TEXTO: DnaPergunta = {
  key: "limites.nunca_faco",
  classe: "retrato",
  eixo: "limites",
  texto: "O que você nunca faz?",
  formato: "texto",
  opcoes: [],
};

describe("PerguntaDaVima", () => {
  it("responde uma escolha em um toque", async () => {
    const onPronto = vi.fn();
    render(<PerguntaDaVima pergunta={ESCOLHA} source="gancho" onPronto={onPronto} />);

    fireEvent.click(screen.getByRole("button", { name: "5 dias" }));

    await waitFor(() => expect(onPronto).toHaveBeenCalled());
    expect(api.put).toHaveBeenCalledWith("/dna/ritmo.card_parado_dias", {
      valor: 5,
      source: "gancho",
    });
  });

  it("avisa que Calibração vale a partir de amanhã", () => {
    render(<PerguntaDaVima pergunta={ESCOLHA} source="gancho" onPronto={vi.fn()} />);
    expect(screen.getByText(/a partir de amanhã/i)).toBeInTheDocument();
  });

  it("avisa que Retrato fica guardado, sem prometer efeito", () => {
    render(<PerguntaDaVima pergunta={TEXTO} source="config" onPronto={vi.fn()} />);
    expect(screen.getByText(/guardad/i)).toBeInTheDocument();
    expect(screen.queryByText(/a partir de amanhã/i)).not.toBeInTheDocument();
  });

  it("pular chama a rota de pular e não a de responder", async () => {
    const onPular = vi.fn();
    render(
      <PerguntaDaVima pergunta={TEXTO} source="gancho" onPronto={vi.fn()} onPular={onPular} />,
    );

    fireEvent.click(screen.getByRole("button", { name: /depois/i }));

    await waitFor(() => expect(onPular).toHaveBeenCalled());
    expect(api.post).toHaveBeenCalledWith("/dna/limites.nunca_faco/pular", { source: "gancho" });
  });
});
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `pnpm --filter @e1p/web test -- PerguntaDaVima`
Expected: FAIL — o módulo `./PerguntaDaVima` não existe.

- [ ] **Step 4: Escrever o componente**

Criar `apps/web/src/features/dna/PerguntaDaVima.tsx`:

```tsx
import type { DnaPergunta } from "@e1p/shared-types";
import { useState } from "react";
import { api, apiErrorMessage } from "../../lib/api";

type Props = {
  pergunta: DnaPergunta;
  source: "nucleo" | "gancho" | "config";
  onPronto: () => void;
  onPular?: () => void;
};

/**
 * A pergunta do DNA, em um único componente para todas as superfícies (núcleo, gancho, config).
 *
 * **A tela DIZ o que cada classe faz.** Calibração vale a partir de amanhã — o briefing de hoje
 * é idempotente e já foi narrado, e mentir sobre isso custa mais que explicar. Retrato é
 * guardado, e prometer efeito imediato a ele seria exatamente o erro que as duas classes
 * existem para impedir: um produto que finge ouvir é pior que um que não pergunta.
 *
 * Desenhado para 360px: opções são blocos de largura inteira, não uma linha de pílulas.
 */
export default function PerguntaDaVima({ pergunta, source, onPronto, onPular }: Props) {
  const [texto, setTexto] = useState("");
  const [marcadas, setMarcadas] = useState<(string | number | null)[]>([]);
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  async function responder(valor: unknown) {
    setSalvando(true);
    setErro(null);
    try {
      await api.put(`/dna/${pergunta.key}`, { valor, source });
      onPronto();
    } catch (e) {
      setErro(apiErrorMessage(e));
    } finally {
      setSalvando(false);
    }
  }

  async function pular() {
    setSalvando(true);
    setErro(null);
    try {
      await api.post(`/dna/${pergunta.key}/pular`, { source });
      (onPular ?? onPronto)();
    } catch (e) {
      setErro(apiErrorMessage(e));
    } finally {
      setSalvando(false);
    }
  }

  return (
    <div className="rounded-xl border border-neutral-200 bg-white p-4">
      <p className="text-base font-medium text-neutral-800">{pergunta.texto}</p>
      <p className="mt-1 text-xs text-neutral-500">
        {pergunta.classe === "calibracao"
          ? "Isso muda o seu resumo a partir de amanhã."
          : "Fica guardado para a Vima te conhecer melhor."}
      </p>

      {pergunta.formato === "escolha" && (
        <div className="mt-3 space-y-2">
          {pergunta.opcoes.map((o) => (
            <button
              key={o.rotulo}
              type="button"
              disabled={salvando}
              onClick={() => responder(o.valor)}
              className="w-full rounded-lg border border-neutral-200 px-4 py-3 text-left text-sm text-neutral-700 hover:border-neutral-400 disabled:opacity-50"
            >
              {o.rotulo}
            </button>
          ))}
        </div>
      )}

      {pergunta.formato === "escolha_multipla" && (
        <div className="mt-3 space-y-2">
          {pergunta.opcoes.map((o) => {
            const ativa = marcadas.includes(o.valor);
            return (
              <button
                key={o.rotulo}
                type="button"
                disabled={salvando}
                onClick={() =>
                  setMarcadas(ativa ? marcadas.filter((v) => v !== o.valor) : [...marcadas, o.valor])
                }
                className={`w-full rounded-lg border px-4 py-3 text-left text-sm disabled:opacity-50 ${
                  ativa
                    ? "border-neutral-800 bg-neutral-800 text-white"
                    : "border-neutral-200 text-neutral-700 hover:border-neutral-400"
                }`}
              >
                {o.rotulo}
              </button>
            );
          })}
          <button
            type="button"
            disabled={salvando || marcadas.length === 0}
            onClick={() => responder(marcadas)}
            className="w-full rounded-lg bg-neutral-900 px-4 py-3 text-sm font-medium text-white disabled:opacity-40"
          >
            Confirmar
          </button>
        </div>
      )}

      {pergunta.formato === "texto" && (
        <div className="mt-3 space-y-2">
          <textarea
            value={texto}
            onChange={(e) => setTexto(e.target.value)}
            rows={3}
            maxLength={2000}
            className="w-full rounded-lg border border-neutral-200 p-3 text-sm text-neutral-700"
            placeholder="Escreva do seu jeito"
          />
          <button
            type="button"
            disabled={salvando || texto.trim() === ""}
            onClick={() => responder(texto.trim())}
            className="w-full rounded-lg bg-neutral-900 px-4 py-3 text-sm font-medium text-white disabled:opacity-40"
          >
            Salvar
          </button>
        </div>
      )}

      {erro && <p className="mt-2 text-xs text-red-600">{erro}</p>}

      <button
        type="button"
        disabled={salvando}
        onClick={pular}
        className="mt-3 text-xs text-neutral-400 underline disabled:opacity-50"
      >
        Responder depois
      </button>
    </div>
  );
}
```

- [ ] **Step 5: Rodar os testes**

Run: `pnpm --filter @e1p/web test -- PerguntaDaVima`
Expected: PASS (4 testes)

- [ ] **Step 6: Commit**

```bash
git add packages/shared-types/src/index.ts apps/web/src/features/dna/
git commit -m "feat: o componente único de pergunta do DNA, com o rótulo honesto por classe [V2]"
```

---

### Task 9: O núcleo de 6 no primeiro acesso

**Files:**
- Create: `apps/web/src/features/dna/NucleoPage.tsx`
- Modify: `apps/web/src/features/vima/EntradaDoDia.tsx`
- Modify: `apps/web/src/app/App.tsx`
- Test: `apps/web/src/features/dna/NucleoPage.test.tsx`, `apps/web/src/features/vima/EntradaDoDia.test.tsx`

**Interfaces:**
- Consumes: `PerguntaDaVima`, `api`, `GET /dna/faltantes?gancho=nucleo`
- Produces: rota `/dna/nucleo`; `EntradaDoDia` ganha o estado `"nucleo"` e a chave `CHAVE_NUCLEO`

- [ ] **Step 1: Escrever o teste do NucleoPage**

```tsx
// apps/web/src/features/dna/NucleoPage.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import NucleoPage from "./NucleoPage";

const PERGUNTAS = [
  {
    key: "oferta.o_que_vende",
    classe: "retrato",
    eixo: "oferta",
    texto: "O que você vende?",
    formato: "escolha",
    opcoes: [{ rotulo: "Serviço por projeto", valor: "servico_projeto" }],
  },
  {
    key: "oferta.em_uma_frase",
    classe: "retrato",
    eixo: "oferta",
    texto: "O que você responde?",
    formato: "texto",
    opcoes: [],
  },
];

vi.mock("../../lib/api", () => ({
  api: {
    get: vi.fn().mockResolvedValue({ data: PERGUNTAS }),
    put: vi.fn().mockResolvedValue({ data: {} }),
    post: vi.fn().mockResolvedValue({ data: {} }),
  },
  apiErrorMessage: (e: unknown) => String(e),
}));

describe("NucleoPage", () => {
  it("mostra uma pergunta por vez, com o progresso visível", async () => {
    render(
      <MemoryRouter>
        <NucleoPage />
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByText("O que você vende?")).toBeInTheDocument());
    expect(screen.queryByText("O que você responde?")).not.toBeInTheDocument();
    expect(screen.getByText("1 de 2")).toBeInTheDocument();
  });

  it("oferece sair da sequência inteira — não é um beco", async () => {
    render(
      <MemoryRouter>
        <NucleoPage />
      </MemoryRouter>,
    );
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /pular por enquanto/i })).toBeInTheDocument(),
    );
  });
});
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `pnpm --filter @e1p/web test -- NucleoPage`
Expected: FAIL — o módulo não existe.

- [ ] **Step 3: Escrever a página**

Criar `apps/web/src/features/dna/NucleoPage.tsx`:

```tsx
import type { DnaPergunta } from "@e1p/shared-types";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../../lib/api";
import PerguntaDaVima from "./PerguntaDaVima";

/** Marca de "o núcleo já foi decidido NESTE aparelho". Espelha `CHAVE_ENTRADA` do briefing. */
export const CHAVE_NUCLEO = "e1p_dna_nucleo";

/**
 * As seis perguntas do primeiro acesso.
 *
 * **Nenhuma é de Calibração, e essa é a inversão central do design.** "Em quanto tempo eu te
 * aviso que ninguém respondeu o Carlos?" é impossível de responder bem antes de ter visto um
 * briefing — a resposta seria um chute que depois vira comportamento errado com aparência de
 * configuração deliberada. Calibração vem por gancho, colada à ausência que a motivou.
 *
 * **É sequência anunciada, não interrogatório:** fim visível ("2 de 6") e saída em um toque. Por
 * isso é a exceção declarada à regra de uma pergunta por dia — o que cansa é a interrupção não
 * anunciada, não a sequência que a pessoa entrou sabendo que ia atravessar.
 */
export default function NucleoPage() {
  const navegar = useNavigate();
  const [perguntas, setPerguntas] = useState<DnaPergunta[] | null>(null);
  const [i, setI] = useState(0);

  useEffect(() => {
    api
      .get<DnaPergunta[]>("/dna/faltantes", { params: { gancho: "nucleo" } })
      .then(({ data }) => setPerguntas(data))
      .catch(() => sair());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function sair() {
    try {
      localStorage.setItem(CHAVE_NUCLEO, "1");
    } catch {
      // Sem a marca, a entrada volta a perguntar ao servidor — mais lento, correto.
    }
    navegar("/", { replace: true });
  }

  function avancar() {
    if (perguntas && i + 1 < perguntas.length) setI(i + 1);
    else sair();
  }

  if (!perguntas) {
    return <div className="py-10 text-center text-sm text-neutral-400">Um instante…</div>;
  }
  if (perguntas.length === 0) {
    sair();
    return null;
  }

  return (
    <div className="mx-auto max-w-md space-y-4 p-4">
      <div>
        <p className="text-sm text-neutral-500">
          {i + 1} de {perguntas.length}
        </p>
        <h1 className="text-xl font-bold text-neutral-800">Me conta do seu negócio</h1>
        <p className="mt-1 text-sm text-neutral-500">
          Leva menos de dois minutos e é o que faz o resumo diário falar a sua língua.
        </p>
      </div>

      <PerguntaDaVima
        key={perguntas[i].key}
        pergunta={perguntas[i]}
        source="nucleo"
        onPronto={avancar}
        onPular={avancar}
      />

      <button
        type="button"
        onClick={sair}
        className="w-full text-center text-xs text-neutral-400 underline"
      >
        Pular por enquanto
      </button>
    </div>
  );
}
```

- [ ] **Step 4: Rodar o teste da página**

Run: `pnpm --filter @e1p/web test -- NucleoPage`
Expected: PASS (2 testes)

- [ ] **Step 5: Escrever o teste da nova decisão de entrada**

Acrescentar a `apps/web/src/features/vima/EntradaDoDia.test.tsx` — siga o padrão dos testes já existentes no arquivo para mockar `api` e `useFuso`:

```tsx
it("manda ao núcleo no primeiro acesso, antes do briefing", async () => {
  localStorage.clear();
  // `api.get` responde: /dna/faltantes → 6 perguntas; /vima/briefing → não lido
  render(
    <MemoryRouter>
      <EntradaDoDia>
        <div>cockpit</div>
      </EntradaDoDia>
    </MemoryRouter>,
  );
  await waitFor(() => expect(screen.queryByText("cockpit")).not.toBeInTheDocument());
});

it("não volta ao núcleo depois de ele ter sido decidido neste aparelho", async () => {
  localStorage.setItem("e1p_dna_nucleo", "1");
  // briefing já lido → cockpit
  render(
    <MemoryRouter>
      <EntradaDoDia>
        <div>cockpit</div>
      </EntradaDoDia>
    </MemoryRouter>,
  );
  await waitFor(() => expect(screen.getByText("cockpit")).toBeInTheDocument());
});
```

- [ ] **Step 6: Acrescentar o terceiro estado à entrada**

Modificar `apps/web/src/features/vima/EntradaDoDia.tsx`:

```tsx
type Decisao = "perguntando" | "nucleo" | "vima" | "cockpit";
```

No `useEffect`, antes da chamada ao briefing:

```tsx
    // O núcleo vem ANTES do briefing, e só no primeiro acesso: um dono que nunca respondeu nada
    // recebe um briefing que fala com todo mundo do mesmo jeito. Perguntar primeiro é o que
    // torna a primeira leitura dele já calibrada — de amanhã em diante.
    if (lerMarcaNucleo() === null) {
      api
        .get<unknown[]>("/dna/faltantes", { params: { gancho: "nucleo" } })
        .then(({ data }) => {
          if (!vivo) return;
          if (data.length > 0) {
            setDecisao("nucleo");
            return;
          }
          gravarMarcaNucleo();
          decidirPeloBriefing();
        })
        // 403 = sub-usuário sem `settings`. O DNA é da empresa e não é dele: segue para o
        // briefing normalmente, sem nunca ver a pergunta.
        .catch(() => decidirPeloBriefing());
      return;
    }
    decidirPeloBriefing();
```

E, junto às funções de marca já existentes:

```tsx
export const CHAVE_NUCLEO = "e1p_dna_nucleo";

function lerMarcaNucleo(): string | null {
  try {
    return localStorage.getItem(CHAVE_NUCLEO);
  } catch {
    return null;
  }
}

function gravarMarcaNucleo(): void {
  try {
    localStorage.setItem(CHAVE_NUCLEO, "1");
  } catch {
    // Sem a marca, a entrada consulta o servidor toda visita — mais lento, correto.
  }
}
```

E o novo destino:

```tsx
  if (decisao === "nucleo") return <Navigate to="/dna/nucleo" replace />;
```

> **Nota para quem implementa:** o `useEffect` atual tem a chamada ao briefing inline. Extraia
> aquele trecho para uma função local `decidirPeloBriefing()` dentro do efeito, preservando o
> `gravarMarca(hoje)` e o `catch` que cai no cockpit. Não mude o comportamento existente — só
> ganhe um caminho antes dele.

- [ ] **Step 7: Registrar a rota**

Modificar `apps/web/src/app/App.tsx`, ao lado da rota `/vima`:

```tsx
import NucleoPage from "../features/dna/NucleoPage";
```

```tsx
          <Route path="/dna/nucleo" element={<NucleoPage />} />
```

> A rota fica no mesmo bloco de `/vima` — dentro do `ProtectedBareLayout`, sem o shell do app.
> O núcleo é porta de entrada, não uma página do produto.

- [ ] **Step 8: Rodar a suíte do front**

Run: `pnpm --filter @e1p/web test`
Expected: PASS. Nenhum teste existente de `EntradaDoDia` pode quebrar — o caminho novo só roda quando a marca do núcleo está ausente.

- [ ] **Step 9: Commit**

```bash
git add apps/web/src/features/dna/ apps/web/src/features/vima/EntradaDoDia.tsx apps/web/src/app/App.tsx
git commit -m "feat: o núcleo de seis perguntas no primeiro acesso [V2]"
```

---

# ONDA 4 — Os ganchos

### Task 10: `GanchoDaVima` e a Calibração colada à ausência

**Files:**
- Create: `apps/web/src/features/dna/GanchoDaVima.tsx`
- Modify: `apps/web/src/features/vima/BriefingPage.tsx`
- Test: `apps/web/src/features/dna/GanchoDaVima.test.tsx`

**Interfaces:**
- Consumes: `PerguntaDaVima`, `GET /dna/pendente?gancho=`
- Produces: `GanchoDaVima({ gancho })` — renderiza a pergunta pendente daquele gancho, ou `null`

- [ ] **Step 1: Escrever o teste que falha**

```tsx
// apps/web/src/features/dna/GanchoDaVima.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import GanchoDaVima from "./GanchoDaVima";

vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), put: vi.fn(), post: vi.fn() },
  apiErrorMessage: (e: unknown) => String(e),
}));

describe("GanchoDaVima", () => {
  it("não renderiza nada quando não há pergunta para hoje", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: null });
    const { container } = render(<GanchoDaVima gancho="briefing.ausencia.comercial.card.parado" />);
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("some depois de responder, sem recarregar a tela", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: {
        key: "ritmo.card_parado_dias",
        classe: "calibracao",
        eixo: "ritmo",
        texto: "Há quanto tempo te incomoda?",
        formato: "escolha",
        opcoes: [{ rotulo: "5 dias", valor: 5 }],
      },
    });
    vi.mocked(api.put).mockResolvedValue({ data: {} });

    render(<GanchoDaVima gancho="briefing.ausencia.comercial.card.parado" />);
    await waitFor(() => expect(screen.getByText("Há quanto tempo te incomoda?")).toBeInTheDocument());

    screen.getByRole("button", { name: "5 dias" }).click();
    await waitFor(() =>
      expect(screen.queryByText("Há quanto tempo te incomoda?")).not.toBeInTheDocument(),
    );
  });

  it("erro na busca não derruba a tela hospedeira", async () => {
    vi.mocked(api.get).mockRejectedValue(new Error("403"));
    const { container } = render(<GanchoDaVima gancho="qualquer" />);
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });
});
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `pnpm --filter @e1p/web test -- GanchoDaVima`
Expected: FAIL — o módulo não existe.

- [ ] **Step 3: Escrever o componente**

Criar `apps/web/src/features/dna/GanchoDaVima.tsx`:

```tsx
import type { DnaPergunta } from "@e1p/shared-types";
import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import PerguntaDaVima from "./PerguntaDaVima";

/**
 * A pergunta do DNA colada ao contexto que a torna óbvia.
 *
 * **Falha em silêncio, sempre.** Um 403 (sub-usuário sem `settings`) ou uma rede ruim não podem
 * derrubar a tela hospedeira — o DNA é acessório em toda superfície onde aparece. Erro aqui
 * significa "não pergunta hoje", nunca "quebra o briefing".
 *
 * A cadência inteira mora no servidor (`dna/cadencia.py`): uma pergunta por dia no produto
 * inteiro, pulada em quarentena de 7 dias. O componente só mostra o que lhe deram.
 */
export default function GanchoDaVima({ gancho }: { gancho: string }) {
  const [pergunta, setPergunta] = useState<DnaPergunta | null>(null);

  useEffect(() => {
    let vivo = true;
    api
      .get<DnaPergunta | null>("/dna/pendente", { params: { gancho } })
      .then(({ data }) => {
        if (vivo) setPergunta(data ?? null);
      })
      .catch(() => {
        if (vivo) setPergunta(null);
      });
    return () => {
      vivo = false;
    };
  }, [gancho]);

  if (!pergunta) return null;

  return (
    <div className="mt-2">
      <PerguntaDaVima
        pergunta={pergunta}
        source="gancho"
        onPronto={() => setPergunta(null)}
        onPular={() => setPergunta(null)}
      />
    </div>
  );
}
```

- [ ] **Step 4: Rodar os testes**

Run: `pnpm --filter @e1p/web test -- GanchoDaVima`
Expected: PASS (3 testes)

- [ ] **Step 5: Colar o gancho na linha de ausência do briefing**

Modificar `apps/web/src/features/vima/BriefingPage.tsx`. Abra o arquivo e encontre onde as
`linhas` do briefing são renderizadas. Depois da **primeira** linha cuja `secao` é a de
pendências, inserir:

```tsx
{primeiraAusencia && <GanchoDaVima gancho={`briefing.ausencia.${primeiraAusencia.kind}`} />}
```

**O `kind` não viaja hoje — é preciso fazê-lo viajar.** `Linha` (composer.py:86) carrega só
`secao`, `module` e `texto`; o `kind` existe apenas dentro de `Candidato.chave`, no formato
`"{kind}:{subject_id}"`. São quatro edições, nesta ordem:

**(a)** Teste primeiro, em `apps/api/tests/test_vima_briefing.py`:

```python
def test_a_linha_de_ausencia_carrega_o_kind(client: TestClient, headers):
    """Sem o kind na linha, a pergunta do DNA não tem como se colar à ausência certa."""
    corpo = client.get("/vima/briefing", headers=headers).json()
    pendentes = [linha for linha in corpo["linhas"] if linha["secao"] == "PENDENTE"]
    assert pendentes, "o tenant novo deveria ter ao menos uma pendência"
    assert pendentes[0]["kind"], "a linha de pendência não trouxe o kind"
```

**(b)** `apps/api/app/modules/vima/composer.py` — acrescentar o campo a `Candidato` (junto de
`chave` e `dias`, que já são "só ausência preenche"):

```python
    # Só ausência preenche: a chave e a intensidade que alimentam a regra do silêncio.
    chave: str | None = None
    dias: int = 0
    # Só ausência preenche: é o que permite ao V2 colar a pergunta de calibração na linha que a
    # motivou. Fica separado de `chave` de propósito — aquela é uma chave composta com
    # `subject_id`, e fatiá-la no front acoplaria a tela ao formato dela.
    kind: str = ""
```

a `Linha`:

```python
class Linha(BaseModel):
    secao: str
    module: str
    texto: str
    kind: str = ""
```

em `_da_ausencia`, passar `kind=a.kind` junto de `chave=` e `dias=`, e na construção do payload
(linha 120):

```python
        linhas=[
            Linha(secao=c.secao, module=c.module, texto=c.texto, kind=c.kind) for c in mantidas
        ],
```

> **Nota:** `Linha` pode ser dataclass em vez de `BaseModel` — abra o arquivo e siga o que
> estiver lá. O default `""` é obrigatório em qualquer um dos dois: **briefings já gravados não
> têm `kind` no payload**, e ler um deles sem default estoura na desserialização.

**(c)** `apps/api/app/modules/vima/schemas.py` — `LinhaOut` ganha `kind: str = ""`. `to_out` já
faz `LinhaOut(**linha)`, então nada mais muda ali.

**(d)** `packages/shared-types/src/index.ts` — `BriefingLinha` ganha `kind: string`.

- [ ] **Step 6: Rodar as duas suítes**

Run: `cd apps/api && pytest tests/test_vima_briefing.py -v && cd ../.. && pnpm --filter @e1p/web test`
Expected: PASS nas duas.

- [ ] **Step 7: Commit**

```bash
git add apps/web/src/features/dna/GanchoDaVima.tsx apps/web/src/features/dna/GanchoDaVima.test.tsx apps/web/src/features/vima/BriefingPage.tsx apps/api/app/modules/vima/schemas.py packages/shared-types/src/index.ts apps/api/tests/test_vima_briefing.py
git commit -m "feat: a Calibração chega colada à ausência que a motivou [V2]"
```

---

### Task 11: Os ganchos de contexto

**Files:**
- Modify: `apps/web/src/features/crm/` (a tela que lista contatos, depois de criar um)
- Modify: `apps/web/src/features/receivables/`, `apps/web/src/features/quotes/`, `apps/web/src/features/payables/`, `apps/web/src/features/agenda/`
- Test: nenhum novo — `GanchoDaVima` já está coberto

**Interfaces:**
- Consumes: `GanchoDaVima`

Os cinco ganchos declarados no catálogo, cada um numa tela onde a resposta é óbvia:

| Gancho | Tela | Perguntas que ele serve |
|---|---|---|
| `crm.cliente.criado` | lista de contatos do CRM | `cliente.quem_e`, `cliente.decisao_tempo` |
| `receivables.cobranca.criada` | lista de cobranças | `dinheiro.atraso_reacao`, `dinheiro.formas_recebimento` |
| `quotes.orcamento.criado` | lista de orçamentos | `oferta.ticket_tipico`, `oferta.proposta_formal`, `limites.desconto` |
| `payables.conta.criada` | lista de contas a pagar | `dinheiro.emite_nota` |
| `agenda.evento.criado` | agenda | `limites.horario_contato` |

- [ ] **Step 1: Localizar as cinco telas**

Run: `ls apps/web/src/features/crm apps/web/src/features/receivables apps/web/src/features/quotes apps/web/src/features/payables apps/web/src/features/agenda`
Anote o componente de LISTA de cada módulo (o que a rota do menu abre).

- [ ] **Step 2: Inserir o gancho em cada uma**

Em cada tela, logo **abaixo do cabeçalho e acima da lista**, inserir:

```tsx
<GanchoDaVima gancho="crm.cliente.criado" />
```

(trocando o valor pelo gancho da tabela acima). O import:

```tsx
import GanchoDaVima from "../dna/GanchoDaVima";
```

**Só isso.** O componente já decide sozinho se aparece — a cadência inteira mora no servidor, e
uma tela sem pergunta do dia renderiza `null`.

- [ ] **Step 3: Rodar a suíte do front**

Run: `pnpm --filter @e1p/web test`
Expected: PASS. Se algum teste de lista quebrar por causa do `api.get` não mockado para
`/dna/pendente`, adicione o mock devolvendo `{ data: null }` — é o caminho de "sem pergunta
hoje", que é o normal.

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/features/
git commit -m "feat: os cinco ganchos de contexto do DNA [V2]"
```

---

# ONDA 5 — A aba "A sua empresa"

### Task 12: Os cinco eixos em `/config`

**Files:**
- Create: `apps/web/src/features/config/EmpresaDnaTab.tsx`
- Modify: `apps/web/src/features/config/ConfiguracoesPage.tsx`
- Test: `apps/web/src/features/config/EmpresaDnaTab.test.tsx`

**Interfaces:**
- Consumes: `PerguntaDaVima`, `GET /dna/faltantes?gancho=<eixo>` não serve aqui — use `GET /dna/respostas` + o catálogo completo
- Produces: `EmpresaDnaTab()`; nova aba `"dna"` em `ConfiguracoesPage`

> **Ajuste necessário no backend:** a aba precisa listar **todas** as 45 com o que já foi
> respondido. Acrescentar a `apps/api/app/modules/dna/router.py`:
>
> ```python
> @router.get("/catalogo", response_model=list[PerguntaOut])
> def catalogo(
>     user: CurrentUser = Depends(require_module("settings")),
> ) -> list[PerguntaOut]:
>     """As 45, na ordem do catálogo. A aba de configurações é a única superfície SEM cadência —
>     a pessoa escolheu estar ali, e esconder pergunta de quem foi procurá-la é hostil."""
>     return [to_out(p) for p in catalog.PERGUNTAS]
> ```
>
> `catalog` já está importado no router desde a Task 5 — nenhum import novo. Escreva o teste em
> `tests/test_dna_router.py` afirmando `len(resposta) == 45` antes de implementar.

- [ ] **Step 1: Escrever o teste que falha**

```tsx
// apps/web/src/features/config/EmpresaDnaTab.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import EmpresaDnaTab from "./EmpresaDnaTab";

const CATALOGO = [
  {
    key: "oferta.o_que_vende",
    classe: "retrato",
    eixo: "oferta",
    texto: "O que você vende?",
    formato: "escolha",
    opcoes: [{ rotulo: "Serviço por projeto", valor: "servico_projeto" }],
  },
  {
    key: "limites.nunca_faco",
    classe: "retrato",
    eixo: "limites",
    texto: "O que você nunca faz?",
    formato: "texto",
    opcoes: [],
  },
];

vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), put: vi.fn(), post: vi.fn() },
  apiErrorMessage: (e: unknown) => String(e),
}));

describe("EmpresaDnaTab", () => {
  it("agrupa por eixo e mostra quantas faltam", async () => {
    vi.mocked(api.get).mockImplementation((url: string) =>
      Promise.resolve({
        data: url === "/dna/catalogo" ? CATALOGO : { "oferta.o_que_vende": "servico_projeto" },
      }),
    );

    render(<EmpresaDnaTab />);

    await waitFor(() => expect(screen.getByText("Oferta")).toBeInTheDocument());
    expect(screen.getByText("Limites")).toBeInTheDocument();
    expect(screen.getByText(/1 de 2 respondidas/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `pnpm --filter @e1p/web test -- EmpresaDnaTab`
Expected: FAIL — o módulo não existe.

- [ ] **Step 3: Escrever a aba**

Criar `apps/web/src/features/config/EmpresaDnaTab.tsx`:

```tsx
import type { DnaPergunta } from "@e1p/shared-types";
import { useCallback, useEffect, useState } from "react";
import { api } from "../../lib/api";
import PerguntaDaVima from "../dna/PerguntaDaVima";

const EIXOS: { key: DnaPergunta["eixo"]; titulo: string; descricao: string }[] = [
  { key: "oferta", titulo: "Oferta", descricao: "O que você vende e como cobra" },
  { key: "cliente", titulo: "Cliente", descricao: "Quem compra e como chega até você" },
  { key: "ritmo", titulo: "Ritmo", descricao: "Como é a sua semana" },
  { key: "dinheiro", titulo: "Dinheiro", descricao: "Como você recebe e reage a atraso" },
  { key: "limites", titulo: "Limites", descricao: "O que você nunca faz" },
];

/**
 * A saída para quem quiser sentar e responder tudo de uma vez.
 *
 * **É a única superfície SEM cadência.** A regra de uma pergunta por dia existe para proteger
 * de interrupção; aqui a pessoa foi procurar, e esconder pergunta de quem foi atrás dela seria
 * hostil. Tudo editável a qualquer momento — inclusive o que já foi respondido.
 */
export default function EmpresaDnaTab() {
  const [catalogo, setCatalogo] = useState<DnaPergunta[]>([]);
  const [respostas, setRespostas] = useState<Record<string, unknown>>({});

  const carregar = useCallback(async () => {
    const [{ data: perguntas }, { data: dadas }] = await Promise.all([
      api.get<DnaPergunta[]>("/dna/catalogo"),
      api.get<Record<string, unknown>>("/dna/respostas"),
    ]);
    setCatalogo(perguntas);
    setRespostas(dadas);
  }, []);

  useEffect(() => {
    carregar();
  }, [carregar]);

  if (catalogo.length === 0) {
    return <p className="text-sm text-neutral-400">Carregando…</p>;
  }

  const respondidas = catalogo.filter((p) => p.key in respostas).length;

  return (
    <div className="space-y-8">
      <p className="text-sm text-neutral-500">
        {respondidas} de {catalogo.length} respondidas. Não precisa responder tudo de uma vez — a
        Vima pergunta aos poucos, no momento em que cada resposta faz sentido.
      </p>

      {EIXOS.map((eixo) => {
        const doEixo = catalogo.filter((p) => p.eixo === eixo.key);
        if (doEixo.length === 0) return null;
        return (
          <section key={eixo.key} className="space-y-3">
            <div>
              <h2 className="text-lg font-semibold text-neutral-800">{eixo.titulo}</h2>
              <p className="text-xs text-neutral-500">{eixo.descricao}</p>
            </div>
            {doEixo.map((p) => (
              <div key={p.key}>
                {p.key in respostas ? (
                  <div className="rounded-xl border border-neutral-200 bg-neutral-50 p-4">
                    <p className="text-sm text-neutral-600">{p.texto}</p>
                    <p className="mt-1 text-sm font-medium text-neutral-800">
                      {rotulo(p, respostas[p.key])}
                    </p>
                    <button
                      type="button"
                      onClick={() => {
                        const resto = { ...respostas };
                        delete resto[p.key];
                        setRespostas(resto);
                      }}
                      className="mt-2 text-xs text-neutral-400 underline"
                    >
                      Mudar
                    </button>
                  </div>
                ) : (
                  <PerguntaDaVima
                    pergunta={p}
                    source="config"
                    onPronto={carregar}
                    onPular={carregar}
                  />
                )}
              </div>
            ))}
          </section>
        );
      })}
    </div>
  );
}

/** Mostra o RÓTULO que o dono escolheu, não o valor interno que o sistema guarda. */
function rotulo(pergunta: DnaPergunta, valor: unknown): string {
  if (pergunta.formato === "texto") return String(valor);
  const lista = Array.isArray(valor) ? valor : [valor];
  return lista
    .map((v) => pergunta.opcoes.find((o) => o.valor === v)?.rotulo ?? String(v))
    .join(", ");
}
```

- [ ] **Step 4: Registrar a aba**

Modificar `apps/web/src/features/config/ConfiguracoesPage.tsx`:

```tsx
import { Building2, Check, Filter, MessageCircle, Sparkles, Workflow } from "lucide-react";
import EmpresaDnaTab from "./EmpresaDnaTab";
```

```tsx
type Tab = "empresa" | "dna" | "canais" | "integracoes" | "vendas";

const TABS: { key: Tab; label: string; icon: typeof Building2 }[] = [
  { key: "empresa", label: "Empresa", icon: Building2 },
  { key: "dna", label: "A sua empresa", icon: Sparkles },
  { key: "canais", label: "Canais", icon: MessageCircle },
  { key: "integracoes", label: "Integrações", icon: Workflow },
  { key: "vendas", label: "Vendas", icon: Filter },
];
```

E no corpo, junto às outras abas:

```tsx
        {tab === "dna" && <EmpresaDnaTab />}
```

> **Atenção:** `PERFIL_TABS` continua `["empresa", "vendas"]`. A aba do DNA **não** entra ali —
> ela salva sozinha, pergunta a pergunta, e o botão "Salvar" do perfil não tem o que fazer com
> ela.

- [ ] **Step 5: Rodar as duas suítes**

Run: `cd apps/api && pytest && cd ../.. && pnpm --filter @e1p/web test`
Expected: PASS nas duas.

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/features/config/ apps/api/app/modules/dna/router.py apps/api/tests/test_dna_router.py
git commit -m "feat: a aba 'A sua empresa' com os cinco eixos do DNA [V2]"
```

---

## Fechamento

- [ ] **Rodar tudo, uma última vez**

Run: `cd apps/api && pytest && cd ../.. && pnpm --filter @e1p/web test && pnpm --filter @e1p/web build`
Expected: PASS nos três.

- [ ] **Reconferir o head do Alembic**

Run: `ls apps/api/migrations/versions/ | sort | tail -3`
Se a frente paralela mergeou uma `0076` enquanto isto era construído, renumerar para `0077` e
ajustar `down_revision`. **É a terceira vez que este repositório paga essa lição** — 0072, 0076,
e a próxima.

- [ ] **Validação manual em ~360px**

Abrir `/dna/nucleo` e a aba "A sua empresa" em 360px de largura e conferir que nenhum bloco
estoura. **Bloqueia release, não bloqueia merge** — mesmo padrão das telas de Contas & Saldos,
Conversas e do briefing. `toContain("flex-wrap")` não prova layout: meça.

- [ ] **Registrar no `CLAUDE.md`**

Acrescentar a seção do V2 seguindo o formato das seções da Vima já existentes: o que mudou, as
duas guardas de classe, a inversão do núcleo, a limpeza do silêncio ao recalibrar, e as dívidas
(cobrança sem antecedência, sem medição de ativação, 45 perguntas não validadas com dono real).

- [ ] **Abrir o PR**

```bash
git push -u origin feat/vima-dna-da-empresa
```

⚠️ `git push` é **exclusivo do @devops** neste repositório. Delegue.
