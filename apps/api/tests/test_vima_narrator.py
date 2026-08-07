"""mask → Claude → unmask, com fallback por template. Mesmo caminho do ai_narrator."""
from app.core.audit import AuditEntry
from app.modules.vima.composer import Linha, Payload
from app.modules.vima.narrator import narrar

_PAYLOAD = Payload(
    referencia=None, desde=None, excedente=0,
    linhas=[Linha(secao="ACONTECEU", module="financeiro",
                  texto="Pagamento de João recebido — R$ 3.200,00")],
)


def test_sem_chave_cai_no_template_e_nao_grava_rastro_de_ia(db, monkeypatch):
    """Seguindo o ai_narrator: quando a IA não rodou, não grava rastro de IA."""
    monkeypatch.setattr("app.config.settings.anthropic_api_key", "")
    n = narrar(db, tenant_id="t1", payload=_PAYLOAD, nome_do_usuario="Flávio")
    db.commit()
    assert n.por_ia is False
    assert "Pagamento de João recebido" in n.texto
    assert db.query(AuditEntry).filter(AuditEntry.is_ai.is_(True)).count() == 0


def test_erro_da_api_cai_no_template_com_o_mesmo_conteudo(db, monkeypatch):
    monkeypatch.setattr("app.config.settings.anthropic_api_key", "sk-fake")

    def _explode(**kwargs):
        raise RuntimeError("timeout")

    monkeypatch.setattr("app.core.ai.complete", _explode)
    n = narrar(db, tenant_id="t1", payload=_PAYLOAD, nome_do_usuario="Flávio")
    assert n.por_ia is False
    assert "Pagamento de João recebido" in n.texto


def test_narracao_bem_sucedida_grava_rastro_de_ia(db, monkeypatch):
    monkeypatch.setattr("app.config.settings.anthropic_api_key", "sk-fake")
    monkeypatch.setattr(
        "app.core.ai.complete",
        lambda **kw: type("R", (), {"text": "Bom dia. Entrou dinheiro.",
                                    "input_tokens": 10, "output_tokens": 5})(),
    )
    n = narrar(db, tenant_id="t1", payload=_PAYLOAD, nome_do_usuario="Flávio")
    db.commit()
    assert n.por_ia is True
    assert db.query(AuditEntry).filter(AuditEntry.is_ai.is_(True)).count() == 1


def test_o_telefone_vai_mascarado_e_volta_real(db, monkeypatch):
    """Regra de Ouro nº 2: nenhum texto vai ao Claude sem passar pelo anonimizador antes."""
    visto = {}
    monkeypatch.setattr("app.config.settings.anthropic_api_key", "sk-fake")

    def _captura(**kw):
        visto["mensagem"] = kw["user_message"]
        return type("R", (), {"text": kw["user_message"], "input_tokens": 1,
                              "output_tokens": 1})()

    monkeypatch.setattr("app.core.ai.complete", _captura)
    p = Payload(referencia=None, desde=None, excedente=0, linhas=[
        Linha(secao="PENDENTE", module="comercial",
              texto="Ligar para (11) 99999-8888"),
    ])
    n = narrar(db, tenant_id="t1", payload=p, nome_do_usuario="Flávio")
    assert "(11) 99999-8888" not in visto["mensagem"]
    assert "[FONE_1]" in visto["mensagem"]
    assert "(11) 99999-8888" in n.texto
