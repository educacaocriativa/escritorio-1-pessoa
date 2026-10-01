"""O contrato do §6.1: o que passa, o que vira 422, e o que é tolerado de propósito."""
import copy
from datetime import timedelta
from typing import get_args

import pytest
from pydantic import ValidationError

from app.modules.lead_ingest import config
from app.modules.lead_ingest.schemas import Evento, IngestIn
from tests.lead_ingest_apoio import EXEMPLO_DA_SPEC, corpo


def test_exemplo_da_spec_valida_e_preserva_o_fuso():
    dados = IngestIn.model_validate(EXEMPLO_DA_SPEC)
    assert dados.evento == "compra_aprovada"
    assert dados.ocorrido_em.utcoffset() == timedelta(hours=-3)
    assert dados.pedido is not None and dados.pedido.valor_bruto_centavos == 49900
    assert dados.atribuicao.ultimo_toque is not None
    assert dados.atribuicao.ultimo_toque.utm_content == "ig-r-c8abc"


def test_vocabulario_de_eventos_e_um_so():
    assert set(get_args(Evento)) == set(config.EVENTOS)


def test_contato_sem_email_e_sem_telefone_e_recusado():
    with pytest.raises(ValidationError, match="e-mail ou telefone"):
        IngestIn.model_validate(corpo(contato={"nome": "Sem Canal"}))


def test_string_vazia_vale_como_ausente_e_nao_como_email_invalido():
    dados = IngestIn.model_validate(
        corpo(contato={"nome": "Ana", "email": "", "telefone": "(11) 98888-7777"})
    )
    assert dados.contato.email is None
    assert dados.contato.telefone == "(11) 98888-7777"


def test_email_invalido_e_recusado():
    with pytest.raises(ValidationError):
        IngestIn.model_validate(corpo(contato={"email": "nao-e-email"}))


def test_evento_desconhecido_e_recusado():
    with pytest.raises(ValidationError):
        IngestIn.model_validate(corpo(evento="compra"))


def test_ocorrido_em_sem_fuso_e_recusado():
    with pytest.raises(ValidationError):
        IngestIn.model_validate(corpo(ocorrido_em="2026-10-02T14:31:00"))


def test_chave_so_de_espacos_e_recusada():
    with pytest.raises(ValidationError):
        IngestIn.model_validate(corpo(chave_idempotencia="   "))


def test_sessenta_tags_passam_no_contrato_mas_cento_e_uma_nao():
    """O limite de 50 é do CONTATO e vira descarte registrado, não 422 (spec §6.2).

    100 é só teto anti-abuso do corpo da requisição.
    """
    assert len(IngestIn.model_validate(corpo(tags=[f"t:{i}" for i in range(60)])).tags) == 60
    with pytest.raises(ValidationError):
        IngestIn.model_validate(corpo(tags=[f"t:{i}" for i in range(101)]))


def test_toque_aceita_click_id_que_o_contrato_nao_lista():
    """O site captura gbraid/wbraid (spec §5.1), o contrato só lista gclid/fbclid."""
    exemplo = copy.deepcopy(EXEMPLO_DA_SPEC)
    exemplo["atribuicao"]["ultimo_toque"]["gbraid"] = "gb-1"
    dados = IngestIn.model_validate(exemplo)
    assert dados.atribuicao.model_dump(mode="json")["ultimo_toque"]["gbraid"] == "gb-1"


def test_sem_origem_aceita_toques_nulos_e_pedido_ausente():
    dados = IngestIn.model_validate(
        corpo(atribuicao={"situacao": "sem_origem", "primeiro_toque": None, "ultimo_toque": None})
    )
    assert dados.atribuicao.primeiro_toque is None
    assert dados.pedido is None


def test_tenant_id_no_corpo_e_ignorado():
    dados = IngestIn.model_validate(corpo(tenant_id="outro-tenant"))
    assert "tenant_id" not in dados.model_dump()
