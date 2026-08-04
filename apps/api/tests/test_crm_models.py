"""Estrutura das tabelas do CRM que a timeline depende."""
from app.modules.crm.models import EVENT_KINDS, Client, ClientEvent


def test_client_events_tem_as_colunas_do_contrato():
    cols = {c.name for c in ClientEvent.__table__.columns}
    assert cols == {
        "id", "tenant_id", "client_id", "kind", "title", "body", "actor", "is_ai",
        "created_at", "updated_at",
    }


def test_client_event_nao_tem_gancho_generico():
    """Sem `meta` JSON e sem `ref_type`/`ref_id`: seriam o depósito de qualquer coisa.

    Decisão da spec §"Modelo de dados". Se um caso concreto exigir, entra com nome próprio.
    """
    cols = {c.name for c in ClientEvent.__table__.columns}
    assert "meta" not in cols
    assert "ref_type" not in cols
    assert "ref_id" not in cols


def test_client_id_e_obrigatorio_e_cascateia():
    col = ClientEvent.__table__.c.client_id
    assert col.nullable is False
    fk = next(iter(col.foreign_keys))
    assert fk.column.table.name == "clients"
    assert fk.ondelete == "CASCADE"


def test_vocabulario_de_kind_fechado_em_seis():
    assert EVENT_KINDS == (
        "lead_created", "lead_return", "stage_move", "reopened", "note", "funnel",
    )


def test_client_ganhou_phone_key_indexada_e_sem_unique():
    col = Client.__table__.c.phone_key
    assert col.nullable is True
    assert col.index is True
    assert col.unique is not True  # dedup é busca, não invariante do banco
    assert col.type.length == 16
