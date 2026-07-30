"""O que cada transporte de WhatsApp sabe fazer — como DADO, não como `if` espalhado.

A Meta Cloud API exige template aprovado fora da janela de 24h; a Evolution (Baileys) não
conhece nenhum dos dois conceitos. Em vez de cada consumidor checar
`profile.whatsapp_provider == "meta"` (fácil de esquecer num consumidor novo), os 3 pontos que
precisam saber disso (fila de notificações ao resolver vínculo propósito→template, caixa de
resposta do inbox ao decidir entre texto livre e seletor de template, tela de Configurações ao
mostrar/esconder os cards de Templates e Vínculos) consultam este objeto — um transporte novo
sem entrada aqui quebra explicitamente em vez de falhar em silêncio.

Ver docs/superpowers/specs/2026-07-30-whatsapp-evolution-multi-tenant-design.md §4.

Nesta onda (Onda 0), `EVOLUTION` é dado sem provider atrás — `providers/evolution.py` chega na
Onda 1, e nenhum consumidor consegue alcançar `EVOLUTION` de fato até `TenantProfile
.whatsapp_provider` existir (Onda 2).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Capabilities:
    templates: bool
    session_window: bool
    media: bool
    provisioning: str  # "credentials" (Meta: cola token/phone_id) | "qrcode" (Evolution)


META = Capabilities(templates=True, session_window=True, media=True, provisioning="credentials")
EVOLUTION = Capabilities(
    templates=False, session_window=False, media=True, provisioning="qrcode"
)
