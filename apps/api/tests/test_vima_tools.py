"""As cinco ferramentas de leitura que a Vima oferece à Claude — permissão, delegação e o
contrato "nunca deixa exceção subir crua" (o loop de tool-use precisa de um tool_result sempre).
"""
import json
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app.core.tenancy import CurrentUser
from app.modules.crm.models import Client
from app.modules.receivables.models import METHOD_PIX, STATUS_OPEN, Charge
from app.modules.vima import tools
from app.modules.wallet.models import KIND_SERVICE

TENANT = "t1"


def _usuario(role: str = "owner", modulos: list[str] | None = None) -> CurrentUser:
    return CurrentUser(
        user_id="u1", tenant_id=TENANT, role=role,
        allowed_modules=modulos or [], is_platform_admin=False,
    )


# ── Catálogo e permissão ────────────────────────────────────────────────────────────────────


def test_owner_ve_as_cinco_ferramentas():
    nomes = {f.nome for f in tools.ferramentas_disponiveis(_usuario("owner"))}
    assert nomes == {
        "consultar_recebiveis", "consultar_pagaveis", "consultar_projecao_caixa",
        "consultar_agenda", "consultar_cliente",
    }


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


# ── Falha nunca sobe crua ───────────────────────────────────────────────────────────────────


def test_ferramenta_com_entrada_invalida_devolve_erro_em_vez_de_estourar(db: Session):
    resultado = json.loads(
        tools.executar(db, _usuario(), "consultar_agenda", {"data_inicio": "não é uma data"})
    )
    assert "erro" in resultado
