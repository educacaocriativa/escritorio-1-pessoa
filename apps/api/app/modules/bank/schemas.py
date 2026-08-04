"""Schemas da conta (8.2), do movimento (8.3) e do saldo declarado (8.4) — módulo bancário.

**Nenhum saldo trafega sem procedência** (Regra dos Planos §1.3c): todo campo que carrega saldo tem
um irmão `*_origem` preenchido com uma constante de `app.core.money_planes` — nunca uma string
literal solta. Aqui a origem é sempre `ORIGEM_BANCO`, porque o número vem do plano 3.

⚠️ `BankTransactionOut.amount_cents` **não** é um saldo e por isso não tem `*_origem`: é o valor de
UM movimento, não o resultado de uma soma. A regra §1.3c fala de campos que carregam saldo — quem
carrega saldo neste módulo é `saldo_derivado_cents` (8.2) e `balance_cents` (8.4), e os dois
declaram.

### Os DOIS eixos de procedência, e como eles aparecem aqui (design §1.3.1)

- **Eixo A — plano** (`*_origem`, `app.core.money_planes`): *"de qual PLANO de dinheiro este número
  vem?"* → `plataforma|banco|misto|indisponivel`. **Obrigatório em todo campo de saldo.**
  `BankAccountOut.saldo_derivado_origem` e `CheckpointOut.balance_origem` são ambos `ORIGEM_BANCO`,
  e é justamente por isso que os dois números são **comparáveis** na Story 8.5: o saldo que o
  sistema calculou e o saldo que o banco atesta são o mesmo plano visto por dois caminhos.
- **Eixo B — porta de entrada** (`*_fonte`, `app.modules.bank.models.ORIGINS`): *"por qual PORTA
  este saldo EXTERNO entrou no e1p?"* → `manual|ofx`. Obrigatório **só** em saldo atestado por
  terceiro, que hoje é exclusivamente o checkpoint — o saldo derivado não tem eixo B porque não
  entrou por porta nenhuma: ele é calculado aqui dentro. Em `CheckpointOut` o eixo B é o campo
  `origin` (mesmo nome da coluna, AC8); a Story 8.5 o lê **direto**, sem traduzir, no campo
  `saldo_banco_fonte` do relatório dela. Um segundo campo `balance_fonte` espelhando `origin` no
  mesmo payload seria duas fontes para o mesmo valor — exatamente o que este épico combinou evitar.
"""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator

from app.core.money_planes import ORIGEM_BANCO
from app.core.validators import validate_document
from app.modules.bank.models import ORIGIN_MANUAL


def _digits_or_empty(v: str | None) -> str | None:
    """CPF/CNPJ do TITULAR — opcional. Normaliza para só-dígitos e valida quando informado.

    ⚠️ **DESVIO DOCUMENTADO da Task 5 da story 8.2** (registrado no Dev Agent Record). A story
    mandava validar *"só tamanho/normalização de dígitos, sem dígito verificador"*, com a
    justificativa de que o DV é *"a dívida global já registrada no `CLAUDE.md` §6.1"* e que
    resolvê-la aqui *"criaria inconsistência com o resto do produto"*. **A premissa está
    desatualizada:** `app/core/validators.py` já implementa CPF/CNPJ com dígito verificador e é
    usado por `auth`, `crm`, `contracts` e `platform` — validar só o tamanho aqui produziria
    exatamente a inconsistência que a instrução queria evitar. Seguimos o padrão real do projeto
    (mesmo formato opcional de `crm.schemas.ClientCreate.document`); a nota do `CLAUDE.md` §6.1 é
    que está velha, e corrigi-la é fora do escopo desta story.
    """
    if v is None or not v.strip():
        return ""
    return validate_document(v)


def _strip(v: str | None) -> str | None:
    return v.strip() if v is not None else None


class BankAccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    # Validado contra `models.KINDS` no SERVICE (não aqui): `platform_wallet` precisa de uma
    # mensagem de 422 PRÓPRIA, explicando a Regra dos Planos, e não do erro genérico do Pydantic.
    kind: str = Field(max_length=16)
    institution: str = Field(default="", max_length=120)
    institution_code: str = Field(default="", max_length=8)
    branch: str = Field(default="", max_length=16)
    number: str = Field(default="", max_length=32)
    holder_document: str = Field(default="", max_length=20)
    pix_key: str = Field(default="", max_length=140)
    # PODE ser negativo: conta no limite / cheque especial é saldo de partida legítimo.
    opening_balance_cents: int = 0
    opening_date: date

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("nome não pode ser vazio")
        return v

    @field_validator("institution", "institution_code", "branch", "number", "pix_key", "kind")
    @classmethod
    def _text(cls, v: str) -> str:
        return v.strip()

    @field_validator("holder_document")
    @classmethod
    def _holder_document(cls, v: str) -> str:
        return _digits_or_empty(v) or ""


class BankAccountUpdate(BaseModel):
    """Edição parcial — `None` significa "não altera" em todos os campos.

    `archived_at` **não** é editável por aqui (AC2): arquivar é uma operação própria
    (`POST /bank/accounts/{id}/archive`), com auditoria, e desarquivar não existe de propósito.
    """

    name: str | None = Field(default=None, min_length=1, max_length=120)
    kind: str | None = Field(default=None, max_length=16)
    institution: str | None = Field(default=None, max_length=120)
    institution_code: str | None = Field(default=None, max_length=8)
    branch: str | None = Field(default=None, max_length=16)
    number: str | None = Field(default=None, max_length=32)
    holder_document: str | None = Field(default=None, max_length=20)
    pix_key: str | None = Field(default=None, max_length=140)
    opening_balance_cents: int | None = None
    opening_date: date | None = None
    is_primary: bool | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("nome não pode ser vazio")
        return v

    @field_validator("institution", "institution_code", "branch", "number", "pix_key", "kind")
    @classmethod
    def _text(cls, v: str | None) -> str | None:
        return _strip(v)

    @field_validator("holder_document")
    @classmethod
    def _holder_document(cls, v: str | None) -> str | None:
        return _digits_or_empty(v)


class BankAccountOut(BaseModel):
    id: str
    name: str
    kind: str
    institution: str
    institution_code: str
    branch: str
    number: str
    holder_document: str
    pix_key: str
    opening_balance_cents: int
    opening_date: date
    is_primary: bool
    archived_at: datetime | None
    # Saldo DERIVADO (design §3.1) — não existe coluna de saldo; este número é calculado a cada
    # leitura por `service.derived_balance`: `opening_balance_cents` + Σ dos movimentos posteriores
    # à data de abertura que não estejam ignorados (Story 8.3).
    saldo_derivado_cents: int
    # Procedência OBRIGATÓRIA do saldo acima (Regra dos Planos §1.3c). Sempre `ORIGEM_BANCO`: este
    # número vem do plano 3, jamais da Carteira.
    saldo_derivado_origem: str = ORIGEM_BANCO
    # ── O que já tem dia marcado e ainda não aconteceu (Story 8.14, AC13) ────────────────────
    #
    # Σ dos movimentos desta conta com `posted_at > hoje`, separada por sinal e em **MÓDULO** nos
    # dois campos. Vem de `service.agendado_sums`, que reusa `_movements_sums` com o recorte de
    # data invertido — **não existe uma segunda fórmula de soma** (`CLAUDE.md` Regra 4).
    #
    # ⚠️ **É o COMPLEMENTO EXATO de `saldo_derivado_cents`**, não uma parcela dele: aquele soma
    # `posted_at <= hoje`, este soma `posted_at > hoje`. Nenhum movimento entra nos dois, nenhum
    # fica de fora dos dois. **Nunca some os dois campos num total** sem dizer, na tela, que o
    # resultado é "o saldo depois que tudo o que já foi agendado acontecer" — que é uma terceira
    # afirmação, e afirmação de saldo sem rótulo próprio é a divergência D-6 outra vez.
    #
    # `agendado_entrada_cents` é **estruturalmente zero até a Story 8.15**: nada no e1p produz
    # movimento de ENTRADA com data futura hoje. Ele nasce aqui mesmo assim porque o par simétrico
    # é o contrato que a 8.15 consome — e um campo que aparece junto do irmão não obriga a UI a
    # mudar de forma quando o valor deixar de ser zero.
    agendado_saida_cents: int = 0
    agendado_entrada_cents: int = 0
    # Irmão de procedência dos DOIS números acima (Regra dos Planos §1.3c / `CLAUDE.md` Regra 3).
    # Um só para os dois porque os dois vêm da mesma soma, do mesmo plano: dois campos idênticos
    # seriam duas fontes para a mesma informação. Sempre `ORIGEM_BANCO`.
    agendado_origem: str = ORIGEM_BANCO
    created_at: datetime


class BankBalanceOut(BaseModel):
    """Resposta de `GET /bank/accounts/{id}/balance`.

    `until` é a data de corte **efetivamente usada** (inclusiva), devolvida no payload porque a
    Story 8.5 compara saldos **na mesma data** e um saldo sem a data em que foi apurado é um número
    que não dá para conferir.

    ⚠️ **Desde a Story 8.10 este campo nunca vem `null` nesta rota.** Antes, chamar sem `?until=`
    significava "todo o histórico" e o payload vinha com `until: null` — ou seja, o campo se
    calava justamente na chamada mais comum. Agora o default é **hoje** e a rota devolve a data
    que usou, sempre.

    **O tipo continua `date | None` de propósito.** Não é frouxidão: é que o `None` deixou de ser
    alcançável *por esta rota*, não do vocabulário do schema — apertar para `date` transformaria
    uma decisão de rota num contrato de tipo, e o dia em que alguma superfície precisar dizer
    honestamente "não houve corte" (`SEM_CORTE`) a mudança voltaria como quebra de contrato. Quem
    garante o invariante é o teste, não o tipo: ver `test_bank_corte_de_data.py`.
    """

    saldo_derivado_cents: int
    saldo_derivado_origem: str = ORIGEM_BANCO
    until: date | None


# ── Movimento bancário (Story 8.3) ───────────────────────────────────────────────────────────


class BankTransactionCreate(BaseModel):
    """Lançamento MANUAL de um movimento. A conta vem do PATH, nunca do corpo.

    `source` **não** existe aqui de propósito (AC6): quem escolhe a origem da linha é o caminho de
    código (`SOURCE_MANUAL`, fixado no service), nunca o cliente. Se o payload pudesse dizer
    `source='ofx'`, a coluna deixaria de significar "de onde este dado veio" — e é ela que a
    auditoria usa para separar o que o banco disse do que o usuário digitou.

    `description` alimenta `raw_description`, que é **imutável** a partir daí (invariante (c) do
    modelo). Toda edição posterior vai em `user_description`.
    """

    posted_at: date
    # COM SINAL: + entrada, − saída. `0` é recusado com 422 no service (invariante (b) do modelo).
    amount_cents: int
    # Vira `raw_description` (TEXT, sem limite de tamanho no banco) e congela.
    description: str = Field(default="")
    # Contraparte informável à mão (§7). Os demais campos de contraparte (`pix_end_to_end_id`,
    # `fiscal_document_ref`) só são preenchidos por importação/conciliação e não entram aqui.
    counterparty_name: str = Field(default="", max_length=160)
    counterparty_document: str = Field(default="", max_length=20)
    # *"Para que serve este movimento?"* — RÓTULO, nunca fato de dinheiro (Story 8.17 AC9).
    #
    # ⚠️ **Validado por TAMANHO, jamais contra a lista** (AC3): `models.OPERATION_NATURES` é
    # vocabulário **sugerido na UI**, e o texto livre de *"Outro (descreva)"* precisa passar. Um
    # `Literal[...]`/`Enum` aqui recusaria o fato bancário legítimo que ninguém imaginou (estorno de
    # tarifa, crédito de convênio, cashback) e recriaria a incompletude que a onda combate. Não
    # afrouxe o `max_length` também: a coluna é `String(24)`.
    operation_nature: str | None = Field(default=None, max_length=24)
    # ⚠️ **NÃO É PERSISTIDO — e não deve passar a ser** (Story 8.17 AC5). É a resposta do usuário à
    # pergunta do 409 (*"é outro pagamento mesmo"*), ou seja, uma confirmação de **intenção**; um
    # fato sobre o movimento é outra coisa, e gravá-lo criaria uma coluna que descreve o diálogo em
    # vez do dinheiro. `create_transaction` lê o campo e o descarta — não existe coluna equivalente
    # em `BankTransaction`, e o `BankTransactionOut` não o devolve.
    #
    # Fluxo: 1º POST → 409 com as duas escolhas → o usuário escolhe *"é outro pagamento"* → o mesmo
    # POST volta com `confirmar_avulso=true` e passa. Repetir é o mecanismo, de propósito: nada é
    # pré-selecionado para ele, e o formulário não é perdido no caminho (AC8).
    confirmar_avulso: bool = Field(default=False)

    @field_validator("description", "counterparty_name")
    @classmethod
    def _text(cls, v: str) -> str:
        return v.strip()

    @field_validator("operation_nature")
    @classmethod
    def _nature(cls, v: str | None) -> str | None:
        return _strip(v) or None

    @field_validator("counterparty_document")
    @classmethod
    def _counterparty_document(cls, v: str) -> str:
        """Mesma validação de `holder_document` (dígito verificador, via `core/validators`).

        ⚠️ **A Onda 3 NÃO deve reusar esta validação para dado importado.** Aqui o documento é
        digitado por quem está olhando para o comprovante e um erro de digitação vale um 422; num
        arquivo do banco, um CPF malformado é o que o banco mandou — recusar a linha por causa dele
        perderia a evidência, que é justo o que a importação existe para preservar.
        """
        return _digits_or_empty(v) or ""


class BankTransactionUpdate(BaseModel):
    """Edição parcial — `None` significa "não altera".

    **Três campos, e mais nada** (AC4/AC6). Ausentes de propósito, com guarda redundante no service
    para o caso de alguém acrescentá-los aqui sem ler:
    - `raw_description`: imutável, é a prova documental (invariante (c) do modelo);
    - `source`, `dedup_hash`, `fitid`: descrevem a PROCEDÊNCIA da linha, que o usuário não escolhe;
    - `status`: só `ignore`/`unignore` a escrevem nesta onda (invariante (d) do modelo).

    Um movimento `ignored` **pode** ser editado: corrigir e depois reativar é o caminho normal.
    """

    posted_at: date | None = None
    amount_cents: int | None = None
    user_description: str | None = None

    @field_validator("user_description")
    @classmethod
    def _user_description(cls, v: str | None) -> str | None:
        return _strip(v)


class IgnoreRequest(BaseModel):
    """Corpo de `POST /bank/transactions/{id}/ignore`. `reason` é opcional."""

    reason: str = Field(default="", max_length=120)

    @field_validator("reason")
    @classmethod
    def _reason(cls, v: str) -> str:
        return v.strip()


class BankTransactionOut(BaseModel):
    """Movimento como a API o devolve.

    `description` é a **derivação pronta** `user_description or raw_description` — entregue além
    dos dois campos crus para que a UI (Story 8.7) não reimplemente a regra e as duas
    implementações não divirjam depois (Dev Notes da 8.3).

    **Colunas da tabela que NÃO entram neste contrato agora**, e por quê: `fitid`, `dedup_hash`,
    `balance_after_cents`, `import_batch_id` e `transfer_id` são criadas pela migration desta story
    porque a Onda 3/4 depende delas (design §7.3), mas nesta onda **nenhum caminho de código as
    escreve** e nenhum consumidor as lê — são NULL/derivadas por construção. Quem passar a
    populá-las define o contrato de saída delas, com uma pergunta a mais no caso de
    `balance_after_cents`: por carregar um saldo (o que o banco reportou após o movimento), ela
    precisa nascer com o irmão `*_origem` da Regra dos Planos §1.3c. Expor um campo de saldo agora,
    sempre nulo e sem procedência, seria justamente o contra-exemplo que essa regra procura.
    """

    id: str
    bank_account_id: str
    posted_at: date
    # COM SINAL (+ entrada / − saída). NÃO é saldo — ver a nota no topo do módulo.
    amount_cents: int
    # O que o banco/usuário disse, congelado. Nunca muda depois da criação.
    raw_description: str
    # O rótulo editável.
    user_description: str
    # `user_description or raw_description` — a regra de exibição, já resolvida.
    description: str
    counterparty_name: str
    counterparty_document: str
    operation_nature: str | None
    # Sempre `manual` nesta onda; existe no contrato porque a UI da 8.7 precisa distinguir o que foi
    # digitado do que veio de arquivo assim que a Onda 3 existir.
    source: str
    status: str
    ignored_reason: str
    created_at: datetime
    updated_at: datetime


# ── Saldo declarado / checkpoint (Story 8.4) ─────────────────────────────────────────────────


class CheckpointCreate(BaseModel):
    """*"O saldo desta conta, no FIM deste dia, era X."* A conta vem do PATH, nunca do corpo.

    `origin` **existe** no corpo (ao contrário de `BankTransactionCreate.source`, que é fixado no
    service) porque o vocabulário do eixo B é aberto ao cliente por desenho: na Onda 3 a mesma
    escrita virá do caminho de importação com `origin='ofx'`. Nesta onda o service recusa qualquer
    valor diferente de `manual` com 422 (AC3), e a validação mora lá — e não num `Literal` do
    Pydantic — para que a mensagem possa explicar **por que** `ofx` ainda não é aceito, em vez de
    devolver o erro genérico de enum.

    `balance_cents` PODE ser negativo: conta no limite / cheque especial é um saldo legítimo, e
    recusá-lo forçaria o usuário a mentir o número que ele está olhando na tela do banco.
    """

    reference_date: date
    balance_cents: int
    origin: str = Field(default=ORIGIN_MANUAL, max_length=12)

    @field_validator("origin")
    @classmethod
    def _origin(cls, v: str) -> str:
        return v.strip()


class CheckpointOut(BaseModel):
    """O saldo declarado como a API o devolve.

    ⚠️ **NÃO expõe o saldo do sistema nem a divergência**, de propósito. Comparar os dois é a Story
    8.5, num serviço read-only próprio, com a banda de tolerância e a decomposição por conta que o
    epic §3.2 exige. Se a divergência nascesse aqui também, existiriam duas implementações do mesmo
    número — e a daqui nasceria **sem** a banda e **sem** a decomposição, que é a forma de um
    consolidado saudável esconder duas contas com problema.

    **Colunas da tabela fora deste contrato:** `import_batch_id` é criada pela migration desta story
    porque a Onda 3 depende dela (design §7.3), mas nesta onda nenhum caminho de código a escreve —
    é NULL por construção. Quem passar a populá-la define o contrato de saída dela.
    """

    id: str
    bank_account_id: str
    # Data de calendário. É o **fim** deste dia — a mesma janela de `derived_balance(until=...)`.
    reference_date: date
    # O saldo que o banco atesta. Centavos, pode ser negativo.
    balance_cents: int
    # Eixo A (plano) do saldo acima — OBRIGATÓRIO pela Regra dos Planos §1.3c. Constante
    # `ORIGEM_BANCO`: o número que o usuário leu no app do banco é o plano 3, sempre. Nunca
    # `indisponivel` — se este objeto existe, o número existe; "não sei" é a AUSÊNCIA de checkpoint
    # (`latest_checkpoint` → `None`), e quem traduz essa ausência em `ORIGEM_INDISPONIVEL` é o
    # relatório da 8.5, não este contrato.
    balance_origem: str = ORIGEM_BANCO
    # Eixo B (porta de entrada) do MESMO saldo: `manual` nesta onda, `ofx` na Onda 3. Ver a nota
    # sobre os dois eixos no topo deste módulo — os eixos não se traduzem um no outro.
    origin: str
    created_by: str | None
    created_at: datetime


# ── Conferência, bloco 1 (Story 8.5) ─────────────────────────────────────────────────────────
#
# Espelho 1:1 das dataclasses de `bank/reconciliation.py`. A conversão acontece no router (mesmo
# padrão de `_projection_out` em `financial_intelligence/router.py`): o serviço devolve dataclasses
# puras, testáveis sem HTTP, e o Pydantic fica na borda.
#
# ⚠️ **Nenhum destes schemas existe isolado.** Não há (e não pode passar a haver) um
# `ConferenciaTotalOut` com o consolidado sozinho: `ConferenciaReportOut` carrega SEMPRE `contas` e
# `contas_fora_da_banda` (epic §3.2 / decisão do fundador F3). Três contas divergindo +R$ 1.200,
# −R$ 900 e +R$ 40 somam +R$ 340, que parece saudável e esconde dois problemas.


class ConferenciaContaOut(BaseModel):
    """A conferência de UMA conta.

    **`None` significa "não sei", jamais zero.** Quando não houve saldo informado dentro do período,
    `saldo_banco_cents`, `saldo_sistema_cents`, `divergencia_cents` e `dentro_da_tolerancia` vêm
    `None`, `saldo_banco_origem` vem `indisponivel` e `notes` explica. Um `0` em `divergencia_cents`
    afirmaria "conferi e está batendo" — coisa que o e1p não tem lastro para dizer.

    Os dois eixos de procedência (§1.3.1) aparecem lado a lado: `saldo_banco_origem` e
    `saldo_sistema_origem` são o **eixo A** (plano de dinheiro) e valem `banco` no caminho avaliável
    — é por serem o MESMO plano que os dois números são comparáveis; `saldo_banco_fonte` é
    o **eixo B** (porta de entrada do saldo externo: `manual`|`ofx`), copiado **cru** do checkpoint.
    """

    bank_account_id: str
    bank_account_name: str
    bank_account_kind: str
    # O que o banco atesta (checkpoint). `None` = nenhum saldo informado no período.
    saldo_banco_cents: int | None
    # Eixo A: `banco` quando há checkpoint na janela, `indisponivel` quando não há.
    saldo_banco_origem: str
    # Eixo B: `manual`|`ofx`, cru. `None` quando não houve porta de entrada.
    saldo_banco_fonte: str | None
    # A data em que os DOIS saldos foram apurados (o `reference_date` do checkpoint).
    saldo_banco_data: date | None
    # O que o e1p calculou, na MESMA data acima — nunca em `end`, nunca "hoje".
    saldo_sistema_cents: int | None
    # Eixo A do saldo derivado: SEMPRE `banco`, inclusive quando o valor é `None`.
    saldo_sistema_origem: str = ORIGEM_BANCO
    # banco − sistema: `> 0` = o banco tem dinheiro que o sistema não conhece (entrada não lançada);
    # `< 0` = o banco está abaixo (saída não lançada — o achado de maior valor, REQ-14).
    divergencia_cents: int | None
    dentro_da_tolerancia: bool | None
    # A banda aplicada (`max(R$ 50; 0,5%)`). `0` no caminho não avaliável — não leia este campo
    # quando `divergencia_cents` é `None`.
    tolerancia_cents: int
    # `None` = esta conta NUNCA teve saldo informado (diferente de `0` = informado hoje).
    dias_desde_ultima_conferencia: int | None
    movimentos_ignorados: int
    notes: list[str]


class ContaForaDaBandaOut(BaseModel):
    """Uma conta cuja divergência estourou a banda — com nome, para a tela poder apontar QUAL."""

    bank_account_id: str
    bank_account_name: str
    divergencia_cents: int
    tolerancia_cents: int


class ConferenciaReportOut(BaseModel):
    """Resposta de `GET /bank/reconciliation-report`. SOMENTE LEITURA.

    `total_divergencia_cents` soma **apenas** as contas avaliáveis e é `None` quando nenhuma é.
    `contas_avaliadas`/`contas_sem_checkpoint` existem para que o consumidor saiba **o que o total
    cobre** sem precisar recontar a lista, e `notes` avisa em texto quando ele é parcial.

    **Os quatro campos da Story 8.16 ANOTAM, nunca subtraem.** Eles medem a **pré-condição do
    gate** — o que o e1p sabe que moveu dinheiro numa conta real e ainda não virou movimento
    bancário no período. Nenhum deles entra em `divergencia_cents`, `tolerancia_cents`,
    `dentro_da_tolerancia`, `total_divergencia_cents` nem `contas_fora_da_banda`: descontá-los
    a divergência a zero por construção sempre que o sistema soubesse explicar a diferença, e a
    métrica primária do épico morreria (Regra 5 do `CLAUDE.md`).

    São do RELATÓRIO e não por conta porque a conta é justamente o que falta nas duas primeiras
    populações — ver `reconciliation.ConferenciaReport`.
    """

    start: date
    end: date
    contas: list[ConferenciaContaOut]
    total_divergencia_cents: int | None
    contas_avaliadas: int
    contas_sem_checkpoint: int
    contas_fora_da_banda: list[ContaForaDaBandaOut]
    notes: list[str]
    # P1 + P2 — baixa de conta a pagar e recebimento fora da cobrança do e1p, sem conta informada.
    # Fecham na **Onda 2**, e a nota correspondente em `notes` diz isso.
    lancamentos_sem_conta_informada: int = 0
    valor_sem_conta_informada_cents: int = 0
    # P3 — rendimento de aplicação sem perna bancária. Contador PRÓPRIO porque fecha na **Onda 2b**,
    # não nesta: achatá-lo dentro do par acima prometeria na tela um prazo falso.
    rendimentos_sem_perna_bancaria: int = 0
    valor_rendimentos_sem_perna_cents: int = 0
