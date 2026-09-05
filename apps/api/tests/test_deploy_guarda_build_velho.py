"""As duas guardas do `deploy.sh` contra "o web está servindo build velho".

⚠️ Como o gate irmão (`test_deploy_guarda_checkout_limpo.py`), este teste EXECUTA as linhas que
estão no `deploy.sh`, extraídas dele em tempo de teste — nunca uma cópia escrita aqui. Cópia passa
a concordar consigo mesma no dia em que alguém edita o script (§5.1).

O defeito que a primeira guarda fecha: a classificação `FRONT` olhava só o CAMINHO (`apps/web`,
`packages`) e, com ela ligada, o script exigia que o hash do bundle mudasse. Mas `apps/web/public/`
é copiado VERBATIM pelo Vite para o `dist/` — por construção não pode mudar o `index-*.js`. O
deploy do #300 (um único arquivo em `public/`, a verificação de propriedade do Google) subiu
inteiro e correto e mesmo assim ABORTOU na última asserção, com a produção já saudável. Mesma
classe: `apps/web/e2e/` e os 96 `*.test.tsx`, que não entram no bundle.

O defeito que a segunda guarda fecha é o oposto — o ponto cego que a primeira abriria sozinha: com
`FRONT=0`, NADA mais verificava que o web havia sido reconstruído. A checagem de imagem não depende
de conteúdo mudar: compara a imagem que o container em pé roda com a imagem recém-construída. Se o
`up -d --build` construiu e não recriou o container, as duas divergem — que é exatamente "servindo
build velho", e vale para `public/`, para e2e e para código real.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest


def _acha_infra() -> pathlib.Path | None:
    """Sobe procurando o `infra/`.

    A suíte também roda DENTRO da imagem da API, onde só `apps/api` foi copiado. Resolver a raiz
    por índice fixo (`parents[3]`) estoura `IndexError` na COLETA e derruba o job inteiro.
    """
    for pai in pathlib.Path(__file__).resolve().parents:
        candidato = pai / "infra"
        if (candidato / "scripts" / "deploy.sh").is_file():
            return candidato
    return None


INFRA = _acha_infra()

pytestmark = pytest.mark.skipif(
    INFRA is None or shutil.which("bash") is None or shutil.which("git") is None,
    reason=(
        "precisa de infra/, bash e git — o job cross-tenant-rls tem os três, "
        "e lá o SKIP é reprovado pela guarda anti-vacuidade"
    ),
)


def _fonte() -> str:
    assert INFRA is not None
    return (INFRA / "scripts" / "deploy.sh").read_text(encoding="utf-8")


def _bash(
    script: str, *args: str, cwd: pathlib.Path | None = None
) -> subprocess.CompletedProcess[str]:
    """Roda `script` no bash entregando-o por STDIN em BYTES, nunca por `bash -c` e nunca em texto.

    ⚠️ Nenhuma das duas escolhas é estilo; cada uma fecha uma falha SILENCIOSA medida aqui:

    1. `bash -c` não serve. Nesta máquina de dev o `bash` do PATH é o do WSL, e o interop
       Windows→WSL EXPANDE os `$` do argumento antes de o bash parsear: as atribuições rodam, mas
       toda referência a variável chega vazia. Com `set -x`, a linha da classificação virava
       `git diff --name-only .. -- apps/web packages ''`.

    2. `text=True` não serve. No Windows ele traduz `\\n` em `\\r\\n` ao escrever no pipe, e o CR
       entra no script: `set -uo pipefail\\r` vira "invalid option name" e `HEAD~1\\r..HEAD\\r`
       vira "bad revision". Bytes passam intactos.

    Os dois defeitos falham para o MESMO lado — o script sai 0, o stdout vem plausível e a guarda
    parece ter respondido. Por isso quem chama esta função confere o stderr: um erro do git aqui
    não pode virar "FRONT=0, teste verde". No Linux do CI as duas escolhas são indiferentes.
    """
    r = subprocess.run(
        ["bash", "-s", "--", *args],
        input=script.encode("utf-8"),
        cwd=cwd,
        capture_output=True,
    )
    return subprocess.CompletedProcess(
        r.args,
        r.returncode,
        r.stdout.decode("utf-8", "replace"),
        r.stderr.decode("utf-8", "replace"),
    )


def _linha_unica(agulha: str) -> str:
    """A ÚNICA linha não-comentada do deploy.sh que contém `agulha`."""
    linhas = [
        linha.strip()
        for linha in _fonte().splitlines()
        if agulha in linha and not linha.lstrip().startswith("#")
    ]
    assert len(linhas) == 1, f"esperava UMA linha com {agulha!r}, achei {len(linhas)}: {linhas}"
    return linhas[0]


# --------------------------------------------------------------- guarda 1: classificação FRONT


def _classificacao_front() -> str:
    """As linhas REAIS que decidem se o diff mexe no que vira bundle."""
    return _linha_unica("FORA_DO_BUNDLE=(") + "\n" + _linha_unica("FRONT=1") + "\n"


def _front_para(tmp_path: pathlib.Path, caminho: str) -> int:
    """Cria um repo cujo último commit mexe SÓ em `caminho`, e roda a classificação real nele."""

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q", ".")
    git("config", "user.email", "teste@e1p")
    git("config", "user.name", "teste")
    # Mesmo motivo do gate irmão: o `bash` desta máquina é o do WSL e traz um git PRÓPRIO, com
    # `core.autocrlf` diferente do git que cria o repo aqui. Sem fixar, o repo nasce sujo.
    git("config", "core.autocrlf", "false")
    (tmp_path / "base.txt").write_text("base\n", encoding="utf-8")
    git("add", "base.txt")
    git("commit", "-q", "-m", "base")

    alvo = tmp_path / caminho
    alvo.parent.mkdir(parents=True, exist_ok=True)
    alvo.write_text("conteudo\n", encoding="utf-8")
    git("add", "--all")
    git("commit", "-q", "-m", "mudanca")

    script = (
        "set -uo pipefail\n"
        'SHA_ANTES="HEAD~1"\n'
        'SHA_ALVO="HEAD"\n'
        "FRONT=0\n"
        + _classificacao_front()
        + 'echo "$FRONT"\n'
    )
    r = _bash(script, cwd=tmp_path)
    assert r.returncode == 0, f"a classificação estourou: {r.stderr}"
    # Sem esta linha o teste mente: um `fatal:` do git faz o `grep -q` não achar nada, FRONT fica
    # 0 e os três testes de "NÃO marca front" passam VERDES sem a guarda ter sido exercitada.
    assert not r.stderr.strip(), f"a classificação escreveu em stderr (git falhou?): {r.stderr}"
    return int(r.stdout.strip())


def test_arquivo_em_public_NAO_marca_front(tmp_path):
    """O caso do #300: um arquivo em `public/` é copiado verbatim, o bundle NÃO pode mudar."""
    assert _front_para(tmp_path, "apps/web/public/google43f12893cae1f247.html") == 0, (
        "`apps/web/public/` marcou FRONT=1. O Vite copia essa pasta verbatim para o `dist/`: com "
        "FRONT=1 o script exige uma mudança de hash do bundle que é impossível por construção, e "
        "aborta um deploy que subiu inteiro e correto (medido em 04/09/2026, deploy do #300)."
    )


def test_e2e_NAO_marca_front(tmp_path):
    """Os `*.spec.ts` do Playwright não são importados pela entrada — não entram no bundle."""
    assert _front_para(tmp_path, "apps/web/e2e/alcance-360.spec.ts") == 0


def test_teste_de_unidade_NAO_marca_front(tmp_path):
    """Os 96 `*.test.tsx` do vitest também não: mesma classe de falso alarme."""
    assert _front_para(tmp_path, "apps/web/src/features/legal/PaginasLegais.test.tsx") == 0


def test_codigo_do_front_MARCA_front(tmp_path):
    """Controle positivo. Sem ele, uma classificação que devolve 0 para TUDO passaria acima."""
    assert _front_para(tmp_path, "apps/web/src/features/legal/PrivacidadePage.tsx") == 1, (
        "código-fonte do front não marcou FRONT=1 — a guarda do bundle deixou de existir"
    )


def test_packages_MARCA_front(tmp_path):
    """O bundle também come `packages/` (o Dockerfile copia os dois para o build)."""
    assert _front_para(tmp_path, "packages/tipos/src/index.ts") == 1


def test_backend_NAO_marca_front(tmp_path):
    """Controle: o que nunca foi front continua fora."""
    assert _front_para(tmp_path, "apps/api/app/main.py") == 0


# ------------------------------------------------------ guarda 2: o container roda a imagem nova


def _imagem_atual(em_pe: str, construida: str) -> bool:
    """Roda a função REAL do deploy.sh. True = o container roda a imagem recém-construída."""
    partes = _fonte().split("imagem_do_web_esta_atual()", 1)
    assert len(partes) == 2, "não achei a função `imagem_do_web_esta_atual` no deploy.sh"
    linhas = partes[1].splitlines()
    fim = next(i for i, linha in enumerate(linhas) if linha.startswith("}"))
    funcao = "imagem_do_web_esta_atual()" + "\n".join(linhas[: fim + 1])
    script = funcao + '\nimagem_do_web_esta_atual "$1" "$2"\n'
    return _bash(script, em_pe, construida).returncode == 0


SHA_A = "sha256:1111111111111111111111111111111111111111111111111111111111111111"
SHA_B = "sha256:2222222222222222222222222222222222222222222222222222222222222222"


def test_container_na_imagem_recem_construida_PASSA():
    assert _imagem_atual(SHA_A, SHA_A)


def test_container_em_imagem_ANTIGA_reprova():
    """O caso que a guarda existe para pegar: construiu a nova e não recriou o container."""
    assert not _imagem_atual(SHA_A, SHA_B), (
        "o container em pé roda uma imagem DIFERENTE da recém-construída e a guarda aceitou — "
        "é literalmente 'o web está servindo build velho'"
    )


def test_valor_vazio_reprova():
    """Um `docker inspect` que falha devolve string vazia; vazio == vazio não pode virar OK."""
    assert not _imagem_atual("", ""), "duas strings vazias passaram pela guarda"
    assert not _imagem_atual(SHA_A, ""), "imagem construída vazia passou pela guarda"
