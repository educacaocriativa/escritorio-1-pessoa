"""Testes do loop de tool-use (`core/ai.complete_with_tools`).

Esta é a PRIMEIRA consumidora da API de tool-use da Anthropic neste repositório — nenhum outro
módulo tinha `tools=`/`tool_use` antes desta função existir. Mesma disciplina do resto de
`core/ai.py`: mockar `_get_client`, nunca chamar a API de verdade.
"""
from types import SimpleNamespace

from sqlalchemy.orm import Session

from app.core import ai
from app.core.ai_usage import AIUsage

TENANT = "t1"


class _FakeMessagesQueue:
    """Devolve uma resposta por chamada, na ordem — o loop faz várias chamadas."""

    def __init__(self, respostas: list):
        self.respostas = list(respostas)
        self.chamadas: list[dict] = []

    def create(self, **kwargs):
        self.chamadas.append(kwargs)
        return self.respostas.pop(0)


class _FakeClient:
    def __init__(self, messages: _FakeMessagesQueue):
        self.messages = messages


def _bloco_texto(texto: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=texto)


def _bloco_tool_use(nome: str, entrada: dict, tool_id: str = "tu_1") -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=tool_id, name=nome, input=entrada)


def _resposta(
    blocos: list, *, stop_reason: str, input_tokens=10, output_tokens=5
) -> SimpleNamespace:
    return SimpleNamespace(
        content=blocos,
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
        stop_reason=stop_reason,
    )


def _install_fake(monkeypatch, respostas: list) -> _FakeMessagesQueue:
    fila = _FakeMessagesQueue(respostas)
    monkeypatch.setattr(ai, "_get_client", lambda: _FakeClient(fila))
    return fila


def _loop(db, **over):
    kwargs = {
        "db": db, "tenant_id": TENANT, "task": "vima.pergunta",
        "system": "S", "user_message": "quanto eu tenho a receber?",
        "tools": [{"name": "consultar_recebiveis", "description": "d",
                   "input_schema": {"type": "object", "properties": {}}}],
        "executar_ferramenta": lambda nome, entrada: "{}",
    }
    kwargs.update(over)
    return ai.complete_with_tools(**kwargs)


def test_para_direto_quando_a_primeira_rodada_nao_pede_ferramenta(db: Session, monkeypatch):
    fila = _install_fake(
        monkeypatch, [_resposta([_bloco_texto("R$ 0,00")], stop_reason="end_turn")]
    )
    resultado = _loop(db)
    assert resultado.text == "R$ 0,00"
    assert resultado.turnos_usados == 1
    assert resultado.parou_no_teto is False
    assert len(fila.chamadas) == 1


def test_chama_a_ferramenta_com_o_nome_e_o_input_pedidos_pela_claude(db: Session, monkeypatch):
    _install_fake(monkeypatch, [
        _resposta(
            [_bloco_tool_use("consultar_recebiveis", {"foo": "bar"})], stop_reason="tool_use"
        ),
        _resposta([_bloco_texto("resposta final")], stop_reason="end_turn"),
    ])
    chamadas_da_ferramenta = []

    def _executar(nome, entrada):
        chamadas_da_ferramenta.append((nome, entrada))
        return '{"open_cents": 100}'

    resultado = _loop(db, executar_ferramenta=_executar)
    assert chamadas_da_ferramenta == [("consultar_recebiveis", {"foo": "bar"})]
    assert resultado.text == "resposta final"


def test_o_resultado_da_ferramenta_volta_para_a_claude_como_tool_result(db: Session, monkeypatch):
    fila = _install_fake(monkeypatch, [
        _resposta(
            [_bloco_tool_use("consultar_recebiveis", {}, tool_id="tu_9")], stop_reason="tool_use"
        ),
        _resposta([_bloco_texto("ok")], stop_reason="end_turn"),
    ])
    _loop(db, executar_ferramenta=lambda nome, entrada: '{"open_cents": 500}')

    segunda_chamada = fila.chamadas[1]
    ultima_mensagem = segunda_chamada["messages"][-1]
    assert ultima_mensagem["role"] == "user"
    assert ultima_mensagem["content"] == [
        {"type": "tool_result", "tool_use_id": "tu_9", "content": '{"open_cents": 500}'}
    ]


def test_grava_uma_linha_de_ledger_por_rodada_de_api(db: Session, monkeypatch):
    _install_fake(monkeypatch, [
        _resposta([_bloco_tool_use("consultar_recebiveis", {})], stop_reason="tool_use",
                   input_tokens=10, output_tokens=5),
        _resposta([_bloco_texto("ok")], stop_reason="end_turn", input_tokens=20, output_tokens=8),
    ])
    _loop(db, executar_ferramenta=lambda nome, entrada: "{}", user_id="u1")
    db.commit()

    linhas = db.query(AIUsage).order_by(AIUsage.input_tokens).all()
    assert len(linhas) == 2
    assert [linha.input_tokens for linha in linhas] == [10, 20]
    assert all(
        linha.task == "vima.pergunta" and linha.model == "claude-sonnet-5" for linha in linhas
    )
    assert all(linha.user_id == "u1" for linha in linhas)


def test_estoura_o_teto_de_rodadas_e_forca_uma_resposta_final_sem_ferramentas(
    db: Session, monkeypatch
):
    fila = _install_fake(monkeypatch, [
        _resposta([_bloco_tool_use("consultar_recebiveis", {})], stop_reason="tool_use"),
        _resposta([_bloco_tool_use("consultar_recebiveis", {})], stop_reason="tool_use"),
        _resposta([_bloco_texto("melhor resposta possível")], stop_reason="end_turn"),
    ])
    resultado = _loop(db, executar_ferramenta=lambda nome, entrada: "{}", max_tool_turns=2)

    assert resultado.parou_no_teto is True
    assert resultado.turnos_usados == 3
    assert resultado.text == "melhor resposta possível"
    # a chamada de wrap-up NÃO oferece ferramentas — é isso que força um texto final
    assert "tools" not in fila.chamadas[-1]


def test_soma_os_tokens_de_todas_as_rodadas_no_resultado(db: Session, monkeypatch):
    _install_fake(monkeypatch, [
        _resposta([_bloco_tool_use("consultar_recebiveis", {})], stop_reason="tool_use",
                   input_tokens=10, output_tokens=5),
        _resposta([_bloco_texto("ok")], stop_reason="end_turn", input_tokens=20, output_tokens=8),
    ])
    resultado = _loop(db, executar_ferramenta=lambda nome, entrada: "{}")
    assert (resultado.input_tokens, resultado.output_tokens) == (30, 13)
