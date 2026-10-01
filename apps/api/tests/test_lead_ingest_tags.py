"""Soma de tags vindas de fora: sem duplicar, sem estourar 50 × 40, descarte registrado."""
import pytest
from pydantic import ValidationError

from app.modules.crm.models import TAG_LIMIT, TAG_MAX_LENGTH
from app.modules.crm.schemas import ClientCreate
from app.modules.lead_ingest.tags import somar_tags


def test_limites_sao_os_do_crm():
    assert (TAG_LIMIT, TAG_MAX_LENGTH) == (50, 40)


def test_soma_sem_duplicar_preservando_a_ordem():
    resultado, descartadas = somar_tags(
        ["vindo-do-site", "origem:instagram"], ["origem:instagram", "post:ig-r-c8abc"]
    )
    assert resultado == ["vindo-do-site", "origem:instagram", "post:ig-r-c8abc"]
    assert descartadas == []


def test_tag_nova_e_normalizada_mas_a_antiga_fica_como_o_dono_escreveu():
    resultado, _ = somar_tags(["Tem Filhos", "origem:instagram"], ["  Origem:Instagram ", ""])
    assert resultado == ["Tem Filhos", "origem:instagram"]


def test_acima_do_limite_guarda_as_primeiras_e_lista_o_resto_uma_vez():
    atuais = [f"a:{i:02d}" for i in range(48)]
    resultado, descartadas = somar_tags(atuais, ["n:1", "n:2", "n:3", "n:4", "n:3"])
    assert len(resultado) == 50
    assert resultado[-2:] == ["n:1", "n:2"]
    assert descartadas == ["n:3", "n:4"]


def test_tag_de_41_caracteres_e_descartada_e_a_de_40_entra():
    quarenta, quarenta_e_um = "c:" + "x" * 38, "c:" + "x" * 39
    resultado, descartadas = somar_tags([], [quarenta, quarenta_e_um])
    assert resultado == [quarenta]
    assert descartadas == [quarenta_e_um]


def test_nao_muta_a_lista_do_contato():
    atuais = ["origem:instagram"]
    somar_tags(atuais, ["post:ig-r-c8abc"])
    assert atuais == ["origem:instagram"]


def test_schema_do_crm_continua_recusando_51_tags():
    with pytest.raises(ValidationError, match="máximo de 50 tags"):
        ClientCreate(name="X", tags=[f"t{i}" for i in range(51)])


def test_tag_nova_nao_duplica_a_existente_com_outra_caixa():
    resultado, descartadas = somar_tags(["Origem:Instagram"], ["origem:instagram"])
    assert resultado == ["Origem:Instagram"]
    assert descartadas == []
