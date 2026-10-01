"""Configuração da ingestão por tenant: produto (prefixo de tag) e funil por evento."""
import pytest

from app.modules.lead_ingest import config
from app.modules.settings.models import TenantProfile


def _perfil(cfg: dict | None = None, padrao: str | None = None) -> TenantProfile:
    return TenantProfile(
        tenant_id="t-1", lead_ingest_config={} if cfg is None else cfg,
        default_entry_funnel_id=padrao,
    )


def test_produto_configurado():
    assert config.produto(_perfil({"produto": "publia"})) == "publia"


@pytest.mark.parametrize("valor", [None, "", "Publ.IA", "publia com espaço", "x" * 21, 7])
def test_produto_invalido_ou_ausente_e_none(valor):
    assert config.produto(_perfil({"produto": valor})) is None


def test_sem_configuracao_nenhuma_nao_ha_produto():
    assert config.produto(_perfil()) is None


def test_validar_produto_normaliza_e_recusa():
    assert config.validar_produto("  PublIA ") == "publia"
    with pytest.raises(ValueError):
        config.validar_produto("Publ.IA")


def test_evento_mapeado_usa_o_funil_do_evento():
    perfil = _perfil({"funis": {"carrinho_abandonado": "f-recuperacao"}}, padrao="f-padrao")
    assert config.funil_do_evento(perfil, "carrinho_abandonado") == "f-recuperacao"


@pytest.mark.parametrize("evento", ["lead", "carrinho_abandonado", "compra_aprovada"])
def test_evento_de_entrada_sem_mapeamento_cai_no_padrao(evento):
    assert config.funil_do_evento(_perfil(padrao="f-padrao"), evento) == "f-padrao"


@pytest.mark.parametrize("evento", ["renovacao", "reembolso", "chargeback", "cancelamento"])
def test_pos_venda_sem_mapeamento_nao_cai_no_padrao(evento):
    """Reembolso não pode reinscrever o cliente no funil de boas-vindas."""
    assert config.funil_do_evento(_perfil(padrao="f-padrao"), evento) is None


def test_pos_venda_mapeado_explicitamente_vale():
    perfil = _perfil({"funis": {"cancelamento": "f-retencao"}}, padrao="f-padrao")
    assert config.funil_do_evento(perfil, "cancelamento") == "f-retencao"


@pytest.mark.parametrize("funis", [{"lead": ""}, {"lead": None}, "lixo", ["lead"]])
def test_mapeamento_vazio_ou_malformado_cai_no_padrao(funis):
    assert config.funil_do_evento(_perfil({"funis": funis}, padrao="f-padrao"), "lead") == (
        "f-padrao"
    )
