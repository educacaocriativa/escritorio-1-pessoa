"""Testes do validador central de CPF/CNPJ (app/core/validators.py)."""
import pytest

from app.core.validators import (
    normalize_document,
    validate_cnpj,
    validate_cpf,
    validate_document,
)

# CPF/CNPJ com dígito verificador REAL (conferidos pelo próprio algoritmo).
VALID_CPF = "52998224725"
VALID_CNPJ = "11222333000181"


def test_normalize_strips_punctuation():
    assert normalize_document("529.982.247-25") == "52998224725"
    assert normalize_document("11.222.333/0001-81") == "11222333000181"
    assert normalize_document("") == ""
    assert normalize_document("abc") == ""


def test_valid_cpf():
    assert validate_cpf(VALID_CPF) is True


def test_cpf_all_same_digits_is_invalid():
    for d in ("00000000000", "11111111111", "99999999999"):
        assert validate_cpf(d) is False


def test_cpf_wrong_check_digit_is_invalid():
    # último dígito trocado -> DV inválido
    assert validate_cpf("52998224724") is False


def test_cpf_wrong_length_is_invalid():
    assert validate_cpf("5299822472") is False   # 10 dígitos
    assert validate_cpf("529982247250") is False  # 12 dígitos


def test_valid_cnpj():
    assert validate_cnpj(VALID_CNPJ) is True


def test_cnpj_wrong_check_digit_is_invalid():
    assert validate_cnpj("11222333000180") is False


def test_cnpj_all_same_digits_is_invalid():
    assert validate_cnpj("00000000000000") is False


def test_validate_document_returns_normalized_digits():
    # aceita já formatado e devolve só-dígitos
    assert validate_document("529.982.247-25") == VALID_CPF
    assert validate_document("11.222.333/0001-81") == VALID_CNPJ
    # aceita já só-dígitos
    assert validate_document(VALID_CPF) == VALID_CPF
    assert validate_document(VALID_CNPJ) == VALID_CNPJ


def test_validate_document_rejects_invalid_cpf():
    with pytest.raises(ValueError, match="CPF inválido"):
        validate_document("52998224724")


def test_validate_document_rejects_invalid_cnpj():
    with pytest.raises(ValueError, match="CNPJ inválido"):
        validate_document("11222333000180")


def test_validate_document_rejects_wrong_length():
    with pytest.raises(ValueError, match="11 \\(CPF\\) ou 14 \\(CNPJ\\)"):
        validate_document("123456789")  # 9 dígitos
    with pytest.raises(ValueError, match="11 \\(CPF\\) ou 14 \\(CNPJ\\)"):
        validate_document("")  # vazio


def test_validate_document_rejects_repeated_sequence():
    with pytest.raises(ValueError, match="CPF inválido"):
        validate_document("00000000000")
