"""Testes do narrador por IA (Story 5.8, Task 5 — AC3, IV2/IV3) + prova de sinais idênticos.

Cobre os DOIS testes mais críticos do épico:
  #1 (IV1/AC2) — os SINAIS são idênticos COM e SEM `ANTHROPIC_API_KEY`: a IA só reformula texto,
     nunca origina número (teste de endpoint end-to-end comparando as duas respostas).
  #2 (IV2/Regra de Ouro nº 2) — o texto enviado à IA PASSOU pelo anonimizador: o payload capturado
     no mock de `core.ai.complete` contém placeholders ([CNPJ_1]/[CPF_1]/[EMAIL_1]) e NÃO o dado
     cru; a resposta é desanonimizada localmente na volta.
Mais graceful degradation sem chave (IV3, sem rastro de IA) e o rastro `is_ai=True` (Regra de Ouro
nº 3). Nunca chama a API real da Anthropic (monkeypatch de `core.ai.complete`).
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import AuditEntry
from app.modules.financial_intelligence import ai_narrator
from app.modules.financial_intelligence.engine import AMARELO, VERMELHO, Signal


@dataclass
class _FakeAIResult:
    text: str
    input_tokens: int = 1
    output_tokens: int = 1


def _signals() -> list[Signal]:
    return [
        Signal(VERMELHO, "Runway crítico", "Runway < 60 dias", "projecao"),
        Signal(AMARELO, "Runway curto", "Runway < 120 dias", "projecao"),
    ]


# ── IV3: graceful degradation sem chave (sem rastro de IA) ──────────────────────────────────
def test_no_key_returns_template_without_audit(db: Session, monkeypatch) -> None:
    monkeypatch.setattr(ai_narrator.settings, "anthropic_api_key", "", raising=False)
    text, source = ai_narrator.narrate_with_source(
        _signals(), db=db, tenant_id="t1", actor="u1", target="p"
    )
    assert source == "template"
    assert "Runway < 60 dias" in text  # narrativa fiel aos sinais (nenhum número novo)
    # Nenhuma ação de IA aconteceu → nenhum rastro de IA gravado (Task 3).
    assert db.scalars(select(AuditEntry)).all() == []


def test_empty_signals_neutral_template(db: Session, monkeypatch) -> None:
    monkeypatch.setattr(ai_narrator.settings, "anthropic_api_key", "sk-ant-x", raising=False)
    text, source = ai_narrator.narrate_with_source([], db=db, tenant_id="t1")
    assert source == "template" and "Nenhum sinal" in text


def test_ai_error_falls_back_to_template(db: Session, monkeypatch) -> None:
    monkeypatch.setattr(ai_narrator.settings, "anthropic_api_key", "sk-ant-x", raising=False)

    def _boom(**_kwargs):
        raise RuntimeError("Anthropic indisponível")

    monkeypatch.setattr(ai_narrator.ai, "complete", _boom)
    text, source = ai_narrator.narrate_with_source(
        _signals(), db=db, tenant_id="t1", actor="u1", target="p"
    )
    assert source == "template"  # IA nunca derruba o diagnóstico (IV3)
    assert db.scalars(select(AuditEntry)).all() == []  # erro não gera rastro de IA


# ── IV2 (teste CRÍTICO #2): payload anonimizado ANTES da IA ─────────────────────────────────
def test_payload_sent_to_ai_is_anonymized_and_unmasked_on_return(db: Session, monkeypatch) -> None:
    monkeypatch.setattr(ai_narrator.settings, "anthropic_api_key", "sk-ant-x", raising=False)
    captured: dict[str, str] = {}

    def _fake_complete(*, system: str, user_message: str, max_tokens: int = 800, model=None):
        captured["system"] = system
        captured["user_message"] = user_message
        # A IA "responde" ecoando o texto seguro (com placeholders) — força o teste de unmask.
        return _FakeAIResult(text=user_message)

    monkeypatch.setattr(ai_narrator.ai, "complete", _fake_complete)

    # Sinal cuja explicação carrega PII estrutural (CNPJ + CPF + e-mail) — como poderia acontecer
    # num título de contrato/contraparte que vaza para a explicação numérica.
    cnpj, cpf, email = "12.345.678/0001-90", "123.456.789-09", "ana@exemplo.com"
    sig = Signal(
        VERMELHO, "Margem de contribuição em queda forte",
        f"Projeto Cliente CNPJ {cnpj}, CPF {cpf}, contato {email}: margem 40%→10% em 1 mês",
        "lucratividade",
    )

    final, source = ai_narrator.narrate_with_source(
        [sig], db=db, tenant_id="t1", actor="u1", target="p"
    )
    assert source == "ai"

    payload = captured["user_message"]
    # O dado CRU NÃO pode ter ido ao Claude…
    assert cnpj not in payload
    assert cpf not in payload
    assert email not in payload
    # …e no lugar dele foram os placeholders do anonimizador.
    assert "[CNPJ_1]" in payload
    assert "[CPF_1]" in payload
    assert "[EMAIL_1]" in payload
    # Desanonimização LOCAL na volta: os valores reais voltam só do lado de cá.
    assert cnpj in final
    assert cpf in final
    assert email in final


# ── Regra de Ouro nº 3: rastro is_ai=True quando a IA de fato narra ─────────────────────────
def test_successful_ai_narration_records_ai_audit(db: Session, monkeypatch) -> None:
    monkeypatch.setattr(ai_narrator.settings, "anthropic_api_key", "sk-ant-x", raising=False)
    monkeypatch.setattr(
        ai_narrator.ai, "complete",
        lambda **_k: _FakeAIResult(text="Resumo gerado pela IA."),
    )
    ai_narrator.narrate_with_source(
        _signals(), db=db, tenant_id="t1", actor="u1", target="2026-07-01..2026-07-31"
    )
    entries = db.scalars(select(AuditEntry)).all()
    assert len(entries) == 1
    e = entries[0]
    assert e.is_ai is True
    assert e.action == "financial_diagnostics.narrated"
    assert e.actor == "u1"


# ── narrate_signals (assinatura pública da Story) delega e retorna só o texto ────────────────
def test_narrate_signals_public_api_returns_text(db: Session, monkeypatch) -> None:
    monkeypatch.setattr(ai_narrator.settings, "anthropic_api_key", "", raising=False)
    text = ai_narrator.narrate_signals(_signals())
    assert isinstance(text, str) and "Runway < 60 dias" in text


# ── IV1 (teste CRÍTICO #1): sinais IDÊNTICOS com e sem IA (end-to-end no endpoint) ───────────
_REGISTER = {
    "legal_name": "Diagnóstico ME",
    "document": "22333444000181",
    "slug": "diag",
    "email": "diag@example.com",
    "name": "Dora",
    "password": "uma-senha-bem-grande",
}
_START, _END = "2026-07-01", "2026-07-31"


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=_REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_signals_identical_with_and_without_ai(
    client: TestClient, headers, db: Session, monkeypatch
) -> None:
    """O CORAÇÃO da Story 5.8: os sinais determinísticos são idênticos byte-a-byte com e sem IA —
    a IA só troca o texto da NARRATIVA, jamais um número/sinal."""
    # Semeia uma aplicação com principal > 0 e sem rendimento → sinal 🟡 determinístico e estável.
    r = client.post(
        "/investments",
        json={"name": "CDB Reserva", "principal_cents": 100000, "opened_at": "2026-06-01"},
        headers=headers,
    )
    assert r.status_code == 201, r.text

    # Caso A — SEM chave (default no teste): narrativa por template.
    monkeypatch.setattr(ai_narrator.settings, "anthropic_api_key", "", raising=False)
    url = f"/financial-intelligence/diagnostics?start={_START}&end={_END}"
    ra = client.get(url, headers=headers)
    assert ra.status_code == 200, ra.text
    a = ra.json()
    assert a["narrative_source"] == "template"

    # Caso B — COM chave + IA mockada: narrativa pela IA (rastro is_ai=True).
    monkeypatch.setattr(ai_narrator.settings, "anthropic_api_key", "sk-ant-x", raising=False)
    monkeypatch.setattr(
        ai_narrator.ai, "complete",
        lambda **_k: _FakeAIResult(text="Atenção ao rendimento da reserva."),
    )
    rb = client.get(url, headers=headers)
    assert rb.status_code == 200, rb.text
    b = rb.json()
    assert b["narrative_source"] == "ai"

    # PROVA: os sinais são IDÊNTICOS; só a narrativa mudou.
    assert a["signals"] == b["signals"]
    assert len(a["signals"]) >= 1
    assert a["narrative"] != b["narrative"]

    # E a narração por IA gravou o rastro (Regra de Ouro nº 3).
    entries = db.scalars(
        select(AuditEntry).where(AuditEntry.action == "financial_diagnostics.narrated")
    ).all()
    assert len(entries) == 1 and entries[0].is_ai is True
