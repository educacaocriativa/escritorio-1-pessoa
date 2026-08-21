"""A guarda de "checkout limpo" do deploy.sh recusa o que deve e ACEITA o que a máquina carrega.

⚠️ Este teste EXECUTA a linha que está no `deploy.sh`, extraída dele em tempo de teste — não uma
cópia dela escrita aqui. Uma cópia passaria a concordar consigo mesma no dia em que alguém
editasse o script, que é exatamente a família de teste que este repositório documenta como
"passa e não prova nada" (§5.1). Se a linha mudar, é a linha nova que roda.

O defeito que ele fecha: `git status --porcelain` lista arquivo NÃO RASTREADO como `?? caminho`,
e a instância da AWS carrega três de propósito (`DEPLOY-AWS.md`, `docker-compose.override.yml`,
`Caddyfile.single`) para o `git pull` nunca conflitar. A guarda original abortava em 100% das
execuções naquele host — medido no primeiro `--dry-run` real, depois do merge do #167.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest


def _acha_infra() -> pathlib.Path | None:
    """Sobe procurando o `infra/` — o mesmo motivo do gate do Caddyfile.

    A suíte também roda DENTRO da imagem da API, onde só `apps/api` foi copiado. Resolver a raiz
    por índice fixo (`parents[3]`) estoura `IndexError` na COLETA e derruba o job inteiro por um
    teste que nem era sobre a API.
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


def _linha_da_guarda() -> str:
    """A linha do `deploy.sh` que decide se o checkout está limpo."""
    assert INFRA is not None
    fonte = (INFRA / "scripts" / "deploy.sh").read_text(encoding="utf-8")
    linhas = [
        linha.strip()
        for linha in fonte.splitlines()
        if "git status --porcelain" in linha and not linha.lstrip().startswith("#")
    ]
    assert len(linhas) == 1, f"esperava UMA linha de guarda, achei {len(linhas)}: {linhas}"
    return linhas[0]


def _repo(tmp_path: pathlib.Path) -> pathlib.Path:
    """Um repositório com um commit e um arquivo versionado."""
    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q", ".")
    git("config", "user.email", "teste@e1p")
    git("config", "user.name", "teste")
    # ⚠️ NÃO é supérfluo. `bash` nesta máquina de dev é o do WSL, que traz um git PRÓPRIO com
    # `core.autocrlf` diferente do git do Windows que cria o repo aqui — e os dois discordam
    # sobre um arquivo escrito com LF: o git do Windows vê limpo, o do WSL vê ` M`. O repo de
    # teste nasceria SUJO e os dois casos de "aceita" falhariam por um motivo que não tem nada a
    # ver com a guarda. Fixar no repo (e não por `-c`) é o que faz os dois lerem a mesma coisa.
    git("config", "core.autocrlf", "false")
    (tmp_path / "versionado.txt").write_text("original\n", encoding="utf-8")
    git("add", "versionado.txt")
    git("commit", "-q", "-m", "base")
    return tmp_path


def _guarda_aceita(repo: pathlib.Path) -> bool:
    """Roda a guarda REAL nesse repo. True = deploy seguiria; False = abortaria."""
    script = f'morre() {{ echo "ABORTADO: $*" >&2; exit 1; }}\nRAIZ="."\n{_linha_da_guarda()}\n'
    r = subprocess.run(["bash", "-c", script], cwd=repo, capture_output=True, text=True)
    return r.returncode == 0


def test_arquivo_nao_rastreado_NAO_impede_o_deploy(tmp_path):
    """O caso que abortava a AWS em toda execução — um `?? DEPLOY-AWS.md` sozinho bastava."""
    repo = _repo(tmp_path)
    (repo / "DEPLOY-AWS.md").write_text("runbook local, nao versionado\n", encoding="utf-8")
    assert _guarda_aceita(repo), (
        "a guarda recusou um checkout cujo único desvio é arquivo NÃO RASTREADO. A instância da "
        "AWS carrega três de propósito (DEPLOY-AWS.md, docker-compose.override.yml, "
        "Caddyfile.single) para o `git pull` nunca conflitar: assim o deploy.sh não roda ali."
    )


def test_arquivo_VERSIONADO_modificado_ABORTA(tmp_path):
    """Controle positivo — sem ele, a guarda poderia aceitar tudo e o teste acima passaria igual."""
    repo = _repo(tmp_path)
    (repo / "versionado.txt").write_text("editado direto no servidor\n", encoding="utf-8")
    assert not _guarda_aceita(repo), (
        "a guarda aceitou um arquivo versionado modificado. É o caso 'editei em produção para "
        "testar e esqueci': o `git pull --ff-only` do passo seguinte falharia no meio do deploy."
    )


def test_mudanca_em_STAGE_tambem_ABORTA(tmp_path):
    """`--untracked-files=no` não pode cegar a guarda para o que já foi adicionado ao índice."""
    repo = _repo(tmp_path)
    (repo / "versionado.txt").write_text("editado e adicionado\n", encoding="utf-8")
    subprocess.run(["git", "add", "versionado.txt"], cwd=repo, check=True, capture_output=True)
    assert not _guarda_aceita(repo), "mudança em stage passou pela guarda"


def test_checkout_limpo_passa(tmp_path):
    """Sem este, os dois 'ABORTA' acima passariam com uma guarda que recusa tudo."""
    assert _guarda_aceita(_repo(tmp_path))
