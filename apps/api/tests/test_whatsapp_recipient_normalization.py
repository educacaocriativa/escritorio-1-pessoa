"""O destinatário é normalizado na FRONTEIRA (despachante), não em cada call site.

Bug real de produção (2026-08-05): o nó de WhatsApp do funil registrava a mensagem e ela nunca
chegava. A Evolution devolvia `400`, e a sondagem do endpoint `/chat/whatsappNumbers` provou o
motivo — o contato estava gravado como `43984074017` (o que o dono digitou, sem código do país)
e esse número **não existe** no WhatsApp; `5543984074017` existe.

A forma normalizada já era calculada em `clients.phone_key` (PR #76), mas os 6 caminhos que
enviam WhatsApp (funil, alerta pra equipe, convite de funcionário, orçamento, cobrança,
contrato) resolvem o destinatário de campos de telefone CRUS, e só `Client` tem gêmeo
normalizado. Corrigir call site por call site deixaria 4 deles quebrados — por isso a
normalização vive no despachante, que é por onde TODO envio passa.

Decisão de produto do fundador: o produto é BR-only (CPF/CNPJ, boleto, Pix), então assume-se
número brasileiro. Um celular estrangeiro de 10-11 dígitos seria reescrito como BR — daí toda
reescrita ser logada em nível INFO, para que o caso apareça em vez de sumir.
"""
from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest

from app.core import whatsapp
from app.core.whatsapp.providers import evolution, meta
from app.modules.settings.models import TenantProfile

TENANT_ID = "99999999-9999-9999-9999-999999999999"


@pytest.fixture()
def enviados(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Captura o `to` que chegou NO PROVIDER — o que de fato vai pra rede."""
    destinos: list[str] = []

    def _fake(**kwargs: object) -> str:
        destinos.append(str(kwargs["to"]))
        return "sent"

    monkeypatch.setattr(evolution, "send_text", _fake)
    monkeypatch.setattr(meta, "send_text", _fake)
    return destinos


def _evolution() -> TenantProfile:
    return TenantProfile(tenant_id=TENANT_ID, whatsapp_provider="evolution")


def test_numero_sem_codigo_do_pais_ganha_o_55(enviados: list[str]) -> None:
    """O bug reportado, na forma mínima."""
    whatsapp.send_text(to="43984074017", text="oi", profile=_evolution())
    assert enviados == ["5543984074017"]


def test_numero_como_a_pessoa_digitou(enviados: list[str]) -> None:
    """`clients.phone` guarda o que foi digitado, com máscara e tudo — é evidência, não
    endereço. Quem transforma em endereço é o despachante."""
    whatsapp.send_text(to="(43) 98407-4017", text="oi", profile=_evolution())
    assert enviados == ["5543984074017"]


def test_numero_ja_normalizado_passa_igual(enviados: list[str]) -> None:
    whatsapp.send_text(to="5543984074017", text="oi", profile=_evolution())
    assert enviados == ["5543984074017"]


def test_vale_tambem_para_a_meta(enviados: list[str]) -> None:
    """A Cloud API também exige o número internacional — a normalização é do transporte
    WhatsApp, não de um provider específico."""
    whatsapp.send_text(to="43984074017", text="oi", profile=None)
    assert enviados == ["5543984074017"]


# ── O que NÃO pode ser tocado ────────────────────────────────────────────────
# Nem todo `to` é telefone: grupo é JID, contato não identificado é `@lid`, e o destinatário do
# owner cai em e-mail (placeholder histórico) ou no NOME do contato quando não há telefone.
# Reescrever qualquer um desses seria trocar um envio que falha visível por um que vai pro
# lugar errado.


@pytest.mark.parametrize(
    "destino",
    [
        "120363123456789012@g.us",   # grupo
        "123456789012345@lid",       # contato não identificado
        "dono@example.com",          # fallback histórico de _owner_recipient
        "Flavio Kato",               # fallback do funil quando o contato não tem telefone
        "legacy:unidentified",       # JID sintético do backfill da 0066
        "",                          # nunca vira "55" + lixo
    ],
)
def test_destino_que_nao_e_telefone_passa_intacto(
    enviados: list[str], destino: str
) -> None:
    whatsapp.send_text(to=destino, text="oi", profile=_evolution())
    assert enviados == [destino]


@pytest.fixture()
def logs() -> Iterator[list[str]]:
    """Handler PRÓPRIO, preso ao logger `e1p.whatsapp`.

    Não usa `caplog`: ele captura por um handler na raiz, e o nível efetivo da raiz depende do
    que os ~1700 outros testes da suíte deixaram para trás (`app/main.py` e `app/worker.py`
    chamam `logging.basicConfig` na importação). Este teste passava sozinho e falhava na suíte
    inteira — a asserção estava medindo o estado global de logging, não o comportamento do
    despachante."""
    logger = logging.getLogger("e1p.whatsapp")
    capturado: list[str] = []

    class _Coletor(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            capturado.append(record.getMessage())

    handler = _Coletor(level=logging.INFO)
    nivel_anterior, propaga_anterior = logger.level, logger.propagate
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False  # não suja a saída dos outros testes
    try:
        yield capturado
    finally:
        logger.removeHandler(handler)
        logger.setLevel(nivel_anterior)
        logger.propagate = propaga_anterior


def test_reescrita_e_logada(enviados: list[str], logs: list[str]) -> None:
    """A reescrita precisa ser observável: é ela que carrega a suposição BR-only, e o caso
    estrangeiro só aparece se a gente registrar quando mexemos no número."""
    whatsapp.send_text(to="43984074017", text="oi", profile=_evolution())
    assert any("43984074017" in m and "5543984074017" in m for m in logs)


def test_numero_intacto_nao_polui_o_log(enviados: list[str], logs: list[str]) -> None:
    whatsapp.send_text(to="5543984074017", text="oi", profile=_evolution())
    assert logs == []


def test_send_media_normaliza_igual(monkeypatch: pytest.MonkeyPatch) -> None:
    destinos: list[str] = []
    monkeypatch.setattr(
        evolution, "send_media", lambda **kw: (destinos.append(str(kw["to"])), "sent")[1]
    )
    whatsapp.send_media(
        to="43984074017", kind="image", media_id="x", profile=_evolution()
    )
    assert destinos == ["5543984074017"]


def test_send_template_normaliza_igual(monkeypatch: pytest.MonkeyPatch) -> None:
    destinos: list[str] = []
    monkeypatch.setattr(
        meta, "send_template", lambda **kw: (destinos.append(str(kw["to"])), "sent")[1]
    )
    whatsapp.send_template(
        to="43984074017", template_name="t", language="pt_BR", variables=[], profile=None
    )
    assert destinos == ["5543984074017"]
