"""A linha de resposta do DNA: upsert por (tenant, pergunta), e nulo significa 'pulei'."""
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.modules.dna.models import SOURCE_CONFIG, DnaAnswer


def test_grava_e_le(db: Session):
    db.add(
        DnaAnswer(
            tenant_id="t1", question_key="oferta.o_que_vende", value="servico_projeto",
            answered_at=datetime.now(UTC), answered_by="u1", source=SOURCE_CONFIG,
        )
    )
    db.commit()
    linha = db.query(DnaAnswer).one()
    assert linha.value == "servico_projeto"
    assert linha.id  # uuid gerado pelo default


def test_valor_nulo_e_estado_valido_e_significa_pulada(db: Session):
    """'Pulei' precisa ser distinguível de 'nunca me perguntaram', sem tabela nova."""
    db.add(
        DnaAnswer(
            tenant_id="t1", question_key="limites.nunca_faco", value=None,
            answered_at=datetime.now(UTC), answered_by="u1", source=SOURCE_CONFIG,
        )
    )
    db.commit()
    linha = db.query(DnaAnswer).one()
    assert linha.value is None


def test_valor_aceita_lista_para_escolha_multipla(db: Session):
    db.add(
        DnaAnswer(
            tenant_id="t1", question_key="cliente.como_chega", value=["indicacao", "busca"],
            answered_at=datetime.now(UTC), answered_by="u1", source=SOURCE_CONFIG,
        )
    )
    db.commit()
    assert db.query(DnaAnswer).one().value == ["indicacao", "busca"]
