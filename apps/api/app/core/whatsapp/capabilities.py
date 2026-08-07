"""O que cada transporte de WhatsApp sabe fazer — como DADO, não como `if` espalhado.

A Meta Cloud API exige template aprovado fora da janela de 24h; a Evolution (Baileys) não
conhece nenhum dos dois conceitos. Em vez de cada consumidor checar
`profile.whatsapp_provider == "meta"` (fácil de esquecer num consumidor novo), quem precisa
saber disso chama `for_profile(profile)`.

Ver docs/superpowers/specs/2026-07-30-whatsapp-evolution-multi-tenant-design.md §4.

⚠️ **Este módulo nasceu (Onda 0) descrevendo 3 consumidores que nunca foram escritos** — ficou
com zero call sites em produção e só o próprio teste unitário, enquanto as regras da Meta
seguiam rodando incondicionalmente sob a Evolution. Isso custou dois bugs reais, achados usando
o produto conectado por QR code: o nó de WhatsApp do funil exigindo template aprovado, e a
janela de 24h emudecendo a conversa no inbox. **A docstring afirmava que os consumidores
existiam, e nada contradizia a afirmação** — um módulo de capacidades sem consumidor não
protege ninguém; ele só documenta uma intenção. Antes de adicionar uma capacidade aqui,
escreva o consumidor no mesmo passo.

Consumidores REAIS hoje (verificáveis por grep de `capabilities.for_profile` /
`whatsapp_capabilities`):
- `app/core/whatsapp/__init__.py::_resolve` — escolhe o provider (a resolução é DERIVADA daqui,
  então capacidade e provider não conseguem divergir; gate em tests/test_whatsapp_capabilities).
- `app/modules/funnels/service.py::run_node` (`send_message`) — template aprovado × texto livre.
- `app/modules/whatsapp_inbox/service.py::is_within_session_window` — janela de 24h.
- `app/modules/notifications/service.py::process_pending` — guarda de ENTREGA: os 5 pontos do
  domínio que resolvem vínculo propósito→template no enfileiramento não sabem por qual
  transporte a mensagem sai; a decisão final é tomada aqui, onde o transporte é conhecido.
- `app/modules/vima/scheduler.py::_entregar_no_whatsapp` — briefing em um passo × dois passos.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.modules.settings.models import TenantProfile


@dataclass(frozen=True)
class Capabilities:
    templates: bool
    session_window: bool
    media: bool
    provisioning: str  # "credentials" (Meta: cola token/phone_id) | "qrcode" (Evolution)
    # O briefing diário precisa de um "pode mandar?" do dono ANTES do texto?
    #
    # Meta: sim. Parâmetro de template da Cloud API não aceita quebra de linha (e o briefing tem
    # várias), e às 7h o dono está sempre fora da janela de 24h — então o que sai primeiro é um
    # template curto com botão de resposta rápida; o toque abre a janela e o texto inteiro sai
    # depois, livre. Evolution: não. Não tem janela nem template — sai direto, em um passo.
    #
    # NÃO é uma reescrita de `templates`/`session_window`: aquelas dizem o que o transporte
    # SUPORTA; esta diz o que ESTE fluxo precisa fazer por causa disso. Um transporte futuro com
    # template e sem janela (ou com janela de 7 dias) as combinaria de outro jeito.
    #
    # Consumidor (verificável por grep — este módulo já passou meses com zero call sites enquanto
    # a docstring afirmava ter três):
    #   - app/modules/vima/scheduler.py::_entregar_no_whatsapp
    briefing_needs_optin: bool


META = Capabilities(
    templates=True, session_window=True, media=True, provisioning="credentials",
    briefing_needs_optin=True,
)
EVOLUTION = Capabilities(
    templates=False, session_window=False, media=True, provisioning="qrcode",
    briefing_needs_optin=False,
)


def for_profile(profile: TenantProfile | None) -> Capabilities:
    """O que o transporte DESTE tenant sabe fazer.

    `None` (perfil ausente) ou qualquer valor diferente de "evolution" é Meta — inclusive
    `None`/"meta" (tenant que nunca conectou por QR). É deliberadamente a MESMA regra de
    `whatsapp.__init__._resolve`, que a deriva desta função em vez de repetir a comparação:
    capacidade e provider divergirem produziria um envio que passa na validação aqui e falha
    lá no worker, longe de quem poderia relacionar as duas decisões.
    """
    if profile is not None and profile.whatsapp_provider == "evolution":
        return EVOLUTION
    return META
