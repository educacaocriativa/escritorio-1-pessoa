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


# ---------------------------------------------------------------------------
# Caminho infeliz do anonimizador (Story 7.2) — testes adversariais.
#
# Provam e travam o invariante fail-safe do `unmask`: como ele faz substituição
# de substring LITERAL (`str.replace`), apenas para as chaves presentes no
# `mapping`, um par mask/unmask inconsistente (placeholder órfão, mapa parcial,
# texto adulterado pela IA) NUNCA reinsere PII errada nem estoura exceção —
# no pior caso deixa um placeholder cru/corrompido visível (aceitável).
# São a rede de segurança da Regra de Ouro nº 2 contra uma refatoração futura
# (ex.: trocar para regex, ou mudar o formato de placeholder) que quebre essa
# garantia silenciosamente.
# ---------------------------------------------------------------------------


def test_unmask_orphan_placeholder_left_untouched():
    """Placeholder no texto de volta mas ausente do mapping (órfão) fica intacto."""
    anon = Anonymizer()
    mapping = {"[CPF_1]": CPF}
    # A IA ecoou/inventou um [EMAIL_1] que não existe no mapping deste request.
    ai_return = "O CPF do autor é [CPF_1]. Contato: [EMAIL_1]."
    result = anon.unmask(ai_return, mapping)

    assert result == f"O CPF do autor é {CPF}. Contato: [EMAIL_1]."
    assert CPF in result  # placeholder mapeado é resolvido
    assert "[EMAIL_1]" in result  # órfão permanece literal, sem virar PII
    assert EMAIL not in result  # nenhuma PII inventada aparece


def test_unmask_partial_map_leaves_unresolved_placeholders():
    """Mapa parcial: só os placeholders com entrada resolvem; os demais ficam crus."""
    anon = Anonymizer()
    email2 = "maria.souza@example.com"
    mapping = {"[CPF_1]": CPF, "[EMAIL_1]": EMAIL}  # cobre 2 de 3
    ai_return = "CPF [CPF_1], e-mail [EMAIL_1], segundo e-mail [EMAIL_2]."
    result = anon.unmask(ai_return, mapping)

    assert CPF in result
    assert EMAIL in result
    assert "[EMAIL_2]" in result  # não mapeado permanece como placeholder cru
    assert email2 not in result  # e nunca é preenchido com um valor errado


def test_unmask_corrupted_placeholder_not_matched():
    """Fragmento corrompido/truncado nunca casa com a chave -> PII real não vaza."""
    anon = Anonymizer()
    mapping = {"[CPF_1]": CPF}

    # (a) colchete de fechamento ausente (truncado)
    truncated = "Documento adulterado: [CPF_1 sem fechar o colchete."
    result_a = anon.unmask(truncated, mapping)
    assert result_a == truncated  # nada foi substituído
    assert "[CPF_1 sem" in result_a  # fragmento corrompido intacto
    assert CPF not in result_a  # valor real do CPF não aparece

    # (b) caractere trocado no rótulo ('l' minúsculo no lugar de '1')
    swapped = "Rótulo trocado pela IA: [CPF_l] deveria ser [CPF_1]."
    result_b = anon.unmask(swapped, mapping)
    assert "[CPF_l]" in result_b  # variação corrompida permanece intacta
    assert result_b.count(CPF) == 1  # só a chave EXATA [CPF_1] resolveu


def test_unmask_no_placeholder_prefix_collision():
    """[CPF_1] não é substring de [CPF_10]: sem substituição por prefixo acidental."""
    anon = Anonymizer()
    cpf_first = "111.111.111-11"  # valor de [CPF_1]
    cpf_tenth = "222.222.222-22"  # valor de [CPF_10]
    mapping = {"[CPF_1]": cpf_first, "[CPF_10]": cpf_tenth}
    ai_return = "Somente a décima ocorrência: [CPF_10]."
    result = anon.unmask(ai_return, mapping)

    assert cpf_tenth in result  # [CPF_10] resolvido para o valor correto
    assert cpf_first not in result  # o valor de [CPF_1] NÃO vaza por prefixo
    assert "[CPF_1]" not in result
    assert "[CPF_10]" not in result


def test_unmask_never_leaks_unmapped_pii():
    """Invariante de segurança (AC2): PII real só aparece onde o placeholder casou exato."""
    anon = Anonymizer()
    mapping = {"[CPF_1]": CPF, "[EMAIL_1]": EMAIL}
    # Texto de retorno adversarial: resolvido + órfão + corrompido + parcial.
    ai_return = (
        "Resolvido [CPF_1] e [EMAIL_1]; "
        "órfão [CARTAO_1]; "
        "corrompido [CPF_1 e [EMAIL_l]; "
        "parcial [CPF_2]."
    )
    result = anon.unmask(ai_return, mapping)

    # cada valor real de PII aparece EXATAMENTE uma vez (só onde casou exato)
    assert result.count(CPF) == 1
    assert result.count(EMAIL) == 1
    # placeholders órfão/corrompido/parcial nunca puxam um valor real
    assert "[CARTAO_1]" in result  # órfão
    assert "[CPF_1 e" in result  # corrompido (sem colchete de fechamento)
    assert "[EMAIL_l]" in result  # corrompido (rótulo trocado)
    assert "[CPF_2]" in result  # parcial (não mapeado)
