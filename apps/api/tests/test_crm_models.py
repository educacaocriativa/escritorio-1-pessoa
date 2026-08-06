"""Estrutura das tabelas que a timeline do contato depende.

A tabela persistida mudou de `client_events` para `facts` na migration 0069. Três asserções
deste arquivo foram **deliberadamente invertidas** nessa passagem, e a razão é a mesma nas
três: `client_events` era do CRM, `facts` é do negócio inteiro.
"""
from app.core.facts import (
    CRM_ETAPA_MOVIDA,
    CRM_FUNIL_INSCRITO,
    CRM_LEAD_CRIADO,
    CRM_LEAD_REABERTO,
    CRM_LEAD_RETORNOU,
    CRM_NOTA_CRIADA,
    Fact,
)
from app.modules.crm.models import Client

_KINDS_DO_CRM = (
    CRM_LEAD_CRIADO, CRM_LEAD_RETORNOU, CRM_ETAPA_MOVIDA,
    CRM_LEAD_REABERTO, CRM_NOTA_CRIADA, CRM_FUNIL_INSCRITO,
)


def test_facts_tem_as_colunas_do_contrato():
    cols = {c.name for c in Fact.__table__.columns}
    assert cols == {
        "id", "tenant_id", "module", "kind", "title", "body", "client_id",
        "subject_type", "subject_id", "actor", "is_ai", "occurred_at", "origin",
        "created_at", "updated_at",
    }


def test_facts_nao_tem_gancho_generico_de_dados():
    """Sem `meta` JSON: continua sendo o depósito de qualquer coisa, e continua proibido.

    ⚠️ REVERSÃO DELIBERADA da decisão original de `client_events`, que proibia também
    `ref_type`/`ref_id`. Ali a proibição estava certa: toda linha era sobre um contato, então
    um par genérico só poderia ser abuso. Aqui `subject_type`/`subject_id` são a ÚNICA forma
    de nomear o sujeito — nenhuma coluna consegue apontar por FK para `charges`, `payables`,
    `agenda_events`, `quotes`, `pages` e `funnel_runs` ao mesmo tempo.

    O que separa "gancho genérico" de "referência polimórfica" é a disciplina: `subject_*`
    aponta para UMA linha de UMA tabela, com nome de tipo fixo, e não carrega payload. `meta`
    carregaria estrutura livre, que é onde a bagunça entra.
    """
    cols = {c.name for c in Fact.__table__.columns}
    assert "meta" not in cols
    assert "payload" not in cols
    assert "data" not in cols


def test_client_id_e_opcional_e_cascateia():
    """⚠️ REVERSÃO: em `client_events` o `client_id` era OBRIGATÓRIO.

    Um fato financeiro ou de agenda pode não ter contato nenhum. O CASCADE fica: quando há
    contato, a história dele não sobrevive a ele (LGPD, direito ao esquecimento). Contato é o
    sujeito privilegiado; os demais usam `subject_*`, que não cascateia e exige expurgo
    explícito.
    """
    col = Fact.__table__.c.client_id
    assert col.nullable is True
    fk = next(iter(col.foreign_keys))
    assert fk.column.table.name == "clients"
    assert fk.ondelete == "CASCADE"


def test_occurred_at_e_created_at_sao_colunas_distintas():
    """Quando aconteceu ≠ quando gravamos. `client_events` só tinha a segunda."""
    cols = {c.name for c in Fact.__table__.columns}
    assert "occurred_at" in cols
    assert "created_at" in cols
    assert Fact.__table__.c.occurred_at.nullable is False


def test_kinds_do_crm_seguem_a_convencao():
    """⚠️ REVERSÃO: o vocabulário não é mais fechado em seis.

    `client_events` podia enumerar todos os kinds porque era de um módulo só. `facts` recebe
    de oito módulos na Onda 1 e de mais depois — uma tupla fechada viraria o arquivo que todo
    mundo esquece de atualizar, e a verificação que importa (o prefixo bater com o módulo) já
    é mecânica em `facts.record`. O que continua garantido aqui é a FORMA.
    """
    for kind in _KINDS_DO_CRM:
        assert kind.startswith("crm.")
        assert len(kind.split(".")) == 3, f"{kind} não é <módulo>.<entidade>.<verbo>"


def test_client_ganhou_phone_key_indexada_e_sem_unique():
    col = Client.__table__.c.phone_key
    assert col.nullable is True
    assert col.index is True
    assert col.unique is not True  # dedup é busca, não invariante do banco
    assert col.type.length == 16
