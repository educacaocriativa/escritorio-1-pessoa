"""Gate estrutural do Caddyfile: nenhum bloco que dependa de config externa mora nele (issue #151).

**O parse do Caddyfile é ALL-OR-NOTHING.** Um bloco que falha ao adaptar derruba o arquivo
INTEIRO — não só aquele bloco. Com `CLOUDFLARE_API_TOKEN` vazio, o `dns cloudflare {$...}` do
wildcard fazia o Caddy recusar tudo (`missing API token`) e **nem o domínio único subia**, mesmo
com o certificado dele intacto em disco. Em 2026-08-20 isso derrubou a produção por ~40 min.

Por isso os blocos opcionais mudaram de casa: vivem em `infra/caddy/optional/`, entram em
`/etc/caddy/conf.d/` só quando a env correspondente está preenchida (`infra/caddy/entrypoint.sh`),
e o Caddyfile os puxa por `import`. Glob sem correspondência é **no-op** (medido: `caddy validate`
devolve `Valid configuration` com um `warn`, não erro).

Este gate é de TEXTO, e é o que impede alguém de mover um bloco de volta para dentro do arquivo
principal — a validação de verdade (build da imagem + `caddy validate` nos cinco cenários) é
manual, com Docker, e não roda no CI. Ver a dívida no CLAUDE.md.
"""
import pathlib

import pytest

INFRA = pathlib.Path(__file__).resolve().parents[3] / "infra"
CADDYFILE = INFRA / "Caddyfile"
OPCIONAIS = INFRA / "caddy" / "optional"

# Diretivas que EXIGEM configuração externa para adaptar. Nenhuma pode estar no arquivo base.
# `dns <provider>` cobre o caso real (cloudflare) e o próximo provedor de DNS que aparecer.
_DIRETIVAS_QUE_EXIGEM_CONFIG = ("dns cloudflare", "{$CLOUDFLARE_API_TOKEN}")


def test_caddyfile_base_nao_tem_bloco_que_exige_config_externa():
    texto = CADDYFILE.read_text(encoding="utf-8")
    # Só as linhas de CÓDIGO: o cabeçalho explica o defeito e cita o nome da diretiva de
    # propósito, e um gate que reprovasse o comentário obrigaria a apagar a explicação.
    codigo = "\n".join(
        linha for linha in texto.splitlines() if not linha.lstrip().startswith("#")
    )
    for diretiva in _DIRETIVAS_QUE_EXIGEM_CONFIG:
        assert diretiva not in codigo, (
            f"`{diretiva}` voltou para o infra/Caddyfile. O parse é all-or-nothing: com a env "
            "vazia, isto derruba a config INTEIRA e o domínio único para de ser servido "
            "(issue #151). O bloco pertence a infra/caddy/optional/, ativado por env."
        )


def test_caddyfile_base_importa_os_opcionais():
    codigo = CADDYFILE.read_text(encoding="utf-8")
    assert "import /etc/caddy/conf.d/*.caddy" in codigo, (
        "sem o import, os blocos de infra/caddy/optional/ nunca entram e o wildcard deixa de "
        "existir mesmo com token configurado — a feature some em silêncio."
    )


def test_todo_bloco_opcional_e_ativado_pelo_entrypoint():
    """Arquivo em `optional/` sem ramo no entrypoint é bloco que NUNCA entra.

    Falha silenciosa perfeita: o arquivo existe, está versionado, parece ativo, e nenhuma env
    o alcança. Mesma família da `capabilities.py` sem consumidor (§WhatsApp item 12).
    """
    entrypoint = (INFRA / "caddy" / "entrypoint.sh").read_text(encoding="utf-8")
    blocos = sorted(p.name for p in OPCIONAIS.glob("*.caddy"))
    assert blocos, "nenhum bloco opcional encontrado — o diretório sumiu?"
    for nome in blocos:
        assert f"ativa {nome}" in entrypoint, (
            f"`{nome}` está em optional/ e o entrypoint nunca o ativa: ele jamais entra em "
            "conf.d/, e a ausência não quebra nada — some sem sintoma."
        )


@pytest.mark.parametrize("nome", ["wildcard.caddy", "monitor.caddy"])
def test_o_bloco_opcional_existe_e_nao_esta_vazio(nome: str):
    """Controle positivo do gate acima: sem isto, apagar os dois arquivos deixaria
    `test_todo_bloco_opcional_e_ativado_pelo_entrypoint` verde por vacuidade."""
    conteudo = (OPCIONAIS / nome).read_text(encoding="utf-8")
    assert "{" in conteudo, f"{nome} não tem bloco de site nenhum"
