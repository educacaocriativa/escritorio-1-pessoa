"""A busca global. Uma consulta curta por tipo, agrupada em Python.

**Sem `UNION`, e isso é decisão.** Como o resultado é agrupado por tipo (spec §9), não existe
ranking global a calcular — não há nada para o banco juntar. Cada consulta fica trivial, sem cast
entre sete modelos de formatos diferentes, e idêntica em SQLite e Postgres. É o que mantém isto
coberto pelo `pytest -q` inteiro, que roda SQLite.

**Sem índice de texto, e isso também é decisão medida.** Sob RLS, o Postgres não usa índice
trigrama nem tsvector para `ILIKE`: `texticlike` não é `leakproof`, então a política de segurança
tem que ser avaliada antes do operador e o `ILIKE` vira filtro pós-segurança. Medido em 2026-08-18:
0,7 ms com a RLS fora do caminho contra 154 ms com ela. Ver spec §5 antes de propor `pg_trgm`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import case, or_, select
from sqlalchemy.orm import Session

from app.core.textsearch import ESCAPE, escapa_curinga, padrao_ilike
from app.modules.search.registro import REGISTRO, Entidade

#: Abaixo disto a busca não consulta o banco. Uma letra casa com quase tudo e custaria sete
#: varreduras por tecla — e o resultado seria ruído, não resposta.
MIN_CARACTERES = 2


@dataclass
class ItemBruto:
    id: str
    titulo: str
    subtitulo: str
    rota: str
    trecho: str | None = None


@dataclass
class GrupoBruto:
    tipo: str
    itens: list[ItemBruto]
    tem_mais: bool
    total: int | None = None


def _liberado(entidade: Entidade, modulos_liberados: list[str]) -> bool:
    """Espelha `require_module`: lista vazia = sem restrição. Ver spec §6.4."""
    return not modulos_liberados or entidade.modulo in modulos_liberados


def _predicado(entidade: Entidade, padrao: str, fundo: bool, corte: datetime | None):
    """Construtor ÚNICO do predicado — usado pela LISTA e (na camada funda) pela CONTAGEM.

    ⚠️ **Não duplique este `where` do outro lado.** Dois blocos copiados divergem na primeira
    manutenção, e a partir daí a tela anuncia um `total` que a própria lista não confirma: nada
    quebra, o rodapé só passa a mentir. É a lição do #125, e ela custou caro para ser aprendida.
    """
    if entidade.predicado is not None:
        return entidade.predicado(padrao, ESCAPE, fundo, corte)
    campos = entidade.campos_rasos + (entidade.campos_fundos if fundo else ())
    return or_(*[coluna.ilike(padrao, escape=ESCAPE) for coluna in campos])


def _ordem(entidade: Entidade, termo: str):
    """Dois degraus: prefixo antes de casamento no meio; depois, o mais recente.

    Dois e não três porque cabe num `case()` portátil e num teste que se lê. Não há score entre
    tipos — o agrupamento por tipo substitui o ranking.
    """
    prefixo = f"{escapa_curinga(termo)}%"
    return (
        case((entidade.principal.ilike(prefixo, escape=ESCAPE), 0), else_=1),
        entidade.recencia.desc(),
    )


def buscar(
    db: Session,
    *,
    q: str,
    modulos_liberados: list[str],
    limite: int = 3,
) -> list[GrupoBruto]:
    """Camada rasa: rótulo + campos de identidade, agrupado por tipo, na ordem do registro."""
    termo = " ".join(q.split())
    if len(termo) < MIN_CARACTERES:
        return []

    padrao = padrao_ilike(termo)
    grupos: list[GrupoBruto] = []

    for entidade in REGISTRO:
        if not _liberado(entidade, modulos_liberados):
            continue
        stmt = (
            select(entidade.modelo)
            .where(_predicado(entidade, padrao, False, None))
            .order_by(*_ordem(entidade, termo))
            # +1 descobre `tem_mais` sem um `count()` por tipo. Um booleano não tem como mentir
            # sobre um número que ele não anuncia — a contagem exata é da camada funda.
            .limit(limite + 1)
        )
        linhas = list(db.scalars(stmt).all())
        if not linhas:
            continue
        grupos.append(
            GrupoBruto(
                tipo=entidade.tipo,
                itens=[
                    ItemBruto(
                        id=linha.id,
                        titulo=entidade.titulo(linha),
                        subtitulo=entidade.subtitulo(linha),
                        rota=entidade.rota(linha),
                    )
                    for linha in linhas[:limite]
                ],
                tem_mais=len(linhas) > limite,
            )
        )
    return grupos
