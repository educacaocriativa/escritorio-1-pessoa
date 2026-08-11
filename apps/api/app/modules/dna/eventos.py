"""O vocabulário do rastro do DNA, e a única porta que o grava.

**Por que existe.** `dna_answers` é upsert por `(tenant, question_key)`: responder no núcleo e
editar depois no `/config` sobrescreve `value`, `answered_at`, `answered_by` **e `source`** — a
linha passa a dizer que a resposta nasceu no `/config`, e o fato de ela ter vindo do núcleo, e
*quando*, deixa de existir. A docstring de `models.py` sempre defendeu o upsert dizendo que "o
histórico de quem mudou o quê já é trabalho de `core/audit.py`". Até 2026-08-11 isso era falso:
`audit` aparecia UMA vez no módulo `dna`, dentro daquela frase, com zero chamadas. Este módulo é
o que torna a frase verdadeira.

**`source` vai no `target`, NUNCA no `action`.** Quatro actions × três sources (`nucleo｜gancho｜
config`) seriam doze strings, e é assim que 117 actions distintas viram 200. O repo já tem
`account_deleted` — sem pontos, fora do padrão `<entidade>.<entidade>.<verbo>` — provando que a
convenção sozinha não segura o vocabulário.

**Por que a validação é aqui e não uma convenção.** `facts.record` tem guarda mecânica (o `kind`
tem de começar pelo `module`); `audit.record` não tem nenhuma. Esta função é a guarda equivalente
para o DNA, e `tests/test_dna_vocabulario_gate.py` garante por AST que ela é o único caminho.

Consumidores (verificável por `grep -rn "eventos.registrar" apps/api/app/modules/dna/`):
`service._gravar` (save/skip) e `router.nucleo_evento` (open/abandon). **Se esta lista divergir do
grep, ela é que está errada** — a lista de consumidores numa docstring tem de ser verificável.
"""
from __future__ import annotations

from app.core import audit

PREFIXO = "dna."

ACTION_SAVE = "dna.answer.save"
ACTION_SKIP = "dna.answer.skip"
ACTION_OPEN = "dna.nucleo.open"
ACTION_ABANDON = "dna.nucleo.abandon"

#: O conjunto fechado. Acrescentar aqui é a única forma de emitir uma action nova.
ACTIONS: tuple[str, ...] = (ACTION_SAVE, ACTION_SKIP, ACTION_OPEN, ACTION_ABANDON)

#: A rota nova é UMA, com o evento no caminho: `POST /dna/nucleo/{evento}`. Porta estreita
#: validada contra um conjunto, como `service._validar` já faz contra o catálogo.
EVENTOS_DO_NUCLEO: dict[str, str] = {"open": ACTION_OPEN, "abandon": ACTION_ABANDON}


class VocabularioError(Exception):
    """Erro de programação, não de usuário: estoura na hora, como `FactError`."""


def alvo_da_resposta(source: str, key: str) -> str:
    """O `target` de uma resposta: `<source>:<pergunta>`.

    É esta string que sobrevive ao upsert e distingue "respondeu no núcleo" de "editou no
    `/config`" — as duas linhas de audit que o `dna_answers` não consegue guardar.
    """
    return f"{source}:{key}"


def registrar(db, *, tenant_id: str, actor: str, action: str, target: str = ""):
    """Grava a trilha do DNA, validando o vocabulário AGORA.

    ⚠️ Quem chama é responsável pelo `db.flush()` quando o `target` depende de uma linha recém
    adicionada — o `id` tem default Python-side e só existe depois do INSERT (defeito MNT-001, 17
    call sites no projeto; o módulo `bank` já faz certo).
    """
    if not action.startswith(PREFIXO) or action not in ACTIONS:
        raise VocabularioError(
            f"'{action}' não é uma action do DNA. O vocabulário é fechado e mora em "
            f"`eventos.ACTIONS`: {ACTIONS}. Se o evento é novo, declare-o lá — e note que o "
            "`source` vai no TARGET, nunca no action."
        )
    return audit.record(db, tenant_id=tenant_id, actor=actor, action=action, target=target)
