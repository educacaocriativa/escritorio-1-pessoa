"""A única porta de leitura do DNA.

Três funções, e nada mais. Nenhum outro módulo lê `dna_answers` direto — é o que mantém a
classe Retrato honestamente SEM consumidor até o V4, em vez de ela vazar por um `select`
esperto em algum lugar, que é como um contrato de arquitetura morre na prática.

⚠️ **Módulo PURO:** não lê relógio. `recalibrado_apos` recebe a data de comparação por
parâmetro.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.dna import catalog
from app.modules.dna.models import DnaAnswer
from app.modules.vima.absences import LIMIARES_PADRAO

_CALIBRACAO_POR_KEY = {
    p.key: p for p in catalog.PERGUNTAS if p.classe == catalog.CALIBRACAO
}


def limiares(db: Session) -> dict[str, int | None]:
    """Só as respostas de Calibração, prontas para `absences.coletar(..., limiares=...)`.

    Devolve **só o que foi respondido**, nunca os defaults: quem mescla é `coletar`, com
    `{**LIMIARES_PADRAO, **override}`. Uma segunda fonte de default divergiria da primeira no
    dia em que alguém mudasse um número em só um dos lugares.
    """
    fora: dict[str, int | None] = {}
    for linha in db.scalars(select(DnaAnswer)).all():
        pergunta = _CALIBRACAO_POR_KEY.get(linha.question_key)
        if pergunta is None or pergunta.consome not in LIMIARES_PADRAO:
            continue
        # A resposta precisa continuar sendo uma das opções. Trocar o `valor` de uma opção
        # depois de alguém responder deixa a linha órfã — e uma resposta órfã tem que cair no
        # default, não derrubar o briefing do dia.
        if linha.value not in {o.valor for o in pergunta.opcoes}:
            continue
        fora[pergunta.consome] = linha.value
    return fora


def retrato(db: Session) -> dict[str, Any]:
    """O dossiê. **Sem consumidor no V2** — existe para que o V4 encontre a porta pronta."""
    return {
        linha.question_key: linha.value
        for linha in db.scalars(select(DnaAnswer)).all()
        if linha.value is not None and linha.question_key not in _CALIBRACAO_POR_KEY
    }


def recalibrado_apos(db: Session, quando: date) -> bool:
    """Houve resposta de CALIBRAÇÃO depois desta data?

    É o gatilho da limpeza do silêncio em `vima/service._ja_reportadas`. Só Calibração conta:
    responder Retrato não muda comportamento nenhum, e limpar o silêncio por causa disso faria
    o briefing repetir pendências sem motivo.

    ⚠️ **A comparação é `>=`, não `>`, e o estrito quebraria o recurso inteiro.** O caso normal
    é o dono recalibrar HOJE, pelo gancho colado à ausência do briefing de hoje — cujo
    `reference_date` também é hoje. Com `>`, a limpeza nunca aconteceria no dia seguinte, que é
    justamente quando ela precisa acontecer: o briefing de amanhã olha o de hoje como anterior.

    O custo do `>=` é repetir uma pendência para quem respondeu ANTES de o briefing do dia sair.
    É o erro barato: uma ausência repetida incomoda, uma calibração que não produz efeito visível
    ensina o dono a não mexer mais em nada.
    """
    for linha in db.scalars(select(DnaAnswer)).all():
        if linha.question_key in _CALIBRACAO_POR_KEY and linha.answered_at.date() >= quando:
            return True
    return False
