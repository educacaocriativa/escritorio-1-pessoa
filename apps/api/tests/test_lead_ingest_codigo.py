"""Leitura do código `<canal>-<tipo>-<id>` na mensagem de WhatsApp (spec §4.1 e §6.3)."""
import unicodedata

import pytest

from app.modules.lead_ingest.codigo import CodigoLido, ler_codigo


@pytest.mark.parametrize(
    ("texto", "codigo", "origem"),
    [
        ("Olá! Quero saber da Publ.IA (código ig-r-c8abc)", "ig-r-c8abc", "instagram"),
        ("CÓDIGO IG-R-C8ABC", "ig-r-c8abc", "instagram"),
        ("codigo   gg-s-out26a obrigado", "gg-s-out26a", "google"),
        ("código: em-n12-topo", "em-n12-topo", "email"),
        ("Oi (código wa-l-abc1).", "wa-l-abc1", "whatsapp"),
        ("código pt-x-parc1", "pt-x-parc1", "parceria"),
        (unicodedata.normalize("NFD", "código ig-b-bio1"), "ig-b-bio1", "instagram"),
        ("código ig-r-" + "a" * 15, "ig-r-" + "a" * 15, "instagram"),  # exatamente 20
        ("Olá! Quero saber da Publ.IA (código np-lp)", "np-lp", None),
        # Variantes da palavra "código": capitalizada, sem acento, caixa alta, espaços extras.
        ("Código ig-r-c8abc", "ig-r-c8abc", "instagram"),
        ("CODIGO ig-r-c8abc", "ig-r-c8abc", "instagram"),
        ("código      ig-r-c8abc", "ig-r-c8abc", "instagram"),
        ("código #ig-r-c8abc", "ig-r-c8abc", "instagram"),
        # E9: o primeiro candidato não é código; vale o primeiro VÁLIDO.
        ("meu código pt-br é esse (código ig-r-c8abc)", "ig-r-c8abc", "instagram"),
        ("código xx-r-abc e depois código gg-s-out26a", "gg-s-out26a", "google"),
        ("código ig-r-" + "a" * 16 + " ou código em-n1-ok", "em-n1-ok", "email"),
    ],
)
def test_le_codigo_valido(texto, codigo, origem):
    assert ler_codigo(texto) == CodigoLido(codigo=codigo, origem=origem)


@pytest.mark.parametrize(
    "texto",
    [
        None,
        "",
        "Olá, quero saber da Publ.IA",
        "ig-r-c8abc sem a palavra-chave",
        "meu código pt-br é esse",  # dois segmentos: não é código
        "código xx-r-abc",  # canal desconhecido
        "código ig-r-",
        "código ig-r-" + "a" * 16,  # 21 caracteres
    ],
)
def test_ignora_o_que_nao_e_codigo(texto):
    assert ler_codigo(texto) is None
