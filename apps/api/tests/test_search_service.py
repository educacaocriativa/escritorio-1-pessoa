"""A busca global — camada rasa.

SQLite, como todo o `pytest -q`. Isolamento cross-tenant é validado em Postgres real, no
`test_rls_isolation.py` (marcador `rls_e2e`) — aqui a RLS nem existe.
"""
from datetime import date

from app.modules.contracts.models import Contract
from app.modules.crm.models import Client
from app.modules.juridico.models import LegalDocument
from app.modules.payables.models import Payable
from app.modules.quotes.models import Quote
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


def _conta(db, *, description="", supplier="", status="open", **kw):
    """Conta mínima: `due_date`/`amount_cents` são NOT NULL e não interessam ao texto."""
    p = Payable(
        tenant_id=TENANT, description=description, supplier=supplier, status=status,
        amount_cents=kw.pop("amount_cents", 12345), due_date=kw.pop("due_date", date(2026, 9, 10)),
        **kw,
    )
    db.add(p)
    db.commit()
    return p


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
    """Uma letra casa com quase tudo e custaria oito varreduras por tecla."""
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


# ── Contas a Pagar (#146) ─────────────────────────────────────────────────────────────────────
#
# Entrou na busca porque o PR #143 (issue #138) fez `/pagar` hidratar o recorte a partir da URL.
# Antes disso o destino era inerte e o resultado seria pior que nenhum — spec §2 e a errata.


def test_conta_a_pagar_casa_pela_descricao(db):
    _conta(db, description="IOF sobre emprestimo", supplier="Banco Azul")
    _conta(db, description="Aluguel da sala", supplier="Imobiliaria Norte")

    grupos = _por_tipo(buscar(db, q="iof", modulos_liberados=TODOS))

    assert "payable" in grupos, "buscar IOF tem de achar a conta de IOF"
    assert [i.titulo for i in grupos["payable"].itens] == ["IOF sobre emprestimo"]


def test_conta_a_pagar_casa_pelo_fornecedor(db):
    """Quem procura *"o que eu pago para a Vivo"* digita o fornecedor, não a descrição."""
    _conta(db, description="Internet da sala", supplier="Vivo Fibra")

    grupos = _por_tipo(buscar(db, q="vivo", modulos_liberados=TODOS))

    assert grupos["payable"].itens[0].titulo == "Internet da sala"
    assert grupos["payable"].itens[0].subtitulo == "Vivo Fibra"


def test_conta_sem_descricao_usa_o_fornecedor_como_titulo(db):
    """As duas colunas nascem `""`; uma linha sem rótulo legível seria um resultado inútil."""
    _conta(db, description="", supplier="Cartorio Central", category="Taxas")

    item = _por_tipo(buscar(db, q="cartorio", modulos_liberados=TODOS))["payable"].itens[0]

    assert item.titulo == "Cartorio Central"
    assert item.subtitulo == "Taxas", "repetir o fornecedor nas duas linhas não informa nada"


def test_o_destino_leva_para_a_lista_ja_filtrada_na_conta(db):
    """O clique aterrissa na lista JÁ recortada — e com o recorte padrão desarmado.

    `status=` e `ate=` vazios não são enfeite: `filtros.ts::daUrl` os lê como "todos os status" e
    "sem horizonte". Sem eles, a visão padrão (`open`+`scheduled` dentro do mês seguinte) esconderia
    justamente a conta **paga** que a busca acabou de encontrar — a objeção nominal da spec §2.
    """
    _conta(db, description="IOF sobre emprestimo", supplier="Banco Azul")

    rota = _por_tipo(buscar(db, q="iof", modulos_liberados=TODOS))["payable"].itens[0].rota

    assert rota == "/pagar?q=IOF%20sobre%20emprestimo&status=&ate="


def test_o_destino_de_conta_paga_tambem_mostra_a_conta(db):
    """O mesmo destino, agora sobre o caso que motivou desarmar o filtro."""
    _conta(db, description="Alvara anual", supplier="Prefeitura", status="paid")

    rota = _por_tipo(buscar(db, q="alvara", modulos_liberados=TODOS))["payable"].itens[0].rota

    assert rota.startswith("/pagar?q=")
    assert "status=" in rota, "sem `status=` a conta paga não aparece na tela de destino"
    assert "ate=" in rota, "sem `ate=` o horizonte esconderia a conta de vencimento distante"


def test_curinga_na_conta_nao_casa_com_tudo(db):
    """Mesmo escape do `test_q_escapa_curinga_do_like` da listagem, pela mesma porta."""
    _conta(db, description="Aluguel da sala", supplier="Imobiliaria Norte")
    _conta(db, description="Taxa de 5% ao mes", supplier="Banco Azul")

    so_o_literal = _por_tipo(buscar(db, q="5%", modulos_liberados=TODOS))

    assert [i.titulo for i in so_o_literal["payable"].itens] == ["Taxa de 5% ao mes"]
    assert buscar(db, q="%%", modulos_liberados=TODOS) == [], "curinga cru casaria com tudo"


def test_conta_a_pagar_respeita_o_rbac(db):
    """Sub-usuário sem `payables` não lê fornecedor nem valor devido pela porta da busca."""
    _cliente(db, name="Ana Souza")
    _conta(db, description="Ana Consultoria mensal", supplier="Ana Consultoria")

    tipos = {g.tipo for g in buscar(db, q="ana", modulos_liberados=["crm"])}

    assert "client" in tipos
    assert "payable" not in tipos


def test_conta_a_pagar_entra_entre_orcamento_e_juridico(db):
    """A ordem dos grupos é a do registro, num lugar só — dinheiro junto de dinheiro."""
    _cliente(db, name="Ana Souza")
    db.add(Quote(tenant_id=TENANT, title="Orcamento da Ana"))
    db.add(LegalDocument(tenant_id=TENANT, skill="peticao", title="Peticao da Ana"))
    db.commit()
    _conta(db, description="Ana Consultoria mensal")

    tipos = [g.tipo for g in buscar(db, q="ana", modulos_liberados=TODOS)]

    assert tipos == ["client", "quote", "payable", "legal_document"]


def test_conta_nao_e_lida_mais_fundo_na_camada_funda(db):
    """`payment_code` é linha digitável de boleto: ninguém procura conta por 44 dígitos.

    Sem campo fundo, a camada funda acrescenta só a CONTAGEM exata — e é isso que este teste fixa,
    para que ninguém acrescente `payment_code` a `campos_fundos` sem decidir a troca.
    """
    boleto = "34191790010104351004791020150008291070026000"
    _conta(db, description="Aluguel da sala", payment_code=boleto)

    funda = _por_tipo(buscar(db, q="34191790", modulos_liberados=TODOS, profundidade="deep"))
    por_texto = _por_tipo(buscar(db, q="aluguel", modulos_liberados=TODOS, profundidade="deep"))

    assert "payable" not in funda
    assert por_texto["payable"].total == 1
    assert por_texto["payable"].itens[0].trecho is None
