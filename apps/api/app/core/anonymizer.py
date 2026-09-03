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

import json
import re
from typing import Any

# Ordem importa: padrões mais específicos primeiro.
_PATTERNS: list[tuple[str, str]] = [
    ("CNPJ", r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b"),
    ("CPF", r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"),
    ("EMAIL", r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    ("FONE", r"\b(?:\+55\s?)?\(?\d{2}\)?\s?9?\d{4}-?\d{4}\b"),
    ("CARTAO", r"\b(?:\d[ -]?){13,16}\b"),
]


# Instrução de sistema que faz o `unmask` funcionar. Sem ela o modelo reescreve `[CPF_1]` como
# "o CPF informado" e o valor real não tem mais onde voltar — o dado não vaza, mas a resposta
# chega mutilada ao dono e ninguém entende por quê. Vive aqui, ao lado dos marcadores que
# descreve, para não virar cinco redações diferentes espalhadas pelos chamadores.
INSTRUCAO_PRESERVAR_MARCADORES = (
    " Os trechos entre colchetes (ex.: [CPF_1], [EMAIL_1], [FONE_1]) são dados ocultados por "
    "privacidade: repita-os EXATAMENTE como aparecem, sem traduzir, descrever ou inventar outros."
)


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


class AnonymizationContext:
    """Mapa reversível que vive por um turno completo de IA.

    Diferentemente de :class:`Anonymizer`, o contexto acumula os valores encontrados na pergunta
    e em cada resultado de ferramenta. Assim, o mesmo dado recebe sempre o mesmo marcador e uma
    chamada posterior de ferramenta pode devolver esse marcador para ser resolvido localmente.
    """

    def __init__(self) -> None:
        self.mapping: dict[str, str] = {}
        self._counters: dict[str, int] = {}

    def _placeholder(self, label: str, value: str) -> str:
        for placeholder, real in self.mapping.items():
            if real == value:
                return placeholder
        self._counters[label] = self._counters.get(label, 0) + 1
        placeholder = f"[{label}_{self._counters[label]}]"
        self.mapping[placeholder] = value
        return placeholder

    def mask(self, text: str) -> str:
        result = text
        for label, pattern in _PATTERNS:
            result = re.sub(
                pattern,
                lambda match, current_label=label: self._placeholder(
                    current_label, match.group(0)
                ),
                result,
            )
        return result

    def mask_value(self, value: str, *, label: str) -> str:
        """Oculta um campo estrutural inteiro, inclusive nomes que regex não reconhece."""
        if not value:
            return value
        return self._placeholder(label, value)

    def mask_literals(self, text: str, values: list[str], *, label: str) -> str:
        """Oculta valores conhecidos no texto, sem depender de reconhecimento probabilístico."""
        result = text
        # Nomes completos antes de seus componentes evita produzir dois marcadores adjacentes.
        literals = {item.strip() for item in values if item.strip()}
        for value in sorted(literals, key=len, reverse=True):
            pattern = rf"(?<!\w){re.escape(value)}(?!\w)"
            result = re.sub(
                pattern,
                lambda match: self._placeholder(label, match.group(0)),
                result,
                flags=re.IGNORECASE,
            )
        return result

    def unmask(self, value: Any) -> Any:
        """Resolve marcadores recursivamente em argumentos JSON ou no texto final."""
        if isinstance(value, str):
            result = value
            for placeholder, real in self.mapping.items():
                result = result.replace(placeholder, real)
            return result
        if isinstance(value, list):
            return [self.unmask(item) for item in value]
        if isinstance(value, dict):
            return {key: self.unmask(item) for key, item in value.items()}
        return value

    def mask_tool_result(self, raw_result: str) -> str:
        """Protege JSON de ferramenta antes de ele ser incorporado às mensagens da Claude.

        Campos livres são ocultados por inteiro porque podem conter nomes que não são detectáveis
        com segurança por expressão regular. Números, datas, estados e categorias permanecem
        disponíveis para a análise; o usuário recebe os textos reais após ``unmask``.
        """
        try:
            payload = json.loads(raw_result)
        except (TypeError, json.JSONDecodeError):
            return self.mask(raw_result)

        labels = {
            "id": "ID",
            "event_id": "ID",
            "cliente_id": "ID",
            "nome": "NOME",
            "cliente": "CLIENTE",
            "telefone": "FONE",
            "email": "EMAIL",
            "titulo": "TITULO",
            "descricao": "DESCRICAO",
            "tema": "TEMA",
            "local": "LOCAL",
        }

        def _mask_structured(value: Any) -> Any:
            if isinstance(value, list):
                return [_mask_structured(item) for item in value]
            if isinstance(value, dict):
                protected: dict[str, Any] = {}
                for key, item in value.items():
                    if key in labels and isinstance(item, str):
                        protected[key] = self.mask_value(item, label=labels[key])
                    else:
                        protected[key] = _mask_structured(item)
                return protected
            if isinstance(value, str):
                return self.mask(value)
            return value

        return json.dumps(_mask_structured(payload), ensure_ascii=False, default=str)
