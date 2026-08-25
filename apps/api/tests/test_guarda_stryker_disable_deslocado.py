"""A guarda de diretivas `Stryker disable next-line` deslocadas dispara com arquivo e linha corretos
na mensagem (issue #229).

⚠️ Este teste EXECUTA `scripts/guarda-stryker-disable-deslocado.mjs`, o arquivo de verdade — não uma
reimplementação da regra escrita aqui. Uma cópia passaria a concordar consigo mesma no dia em que
alguém editasse o script, a mesma família de teste que este repositório documenta como "passa e não
prova nada" (§5.1). Mesma escolha do `test_guarda_timeouts_mutacao.py` e do
`test_deploy_guarda_checkout_limpo.py`.

O defeito que ele fecha: `// Stryker disable next-line <mutador>` só suprime a mutação da linha
LITERAL seguinte. Achado na triagem do #214 (PR #222): `financeiro/ledger.ts` e
`financeiro/dreMatrixEntries.ts` traziam a diretiva SETE LINHAS acima do alvo — a linha seguinte
literal era outro comentário, então a supressão nunca existiu, e o mutante apareceu como `Survived`
em dois relatórios de CI sem ninguém notar. Os dois casos foram consertados no PR #222; esta guarda
fecha a reincidência.

Por que um teste em Python para um script Node: é onde este repositório já testa ferramental que não
é código de aplicação (o `Caddyfile`, o `deploy.sh` e a guarda de timeouts da mutação têm os seus
aqui), e é o job `cross-tenant-rls` — required em `main` — que os roda, com a guarda anti-vacuidade
que REPROVA o skip.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess
import textwrap

import pytest


def _acha_guarda() -> pathlib.Path | None:
    """Sobe procurando o script — o mesmo motivo do gate do Caddyfile e do `deploy.sh`.

    A suíte também roda DENTRO da imagem da API (`test-in-prod-image`), onde só `apps/api` foi
    copiado: `scripts/` não existe lá. Resolver a raiz por índice fixo estoura `IndexError` na
    COLETA e derruba o job inteiro por um teste que nem era sobre a API.
    """
    for pai in pathlib.Path(__file__).resolve().parents:
        candidato = pai / "scripts" / "guarda-stryker-disable-deslocado.mjs"
        if candidato.is_file():
            return candidato
    return None


GUARDA = _acha_guarda()

pytestmark = pytest.mark.skipif(
    GUARDA is None or shutil.which("node") is None,
    reason=(
        "precisa de scripts/guarda-stryker-disable-deslocado.mjs e do node — o job "
        "cross-tenant-rls tem os dois, e lá o SKIP é reprovado pela guarda anti-vacuidade"
    ),
)


def _roda(*args: str) -> subprocess.CompletedProcess[str]:
    assert GUARDA is not None
    return subprocess.run(
        ["node", str(GUARDA), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )


def _escreve(tmp_path: pathlib.Path, nome: str, conteudo: str) -> pathlib.Path:
    caminho = tmp_path / nome
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(textwrap.dedent(conteudo), encoding="utf-8")
    return caminho


# ── CASO POSITIVO (CONTROLE) — diretiva encostada no alvo ──────────────────────────────────────────


def test_diretiva_encostada_no_alvo_passa(tmp_path: pathlib.Path) -> None:
    """A mesma forma de `pagar/baixa.ts:197` — nada entre a diretiva e o código."""
    _escreve(
        tmp_path,
        "ok.ts",
        """\
        // Explicação qualquer sobre o mutante equivalente.
        // Stryker disable next-line ArithmeticOperator
        export const X = 1 + 2;
        """,
    )
    r = _roda(str(tmp_path))
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.startswith("OK: nenhuma diretiva")


def test_os_quatro_arquivos_reais_do_e1p_passam_limpo() -> None:
    """Controle contra a árvore REAL: roda a guarda direto em `apps/web/src`.

    Os quatro pontos citados na issue #229 (grade.ts, dreMatrixEntries.ts, ledger.ts, baixa.ts) têm
    de estar, hoje, com a diretiva encostada no alvo — senão este teste é o primeiro a acusar.
    """
    raiz = None
    for pai in pathlib.Path(__file__).resolve().parents:
        candidato = pai / "apps" / "web" / "src"
        if candidato.is_dir():
            raiz = candidato
            break
    if raiz is None:
        pytest.skip("apps/web/src não está presente neste checkout (ex.: imagem da API)")

    r = _roda(str(raiz))
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.startswith("OK: nenhuma diretiva")


# ── CASO NEGATIVO (REGRESSÃO) — diretiva deslocada ──────────────────────────────────────────────────


def test_diretiva_seguida_de_comentario_reprova_com_arquivo_e_linha(tmp_path: pathlib.Path) -> None:
    """O caso EXATO do #214/#222: a diretiva na linha 2, o alvo real sete linhas abaixo."""
    _escreve(
        tmp_path,
        "features/financeiro/quebrado.ts",
        """\
        // 0 onde o original devolve 1, e o sort só observa o SINAL do comparador.
        // Stryker disable next-line EqualityOperator
        // Medido: 23.600 arranjos de 2 a 60 itens com datas repetidas, ZERO divergências.
        // Não leva `disable` porque a directive é por MUTADOR, e desligar
        // `ConditionalExpression` aqui apagaria junto o mutante `true`, que HOJE morre no
        // teste de empate.
        export function cmp(a: number, b: number): number {
          return a < b ? 1 : a > b ? -1 : 0;
        }
        """,
    )
    r = _roda(str(tmp_path))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "ERRO: 1 diretiva(s)" in r.stdout
    assert "features/financeiro/quebrado.ts:2" in r.stdout
    assert "linha seguinte não-branca (linha 3) é outro COMENTÁRIO" in r.stdout


def test_diretiva_no_fim_do_arquivo_reprova(tmp_path: pathlib.Path) -> None:
    """Sem linha nenhuma depois da diretiva não há o que suprimir — também é defeito."""
    _escreve(
        tmp_path,
        "orfao.ts",
        """\
        export const Y = 1;
        // Stryker disable next-line ArithmeticOperator
        """,
    )
    r = _roda(str(tmp_path))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "orfao.ts:2" in r.stdout
    assert "ÚLTIMA linha do arquivo" in r.stdout


def test_linha_em_branco_entre_diretiva_e_alvo_e_ignorada_na_busca(tmp_path: pathlib.Path) -> None:
    """Linha em branco pura NÃO conta como "outra linha" — só comentário conta."""
    _escreve(
        tmp_path,
        "com-branco.ts",
        """\
        // Stryker disable next-line ArithmeticOperator

        export const Z = 1 + 1;
        """,
    )
    r = _roda(str(tmp_path))
    assert r.returncode == 0, r.stdout + r.stderr


def test_bloco_de_comentario_apos_a_diretiva_tambem_reprova(tmp_path: pathlib.Path) -> None:
    """Não é só `//`: um `/* ... */` ou uma linha `*` de continuação também não é código."""
    _escreve(
        tmp_path,
        "com-bloco.ts",
        """\
        // Stryker disable next-line ArithmeticOperator
        /** JSDoc que por engano ficou entre a diretiva e o alvo. */
        export const W = 3 + 4;
        """,
    )
    r = _roda(str(tmp_path))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "com-bloco.ts:1" in r.stdout


def test_multiplas_diretivas_deslocadas_aparecem_todas(tmp_path: pathlib.Path) -> None:
    _escreve(
        tmp_path,
        "a.ts",
        """\
        // Stryker disable next-line ArithmeticOperator
        // comentário no meio
        export const A = 1;
        """,
    )
    _escreve(
        tmp_path,
        "b.ts",
        """\
        // Stryker disable next-line EqualityOperator
        // outro comentário no meio
        export const B = 2;
        """,
    )
    r = _roda(str(tmp_path))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "ERRO: 2 diretiva(s)" in r.stdout
    assert "a.ts:1" in r.stdout
    assert "b.ts:1" in r.stdout


# ── FALHA-DURA ANTI-VACUIDADE ────────────────────────────────────────────────────────────────────


def test_diretorio_inexistente_nao_e_aprovacao(tmp_path: pathlib.Path) -> None:
    r = _roda(str(tmp_path / "nao-existe"))
    assert r.returncode == 2
    assert "NAO e aprovacao" in r.stderr


def test_diretorio_sem_ts_nao_e_aprovacao(tmp_path: pathlib.Path) -> None:
    """Nenhum `.ts`/`.tsx` encontrado — uma guarda que fica verde aqui não guardou nada."""
    _escreve(tmp_path, "nao-e-typescript.py", "x = 1\n")
    r = _roda(str(tmp_path))
    assert r.returncode == 2
    assert "NAO e aprovacao" in r.stderr


# ── SEM ARGUMENTO, USA O ALVO PADRÃO (apps/web/src) ─────────────────────────────────────────────


def test_sem_argumento_usa_apps_web_src_como_alvo_padrao() -> None:
    """Sem argumento o script varre `apps/web/src` da raiz do repo — não falha por falta de alvo."""
    r = _roda()
    assert r.returncode in (0, 1), r.stdout + r.stderr
    assert "apps/web/src" in r.stdout
