"""Ingestão: compra vai ao Ganho, pós-venda não tira de lá, e o funil é escolhido pelo evento."""
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import events
from app.core.facts import Fact
from app.modules.crm.models import Client, PipelineStage
from app.modules.funnels import automation
from app.modules.funnels.models import Funnel, FunnelRun
from app.modules.lead_ingest import service
from app.modules.settings import service as settings_service
from tests.lead_ingest_apoio import TENANT, payload, usar_sessao_do_teste


@pytest.fixture(autouse=True)
def _sem_assinantes():
    events.clear()
    yield
    events.clear()


def _ingere(db: Session, **sobre):
    return service.ingest(db, tenant_id=TENANT, dados=payload(**sobre))


def _etapa(db: Session, client_id: str) -> str:
    return db.get(PipelineStage, db.get(Client, client_id).stage_id).name


def _conta_fatos(db: Session, client_id: str, kind: str) -> int:
    return db.scalar(
        select(func.count(Fact.id)).where(Fact.client_id == client_id, Fact.kind == kind)
    )


def _funil(db: Session, nome: str, *, espera: bool = False) -> Funnel:
    if espera:
        nodes = [
            {"id": "n1", "data": {"key": "esperar", "config": {"delay_minutes": 60}}},
            {"id": "n2"},
        ]
        edges = [{"id": "e1", "source": "n1", "target": "n2"}]
    else:
        nodes, edges = [{"id": "n1"}], []
    funil = Funnel(tenant_id=TENANT, name=nome, nodes=nodes, edges=edges)
    db.add(funil)
    db.commit()
    db.refresh(funil)
    return funil


def _configura(db: Session, *, padrao: str | None = None, **cfg) -> None:
    perfil = settings_service.get_profile(db, TENANT)
    perfil.default_entry_funnel_id = padrao
    perfil.lead_ingest_config = cfg
    db.commit()


def _funis_do(db: Session, client_id: str) -> list[str]:
    return [
        r.funnel_id
        for r in db.scalars(select(FunnelRun).where(FunnelRun.client_id == client_id)).all()
    ]


def test_compra_aprovada_move_para_o_ganho(db: Session):
    r = _ingere(db, evento="compra_aprovada", chave_idempotencia="kiwify:ord_1:compra")
    assert _etapa(db, r.contato_id) == "Ganho"
    assert _conta_fatos(db, r.contato_id, "crm.etapa.movida") == 1


@pytest.mark.parametrize("evento", ["reembolso", "chargeback", "cancelamento", "renovacao"])
def test_pos_venda_nao_tira_do_ganho_nem_reabre(db: Session, evento: str):
    compra = _ingere(db, evento="compra_aprovada", chave_idempotencia="kiwify:ord_1:compra")
    _ingere(db, evento=evento, chave_idempotencia=f"kiwify:ord_1:{evento}")
    assert _etapa(db, compra.contato_id) == "Ganho"
    assert _conta_fatos(db, compra.contato_id, "crm.lead.reaberto") == 0


def test_compra_sem_coluna_de_ganho_ativa_registra_sem_mover(db: Session):
    _ingere(db)  # semeia as colunas e põe o contato em Entrada
    ganho = db.scalar(select(PipelineStage).where(PipelineStage.is_won.is_(True)))
    ganho.is_archived = True
    db.commit()
    r = _ingere(db, evento="compra_aprovada", chave_idempotencia="kiwify:ord_1:compra")
    assert r.processado is True
    assert _etapa(db, r.contato_id) == "Entrada"
    assert _conta_fatos(db, r.contato_id, "comercial.compra.aprovada") == 1


def test_evento_mapeado_vai_so_para_o_funil_do_evento(db: Session):
    padrao = _funil(db, "Boas-vindas")
    recuperacao = _funil(db, "Recuperação")
    _configura(db, padrao=padrao.id, funis={"carrinho_abandonado": recuperacao.id})
    r = _ingere(db, evento="carrinho_abandonado", chave_idempotencia="kiwify:c1:carrinho")
    assert _funis_do(db, r.contato_id) == [recuperacao.id]


def test_lead_sem_mapeamento_cai_no_funil_padrao(db: Session):
    padrao = _funil(db, "Boas-vindas")
    _configura(db, padrao=padrao.id)
    r = _ingere(db)
    assert _funis_do(db, r.contato_id) == [padrao.id]


@pytest.mark.parametrize("evento", ["renovacao", "reembolso", "chargeback", "cancelamento"])
def test_pos_venda_sem_mapeamento_nao_entra_no_funil_padrao(db: Session, evento: str):
    padrao = _funil(db, "Boas-vindas")
    _configura(db, padrao=padrao.id)
    r = _ingere(
        db, evento=evento, chave_idempotencia=f"kiwify:o:{evento}",
        contato={"nome": "Ana", "email": "ana@exemplo.gov.br"},
    )
    assert _funis_do(db, r.contato_id) == []


def test_pos_venda_mapeado_explicitamente_inscreve(db: Session):
    retencao = _funil(db, "Retenção")
    _configura(db, funis={"cancelamento": retencao.id})
    r = _ingere(
        db, evento="cancelamento", chave_idempotencia="kiwify:o:cancelamento",
        contato={"nome": "Ana", "email": "ana@exemplo.gov.br"},
    )
    assert _funis_do(db, r.contato_id) == [retencao.id]


def test_jornada_viva_nao_e_duplicada(db: Session):
    padrao = _funil(db, "Boas-vindas", espera=True)
    _configura(db, padrao=padrao.id)
    primeiro = _ingere(db)
    _ingere(db, chave_idempotencia="site:lead:2")
    assert _funis_do(db, primeiro.contato_id) == [padrao.id]


def test_funil_inexistente_nao_derruba_a_ingestao(db: Session):
    _configura(db, funis={"lead": "funil-que-nao-existe"})
    r = _ingere(db)
    assert r.processado is True
    assert _funis_do(db, r.contato_id) == []


def test_com_assinantes_reais_o_lead_entra_em_um_unico_funil(db: Session, monkeypatch):
    """Controller E1: auto-enroll do `source="api"` + inscrição por evento não somam."""
    usar_sessao_do_teste(db, monkeypatch)
    automation.register()
    padrao = _funil(db, "Boas-vindas")
    recuperacao = _funil(db, "Recuperação")
    _configura(db, padrao=padrao.id, funis={"carrinho_abandonado": recuperacao.id})

    novo = _ingere(db, evento="carrinho_abandonado", chave_idempotencia="kiwify:c1:carrinho")
    assert _funis_do(db, novo.contato_id) == [recuperacao.id]


@pytest.mark.parametrize(
    "evento", ["carrinho_abandonado", "lead"]
)
def test_evento_de_entrada_de_quem_ja_esta_no_ganho_nao_reabre_nem_inscreve(
    db: Session, evento: str
):
    recuperacao = _funil(db, "Recuperação")
    boas_vindas = _funil(db, "Boas-vindas")
    _configura(db, padrao=boas_vindas.id, funis={"carrinho_abandonado": recuperacao.id})
    compra = _ingere(db, evento="compra_aprovada", chave_idempotencia="kiwify:ord_1:compra")
    runs_antes = _funis_do(db, compra.contato_id)

    r = _ingere(
        db, evento=evento, chave_idempotencia=f"site:{evento}:2", tags=["carrinho:aberto"]
    )

    assert r.contato_id == compra.contato_id
    assert _etapa(db, compra.contato_id) == "Ganho"
    assert _conta_fatos(db, compra.contato_id, "crm.lead.reaberto") == 0
    assert _funis_do(db, compra.contato_id) == runs_antes
    contato = db.get(Client, compra.contato_id)
    assert "carrinho:aberto" in contato.tags
    kind = "comercial.carrinho.abandonado" if evento == "carrinho_abandonado" else (
        "comercial.lead.recebido"
    )
    assert _conta_fatos(db, compra.contato_id, kind) == 1


def test_evento_de_entrada_fora_do_ganho_continua_passando_pelo_absorb_lead(db: Session):
    recuperacao = _funil(db, "Recuperação")
    _configura(db, funis={"carrinho_abandonado": recuperacao.id})
    primeiro = _ingere(db)  # lead: fica em Entrada
    r = _ingere(db, evento="carrinho_abandonado", chave_idempotencia="kiwify:c1:carrinho")
    assert r.contato_id == primeiro.contato_id
    assert _etapa(db, r.contato_id) == "Entrada"
    assert _funis_do(db, r.contato_id) == [recuperacao.id]


def test_falha_inesperada_na_inscricao_nao_derruba_a_ingestao(db: Session, monkeypatch, caplog):
    from app.modules.funnels import engine

    funil = _funil(db, "Boas-vindas")
    _configura(db, funis={"lead": funil.id})

    def _quebra(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr(engine, "enroll", _quebra)
    r = _ingere(db)
    assert r.processado is True
    assert _funis_do(db, r.contato_id) == []
    erros = [x for x in caplog.records if "inscrição falhou" in x.getMessage()]
    assert len(erros) == 1
    # o registro continua concluído: a retentativa é no-op
    assert _ingere(db).processado is False
    # a sessão segue utilizável depois do rollback
    assert db.get(Client, r.contato_id) is not None
    db.commit()


def test_inscricao_bem_sucedida_nao_registra_erro_falso(db: Session, caplog):
    funil = _funil(db, "Boas-vindas")
    _configura(db, funis={"lead": funil.id})
    with caplog.at_level("DEBUG"):
        r = _ingere(db)
    assert r.processado is True
    assert [x for x in caplog.records if "inscrição falhou" in x.getMessage()] == []
    assert _funis_do(db, r.contato_id) == [funil.id]


# --- compra aprovada encerra as jornadas de entrada ---------------------------------------


def _status_das_jornadas(db: Session, client_id: str) -> dict[str, str]:
    return {
        r.funnel_id: r.status
        for r in db.scalars(select(FunnelRun).where(FunnelRun.client_id == client_id)).all()
    }


def _carrinho(db: Session, **sobre):
    return _ingere(
        db, evento="carrinho_abandonado", chave_idempotencia="kiwify:c1:carrinho", **sobre
    )


def _compra(db: Session, chave: str = "kiwify:ord_1:compra"):
    return _ingere(db, evento="compra_aprovada", chave_idempotencia=chave)


def test_compra_cancela_a_recuperacao_viva_e_inscreve_no_funil_da_compra(db: Session):
    recuperacao = _funil(db, "Recuperação", espera=True)
    boas_vindas = _funil(db, "Boas-vindas")
    _configura(
        db, funis={"carrinho_abandonado": recuperacao.id, "compra_aprovada": boas_vindas.id}
    )
    carrinho = _carrinho(db)
    assert _status_das_jornadas(db, carrinho.contato_id) == {recuperacao.id: "waiting"}

    r = _compra(db)

    assert r.processado is True
    assert _etapa(db, r.contato_id) == "Ganho"
    status = _status_das_jornadas(db, r.contato_id)
    assert status[recuperacao.id] == "cancelled"
    assert boas_vindas.id in status and status[boas_vindas.id] != "cancelled"


def test_compra_cancela_jornada_viva_do_funil_lead_e_do_padrao(db: Session):
    lead_funil = _funil(db, "Nutrição", espera=True)
    padrao = _funil(db, "Boas-vindas", espera=True)
    pos_compra = _funil(db, "Pós-compra")
    _configura(
        db, padrao=padrao.id, funis={"lead": lead_funil.id, "compra_aprovada": pos_compra.id}
    )
    lead = _ingere(db)
    # o funil padrão só recebe quem não tem mapeamento: inscreve à mão, como o dono faria
    from app.modules.funnels import engine

    engine.enroll(
        db, tenant_id=TENANT, actor="teste", funnel_id=padrao.id, client_id=lead.contato_id
    )
    assert set(_status_das_jornadas(db, lead.contato_id).values()) == {"waiting"}

    _compra(db)

    status = _status_das_jornadas(db, lead.contato_id)
    assert status[lead_funil.id] == "cancelled"
    assert status[padrao.id] == "cancelled"


def test_sem_mapeamento_da_compra_o_funil_padrao_vivo_e_preservado(db: Session):
    """O funil padrão É o funil da compra quando nada o mapeia: não cancela nem recomeça."""
    padrao = _funil(db, "Boas-vindas", espera=True)
    _configura(db, padrao=padrao.id)
    lead = _ingere(db)
    assert _status_das_jornadas(db, lead.contato_id) == {padrao.id: "waiting"}

    _compra(db)

    assert _status_das_jornadas(db, lead.contato_id) == {padrao.id: "waiting"}


def test_compra_nao_cancela_o_proprio_funil_da_compra(db: Session):
    compra_funil = _funil(db, "Pós-compra", espera=True)
    recuperacao = _funil(db, "Recuperação", espera=True)
    _configura(
        db, funis={"carrinho_abandonado": recuperacao.id, "compra_aprovada": compra_funil.id}
    )
    carrinho = _carrinho(db)
    from app.modules.funnels import engine

    engine.enroll(
        db, tenant_id=TENANT, actor="teste", funnel_id=compra_funil.id,
        client_id=carrinho.contato_id,
    )

    _compra(db)

    status = _status_das_jornadas(db, carrinho.contato_id)
    assert status[compra_funil.id] == "waiting"
    assert status[recuperacao.id] == "cancelled"


def test_funil_mapeado_a_carrinho_e_a_compra_nao_e_cancelado(db: Session):
    mesmo = _funil(db, "Único", espera=True)
    _configura(db, funis={"carrinho_abandonado": mesmo.id, "compra_aprovada": mesmo.id})
    carrinho = _carrinho(db)

    _compra(db)

    assert _status_das_jornadas(db, carrinho.contato_id) == {mesmo.id: "waiting"}


def test_falha_no_cancelamento_nao_perde_a_venda(db: Session, monkeypatch, caplog):
    from app.modules.funnels import engine

    recuperacao = _funil(db, "Recuperação", espera=True)
    _configura(db, funis={"carrinho_abandonado": recuperacao.id})
    carrinho = _carrinho(db)

    def _quebra(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr(engine, "cancel_run", _quebra)
    r = _compra(db)

    assert r.processado is True
    assert _etapa(db, r.contato_id) == "Ganho"
    assert _conta_fatos(db, r.contato_id, "comercial.compra.aprovada") == 1
    erros = [x for x in caplog.records if "cancelamento de jornada falhou" in x.getMessage()]
    assert len(erros) == 1
    assert _status_das_jornadas(db, carrinho.contato_id) == {recuperacao.id: "waiting"}
    assert db.get(Client, r.contato_id) is not None  # sessão segue utilizável
    db.commit()


def test_compra_nao_toca_jornadas_de_outro_cliente(db: Session):
    recuperacao = _funil(db, "Recuperação", espera=True)
    _configura(db, funis={"carrinho_abandonado": recuperacao.id})
    outro = _ingere(
        db, evento="carrinho_abandonado", chave_idempotencia="kiwify:c2:carrinho",
        contato={"nome": "Outro", "email": "outro@exemplo.gov.br"},
    )
    comprador = _carrinho(db)

    _compra(db)

    assert _status_das_jornadas(db, outro.contato_id) == {recuperacao.id: "waiting"}
    assert _status_das_jornadas(db, comprador.contato_id) == {recuperacao.id: "cancelled"}


def test_compra_nao_cancela_jornada_de_funil_fora_da_entrada(db: Session):
    recuperacao = _funil(db, "Recuperação", espera=True)
    outro_funil = _funil(db, "Campanha avulsa", espera=True)
    _configura(db, funis={"carrinho_abandonado": recuperacao.id})
    carrinho = _carrinho(db)
    from app.modules.funnels import engine

    engine.enroll(
        db, tenant_id=TENANT, actor="teste", funnel_id=outro_funil.id,
        client_id=carrinho.contato_id,
    )

    _compra(db)

    status = _status_das_jornadas(db, carrinho.contato_id)
    assert status[outro_funil.id] == "waiting"
    assert status[recuperacao.id] == "cancelled"


@pytest.mark.parametrize("evento", ["reembolso", "renovacao", "chargeback", "cancelamento"])
def test_pos_venda_nao_cancela_jornadas(db: Session, evento: str):
    recuperacao = _funil(db, "Recuperação", espera=True)
    _configura(db, funis={"carrinho_abandonado": recuperacao.id})
    carrinho = _carrinho(db)

    _ingere(db, evento=evento, chave_idempotencia=f"kiwify:ord_1:{evento}")

    assert _status_das_jornadas(db, carrinho.contato_id) == {recuperacao.id: "waiting"}


def test_compra_sem_config_de_ingestao_segue_igual(db: Session):
    r = _compra(db)
    assert r.processado is True
    assert _etapa(db, r.contato_id) == "Ganho"
