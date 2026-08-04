"""A **Regra dos Planos** como teste executável — não como convenção (Story 8.2, AC8).

Por que este arquivo existe (design `controle-bancario-design.md` §1.3): o bug que originou o Epic
8 foi a Projeção de Caixa tratando `wallet.available_cents` (plano 1 — dinheiro na plataforma) como
se fosse o saldo da conta bancária do usuário (plano 3). Rotular os campos e escrever a regra na
docstring resolve o caso conhecido; não resolve o próximo. Literalmente:

    *"sem (1) o resto degrada por acidente: basta uma story futura importar o módulo errado para
    recriar o bug numa forma nova."*

Por isso o design classifica esta regra como **gate**, e por isso ela vive aqui, em varredura
estática (mesmo estilo de `tests/test_tenancy_guard.py`), e não num comentário que ninguém lê.

**A regra**, em três partes:
  (a) nenhum cálculo de saldo bancário lê `transactions`, nenhum cálculo de saldo de carteira lê
      `bank_transactions`, e as duas somas **nunca** ocupam o mesmo campo numérico;
  (b) `app.modules.bank` **pode** importar `app.modules.wallet`; `app.modules.wallet` **nunca**
      importa `app.modules.bank` — o único ponto de contato legítimo (o payout da Carteira, Onda 3)
      vive do lado `bank` e se comunica por `core/events` (design §6.6);
  (c) todo campo de API que carrega saldo declara a procedência num irmão `*_origem`
      (`app.core.money_planes`);
  (d) **[Story 8.9]** `payables`/`receivables` **podem** importar `app.modules.bank`;
      `app.modules.bank` **nunca** importa `payables`/`receivables` — a dependência é **de negócio
      para banco, jamais a volta** (design Onda 2 §3.5).

**Os testes da regra, e onde cada um mora:**
  1. `test_wallet_nao_importa_bank`        — aqui (parte b, direção proibida)
  2. `test_bank_nao_referencia_transaction`— aqui (parte b, mais estrito que o design de propósito)
  3. `test_bank_balance_ignora_wallet`     — aqui (parte a, plano 1 → plano 3)
  4. `test_wallet_summary_ignora_bank`     — aqui (parte a, plano 3 → plano 1)
  5. `test_projecao_declara_origem_do_saldo_inicial` — **NÃO está aqui**: é da Story 8.1 e vive em
     `tests/test_financial_intelligence_projection.py` (parte c). Duplicá-lo criaria dois testes de
     mesmo nome em arquivos diferentes; este comentário existe para o leitor achar o quinto.
  6. `test_bank_nao_importa_payables`      — aqui (parte d, Story 8.9)
  7. `test_sources_particionam_o_vocabulario` — aqui (Story 8.9: os dois conjuntos de `source`)
  8. `test_origin_type_e_payment_route_nao_existem` — aqui (Story 8.9: o D-3 pela terceira vez)
"""
from __future__ import annotations

import ast
import pathlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.bank import service as bank_service
from app.modules.wallet import service as wallet_service
from app.modules.wallet.models import STATUS_AVAILABLE, STATUS_PENDING, Transaction

APP_DIR = pathlib.Path(__file__).resolve().parents[1] / "app"
WALLET_DIR = APP_DIR / "modules" / "wallet"
BANK_DIR = APP_DIR / "modules" / "bank"
MODULES_DIR = APP_DIR / "modules"


# ── Varredura estática (parte b da regra) ─────────────────────────────────────────────────────


def _python_files(directory: pathlib.Path) -> list[pathlib.Path]:
    files = sorted(p for p in directory.rglob("*.py") if "__pycache__" not in p.parts)
    assert files, f"Nenhum .py encontrado em {directory} — teste desatualizado?"
    return files


def _imported_modules(path: pathlib.Path) -> list[str]:
    """Módulos importados por um arquivo, via AST (não por texto).

    AST em vez de `grep` porque prosa em docstring **precisa** poder citar o módulo proibido (esta
    suíte inteira fala de `app.modules.bank` o tempo todo) sem quebrar o teste. Imports RELATIVOS
    são devolvidos com um prefixo `.` para que o chamador os inspecione — o projeto usa imports
    absolutos (Constitution, Artigo VI), então um relativo aqui já é anomalia por si só.

    ⚠️ **O `ImportFrom` devolve o caminho COM o alias apenso** (`app.modules` + `bank` →
    `app.modules.bank`), e essa linha é o que torna o gate auditável. Sem ela,
    `from app.modules import bank` produzia só `"app.modules"` — que não casa com nenhum dos
    prefixos proibidos — e **passava nos dois testes**: o AST não via o `bank`, e o teste por texto
    cru procura a string literal `"app.modules.bank"`, que essa forma de import não contém.
    Verificado por mutação no quality gate do Epic 8 (2026-07-30): com o import evasivo dentro de
    `wallet/service.py`, a suíte inteira ficava verde. O módulo também é devolvido sozinho, para
    que um `import app.modules.bank as x` continue casando pelo prefixo.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = f"{'.' * node.level}{node.module or ''}"
            modules.append(base)
            # `from X import y` também vale como "importou X.y" — é a forma evasiva.
            sep = "" if base.endswith(".") else "."
            modules.extend(f"{base}{sep}{alias.name}" for alias in node.names)
    return modules


def test_wallet_nao_importa_bank():
    """`app.modules.wallet` NUNCA importa `app.modules.bank` (Regra dos Planos §1.3b).

    Este é o teste de maior valor da Story 8.2: é a única defesa **permanente** contra a
    reintrodução do bug original numa forma nova, e custa ~20 linhas.

    **Sem allowlist, e isso é deliberado.** O ponto de contato entre os planos 1 e 3 (o payout da
    Carteira, Onda 6) foi desenhado para viver do lado `bank`, publicando/consumindo `core/events`
    (design §6.6) — logo **não existe** exceção legítima nesta direção. Se uma story futura
    "precisar" de uma, o que ela precisa de verdade é rever o desenho do ponto de contato.
    """
    offenders: list[str] = []
    for path in _python_files(WALLET_DIR):
        for module in _imported_modules(path):
            if module.startswith("app.modules.bank") or module.lstrip(".").startswith("bank"):
                offenders.append(f"{path.relative_to(APP_DIR)} → {module}")

    assert not offenders, (
        "Regra dos Planos §1.3b VIOLADA: app/modules/wallet importa app/modules/bank — a direção "
        f"proibida. Ocorrências: {offenders}. O ponto de contato entre a Carteira (plano 1) e o "
        "banco (plano 3) é o payout da Onda 6, e ele vive do lado `bank`, via core/events. "
        "Importar `bank` de dentro de `wallet` é o caminho por onde o bug que originou o Epic 8 "
        "volta numa forma nova."
    )


def test_wallet_nao_importa_bank_tambem_por_texto_cru():
    """O equivalente literal do `grep -r "from app.modules.bank" app/modules/wallet/` (epic §5).

    Redundante com o teste por AST **de propósito**: se um dia alguém trocar o import por algo que
    o AST não pega (um `importlib.import_module("app.modules.bank")`, um `__import__` montado por
    string), o grep cru ainda pega. Custa duas linhas e cobre a fuga mais óbvia.
    """
    offenders = [
        str(path.relative_to(APP_DIR))
        for path in _python_files(WALLET_DIR)
        if "app.modules.bank" in path.read_text(encoding="utf-8")
    ]
    assert not offenders, (
        f"Menção a `app.modules.bank` dentro de app/modules/wallet: {offenders}. "
        "Ver test_wallet_nao_importa_bank."
    )


def test_bank_nao_referencia_transaction():
    """`app.modules.bank` não referencia `Transaction`/`wallet.models` — **hoje**.

    ⚠️ Este teste é **mais estrito que o design de propósito**. A Regra dos Planos §1.3b *permite*
    `bank → wallet`; o que ela proíbe é o contrário. Mas o ponto de contato da Onda 6 foi desenhado
    via `core/events` (design §6.6) e **não precisa** do modelo da Carteira, então hoje a referência
    correta é: nenhuma. Manter o teste apertado enquanto a resposta certa é "nenhuma" é o que faz
    dele um sinal — um teste que já permite o que ninguém usa não avisa nada quando alguém começar
    a usar.

    Se uma story futura precisar legitimamente do símbolo, ela **atualiza este teste com
    justificativa escrita** (mesmo padrão de allowlist do `test_tenancy_guard.py`) — nunca o apaga.
    """
    offenders: list[str] = []
    for path in _python_files(BANK_DIR):
        for module in _imported_modules(path):
            if module.startswith("app.modules.wallet") or module.lstrip(".").startswith("wallet"):
                offenders.append(f"{path.relative_to(APP_DIR)} → import {module}")
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == "Transaction":
                offenders.append(f"{path.relative_to(APP_DIR)} → símbolo Transaction")
            elif isinstance(node, ast.Attribute) and node.attr == "Transaction":
                offenders.append(f"{path.relative_to(APP_DIR)} → atributo .Transaction")

    assert not offenders, (
        "app/modules/bank passou a referenciar a Carteira (plano 1). Isto NÃO é proibido pelo "
        f"design (§1.3b permite bank → wallet), mas hoje não deveria existir: {offenders}. Se o "
        "uso for legítimo, atualize ESTE teste com a justificativa escrita — não o apague."
    )


# ── Parte (d) da regra — a direção de import de NEGÓCIO → BANCO (Story 8.9, AC10) ─────────────

_NEGOCIO_PROIBIDO = ("app.modules.payables", "app.modules.receivables")


def test_bank_nao_importa_payables():
    """`app.modules.bank` NUNCA importa `payables`/`receivables` — a **asserção positiva** do §1.3d.

    É o gate que a Onda 2 acrescenta, e ele fecha a direção que o design deixou implícita. A partir
    da Story 8.12, `payables`/`receivables` **passam a importar** `app.modules.bank` (é assim que a
    baixa gera o movimento) — e é exatamente esse novo tráfego que torna urgente afirmar a direção
    contrária: sem isso, o primeiro atalho de conveniência (*"o módulo bank só precisa dar uma
    olhadinha na conta a pagar"*) recria um ciclo entre os dois planos.

    ⚠️ **Consequência de projeto que esta story trava:** o aviso pró-ativo da Story 8.11 e qualquer
    leitura de `payables` a partir do módulo `bank` são **proibidos**. Quem precisa cruzar os dois
    lados faz isso **do lado do negócio**.

    ⚠️ **Sem allowlist, e isso é deliberado**, pelo mesmo motivo de `test_wallet_nao_importa_bank`:
    o ponto de contato foi desenhado numa direção só. Se uma story futura "precisar" de uma exceção,
    o que ela precisa de verdade é inverter a chamada.
    """
    offenders: list[str] = []
    for path in _python_files(BANK_DIR):
        for module in _imported_modules(path):
            nu = module.lstrip(".")
            if module.startswith(_NEGOCIO_PROIBIDO) or nu.startswith(("payables", "receivables")):
                offenders.append(f"{path.relative_to(APP_DIR)} → import {module}")

    assert not offenders, (
        "Regra dos Planos §1.3d VIOLADA: app/modules/bank importa payables/receivables — a "
        f"direção proibida. Ocorrências: {offenders}. A dependência é de NEGÓCIO para BANCO, "
        "jamais a volta: `payables`/`receivables` chamam `bank.origin.sync_origin_movement`, e o "
        "módulo `bank` não sabe que eles existem. Quem precisa cruzar os dois lados faz isso do "
        "lado do negócio."
    )


def test_bank_nao_importa_payables_tambem_por_texto_cru():
    """O equivalente literal do `grep -r "app.modules.payables" app/modules/bank/`.

    Redundante com o teste por AST **de propósito**, e a redundância não é simétrica: o AST pega a
    forma evasiva `from app.modules import payables` (que o grep não pega, porque a string literal
    não aparece); o grep pega o que o AST não vê (`importlib.import_module("app.modules.payables")`,
    um `__import__` montado por string). Foi a mutação do re-gate da Onda 1 (TEST-001) que provou
    que **os dois** são necessários — com o import evasivo dentro de `wallet/service.py`, a suíte
    inteira ficava verde.
    """
    offenders: list[str] = []
    for path in _python_files(BANK_DIR):
        texto = path.read_text(encoding="utf-8")
        for proibido in _NEGOCIO_PROIBIDO:
            if proibido in texto:
                offenders.append(f"{path.relative_to(APP_DIR)} → {proibido}")
    assert not offenders, (
        f"Menção a {_NEGOCIO_PROIBIDO} dentro de app/modules/bank: {offenders}. "
        "Ver test_bank_nao_importa_payables."
    )


# ── Story 8.18 — a asserção NOVA: `bank` não importa `investments` ────────────────────────────

_INVESTMENTS_PROIBIDO = "app.modules.investments"


def test_bank_transfers_nao_importa_investments():
    """`app.modules.bank` NUNCA importa `app.modules.investments` (Story 8.18 AC5, IV4).

    **O que esta asserção protege, e por que ela nasce agora.** A Story 8.18 cria `bank_transfers`
    com `kind ∈ {own_transfer, investment_in, investment_out}` — um vocabulário que *soa* como uma
    ponte para o módulo de investimentos e **não é**. `investment_in`/`investment_out` dizem para
    onde o dinheiro do dono foi (uma `bank_account` com `kind='investment'`), não qual produto
    financeiro ele comprou. A faceta de produto — `investment_accounts.bank_account_id`,
    `principal_cents` derivado, `register_yield` — é **Onda 2b**, e é lá que mora **o único backfill
    sobre dado existente de todo o épico**, exposto à armadilha do `FORCE RLS` (a lição da 0046, que
    o SQLite dos testes não pega).

    O corte entre as duas ondas é o mesmo que o design-mãe §3.2 já fez no modelo: **a transferência
    é o dinheiro; a aplicação é o produto financeiro.** Acoplar os dois aqui adiaria o urgente (o
    fluxo de pagamento, 45 contas com saldo derivado R$ 0,00) pelo arriscado.

    ⚠️ **É o gate acima que impede a antecipação, não a boa intenção de quem lê a story.** O atalho
    provável é concreto e tentador: *"já que a transferência sabe que o destino é uma aplicação, ela
    podia atualizar o `principal_cents` da `InvestmentAccount` correspondente"*. Isso derivaria um
    campo hoje digitado (o AC1 da Story 5.6, que **não** é superado por esta story) a partir de um
    caminho sem backfill — e as contas antigas ficariam com um principal que ninguém recalculou.

    **Sem allowlist**, pelo mesmo motivo de `test_wallet_nao_importa_bank`: a ligação foi desenhada
    para acontecer na 2b, do lado de `investments` (que **pode** importar `bank`). Se uma story
    futura "precisar" de uma exceção aqui, o que ela precisa de verdade é inverter a chamada.

    **Mutante que este teste mata** (demonstrado na implementação da 8.18): um
    `from app.modules.investments.models import InvestmentAccount` dentro de
    `app/modules/bank/transfers.py` — inclusive na forma evasiva `from app.modules import
    investments`, que o `_imported_modules` pega pelo caminho com alias apenso.
    """
    offenders: list[str] = []
    for path in _python_files(BANK_DIR):
        for module in _imported_modules(path):
            nu = module.lstrip(".")
            if module.startswith(_INVESTMENTS_PROIBIDO) or nu.startswith("investments"):
                offenders.append(f"{path.relative_to(APP_DIR)} → import {module}")

    assert not offenders, (
        "Story 8.18 AC5 VIOLADO: app/modules/bank importa app/modules/investments. "
        f"Ocorrências: {offenders}. A transferência é GENÉRICA — `kind` é vocabulário do módulo "
        "`bank` e não referencia o produto financeiro. A aplicação (rentabilidade, principal "
        "derivado, `register_yield`) é Onda 2b, e é lá que mora o único backfill do épico. Se a "
        "ligação for legítima, ela se faz do lado de `investments`, que PODE importar `bank`."
    )


def test_bank_nao_importa_investments_tambem_por_texto_cru():
    """O equivalente literal do `grep -r "app.modules.investments" app/modules/bank/`.

    Redundante com o teste por AST **de propósito**, e a redundância não é simétrica — a mesma razão
    escrita em `test_bank_nao_importa_payables_tambem_por_texto_cru`: o AST pega
    `from app.modules import investments`; o grep pega
    `importlib.import_module("app.modules.investments")`. Foi a mutação do re-gate da Onda 1
    (TEST-001) que provou que **os dois** são necessários.
    """
    offenders = [
        str(path.relative_to(APP_DIR))
        for path in _python_files(BANK_DIR)
        if _INVESTMENTS_PROIBIDO in path.read_text(encoding="utf-8")
    ]
    assert not offenders, (
        f"Menção a `{_INVESTMENTS_PROIBIDO}` dentro de app/modules/bank: {offenders}. "
        "Ver test_bank_transfers_nao_importa_investments."
    )


def test_bank_service_nao_nomeia_a_entidade_de_negocio():
    """**Story 8.17 / achado A-2** — o gate que a porta de saída da guarda tinha de sobreviver.

    A Story 8.17 precisa perguntar, de dentro de `create_transaction`, se já existe uma obrigação de
    negócio para o mesmo dinheiro (senão o pagamento contado duas vezes derruba o saldo em dobro, e
    *"a divergência dobrada parece um achado real"*). A primeira forma proposta era um `Protocol`
    devolvendo `Payable | None` — e **essa forma reprovava o próprio gate que ela existia para
    respeitar**: com `Payable` na assinatura, `bank/service.py` precisa do TIPO, e
    `if TYPE_CHECKING: from app.modules.payables.models import Payable` **continua sendo um import
    de `payables` dentro de `bank`**. Foi por isso que a ratificação (§C-5.3) trocou o retorno por
    um DTO do próprio `bank` (`DuplicataCandidato`, com `referencia_id` **opaco**).

    ⚠️ Este teste é mais estrito que os dois acima **de propósito**: eles procuram o caminho de
    import (`app.modules.payables`); este procura o **nome do conceito**, em qualquer posição —
    inclusive em nome de campo de dataclass, em anotação sob `TYPE_CHECKING` e em docstring. É
    deliberado que a prosa deste arquivo não possa citar a entidade: o custo é escrever *"a entidade
    de negócio"* em vez do nome dela, e o ganho é que **não existe forma de reintroduzir a
    dependência que passe daqui**.

    **Mutante que este teste mata:** trocar o retorno do `Protocol` de `DuplicataCandidato | None`
    para `Payable | None` (com ou sem `TYPE_CHECKING`). Verificado por mutação na implementação da
    Story 8.17.

    O vocabulário do outro módulo aparece **só no payload HTTP** (`{"acao": "baixar_payable",
    "payable_id": ...}`), montado pela ROTA a partir do id opaco — por isso o teste é escopado em
    `service.py`, e não no módulo inteiro.
    """
    alvo = BANK_DIR / "service.py"
    texto = alvo.read_text(encoding="utf-8")
    proibidas = [t for t in ("payables", "Payable", "payable_id") if t in texto]
    assert not proibidas, (
        f"app/modules/bank/service.py nomeia a entidade de `payables`: {proibidas}. O contrato da "
        "guarda de contagem dupla é um DTO do próprio `bank` (`DuplicataCandidato`, com "
        "`referencia_id` opaco) justamente para que este arquivo não precise do tipo do outro "
        "módulo — nem em runtime, nem sob TYPE_CHECKING, nem em nome de campo. Quem traduz o id "
        "opaco para o vocabulário de negócio é `bank/router.py`, no payload HTTP. Ver ratificação "
        "§C-5.3 (achado A-2)."
    )


def test_a_guarda_de_contagem_dupla_e_uma_porta_registrada():
    """O outro lado do A-2: a porta **existe** e é ligada por composição (Story 8.17 AC6).

    Sem esta asserção, o teste acima ficaria verde do jeito mais fácil possível — apagando a guarda.
    Um teste de ausência precisa de um teste de presença ao lado, senão ele mede o vazio.
    """
    from app.modules.bank import service as bank

    assert hasattr(bank, "DuplicataCandidato") and hasattr(bank, "DuplicataProbe")
    campos = set(bank.DuplicataCandidato.__dataclass_fields__)
    assert campos == {"referencia_id", "descricao", "valor_cents", "data"}
    # E quem implementa vive do lado do NEGÓCIO, que pode importar `bank` — a direção permitida.
    from app.modules.payables.service import probe_pagamento_duplicado

    assert callable(probe_pagamento_duplicado)


# ── Story 8.9 — o vocabulário de `source` é uma PARTIÇÃO, e o D-3 não ganha uma terceira vida ──


def test_sources_particionam_o_vocabulario():
    """`SOURCES_EXTERNA ∪ SOURCES_SISTEMA == SOURCES`, e a interseção é vazia (AC3).

    Toda regra da Onda 2 é escrita contra os **conjuntos**, nunca contra um valor solto de `source`
    — e é isso que impede a mistura de eixos que existe na coluna desde a 0059 (portas de entrada
    `manual|ofx|csv` convivendo com origens de lançamento) de **infectar** as regras. Um valor novo
    que entrasse em um conjunto e sumisse do outro deixaria uma regra em silêncio: por isso a união
    e a interseção são testadas, e por isso `SOURCES` é **derivada**, nunca uma terceira lista.
    """
    from app.modules.bank.models import SOURCES, SOURCES_EXTERNA, SOURCES_SISTEMA

    assert set(SOURCES_EXTERNA) | set(SOURCES_SISTEMA) == set(SOURCES)
    assert set(SOURCES_EXTERNA) & set(SOURCES_SISTEMA) == set(), (
        "um valor de `source` está nos DOIS conjuntos — a pergunta que eles respondem ('o e1p "
        "conhece o lançamento de negócio desta linha?') deixou de ter resposta única"
    )
    assert len(SOURCES) == len(SOURCES_EXTERNA) + len(SOURCES_SISTEMA) == len(set(SOURCES))
    # E o vocabulário cabe na coluna `String(16)` — `"payable"` (7) e `"charge"` (6) cabem, então
    # a Story 8.9 não precisa de migration de tipo. Um valor novo maior reprova AQUI.
    from app.modules.bank.models import BankTransaction as _BT

    largura = _BT.__table__.c.source.type.length
    grandes = {s: len(s) for s in SOURCES if len(s) > largura}
    assert not grandes, f"valor de `source` maior que VARCHAR({largura}): {grandes}"


def test_origin_type_e_payment_route_nao_existem():
    """**AC8 — teste de AUSÊNCIA.** Nem `origin_type`, nem `payment_route`, em `app/modules/**`.

    Os dois seriam a terceira encarnação do defeito D-3 (dois conceitos, um campo — ou, aqui, um
    conceito, dois campos):

    - `origin_type` — para todo valor de `SOURCES_SISTEMA`, `source` **já responde** *"qual tipo de
      lançamento"*. Um segundo campo dizendo a mesma coisa pode divergir do primeiro;
    - `payment_route` — a rota é **DERIVADA** dos dois ponteiros da `Charge`
      (`"trilho" if transaction_id else "banco"`); um rótulo separado vira a terceira fonte de
      verdade sobre por onde o dinheiro entrou.

    O teste é barato e existe porque a "melhoria" é **óbvia para quem chegar depois** — quem abrir
    `bank_transactions` e vir `source='payable'` sem um tipo explícito vai querer acrescentá-lo.
    """
    offenders: list[str] = []
    for path in sorted(MODULES_DIR.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            nome = None
            if isinstance(node, ast.Name):
                nome = node.id
            elif isinstance(node, ast.Attribute):
                nome = node.attr
            elif isinstance(node, ast.arg):
                nome = node.arg
            elif isinstance(node, ast.keyword):
                nome = node.arg
            if nome in ("origin_type", "payment_route"):
                offenders.append(f"{path.relative_to(APP_DIR)}:{node.lineno} → {nome}")

    assert not offenders, (
        f"`origin_type`/`payment_route` reapareceram: {offenders}. Os dois são o defeito D-3 outra "
        "vez: `source` já diz qual tipo de lançamento originou o movimento, e a rota de pagamento "
        "é derivada de `transaction_id`/`bank_account_id` — nunca rotulada. Ver design Onda 2 "
        "§3.2 e §3.4."
    )


# ── Os planos não se cruzam em RUNTIME (parte a da regra) ─────────────────────────────────────

REGISTER = {
    "legal_name": "Planos Separados ME",
    "document": "11444777000161",
    "slug": "planos",
    "email": "planos@example.com",
    "name": "Petra",
    "password": "uma-senha-bem-grande",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _tenant_id(client: TestClient, headers: dict[str, str]) -> str:
    return client.get("/auth/me", headers=headers).json()["user"]["tenant_id"]


def _bank_account(client: TestClient, headers: dict[str, str], *, opening: int) -> dict:
    resp = client.post(
        "/bank/accounts",
        json={
            "name": "Itaú PJ",
            "kind": "checking",
            "opening_balance_cents": opening,
            "opening_date": "2026-07-01",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_bank_balance_ignora_wallet(client: TestClient, headers, db: Session):
    """Dinheiro que entra na Carteira (plano 1) não muda o saldo bancário (plano 3) em 1 centavo.

    Inclui uma transação `available` — a exata que o bug original somava como se fosse saldo de
    banco.
    """
    account = _bank_account(client, headers, opening=250_000)
    tenant_id = _tenant_id(client, headers)
    antes = client.get(f"/bank/accounts/{account['id']}/balance", headers=headers).json()
    assert antes["saldo_derivado_cents"] == 250_000

    db.add_all(
        [
            Transaction(
                tenant_id=tenant_id, kind="service", method="pix", gross_cents=1_000_000,
                platform_fee_cents=300_000, net_cents=700_000, status=STATUS_AVAILABLE,
            ),
            Transaction(
                tenant_id=tenant_id, kind="product", method="card", gross_cents=500_000,
                platform_fee_cents=200_000, net_cents=300_000, status=STATUS_PENDING,
            ),
        ]
    )
    db.commit()
    assert wallet_service.wallet_summary(db)["available_cents"] == 700_000, (
        "pré-condição do teste falhou: a Carteira deveria ter recebido o dinheiro"
    )

    depois = client.get(f"/bank/accounts/{account['id']}/balance", headers=headers).json()
    assert depois["saldo_derivado_cents"] == 250_000, (
        "Regra dos Planos §1.3a VIOLADA: o saldo bancário se moveu por causa de uma venda na "
        "Carteira. O saldo do plano 3 é `opening_balance_cents + SUM(bank_transactions)` e nada "
        "mais — `transactions` não entra nessa conta em hipótese nenhuma."
    )
    assert depois == antes
    # E pelo service, sem passar pela camada HTTP (o cálculo é que precisa estar limpo).
    assert bank_service.derived_balance(db, bank_account_id=account["id"]) == 250_000


def test_wallet_summary_ignora_bank(client: TestClient, headers, db: Session):
    """O recíproco: cadastrar conta bancária com saldo alto não move a Carteira em 1 centavo."""
    tenant_id = _tenant_id(client, headers)
    db.add(
        Transaction(
            tenant_id=tenant_id, kind="service", method="pix", gross_cents=100_000,
            platform_fee_cents=30_000, net_cents=70_000, status=STATUS_AVAILABLE,
        )
    )
    db.commit()
    antes = wallet_service.wallet_summary(db)

    _bank_account(client, headers, opening=99_999_999)

    depois = wallet_service.wallet_summary(db)
    assert depois == antes, (
        "Regra dos Planos §1.3a VIOLADA: o resumo da Carteira mudou depois de cadastrar uma conta "
        f"bancária. antes={antes} depois={depois}"
    )
    # Campo a campo, para que a mensagem diga QUAL campo vazou se um dia falhar.
    for field in ("available_cents", "pending_cents", "withdrawn_cents", "gross_total_cents",
                  "fees_total_cents"):
        assert depois[field] == antes[field], f"campo contaminado pelo plano 3: {field}"


def test_saldos_dos_dois_planos_nao_ocupam_o_mesmo_campo(client: TestClient, headers):
    """Parte (a), fim da frase: as duas somas nunca ocupam o mesmo campo numérico.

    A Carteira devolve `available_cents` (sem `*_origem`, porque nunca foi ambígua: é o plano 1 por
    definição); o banco devolve `saldo_derivado_cents` **com** `saldo_derivado_origem='banco'`. São
    nomes diferentes com procedência declarada — é isso que impede o `saldo_inicial` da Projeção de
    voltar a receber o número errado sem ninguém perceber.
    """
    from app.core.money_planes import ORIGEM_BANCO, ORIGENS

    account = _bank_account(client, headers, opening=1_234)
    assert account["saldo_derivado_origem"] == ORIGEM_BANCO
    assert account["saldo_derivado_origem"] in ORIGENS
    assert "available_cents" not in account
    assert "saldo_derivado_cents" not in client.get("/wallet/summary", headers=headers).json()
