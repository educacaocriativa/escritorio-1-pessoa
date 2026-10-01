"""Soma de tags vindas de fora no contato: sem duplicar, sem estourar os limites do CRM.

O schema do CRM (`ClientBase._tags`) RECUSA lista acima do limite — certo para quem edita na
tela, errado para a ingestão: recusar seria 422, a fila do site trataria como erro permanente e
a venda ficaria sem contato. A spec (§6.2) manda o contrário: acrescenta o que couber e REGISTRA
o que sobrou (o fato na linha do tempo leva a origem completa e a lista de descartadas).
"""
from __future__ import annotations

from app.modules.crm.models import TAG_LIMIT, TAG_MAX_LENGTH


def somar_tags(atuais: list[str] | None, novas: list[str]) -> tuple[list[str], list[str]]:
    """Devolve `(tags_resultantes, descartadas)`, nas ordens de chegada. Não muta `atuais`.

    Tags NOVAS chegam normalizadas — sem espaço nas pontas, em minúsculas: a taxonomia da spec
    (§4) é minúscula, e `Origem:Instagram` e `origem:instagram` virariam dois filtros no CRM. As
    que já estavam no contato ficam como estão: o dono pode ter escrito "Tem Filhos" à mão.
    """
    resultado = list(atuais or [])
    descartadas: list[str] = []
    for bruta in novas:
        tag = bruta.strip().lower()
        if not tag or tag in resultado or tag in descartadas:
            continue
        if len(tag) > TAG_MAX_LENGTH or len(resultado) >= TAG_LIMIT:
            descartadas.append(tag)
            continue
        resultado.append(tag)
    return resultado, descartadas
