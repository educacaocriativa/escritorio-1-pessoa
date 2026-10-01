"""Reivindicação de chave de idempotência da ingestão (spec §6.2)."""
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.modules.crm.models import Client
from app.modules.lead_ingest import registro
from app.modules.lead_ingest.models import LeadIngestRecord

TENANT = "tenant-nexus-0001"
CHAVE = "kiwify:ord_123:compra_aprovada"
QUANDO = datetime(2026, 10, 2, 17, 31, tzinfo=UTC)


def _reivindica(db: Session, chave: str = CHAVE):
    return registro.reivindicar(
        db, tenant_id=TENANT, chave=chave, evento="compra_aprovada", ocorrido_em=QUANDO,
        payload={"evento": "compra_aprovada"},
    )


def _contato(db: Session) -> Client:
    contato = Client(tenant_id=TENANT, name="Maria", source="api")
    db.add(contato)
    db.commit()
    return contato


def test_chave_nova_e_reivindicada_com_id_e_sem_conclusao(db: Session):
    linha = _reivindica(db)
    assert linha is not None and linha.id
    assert linha.concluido_em is None
    assert linha.payload == {"evento": "compra_aprovada"}


def test_chave_concluida_nao_e_reivindicada_de_novo(db: Session):
    contato = _contato(db)
    linha = _reivindica(db)
    registro.concluir(linha, client_id=contato.id, tags_descartadas=["x" * 41])
    db.commit()
    assert _reivindica(db) is None
    assert registro.contato_da_chave(db, chave=CHAVE) == contato.id
    assert db.scalar(select(LeadIngestRecord)).tags_descartadas == ["x" * 41]


def test_chave_reivindicada_e_nao_concluida_e_retomada(db: Session):
    """Queda entre os dois commits do serviço: a próxima tentativa retoma, não vira no-op."""
    primeira = _reivindica(db)
    db.commit()
    retomada = _reivindica(db)
    assert retomada is not None
    assert retomada.id == primeira.id
    assert db.scalar(select(func.count(LeadIngestRecord.id))) == 1


def test_retomada_trava_a_linha_com_for_update(db: Session):
    """Duas retomadas simultâneas não podem passar juntas (ledger E7).

    O SQLite dos testes ignora `FOR UPDATE`, então a prova é sobre a consulta que o caminho de
    retomada emite: ela tem de carregar o bloqueio, e compilada para Postgres sai com ele.
    """
    _reivindica(db)
    db.commit()
    consultas = []
    original = db.scalar

    def espia(stmt, *args, **kwargs):
        consultas.append(stmt)
        return original(stmt, *args, **kwargs)

    db.scalar = espia
    try:
        assert _reivindica(db) is not None
    finally:
        del db.scalar
    assert consultas, "a retomada deveria consultar a chave"
    sql = str(consultas[0].compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in sql


def test_consulta_de_leitura_nao_trava():
    sql = str(registro._consulta("k").compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" not in sql


def test_chaves_diferentes_convivem(db: Session):
    assert _reivindica(db, "kiwify:a:compra_aprovada") is not None
    assert _reivindica(db, "kiwify:b:compra_aprovada") is not None
    assert db.scalar(select(func.count(LeadIngestRecord.id))) == 2


def test_corrida_perdida_no_insert_vira_none(db: Session, monkeypatch):
    """No Postgres, o INSERT de quem chegou depois espera no índice único e então falha.

    Aqui forçamos o mesmo caminho: a busca "não vê" a linha que já existe, o INSERT bate na
    restrição única, e quem perdeu responde "já processado" em vez de estourar 500.
    """
    _reivindica(db)
    db.commit()
    monkeypatch.setattr(registro, "_buscar", lambda _db, *, chave, travar=False: None)
    assert _reivindica(db) is None


def test_contato_da_chave_desconhecida_e_none(db: Session):
    assert registro.contato_da_chave(db, chave="nunca-vista") is None


def test_restricao_unica_por_tenant_e_chave_esta_no_modelo():
    nomes = {c.name for c in LeadIngestRecord.__table__.constraints}
    assert "uq_lead_ingest_tenant_chave" in nomes
