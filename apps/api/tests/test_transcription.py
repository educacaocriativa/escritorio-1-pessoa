"""Transcrição de voz via Groq — a chamada real (`httpx.post`) é sempre mockada, mesmo padrão de
`test_whatsapp.py` (este ambiente não tem credenciais reais)."""
from __future__ import annotations

import httpx
import pytest
from sqlalchemy.orm import Session

from app.config import settings
from app.core import transcription
from app.core.ai_usage import AIUsage

TENANT = "t-transcricao"


class _FakeResponse:
    def __init__(self, status_code: int = 200, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "erro", request=httpx.Request("POST", "https://x"), response=self
            )

    def json(self) -> dict:
        return self._payload

    @property
    def text(self) -> str:
        return str(self._payload)


@pytest.fixture(autouse=True)
def _sem_chave_por_padrao(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "groq_api_key", "")


def test_sem_groq_api_key_devolve_none_sem_chamar_httpx(db: Session, monkeypatch):
    def _boom(*_a, **_kw):
        raise AssertionError("httpx.post não deveria ser chamado sem GROQ_API_KEY")

    monkeypatch.setattr(httpx, "post", _boom)

    resultado = transcription.transcribe(
        db, tenant_id=TENANT, audio_bytes=b"audio", mime_type="audio/ogg",
    )
    assert resultado is None


def test_transcricao_com_sucesso_grava_no_ledger_e_devolve_texto(db: Session, monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "gsk-fake")
    monkeypatch.setattr(
        httpx, "post",
        lambda *a, **kw: _FakeResponse(
            200, {"text": " quanto tenho a receber essa semana? ", "duration": 3.4}
        ),
    )

    resultado = transcription.transcribe(
        db, tenant_id=TENANT, audio_bytes=b"audio-bytes", mime_type="audio/ogg",
        user_id="user-1",
    )

    assert resultado is not None
    assert resultado.text == "quanto tenho a receber essa semana?"
    assert resultado.audio_seconds == 3.4

    linha = db.query(AIUsage).one()
    assert linha.provider == "groq"
    assert linha.task == "vima.transcricao"
    assert linha.model == transcription._MODELO
    assert linha.audio_seconds == 3.4
    assert linha.user_id == "user-1"
    assert linha.input_tokens == 0  # a "moeda" da Groq é audio_seconds, não token


def test_transcricao_manda_o_arquivo_e_o_modelo_certo(db: Session, monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "gsk-fake")
    capturado = {}

    def _fake_post(url, *, headers, files, data, timeout):
        capturado.update(url=url, headers=headers, files=files, data=data)
        return _FakeResponse(200, {"text": "oi", "duration": 1.0})

    monkeypatch.setattr(httpx, "post", _fake_post)

    transcription.transcribe(db, tenant_id=TENANT, audio_bytes=b"XYZ", mime_type="audio/ogg")

    assert capturado["headers"]["Authorization"] == "Bearer gsk-fake"
    assert capturado["data"]["model"] == transcription._MODELO
    assert capturado["files"]["file"][1] == b"XYZ"
    assert capturado["files"]["file"][2] == "audio/ogg"


def test_nome_do_arquivo_enviado_tem_extensao_ogg_para_mime_ogg(db: Session, monkeypatch):
    # Groq espelha a API Whisper da OpenAI, que infere o container do áudio pela extensão do
    # nome do arquivo — um nome sem extensão ("audio", sem sufixo) pode ser rejeitado. Notas de
    # voz do WhatsApp via Baileys/Evolution são sempre audio/ogg.
    monkeypatch.setattr(settings, "groq_api_key", "gsk-fake")
    capturado = {}

    def _fake_post(url, *, headers, files, data, timeout):
        capturado.update(files=files)
        return _FakeResponse(200, {"text": "oi", "duration": 1.0})

    monkeypatch.setattr(httpx, "post", _fake_post)

    transcription.transcribe(db, tenant_id=TENANT, audio_bytes=b"XYZ", mime_type="audio/ogg")

    assert capturado["files"]["file"][0].endswith(".ogg")


def test_nome_do_arquivo_enviado_cai_no_default_ogg_para_mime_desconhecido(
    db: Session, monkeypatch,
):
    monkeypatch.setattr(settings, "groq_api_key", "gsk-fake")
    capturado = {}

    def _fake_post(url, *, headers, files, data, timeout):
        capturado.update(files=files)
        return _FakeResponse(200, {"text": "oi", "duration": 1.0})

    monkeypatch.setattr(httpx, "post", _fake_post)

    transcription.transcribe(
        db, tenant_id=TENANT, audio_bytes=b"XYZ", mime_type="application/x-desconhecido",
    )

    assert capturado["files"]["file"][0].endswith(".ogg")


def test_erro_http_da_groq_devolve_none_sem_gravar_ledger(db: Session, monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "gsk-fake")
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _FakeResponse(401, {}))

    resultado = transcription.transcribe(
        db, tenant_id=TENANT, audio_bytes=b"audio", mime_type="audio/ogg",
    )
    assert resultado is None
    assert db.query(AIUsage).count() == 0


def test_erro_de_rede_devolve_none(db: Session, monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "gsk-fake")

    def _raise(*_a, **_kw):
        raise httpx.ConnectError("sem rede")

    monkeypatch.setattr(httpx, "post", _raise)

    resultado = transcription.transcribe(
        db, tenant_id=TENANT, audio_bytes=b"audio", mime_type="audio/ogg",
    )
    assert resultado is None


def test_texto_vazio_da_groq_devolve_none(db: Session, monkeypatch):
    # Áudio ilegível: a Groq às vezes devolve texto vazio (ou só espaços) em vez de erro HTTP.
    monkeypatch.setattr(settings, "groq_api_key", "gsk-fake")
    monkeypatch.setattr(
        httpx, "post", lambda *a, **kw: _FakeResponse(200, {"text": "   ", "duration": 0.5}),
    )

    resultado = transcription.transcribe(
        db, tenant_id=TENANT, audio_bytes=b"audio", mime_type="audio/ogg",
    )
    assert resultado is None


def test_duration_nao_numerico_da_groq_devolve_none_sem_levantar(db: Session, monkeypatch):
    # 200 com corpo em formato inesperado — não é erro HTTP, mas `float(duracao)` levantaria
    # ValueError se a leitura do payload não estivesse dentro do mesmo guard do erro de rede.
    monkeypatch.setattr(settings, "groq_api_key", "gsk-fake")
    monkeypatch.setattr(
        httpx, "post",
        lambda *a, **kw: _FakeResponse(200, {"text": "oi", "duration": "nao-e-numero"}),
    )

    resultado = transcription.transcribe(
        db, tenant_id=TENANT, audio_bytes=b"audio", mime_type="audio/ogg",
    )
    assert resultado is None
    assert db.query(AIUsage).count() == 0


def test_duration_ausente_do_payload_devolve_none(db: Session, monkeypatch):
    # Diferente do caso "duration não numérico": aqui a chave nem existe no payload — `.get()`
    # devolve None, e o guard `duracao is None` precisa pegar isso sem nunca chegar em `float()`.
    monkeypatch.setattr(settings, "groq_api_key", "gsk-fake")
    monkeypatch.setattr(
        httpx, "post", lambda *a, **kw: _FakeResponse(200, {"text": "oi"}),
    )

    resultado = transcription.transcribe(
        db, tenant_id=TENANT, audio_bytes=b"audio", mime_type="audio/ogg",
    )
    assert resultado is None
    assert db.query(AIUsage).count() == 0


def test_payload_nao_e_dict_devolve_none_sem_levantar(db: Session, monkeypatch):
    # Um corpo 200 que não é dict (lista, string...) faria `.get()` levantar AttributeError — a
    # promessa "nunca levanta" da assinatura depende do guard `except Exception` cobrir isso.
    monkeypatch.setattr(settings, "groq_api_key", "gsk-fake")
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _FakeResponse(200, ["nao", "e", "dict"]))

    resultado = transcription.transcribe(
        db, tenant_id=TENANT, audio_bytes=b"audio", mime_type="audio/ogg",
    )
    assert resultado is None
    assert db.query(AIUsage).count() == 0
