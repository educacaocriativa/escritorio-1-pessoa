"""Camada única de acesso à IA (Claude).

REGRA: todo texto que entra aqui DEVE já estar anonimizado (ver anonymizer.py).
Esta camada não conhece dados reais — ela só fala com a Anthropic e devolve tokens + texto.
"""
from __future__ import annotations

from dataclasses import dataclass

from anthropic import Anthropic

from app.config import settings

_client: Anthropic | None = None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=settings.anthropic_api_key)
    return _client


@dataclass
class AIResult:
    text: str
    input_tokens: int
    output_tokens: int


def complete(
    *,
    system: str,
    user_message: str,
    max_tokens: int = 4096,
    model: str | None = None,
) -> AIResult:
    """Chamada simples de completude. `user_message` deve estar anonimizado."""
    resp = _get_client().messages.create(
        model=model or settings.anthropic_model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user_message}],
    )
    return AIResult(
        text=resp.content[0].text,
        input_tokens=resp.usage.input_tokens,
        output_tokens=resp.usage.output_tokens,
    )
