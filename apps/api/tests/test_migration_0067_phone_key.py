"""A cópia congelada da normalização dentro da migration 0067 concorda com `core/phone`.

A migration não pode importar de `app.` (convenção do repo: 0 de 66 fazem isso), então a
regra existe em dois lugares. Este teste é o que impede as duas de divergirem sem ninguém
notar — uma divergência aqui significaria backfill gerando chaves que o `absorb_lead` nunca
encontraria, e a dedup falharia em silêncio para todo contato que já existe.
"""
import importlib.util
from pathlib import Path

import pytest

from app.core.phone import normalize_br

_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations" / "versions" / "0067_client_events_and_phone_key.py"
)

CASOS = [
    "(11) 99999-8888", "11999998888", "5511999998888", "+55 (11) 99999-8888",
    "(11) 9999-8888", "(11) 3333-4444", "1133334444", "(61) 98888-7777",
    "", "99998888", "011999998888", "123",
]


@pytest.fixture(scope="module")
def migration_module():
    spec = importlib.util.spec_from_file_location("migracao_0067", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("entrada", CASOS)
def test_copia_congelada_concorda_com_core_phone(migration_module, entrada):
    assert migration_module._normalize_br_frozen(entrada) == normalize_br(entrada)


def test_revisao_encadeia_na_0066(migration_module):
    assert migration_module.revision == "0067"
    assert migration_module.down_revision == "0066"
