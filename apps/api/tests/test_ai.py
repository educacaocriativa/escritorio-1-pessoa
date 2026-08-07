"""Testes unitários diretos da camada de IA (`core/ai.py`).

Cobrem, isoladamente (sem tocar a API real do Claude), a montagem do prompt, o parsing de
`AIResult`, a propagação de erro — pré-condição dos fallbacks implementados em cada caller
(marketing, juridico, funnels, quotes, financial_intelligence, receivables, vima) — e as duas
garantias novas: **toda chamada bem-sucedida é contabilizada** e **o roteamento escolhe o
modelo pela tarefa**.
"""
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from app.core import ai
from app.core.ai_usage import AIUsage

TENANT = "t1"


class _FakeMessages:
    """Captura os kwargs de `create(...)` e devolve uma resposta fixa (ou lança)."""

    def __init__(self, response=None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.captured: dict | None = None

    def create(self, **kwargs):
        self.captured = kwargs
        if self.error is not None:
            raise self.error
        return self.response


class _FakeClient:
    def __init__(self, messages: _FakeMessages):
        self.messages = messages


def _ok_response(text="ok", input_tokens=1, output_tokens=1, **usage_extra):
    return SimpleNamespace(
        content=[SimpleNamespace(text=text)],
        usage=SimpleNamespace(
            input_tokens=input_tokens, output_tokens=output_tokens, **usage_extra
        ),
    )


def _install_fake(monkeypatch, *, response=None, error=None) -> _FakeMessages:
    messages = _FakeMessages(response=response, error=error)
    client = _FakeClient(messages)
    monkeypatch.setattr(ai, "_get_client", lambda: client)
    return messages


def _complete(db, **over):
    """Chamada mínima válida — `db`, `tenant_id` e `task` são obrigatórios."""
    kwargs = {
        "db": db, "tenant_id": TENANT, "task": "vima.briefing",
        "system": "S", "user_message": "U",
    }
    kwargs.update(over)
    return ai.complete(**kwargs)


# ── Montagem do prompt e parsing ────────────────────────────────────────────────────────────


def test_complete_builds_prompt_with_system_and_user_message(db: Session, monkeypatch):
    messages = _install_fake(monkeypatch, response=_ok_response())
    _complete(db, system="SYS", user_message="MSG", max_tokens=123)
    kwargs = messages.captured
    assert kwargs["system"] == "SYS"
    assert kwargs["messages"] == [{"role": "user", "content": "MSG"}]
    assert kwargs["max_tokens"] == 123


def test_complete_uses_explicit_model_override(db: Session, monkeypatch):
    messages = _install_fake(monkeypatch, response=_ok_response())
    _complete(db, model="modelo-x")
    assert messages.captured["model"] == "modelo-x"


def test_complete_uses_default_max_tokens(db: Session, monkeypatch):
    messages = _install_fake(monkeypatch, response=_ok_response())
    _complete(db)
    assert messages.captured["max_tokens"] == 4096


def test_complete_parses_ai_result_from_response(db: Session, monkeypatch):
    _install_fake(
        monkeypatch,
        response=_ok_response(text="resposta da IA", input_tokens=10, output_tokens=20),
    )
    result = _complete(db)
    assert isinstance(result, ai.AIResult)
    assert result.text == "resposta da IA"
    assert result.input_tokens == 10
    assert result.output_tokens == 20


def test_complete_propagates_client_error(db: Session, monkeypatch):
    _install_fake(monkeypatch, error=RuntimeError("api indisponível"))
    # A exceção sobe crua — é isso que permite o try/except de fallback dos callers.
    with pytest.raises(RuntimeError, match="api indisponível"):
        _complete(db)


# ── Roteamento de modelo por tarefa ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("task", "modelo"),
    [
        ("vima.briefing", "claude-haiku-4-5"),
        ("financeiro.diagnostico", "claude-haiku-4-5"),
        ("receivables.cobranca", "claude-haiku-4-5"),
        ("quotes.escopo", "claude-sonnet-5"),
        ("funnels.compose", "claude-sonnet-5"),
        ("marketing.carrossel", "claude-sonnet-5"),
        ("juridico.documento", "claude-opus-5"),
    ],
)
def test_roteamento_escolhe_o_modelo_da_tarefa(db: Session, monkeypatch, task, modelo):
    messages = _install_fake(monkeypatch, response=_ok_response())
    _complete(db, task=task)
    assert messages.captured["model"] == modelo


def test_tarefa_desconhecida_cai_no_default_em_vez_de_explodir(db: Session, monkeypatch):
    """Uma tarefa nova não pode derrubar a chamada — e o default é o modelo mais CAPAZ.

    Roteada por engano para o mais barato, ela degradaria em silêncio; roteada para o mais caro,
    só custa mais — e o excedente aparece no ledger, que é o instrumento instalado aqui.
    """
    messages = _install_fake(monkeypatch, response=_ok_response())
    _complete(db, task="modulo.que.ainda.nao.existe")
    assert messages.captured["model"] == ai.MODELO_PADRAO == "claude-opus-5"


def test_toda_tarefa_roteada_usa_um_modelo_conhecido():
    """Instanciação obrigatória do mapa: um typo no ID vira 404 só em produção, na primeira
    chamada real daquela tarefa — nenhum teste de comportamento pega isso."""
    conhecidos = {"claude-haiku-4-5", "claude-sonnet-5", "claude-opus-5"}
    assert set(ai.MODELO_POR_TAREFA.values()) <= conhecidos
    assert ai.MODELO_PADRAO in conhecidos
    # O não-membro que torna a asserção acima não-trivial.
    assert ai.modelo_da_tarefa("tarefa.inexistente") == ai.MODELO_PADRAO


# ── Contabilidade ───────────────────────────────────────────────────────────────────────────


def test_toda_chamada_bem_sucedida_grava_uma_linha_no_ledger(db: Session, monkeypatch):
    _install_fake(
        monkeypatch,
        response=_ok_response(
            input_tokens=100, output_tokens=250,
            cache_read_input_tokens=40, cache_creation_input_tokens=7,
        ),
    )
    _complete(db, task="juridico.documento", user_id="u1")
    db.commit()

    linhas = db.query(AIUsage).all()
    assert len(linhas) == 1
    uso = linhas[0]
    assert uso.tenant_id == TENANT
    assert uso.user_id == "u1"
    assert uso.task == "juridico.documento"
    # O modelo gravado é o que RODOU, não o configurado.
    assert uso.model == "claude-opus-5"
    assert (uso.input_tokens, uso.output_tokens) == (100, 250)
    assert (uso.cache_read_tokens, uso.cache_creation_tokens) == (40, 7)


def test_resposta_sem_campos_de_cache_grava_zero(db: Session, monkeypatch):
    """Nem toda resposta traz os campos de cache; a ausência deles não pode virar erro."""
    _install_fake(monkeypatch, response=_ok_response(input_tokens=5, output_tokens=6))
    _complete(db)
    db.commit()

    uso = db.query(AIUsage).one()
    assert (uso.cache_read_tokens, uso.cache_creation_tokens) == (0, 0)


def test_sem_usuario_a_linha_ainda_e_gravada(db: Session, monkeypatch):
    """Worker e cron não têm usuário — `user_id` nulo é o caso normal, não uma falha."""
    _install_fake(monkeypatch, response=_ok_response())
    _complete(db)
    db.commit()

    assert db.query(AIUsage).one().user_id is None


def test_falha_ao_gravar_o_ledger_nao_derruba_a_chamada(db: Session, monkeypatch):
    """A regra que separa este ledger de `facts.record`.

    Quando o ledger vai gravar, a chamada à Anthropic JÁ aconteceu e JÁ custou dinheiro.
    Derrubar a transação aqui perderia o documento que o usuário esperou 40 segundos para
    receber — e o dinheiro teria sido gasto do mesmo jeito.
    """
    _install_fake(monkeypatch, response=_ok_response(text="entregue mesmo assim"))

    def _explode(*_a, **_kw):
        raise RuntimeError("banco caiu na hora de gravar o ledger")

    monkeypatch.setattr(ai.ai_usage, "AIUsage", _explode)

    resultado = _complete(db)

    assert resultado.text == "entregue mesmo assim"
    assert db.query(AIUsage).count() == 0


def test_transacao_do_chamador_sobrevive_a_falha_do_ledger(db: Session, monkeypatch):
    """O `except` sozinho não bastaria: um flush que falha deixa a Session em rollback
    pendente, e o commit do CHAMADOR morreria depois, longe daqui. O SAVEPOINT é o que
    delimita a falha."""
    from app.core.audit import AuditEntry
    from app.core.facts import Fact

    _install_fake(monkeypatch, response=_ok_response())

    # Trabalho de negócio pendente ANTES da chamada de IA, como no juridico.
    db.add(AuditEntry(tenant_id=TENANT, actor="u1", action="legal.generate", target="doc1"))

    def _flush_quebrado(*_a, **_kw):
        # Uma linha inválida: `module` é NOT NULL. Estoura no flush, dentro do savepoint.
        return Fact(tenant_id=TENANT, kind="x", title="y", actor="s")

    monkeypatch.setattr(ai.ai_usage, "AIUsage", _flush_quebrado)

    _complete(db)
    db.commit()  # o que importa: isto não pode levantar

    assert db.query(AuditEntry).count() == 1
    assert db.query(AIUsage).count() == 0
