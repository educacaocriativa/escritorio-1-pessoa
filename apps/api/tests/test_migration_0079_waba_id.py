"""A 0079 encadeia na 0078 e o backfill do `waba_id` abre a janela de RLS na FONTE.

O `UPDATE` lê `tenant_profiles`, que tem `FORCE ROW LEVEL SECURITY` desde a 0022. A migration
roda como `e1p_app` SEM a GUC `app.current_tenant_id`: sem a janela, o backfill seria filtrado
a ZERO LINHAS, em silêncio — e o sintoma em produção não seria erro de deploy, seria "a Meta
aprovou o template e o e1p continua dizendo Pendente". Este teste lê o TEXTO da migration
porque a asserção é sobre o que o arquivo faz rodar, não sobre um efeito observável em SQLite
(que não tem RLS). O efeito real é exercido em `test_whatsapp_template_status_rls.py`.
"""
import importlib.util
from pathlib import Path

import pytest

_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations" / "versions" / "0079_public_whatsapp_account_waba_id.py"
)


@pytest.fixture(scope="module")
def migration_module():
    spec = importlib.util.spec_from_file_location("migracao_0079", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revisao_encadeia_na_0078(migration_module):
    assert migration_module.revision == "0079"
    assert migration_module.down_revision == "0078"


def test_backfill_abre_e_fecha_a_janela_de_rls_na_fonte():
    texto = _MIGRATION.read_text(encoding="utf-8")
    assert "ALTER TABLE tenant_profiles DISABLE ROW LEVEL SECURITY" in texto
    assert "ALTER TABLE tenant_profiles ENABLE ROW LEVEL SECURITY" in texto
    # ENABLE sozinho não basta: sem FORCE, o dono da tabela volta a escapar da policy.
    assert "ALTER TABLE tenant_profiles FORCE ROW LEVEL SECURITY" in texto


def test_backfill_e_reentrante():
    """`a.waba_id IS NULL` — rodar a SQL de novo à mão contra produção (coisa que já aconteceu
    na história deste projeto) não pode sobrescrever o que o dual-write já corrigiu depois."""
    texto = _MIGRATION.read_text(encoding="utf-8")
    assert "a.waba_id IS NULL" in texto
