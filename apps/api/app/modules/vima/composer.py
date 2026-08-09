"""Colapsa, agrega, prioriza e corta. Puro — sem banco, sem relógio, sem rede.

**O compositor decide O QUE entra e em que ordem. A Claude decide apenas COMO dizer.**

Se a LLM escolhesse o que importa, isso seria Inferência — a categoria deferida ao V4 por
assimetria de credibilidade. A priorização aqui é determinística: peso fixo por `kind` mais
recência. Chata e previsível, que é o ponto.

`valores` chega pronto de fora, mapeando `(subject_type, subject_id) → "R$ 3.200,00"`. É como
a Invariante 2 se sustenta: o fato nunca guardou o dinheiro; o valor é lido da origem
(`charges`/`bank_transactions`) e injetado aqui, no momento da leitura — mesma mecânica do
`crm/timeline.py`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from app.core.facts import COM_FORMULARIO_RECEBIDO, CRM_LEAD_CRIADO

SECAO_PENDENTE = "PENDENTE"
SECAO_ACONTECEU = "ACONTECEU"
SECAO_NUMEROS = "NÚMEROS"

# Ausência primeiro: ela pede ação. Número por último: é contexto, não notícia.
_ORDEM_DAS_SECOES = (SECAO_PENDENTE, SECAO_ACONTECEU, SECAO_NUMEROS)

# Pares que descrevem UM acontecimento. `crm.lead.criado` é consequência do formulário; juntos
# viram uma frase. Os dois fatos continuam gravados — a atribuição de marketing e o nascimento
# do contato são informações diferentes, e o V3 vai querer as duas.
_COLAPSOS: dict[tuple[str, str], str] = {
    (COM_FORMULARIO_RECEBIDO, CRM_LEAD_CRIADO): "{a} e entrou no funil",
}

# Dois fatos só descrevem o mesmo acontecimento se forem do mesmo contato e quase simultâneos.
_JANELA_DO_COLAPSO = timedelta(seconds=60)

# Peso maior aparece primeiro.
_PESO_PADRAO = 10
_PESOS: dict[str, int] = {
    "financeiro.pagamento.recebido": 90,
    "operacao.jornada.falhou": 85,
    COM_FORMULARIO_RECEBIDO: 80,
    "comercial.mensagem.recebida": 70,
    "comercial.orcamento.aceito": 70,
    "agenda.evento.cancelado": 60,
}

_LIMITE_AGREGACAO = 3


@dataclass(frozen=True)
class Linha:
    secao: str  # "ACONTECEU" | "PENDENTE" | "NÚMEROS"
    module: str
    texto: str
    # Só ausência preenche. É o que permite ao V2 colar a pergunta de calibração na linha que a
    # motivou. O default `""` não é cosmético: **briefings gravados antes do V2 não têm este
    # campo no payload**, e lê-los sem default estouraria na desserialização.
    kind: str = ""


@dataclass(frozen=True)
class Payload:
    referencia: datetime | None
    desde: datetime | None
    linhas: list[Linha]
    excedente: int
    # `{kind}:{subject_id}` → `dias`, só das ausências que SOBREVIVERAM ao corte. Uma ausência
    # cortada pelo teto não foi dita a ninguém; registrá-la aqui a calaria amanhã por algo que
    # o dono nunca leu. É o insumo da regra do silêncio no briefing seguinte.
    ausencias_ditas: dict[str, int] = field(default_factory=dict)

    def sem_acontecimentos(self) -> bool:
        """"Nada aconteceu" — que NÃO é o mesmo que "não há linhas".

        Ausência e tendência descrevem estado permanente: um tenant recém-criado já nasce com
        pelo menos uma de cada (o topo sem lead, o 🟡 de completude do Epic 8). Se o flag de
        vazio olhasse `linhas`, ele nunca seria verdadeiro e a tela perderia o único caso que
        precisa de tratamento próprio — o dia em que de fato não houve notícia.
        """
        return not any(linha.secao == SECAO_ACONTECEU for linha in self.linhas)


@dataclass(frozen=True)
class _Candidata:
    """Uma linha ainda não ordenada, carregando o que decide a posição dela."""

    secao: str
    module: str
    texto: str
    peso: int
    quando: datetime | None
    # Só ausência preenche: a chave e a intensidade que alimentam a regra do silêncio.
    chave: str | None = None
    dias: int = 0
    # Só ausência preenche. Fica SEPARADO de `chave` de propósito: aquela é composta com o
    # `subject_id`, e fatiá-la na tela acoplaria o front ao formato dela.
    kind: str = ""


def compor(
    *,
    fatos: list[Any],
    ausencias: list[Any],
    tendencias: list[Any],
    valores: dict[tuple[str, str], str],
    teto: int = 12,
    referencia: datetime | None = None,
    desde: datetime | None = None,
) -> Payload:
    """Executa, nesta ordem: colapso → agregação → injeção de valor → ordenação → corte."""
    restantes, colapsadas = _colapsar(fatos)
    candidatas = [
        *(_da_ausencia(a) for a in ausencias),
        *colapsadas,
        *_dos_fatos(restantes, valores),
        *(_da_tendencia(t) for t in tendencias),
    ]

    ordenadas = sorted(candidatas, key=_chave_de_ordem)
    mantidas = ordenadas[:teto]
    return Payload(
        referencia=referencia,
        desde=desde,
        linhas=[
            Linha(secao=c.secao, module=c.module, texto=c.texto, kind=c.kind) for c in mantidas
        ],
        excedente=max(0, len(ordenadas) - len(mantidas)),
        ausencias_ditas={c.chave: c.dias for c in mantidas if c.chave},
    )


def _chave_de_ordem(c: _Candidata) -> tuple[int, int, float]:
    # Seção, depois peso decrescente, depois recência decrescente. Sem `quando` (ausência e
    # tendência descrevem um estado, não um instante) o desempate é só o peso.
    quando = c.quando.timestamp() if c.quando is not None else 0.0
    return (_ORDEM_DAS_SECOES.index(c.secao), -c.peso, -quando)


def _peso(kind: str) -> int:
    return _PESOS.get(kind, _PESO_PADRAO)


def _da_ausencia(a: Any) -> _Candidata:
    return _Candidata(
        secao=SECAO_PENDENTE, module=a.module, texto=a.title,
        peso=_peso(a.kind), quando=None,
        chave=f"{a.kind}:{a.subject_id}", dias=a.dias, kind=a.kind,
    )


def _da_tendencia(t: Any) -> _Candidata:
    return _Candidata(
        secao=SECAO_NUMEROS, module=t.module, texto=t.title,
        peso=_PESO_PADRAO, quando=None,
    )


def _colapsar(fatos: list[Any]) -> tuple[list[Any], list[_Candidata]]:
    """Funde os pares de `_COLAPSOS` que falam do mesmo contato quase ao mesmo tempo."""
    consumidos: set[int] = set()
    saida: list[_Candidata] = []

    for (kind_a, kind_b), molde in _COLAPSOS.items():
        for i, a in enumerate(fatos):
            if i in consumidos or a.kind != kind_a:
                continue
            for j, b in enumerate(fatos):
                if j in consumidos or i == j or b.kind != kind_b:
                    continue
                if a.client_id is None or a.client_id != b.client_id:
                    continue
                if abs(a.occurred_at - b.occurred_at) > _JANELA_DO_COLAPSO:
                    continue
                consumidos.update({i, j})
                saida.append(
                    _Candidata(
                        secao=SECAO_ACONTECEU, module=a.module,
                        texto=molde.format(a=a.title, b=b.title),
                        peso=max(_peso(kind_a), _peso(kind_b)),
                        quando=max(a.occurred_at, b.occurred_at),
                    )
                )
                break

    return [f for i, f in enumerate(fatos) if i not in consumidos], saida


def _dos_fatos(fatos: list[Any], valores: dict[tuple[str, str], str]) -> list[_Candidata]:
    """Agrega repetição e injeta o valor lido da origem.

    ⚠️ O eixo da agregação é a **frase repetida** (`kind` + `title`), não o `kind` sozinho.
    Quarenta "Contato entrou na automação “Boas-vindas”" é uma notícia; cinquenta notas com
    textos diferentes são cinquenta acontecimentos, e fundi-las esconderia o conteúdo de todas
    menos o número. Agregar por `kind` seria a diferença entre resumir e omitir.
    """
    grupos: dict[tuple[str, str], list[Any]] = {}
    for f in fatos:
        grupos.setdefault((f.kind, f.title), []).append(f)

    saida: list[_Candidata] = []
    for (kind, title), membros in grupos.items():
        quando = max(f.occurred_at for f in membros)
        if len(membros) > _LIMITE_AGREGACAO:
            texto = f"{title} ({len(membros)}×)"
        else:
            for f in membros:
                saida.append(
                    _Candidata(
                        secao=SECAO_ACONTECEU, module=f.module,
                        texto=_com_valor(f, valores), peso=_peso(kind),
                        quando=f.occurred_at,
                    )
                )
            continue
        saida.append(
            _Candidata(
                secao=SECAO_ACONTECEU, module=membros[0].module, texto=texto,
                peso=_peso(kind), quando=quando,
            )
        )
    return saida


def _com_valor(fato: Any, valores: dict[tuple[str, str], str]) -> str:
    """O dinheiro entra AQUI, lido da origem — nunca de dentro do fato (Invariante 2)."""
    if not fato.subject_type or not fato.subject_id:
        return fato.title
    valor = valores.get((fato.subject_type, fato.subject_id))
    return f"{fato.title} — {valor}" if valor else fato.title
