"""A busca global — camada funda: corpo de documento, notas e mensagens.

O que esta camada custa foi medido (spec §5): 140-270 ms sobre 240k mensagens, e isso NÃO melhora
com índice — sob RLS o Postgres não usa trigrama nem tsvector para `ILIKE`. A única alavanca é
quantas linhas se varre, e é por isso que o recorte de meses existe.
"""
from datetime import UTC, datetime, timedelta

from app.modules.crm.models import Client
from app.modules.juridico.models import LegalDocument
from app.modules.search.service import buscar
from app.modules.whatsapp_inbox.models import WhatsappChat, WhatsappMessage

TENANT = "t-aaaaaaaa"
TODOS: list[str] = []


def _por_tipo(grupos):
    return {g.tipo: g for g in grupos}


def test_corpo_do_documento_so_e_lido_na_camada_funda(db):
    db.add(
        LegalDocument(
            tenant_id=TENANT, skill="peticao", title="Peticao 1",
            content="... com pedido de rescisao antecipada do contrato ...",
        )
    )
    db.commit()

    rasa = buscar(db, q="rescisao", modulos_liberados=TODOS)
    funda = buscar(db, q="rescisao", modulos_liberados=TODOS, profundidade="deep")

    assert rasa == [], "corpo não é lido na camada rasa — é o que a mantém em milissegundos"
    assert {g.tipo for g in funda} == {"legal_document"}
    assert "rescisao" in funda[0].itens[0].trecho.lower()


def test_notas_do_cliente_entram_na_camada_funda(db):
    db.add(Client(tenant_id=TENANT, name="Zulmira", notes="prefere ser chamada de Zu"))
    db.commit()

    rasa = buscar(db, q="chamada", modulos_liberados=TODOS)
    funda = buscar(db, q="chamada", modulos_liberados=TODOS, profundidade="deep")

    assert rasa == []
    assert _por_tipo(funda)["client"].itens[0].titulo == "Zulmira"


def test_funda_conta_o_total_exato(db):
    """Na página funda a contagem É a informação — ali ela é exata, não estimada."""
    for i in range(7):
        db.add(
            LegalDocument(tenant_id=TENANT, skill="peticao", title=f"Doc {i}",
                          content="rescisao")
        )
    db.commit()

    grupo = buscar(db, q="rescisao", modulos_liberados=TODOS, profundidade="deep", limite=3)[0]

    assert len(grupo.itens) == 3
    assert grupo.tem_mais is True
    assert grupo.total == 7


def test_uma_conversa_e_um_resultado_mesmo_com_quarenta_mensagens(db):
    """Spec §3: quarenta mensagens do mesmo chat saem como UMA linha.

    O contrário afogaria os outros sete tipos com repetição do mesmo diálogo — que é exatamente o
    risco levantado ao decidir incluir mensagens na busca.
    """
    chat = WhatsappChat(tenant_id=TENANT, chat_jid="5511999998888@s.whatsapp.net", title="Ana")
    db.add(chat)
    db.commit()
    for i in range(40):
        db.add(
            WhatsappMessage(tenant_id=TENANT, chat_id=chat.id, direction="in",
                            text_body=f"falamos de rescisao na mensagem {i}")
        )
    db.commit()

    grupo = _por_tipo(
        buscar(db, q="rescisao", modulos_liberados=TODOS, profundidade="deep")
    )["conversation"]

    assert len(grupo.itens) == 1
    assert grupo.total == 1


def test_recorte_de_meses_vale_so_para_mensagens(db):
    """Spec §6.2: cortar documento por data esconderia a petição de dois anos atrás — que é
    justamente o tipo de coisa que se procura por texto."""
    antigo = datetime.now(UTC) - timedelta(days=800)

    doc = LegalDocument(tenant_id=TENANT, skill="peticao", title="Antiga", content="rescisao")
    doc.created_at = antigo
    db.add(doc)
    chat = WhatsappChat(tenant_id=TENANT, chat_jid="5511999998888@s.whatsapp.net", title="Ana")
    db.add(chat)
    db.commit()
    msg = WhatsappMessage(tenant_id=TENANT, chat_id=chat.id, direction="in", text_body="rescisao")
    msg.created_at = antigo
    db.add(msg)
    db.commit()

    tipos = {
        g.tipo
        for g in buscar(db, q="rescisao", modulos_liberados=TODOS, profundidade="deep", meses=12)
    }

    assert "legal_document" in tipos, "documento antigo NÃO pode ser cortado pelo recorte"
    assert "conversation" not in tipos, "mensagem de 800 dias atrás está fora dos 12 meses"


def test_meses_zero_significa_tudo(db):
    """O seletor oferece 'tudo'; quem precisa do histórico inteiro paga conscientemente."""
    antigo = datetime.now(UTC) - timedelta(days=800)
    chat = WhatsappChat(tenant_id=TENANT, chat_jid="5511999998888@s.whatsapp.net", title="Ana")
    db.add(chat)
    db.commit()
    msg = WhatsappMessage(tenant_id=TENANT, chat_id=chat.id, direction="in", text_body="rescisao")
    msg.created_at = antigo
    db.add(msg)
    db.commit()

    tipos = {
        g.tipo
        for g in buscar(db, q="rescisao", modulos_liberados=TODOS, profundidade="deep", meses=0)
    }

    assert "conversation" in tipos


def test_trecho_mostra_o_contexto_e_nao_o_documento_inteiro(db):
    corpo = "a" * 500 + " rescisao antecipada " + "b" * 500
    db.add(LegalDocument(tenant_id=TENANT, skill="peticao", title="Doc", content=corpo))
    db.commit()

    grupos = buscar(db, q="rescisao", modulos_liberados=TODOS, profundidade="deep")
    trecho = grupos[0].itens[0].trecho

    assert "rescisao" in trecho
    assert len(trecho) < len(corpo), "o trecho é um recorte, não o documento inteiro"


def test_o_recorte_nasce_do_fuso_do_tenant_e_nao_do_relogio_do_servidor(db):
    """A âncora de "hoje" é `hoje_do_tenant`, não `datetime.now(UTC)`.

    Dois tenants em fusos separados por 25 horas (UTC+14 e UTC-11) enxergam dias diferentes ao
    mesmo instante. Se o corte viesse do relógio do servidor, os dois piso seriam idênticos — e
    esta é a classe de bug que o PR #78 fechou no resto do sistema.

    Testar isto pela variável `TZ` não funcionaria: no Windows ela não muda o fuso local do
    Python (verificado), e o fuso que importa aqui nunca foi o da máquina.
    """
    from app.modules.auth.models import Tenant
    from app.modules.search.service import _corte_de_mensagens
    from app.modules.settings.models import TenantProfile

    tenant = Tenant(
        id=TENANT, slug="estudio", legal_name="Estudio", document="1",
        timezone="Pacific/Kiritimati",  # UTC+14
    )
    db.add(tenant)
    # O perfil não é decoração do teste: `tenant_timezone` chega ao fuso por JOIN com
    # `tenant_profiles` (é o join que recorta o tenant, porque `tenants` é global e sem RLS).
    # Sem ele, a função cai no fuso padrão e o teste mediria o padrão duas vezes.
    db.add(TenantProfile(tenant_id=TENANT, display_name="Estudio"))
    db.commit()
    adiantado = _corte_de_mensagens(db, 12)

    tenant.timezone = "Pacific/Niue"  # UTC-11
    db.commit()
    atrasado = _corte_de_mensagens(db, 12)

    assert adiantado is not None and atrasado is not None
    # Estrito, e com a diferença exata: 25 horas de separação garantem que as duas datas locais
    # NUNCA coincidem. Um `>=` aqui passaria com os dois piso idênticos — que é exatamente o
    # sintoma de o corte ter vindo do relógio do servidor.
    assert adiantado - atrasado == timedelta(days=1)


def test_camada_funda_respeita_o_rbac(db):
    """O RBAC não afrouxa quando a busca fica mais funda."""
    db.add(LegalDocument(tenant_id=TENANT, skill="peticao", title="Doc", content="rescisao"))
    db.commit()

    tipos = {
        g.tipo
        for g in buscar(db, q="rescisao", modulos_liberados=["crm"], profundidade="deep")
    }

    assert tipos == set()
