"""A busca global — camada rasa.

SQLite, como todo o `pytest -q`. Isolamento cross-tenant é validado em Postgres real, no
`test_rls_isolation.py` (marcador `rls_e2e`) — aqui a RLS nem existe.
"""
from app.modules.contracts.models import Contract
from app.modules.crm.models import Client
from app.modules.juridico.models import LegalDocument
from app.modules.search.service import buscar
from app.modules.whatsapp_inbox.models import WhatsappChat

TENANT = "t-aaaaaaaa"
#: Lista vazia = sem restrição de módulo, exatamente como em `require_module`.
TODOS: list[str] = []


def _cliente(db, name="Ana Souza", **kw):
    c = Client(tenant_id=TENANT, name=name, **kw)
    db.add(c)
    db.commit()
    return c


def _por_tipo(grupos):
    return {g.tipo: g for g in grupos}


def test_casa_pelo_nome_do_cliente(db):
    _cliente(db, name="Ana Souza")
    _cliente(db, name="Bruno Lima")

    grupos = _por_tipo(buscar(db, q="ana", modulos_liberados=TODOS))

    assert [i.titulo for i in grupos["client"].itens] == ["Ana Souza"]
    assert grupos["client"].itens[0].rota.startswith("/crm/clients/")


def test_casa_pelo_email_e_pelo_telefone(db):
    """Quem digita um telefone está procurando a pessoa, não um número."""
    _cliente(db, name="Zulmira", email="contato@padaria.com.br", phone="11999998888")

    por_email = buscar(db, q="padaria", modulos_liberados=TODOS)
    por_telefone = buscar(db, q="99999", modulos_liberados=TODOS)

    assert {g.tipo for g in por_email} == {"client"}
    assert {g.tipo for g in por_telefone} == {"client"}


def test_porcento_nao_casa_com_tudo(db):
    _cliente(db, name="Ana Souza")

    assert buscar(db, q="%", modulos_liberados=TODOS) == []


def test_termo_curto_nao_devolve_nada(db):
    """Uma letra casa com quase tudo e custaria sete varreduras por tecla."""
    _cliente(db, name="Ana Souza")

    assert buscar(db, q="a", modulos_liberados=TODOS) == []
    assert buscar(db, q="  ", modulos_liberados=TODOS) == []


def test_prefixo_vem_antes_de_casamento_no_meio(db):
    _cliente(db, name="Mariana Costa")  # 'ana' no meio
    _cliente(db, name="Ana Beatriz")  # 'ana' no começo

    itens = _por_tipo(buscar(db, q="ana", modulos_liberados=TODOS))["client"].itens

    assert [i.titulo for i in itens] == ["Ana Beatriz", "Mariana Costa"]


def test_grupo_vazio_nao_entra_no_resultado(db):
    _cliente(db, name="Ana Souza")

    assert {g.tipo for g in buscar(db, q="ana", modulos_liberados=TODOS)} == {"client"}


def test_tem_mais_quando_passa_do_limite(db):
    for i in range(5):
        _cliente(db, name=f"Ana {i}")

    grupo = _por_tipo(buscar(db, q="ana", modulos_liberados=TODOS, limite=3))["client"]

    assert len(grupo.itens) == 3
    assert grupo.tem_mais is True
    assert grupo.total is None, "camada rasa não conta — contar é da funda"


def test_conversa_casa_pelo_nome_do_cliente_vinculado(db):
    """`WhatsappChat.title` é nullable; quem procura conversa procura pelo nome da pessoa."""
    ana = _cliente(db, name="Ana Souza")
    db.add(
        WhatsappChat(
            tenant_id=TENANT, chat_jid="5511999998888@s.whatsapp.net",
            title=None, client_id=ana.id,
        )
    )
    db.commit()

    grupos = _por_tipo(buscar(db, q="ana", modulos_liberados=TODOS))

    assert "conversation" in grupos
    assert len(grupos["conversation"].itens) == 1


def test_conversa_casa_pelo_proprio_titulo(db):
    """Grupo de WhatsApp não vira contato do CRM — só o título dele identifica a conversa."""
    db.add(WhatsappChat(tenant_id=TENANT, chat_jid="123@g.us", kind="group", title="Obra Anapolis"))
    db.commit()

    grupos = _por_tipo(buscar(db, q="anapolis", modulos_liberados=TODOS))

    assert grupos["conversation"].itens[0].titulo == "Obra Anapolis"


def test_os_grupos_saem_na_ordem_do_registro(db):
    """Gente primeiro, depois o diálogo, depois compromisso. A ordem é do backend, um lugar só."""
    ana = _cliente(db, name="Ana Souza")
    db.add(WhatsappChat(tenant_id=TENANT, chat_jid="55@s.whatsapp.net", client_id=ana.id))
    db.add(Contract(tenant_id=TENANT, title="Contrato da Ana"))
    db.commit()

    tipos = [g.tipo for g in buscar(db, q="ana", modulos_liberados=TODOS)]

    assert tipos == ["client", "conversation", "contract"]


def test_modulo_bloqueado_nao_produz_grupo(db):
    """RBAC (spec §6.4): a RLS garante o tenant certo, não que ESTE usuário vê ESTE módulo."""
    _cliente(db, name="Ana Souza")
    db.add(LegalDocument(tenant_id=TENANT, skill="peticao", title="Peticao da Ana"))
    db.commit()

    tipos = {g.tipo for g in buscar(db, q="ana", modulos_liberados=["crm"])}

    assert "client" in tipos
    assert "legal_document" not in tipos, "sub-usuário sem juridico leria título de petição"
