"""Os dois caches de `vima/whatsapp_conversa.py`: dedup de reentrega de webhook e contexto
curto entre perguntas — os dois em processo, com TTL, sem tabela nova (decisão da spec)."""
from sqlalchemy.orm import Session

from app.modules.auth.models import User
from app.modules.vima import whatsapp_conversa as vc

TENANT = "t1"


def setup_function():
    # Os caches são módulo-level (dict global) — cada teste começa limpo, senão o TTL de um
    # teste vazaria pro próximo e a ordem de execução passaria a importar.
    vc._VISTAS.clear()
    vc._HISTORICO.clear()
    vc._ULTIMAS_RESPOSTAS.clear()


# ── Dedup de reentrega ──────────────────────────────────────────────────────────────────────


def test_mensagem_nunca_vista_nao_esta_processada():
    assert vc._ja_processada("wamid.novo") is False


def test_mensagem_marcada_fica_processada():
    vc._marcar_processada("wamid.x")
    assert vc._ja_processada("wamid.x") is True


def test_marca_expira_apos_o_ttl(monkeypatch):
    agora = [1000.0]
    monkeypatch.setattr(vc.time, "monotonic", lambda: agora[0])
    vc._marcar_processada("wamid.y")
    assert vc._ja_processada("wamid.y") is True
    agora[0] += vc.TTL_DEDUP_SEGUNDOS + 1
    assert vc._ja_processada("wamid.y") is False


# ── Contexto entre perguntas ─────────────────────────────────────────────────────────────────


def test_chave_sem_historico_devolve_lista_vazia():
    assert vc._historico("t1:5511999998888") == []


def test_turno_guardado_aparece_no_historico():
    chave = vc._chave(TENANT, "5511999998888")
    vc._guardar_turno(chave, "usuario", "quanto tenho a receber?")
    vc._guardar_turno(chave, "vima", "R$ 500,00")
    historico = vc._historico(chave)
    assert [(t.papel, t.texto) for t in historico] == [
        ("usuario", "quanto tenho a receber?"), ("vima", "R$ 500,00"),
    ]


def test_turno_expirado_some_do_historico(monkeypatch):
    agora = [2000.0]
    monkeypatch.setattr(vc.time, "monotonic", lambda: agora[0])
    chave = vc._chave(TENANT, "5511999997777")
    vc._guardar_turno(chave, "usuario", "pergunta antiga")
    agora[0] += vc.TTL_CONTEXTO_SEGUNDOS + 1
    assert vc._historico(chave) == []


def test_chave_normaliza_o_telefone():
    # "(11) 99999-8888" e "5511999998888" são o MESMO telefone — a chave do cache não pode
    # tratá-los como duas conversas diferentes, ou o contexto se perde a cada formatação distinta
    # do mesmo número que o provider entregar.
    assert vc._chave(TENANT, "11999998888") == vc._chave(TENANT, "(11) 99999-8888")


# ── Resolução do usuário pelo telefone ──────────────────────────────────────────────────────


def test_usuario_do_telefone_encontra_por_numero_normalizado(db: Session):
    user = User(
        tenant_id=TENANT, email="dono@example.com", name="Dono", password_hash="x",
        phone="(11) 99999-8888",
    )
    db.add(user)
    db.commit()
    encontrado = vc._usuario_do_telefone(db, TENANT, "5511999998888")
    assert encontrado is not None
    assert encontrado.id == user.id


def test_usuario_do_telefone_ignora_usuario_inativo(db: Session):
    user = User(
        tenant_id=TENANT, email="inativo@example.com", name="Ex", password_hash="x",
        phone="5511988887777", is_active=False,
    )
    db.add(user)
    db.commit()
    assert vc._usuario_do_telefone(db, TENANT, "5511988887777") is None


def test_usuario_do_telefone_sem_match_devolve_none(db: Session):
    assert vc._usuario_do_telefone(db, TENANT, "5511900000000") is None


# ── responder() — a orquestração ────────────────────────────────────────────────────────────


def test_responder_chama_pergunta_e_manda_a_resposta_por_whatsapp(db: Session, monkeypatch):
    user = User(
        tenant_id=TENANT, email="dono2@example.com", name="Dono", password_hash="x",
        phone="5511999991111",
    )
    db.add(user)
    db.commit()

    capturado = {}

    def _fake_pergunta_responder(db, *, user, pergunta, historico):
        from app.modules.vima.pergunta import Resposta
        capturado["user_id"] = user.user_id
        capturado["pergunta"] = pergunta
        capturado["historico"] = historico
        return Resposta(texto="Você tem R$ 500,00 a receber.", por_ia=True)

    def _fake_send_text(*, to, text, profile=None, **_kw):
        capturado["enviado_para"] = to
        capturado["texto_enviado"] = text
        return "sent"

    monkeypatch.setattr(vc.pergunta_service, "responder", _fake_pergunta_responder)
    monkeypatch.setattr(vc.whatsapp, "send_text", _fake_send_text)

    vc.responder(
        db, tenant_id=TENANT, phone="5511999991111", wa_message_id="wamid.1",
        texto="quanto tenho a receber?", profile=None,
    )

    assert capturado["user_id"] == user.id
    assert capturado["pergunta"] == "quanto tenho a receber?"
    assert capturado["historico"] == []
    assert capturado["enviado_para"] == "5511999991111"
    assert capturado["texto_enviado"] == "Você tem R$ 500,00 a receber."


def test_responder_guarda_o_turno_para_a_proxima_pergunta(db: Session, monkeypatch):
    from app.modules.vima.pergunta import Resposta

    user = User(
        tenant_id=TENANT, email="dono3@example.com", name="Dono", password_hash="x",
        phone="5511999992222",
    )
    db.add(user)
    db.commit()

    monkeypatch.setattr(
        vc.pergunta_service, "responder",
        lambda db, *, user, pergunta, historico: Resposta(texto="R$ 500,00", por_ia=True),
    )
    monkeypatch.setattr(vc.whatsapp, "send_text", lambda **_kw: "sent")

    vc.responder(
        db, tenant_id=TENANT, phone="5511999992222", wa_message_id="wamid.2",
        texto="quanto tenho a receber?", profile=None,
    )

    historico = vc._historico(vc._chave(TENANT, "5511999992222"))
    assert [(t.papel, t.texto) for t in historico] == [
        ("usuario", "quanto tenho a receber?"), ("vima", "R$ 500,00"),
    ]


def test_responder_ignora_reentrega_do_mesmo_wa_message_id(db: Session, monkeypatch):
    from app.modules.vima.pergunta import Resposta

    user = User(
        tenant_id=TENANT, email="dono4@example.com", name="Dono", password_hash="x",
        phone="5511999993333",
    )
    db.add(user)
    db.commit()

    chamadas = {"n": 0}

    def _fake_pergunta_responder(db, *, user, pergunta, historico):
        chamadas["n"] += 1
        return Resposta(texto="ok", por_ia=True)

    monkeypatch.setattr(vc.pergunta_service, "responder", _fake_pergunta_responder)
    monkeypatch.setattr(vc.whatsapp, "send_text", lambda **_kw: "sent")

    for _ in range(2):
        vc.responder(
            db, tenant_id=TENANT, phone="5511999993333", wa_message_id="wamid.dup",
            texto="oi", profile=None,
        )
    assert chamadas["n"] == 1


def test_responder_sem_usuario_correspondente_nao_estoura(db: Session, monkeypatch):
    # Defensivo: o chamador já checou `_e_telefone_da_equipe`, mas nada garante atomicidade
    # entre a checagem e aqui — não pode estourar se o telefone não bater com ninguém.
    chamado = {"n": 0}
    monkeypatch.setattr(
        vc.pergunta_service, "responder",
        lambda *a, **kw: chamado.update(n=chamado["n"] + 1),
    )
    vc.responder(
        db, tenant_id=TENANT, phone="5511900009999", wa_message_id="wamid.semuser",
        texto="oi", profile=None,
    )
    assert chamado["n"] == 0  # nunca chegou a chamar pergunta.responder


def test_responder_ignora_eco_da_propria_resposta(db: Session, monkeypatch):
    """A Evolution ecoa de volta, via MESSAGES_UPSERT, toda mensagem que o próprio produto manda
    pro self-chat — inclusive a resposta que a Vima acabou de enviar (mesmo mecanismo do eco de
    `whatsapp_inbox.service`, ver comentário em `ingest_webhook_payload`). Esse eco chega com um
    `wa_message_id` NOVO e genuíno (não é reentrega do mesmo evento, então `_ja_processada` não
    pega) e bate na MESMA condição de roteamento que uma pergunta real (`from_me` + `da_equipe` +
    texto) — sem uma guarda, a Vima responde à própria resposta, que ecoa nova, para sempre."""
    from app.modules.vima.pergunta import Resposta

    user = User(
        tenant_id=TENANT, email="dono12@example.com", name="Dono", password_hash="x",
        phone="5511999990001",
    )
    db.add(user)
    db.commit()

    chamadas = {"n": 0}

    def _fake_pergunta_responder(db, *, user, pergunta, historico):
        chamadas["n"] += 1
        return Resposta(texto="Combinado! Fico por aqui.", por_ia=True)

    monkeypatch.setattr(vc.pergunta_service, "responder", _fake_pergunta_responder)
    monkeypatch.setattr(vc.whatsapp, "send_text", lambda **_kw: "sent")

    vc.responder(
        db, tenant_id=TENANT, phone="5511999990001", wa_message_id="wamid.pergunta",
        texto="e essa semana, quanto tenho a pagar?", profile=None,
    )
    assert chamadas["n"] == 1

    vc.responder(
        db, tenant_id=TENANT, phone="5511999990001", wa_message_id="wamid.eco",
        texto="Combinado! Fico por aqui.", profile=None,
    )
    assert chamadas["n"] == 1  # o eco da própria resposta não vira pergunta nova


def test_responder_nao_ignora_pergunta_igual_ao_eco_depois_do_ttl(db: Session, monkeypatch):
    """A guarda do eco é por TEMPO curto (mesmo TTL do dedup), não para sempre — se o dono
    realmente perguntar de novo o mesmo texto que a Vima respondeu, depois do TTL isso volta a
    ser uma pergunta válida."""
    from app.modules.vima.pergunta import Resposta

    user = User(
        tenant_id=TENANT, email="dono13@example.com", name="Dono", password_hash="x",
        phone="5511999990002",
    )
    db.add(user)
    db.commit()

    agora = [3000.0]
    monkeypatch.setattr(vc.time, "monotonic", lambda: agora[0])

    chamadas = {"n": 0}
    monkeypatch.setattr(
        vc.pergunta_service, "responder",
        lambda db, *, user, pergunta, historico: chamadas.update(n=chamadas["n"] + 1)
        or Resposta(texto="oi", por_ia=True),
    )
    monkeypatch.setattr(vc.whatsapp, "send_text", lambda **_kw: "sent")

    vc.responder(
        db, tenant_id=TENANT, phone="5511999990002", wa_message_id="wamid.p1",
        texto="pergunta original", profile=None,
    )
    assert chamadas["n"] == 1

    agora[0] += vc.TTL_DEDUP_SEGUNDOS + 1
    vc.responder(
        db, tenant_id=TENANT, phone="5511999990002", wa_message_id="wamid.p2",
        texto="oi", profile=None,
    )
    assert chamadas["n"] == 2  # TTL expirado — texto igual à resposta antiga é pergunta válida


def test_responder_falha_no_meio_manda_desculpa_em_vez_de_estourar(db: Session, monkeypatch):
    user = User(
        tenant_id=TENANT, email="dono5@example.com", name="Dono", password_hash="x",
        phone="5511999994444",
    )
    db.add(user)
    db.commit()

    def _explode(db, *, user, pergunta, historico):
        raise RuntimeError("Claude indisponível")

    capturado = {}

    def _fake_send_text(*, to, text, profile=None, **_kw):
        capturado["texto"] = text
        return "sent"

    monkeypatch.setattr(vc.pergunta_service, "responder", _explode)
    monkeypatch.setattr(vc.whatsapp, "send_text", _fake_send_text)

    vc.responder(  # não pode levantar
        db, tenant_id=TENANT, phone="5511999994444", wa_message_id="wamid.falha",
        texto="oi", profile=None,
    )
    assert "não consegui" in capturado["texto"].lower()


# ── responder_audio() — a voz vira pergunta, com eco ────────────────────────────────────────


def test_responder_audio_transcreve_e_ecoa_a_pergunta_entendida(db: Session, monkeypatch):
    from app.core.transcription import TranscriptionResult
    from app.modules.vima.pergunta import Resposta

    user = User(
        tenant_id=TENANT, email="dono6@example.com", name="Dono", password_hash="x",
        phone="5511999995555",
    )
    db.add(user)
    db.commit()

    capturado = {}

    monkeypatch.setattr(
        vc.transcription, "transcribe",
        lambda db, *, tenant_id, audio_bytes, mime_type, user_id=None: TranscriptionResult(
            text="quanto tenho a receber?", audio_seconds=2.1,
        ),
    )
    monkeypatch.setattr(
        vc.pergunta_service, "responder",
        lambda db, *, user, pergunta, historico: Resposta(texto="R$ 500,00", por_ia=True),
    )

    def _fake_send_text(*, to, text, profile=None, **_kw):
        capturado["texto_enviado"] = text
        return "sent"

    monkeypatch.setattr(vc.whatsapp, "send_text", _fake_send_text)

    vc.responder_audio(
        db, tenant_id=TENANT, phone="5511999995555", wa_message_id="wamid.audio1",
        audio_bytes=b"audio-bytes", audio_mime_type="audio/ogg", profile=None,
    )

    assert capturado["texto_enviado"] == '🎤 "quanto tenho a receber?" — R$ 500,00'


def test_responder_audio_guarda_o_turno_com_o_texto_transcrito(db: Session, monkeypatch):
    from app.core.transcription import TranscriptionResult
    from app.modules.vima.pergunta import Resposta

    user = User(
        tenant_id=TENANT, email="dono7@example.com", name="Dono", password_hash="x",
        phone="5511999996666",
    )
    db.add(user)
    db.commit()

    monkeypatch.setattr(
        vc.transcription, "transcribe",
        lambda *a, **kw: TranscriptionResult(text="e essa semana?", audio_seconds=1.0),
    )
    monkeypatch.setattr(
        vc.pergunta_service, "responder",
        lambda db, *, user, pergunta, historico: Resposta(texto="R$ 100,00", por_ia=True),
    )
    monkeypatch.setattr(vc.whatsapp, "send_text", lambda **_kw: "sent")

    vc.responder_audio(
        db, tenant_id=TENANT, phone="5511999996666", wa_message_id="wamid.audio2",
        audio_bytes=b"x", audio_mime_type="audio/ogg", profile=None,
    )

    historico = vc._historico(vc._chave(TENANT, "5511999996666"))
    assert [(t.papel, t.texto) for t in historico] == [
        ("usuario", "e essa semana?"), ("vima", "R$ 100,00"),
    ]


def test_responder_audio_sem_transcricao_manda_desculpa_sem_chamar_pergunta(
    db: Session, monkeypatch,
):
    user = User(
        tenant_id=TENANT, email="dono8@example.com", name="Dono", password_hash="x",
        phone="5511999997778",
    )
    db.add(user)
    db.commit()

    chamado = {"n": 0}
    capturado = {}

    monkeypatch.setattr(vc.transcription, "transcribe", lambda *a, **kw: None)
    monkeypatch.setattr(
        vc.pergunta_service, "responder",
        lambda *a, **kw: chamado.update(n=chamado["n"] + 1),
    )

    def _fake_send_text(*, to, text, profile=None, **_kw):
        capturado["texto"] = text
        return "sent"

    monkeypatch.setattr(vc.whatsapp, "send_text", _fake_send_text)

    vc.responder_audio(
        db, tenant_id=TENANT, phone="5511999997778", wa_message_id="wamid.audiofalha",
        audio_bytes=b"ruido", audio_mime_type="audio/ogg", profile=None,
    )

    assert chamado["n"] == 0  # nunca chegou a chamar pergunta.responder
    assert "não consegui" in capturado["texto"].lower()


def test_responder_audio_passa_user_id_correto_para_transcribe(db: Session, monkeypatch):
    from app.core.transcription import TranscriptionResult
    from app.modules.vima.pergunta import Resposta

    user = User(
        tenant_id=TENANT, email="dono10@example.com", name="Dono", password_hash="x",
        phone="5511999999111",
    )
    db.add(user)
    db.commit()

    capturado = {}

    def _fake_transcribe(db, *, tenant_id, audio_bytes, mime_type, user_id=None):
        capturado["user_id"] = user_id
        return TranscriptionResult(text="oi", audio_seconds=1.0)

    monkeypatch.setattr(vc.transcription, "transcribe", _fake_transcribe)
    monkeypatch.setattr(
        vc.pergunta_service, "responder",
        lambda db, *, user, pergunta, historico: Resposta(texto="ok", por_ia=True),
    )
    monkeypatch.setattr(vc.whatsapp, "send_text", lambda **_kw: "sent")

    vc.responder_audio(
        db, tenant_id=TENANT, phone="5511999999111", wa_message_id="wamid.useridok",
        audio_bytes=b"x", audio_mime_type="audio/ogg", profile=None,
    )

    assert capturado["user_id"] == user.id


def test_responder_audio_passa_user_id_none_quando_telefone_nao_bate(db: Session, monkeypatch):
    # Mirror de `test_responder_sem_usuario_correspondente_nao_estoura` (caminho texto), mas
    # aqui o ponto é `transcribe`: mesmo sem usuário correspondente, a transcrição AINDA roda
    # (só o ledger fica sem user_id) — quem desiste em silêncio é `_responder`, não este ponto.
    from app.core.transcription import TranscriptionResult

    capturado = {}

    def _fake_transcribe(db, *, tenant_id, audio_bytes, mime_type, user_id=None):
        capturado["user_id"] = user_id
        return TranscriptionResult(text="oi", audio_seconds=1.0)

    monkeypatch.setattr(vc.transcription, "transcribe", _fake_transcribe)
    monkeypatch.setattr(vc.whatsapp, "send_text", lambda **_kw: "sent")

    vc.responder_audio(
        db, tenant_id=TENANT, phone="5511900001234", wa_message_id="wamid.useridnone",
        audio_bytes=b"x", audio_mime_type="audio/ogg", profile=None,
    )

    assert capturado["user_id"] is None


def test_responder_audio_falha_apos_transcricao_preserva_ledger_da_groq_e_manda_desculpa(
    db: Session, monkeypatch,
):
    # A transcrição AQUI é a real (`transcription.transcribe`, só o `httpx.post` é mockado) para
    # que `ai_usage.record` grave de verdade uma linha `provider='groq'` na transação do `db` —
    # é essa linha que precisa SOBREVIVER ao `db.rollback()` de dentro do except de `_responder`
    # quando `pergunta.responder` explode em seguida. Prova mais convincente que mockar
    # `db.commit()`: consulta real no banco de teste, depois da chamada inteira.
    import httpx

    from app.config import settings
    from app.core.ai_usage import AIUsage

    user = User(
        tenant_id=TENANT, email="dono11@example.com", name="Dono", password_hash="x",
        phone="5511999999222",
    )
    db.add(user)
    db.commit()

    monkeypatch.setattr(settings, "groq_api_key", "gsk-fake")

    class _FakeGroqResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"text": "quanto tenho a receber?", "duration": 2.5}

    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _FakeGroqResponse())

    def _explode(db, *, user, pergunta, historico):
        raise RuntimeError("Claude indisponível")

    capturado = {}

    def _fake_send_text(*, to, text, profile=None, **_kw):
        capturado["texto"] = text
        return "sent"

    monkeypatch.setattr(vc.pergunta_service, "responder", _explode)
    monkeypatch.setattr(vc.whatsapp, "send_text", _fake_send_text)

    vc.responder_audio(  # não pode levantar, mesmo com a falha posterior em pergunta.responder
        db, tenant_id=TENANT, phone="5511999999222", wa_message_id="wamid.audiofalhapos",
        audio_bytes=b"x", audio_mime_type="audio/ogg", profile=None,
    )

    # (b) a desculpa foi mandada pelo mesmo canal, mesmo caminho do texto
    assert "não consegui" in capturado["texto"].lower()

    # a cobrança da Groq já tinha acontecido antes da falha — o rollback de _responder não pode
    # apagar essa linha do ledger
    linha = db.query(AIUsage).filter_by(provider="groq").one()
    assert linha.user_id == user.id
    assert linha.audio_seconds == 2.5
    assert linha.tenant_id == TENANT


def test_responder_audio_ignora_reentrega_do_mesmo_wa_message_id(db: Session, monkeypatch):
    from app.core.transcription import TranscriptionResult
    from app.modules.vima.pergunta import Resposta

    user = User(
        tenant_id=TENANT, email="dono9@example.com", name="Dono", password_hash="x",
        phone="5511999998889",
    )
    db.add(user)
    db.commit()

    chamadas = {"n": 0}

    def _fake_transcribe(*a, **kw):
        chamadas["n"] += 1
        return TranscriptionResult(text="oi", audio_seconds=1.0)

    monkeypatch.setattr(vc.transcription, "transcribe", _fake_transcribe)
    monkeypatch.setattr(
        vc.pergunta_service, "responder",
        lambda db, *, user, pergunta, historico: Resposta(texto="ok", por_ia=True),
    )
    monkeypatch.setattr(vc.whatsapp, "send_text", lambda **_kw: "sent")

    for _ in range(2):
        vc.responder_audio(
            db, tenant_id=TENANT, phone="5511999998889", wa_message_id="wamid.audiodup",
            audio_bytes=b"x", audio_mime_type="audio/ogg", profile=None,
        )

    assert chamadas["n"] == 1  # não paga a Groq de novo numa reentrega
