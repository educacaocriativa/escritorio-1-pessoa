"""Primitivo de busca textual — um lugar só para escapar curinga e montar o padrão do `ilike`.

Extraído de `payables/service.py` (#125) quando a busca global passou a precisar dele em sete
tabelas. Mora aqui, e não copiado por módulo, porque o modo de falha da divergência é MUDO: a cópia
que ficar para trás não quebra nada, só passa a não filtrar, e a tela continua respondendo.
"""
from __future__ import annotations

#: Passe sempre junto com o padrão: `coluna.ilike(padrao_ilike(termo), escape=ESCAPE)`.
#: Sem o `escape`, a barra invertida que este módulo insere é lida como texto e o escape não
#: acontece — o `ilike` volta a tratar `%` como curinga e o defeito reaparece silenciosamente.
ESCAPE = "\\"


def escapa_curinga(termo: str) -> str:
    """Neutraliza `%` e `_` para que o texto do usuário seja tratado como TEXTO no `ilike`.

    Sem isto, buscar `%` casa com todas as linhas e a busca parece funcionar enquanto não filtra
    nada — o pior tipo de defeito de busca, porque não tem sintoma.

    A barra invertida é escapada PRIMEIRO: fazê-lo por último re-escaparia as barras que os dois
    `replace` seguintes acabaram de inserir, e `%` viraria `\\\\%` (barra literal + curinga vivo).
    """
    return termo.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def padrao_ilike(termo: str) -> str:
    """`%termo%` com o miolo escapado. Os `%` das pontas são os curingas que a busca QUER."""
    return f"%{escapa_curinga(termo)}%"
