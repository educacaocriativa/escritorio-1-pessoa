"""Testes de app/core/whatsapp/capabilities.py — o que cada transporte sabe fazer, como DADO,
não como `if` espalhado pelos consumidores (ver spec §4)."""
from __future__ import annotations

import dataclasses

import pytest

from app.core import whatsapp
from app.core.whatsapp.capabilities import EVOLUTION, META, Capabilities, for_profile
from app.core.whatsapp.providers import evolution as evolution_provider
from app.core.whatsapp.providers import meta as meta_provider


class _Profile:
    """Dublê mínimo — `for_profile` só lê `whatsapp_provider` (mesmo padrão do dublê de
    tests/test_whatsapp_dispatcher.py)."""

    def __init__(self, provider: str | None) -> None:
        self.whatsapp_provider = provider


def test_meta_capabilities() -> None:
    assert META == Capabilities(
        templates=True, session_window=True, media=True, provisioning="credentials",
        briefing_needs_optin=True,
    )


def test_evolution_capabilities() -> None:
    assert EVOLUTION == Capabilities(
        templates=False, session_window=False, media=True, provisioning="qrcode",
        briefing_needs_optin=False,
    )


def test_capabilities_is_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        META.templates = False  # type: ignore[misc]


def test_for_profile_evolution() -> None:
    assert for_profile(_Profile("evolution")) is EVOLUTION


@pytest.mark.parametrize("provider", ["meta", None, "", "transporte-que-nao-existe"])
def test_for_profile_cai_em_meta(provider: str | None) -> None:
    """Qualquer valor diferente de "evolution" (inclusive `None` = nunca conectou) é Meta —
    MESMA regra do despachante, por construção (ver o teste de acordo abaixo)."""
    assert for_profile(_Profile(provider)) is META


def test_for_profile_sem_perfil_e_meta() -> None:
    assert for_profile(None) is META


@pytest.mark.parametrize("provider", ["evolution", "meta", None, "transporte-que-nao-existe"])
def test_capabilities_e_despachante_nunca_divergem(provider: str | None) -> None:
    """Gate estrutural: capability e provider REAL têm que concordar sempre.

    Se divergissem, um consumidor consultaria `capabilities` (e concluiria "posso mandar texto
    livre") enquanto o despachante entregaria pela Meta (que exige template fora da janela) — o
    envio falharia longe daqui, no worker, sem ninguém para relacionar as duas decisões. Por isso
    `_resolve` deriva de `for_profile`, e este teste prova que continua derivando."""
    profile = _Profile(provider)
    esperado = evolution_provider if for_profile(profile) is EVOLUTION else meta_provider
    assert whatsapp._resolve(profile) is esperado
