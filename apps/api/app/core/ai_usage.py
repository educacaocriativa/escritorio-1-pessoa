"""O ledger de uso de IA — quanto se gastou, por quem, em qual tarefa.

Antes disto o e1p já gastava IA em produção e não sabia quanto: seis módulos chamavam
`ai.complete` e cinco descartavam os tokens que a Anthropic devolvia. Só o `juridico` guardava,
e na própria linha do documento (`LegalDocument.input_tokens`), o que não agrega por tenant nem
por período. A descoberta do custo vinha pela fatura.

**Isto é medição, não cobrança.** Não há teto de gasto, tela ou preço aqui — medir é
reversível, decisão de preço não é, e ela ainda não foi tomada.

⚠️ **A regra de gravação é o OPOSTO da de `core/facts.py`, e é o ponto mais fácil de errar
lendo por analogia.** `facts.record` grava na mesma transação e falha junto de propósito: um
fato que existe sem o negócio é pior que nenhum fato. Aqui não — quando o ledger vai gravar,
a chamada à Anthropic **já aconteceu e já custou dinheiro**. Derrubar a transação por causa do
registro perderia o documento jurídico que o usuário esperou 40 segundos para receber, e o
dinheiro teria sido gasto do mesmo jeito. Então: best-effort, `logger.exception` em falha,
nunca derrubando quem chamou.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, String, func
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.db.base import Base, TenantMixin, TimestampMixin, _uuid

logger = logging.getLogger("e1p.ai")


class AIUsage(Base, TenantMixin, TimestampMixin):
    """Uma chamada à Anthropic, com o que ela custou em tokens."""

    __tablename__ = "ai_usage"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # NULL quando não há usuário: worker, cron, webhook de gateway. É por isso que a coluna é
    # nullable — não porque o campo seja opcional para quem tem usuário.
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    # `vima.briefing`, `juridico.documento`, `receivables.cobranca`… É o eixo de agregação que
    # responde "qual funcionalidade custa caro", e o mesmo eixo que escolhe o modelo em
    # `core/ai.py`. Um só vocabulário para as duas perguntas.
    task: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    # O modelo que REALMENTE rodou, não o configurado. Divergem quando o roteamento muda, e é a
    # linha gravada que precisa valer para reconstruir a conta.
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    input_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    # Cache tem preço próprio (leitura ~0,1× do input; escrita ~1,25×), então somar tudo em
    # `input_tokens` produziria uma conta errada — para mais ou para menos, dependendo do mix.
    cache_read_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    cache_creation_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    # Default do lado do PYTHON: no Postgres `now()` é o instante da TRANSAÇÃO, e duas chamadas
    # de IA no mesmo commit sairiam com timestamp idêntico. Mesma lição de `Fact.created_at`.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )


def record(
    db: Session,
    *,
    tenant_id: str,
    task: str,
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
    user_id: str | None = None,
) -> AIUsage | None:
    """Registra uma chamada de IA. **Nunca levanta** — devolve `None` se não conseguiu gravar.

    O `begin_nested()` é o que torna a promessa acima verdadeira em vez de aspiracional. Um
    `db.add()` seguido de `flush()` que falha deixa a Session em estado de rollback pendente:
    o `except` engoliria a exceção e o **commit do chamador** morreria depois, longe daqui,
    com uma mensagem que não menciona IA nenhuma. O SAVEPOINT delimita a falha — desfaz só o
    que esta função tentou escrever e devolve a transação de fora intacta.

    Preço assumido: a linha vive na transação do chamador, então um rollback do NEGÓCIO leva o
    registro junto e o gasto some da conta. É raro comparado a "o insert do ledger falhou", e a
    alternativa (conexão própria, commit independente) paga uma conexão a mais em toda chamada
    de IA para cobrir o caso raro.
    """
    try:
        with db.begin_nested():
            uso = AIUsage(
                tenant_id=tenant_id,
                user_id=user_id,
                task=task,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=cache_read_tokens,
                cache_creation_tokens=cache_creation_tokens,
            )
            db.add(uso)
            db.flush()
        return uso
    except Exception:  # noqa: BLE001 — a contabilidade nunca derruba quem já pagou pela chamada.
        logger.exception(
            "Falha ao registrar uso de IA (task=%s, model=%s, tenant=%s) — "
            "a chamada à Anthropic já aconteceu e já custou; seguindo sem o registro.",
            task, model, tenant_id,
        )
        return None
