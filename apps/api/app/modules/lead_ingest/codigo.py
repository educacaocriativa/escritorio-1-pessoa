"""Código de origem dentro da mensagem de WhatsApp (spec §4.1 e §6.3). Puro, sem I/O.

O site abre `wa.me` com a mensagem pronta "… (código ig-r-c8abc)". Formato do código:
`<canal>-<tipo>-<id>`, minúsculas, máx. 20 caracteres, canal ∈ ig gg em wa pt. O prefixo é o
que deixa o e1p derivar a origem sem consultar o site.

Tolerante ao que a pessoa (ou o teclado) faz com a mensagem pronta: maiúsculas, espaços extras,
"codigo" sem acento, dois-pontos, e acento DECOMPOSTO (o iOS às vezes manda "o" + acento
combinante em vez de "ó"; sem normalizar, "código" não casaria). Exige a palavra "código"
antes: um "ig-r-abc" solto no meio da conversa não é atribuição.

Devolve o PRIMEIRO candidato válido: "meu código pt-br ... (código ig-r-c8abc)" tem dois
candidatos, e o primeiro ("pt-br") não é código; o segundo é.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

CANAIS = {
    "ig": "instagram",
    "gg": "google",
    "em": "email",
    "wa": "whatsapp",
    "pt": "parceria",
}
TAMANHO_MAX_CODIGO = 20
# Botão da landing sem toque prévio (spec §5.4): veio do site, origem desconhecida.
CODIGO_SEM_ORIGEM = "np-lp"

_NA_MENSAGEM = re.compile(
    r"c[oó]digo\s*[:#]?\s*(?P<codigo>[a-z0-9]+(?:-[a-z0-9]+)+)(?![a-z0-9-])",
    re.IGNORECASE,
)
_FORMATO = re.compile(r"^(?P<canal>ig|gg|em|wa|pt)-[a-z0-9]+-[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(frozen=True)
class CodigoLido:
    codigo: str
    origem: str | None  # None = `np-lp`: veio da landing sem toque rastreado


def _interpretar(codigo: str) -> CodigoLido | None:
    if len(codigo) > TAMANHO_MAX_CODIGO:
        return None
    if codigo == CODIGO_SEM_ORIGEM:
        return CodigoLido(codigo=codigo, origem=None)
    formato = _FORMATO.match(codigo)
    if formato is None:
        return None
    return CodigoLido(codigo=codigo, origem=CANAIS[formato.group("canal")])


def ler_codigo(texto: str | None) -> CodigoLido | None:
    if not texto:
        return None
    for achado in _NA_MENSAGEM.finditer(unicodedata.normalize("NFC", texto)):
        lido = _interpretar(achado.group("codigo").lower())
        if lido is not None:
            return lido
    return None
