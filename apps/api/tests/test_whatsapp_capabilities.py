"""Testes de app/core/whatsapp/capabilities.py — o que cada transporte sabe fazer, como DADO,
não como `if` espalhado pelos consumidores (ver spec §4)."""
from __future__ import annotations

import dataclasses

import pytest

from app.core.whatsapp.capabilities import EVOLUTION, META, Capabilities


def test_meta_capabilities() -> None:
    assert META == Capabilities(
        templates=True, session_window=True, media=True, provisioning="credentials",
    )


def test_evolution_capabilities() -> None:
    assert EVOLUTION == Capabilities(
        templates=False, session_window=False, media=True, provisioning="qrcode",
    )


def test_capabilities_is_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        META.templates = False  # type: ignore[misc]
