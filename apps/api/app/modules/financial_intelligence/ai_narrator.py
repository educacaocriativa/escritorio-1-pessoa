"""Narrador por IA dos sinais de diagnóstico (Story 5.8, AC3, IV2/IV3).

A IA entra SÓ AQUI e SÓ DEPOIS de o motor puro (`engine.py`) já ter calculado os sinais. Ela
apenas REFORMULA os sinais em linguagem natural PT-BR — nunca origina um número (IV1 é garantido
pela pureza do engine; este módulo jamais recebe dados que não estejam já nos sinais).

Fluxo obrigatório (na ordem — Task 3):
  1. Monta um texto-fonte a partir dos `Signal` (título + explicação, incluindo nomes de
     projeto/contraparte que possam aparecer nas explicações).
  2. `safe_text, mapping = anonymizer.mask(texto_fonte)` — Regra de Ouro nº 2: NENHUM texto vai ao
     Claude sem passar pelo anonimizador ANTES (mesmo padrão do módulo Jurídico).
  3. `ai.complete(system=<narrador financeiro PT-BR>, user_message=safe_text)`.
  4. `anonymizer.unmask(resposta, mapping)` — reinsere os valores reais LOCALMENTE, nunca no Claude.

Graceful degradation (AC2/IV3): sem `ANTHROPIC_API_KEY` (ou em qualquer erro da IA), retorna um
FALLBACK por template a partir dos MESMOS sinais — o diagnóstico determinístico continua íntegro,
a narrativa apenas deixa de ser "conversada". Nesse caso NÃO grava rastro de IA (não houve IA).

Regra de Ouro nº 3 (rastro da IA): quando a IA de fato narra, grava
`audit.record(..., is_ai=True)` — a PRIMEIRA ação real de IA de ponta a ponta do projeto a gravar
esse rastro (precedente para as próximas stories de IA).
"""
from __future__ import annotations

from app.config import settings
from app.core import ai, audit
from app.core.anonymizer import anonymizer
from app.modules.financial_intelligence.engine import (
    AMARELO,
    VERDE,
    VERMELHO,
    Signal,
)

_LEVEL_EMOJI: dict[str, str] = {VERDE: "🟢", AMARELO: "🟡", VERMELHO: "🔴"}

_SYSTEM = (
    "Você é o consultor financeiro de uma empresa de 1 pessoa (profissional autônomo brasileiro). "
    "Recebe uma lista de SINAIS de diagnóstico já calculados por um motor determinístico "
    "(🟢 saudável, 🟡 atenção, 🔴 crítico), cada um com uma explicação numérica. "
    "Escreva um resumo curto e direto em português do Brasil (no máximo 2 parágrafos) explicando o "
    "que esses sinais significam na prática e o que priorizar. "
    "REGRAS ABSOLUTAS: use SOMENTE os números e fatos que estão nos sinais — NUNCA invente "
    "valores, percentuais, datas ou nomes que não estejam no texto. Não prometa resultados. "
    "Mantenha os "
    "marcadores/placeholders (ex.: [CPF_1], [CNPJ_1]) EXATAMENTE como aparecem. "
    "Responda apenas com o texto do resumo."
)


def _source_text(signals: list[Signal]) -> str:
    """Texto-fonte enviado à IA: título + explicação de cada sinal, uma linha por sinal. Pode conter
    PII (nome de projeto/contraparte nas explicações) — por isso SEMPRE passa pelo anonimizador."""
    return "\n".join(
        f"{_LEVEL_EMOJI.get(s.level, '')} {s.title}: {s.explanation}".strip() for s in signals
    )


def fallback_narrative(signals: list[Signal]) -> str:
    """Narrativa por TEMPLATE (sem IA): lista os sinais em PT-BR. Usada sem chave de IA ou em erro.
    Continua 100% fiel aos sinais determinísticos (nenhum número novo)."""
    if not signals:
        return "Nenhum sinal de alerta no período — o diagnóstico não encontrou riscos relevantes."
    linhas = [
        f"{_LEVEL_EMOJI.get(s.level, '')} {s.title}: {s.explanation}".strip() for s in signals
    ]
    return "Resumo do diagnóstico (sinais determinísticos):\n" + "\n".join(linhas)


def narrate_with_source(
    signals: list[Signal],
    *,
    db=None,
    tenant_id: str | None = None,
    actor: str = "ai",
    target: str = "",
) -> tuple[str, str]:
    """Como `narrate_signals`, mas devolve `(texto, origem)` onde origem ∈ {"ai", "template"} —
    usado pela rota para informar a UI qual caminho gerou a narrativa. Nunca levanta:
    - sem sinais / sem `ANTHROPIC_API_KEY` / erro da IA → (template, "template"), SEM rastro;
    - com IA → (texto anonimizado→narrado→desanonimizado, "ai") + `audit.record(is_ai=True)`
      + commit quando `db`+`tenant_id` vierem (Regra de Ouro nº 3).
    """
    if not signals:
        return fallback_narrative(signals), "template"

    # Graceful degradation: sem chave, não há ação de IA — não grava rastro (Task 3/IV3).
    if not settings.anthropic_api_key:
        return fallback_narrative(signals), "template"

    source = _source_text(signals)
    # Regra de Ouro nº 2: anonimiza ANTES de chamar a IA; desanonimiza LOCALMENTE na volta.
    safe_text, mapping = anonymizer.mask(source)
    try:
        result = ai.complete(system=_SYSTEM, user_message=safe_text, max_tokens=800)
    except Exception:  # noqa: BLE001 — IA nunca pode derrubar o diagnóstico (IV3): cai no template.
        return fallback_narrative(signals), "template"

    final = anonymizer.unmask(result.text.strip(), mapping)

    # Regra de Ouro nº 3: houve ação REAL de IA → grava o rastro "Ação executada pela IA".
    if db is not None and tenant_id is not None:
        audit.record(
            db, tenant_id=tenant_id, actor=actor,
            action="financial_diagnostics.narrated", target=target, is_ai=True,
        )
        db.commit()

    return final, "ai"


def narrate_signals(
    signals: list[Signal],
    *,
    db=None,
    tenant_id: str | None = None,
    actor: str = "ai",
    target: str = "",
) -> str:
    """API pública (assinatura da Story 5.8, Task 3): narra os sinais e retorna só o texto.
    Delega a `narrate_with_source`. `db`/`tenant_id` opcionais para narração pura (teste) sem
    auditoria.
    """
    text, _ = narrate_with_source(
        signals, db=db, tenant_id=tenant_id, actor=actor, target=target
    )
    return text
