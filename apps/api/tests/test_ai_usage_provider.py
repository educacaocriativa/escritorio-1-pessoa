"""`ai_usage` passa a distinguir PROVEDOR (Anthropic vs. Groq) — a fatia de voz da Vima introduz
a Groq como segundo provedor de IA do repositório. `provider` tem default 'anthropic' para não
exigir mudança nos dezenas de call sites existentes; só quem grava transcrição passa 'groq'
explícito, junto de `audio_seconds` (a "moeda" da Groq, que cobra por segundo, não por token)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.core import ai_usage
from app.core.ai_usage import AIUsage

TENANT = "t-provider"


def test_record_sem_provider_grava_anthropic_e_audio_seconds_nulo(db: Session):
    ai_usage.record(db, tenant_id=TENANT, task="vima.briefing", model="claude-haiku-4-5")
    db.commit()

    linha = db.query(AIUsage).one()
    assert linha.provider == "anthropic"
    assert linha.audio_seconds is None


def test_record_com_provider_groq_grava_audio_seconds(db: Session):
    ai_usage.record(
        db, tenant_id=TENANT, task="vima.transcricao", model="whisper-large-v3",
        provider="groq", audio_seconds=4.2,
    )
    db.commit()

    linha = db.query(AIUsage).one()
    assert linha.provider == "groq"
    assert linha.audio_seconds == 4.2
    assert linha.input_tokens == 0
    assert linha.output_tokens == 0


def test_uma_linha_anthropic_e_uma_groq_convivem_sem_se_confundir(db: Session):
    ai_usage.record(db, tenant_id=TENANT, task="vima.pergunta", model="claude-sonnet-5")
    ai_usage.record(
        db, tenant_id=TENANT, task="vima.transcricao", model="whisper-large-v3",
        provider="groq", audio_seconds=1.0,
    )
    db.commit()

    linhas = {linha.provider: linha for linha in db.query(AIUsage).all()}
    assert linhas["anthropic"].audio_seconds is None
    assert linhas["groq"].audio_seconds == 1.0
