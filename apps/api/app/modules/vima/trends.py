"""Adaptador dos sinais do motor financeiro para o briefing.

`financial_intelligence/engine.py` já produz `Signal` com 🟢🟡🔴 e explicação numérica. Este
módulo **lê** os sinais; não recalcula nada.

⚠️ O `engine.py` é PURO — sem I/O, sem relógio, com gates AST provando. Este adaptador faz a
coleta de dados FORA dele (via `diagnostics.compute_signals`, que é o ponto único de
orquestração) e recebe o resultado pronto. Empurrar I/O para dentro do motor quebraria os gates
e a garantia que eles protegem.

A janela é o **mês de competência corrente** — a mesma que a tela de Diagnóstico usa, e a mesma
da DRE. O briefing é diário, mas tendência não é: um sinal calculado sobre as últimas 24h
oscilaria com qualquer despesa isolada e viraria ruído. `hoje` entra por parâmetro; nada aqui
lê o relógio.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.core.tenancy import CurrentUser
from app.modules.financial_intelligence import diagnostics
from app.modules.financial_intelligence.engine import AMARELO, VERDE, VERMELHO
from app.modules.vima.permissions import pode_ver

_NIVEL = {VERDE: "verde", AMARELO: "amarelo", VERMELHO: "vermelho"}


@dataclass(frozen=True)
class Tendencia:
    module: str
    nivel: str
    title: str


def coletar(db: Session, *, user: CurrentUser, hoje: date) -> list[Tendencia]:
    if not pode_ver(user, "financeiro"):
        return []
    sinais = diagnostics.compute_signals(
        db, start=hoje.replace(day=1), end=hoje, today=hoje
    )
    return [
        Tendencia(
            module="financeiro",
            nivel=_NIVEL.get(s.level, "verde"),
            title=f"{s.title} — {s.explanation}",
        )
        for s in sinais
    ]
