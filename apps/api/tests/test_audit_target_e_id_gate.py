"""#312 — `audit_entries.target` é um ID, e só. Nada de composto, nada de valor.

O campo não tinha contrato: tinha **convenção por ação**, e a convenção morava no chamador. Foi
assim que três formas diferentes couberam no mesmo lugar — id nu na esmagadora maioria das
chamadas, `f"{source}:{key}"` no módulo `dna` e uma contagem crua (`str(exibidas)`) no `open` do
núcleo — e o consumidor (`scripts/nucleo_activation.py`) precisou virar PARSER
(`target.split(":", 1)[0]`, `int(target)`). Aquele parse só era seguro porque a query filtrava
`action.startswith("dna.")` antes: um contrato que dependia de quem chamava.

**Por que um gate, e não a docstring que a #312 escreveu.** Este repositório já provou duas vezes
que documentar não contém: a docstring de `dna/eventos.py` nomeava o defeito MNT-001 **com
contagem** desde 2026-08-11 e os 17 call sites continuaram lá até a #311; `wallet/models.py`
documentava `target=str(total)` como abuso conhecido do mesmo campo. Conter é trabalho de teste.
Este gate impede a QUARTA forma de nascer.

**O que ele reprova** em `target=`: f-string, `str(...)` de um valor, concatenação/`%`/`.format`,
literal já composto (com `":"`), constante que não é texto — e as mesmas coisas escondidas atrás
de uma variável ou de um **helper do próprio projeto que devolve f-string**. Esta última é a
forma histórica exata (`eventos.alvo_da_resposta`), e sem ela o gate deixaria passar o defeito
que motivou a issue só por ele estar uma camada acima.

**Controles positivos obrigatórios.** Um scanner AST que deixasse de encontrar as chamadas (glob
quebrado, import renomeado, pasta movida) passaria **verde por vacuidade**. Por isso este arquivo
prova, com fontes sintéticas parseadas por `ast`, que o gate MORDE cada forma proibida e que NÃO
morde as formas corretas — e prova, contra o repo real, que ele de fato varreu código.
"""
from __future__ import annotations

import ast
from pathlib import Path

_APP = Path(__file__).resolve().parents[1] / "app"

#: Quem grava trilha. `registrar` é a porta do DNA (`dna/eventos.py`), que delega a `audit.record`.
_GRAVADORES = {"record", "registrar"}

#: Chamadas que produzem TEXTO a partir de um valor — o oposto de um id.
_FABRICAS_DE_TEXTO = {"str", "format", "join", "repr"}


class Ofensa:
    def __init__(self, arquivo: str, linha: int, funcao: str, forma: str) -> None:
        self.arquivo, self.linha, self.funcao, self.forma = arquivo, linha, funcao, forma

    def __eq__(self, outro: object) -> bool:  # para comparar listas em asserção
        return isinstance(outro, Ofensa) and repr(self) == repr(outro)

    def __repr__(self) -> str:  # o que aparece na falha — tem de bastar para o conserto
        return (
            f"{self.arquivo}:{self.linha} em {self.funcao}(): `target=` recebeu {self.forma} "
            "→ `target` é o ID da entidade (ou `\"\"` se não há entidade). O que não é id vai "
            "em `detail`, que é livre — ver o docstring da coluna em `app/core/audit.py`"
        )


def _nome_da_chamada(call: ast.Call) -> str | None:
    f = call.func
    if isinstance(f, ast.Attribute):
        return f.attr
    if isinstance(f, ast.Name):
        return f.id
    return None


def _devolve_texto_composto(no: ast.AST) -> bool:
    """Um `return` que junta PARTES — a assinatura de uma compositora.

    ⚠️ `str(...)` fica de FORA deste critério, e a exclusão foi medida: `db/base.py::_uuid`
    devolve `str(uuid4())` e é a fábrica de ids do projeto inteiro. Indexá-la como compositora
    reprovava `wallet/service.py::request_payout` (`target=payout_id`, com `payout_id = _uuid()`)
    — um id perfeito. `str(x)` numa função que devolve id é o oposto de composição: é conversão
    de UM valor. Junção precisa de DUAS partes, e é isso que f-string, `+`, `%`, `.format` e
    `.join` têm em comum. Na CHAMADA, `str(...)` continua reprovado (`_FABRICAS_DE_TEXTO`): ali
    o que se está convertendo é o valor que deveria ser um id.
    """
    if isinstance(no, ast.JoinedStr):
        return True
    if isinstance(no, ast.BinOp) and isinstance(no.op, ast.Add | ast.Mod):
        return True
    return isinstance(no, ast.Call) and _nome_da_chamada(no) in {"format", "join"}


def compositoras(fontes: list[str]) -> set[str]:
    """Funções do projeto que DEVOLVEM texto composto — `alvo_da_resposta` era uma delas.

    Índice por NOME, sem resolver import: o gate prefere apontar um caso que talvez esteja certo
    a deixar passar um que está errado, e a mesma escolha conservadora está no gate irmão
    (`test_audit_target_flush_gate.py::_linearizar`). Uma função que devolve f-string e é usada
    como `target` viola o contrato, venha de onde vier.
    """
    achadas: set[str] = set()
    for fonte in fontes:
        for no in ast.walk(ast.parse(fonte)):
            if not isinstance(no, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for filho in ast.walk(no):
                if isinstance(filho, ast.Return) and filho.value is not None:
                    if _devolve_texto_composto(filho.value):
                        achadas.add(no.name)
    return achadas


def _composicao(no: ast.AST, apelidos: dict[str, str], indice: set[str]) -> str | None:
    """A razão pela qual esta expressão JUNTA partes em vez de ser um id — ou `None`."""
    if isinstance(no, ast.JoinedStr):
        return "uma f-string (composição)"
    if isinstance(no, ast.BinOp) and isinstance(no.op, ast.Add | ast.Mod):
        return "uma concatenação/formatação de texto"
    if isinstance(no, ast.Call):
        nome = _nome_da_chamada(no)
        if nome in _FABRICAS_DE_TEXTO:
            return f"`{nome}(...)` — texto fabricado de um VALOR, não um id"
        if nome in indice:
            return f"`{nome}(...)`, que devolve texto composto"
        return None
    if isinstance(no, ast.Constant):
        if isinstance(no.value, str) and ":" in no.value:
            return "um literal já composto (contém `:`)"
        return None
    if isinstance(no, ast.Name):
        return apelidos.get(no.id)
    if isinstance(no, ast.IfExp | ast.BoolOp):
        # Um ramo composto contamina o todo: `x if c else f"{a}:{b}"` grava composto metade das
        # vezes, e "metade das vezes" é exatamente como o campo perdeu o contrato.
        ramos = (no.body, no.orelse) if isinstance(no, ast.IfExp) else tuple(no.values)
        for ramo in ramos:
            razao = _composicao(ramo, apelidos, indice)
            if razao:
                return razao
    return None


def _forma_proibida(no: ast.AST, apelidos: dict[str, str], indice: set[str]) -> str | None:
    """A razão pela qual esta expressão não pode ser um `target` — ou `None` se pode.

    Composição em qualquer profundidade, MAIS a regra que só vale na chamada: uma constante que
    não é texto (`target=6`) é um valor, e o campo é `String(255)`.
    """
    razao = _composicao(no, apelidos, indice)
    if razao:
        return razao
    if isinstance(no, ast.Constant) and not isinstance(no.value, str):
        return f"a constante {no.value!r}, que não é texto"
    return None


def _apelidos_compostos(
    fn: ast.FunctionDef | ast.AsyncFunctionDef, indice: set[str]
) -> dict[str, str]:
    """Nomes locais que guardam uma COMPOSIÇÃO — `alvo = f"{source}:{key}"`.

    ⚠️ Passada PRÓPRIA, antes de olhar as chamadas, e é isto que a torna correta: `ast.walk` é
    por nível, **não** por linha, então um `alvo = ...` dentro de um `if` é visitado DEPOIS de um
    `record(...)` no topo da função. Resolver apelidos no mesmo laço perderia exatamente a forma
    do `dna/router.py` (a atribuição vive dentro de um `if`).

    ⚠️ Só atribuições que COMPÕEM entram, e nenhuma atribuição posterior perdoa um nome já
    contaminado — o gate não faz análise de fluxo, e contaminar é o lado conservador. O outro
    lado foi medido: guardar TODA atribuição fazia um `client_id = None` lá em cima reprovar
    `target=client_id or "unidentified"` em `whatsapp_inbox/service.py`, que é um id legítimo.

    Duas passadas resolvem cadeia curta (`a = f"..."` → `b = a` → `target=b`) sem virar
    ponto-fixo: cadeia mais longa que isso num `target` é sintoma pior do que este gate mede.
    """
    apelidos: dict[str, str] = {}
    for _ in range(2):
        for st in ast.walk(fn):
            if (
                isinstance(st, ast.Assign)
                and len(st.targets) == 1
                and isinstance(st.targets[0], ast.Name)
            ):
                razao = _composicao(st.value, apelidos, indice)
                if razao:
                    apelidos.setdefault(st.targets[0].id, razao)
    return apelidos


def _analisar_funcao(
    fn: ast.FunctionDef | ast.AsyncFunctionDef, arquivo: str, indice: set[str]
) -> list[Ofensa]:
    ofensas: list[Ofensa] = []
    apelidos = _apelidos_compostos(fn, indice)
    for st in ast.walk(fn):
        if not isinstance(st, ast.Call) or _nome_da_chamada(st) not in _GRAVADORES:
            continue
        if not any(k.arg == "action" for k in st.keywords):
            continue  # `facts.record(kind=...)` e afins não são a trilha de auditoria
        for kw in st.keywords:
            if kw.arg != "target":
                continue
            razao = _forma_proibida(kw.value, apelidos, indice)
            if razao:
                ofensas.append(Ofensa(arquivo, st.lineno, fn.name, razao))
    return ofensas


def varrer(
    fonte: str, arquivo: str = "<sintetico>", indice: set[str] | None = None
) -> list[Ofensa]:
    """Todas as ofensas ao contrato do `target` num fonte Python."""
    indice = compositoras([fonte]) if indice is None else indice
    ofensas: list[Ofensa] = []
    for no in ast.walk(ast.parse(fonte)):
        if isinstance(no, ast.FunctionDef | ast.AsyncFunctionDef):
            ofensas.extend(_analisar_funcao(no, arquivo, indice))
    return ofensas


def _alvos_analisados(fonte: str) -> int:
    return sum(
        1
        for no in ast.walk(ast.parse(fonte))
        if isinstance(no, ast.Call)
        and _nome_da_chamada(no) in _GRAVADORES
        and any(k.arg == "action" for k in no.keywords)
        and any(k.arg == "target" for k in no.keywords)
    )


# ── Controles positivos: o gate MORDE cada forma proibida ────────────────────

def test_o_gate_reprova_a_f_string():
    """A 2ª forma histórica, na própria chamada."""
    fonte = (
        "\nfrom app.core import audit\n"
        "\n"
        "def salvar(db, *, tenant_id, actor, source, key):\n"
        '    audit.record(db, tenant_id=tenant_id, actor=actor, action="dna.answer.save",\n'
        '                 target=f"{source}:{key}")\n'
    )
    [o] = varrer(fonte, "sintetico.py")
    assert o.linha == 5 and o.funcao == "salvar"
    assert "f-string" in repr(o)
    # A mensagem tem de bastar para consertar sem abrir o gate.
    assert "sintetico.py:5" in repr(o) and "detail" in repr(o)


def test_o_gate_reprova_str_de_um_valor():
    """A 3ª forma histórica: `target=str(corpo.exibidas)` — uma CONTAGEM no campo do id."""
    fonte = (
        "\nfrom app.modules.dna import eventos\n"
        "\n"
        "def nucleo_evento(db, *, tenant_id, actor, corpo):\n"
        '    eventos.registrar(db, tenant_id=tenant_id, actor=actor, action="dna.nucleo.open",\n'
        "                      target=str(corpo.exibidas))\n"
    )
    [o] = varrer(fonte)
    assert "`str(...)`" in repr(o)


def test_o_gate_reprova_concatenacao_e_format():
    concat = (
        "\ndef f(db, *, tenant_id, actor, source, key):\n"
        '    audit.record(db, tenant_id=tenant_id, actor=actor, action="x.y",\n'
        '                 target=source + ":" + key)\n'
    )
    formatado = (
        "\ndef f(db, *, tenant_id, actor, source, key):\n"
        '    audit.record(db, tenant_id=tenant_id, actor=actor, action="x.y",\n'
        '                 target="{}:{}".format(source, key))\n'
    )
    assert len(varrer(concat)) == 1
    assert len(varrer(formatado)) == 1


def test_o_gate_reprova_o_literal_ja_composto():
    """`target="nucleo:oferta"` é a mesma forma, escrita à mão — o `:` é o que denuncia."""
    fonte = (
        "\ndef f(db, *, tenant_id, actor):\n"
        '    audit.record(db, tenant_id=tenant_id, actor=actor, action="x.y",\n'
        '                 target="nucleo:oferta.o_que_vende")\n'
    )
    assert len(varrer(fonte)) == 1


def test_o_gate_reprova_a_composicao_escondida_numa_variavel():
    """Dar um nome à composição não a desfaz — a lição do gate irmão da #311."""
    fonte = (
        "\ndef nucleo_evento(db, *, tenant_id, actor, corpo, source, key):\n"
        '    alvo = f"{source}:{key}"\n'
        '    audit.record(db, tenant_id=tenant_id, actor=actor, action="x.y", target=alvo)\n'
    )
    [o] = varrer(fonte)
    assert "f-string" in repr(o)


def test_o_gate_reprova_a_composicao_atribuida_DENTRO_de_um_if():
    """**A forma exata de `dna/router.py`**: `alvo = str(...)` num ramo, `record` lá embaixo.

    É o caso que obriga a passada própria de apelidos: `ast.walk` visita por NÍVEL, então a
    atribuição dentro do `if` sai DEPOIS da chamada no topo da função. Um gate que resolvesse
    apelidos no mesmo laço passaria verde justamente sobre a terceira forma da issue.
    """
    fonte = (
        "\ndef nucleo_evento(db, *, tenant_id, actor, action, corpo):\n"
        '    alvo = ""\n'
        '    if action == "dna.nucleo.open":\n'
        "        alvo = str(corpo.exibidas)\n"
        "    eventos.registrar(db, tenant_id=tenant_id, actor=actor, action=action, target=alvo)\n"
    )
    [o] = varrer(fonte)
    assert "`str(...)`" in repr(o) and o.linha == 6


def test_o_gate_reprova_a_composicao_escondida_num_HELPER_do_projeto():
    """**A forma histórica exata**: `eventos.alvo_da_resposta(source, key)`.

    A composição acontecia uma CAMADA ACIMA da chamada, noutro arquivo — nenhuma inspeção da
    chamada sozinha a enxergaria. Sem este caso o gate deixaria passar justamente o defeito que
    abriu a issue #312.
    """
    helper = (
        "\ndef alvo_da_resposta(source, key):\n"
        '    return f"{source}:{key}"\n'
    )
    call_site = (
        "\nfrom app.modules.dna import eventos\n"
        "\n"
        "def _gravar(db, *, tenant_id, actor, source, key):\n"
        '    eventos.registrar(db, tenant_id=tenant_id, actor=actor, action="dna.answer.save",\n'
        "                      target=eventos.alvo_da_resposta(source, key))\n"
    )
    indice = compositoras([helper, call_site])
    assert "alvo_da_resposta" in indice

    [o] = varrer(call_site, "dna/service.py", indice)
    assert "alvo_da_resposta" in repr(o)
    # E o controle do controle: sem o índice cross-file, a chamada passa. É por isso que o gate
    # real (abaixo) monta o índice com o repo INTEIRO antes de varrer qualquer arquivo.
    assert varrer(call_site, "dna/service.py", set()) == []


def test_o_gate_reprova_a_constante_que_nao_e_texto():
    fonte = (
        "\ndef f(db, *, tenant_id, actor):\n"
        '    audit.record(db, tenant_id=tenant_id, actor=actor, action="x.y", target=6)\n'
    )
    assert len(varrer(fonte)) == 1


# ── Controles negativos: o gate NÃO morde o que está certo ───────────────────

def test_o_gate_aprova_o_id_da_entidade():
    fonte = (
        "\ndef criar(db, *, tenant_id, actor):\n"
        "    w = Widget(tenant_id=tenant_id)\n"
        "    db.add(w)\n"
        "    db.flush()\n"
        '    audit.record(db, tenant_id=tenant_id, actor=actor, action="w.create", target=w.id)\n'
    )
    assert varrer(fonte) == []


def test_o_gate_aprova_target_vazio_e_id_em_variavel():
    """`""` é o contrato para "não há entidade" — e um id guardado numa variável é um id."""
    fonte = (
        "\ndef f(db, *, tenant_id, actor, chat):\n"
        "    chat_id = chat.id\n"
        '    audit.record(db, tenant_id=tenant_id, actor=actor, action="a.b", target=chat_id)\n'
        '    audit.record(db, tenant_id=tenant_id, actor=actor, action="a.c", target="")\n'
    )
    assert varrer(fonte) == []


def test_o_gate_aprova_id_com_sentinela_sem_dois_pontos():
    """A forma real de `whatsapp_inbox.service`: id, ou uma palavra quando não há cliente.

    Continua sendo "um alvo", não uma composição — e o `:` é o que separa os dois casos.
    """
    fonte = (
        "\ndef f(db, *, tenant_id, client_id):\n"
        '    audit.record(db, tenant_id=tenant_id, actor="x", action="a.b",\n'
        '                 target=client_id or "unidentified")\n'
    )
    assert varrer(fonte) == []


def test_o_gate_ignora_facts_record_que_nao_e_auditoria():
    """`facts.record(kind=...)` não tem `action` e não grava `audit_entries` — fora do escopo."""
    fonte = (
        "\ndef f(db, *, tenant_id, a, b):\n"
        '    facts.record(db, tenant_id=tenant_id, kind="x.y", ref_id=f"{a}:{b}")\n'
    )
    assert varrer(fonte) == []


# ── O gate contra o repo real ────────────────────────────────────────────────

def _fontes_do_app() -> dict[str, str]:
    return {
        a.relative_to(_APP.parent).as_posix(): a.read_text(encoding="utf-8")
        for a in sorted(_APP.rglob("*.py"))
    }


def test_a_varredura_realmente_leu_o_repo():
    """Controle antivacuidade: sem isto, um glob quebrado aprovaria o projeto inteiro."""
    fontes = _fontes_do_app()
    assert len(fontes) > 100, f"a varredura leu só {len(fontes)} arquivos — glob quebrado?"
    alvos = sum(_alvos_analisados(f) for f in fontes.values())
    assert alvos > 50, (
        f"só {alvos} chamadas de auditoria COM `target=` encontradas. O gate abaixo passaria "
        "verde sobre um repo que ele não está enxergando (import renomeado? pasta movida?)."
    )


def test_nenhum_target_do_repo_e_composto_ou_valor():
    fontes = _fontes_do_app()
    # O índice de compositoras é montado com o repo INTEIRO antes da varredura: a composição
    # pode morar noutro arquivo (era o caso de `dna/eventos.py` → `dna/service.py`).
    indice = compositoras(list(fontes.values()))
    ofensas: list[Ofensa] = []
    for rel, fonte in fontes.items():
        ofensas.extend(varrer(fonte, rel, indice))
    assert not ofensas, (
        "`audit_entries.target` é o ID da entidade da ação, ou `\"\"` quando não há entidade — "
        "nunca um composto, nunca um valor. Estas chamadas gravam outra coisa, e é assim que o "
        "campo perde o contrato e o consumidor vira parser (issue #312).\n  "
        + "\n  ".join(repr(o) for o in ofensas)
    )
