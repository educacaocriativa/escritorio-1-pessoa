"""O worker recebe a MESMA composição da API — e este teste é o consumidor mecânico disso.

**O defeito que ele existe para impedir, medido em produção (AWS, 2026-08-21): 336 `BankError`
em 24h.** `app/main.py` compunha a aplicação no import, e o worker roda `python -m app.worker`,
que nunca importa `app.main`. Nesse processo nenhum probe era registrado, e
`bank/reconciliation.py` levantava `BankError` — **o briefing da Vima falhava, em silêncio do
ponto de vista do dono**. O fail-closed estava CERTO; errada era a fiação existir num processo só.

⚠️ **O teste roda num interpretador NOVO, e isso não é preciosismo — é a diferença entre provar e
não provar nada.** Dentro do pytest, `app.main` já foi importado pela `conftest` (o `TestClient`),
então os probes estariam registrados de qualquer jeito e a asserção passaria **verde sobre o bug**.
É a família do "teste que passa e não prova nada" que o Epic 8 documenta oito vezes.

A guarda de não-vacuidade é explícita: o subprocesso assere que `app.main` **não** está em
`sys.modules`. Se um dia o worker passar a importar a API por outro caminho, este teste falha e
avisa — em vez de virar decoração.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

_API_DIR = pathlib.Path(__file__).resolve().parents[1]

_SONDA = """
import sys
import app.worker  # noqa: F401

assert "app.main" not in sys.modules, (
    "o worker importou a API — este teste deixaria de provar qualquer coisa"
)

from app.modules.bank import reconciliation, service
from app.modules.wallet import service as wallet

faltando = [
    nome
    for nome, ok in (
        ("termos_do_gate", reconciliation.termos_do_gate_probe_registrado()),
        ("contagem_dupla", service.duplicata_probe_registrado()),
        ("payout", wallet.payout_registrar_registrado()),
    )
    if not ok
]
assert not faltando, f"o worker subiu sem a fiacao: {faltando}"
print("COMPOSICAO_OK")
"""


def test_o_worker_sozinho_ja_tem_toda_a_fiacao():
    r = subprocess.run(
        [sys.executable, "-c", _SONDA],
        cwd=_API_DIR,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert "COMPOSICAO_OK" in r.stdout


def test_a_sonda_roda_mesmo_um_interpretador_limpo():
    """Controle positivo DA SONDA: sem a fiação, ela precisa REPROVAR.

    Sem isto, uma sonda que deixasse de exercitar o worker (import renomeado, `cwd` errado)
    passaria verde para sempre. Aqui o membro é um processo que importa só os módulos do banco,
    **sem** o worker — e nele os probes têm de estar ausentes.
    """
    sem_worker = (
        "from app.modules.bank import reconciliation\n"
        "assert not reconciliation.termos_do_gate_probe_registrado()\n"
        "print('SEM_FIACAO_OK')\n"
    )
    r = subprocess.run(
        [sys.executable, "-c", sem_worker],
        cwd=_API_DIR,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert "SEM_FIACAO_OK" in r.stdout
