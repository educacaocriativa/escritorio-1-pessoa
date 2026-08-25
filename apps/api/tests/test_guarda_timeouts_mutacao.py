"""A guarda de timeouts da corrida de mutação dispara com o NÚMERO REAL na mensagem (issue #213).

⚠️ Este teste EXECUTA `scripts/guarda-timeouts-mutacao.mjs`, o arquivo de verdade — não uma
reimplementação da regra escrita aqui. Uma cópia passaria a concordar consigo mesma no dia em que
alguém editasse o script, que é a família de teste que este repositório documenta como "passa e não
prova nada" (§5.1). Mesma escolha do `test_deploy_guarda_checkout_limpo.py`, que extrai a linha do
`deploy.sh` em tempo de teste.

O defeito que ele fecha: no Stryker, `Timeout` conta como MORTO
(`mutation-testing-metrics`, `totalDetected = timeout + killed`). Numa máquina carregada os
mutantes estouram o relógio por CONTENÇÃO DE CPU e são creditados como se um teste os tivesse
pego — a régua fica otimista exatamente quando o ambiente está pior. Medido no #213: 12 timeouts
em `contas.ts` local (todos `StringLiteral` em declaração de constante, onde não existe laço
possível) contra 0 na CI, e o módulo mediu ~3,8 pontos a mais do que a verdade.

Por que um teste em Python para um script Node: é onde este repositório já testa ferramental que
não é código de aplicação (o `Caddyfile` e o `deploy.sh` têm os seus aqui), e é o job
`cross-tenant-rls` — required em `main` — que os roda, com a guarda anti-vacuidade que REPROVA o
skip. Um guarda de CI que só rodasse no job noturno seria verificado uma vez por dia, tarde.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

import pytest


def _acha_guarda() -> pathlib.Path | None:
    """Sobe procurando o script — o mesmo motivo do gate do Caddyfile e do `deploy.sh`.

    A suíte também roda DENTRO da imagem da API (`test-in-prod-image`), onde só `apps/api` foi
    copiado: `scripts/` não existe lá. Resolver a raiz por índice fixo (`parents[3]`) estoura
    `IndexError` na COLETA e derruba o job inteiro por um teste que nem era sobre a API.
    """
    for pai in pathlib.Path(__file__).resolve().parents:
        candidato = pai / "scripts" / "guarda-timeouts-mutacao.mjs"
        if candidato.is_file():
            return candidato
    return None


GUARDA = _acha_guarda()

pytestmark = pytest.mark.skipif(
    GUARDA is None or shutil.which("node") is None,
    reason=(
        "precisa de scripts/guarda-timeouts-mutacao.mjs e do node — o job cross-tenant-rls "
        "tem os dois, e lá o SKIP é reprovado pela guarda anti-vacuidade"
    ),
)


def _relatorio(
    tmp_path: pathlib.Path,
    *,
    timeouts: int,
    mortos: int = 100,
    sobreviventes: int = 10,
    sem_cobertura: int = 0,
    quebra: float | None = 80,
    mutador: str = "StringLiteral",
) -> str:
    """Escreve um `mutation.json` no formato que o Stryker emite (schemaVersion 1.0).

    O formato é o do artefato REAL: `files[caminho].mutants[]` com `status`, `mutatorName` e
    `location.start.line`. Conferido contra o `mutation-report` da corrida 32557684625.
    """
    mutantes = []
    linha = 1

    def empurra(quantos: int, status: str, nome: str) -> None:
        nonlocal linha
        for _ in range(quantos):
            mutantes.append(
                {
                    "id": str(linha),
                    "mutatorName": nome,
                    "status": status,
                    "replacement": '""',
                    "location": {
                        "start": {"line": linha, "column": 1},
                        "end": {"line": linha, "column": 9},
                    },
                }
            )
            linha += 1

    empurra(timeouts, "Timeout", mutador)
    empurra(mortos, "Killed", "ConditionalExpression")
    empurra(sobreviventes, "Survived", "StringLiteral")
    empurra(sem_cobertura, "NoCoverage", "StringLiteral")

    relatorio: dict = {
        "schemaVersion": "1.0",
        "files": {
            "src/features/financeiro/contas.ts": {
                "language": "typescript",
                "source": "",
                "mutants": mutantes,
            }
        },
    }
    if quebra is not None:
        relatorio["thresholds"] = {"high": 80, "low": 60, "break": quebra}

    destino = tmp_path / "mutation.json"
    destino.write_text(json.dumps(relatorio), encoding="utf-8")
    return str(destino)


def _roda(*args: str) -> subprocess.CompletedProcess[str]:
    assert GUARDA is not None
    return subprocess.run(
        ["node", str(GUARDA), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )


# ── O LIMIAR ─────────────────────────────────────────────────────────────────────────────────────


def test_limiar_padrao_e_cinco(tmp_path: pathlib.Path) -> None:
    """5 é o limiar embutido — e a mensagem o DIZ, sem ninguém precisar passar `--limiar`.

    Pin do número: `LIMIAR_PADRAO = 5` sai da folga entre o regime medido (1 timeout, reproduzido
    em 3 de 3 corridas de CI, sempre o mesmo mutante de laço real em `grade.ts:294`) e o defeito
    observado (12 timeouts num único módulo na máquina carregada). Trocar o 5 sem trocar a
    evidência quebra este teste.
    """
    r = _roda(_relatorio(tmp_path, timeouts=0))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "limiar: 5" in r.stdout


def test_dentro_do_limiar_passa_e_nao_grita(tmp_path: pathlib.Path) -> None:
    """1 timeout — o número que a CI mede — passa, e a saída não fala em medição não confiável."""
    r = _roda(_relatorio(tmp_path, timeouts=1))
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.startswith("OK: 1 timeout(s)")
    assert "NAO E CONFIAVEL" not in r.stdout


def test_acima_do_limiar_reprova_com_o_numero_real_na_mensagem(tmp_path: pathlib.Path) -> None:
    """O caso do #213: 12 timeouts. Reprova, e a mensagem carrega o 12 — não um texto genérico."""
    r = _roda(_relatorio(tmp_path, timeouts=12))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "ERRO: 12 timeouts" in r.stdout
    assert "limiar: 5" in r.stdout
    assert "MEDICAO NAO E CONFIAVEL" in r.stdout
    assert "maquina dedicada" in r.stdout


def test_empate_exato_no_limiar_passa(tmp_path: pathlib.Path) -> None:
    """Comparação ESTRITA (`>`), a mesma convenção do `thresholds.break` do Stryker.

    Este teste e o seguinte são o par que mata a mutação `>` → `>=`: um deles fica vermelho em
    qualquer das duas trocas.
    """
    r = _roda(_relatorio(tmp_path, timeouts=5))
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.startswith("OK: 5 timeout(s)")


def test_um_acima_do_limiar_reprova(tmp_path: pathlib.Path) -> None:
    r = _roda(_relatorio(tmp_path, timeouts=6))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "ERRO: 6 timeouts" in r.stdout


def test_limiar_pela_cli_substitui_o_padrao(tmp_path: pathlib.Path) -> None:
    """`--limiar N` existe para quem mede um módulo só, onde 5 é folgado demais."""
    relatorio = _relatorio(tmp_path, timeouts=3)
    assert _roda(relatorio).returncode == 0
    apertado = _roda(relatorio, "--limiar", "2")
    assert apertado.returncode == 1, apertado.stdout + apertado.stderr
    assert "limiar: 2" in apertado.stdout


# ── OS MUTANTES APARECEM, COM ARQUIVO, LINHA E MUTADOR ───────────────────────────────────────────


def test_lista_os_mutantes_que_estouraram(tmp_path: pathlib.Path) -> None:
    """Sem a lista, "12 timeouts" não é acionável: é a lista que separa laço real de máquina.

    `StringLiteral` em declaração de constante não pode enlaçar — foi assim que o #213 provou que
    os 12 eram contenção de CPU, e não mutantes lentos.
    """
    r = _roda(_relatorio(tmp_path, timeouts=2, mutador="StringLiteral"), "--limiar", "1")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "src/features/financeiro/contas.ts:1 (StringLiteral)" in r.stdout
    assert "src/features/financeiro/contas.ts:2 (StringLiteral)" in r.stdout


# ── A ARITMÉTICA DO PIOR CASO ────────────────────────────────────────────────────────────────────


def test_score_medido_reproduz_o_numero_do_stryker(tmp_path: pathlib.Path) -> None:
    """Réplica da corrida 32478357936, que o próprio Stryker reportou como 83,52.

    1479 mortos + 1 timeout + 269 sobreviventes + 23 sem cobertura = 1772 válidos;
    (1479 + 1) / 1772 = 83,52%. Se este número deixar de bater, a fórmula do script divergiu da do
    Stryker e todo o resto da saída passa a mentir junto.
    """
    r = _roda(_relatorio(tmp_path, timeouts=1, mortos=1479, sobreviventes=269, sem_cobertura=23))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Score medido: 83.52%" in r.stdout
    # Sem o timeout no numerador: 1479 / 1772 = 83,47.
    assert "seria 83.47%" in r.stdout
    assert "ate 0.06 ponto(s) de otimismo" in r.stdout


def test_avisa_quando_o_pior_caso_cruza_o_break(tmp_path: pathlib.Path) -> None:
    """A pergunta que importa: a dúvida é grande o bastante para derrubar o `thresholds.break`?

    80 mortos + 12 timeouts + 8 sobreviventes = 100 válidos. Medido 92; sem os timeouts, 80,00 —
    que NÃO cruza (a comparação é estrita). Com 13 timeouts o pior caso vira 79 e cruza.
    """
    acima = _roda(_relatorio(tmp_path, timeouts=12, mortos=80, sobreviventes=8), "--limiar", "99")
    assert acima.returncode == 0, acima.stdout + acima.stderr
    assert "ainda fica acima dele (80.00 >= 80)" in acima.stdout

    cruza = _roda(_relatorio(tmp_path, timeouts=13, mortos=79, sobreviventes=8), "--limiar", "99")
    assert "CRUZA o limiar (79.00 < 80)" in cruza.stdout


def test_relatorio_sem_thresholds_nao_quebra(tmp_path: pathlib.Path) -> None:
    """Corridas anteriores ao #189 não trazem `thresholds` no JSON — o artefato de e422278 é uma."""
    r = _roda(_relatorio(tmp_path, timeouts=1, quebra=None))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "thresholds.break" not in r.stdout


# ── FALHA-DURA ANTI-VACUIDADE ────────────────────────────────────────────────────────────────────


def test_sem_relatorio_nao_e_aprovacao(tmp_path: pathlib.Path) -> None:
    """Entrada faltando devolve 2, e NÃO 0.

    Um guarda que fica verde quando não achou o que guardar é a mesma falha que o `ci.yml` já
    reprova no `rls_e2e` e nos gates de `infra/`: silêncio indistinguível de aprovação.
    """
    r = _roda(str(tmp_path / "nao-existe.json"))
    assert r.returncode == 2
    assert "NAO e aprovacao" in r.stderr


def test_json_invalido_nao_e_aprovacao(tmp_path: pathlib.Path) -> None:
    quebrado = tmp_path / "mutation.json"
    quebrado.write_text("{ isto nao e json", encoding="utf-8")
    r = _roda(str(quebrado))
    assert r.returncode == 2


def test_sem_argumento_ensina_o_uso(tmp_path: pathlib.Path) -> None:
    """Regressão: o filtro de `--limiar` já comeu o caminho do relatório quando a flag estava
    ausente (`k !== i + 1` vira `k !== 0`), e o uso mais comum devolvia 2 reclamando de argumento
    faltando. Este teste fixa que o 2 só sai quando o argumento REALMENTE falta."""
    r = _roda()
    assert r.returncode == 2
    assert "uso: node scripts/guarda-timeouts-mutacao.mjs" in r.stderr
