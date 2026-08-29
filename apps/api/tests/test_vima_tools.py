"""As nove ferramentas de leitura que a Vima oferece à Claude — permissão, delegação e o
contrato "nunca deixa exceção subir crua" (o loop de tool-use precisa de um tool_result sempre).
"""
import json
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app.core.tenancy import CurrentUser
from app.modules.crm.models import Client
from app.modules.juridico.models import LegalDocument
from app.modules.marketing.models import Carousel
from app.modules.receivables.models import METHOD_PIX, STATUS_OPEN, Charge
from app.modules.stock.models import StockItem
from app.modules.vima import tools
from app.modules.wallet.models import KIND_SERVICE

TENANT = "t1"


def _usuario(role: str = "owner", modulos: list[str] | None = None) -> CurrentUser:
    return CurrentUser(
        user_id="u1", tenant_id=TENANT, role=role,
        allowed_modules=modulos or [], is_platform_admin=False,
    )


# ── Catálogo e permissão ────────────────────────────────────────────────────────────────────


def test_owner_ve_as_nove_ferramentas():
    nomes = {f.nome for f in tools.ferramentas_disponiveis(_usuario("owner"))}
    assert nomes == {
        "consultar_recebiveis", "consultar_pagaveis", "consultar_projecao_caixa",
        "consultar_agenda", "consultar_cliente", "consultar_documentos_juridicos",
        "consultar_campanhas_marketing", "consultar_estoque_baixo", "consultar_item_estoque",
    }


def test_sub_usuario_so_de_juridico_so_ve_a_ferramenta_de_documentos():
    nomes = {f.nome for f in tools.ferramentas_disponiveis(_usuario("sub_user", ["juridico"]))}
    assert nomes == {"consultar_documentos_juridicos"}


def test_sub_usuario_so_de_marketing_so_ve_a_ferramenta_de_campanhas():
    nomes = {f.nome for f in tools.ferramentas_disponiveis(_usuario("sub_user", ["marketing"]))}
    assert nomes == {"consultar_campanhas_marketing"}


def test_sub_usuario_so_de_stock_ve_as_duas_ferramentas_de_estoque():
    nomes = {f.nome for f in tools.ferramentas_disponiveis(_usuario("sub_user", ["stock"]))}
    assert nomes == {"consultar_estoque_baixo", "consultar_item_estoque"}


def test_sub_usuario_so_de_crm_so_ve_a_ferramenta_de_cliente():
    nomes = {f.nome for f in tools.ferramentas_disponiveis(_usuario("sub_user", ["crm"]))}
    assert nomes == {"consultar_cliente"}


def test_toda_ferramenta_declara_um_input_schema_valido():
    """Instanciação obrigatória do catálogo — uma ferramenta sem `input_schema` quebraria a
    chamada à Anthropic só na primeira vez que a Claude tentasse usá-la."""
    for f in tools.FERRAMENTAS:
        assert f.definicao["name"] == f.nome
        assert f.definicao["input_schema"]["type"] == "object"


def test_executar_recusa_ferramenta_fora_da_lista_permitida(db: Session):
    resultado = json.loads(
        tools.executar(db, _usuario("sub_user", ["crm"]), "consultar_recebiveis", {})
    )
    assert "erro" in resultado


# ── consultar_recebiveis / consultar_pagaveis ──────────────────────────────────────────────


def test_consultar_recebiveis_delega_para_o_resumo_real(db: Session):
    db.add(Charge(
        tenant_id=TENANT, description="Consultoria", kind=KIND_SERVICE, method=METHOD_PIX,
        amount_cents=50_000, due_date=date(2026, 9, 1), status=STATUS_OPEN,
    ))
    db.commit()
    resultado = json.loads(tools.executar(db, _usuario(), "consultar_recebiveis", {}))
    assert resultado["open_cents"] == 50_000
    assert resultado["open_count"] == 1


def test_consultar_pagaveis_devolve_o_resumo_de_pagaveis(db: Session):
    resultado = json.loads(tools.executar(db, _usuario(), "consultar_pagaveis", {}))
    assert "open_cents" in resultado and "overdue_cents" in resultado


# ── consultar_projecao_caixa ────────────────────────────────────────────────────────────────


def test_consultar_projecao_caixa_devolve_janelas_e_runway(db: Session):
    resultado = json.loads(tools.executar(db, _usuario(), "consultar_projecao_caixa", {}))
    assert "windows" in resultado
    assert "runway" in resultado
    assert resultado["saldo_inicial_origem"] in {"plataforma", "banco", "misto", "indisponivel"}


# ── consultar_agenda ─────────────────────────────────────────────────────────────────────────


def test_consultar_agenda_devolve_eventos_do_dia_pedido(db: Session):
    from app.modules.agenda.models import AgendaEvent

    db.add(AgendaEvent(
        tenant_id=TENANT, title="Reunião com cliente", kind="meeting",
        starts_at=datetime(2026, 9, 10, 14, 0, tzinfo=UTC),
        ends_at=datetime(2026, 9, 10, 15, 0, tzinfo=UTC),
    ))
    db.commit()
    resultado = json.loads(tools.executar(
        db, _usuario(), "consultar_agenda", {"data_inicio": "2026-09-10"}
    ))
    assert len(resultado["eventos"]) == 1
    assert resultado["eventos"][0]["titulo"] == "Reunião com cliente"


def test_consultar_agenda_sem_evento_devolve_lista_vazia_nao_erro(db: Session):
    resultado = json.loads(tools.executar(
        db, _usuario(), "consultar_agenda", {"data_inicio": "2026-01-01"}
    ))
    assert resultado["eventos"] == []


# ── consultar_cliente ────────────────────────────────────────────────────────────────────────


def test_consultar_cliente_encontra_por_nome_parcial(db: Session):
    db.add(Client(tenant_id=TENANT, name="João da Silva", phone="11999998888", source="manual"))
    db.commit()
    resultado = json.loads(tools.executar(db, _usuario(), "consultar_cliente", {"nome": "João"}))
    assert len(resultado["clientes"]) == 1
    assert resultado["clientes"][0]["nome"] == "João da Silva"
    assert resultado["clientes"][0]["ultima_interacao"] is None


def test_consultar_cliente_sem_match_devolve_lista_vazia(db: Session):
    resultado = json.loads(tools.executar(db, _usuario(), "consultar_cliente", {"nome": "Ninguém"}))
    assert resultado["clientes"] == []


# ── consultar_documentos_juridicos ──────────────────────────────────────────────────────────


def test_consultar_documentos_juridicos_filtra_por_cliente(db: Session):
    cliente = Client(tenant_id=TENANT, name="Maria Souza", phone="11988887777", source="manual")
    db.add(cliente)
    db.flush()
    db.add(LegalDocument(
        tenant_id=TENANT, skill="peticao_inicial", title="Petição — Maria Souza",
        client_id=cliente.id,
    ))
    db.add(LegalDocument(tenant_id=TENANT, skill="contrato", title="Contrato — outro cliente"))
    db.commit()
    resultado = json.loads(
        tools.executar(db, _usuario(), "consultar_documentos_juridicos", {"cliente": "Maria"})
    )
    assert len(resultado["documentos"]) == 1
    assert resultado["documentos"][0]["titulo"] == "Petição — Maria Souza"
    assert resultado["documentos"][0]["cliente"] == "Maria Souza"


def test_consultar_documentos_juridicos_sem_filtro_lista_tudo(db: Session):
    db.add(LegalDocument(tenant_id=TENANT, skill="contrato", title="Contrato A"))
    db.add(LegalDocument(tenant_id=TENANT, skill="parecer", title="Parecer B"))
    db.commit()
    resultado = json.loads(
        tools.executar(db, _usuario(), "consultar_documentos_juridicos", {})
    )
    assert len(resultado["documentos"]) == 2


def test_consultar_documentos_juridicos_filtra_por_dias(db: Session):
    db.add(LegalDocument(tenant_id=TENANT, skill="contrato", title="Contrato recente"))
    db.commit()
    resultado = json.loads(
        tools.executar(db, _usuario(), "consultar_documentos_juridicos", {"dias": 7})
    )
    assert len(resultado["documentos"]) == 1
    resultado_antigo = json.loads(
        tools.executar(db, _usuario(), "consultar_documentos_juridicos", {"dias": -1})
    )
    assert resultado_antigo["documentos"] == []


def test_consultar_documentos_juridicos_cliente_sem_match_devolve_lista_vazia(db: Session):
    resultado = json.loads(
        tools.executar(db, _usuario(), "consultar_documentos_juridicos", {"cliente": "Ninguém"})
    )
    assert resultado["documentos"] == []


# ── consultar_campanhas_marketing ───────────────────────────────────────────────────────────


def test_consultar_campanhas_marketing_lista_as_geradas(db: Session):
    db.add(Carousel(tenant_id=TENANT, topic="5 erros de precificação", platform="instagram"))
    db.commit()
    resultado = json.loads(
        tools.executar(db, _usuario(), "consultar_campanhas_marketing", {})
    )
    assert len(resultado["campanhas"]) == 1
    assert resultado["campanhas"][0]["tema"] == "5 erros de precificação"
    assert resultado["campanhas"][0]["plataforma"] == "instagram"


def test_consultar_campanhas_marketing_filtra_por_dias(db: Session):
    db.add(Carousel(tenant_id=TENANT, topic="Tema antigo", platform="instagram"))
    db.commit()
    resultado = json.loads(
        tools.executar(db, _usuario(), "consultar_campanhas_marketing", {"dias": -1})
    )
    assert resultado["campanhas"] == []


# ── consultar_estoque_baixo / consultar_item_estoque ────────────────────────────────────────


def test_consultar_estoque_baixo_so_lista_item_no_ou_abaixo_do_minimo(db: Session):
    db.add(StockItem(
        tenant_id=TENANT, name="Caneca personalizada", quantity=2, min_quantity=5, unit="un",
    ))
    db.add(StockItem(
        tenant_id=TENANT, name="Camiseta P", quantity=50, min_quantity=5, unit="un",
    ))
    db.commit()
    resultado = json.loads(tools.executar(db, _usuario(), "consultar_estoque_baixo", {}))
    assert len(resultado["itens"]) == 1
    assert resultado["itens"][0]["nome"] == "Caneca personalizada"


def test_consultar_item_estoque_busca_por_nome_parcial(db: Session):
    db.add(StockItem(
        tenant_id=TENANT, name="Caneca personalizada", quantity=2, min_quantity=5, unit="un",
    ))
    db.commit()
    resultado = json.loads(
        tools.executar(db, _usuario(), "consultar_item_estoque", {"nome": "caneca"})
    )
    assert len(resultado["itens"]) == 1
    assert resultado["itens"][0]["quantidade"] == 2
    assert resultado["itens"][0]["baixo"] is True


def test_consultar_item_estoque_sem_match_devolve_lista_vazia(db: Session):
    resultado = json.loads(
        tools.executar(db, _usuario(), "consultar_item_estoque", {"nome": "Ninguém"})
    )
    assert resultado["itens"] == []


# ── Falha nunca sobe crua ───────────────────────────────────────────────────────────────────


def test_ferramenta_com_entrada_invalida_devolve_erro_em_vez_de_estourar(db: Session):
    resultado = json.loads(
        tools.executar(db, _usuario(), "consultar_agenda", {"data_inicio": "não é uma data"})
    )
    assert "erro" in resultado
