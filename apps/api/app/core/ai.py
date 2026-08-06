"""Camada única de acesso à IA (Claude).

REGRA: todo texto que entra aqui DEVE já estar anonimizado (ver anonymizer.py).
Esta camada não conhece dados reais — ela só fala com a Anthropic e devolve tokens + texto.

Duas responsabilidades além de chamar a API, e as duas existem porque o ponto único de
passagem é o único lugar onde elas são *garantidas*:

1. **Contabilidade.** `db` e `tenant_id` são OBRIGATÓRIOS. Não é rigor decorativo: é a mesma
   disciplina de `payables.is_overdue`, que exige `today` como parâmetro justamente para que
   ninguém esqueça. Com eles obrigatórios, é impossível chamar a IA sem contabilizar — o
   esquecimento vira `TypeError` no import, não uma linha faltando na conta seis meses depois.
2. **Roteamento por tarefa.** O modelo sai de `MODELO_POR_TAREFA`, não de uma configuração
   global. Narrar um briefing já calculado e redigir peça jurídica são trabalhos diferentes e
   não deviam custar o mesmo.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.core import ai_usage

_client: Any | None = None

# ── Roteamento de modelo por tarefa ────────────────────────────────────────────────────────
#
# Preços (USD por milhão de tokens, entrada/saída) no momento desta escolha:
#   claude-haiku-4-5  →  $1 / $5
#   claude-sonnet-5   →  $3 / $15
#   claude-opus-5     →  $5 / $25
#
# O critério é o custo do ERRO, não o tamanho do texto. Onde a IA só reescreve um payload que
# um motor determinístico já calculou, ela não origina número nenhum e o modelo mais barato
# basta. Onde ela redige — proposta, criativo, peça — a qualidade do texto É o produto. E onde
# alucinar tem consequência jurídica, o modelo mais capaz é o único aceitável.
#
# ⚠️ `claude-opus-5` custa exatamente o mesmo que o `claude-opus-4-8` que estava configurado
# globalmente ($5/$25): trocar é ganho de capacidade sem centavo a mais.
MODELO_POR_TAREFA: dict[str, str] = {
    # Só narram o que já foi calculado — não originam número.
    "vima.briefing": "claude-haiku-4-5",
    "financeiro.diagnostico": "claude-haiku-4-5",
    "receivables.cobranca": "claude-haiku-4-5",
    # Redação: o texto é o produto.
    "quotes.escopo": "claude-sonnet-5",
    "funnels.compose": "claude-sonnet-5",
    "marketing.carrossel": "claude-sonnet-5",
    # Anti-alucinação é crítico e o dado é sensível (segredo de justiça).
    "juridico.documento": "claude-opus-5",
}

# Tarefa desconhecida cai aqui em vez de estourar. O default é o modelo mais CAPAZ, não o mais
# barato, por assimetria de custo: uma tarefa nova roteada para Haiku por engano degrada em
# silêncio (texto pior, ninguém percebe), enquanto roteada para Opus só custa mais — e o
# excesso aparece no ledger, que é exatamente o instrumento que este PR instala.
MODELO_PADRAO = "claude-opus-5"


def modelo_da_tarefa(task: str) -> str:
    """Qual modelo roda esta tarefa. Tarefa desconhecida → `MODELO_PADRAO`."""
    return MODELO_POR_TAREFA.get(task, MODELO_PADRAO)


def _get_client() -> Any:
    # Import lazy: só carrega o SDK quando a IA é de fato usada (mantém o boot/testes leves).
    global _client
    if _client is None:
        from anthropic import Anthropic

        _client = Anthropic(api_key=settings.anthropic_api_key)
    return _client


@dataclass
class AIResult:
    text: str
    input_tokens: int
    output_tokens: int
    # Cache tem preço próprio e a Anthropic os devolve separados; achatá-los em `input_tokens`
    # produziria uma conta errada. Default 0 para não quebrar quem constrói o resultado à mão
    # (os testes dos narradores fazem isso).
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0


def complete(
    *,
    db: Session,
    tenant_id: str,
    task: str,
    system: str,
    user_message: str,
    max_tokens: int = 4096,
    model: str | None = None,
    user_id: str | None = None,
) -> AIResult:
    """Chamada simples de completude. `user_message` deve estar anonimizado.

    `db`, `tenant_id` e `task` são obrigatórios — ver o item 1 do docstring do módulo. `model`
    continua aceito para sobrepor o roteamento em um caso específico, mas o normal é deixar a
    `task` decidir.

    Tudo é keyword-only, `db` inclusive — diferente de `facts.record(db, *, ...)` e
    `audit.record(db, *, ...)`, que tomam a sessão posicionalmente. A divergência é deliberada:
    esta função é substituída por mock em vários testes de narrador (`lambda **kw`), e um
    parâmetro posicional os quebraria todos sem que nenhum deles tenha relação com contabilidade
    de IA. Obrigatório e keyword-only são independentes — sem default, esquecer ainda é
    `TypeError`.

    O registro no ledger acontece DEPOIS da resposta e é best-effort: se ele falhar, esta
    função devolve o resultado do mesmo jeito (ver `ai_usage.record`).
    """
    modelo = model or modelo_da_tarefa(task)
    resp = _get_client().messages.create(
        model=modelo,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user_message}],
    )
    resultado = AIResult(
        text=resp.content[0].text,
        input_tokens=resp.usage.input_tokens,
        output_tokens=resp.usage.output_tokens,
        # `getattr` porque nem toda resposta traz os campos de cache (e os mocks dos testes de
        # narrador, que constroem um objeto de usage mínimo, nunca trazem).
        cache_read_tokens=getattr(resp.usage, "cache_read_input_tokens", 0) or 0,
        cache_creation_tokens=getattr(resp.usage, "cache_creation_input_tokens", 0) or 0,
    )

    ai_usage.record(
        db,
        tenant_id=tenant_id,
        task=task,
        model=modelo,
        input_tokens=resultado.input_tokens,
        output_tokens=resultado.output_tokens,
        cache_read_tokens=resultado.cache_read_tokens,
        cache_creation_tokens=resultado.cache_creation_tokens,
        user_id=user_id,
    )
    return resultado
