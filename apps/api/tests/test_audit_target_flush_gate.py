"""MNT-001 — a trilha tem de dizer QUAL entidade a ação criou, e isso não se sustenta na mão.

`audit_entries.target` é `String(255)`, `NOT NULL`, `default=""`. O `id` das entidades tem default
**Python-side** (`_uuid`), aplicado só no INSERT. Então `db.add(x)` seguido de
`audit.record(..., target=x.id)` **sem flush** grava `target=''` — sem exceção, sem log, sem
sintoma: a API responde 201, a suíte fica verde, e a entrada de auditoria diz que algo foi criado
sem dizer o quê. Eram 17 call sites assim (issue #311).

**Por que um gate e não disciplina.** A docstring de `dna/eventos.py` já nomeava o defeito, com
contagem, desde 2026-08-11 — e os 17 continuaram lá. O comentário de `bank/service.py` chegava a
apontar `chart_of_accounts` como ofensor conhecido, também sem consertá-lo. Documentar não conteve;
conter é trabalho de teste.

**Controles positivos obrigatórios.** Um scanner AST que deixasse de encontrar as chamadas (glob
quebrado, `audit` importado com outro nome, pasta renomeada) passaria **verde por vacuidade**. Por
isso este arquivo prova, com fontes sintéticas parseadas por `ast`, que o gate MORDE o defeito e
que NÃO morde as formas corretas — e prova, contra o repo real, que ele de fato varreu código.
"""
from __future__ import annotations

import ast
from pathlib import Path

_APP = Path(__file__).resolve().parents[1] / "app"

#: Quem grava trilha. `registrar` é a porta do DNA (`dna/eventos.py`), que delega a `audit.record`.
_GRAVADORES = {"record", "registrar"}

#: O que garante que o INSERT já aconteceu. `refresh` implica flush da sessão.
_BARREIRAS = {"flush", "commit", "refresh"}

_CAMPOS_DE_BLOCO = ("body", "orelse", "finalbody", "handlers")


class Ofensa:
    def __init__(self, arquivo: str, linha: int, funcao: str, variavel: str) -> None:
        self.arquivo, self.linha, self.funcao, self.variavel = arquivo, linha, funcao, variavel

    def __repr__(self) -> str:  # o que aparece na falha — tem de bastar para o conserto
        return (
            f"{self.arquivo}:{self.linha} em {self.funcao}(): "
            f"`target={self.variavel}.id` depois de `db.add({self.variavel})` sem flush "
            f"→ acrescente `db.flush()` entre os dois"
        )


def _nome_da_chamada(call: ast.Call) -> str | None:
    f = call.func
    if isinstance(f, ast.Attribute):
        return f.attr
    if isinstance(f, ast.Name):
        return f.id
    return None


def _raiz(no: ast.AST) -> str | None:
    """Nome-base de uma expressão: `x` para `x`, para `x.id` e para `x.a.b`."""
    while isinstance(no, ast.Attribute):
        no = no.value
    return no.id if isinstance(no, ast.Name) else None


def _chamadas_do_statement(st: ast.stmt) -> list[ast.Call]:
    """Chamadas do próprio statement, SEM descer para corpos de blocos aninhados.

    Descer duplicaria: o `try` e o statement dentro dele seriam visitados duas vezes, e a mesma
    ofensa apareceria em dobro.
    """
    achadas: list[ast.Call] = []
    pilha: list[tuple[ast.AST, bool]] = [(st, True)]
    while pilha:
        no, e_a_raiz = pilha.pop()
        if isinstance(no, ast.Call):
            achadas.append(no)
        if isinstance(no, ast.stmt) and not e_a_raiz:
            continue  # statement aninhado: entra pela linearização, não por aqui
        for campo, valor in ast.iter_fields(no):
            if e_a_raiz and campo in _CAMPOS_DE_BLOCO:
                continue
            if isinstance(valor, list):
                pilha.extend((v, False) for v in valor if isinstance(v, ast.AST))
            elif isinstance(valor, ast.AST):
                pilha.append((valor, False))
    achadas.sort(key=lambda c: (c.lineno, c.col_offset))
    return achadas


def _linearizar(corpo: list[ast.stmt]) -> list[ast.stmt]:
    """Statements em ordem de linha, achatando blocos — aproximação conservadora do fluxo.

    Um `db.add` dentro de um `if` passa a valer para o que vem depois do `if`. É deliberado: o
    gate prefere apontar um caso que talvez esteja certo a deixar passar um que está errado — e
    é exatamente essa a forma de `google_calendar.upsert_credential`. Corpos de `def`/`class`
    aninhados NÃO entram (eles são analisados como funções próprias).
    """
    saida: list[ast.stmt] = []
    for st in corpo:
        saida.append(st)
        if isinstance(st, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            continue
        for campo in _CAMPOS_DE_BLOCO:
            filhos = getattr(st, campo, None)
            if not isinstance(filhos, list):
                continue
            saida.extend(_linearizar([c for c in filhos if isinstance(c, ast.stmt)]))
            for c in filhos:
                if isinstance(c, ast.ExceptHandler):
                    saida.extend(_linearizar(c.body))
    saida.sort(key=lambda s: (s.lineno, s.col_offset))
    return saida


def _analisar_funcao(fn: ast.FunctionDef | ast.AsyncFunctionDef, arquivo: str) -> list[Ofensa]:
    ofensas: list[Ofensa] = []
    pendentes: set[str] = set()          # adicionados à sessão e ainda sem INSERT
    apelidos: dict[str, str] = {}        # `v = x.id` → `v` guarda o id de `x`
    for st in _linearizar(fn.body):
        for call in _chamadas_do_statement(st):
            nome = _nome_da_chamada(call)
            if nome in _GRAVADORES:
                if not any(k.arg == "action" for k in call.keywords):
                    continue  # `facts.record(kind=...)` e afins não são a trilha de auditoria
                for kw in call.keywords:
                    if kw.arg != "target":
                        continue
                    alvo, base = kw.value, None
                    if isinstance(alvo, ast.Attribute) and alvo.attr == "id":
                        base = _raiz(alvo)
                    elif isinstance(alvo, ast.Name):
                        base = apelidos.get(alvo.id)
                    if base and base in pendentes:
                        ofensas.append(Ofensa(arquivo, call.lineno, fn.name, base))
            elif isinstance(call.func, ast.Attribute) and call.func.attr in _BARREIRAS:
                pendentes.clear()
                apelidos.clear()
            elif (
                isinstance(call.func, ast.Attribute)
                and call.func.attr == "add"
                and len(call.args) == 1
            ):
                base = _raiz(call.args[0])
                if base:
                    pendentes.add(base)
        if (
            isinstance(st, ast.Assign)
            and len(st.targets) == 1
            and isinstance(st.targets[0], ast.Name)
            and isinstance(st.value, ast.Attribute)
            and st.value.attr == "id"
        ):
            base = _raiz(st.value)
            if base:
                apelidos[st.targets[0].id] = base
    return ofensas


def varrer(fonte: str, arquivo: str = "<sintetico>") -> list[Ofensa]:
    """Todas as ofensas MNT-001 de um fonte Python."""
    ofensas: list[Ofensa] = []
    for no in ast.walk(ast.parse(fonte)):
        if isinstance(no, ast.FunctionDef | ast.AsyncFunctionDef):
            ofensas.extend(_analisar_funcao(no, arquivo))
    return ofensas


def _contar_gravacoes(fonte: str) -> int:
    return sum(
        1
        for no in ast.walk(ast.parse(fonte))
        if isinstance(no, ast.Call)
        and _nome_da_chamada(no) in _GRAVADORES
        and any(k.arg == "action" for k in no.keywords)
    )


# ── Controles positivos: o gate MORDE ────────────────────────────────────────

_DEFEITO = (
    "\nfrom app.core import audit\n"
    "\n"
    "def create_widget(db, *, tenant_id, actor, data):\n"
    "    w = Widget(tenant_id=tenant_id, name=data.name)\n"
    "    db.add(w)\n"
    '    audit.record(db, tenant_id=tenant_id, actor=actor, action="widget.create", target=w.id)\n'
    "    db.commit()\n"
    "    return w\n"
)


def test_o_gate_reprova_o_defeito_cru():
    """Sem isto, o gate é um teste que sempre passa: nada prova que ele enxerga o defeito."""
    ofensas = varrer(_DEFEITO, "sintetico.py")
    assert len(ofensas) == 1, ofensas
    assert ofensas[0].linha == 7
    assert ofensas[0].funcao == "create_widget"
    assert ofensas[0].variavel == "w"
    # A mensagem tem de bastar para consertar sem abrir o gate.
    assert "sintetico.py:7" in repr(ofensas[0])
    assert "db.flush()" in repr(ofensas[0])


def test_o_gate_reprova_o_defeito_aninhado_num_if():
    """A forma de `juridico.generate`: o `add` e o `record` dentro de um ramo."""
    fonte = (
        "\nfrom app.core import audit\n"
        "\n"
        "def generate(db, *, tenant_id, actor):\n"
        "    doc = Doc(tenant_id=tenant_id)\n"
        "    if not settings.key:\n"
        "        db.add(doc)\n"
        '        audit.record(db, tenant_id=tenant_id, actor=actor, action="legal.skip",\n'
        "                     target=doc.id)\n"
        "        db.commit()\n"
        "        return doc\n"
        "    return None\n"
    )
    assert len(varrer(fonte)) == 1


def test_o_gate_reprova_o_defeito_distante_do_add():
    """A forma de `google_calendar.upsert_credential`: `add` num ramo, `record` linhas abaixo."""
    fonte = (
        "\nfrom app.core import audit\n"
        "\n"
        "def upsert(db, *, tenant_id, email):\n"
        "    cred = get_credential(db)\n"
        "    if cred is None:\n"
        "        cred = Cred(tenant_id=tenant_id)\n"
        "        db.add(cred)\n"
        "    cred.email = email\n"
        '    audit.record(db, tenant_id=tenant_id, actor="x", action="cred.connect",\n'
        "                 target=cred.id)\n"
        "    db.commit()\n"
    )
    assert len(varrer(fonte)) == 1


def test_o_gate_reprova_o_defeito_disfarcado_de_variavel():
    """`alvo = w.id` antes do flush guarda o MESMO `None` — trocar de nome não conserta nada."""
    fonte = (
        "\nfrom app.core import audit\n"
        "\n"
        "def create_widget(db, *, tenant_id, actor):\n"
        "    w = Widget(tenant_id=tenant_id)\n"
        "    db.add(w)\n"
        "    alvo = w.id\n"
        '    audit.record(db, tenant_id=tenant_id, actor=actor, action="widget.create",\n'
        "                 target=alvo)\n"
        "    db.commit()\n"
    )
    assert len(varrer(fonte)) == 1


def test_o_gate_reprova_pela_porta_do_dna_tambem():
    """`eventos.registrar` delega a `audit.record` — passar por ela não isenta do flush."""
    fonte = (
        "\nfrom app.modules.dna import eventos\n"
        "\n"
        "def salvar(db, *, tenant_id, actor):\n"
        "    resposta = Answer(tenant_id=tenant_id)\n"
        "    db.add(resposta)\n"
        '    eventos.registrar(db, tenant_id=tenant_id, actor=actor, action="dna.answer.save",\n'
        "                      target=resposta.id)\n"
        "    db.commit()\n"
    )
    assert len(varrer(fonte)) == 1


# ── Controles negativos: o gate NÃO morde o que está certo ───────────────────

def test_o_gate_aprova_o_flush_no_lugar():
    fonte = _DEFEITO.replace("    db.add(w)\n", "    db.add(w)\n    db.flush()\n")
    assert varrer(fonte) == []


def test_o_gate_aprova_commit_como_barreira():
    fonte = _DEFEITO.replace("    db.add(w)\n", "    db.add(w)\n    db.commit()\n")
    assert varrer(fonte) == []


def test_o_gate_aprova_alvo_que_nao_nasceu_do_add():
    """Update/delete de linha existente: o `id` veio do banco, não há nada a esperar."""
    fonte = (
        "\nfrom app.core import audit\n"
        "\n"
        "def update_widget(db, *, widget_id, tenant_id, actor, data):\n"
        "    w = get_widget(db, widget_id)\n"
        "    w.name = data.name\n"
        '    audit.record(db, tenant_id=tenant_id, actor=actor, action="widget.update",\n'
        "                 target=w.id)\n"
        "    db.commit()\n"
    )
    assert varrer(fonte) == []


def test_o_gate_ignora_facts_record_que_nao_e_auditoria():
    """`facts.record(kind=...)` não tem `action` e não grava `audit_entries` — fora do escopo."""
    fonte = (
        "\ndef create_widget(db, *, tenant_id):\n"
        "    w = Widget(tenant_id=tenant_id)\n"
        "    db.add(w)\n"
        '    facts.record(db, tenant_id=tenant_id, kind="widget.created", ref_id=w.id)\n'
        "    db.commit()\n"
    )
    assert varrer(fonte) == []


def test_o_gate_nao_conta_a_mesma_ofensa_duas_vezes():
    """Um `record` dentro de um `try` é alcançado pelo `try` e por si — só pode contar uma vez."""
    fonte = (
        "\nfrom app.core import audit\n"
        "\n"
        "def create_widget(db, *, tenant_id, actor):\n"
        "    w = Widget(tenant_id=tenant_id)\n"
        "    db.add(w)\n"
        "    try:\n"
        '        audit.record(db, tenant_id=tenant_id, actor=actor, action="widget.create",\n'
        "                     target=w.id)\n"
        "        db.commit()\n"
        "    except Exception:\n"
        "        db.rollback()\n"
    )
    assert len(varrer(fonte)) == 1


# ── O gate contra o repo real ────────────────────────────────────────────────

def test_a_varredura_realmente_leu_o_repo():
    """Controle antivacuidade: sem isto, um glob quebrado aprovaria o projeto inteiro."""
    arquivos = list(_APP.rglob("*.py"))
    assert len(arquivos) > 100, f"a varredura leu só {len(arquivos)} arquivos — glob quebrado?"
    total = sum(_contar_gravacoes(a.read_text(encoding="utf-8")) for a in arquivos)
    assert total > 50, (
        f"só {total} chamadas de auditoria encontradas no projeto. O gate abaixo passaria verde "
        "sobre um repo que ele não está enxergando (import renomeado? pasta movida?)."
    )


def test_nenhum_call_site_grava_target_vazio():
    ofensas: list[Ofensa] = []
    for arquivo in sorted(_APP.rglob("*.py")):
        rel = arquivo.relative_to(_APP.parent).as_posix()
        ofensas.extend(varrer(arquivo.read_text(encoding="utf-8"), rel))
    assert not ofensas, (
        "MNT-001: estes `audit.record()` gravam `target=''` — a trilha registra que a ação "
        "aconteceu e perde de QUAL entidade tratava, sem erro nenhum (`target` é NOT NULL com "
        'default `""`, e o `id` só existe depois do INSERT).\n  '
        + "\n  ".join(repr(o) for o in ofensas)
    )
