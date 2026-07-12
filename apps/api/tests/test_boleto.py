"""Story 7.6 — teste unitário DIRETO de core/boleto.py (caminho feliz + caminho infeliz).

Chama `generate_boleto_pdf` diretamente (sem HTTP client, sem Charge/Attachment, sem banco),
diferente da cobertura indireta de test_receivables (test_boleto_charge_generates_pdf_attachment).
Valida o CONTEÚDO do PDF gerado extraindo o texto de volta via pdfplumber (já dependência),
e prova/trava o comportamento fail-safe para dado ausente/malformado (erro explícito, não PDF
silenciosamente vazio/corrompido).
"""
import io
from datetime import date

import pytest

from app.core.boleto import generate_boleto_pdf


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    import pdfplumber

    parts: list[str] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                parts.append(t)
    return "\n".join(parts)


# --- AC1: caminho feliz direto e isolado -----------------------------------------


def test_generate_boleto_pdf_happy_path_contains_expected_fields() -> None:
    pdf_bytes = generate_boleto_pdf(
        payee="Escritório João Silva",
        payer="Maria Souza",
        amount_cents=15050,
        due_date=date(2026, 8, 15),
        code="34191.79001 01043.510047 91020.150008 1 98770000015050",
    )

    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 0
    assert pdf_bytes[:4] == b"%PDF"

    text = _extract_pdf_text(pdf_bytes)
    assert "João Silva" in text
    assert "Maria Souza" in text
    assert "R$ 150,50" in text
    assert "15/08/2026" in text
    # A linha digitável quebra em múltiplas linhas no multi_cell; conferir um trecho estável.
    assert "34191.79001" in text


# --- AC2: caminho infeliz (dado ausente/malformado → erro explícito) --------------


def test_generate_boleto_pdf_missing_amount_cents_raises_explicit_error() -> None:
    # _brl(None) faz None/100 -> TypeError explícito (não devolve PDF vazio silencioso).
    with pytest.raises((TypeError, ValueError)):
        generate_boleto_pdf(
            payee="Escritório",
            payer="Cliente",
            amount_cents=None,  # type: ignore[arg-type]
            due_date=date(2026, 8, 15),
            code="linha-digitavel",
        )


def test_generate_boleto_pdf_missing_due_date_raises_explicit_error() -> None:
    # due_date.strftime(...) em None -> AttributeError explícito.
    with pytest.raises((AttributeError, TypeError)):
        generate_boleto_pdf(
            payee="Escritório",
            payer="Cliente",
            amount_cents=15050,
            due_date=None,  # type: ignore[arg-type]
            code="linha-digitavel",
        )


def test_generate_boleto_pdf_malformed_due_date_raises_explicit_error() -> None:
    # str não tem .strftime -> AttributeError explícito (não coerção silenciosa).
    with pytest.raises((AttributeError, TypeError, ValueError)):
        generate_boleto_pdf(
            payee="Escritório",
            payer="Cliente",
            amount_cents=15050,
            due_date="não é uma data",  # type: ignore[arg-type]
            code="linha-digitavel",
        )
