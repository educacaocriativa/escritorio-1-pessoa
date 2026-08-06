"""A função que grava fato: convenção de kind e a Invariante 2 (fato não guarda dinheiro)."""
from datetime import UTC, datetime

import pytest

from app.core.facts import CRM_LEAD_CRIADO, Fact, FactError, record


def test_grava_sem_commitar(db):
    """Mesmo padrão de `receivables.build_charge`: quem chama decide o momento do commit."""
    f = record(
        db, tenant_id="t1", module="crm", kind=CRM_LEAD_CRIADO,
        title="Chegou pelo site", actor="system",
    )
    assert f.module == "crm"
    # Ainda não commitado: a linha só existe na sessão (autoflush=False no conftest).
    assert db.query(Fact).count() == 0
    db.commit()
    assert db.query(Fact).count() == 1
    assert f.id
    assert f.origin == "emitted"
    assert f.is_ai is False


def test_id_so_existe_depois_do_flush(db):
    """`default=_uuid` é column default do SQLAlchemy: aplicado no INSERT, não na construção.

    É a mesma armadilha da dívida MNT-001 (17 call sites de `audit.record(target='')` que
    gravam trilha apontando para lugar nenhum). Quem precisar do `id` do sujeito para montar
    o `subject_id` do fato tem que dar `db.flush()` ANTES de chamar `record`.
    """
    f = record(
        db, tenant_id="t1", module="crm", kind=CRM_LEAD_CRIADO,
        title="Chegou pelo site", actor="system",
    )
    assert f.id is None
    db.flush()
    assert f.id


def test_kind_precisa_comecar_com_o_modulo(db):
    """Convenção `<módulo>.<entidade>.<verbo>` verificada mecanicamente, não por disciplina.

    Trinta módulos emitindo string solta produzem `payment_received` e `payment.received`
    convivendo em seis meses.
    """
    with pytest.raises(FactError, match="kind"):
        record(
            db, tenant_id="t1", module="crm", kind="financeiro.pagamento.recebido",
            title="qualquer coisa", actor="system",
        )


def test_titulo_com_dinheiro_e_recusado(db):
    """Invariante 2: o fato diz 'Pagamento de João recebido', nunca 'Recebido R$ 3.200'.

    Copiar o valor criaria uma segunda versão da verdade sobre dinheiro — o bug que a Onda 0
    do Epic 8 desfez. E, como o texto congelado nunca carrega valor, um fato de `crm` é
    estruturalmente incapaz de vazar número financeiro para um sub-usuário só de CRM.
    """
    with pytest.raises(FactError, match="dinheiro"):
        record(
            db, tenant_id="t1", module="financeiro", kind="financeiro.pagamento.recebido",
            title="Recebido R$ 3.200,00 de João", actor="system",
        )


def test_body_pode_conter_dinheiro(db):
    """`body` carrega texto do usuário; `title` é gerado pelo sistema.

    Uma anotação em que o dono escreveu 'combinei R$ 500' são as palavras dele, não uma
    segunda fonte de verdade — recusar isso seria falso positivo.
    """
    f = record(
        db, tenant_id="t1", module="crm", kind="crm.nota.criada",
        title="Anotação", body="combinei R$ 500 de entrada", actor="user:u1",
    )
    assert "R$ 500" in f.body


def test_occurred_at_e_distinto_de_created_at(db):
    """Mensagem recebida 23h50 e processada 23h55 pertence à noite de ontem."""
    ontem = datetime(2026, 8, 5, 23, 50, tzinfo=UTC)
    f = record(
        db, tenant_id="t1", module="whatsapp", kind="whatsapp.mensagem.recebida",
        title="Contato escreveu", actor="client", occurred_at=ontem,
    )
    db.commit()
    assert f.occurred_at == ontem
    assert f.created_at != ontem


def test_dois_fatos_do_mesmo_commit_tem_instantes_distintos(db):
    """`created_at` tem default do lado do PYTHON, sobrescrevendo `server_default=func.now()`.

    No Postgres `now()` é o timestamp da TRANSAÇÃO: dois fatos do mesmo commit sairiam com
    instante idêntico, o desempate cairia no uuid, e a timeline mostraria "Reaberto" acima de
    "Voltou pelo site" — invertendo a causalidade na tela.
    """
    a = record(db, tenant_id="t1", module="crm", kind="crm.lead.retornou",
               title="Voltou pelo site", actor="client")
    b = record(db, tenant_id="t1", module="crm", kind="crm.lead.reaberto",
               title="Reaberto em Entrada", actor="system")
    db.commit()
    assert a.created_at != b.created_at
