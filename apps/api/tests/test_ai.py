"""Testes unitários diretos da camada de IA (`core/ai.py`).

Cobrem, isoladamente (sem tocar a API real do Claude), a montagem do prompt,
o parsing de `AIResult` e a propagação de erro — pré-condição dos fallbacks
implementados em cada caller (marketing, juridico, funnels, quotes,
financial_intelligence, receivables).
"""
from types import SimpleNamespace

import pytest

from app.config import settings
from app.core import ai


class _FakeMessages:
    """Captura os kwargs de `create(...)` e devolve uma resposta fixa (ou lança)."""

    def __init__(self, response=None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.captured: dict | None = None

    def create(self, **kwargs):
        self.captured = kwargs
        if self.error is not None:
            raise self.error
        return self.response


class _FakeClient:
    def __init__(self, messages: _FakeMessages):
        self.messages = messages


def _ok_response(text="ok", input_tokens=1, output_tokens=1):
    return SimpleNamespace(
        content=[SimpleNamespace(text=text)],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def _install_fake(monkeypatch, *, response=None, error=None) -> _FakeMessages:
    messages = _FakeMessages(response=response, error=error)
    client = _FakeClient(messages)
    monkeypatch.setattr(ai, "_get_client", lambda: client)
    return messages


def test_complete_builds_prompt_with_system_and_user_message(monkeypatch):
    messages = _install_fake(monkeypatch, response=_ok_response())
    ai.complete(system="SYS", user_message="MSG", max_tokens=123)
    kwargs = messages.captured
    assert kwargs["system"] == "SYS"
    assert kwargs["messages"] == [{"role": "user", "content": "MSG"}]
    assert kwargs["max_tokens"] == 123
    assert kwargs["model"] == settings.anthropic_model  # default


def test_complete_uses_explicit_model_override(monkeypatch):
    messages = _install_fake(monkeypatch, response=_ok_response())
    ai.complete(system="S", user_message="U", model="modelo-x")
    assert messages.captured["model"] == "modelo-x"


def test_complete_uses_default_max_tokens(monkeypatch):
    messages = _install_fake(monkeypatch, response=_ok_response())
    ai.complete(system="S", user_message="U")
    assert messages.captured["max_tokens"] == 4096


def test_complete_parses_ai_result_from_response(monkeypatch):
    _install_fake(
        monkeypatch,
        response=_ok_response(text="resposta da IA", input_tokens=10, output_tokens=20),
    )
    result = ai.complete(system="S", user_message="U")
    assert isinstance(result, ai.AIResult)
    assert result.text == "resposta da IA"
    assert result.input_tokens == 10
    assert result.output_tokens == 20


def test_complete_propagates_client_error(monkeypatch):
    _install_fake(monkeypatch, error=RuntimeError("api indisponível"))
    # A exceção sobe crua — é isso que permite o try/except de fallback dos callers.
    with pytest.raises(RuntimeError, match="api indisponível"):
        ai.complete(system="S", user_message="U")
