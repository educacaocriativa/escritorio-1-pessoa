"""Gate: nenhum `TODAY`/`HOJE` de teste lê o relógio real no IMPORT do módulo (issue #232 —
3ª rodada do mesmo defeito: #84 corrigiu, #90 e #101 voltaram por outras frestas).

**O mecanismo, provado em `test_financial_intelligence_projection.py` antes desta correção:**
`TODAY = tenant_today(DEFAULT_TENANT_TIMEZONE)` era lido UMA VEZ, no import do módulo de teste —
mas o SERVIÇO sob teste (o endpoint HTTP, que não injeta `today=`) recalcula "hoje" de novo, na
hora da REQUISIÇÃO. Se a meia-noite do tenant virasse entre as duas leituras, fixture e serviço
discordavam de um dia e a asserção quebrava — raro, não-determinístico e, por isso mesmo, já
"corrigido" duas vezes sem a classe de defeito morrer (#90, #101).

**A correção estrutural**, aplicada nos 3 arquivos exercitáveis desta issue (ver o comentário no
topo de cada um): `TODAY`/`HOJE` passa a vir de um instante FIXO (`tenant_today(DEFAULT_TENANT_
TIMEZONE, now=FIXED_NOW)`) — nunca do relógio — e, onde o SERVIÇO também precisa concordar
(endpoints que não aceitam `today=`), uma fixture `autouse` tranca `hoje_do_tenant` no MESMO
`FIXED_NOW`. O outro padrão igualmente válido, usado em 6 arquivos mais antigos (`test_vima_
absences.py`, `test_dna_cadencia.py`, `test_bank_reconciliation_report.py`, `test_admin_nao_expoe_
recebimento_fora_do_trilho.py`, `test_bank_ciclos.py`, `test_vima_trends.py`), é uma data LITERAL
(`date(2026, 8, 6)`) — mais simples quando o endpoint sob teste aceita `today`/`start`/`end`
injetáveis e não há guarda de "data futura" a coordenar.

**Este gate é o complemento de
`test_fuso_do_processo.py::test_o_app_NAO_ganhou_relogio_de_maquina_novo`** — aquele varre `app/`
(relógio da MÁQUINA num caminho de negócio); este varre `tests/` (relógio lido para ANCORAR uma
fixture de teste no import do módulo). São eixos diferentes e complementares, não duplicados: um
`TODAY` fixo por `date(2026, 8, 6)` nunca aciona nenhum dos dois; um `date.today()` dentro de
`app/modules/x/service.py` aciona só aquele; um `TODAY = tenant_today(...)` sem `now=` no import de
um teste aciona só este.

**Por que só o nível de MÓDULO** (e não qualquer `tenant_today(...)` em `tests/`): ler o relógio
DENTRO do corpo de uma função de teste, na hora em que a asserção roda, não é o defeito — é a
leitura do fixture ficar CONGELADA no import e o serviço ler de novo depois que é a fresta. Uma
varredura
que reprovasse todo `tenant_today()` sem `now=` em `tests/` pegaria ~10 usos legítimos (`hoje =
tenant_today(...)` dentro do corpo de um teste, em `test_agenda_por_contato.py`, `test_investments.
py`, `test_payables_reactivate.py` etc.) e o gate seria ruído — ruído é gate que alguém apaga.
"""
from __future__ import annotations

import ast
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent

# Os dois nomes que a suíte usa, por convenção, para "a data que ancora as fixtures do arquivo".
NOMES_DE_ANCORA = {"TODAY", "HOJE"}

# Chamadas que resolvem "hoje" a partir do relógio quando `now=`/instante fixo NÃO é passado.
NOMES_DE_HOJE_INJETAVEL = {"tenant_today", "hoje_do_tenant"}

# Leituras diretas do relógio da máquina/processo (mesmo vocabulário do gate de `app/`).
ATRIBUTOS_DE_RELOGIO = {"today", "utcnow", "now"}


def _le_relogio(expressao: ast.AST) -> bool:
    """A subárvore de uma expressão (o lado direito de `TODAY = ...`) lê o relógio real?

    Cobre tanto a chamada direta (`TODAY = tenant_today(TZ)`) quanto uma expressão que a contém
    (`TODAY = tenant_today(TZ) - timedelta(days=1)`, `TODAY = date.today()` etc.) — o `ast.walk`
    percorre a árvore inteira da expressão, não só o nó de topo.
    """
    for no in ast.walk(expressao):
        if not isinstance(no, ast.Call):
            continue
        func = no.func
        if isinstance(func, ast.Name) and func.id in NOMES_DE_HOJE_INJETAVEL:
            tem_now = any(kw.arg == "now" for kw in no.keywords)
            if not tem_now:
                return True
        elif isinstance(func, ast.Attribute) and func.attr in ATRIBUTOS_DE_RELOGIO:
            return True
    return False


def _ancoras_de_relogio_no_import(fonte: str) -> list[tuple[str, int]]:
    """`TODAY`/`HOJE` atribuídos no CORPO do módulo (nunca dentro de função/fixture) a partir do
    relógio real — direto ou por trás de `tenant_today`/`hoje_do_tenant` sem `now=`."""
    achados: list[tuple[str, int]] = []
    arvore = ast.parse(fonte)
    for no in arvore.body:  # só o nível do MÓDULO — ler dentro de uma função é outra história
        if not isinstance(no, ast.Assign):
            continue
        alvos = [t.id for t in no.targets if isinstance(t, ast.Name)]
        alvos_de_ancora = [nome for nome in alvos if nome in NOMES_DE_ANCORA]
        if not alvos_de_ancora:
            continue
        if _le_relogio(no.value):
            achados.append((", ".join(alvos_de_ancora), no.lineno))
    return achados


# Exceções FECHADAS — cada uma com o motivo, no molde de `RELOGIO_DE_MAQUINA_DECLARADO` do gate de
# `app/`. A issue #232 corrigiu os 3 arquivos exercitáveis em SQLite; estes dois pedem Postgres/RLS
# real (marcados `rls_e2e`) e não são exercitáveis neste ambiente (sem Docker disponível) — ficam
# como dívida DECLARADA, não silenciosa.
TODAY_PENDENTE_DE_POSTGRES = {
    "test_financial_intelligence_projection_rls.py": (
        "mesma classe de defeito do arquivo principal (issue #232), mas o cenário sob teste exige "
        "Postgres/RLS real (marcado `rls_e2e`) — não foi possível medir a mutação (envelhecer "
        "TODAY em 1 dia) nem aplicar/validar a correção sem Docker neste ambiente. Aplicar o "
        "mesmo padrão de `FIXED_NOW` + fixture autouse de `test_financial_intelligence_"
        "projection.py` quando houver Postgres disponível."
    ),
    "test_payment_queue_rls.py": (
        "mesmo motivo do arquivo acima — RLS real, sem Docker neste ambiente."
    ),
}


def test_nenhum_TODAY_HOJE_novo_le_o_relogio_no_import() -> None:
    """Gate: em `tests/`, `TODAY`/`HOJE` de módulo não pode vir do relógio real — e a lista de
    exceções é FECHADA (mesmo desenho do gate de `app/`, ver `test_fuso_do_processo.py`)."""
    novos: dict[str, list[tuple[str, int]]] = {}
    for arquivo in sorted(TESTS_DIR.glob("*.py")):
        if arquivo.name == Path(__file__).name:
            continue  # este próprio arquivo não define TODAY/HOJE — cita os nomes em dados/texto
        achados = _ancoras_de_relogio_no_import(arquivo.read_text(encoding="utf-8"))
        if achados and arquivo.name not in TODAY_PENDENTE_DE_POSTGRES:
            novos[arquivo.name] = achados

    assert not novos, (
        "TODAY/HOJE novo lido do RELÓGIO no import de um módulo de teste (issue #232 — a mesma "
        "classe de defeito que já voltou 2x, #90 e #101): "
        + "; ".join(f"{f}:{ls}" for f, ls in sorted(novos.items()))
        + ". Use uma data FIXA (`date(2026, 8, 6)`, o padrão de `test_vima_absences.py`) ou, se o "
        "endpoint sob teste também precisa concordar (não aceita `today=`), `tenant_today(..., "
        "now=FIXED_NOW)` + a fixture autouse que tranca `hoje_do_tenant` no mesmo instante (o "
        "padrão de `test_financial_intelligence_projection.py`, pós issue #232). Se a leitura for "
        "mesmo necessária, declare em TODAY_PENDENTE_DE_POSTGRES com o motivo, como as duas RLS."
    )

    # CONTROLE: as exceções declaradas ainda existem E ainda têm o padrão — sem isto o gate viraria
    # vácuo no dia em que os RLS forem corrigidos e ninguém tirar a entrada da lista (o mesmo
    # controle que `test_o_app_NAO_ganhou_relogio_de_maquina_novo` faz para `app/`).
    ainda_pendentes = {
        nome
        for nome in TODAY_PENDENTE_DE_POSTGRES
        if (TESTS_DIR / nome).exists()
        and _ancoras_de_relogio_no_import((TESTS_DIR / nome).read_text(encoding="utf-8"))
    }
    assert ainda_pendentes == set(TODAY_PENDENTE_DE_POSTGRES), (
        "arquivo declarado em TODAY_PENDENTE_DE_POSTGRES que sumiu ou já foi corrigido: tire-o da "
        f"lista. declarados={sorted(TODAY_PENDENTE_DE_POSTGRES)} "
        f"ainda_pendentes={sorted(ainda_pendentes)}"
    )


def test_controle_positivo_o_gate_ACUSA_TODAY_novo_lido_do_relogio() -> None:
    """Controle positivo (issue #232, AC da story): fabrica um arquivo de teste TEMPORÁRIO dentro
    de `tests/` com `TODAY` lido do relógio sem `now=`, mostra o gate REPROVANDO e nomeando esse
    arquivo, e remove o arquivo em seguida — a prova de que a regra dispara de verdade, não só de
    que a lista de exceções está vazia (o mesmo controle que `test_o_guarda_esta_LIGADO_no_import_
    do_conftest` faz para o gate irmão)."""
    nome = "test_ZZZ_fabricado_para_o_controle_positivo_232.py"
    caminho = TESTS_DIR / nome
    assert not caminho.exists(), f"limpeza de uma corrida anterior falhou: {caminho} já existe"
    caminho.write_text(
        "from app.core.tz import DEFAULT_TENANT_TIMEZONE, tenant_today\n"
        "\n"
        "TODAY = tenant_today(DEFAULT_TENANT_TIMEZONE)  # fabricado: sem now=, lê o relogio\n",
        encoding="utf-8",
    )
    try:
        # 1) a unidade que decide "isto é uma leitura de relógio" acusa o caso fabricado:
        achados = _ancoras_de_relogio_no_import(caminho.read_text(encoding="utf-8"))
        assert achados, "o gate não acusou um TODAY fabricado lido do relógio — regra vazia"
        assert achados[0][0] == "TODAY"

        # 2) e a varredura de nível de SUÍTE nomeia justamente ESTE arquivo entre os novos:
        novos: dict[str, list[tuple[str, int]]] = {}
        for arquivo in sorted(TESTS_DIR.glob("*.py")):
            if arquivo.name == Path(__file__).name:
                continue
            ach = _ancoras_de_relogio_no_import(arquivo.read_text(encoding="utf-8"))
            if ach and arquivo.name not in TODAY_PENDENTE_DE_POSTGRES:
                novos[arquivo.name] = ach
        assert nome in novos, f"o gate não nomeou o arquivo fabricado: {sorted(novos)}"
    finally:
        caminho.unlink(missing_ok=True)
    assert not caminho.exists(), "o arquivo fabricado do controle positivo não foi limpo"


def test_controle_negativo_data_literal_e_now_explicito_nao_disparam_o_gate() -> None:
    """Controle negativo: os dois padrões CORRETOS (data literal e `now=` explícito) não acionam a
    regra — sem isto, um gate que reprovasse qualquer `TODAY = ...` seria ruído, não sinal."""
    literal = "from datetime import date\nTODAY = date(2026, 8, 6)\n"
    assert _ancoras_de_relogio_no_import(literal) == []

    com_now = (
        "from datetime import UTC, datetime\n"
        "from app.core.tz import DEFAULT_TENANT_TIMEZONE, tenant_today\n"
        "FIXED_NOW = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)\n"
        "TODAY = tenant_today(DEFAULT_TENANT_TIMEZONE, now=FIXED_NOW)\n"
    )
    assert _ancoras_de_relogio_no_import(com_now) == []

    dentro_de_funcao = (
        "from app.core.tz import DEFAULT_TENANT_TIMEZONE, tenant_today\n"
        "def test_algo():\n"
        "    hoje = tenant_today(DEFAULT_TENANT_TIMEZONE)\n"
        "    assert hoje\n"
    )
    assert _ancoras_de_relogio_no_import(dentro_de_funcao) == []
