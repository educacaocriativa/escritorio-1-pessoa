"""A dependencia de fuso desta suite, DECLARADA -- e o guarda que a cobra (issue #210).

O #184 (PR #202) fixou `TZ: America/Sao_Paulo` no job `frontend`, e a #210 perguntou o obvio:
e os dois jobs Python, que nao fixam fuso em lugar nenhum? A resposta so podia vir de medicao,
e veio.

**Medido em 22/08/2026**, a suite inteira (`pytest -m "not rls_e2e"`, 2201 testes) rodada tres
vezes com o relogio do PROCESSO em fusos diferentes:

    fuso do processo        data local no momento da corrida    resultado
    UTC-3 (maquina)         2026-08-22                          2200 passed, 1 skipped
    UTC  (`TZ=UTC0`)        2026-08-22                          2200 passed, 1 skipped
    UTC+9 (`TZ=JST-9`)      2026-08-23  <-- o dia VIRADO        2200 passed, 1 skipped

O terceiro e o que fecha a classe. O #185 (PR #203) mostrou que varrer so em UTC nao prova nada
quando UTC e UTC-3 CONCORDAM sobre o dia; aqui o processo em UTC+9 ja estava em 23/08 enquanto o
UTC ainda marcava 22/08, e mesmo assim nenhum teste mudou de resposta.

**Por que zero, estruturalmente:** o sistema deriva "hoje" de `hoje_do_tenant()`, que e
`datetime.now(UTC)` convertido pelo `ZoneInfo` do TENANT (#78, migration 0073) -- nunca o fuso
da maquina. Uma varredura AST de `app/` acha 7 chamadas de relogio aparente e 5 delas sao
`func.now()` do SQLAlchemy (SQL, nao processo). Sobram DUAS, nenhuma em caminho de negocio, e o
teste `test_o_app_NAO_ganhou_relogio_de_maquina_novo` abaixo e quem as mantem sendo duas.

**Por isso NAO se fixou `TZ` nos jobs Python do `ci.yml`.** A #210 e explicita em nao querer "as
duas por reflexo": fixar um fuso que nada le seria congelar uma configuracao inerte -- e pior,
daria a impressao de que a suite passou a depender dela. O que faltava era a DECLARACAO, que e
este arquivo, e a DETECCAO, que e o guarda em `conftest.py`.
"""
from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.core.tz import DEFAULT_TENANT_TIMEZONE, local_date, tenant_today
from tests import conftest
from tests.conftest import _incoerencia_de_fuso

API_DIR = Path(__file__).resolve().parents[1]

# Um instante escolhido para DISCORDAR: 23/08 em UTC e em Toquio, 22/08 em Sao Paulo.
# Sem uma borda assim o teste passaria com qualquer implementacao -- e a vacuidade e a familia
# de defeito que este repo mais paga (ver `test_investments.py::..._SAI_do_termo_P3`).
INSTANTE_DA_BORDA = datetime(2026, 8, 23, 1, 30, tzinfo=UTC)


def test_a_ancora_de_hoje_NAO_le_o_fuso_do_processo() -> None:
    """A declaracao, mecanica: "hoje" e funcao do INSTANTE e do fuso do TENANT, e de mais nada.

    O controle negativo (os dois asserts do meio) e obrigatorio: sem ele este teste passaria
    mesmo que `INSTANTE_DA_BORDA` caisse num horario em que os tres fusos concordam, que e
    exatamente como o #185 deixou uma dependencia de fuso escapar de uma varredura em UTC.
    """
    # CONTROLE: o instante realmente separa os tres relogios.
    assert INSTANTE_DA_BORDA.date().isoformat() == "2026-08-23", "em UTC ja e dia 23"
    assert local_date(INSTANTE_DA_BORDA, "Asia/Tokyo").isoformat() == "2026-08-23", "Toquio, 23"

    # A ANCORA: o tenant brasileiro ainda esta no dia 22, e nenhum fuso de processo muda isso.
    assert tenant_today(DEFAULT_TENANT_TIMEZONE, now=INSTANTE_DA_BORDA).isoformat() == "2026-08-22"


def test_o_guarda_cala_quando_nao_ha_TZ_declarado() -> None:
    """O caso do CI: sem `TZ`, nao ha promessa a conferir. Fixar fuso continua NAO sendo exigido."""
    assert _incoerencia_de_fuso(None, timedelta(0), INSTANTE_DA_BORDA) is None
    assert _incoerencia_de_fuso("", timedelta(0), INSTANTE_DA_BORDA) is None


def test_o_guarda_cala_quando_o_TZ_e_honrado() -> None:
    """Linux com `TZ=America/Sao_Paulo`: o processo entrega -03:00, que e o que o nome promete."""
    assert _incoerencia_de_fuso(
        "America/Sao_Paulo", timedelta(hours=-3), INSTANTE_DA_BORDA
    ) is None


def test_o_guarda_cala_diante_de_TZ_no_formato_POSIX() -> None:
    """`JST-9` e `UTC0` sao o unico jeito de medir fuso no Windows -- o guarda nao pode atrapalhar.

    O `zoneinfo` nao decifra POSIX TZ, entao nao ha com o que comparar. Calar aqui e desenho:
    foi com `JST-9` que as 2200 linhas verdes em UTC+9 desta docstring foram medidas.
    """
    assert _incoerencia_de_fuso("JST-9", timedelta(hours=9), INSTANTE_DA_BORDA) is None
    assert _incoerencia_de_fuso("UTC0", timedelta(0), INSTANTE_DA_BORDA) is None


def test_o_guarda_ACUSA_o_TZ_que_o_Windows_nao_honra() -> None:
    """A armadilha real, com os numeros REAIS medidos nesta maquina em 22/08/2026.

    No Windows nao existe `time.tzset()` e quem le `TZ` e a CRT da Microsoft, que nao entende
    nome IANA: diante de `America/Sao_Paulo` ela ADIVINHA e entrega **+01:00** -- nem o fuso do
    Brasil (-03:00) nem o do CI (UTC). `Asia/Tokyo` cai no mesmo +01:00, e nao em +09:00.

    E o que torna a receita da propria #210 ("rode sob `Asia/Tokyo`") uma medicao que nao mede:
    devolve "0 quebras" porque varreu UTC+1, nao UTC+9. Sem este guarda, o sintoma seria uma
    data errada num teste de negocio -- e alguem procurando o bug em `hoje_do_tenant()`.
    """
    msg = _incoerencia_de_fuso("America/Sao_Paulo", timedelta(hours=1), INSTANTE_DA_BORDA)
    assert msg is not None, "TZ que promete -03:00 num processo em +01:00 TEM de ser acusado"
    assert "FUSO DECLARADO QUE O PROCESSO NAO HONRA" in msg
    assert "America/Sao_Paulo" in msg, "a mensagem tem de dizer QUAL fuso mentiu"
    # `-03:00`, e nao o `-1 day, 21:00:00` cru do `timedelta` -- ver `_offset_legivel`.
    assert "-03:00" in msg, "...e o offset PROMETIDO, legivel"
    assert "+01:00" in msg, "...e o offset EFETIVO, que e o outro lado da contradicao"
    assert "-1 day" not in msg, "offset negativo nao pode vazar na forma crua do timedelta"
    assert "time.tzset()" in msg, "...e a causa, para nao mandar ninguem depurar data de negocio"

    # Toquio pelo mesmo caminho: +01:00 no lugar de +09:00.
    tokyo = _incoerencia_de_fuso("Asia/Tokyo", timedelta(hours=1), INSTANTE_DA_BORDA)
    assert tokyo is not None and "Asia/Tokyo" in tokyo


def test_o_guarda_esta_LIGADO_no_import_do_conftest(monkeypatch: pytest.MonkeyPatch) -> None:
    """A regra pode estar certa e nao estar PLUGADA -- e foi assim que o worker ficou sem fiacao.

    Nao da para provar isto trocando `TZ` de verdade: sem `time.tzset()` o processo ja escolheu
    seu fuso e nao reabre a escolha. Entao o que se prova aqui e a COSTURA: quando a regra
    acusa, `_guarda_de_fuso()` levanta -- e ele e chamado no corpo do modulo do `conftest`.
    """
    monkeypatch.setattr(conftest, "_incoerencia_de_fuso", lambda *_: "FUSO MENTIROSO (fixture)")
    with pytest.raises(RuntimeError, match="FUSO MENTIROSO"):
        conftest._guarda_de_fuso()

    fonte = (API_DIR / "tests" / "conftest.py").read_text(encoding="utf-8")
    chamadas = [
        no
        for no in ast.parse(fonte).body
        if isinstance(no, ast.Expr)
        and isinstance(no.value, ast.Call)
        and isinstance(no.value.func, ast.Name)
        and no.value.func.id == "_guarda_de_fuso"
    ]
    assert chamadas, "`_guarda_de_fuso()` precisa ser CHAMADO no corpo do conftest, nao so definido"


# As DUAS unicas leituras do relogio da MAQUINA em `app/`, cada uma com o motivo de ser tolerada.
# Qualquer sitio novo reprova este gate -- de proposito: e o unico jeito de a medicao das 2200
# linhas verdes continuar valendo depois que este PR sair de vista.
RELOGIO_DE_MAQUINA_DECLARADO = {
    "app/modules/crm/schemas.py": (
        "validator de `birthdate` ('nao pode estar no futuro'). Depende do fuso do processo de "
        "verdade, mas a tolerancia e de UM DIA sobre uma DATA DE NASCIMENTO -- nao ha caso em "
        "que a diferenca decida alguma coisa. Trocar por `hoje_do_tenant` exigiria `db` num "
        "schema Pydantic, que e acoplamento pior que a divida."
    ),
    "app/seed_staging.py": (
        "script de seed de STAGING, fora de qualquer caminho de request. Nao ha tenant cujo "
        "fuso consultar no momento em que roda."
    ),
}


def _relogios_de_maquina(fonte: str) -> list[int]:
    """Linhas com `date.today()`, `.utcnow()` ou `datetime.now()` SEM fuso.

    `func.now()` do SQLAlchemy e excluido a dedo: e uma funcao SQL avaliada pelo BANCO, nao um
    relogio deste processo. Sao 5 das 7 ocorrencias de `.now()` em `app/`, e sem esta excecao o
    gate seria 5/7 ruido -- gate ruidoso e gate que alguem apaga.
    """
    achados: list[int] = []
    for no in ast.walk(ast.parse(fonte)):
        if not isinstance(no, ast.Call) or not isinstance(no.func, ast.Attribute):
            continue
        if isinstance(no.func.value, ast.Name) and no.func.value.id == "func":
            continue
        if no.func.attr in ("today", "utcnow"):
            achados.append(no.lineno)
        elif no.func.attr == "now" and not no.args and not no.keywords:
            achados.append(no.lineno)
    return achados


def test_o_app_NAO_ganhou_relogio_de_maquina_novo() -> None:
    """Gate: em `app/`, "hoje" vem de `hoje_do_tenant()` -- e a lista de excecoes e FECHADA.

    Sem consumidor mecanico, a unica coisa entre o produto e um `date.today()` novo num service
    e alguem lembrar. E a suite ficaria verde do mesmo jeito: foi medido que ela e indiferente
    ao fuso do processo, entao ela NAO reprovaria o sitio novo. Este gate e o que reprova.
    """
    novos: dict[str, list[int]] = {}
    for arquivo in sorted((API_DIR / "app").rglob("*.py")):
        rel = arquivo.relative_to(API_DIR).as_posix()
        linhas = _relogios_de_maquina(arquivo.read_text(encoding="utf-8"))
        if linhas and rel not in RELOGIO_DE_MAQUINA_DECLARADO:
            novos[rel] = linhas

    assert not novos, (
        "relogio da MAQUINA novo em app/: "
        + "; ".join(f"{f}:{ls}" for f, ls in sorted(novos.items()))
        + " -- use `hoje_do_tenant(db)` (a ancora do #78). Se a leitura for mesmo legitima, "
        "declare-a em RELOGIO_DE_MAQUINA_DECLARADO com o motivo, como as outras duas."
    )

    # CONTROLE: as duas declaradas continuam existindo. Sem isto o gate viraria vacuo no dia em
    # que alguem consertasse os dois sitios e esquecesse de tirar a lista -- e passaria a
    # aprovar qualquer coisa, calado.
    # `encoding="utf-8"` explicito: sem ele o default no Windows e cp1252 e `seed_staging.py`
    # (que tem acento) estoura com UnicodeDecodeError. Foi este proprio controle que pegou.
    ainda_existem = {
        f
        for f in RELOGIO_DE_MAQUINA_DECLARADO
        if _relogios_de_maquina((API_DIR / f).read_text(encoding="utf-8"))
    }
    assert ainda_existem == set(RELOGIO_DE_MAQUINA_DECLARADO), (
        "sitio declarado que sumiu: tire-o de RELOGIO_DE_MAQUINA_DECLARADO. "
        f"declarados={sorted(RELOGIO_DE_MAQUINA_DECLARADO)} ainda_existem={sorted(ainda_existem)}"
    )
