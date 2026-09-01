"""`vima.pergunta.responder` — mascara antes de mandar, desmascara a resposta, registra rastro
de IA, e degrada graciosamente sem chave configurada."""
from sqlalchemy.orm import Session

from app.core.audit import AuditEntry
from app.core.tenancy import CurrentUser
from app.modules.vima import pergunta

TENANT = "t1"


def _usuario() -> CurrentUser:
    return CurrentUser(user_id="u1", tenant_id=TENANT, role="owner", allowed_modules=[])


def test_sem_chave_de_api_degrada_sem_quebrar(db: Session, monkeypatch):
    monkeypatch.setattr("app.config.settings.anthropic_api_key", "")
    resultado = pergunta.responder(db, user=_usuario(), pergunta="oi", historico=[])
    assert resultado.por_ia is False
    assert resultado.texto


def test_manda_a_pergunta_mascarada_e_desmascara_a_resposta(db: Session, monkeypatch):
    monkeypatch.setattr("app.config.settings.anthropic_api_key", "sk-fake")
    capturado = {}

    def _fake_loop(*, db, tenant_id, task, system, user_message, tools, executar_ferramenta,
                    user_id=None, **_kw):
        capturado["user_message"] = user_message
        capturado["task"] = task
        capturado["tenant_id"] = tenant_id
        # eco do e-mail mascarado, como a Claude faria ao citar o dado de volta
        texto = f"o contato é {user_message.split()[-1]}"
        return type("R", (), {"text": texto})()

    monkeypatch.setattr(pergunta.ai, "complete_with_tools", _fake_loop)

    resultado = pergunta.responder(
        db, user=_usuario(), pergunta="qual o e-mail do cliente joao@example.com", historico=[]
    )

    assert "joao@example.com" not in capturado["user_message"]
    assert capturado["task"] == "vima.pergunta"
    assert capturado["tenant_id"] == TENANT
    assert resultado.texto == "o contato é joao@example.com"
    assert resultado.por_ia is True


def test_registra_rastro_de_ia_quando_a_ia_de_fato_respondeu(db: Session, monkeypatch):
    monkeypatch.setattr("app.config.settings.anthropic_api_key", "sk-fake")
    monkeypatch.setattr(
        pergunta.ai, "complete_with_tools",
        lambda **_kw: type("R", (), {"text": "resposta"})(),
    )
    pergunta.responder(db, user=_usuario(), pergunta="e ai", historico=[])
    db.commit()
    assert db.query(AuditEntry).filter_by(action="vima.pergunta.respondida").count() == 1


def test_historico_entra_no_texto_mandado_a_claude(db: Session, monkeypatch):
    monkeypatch.setattr("app.config.settings.anthropic_api_key", "sk-fake")
    capturado = {}

    def _fake_loop(*, user_message, **_kw):
        capturado["user_message"] = user_message
        return type("R", (), {"text": "ok"})()

    monkeypatch.setattr(pergunta.ai, "complete_with_tools", _fake_loop)
    pergunta.responder(
        db, user=_usuario(), pergunta="e essa semana?",
        historico=[pergunta.Turno(papel="usuario", texto="quanto tenho a receber?"),
                    pergunta.Turno(papel="vima", texto="R$ 1.000,00")],
    )
    assert "quanto tenho a receber?" in capturado["user_message"]
    assert "R$ 1.000,00" in capturado["user_message"]
    assert "e essa semana?" in capturado["user_message"]


def test_system_prompt_exige_confirmacao_antes_de_escrever():
    assert "confirmado=true" in pergunta._SYSTEM
    assert "criar_compromisso" in pergunta._SYSTEM
    assert "cancelar_compromisso" in pergunta._SYSTEM
    assert "remarcar_compromisso" in pergunta._SYSTEM
    assert "consultar_agenda" in pergunta._SYSTEM
