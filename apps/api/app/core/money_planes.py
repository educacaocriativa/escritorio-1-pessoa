"""Vocabulário NORMATIVO de procedência de saldo — **eixo A** da Regra dos Planos (Story 8.1).

**A regra que este módulo torna auditável** (design `controle-bancario-design.md` §1.3c / epic
§4.1c): *todo campo de API que carrega um valor monetário de saldo declara de qual **plano de
dinheiro** ele vem, num campo irmão `*_origem`.* **Nenhum saldo trafega sem procedência.**

Os três planos de dinheiro (design §1.1):
    1. **Plataforma** — dinheiro no trilho e1p, split 40/30/20 (`transactions`/`platform_earnings`);
    2. **Negócio** — direitos e obrigações (`charges`, `payables`);
    3. **Bancário** — o extrato real da conta do usuário (`bank_*`, ainda NÃO existe na Onda 0).

**Por que este vocabulário vive em `app/core/` e não dentro de um módulo:** ele é consumido por
`app.modules.financial_intelligence` **e** por `app.modules.bank` (Stories 8.2–8.8), e nenhum dos
dois pode importar o outro nessa direção — a Regra dos Planos §1.3b fixa que `bank` pode importar
`wallet`, mas `wallet` **nunca** importa `bank`; e `financial_intelligence` só passa a ler `bank` na
Story 8.8. Um vocabulário compartilhado que morasse em qualquer um dos dois criaria a dependência
proibida. Mesma convenção de `core/validators.py` e `core/tz.py`: constantes puras, sem I/O.

---

### DOIS eixos de procedência — não confundir (design §1.3.1, ratificado em 2026-07-29)

Este módulo é dono de **um** dos dois eixos:

- **Eixo A — plano (ESTE módulo).** Pergunta: *"de qual plano de dinheiro (§1.1) este número vem?"*
  Sufixo do campo: `*_origem`. Vocabulário: `plataforma` | `banco` | `misto` | `indisponivel`
  (`ORIGEM_*`/`ORIGENS`, abaixo). Obrigatório em **todo** campo de saldo, sem exceção.
- **Eixo B — porta de entrada.** Pergunta: *"por qual porta este saldo **externo** entrou no e1p?"*
  Sufixo do campo: `*_fonte`. Vocabulário: `manual` | `ofx`, que vive em
  `app/modules/bank/models.py` (`ORIGIN_MANUAL`/`ORIGIN_OFX`/`ORIGINS`, Story 8.4) — ao lado da
  coluna `bank_balance_checkpoints.origin` que ele descreve. Obrigatório só em saldo atestado por
  terceiro (hoje: o checkpoint).

**`declarado` e `extrato` estão REVOGADOS como valores de `*_origem`**: eram valores do eixo B
vestidos de eixo A (`declarado` ≡ `manual`, `extrato` ≡ `ofx`). **`ORIGENS` tem QUATRO valores
porque o domínio conceitual do eixo A tem quatro.** Nunca acrescente a porta de entrada aqui, e
nunca traduza um eixo no outro: toda tradução silenciosa entre dois vocabulários do mesmo conceito
é fábrica de bug de manutenção (foi exatamente a camada `origin='manual'` → `ORIGEM_DECLARADO` que
a ratificação D-3 removeu da Story 8.4).

Consequência boa registrada pela @architect: **na Onda 3 nada muda de vocabulário** — `ofx` já
existe no eixo B desde a §2.4 do design, e a onda só passa a *escrever* nele. É o teste de que a
modelagem em dois eixos era a certa.

---

### Além de declarar a origem: o que o sistema tem o DIREITO DE AFIRMAR (§6.1.1/§6.1.2)

Declarar a procedência é só metade. A outra metade — a que a Onda 0 implementa na Projeção de Caixa
— é que **toda inferência** construída sobre um saldo de origem não confirmada precisa ser
**calada**: o runway em dias (`Runway.days_suprimido`) e o alerta de janela negativa
(`ProjectionWindow.alert_suprimido`). O princípio, literal:

> **Suprima a AFIRMAÇÃO, nunca o NÚMERO.**

O saldo continua exposto e exibido com o rótulo de origem ao lado; o que desaparece é o e1p
afirmando o que não tem lastro para afirmar. Se aparecer uma terceira inferência sobre um saldo de
origem `plataforma`, ela nasce com a mesma pergunta.
"""
from __future__ import annotations

# Plano 1 — dinheiro no trilho e1p (`wallet.available_cents`). Na Onda 0 é o ÚNICO valor possível
# para o saldo inicial da Projeção: não existe `bank_accounts` ainda.
ORIGEM_PLATAFORMA = "plataforma"
# Plano 3 — saldo derivado das contas bancárias do usuário (Stories 8.2+).
ORIGEM_BANCO = "banco"
# Soma rotulada dos planos 3 + 1 (Story 8.8): Σ saldo derivado das contas ativas + available_cents.
# Somar é correto (é dinheiro do usuário); esconder a composição, nunca — a UI mostra as 2 parcelas.
ORIGEM_MISTO = "misto"
# O sistema não consegue estabelecer o saldo (ex.: conta sem checkpoint nem movimento). Estado
# EXPLÍCITO — jamais devolver 0 fingindo saber.
ORIGEM_INDISPONIVEL = "indisponivel"

ORIGENS: frozenset[str] = frozenset(
    {ORIGEM_PLATAFORMA, ORIGEM_BANCO, ORIGEM_MISTO, ORIGEM_INDISPONIVEL}
)
