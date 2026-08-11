import logging
from datetime import date

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.config import settings
from app.modules import ALL_ROUTERS
from app.modules.bank import payout as bank_payout
from app.modules.bank import reconciliation as bank_reconciliation
from app.modules.bank import service as bank_service
from app.modules.funnels.automation import register as register_funnel_automation
from app.modules.notifications.service import register as register_notifications
from app.modules.payables import service as payables_service
from app.modules.payables.service import probe_pagamento_duplicado
from app.modules.receivables import service as receivables_service
from app.modules.wallet import service as wallet_service


class PublicLeadsCORSMiddleware:
    """CORS aberto (qualquer origem) só para `POST /public/leads/*`.

    O `CORSMiddleware` global (abaixo) fica travado em `frontend_url` + `allow_credentials=True`
    — é o que protege a API autenticada. Mas o site externo de um cliente (ex.: doroeventos.com.br)
    precisa chamar essa rota via `fetch`/`<form>` de QUALQUER origem, sem cookie/credencial
    nenhuma. Em vez de afrouxar o middleware global (enfraqueceria tudo), este middleware ASGI
    puro fica ANTES dele na pilha (adicionado depois = mais externo, ver ordem do Starlette) e
    intercepta só esse prefixo: responde o preflight OPTIONS direto e injeta
    `Access-Control-Allow-Origin` na resposta real, sem tocar em mais nada.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/public/leads"):
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        origin = headers.get(b"origin", b"*")

        if scope["method"] == "OPTIONS":
            await send({
                "type": "http.response.start",
                "status": 204,
                "headers": [
                    (b"access-control-allow-origin", origin),
                    (b"access-control-allow-methods", b"POST, OPTIONS"),
                    (b"access-control-allow-headers", b"content-type"),
                    (b"access-control-max-age", b"600"),
                ],
            })
            await send({"type": "http.response.body", "body": b""})
            return

        async def _send(message):
            if message["type"] == "http.response.start":
                message["headers"] = [
                    *message.get("headers", []),
                    (b"access-control-allow-origin", origin),
                ]
            await send(message)

        await self.app(scope, receive, _send)

# Sem isto, o root logger fica sem handler (só o "lastResort" do Python, WARNING+ pra stderr) —
# logger.info/exception de core/email.py, core/whatsapp.py, core/payment_gateway.py etc. nunca
# aparecem em `docker logs`. Mesmo padrão já usado em app/worker.py.
logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="e1p API",
    description="Backend multi-tenant da plataforma e1p (Empresa de 1 Pessoa)",
    version="0.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Adicionado DEPOIS do CORSMiddleware global → fica MAIS EXTERNO na pilha (Starlette prepende
# a cada add_middleware), então intercepta /public/leads/* antes da política travada acima.
app.add_middleware(PublicLeadsCORSMiddleware)

# Módulos de negócio (vão sendo registrados conforme construídos — ver app/modules/__init__.py)
for router in ALL_ROUTERS:
    app.include_router(router)

# Liga os assinantes do barramento de eventos (ex.: WhatsApp ao mover card no CRM;
# auto-enroll no funil de vendas padrão ao criar lead).
register_notifications()
register_funnel_automation()


# ── A composição da guarda de contagem dupla (Story 8.17 AC6) ────────────────────────────────
#
# ⚠️ **Este é o ÚNICO lugar onde `bank` e `payables` se encontram nesta direção — e é de propósito.**
# O gate estrutural da Story 8.9 (`tests/test_money_planes.py`) proíbe `bank` de importar
# `payables`; `bank` declara o `Protocol` e o registrador, `payables` implementa, e a fiação é feita
# **aqui**, na composição. Direção final: `main → bank`, `main → payables`, `payables → bank`.
# O gate fica verde **porque a dependência sumiu**, não porque foi escondida. Ver
# `bank/service.py`, bloco "A porta de saída da guarda de contagem dupla".
def liga_a_guarda_de_contagem_dupla() -> None:
    bank_service.register_duplicata_probe(probe_pagamento_duplicado)


def verifica_fiacao_da_guarda() -> None:
    """**FAIL-CLOSED NO BOOT: a aplicação não sobe sem o probe registrado** (ratificação §C-5.2).

    *"Um erro de fiação é condição de startup, não de request."* A alternativa — deixar o request
    seguir sem validar — seria a guarda **desligada em produção sem ninguém saber**, e a
    consequência é o pior modo de falha da onda (o pagamento contado duas vezes, com a divergência
    dobrada parecendo um achado real). A outra alternativa, o 500 no request, descobriria o
    problema no pior lugar imaginável: uma ação legítima do dono lançando uma tarifa de R$ 2,90.

    Precedente do próprio projeto: a guarda de boot contra `JWT_SECRET` fraco em produção
    (`CLAUDE.md` §6.1). A checagem de request-time **fica** como segunda guarda
    (`bank/service._probe_duplicata`), inalcançável se esta funcionar.

    ⚠️ **Não transforme isto num `warning`.** O teste que amarra o comportamento é
    `test_bank_contagem_dupla.py::test_app_nao_sobe_sem_o_probe_de_contagem_dupla`, e há um teste
    ESTRUTURAL provando que esta função é chamada no nível do módulo — apagar a chamada abaixo
    reprova, porque um fail-closed que ninguém invoca é um comentário.
    """
    if not bank_service.duplicata_probe_registrado():
        raise RuntimeError(
            "A guarda de contagem dupla não foi ligada: `bank.service.register_duplicata_probe` "
            "não recebeu implementação. A aplicação NÃO sobe sem ela — sem essa consulta, um "
            "pagamento lançado à mão e também baixado em Contas a Pagar derrubaria o saldo duas "
            "vezes, em silêncio. Verifique `liga_a_guarda_de_contagem_dupla` em app/main.py."
        )


liga_a_guarda_de_contagem_dupla()
verifica_fiacao_da_guarda()


# ── A composição dos termos da pré-condição do gate (Story 8.16 AC7/AC8) ─────────────────────
#
# ⚠️ **Mesmo motivo e mesma forma da guarda acima.** A conferência (`bank/reconciliation.py`)
# precisa CONTAR obrigações de negócio para poder anotar *"N lançamentos deste período não informam
# de qual conta saíram"* — e o gate estrutural da Story 8.9 proíbe `bank` de importar os módulos de
# negócio. `bank` declara o `Protocol` e o registrador; os módulos de negócio implementam as
# contagens; a fiação é feita **aqui**. Direção final: `main → bank`, `main → negócio`,
# `negócio → bank`.
#
# **Esta função é a ÚNICA que soma P1 com P2**, e a soma é deliberada: os dois termos fecham na
# MESMA onda (a 2) e pedem a MESMA ação do dono, então uma frase só os cobre. **P3 continua
# separado** porque fecha na Onda 2b — outro prazo, outra frase. **P4 não é contado**: desde a
# Onda 3 a população é vazia por construção — `request_payout` recusa sem conta principal (409) e
# `bank/payout.py` escreve a perna bancária na mesma transação —, e alcançá-la exigiria cruzar o
# plano da plataforma com o plano do banco, que é a mistura que produziu o bug de origem.
# ⚠️ A frase anterior aqui era *"o payout ainda não move dinheiro de conta real"*, e ela descrevia o
# `request_payout` de ANTES da Onda 3: ficou falsa no merge dela. A vacuidade de P4 vale **só a
# partir do deploy** — quem decide isso é `bank.reconciliation.PRIMEIRO_CICLO_MEDIVEL`.
def probe_termos_do_gate(
    db: Session, *, start: date, end: date
) -> bank_reconciliation.TermosDoGate:
    p1_qtd, p1_valor = payables_service.contar_saidas_sem_conta_informada(db, start=start, end=end)
    p2_qtd, p2_valor = receivables_service.contar_entradas_sem_conta_informada(
        db, start=start, end=end
    )
    p3_qtd, p3_valor = receivables_service.contar_rendimentos_sem_perna_bancaria(
        db, start=start, end=end
    )
    return bank_reconciliation.TermosDoGate(
        lancamentos_sem_conta_informada=p1_qtd + p2_qtd,
        valor_sem_conta_informada_cents=p1_valor + p2_valor,
        rendimentos_sem_perna_bancaria=p3_qtd,
        valor_rendimentos_sem_perna_cents=p3_valor,
    )


def liga_os_termos_do_gate() -> None:
    bank_reconciliation.register_termos_do_gate_probe(probe_termos_do_gate)


def verifica_fiacao_dos_termos_do_gate() -> None:
    """**FAIL-CLOSED NO BOOT** — a aplicação não sobe sem a contagem dos termos ligada.

    Pelo mesmo princípio da guarda de contagem dupla (*"um erro de fiação é condição de startup, não
    de request"*) e por um motivo próprio, mais caro: sem a contagem, as notas do bloco 4 **somem em
    silêncio** e a conferência passa a dizer, por omissão, *"nenhum termo pendente"*. Zero por
    ausência de medição não é zero — e ler a divergência sob essa premissa falsa é exatamente o erro
    que custou uma decisão de produto neste épico (a divergência medindo a própria incompletude do
    sistema, e pedindo a construção da onda mais cara).
    """
    if not bank_reconciliation.termos_do_gate_probe_registrado():
        raise RuntimeError(
            "A contagem dos termos da pré-condição do gate não foi ligada: "
            "`bank.reconciliation.register_termos_do_gate_probe` não recebeu implementação. A "
            "aplicação NÃO sobe sem ela — sem essa contagem, a conferência devolveria um relatório "
            "sem as notas do bloco 4 e o gate pareceria pronto para ser lido quando não está. "
            "Verifique `liga_os_termos_do_gate` em app/main.py."
        )


liga_os_termos_do_gate()
verifica_fiacao_dos_termos_do_gate()


# ── A composição do ponto de contato entre os PLANOS de dinheiro (Epic 8, Onda 3) ─────────────
#
# ⚠️ **Terceira aplicação do mesmo padrão, e a primeira que atravessa a fronteira dos planos**
# (design-mãe §1.2: o payout é o único write que a cruza). As duas irmãs acima ligam `bank` a
# módulos de negócio; esta liga a Carteira ao banco — a direção em que o Epic 8 nasceu de um bug.
#
# Aqui a declaração é do lado da CARTEIRA (`wallet/service.RegistradorDePayout`) e a implementação
# do lado do BANCO (`bank/payout.registra_payout`). Direção final: `main → wallet`, `main → bank`,
# e **nada** entre os dois. Os dois gates (`test_wallet_nao_importa_bank`,
# `test_bank_nao_referencia_transaction`) continuam apertados **e sem allowlist** — a dependência
# não existe, em vez de existir com permissão.
def liga_o_registrador_de_payout() -> None:
    wallet_service.register_payout_registrar(bank_payout.registra_payout)


def verifica_fiacao_do_payout() -> None:
    """**FAIL-CLOSED NO BOOT: a aplicação não sobe sem o registrador de payout.**

    *"Um erro de fiação é condição de startup, não de request."* Sem esta guarda o modo de falha é
    silencioso e caro: o saque voltaria a ser troca de status sem perna bancária, o termo **P4** da
    pré-condição do gate reabriria, e `|divergencia_cents|` — a métrica que decide se as Ondas 4
    (import OFX) e 5 (matcher) valem o custo — voltaria a medir a própria incompletude do sistema
    sem que ninguém percebesse.

    ⚠️ **Não transforme isto num `warning`.** O par de testes que amarra o comportamento é
    `test_payout_registrar.py::test_app_nao_sobe_sem_o_registrador_de_payout` **e** o teste
    ESTRUTURAL que prova que esta função é chamada no nível do módulo — apagar a chamada abaixo
    reprova, porque um fail-closed que ninguém invoca é um comentário.
    """
    if not wallet_service.payout_registrar_registrado():
        raise RuntimeError(
            "O registrador de payout não foi ligado: `wallet.service.register_payout_registrar` "
            "não recebeu implementação. A aplicação NÃO sobe sem ele — sem essa ligação o saque da "
            "Carteira volta a não escrever movimento bancário nenhum, reabrindo o termo P4 do gate "
            "do Epic 8 em silêncio. Verifique `liga_o_registrador_de_payout` em app/main.py."
        )


liga_o_registrador_de_payout()
verifica_fiacao_do_payout()


@app.get("/health", tags=["infra"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": "e1p-api", "env": settings.environment}
