"""Normalização de telefone brasileiro (chave de deduplicação de contato)."""
import pytest

from app.core.phone import normalize_br


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        # celular moderno (9 dígitos), em todas as formas que um formulário produz
        ("(11) 99999-8888", "5511999998888"),
        ("11999998888", "5511999998888"),
        ("5511999998888", "5511999998888"),
        ("+55 (11) 99999-8888", "5511999998888"),
        # celular no formato pré-2016 (8 dígitos): ganha o 9 e casa com o moderno
        ("(11) 9999-8888", "5511999998888"),
        # fixo (8 dígitos começando em 2-5): NÃO ganha o 9
        ("(11) 3333-4444", "551133334444"),
        ("1133334444", "551133334444"),
        # outros DDDs
        ("(61) 98888-7777", "5561988887777"),
        # entradas que não normalizam
        ("", None),
        (None, None),
        ("99998888", None),          # sem DDD
        ("011999998888", None),      # DDD com zero à esquerda
        ("123", None),
    ],
)
def test_normalize_br(entrada, esperado):
    assert normalize_br(entrada) == esperado


def test_fixo_e_celular_com_mesmos_8_digitos_nao_colidem():
    """O caso que justifica a regra do 9º dígito.

    A alternativa óbvia — "compara os últimos 8 dígitos" — casaria estes dois números,
    e duas pessoas diferentes virariam um card só.
    """
    fixo = normalize_br("(11) 3333-4444")
    celular = normalize_br("(11) 93333-4444")
    assert fixo is not None
    assert celular is not None
    assert fixo != celular


def test_resultado_cabe_na_coluna():
    """`clients.phone_key` é String(16). O maior resultado possível tem 13 caracteres."""
    resultado = normalize_br("+55 (11) 99999-8888")
    assert resultado is not None
    assert len(resultado) <= 16
