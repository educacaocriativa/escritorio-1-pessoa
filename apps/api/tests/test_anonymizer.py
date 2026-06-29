"""Testes da Regra de Ouro nº 2 — nenhum PII pode escapar para a IA."""
from app.core.anonymizer import Anonymizer

CPF = "123.456.789-09"
EMAIL = "joao.silva@example.com"


def test_mask_removes_pii():
    anon = Anonymizer()
    text = f"O autor João tem CPF {CPF} e e-mail {EMAIL}."
    masked, mapping = anon.mask(text)
    assert CPF not in masked
    assert EMAIL not in masked
    assert "[CPF_1]" in masked
    assert "[EMAIL_1]" in masked
    assert mapping["[CPF_1]"] == CPF
    assert mapping["[EMAIL_1]"] == EMAIL


def test_unmask_is_inverse_of_mask():
    anon = Anonymizer()
    text = f"Contato: {EMAIL}, CPF {CPF}."
    masked, mapping = anon.mask(text)
    restored = anon.unmask(masked, mapping)
    assert restored == text


def test_repeated_value_reuses_placeholder():
    anon = Anonymizer()
    text = f"{CPF} aparece duas vezes: {CPF}."
    masked, mapping = anon.mask(text)
    # mesmo valor => um único placeholder
    assert masked.count("[CPF_1]") == 2
    assert len([k for k in mapping if k.startswith("[CPF")]) == 1


def test_no_pii_means_unchanged():
    anon = Anonymizer()
    text = "Texto sem dados sensíveis."
    masked, mapping = anon.mask(text)
    assert masked == text
    assert mapping == {}
