"""A busca global. Uma consulta curta por tipo, agrupada em Python.

**Sem `UNION`, e isso é decisão.** Como o resultado é agrupado por tipo (spec §9), não existe
ranking global a calcular — não há nada para o banco juntar. Cada consulta fica trivial, sem cast
entre oito modelos de formatos diferentes, e idêntica em SQLite e Postgres. É o que mantém isto
coberto pelo `pytest -q` inteiro, que roda SQLite.

**Sem índice de texto, e isso também é decisão medida.** Sob RLS, o Postgres não usa índice
trigrama nem tsvector para `ILIKE`: `texticlike` não é `leakproof`, então a política de segurança
tem que ser avaliada antes do operador e o `ILIKE` vira filtro pós-segurança. Medido em 2026-08-18:
0,7 ms com a RLS fora do caminho contra 154 ms com ela. Ver spec §5 antes de propor `pg_trgm`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.core.textsearch import ESCAPE, escapa_curinga, padrao_ilike
from app.modules.search.registro import REGISTRO, Entidade
from app.modules.settings.service import hoje_do_tenant

#: Abaixo disto a busca não consulta o banco. Uma letra casa com quase tudo e custaria oito
#: varreduras por tecla — e o resultado seria ruído, não resposta.
MIN_CARACTERES = 2

#: O trecho mostrado na camada funda. Assimétrico de propósito: o que vem DEPOIS do termo costuma
#: ser o que explica a frase; o que vem antes serve só para o olho reconhecer onde está.
TRECHO_ANTES = 40
TRECHO_DEPOIS = 80


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


def _trecho(texto: str, termo: str) -> str:
    """Um pedaço do corpo em volta do casamento, para o leitor reconhecer o contexto."""
    if not texto:
        return ""
    pos = texto.lower().find(termo.lower())
    if pos < 0:
        return texto[:TRECHO_DEPOIS]
    inicio = max(0, pos - TRECHO_ANTES)
    fim = min(len(texto), pos + len(termo) + TRECHO_DEPOIS)
    return ("..." if inicio > 0 else "") + texto[inicio:fim] + ("..." if fim < len(texto) else "")


def _trecho_da_linha(entidade: Entidade, linha, termo: str) -> str | None:
    """O primeiro campo fundo que contém o termo vira o trecho mostrado na tela."""
    for coluna in entidade.campos_fundos:
        texto = getattr(linha, coluna.key, "") or ""
        if termo.lower() in texto.lower():
            return _trecho(texto, termo)
    return None


def _corte_de_mensagens(db: Session, meses: int) -> datetime | None:
    """A data-piso do recorte, no FUSO DO TENANT. `meses <= 0` significa "tudo".

    `datetime.now(UTC)` aqui reintroduziria a classe de bug do fuso pela porta do filtro de data:
    em UTC-3, das 21h à meia-noite o piso pularia um dia inteiro.
    """
    if meses <= 0:
        return None
    piso = hoje_do_tenant(db) - timedelta(days=30 * meses)
    return datetime.combine(piso, time.min, tzinfo=UTC)


def buscar(
    db: Session,
    *,
    q: str,
    modulos_liberados: list[str],
    profundidade: str = "shallow",
    meses: int = 12,
    limite: int = 3,
) -> list[GrupoBruto]:
    """Rasa: rótulo + identidade. Funda: acrescenta corpo, notas e mensagens.

    Agrupado por tipo, na ordem do registro. Grupo sem item não entra no resultado.
    """
    termo = " ".join(q.split())
    if len(termo) < MIN_CARACTERES:
        return []

    fundo = profundidade == "deep"
    padrao = padrao_ilike(termo)
    corte = _corte_de_mensagens(db, meses) if fundo else None
    grupos: list[GrupoBruto] = []

    for entidade in REGISTRO:
        if not _liberado(entidade, modulos_liberados):
            continue
        onde = _predicado(entidade, padrao, fundo, corte)
        stmt = (
            select(entidade.modelo)
            .where(onde)
            .order_by(*_ordem(entidade, termo))
            # +1 descobre `tem_mais` sem um `count()` por tipo. Um booleano não tem como mentir
            # sobre um número que ele não anuncia — a contagem exata é da camada funda.
            .limit(limite + 1)
        )
        linhas = list(db.scalars(stmt).all())
        if not linhas:
            continue
        # MESMO `onde` da lista. Contar com um predicado paralelo faria o rodapé anunciar um
        # número que a lista não confirma — nada quebra, o rodapé só passa a mentir (#125).
        total = (
            db.scalar(select(func.count()).select_from(entidade.modelo).where(onde))
            if fundo
            else None
        )
        grupos.append(
            GrupoBruto(
                tipo=entidade.tipo,
                itens=[
                    ItemBruto(
                        id=linha.id,
                        titulo=entidade.titulo(linha),
                        subtitulo=entidade.subtitulo(linha),
                        rota=entidade.rota(linha),
                        trecho=_trecho_da_linha(entidade, linha, termo) if fundo else None,
                    )
                    for linha in linhas[:limite]
                ],
                tem_mais=len(linhas) > limite,
                total=total,
            )
        )
    return grupos
