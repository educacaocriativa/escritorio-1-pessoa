"""Barramento de eventos interno (síncrono, in-process).

Permite que módulos reajam a fatos de outros sem acoplamento direto de import.
Ex.: mover um card do CRM para "Venda" emite `crm.client.moved`, e o módulo financeiro
(quando existir) se inscreve para gerar a cobrança. Por ora não há assinantes — o padrão
fica estabelecido.

Limitação: é in-process e síncrono. Integrações que precisam durar além da request
(disparos WhatsApp, chamadas externas) devem ir para a fila (SQS) quando o worker existir.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable
from typing import Any

logger = logging.getLogger("e1p.events")

Handler = Callable[..., None]

_subscribers: dict[str, list[Handler]] = defaultdict(list)


def subscribe(event_name: str, handler: Handler) -> None:
    _subscribers[event_name].append(handler)


def emit(event_name: str, **payload: Any) -> None:
    """Dispara o evento para todos os assinantes.

    Cada assinante é isolado: uma exceção é registrada e não derruba os demais nem o
    chamador (o fato já aconteceu e foi commitado; reações são best-effort). Reações que
    PRECISAM ser confiáveis devem ir para a fila durável (SQS), não para este barramento.
    """
    for handler in _subscribers.get(event_name, []):
        try:
            handler(**payload)
        except Exception:
            logger.exception("Assinante de '%s' falhou", event_name)


def clear() -> None:
    """Apenas para testes: remove todos os assinantes."""
    _subscribers.clear()
