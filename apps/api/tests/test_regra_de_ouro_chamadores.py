"""O que cada chamador de IA REALMENTE manda para a Anthropic.

`test_regra_de_ouro_gate.py` prova a forma: existe um `mask`, e o que vai em `user_message` saiu
dele. Isso não é o mesmo que provar o efeito — um `mask` pode ser chamado sobre o texto errado, ou
o `unmask` pode ficar para trás e o dono receber `[CPF_1]` na tela. Aqui a prova é comportamental,
uma por chamador, na forma que `test_financial_intelligence_narrator.py` estabeleceu: mocka-se
`ai.complete`, captura-se o `user_message`, e a IA "responde" ecoando o que recebeu.

O eco é o detalhe que faz o teste valer: se o chamador esquecer o `unmask`, o marcador chega
íntegro ao texto final e a asserção de volta reprova.

As funções cobertas mandavam texto livre do dono sem nenhum tratamento até este PR: `quotes`
(o `brief`), `funnels` (o `prompt`), `marketing` (o `topic`) e as DUAS de `receivables` (a
descrição da cobrança).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date

import pytest
from sqlalchemy.orm import Session

from app.core import ai
from app.modules.funnels import service as funnels_service
from app.modules.marketing import service as marketing_service
from app.modules.quotes import service as quotes_service
from app.modules.receivables import service as receivables_service

CPF = "123.456.789-09"
EMAIL = "ana.souza@exemplo.com"
FONE = "(11) 98765-4321"


@dataclass
class _Resultado:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0


class _Espiao:
    """Substitui `ai.complete`: guarda o que recebeu e ecoa de volta o texto seguro.

    `envelope` deixa cada chamador receber a resposta na FORMA que ele espera (JSON, no caso de
    `funnels` e `marketing`) sem perder o eco — o texto seguro continua sendo o que volta.
    """

    def __init__(self) -> None:
        self.user_message = ""
        self.system = ""
        self.envelope = lambda eco: eco

    def __call__(self, *, system: str, user_message: str, **_kwargs) -> _Resultado:
        self.system = system
        self.user_message = user_message
        return _Resultado(text=self.envelope(user_message))


@pytest.fixture()
def espiao(monkeypatch: pytest.MonkeyPatch) -> _Espiao:
    """Liga a IA e troca `ai.complete` pelo espião.

    Um `setattr` só: os quatro módulos importam `from app.core import ai`, então compartilham o
    MESMO objeto de módulo — e `settings` idem. O `monkeypatch` desfaz ao fim do teste, o que
    importa porque `app.core.ai` é global à suíte.
    """
    espiao = _Espiao()
    monkeypatch.setattr(ai, "complete", espiao)
    monkeypatch.setattr(
        quotes_service.settings, "anthropic_api_key", "sk-ant-teste", raising=False
    )
    return espiao


def _nada_de_pii(texto: str) -> None:
    assert CPF not in texto, "CPF saiu do sistema em claro"
    assert EMAIL not in texto, "e-mail saiu do sistema em claro"
    assert FONE not in texto, "telefone saiu do sistema em claro"
    assert "[CPF_1]" in texto and "[EMAIL_1]" in texto and "[FONE_1]" in texto


# ── quotes: o `brief` que o dono digita ────────────────────────────────────────────────────
def test_quotes_nao_manda_o_brief_cru_e_devolve_os_valores(db: Session, espiao: _Espiao) -> None:
    brief = f"Reforma para Ana, CPF {CPF}, e-mail {EMAIL}, fone {FONE}."
    final = quotes_service.generate_scope(db, tenant_id="t1", brief=brief)

    _nada_de_pii(espiao.user_message)
    assert final == brief.strip(), "o dono tem de receber os valores reais de volta"


# ── funnels: o `prompt` livre do nó ────────────────────────────────────────────────────────
def test_funnels_nao_manda_o_prompt_cru_e_devolve_os_valores(db: Session, espiao: _Espiao) -> None:
    prompt = f"Mensagem para Ana, CPF {CPF}, e-mail {EMAIL}, fone {FONE}."
    espiao.envelope = lambda eco: json.dumps({"subject": "Assunto", "body": eco})

    saida = funnels_service.ai_compose(db, tenant_id="t1", kind="email", prompt=prompt)

    _nada_de_pii(espiao.user_message)
    assert CPF in saida["body"] and EMAIL in saida["body"] and FONE in saida["body"]


# ── marketing: o `topic` livre do carrossel ────────────────────────────────────────────────
def test_marketing_nao_manda_o_topic_cru_e_devolve_os_valores(
    db: Session, espiao: _Espiao
) -> None:
    topic = f"Caso da cliente Ana, CPF {CPF}, e-mail {EMAIL}, fone {FONE}"
    espiao.envelope = lambda eco: json.dumps(
        {
            "slides": [
                {"kind": "cover", "heading": "Capa", "body": eco, "secondary": "",
                 "highlight": ""}
            ],
            "caption": eco,
            "hashtags": "#x",
        }
    )

    saida = marketing_service.generate_content(db, tenant_id="t1", topic=topic, n=3, tone="direto")

    _nada_de_pii(espiao.user_message)
    assert CPF in saida["caption"] and EMAIL in saida["caption"] and FONE in saida["caption"]


# ── receivables: a descrição da cobrança ───────────────────────────────────────────────────
@pytest.mark.parametrize(
    "compor",
    [receivables_service._compose_dunning, receivables_service._compose_dunning_phrase],
    ids=["mensagem_inteira", "so_a_frase"],
)
def test_receivables_nao_manda_a_descricao_crua(db: Session, espiao: _Espiao, compor) -> None:
    """As DUAS composições de cobrança, não só a primeira.

    O nome já virava `[NOME]` na montagem — mas a descrição, que é campo livre, ia inteira.
    """
    descricao = f"Consulta de Ana, CPF {CPF}, e-mail {EMAIL}, fone {FONE}"
    final = compor(
        db, tenant_id="t1", name="Ana Souza", amount_cents=15000,
        due=date(2026, 1, 10), description=descricao,
    )

    _nada_de_pii(espiao.user_message)
    assert "Ana Souza" not in espiao.user_message, "o nome nunca sai — vira [NOME] na montagem"
    assert CPF in final and EMAIL in final and FONE in final
    assert "[NOME]" not in final, "o nome real volta no texto entregue ao dono"
