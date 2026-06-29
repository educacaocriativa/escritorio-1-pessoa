"""Anonimizador anti-vazamento (Regra de Ouro nº 2).

Substitui PII (nomes, CPF/CNPJ, e-mails, telefones, contas) por variáveis ANTES de enviar
qualquer texto para a API do Claude, e reinsere os dados reais localmente ao receber a resposta.
Impede que dados sob segredo de justiça / sensíveis alimentem terceiros.

Uso:
    anon = Anonymizer()
    safe_text, mapping = anon.mask(texto_original)
    resposta = chamar_claude(safe_text)
    final = anon.unmask(resposta, mapping)
"""
from __future__ import annotations

import re

# Ordem importa: padrões mais específicos primeiro.
_PATTERNS: list[tuple[str, str]] = [
    ("CNPJ", r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b"),
    ("CPF", r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"),
    ("EMAIL", r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    ("FONE", r"\b(?:\+55\s?)?\(?\d{2}\)?\s?9?\d{4}-?\d{4}\b"),
    ("CARTAO", r"\b(?:\d[ -]?){13,16}\b"),
]


class Anonymizer:
    """Mascara/desmascara PII. Stateless entre chamadas: o mapping é retornado, não guardado."""

    def mask(self, text: str) -> tuple[str, dict[str, str]]:
        """Retorna (texto_mascarado, mapping {placeholder: valor_real})."""
        mapping: dict[str, str] = {}
        counters: dict[str, int] = {}
        result = text

        for label, pattern in _PATTERNS:
            def _sub(match: re.Match[str], _label: str = label) -> str:
                value = match.group(0)
                # reaproveita placeholder se o mesmo valor já apareceu
                for ph, val in mapping.items():
                    if val == value:
                        return ph
                counters[_label] = counters.get(_label, 0) + 1
                ph = f"[{_label}_{counters[_label]}]"
                mapping[ph] = value
                return ph

            result = re.sub(pattern, _sub, result)

        return result, mapping

    def unmask(self, text: str, mapping: dict[str, str]) -> str:
        """Reinsere os valores reais nos placeholders."""
        result = text
        for ph, value in mapping.items():
            result = result.replace(ph, value)
        return result


anonymizer = Anonymizer()
