"""A regra do silêncio ao longo de VÁRIOS dias — que é onde ela quebra.

`test_vima_absences.py` cobre as duas transições de UM dia e passa. A sequência de três dias é
a menor que exercita o encadeamento real do produto: o mapa gravado num dia é a entrada do dia
seguinte. É aí que a ausência calada some do registro e volta a falar no dia seguinte, porque
"sem valor anterior" e "nunca falei disto" são indistinguíveis.
"""
from datetime import UTC, date, datetime

import pytest
from sqlalchemy.orm import Session

from app.core.tenancy import CurrentUser
from app.modules.crm.models import Client, PipelineStage
from app.modules.vima import composer
from app.modules.vima.absences import coletar

TENANT = "t1"
KIND_CARD = "comercial.card.parado"
CHAVE_CARD = f"{KIND_CARD}:c1"


@pytest.fixture()
def usuario_owner() -> CurrentUser:
    return CurrentUser(
        user_id="u1", tenant_id=TENANT, role="owner",
        allowed_modules=[], is_platform_admin=False,
    )


@pytest.fixture()
def card_parado(db: Session) -> Client:
    """Entrou na etapa em 25/07: 12 dias em 06/08, 13 em 07/08, 14 em 08/08."""
    etapa = PipelineStage(tenant_id=TENANT, name="Em contato", position=1)
    db.add(etapa)
    db.flush()
    card = Client(
        id="c1", tenant_id=TENANT, name="Carlos", stage_id=etapa.id,
        stage_entered_at=datetime(2026, 7, 25, 12, 0, tzinfo=UTC),
    )
    db.add(card)
    db.commit()
    return card


def _um_dia(
    db: Session, user: CurrentUser, *, hoje: date, marcos: dict[str, int]
) -> tuple[bool, dict[str, int]]:
    """Um dia inteiro do briefing: coleta, compõe, e devolve (falou do card?, mapa de amanhã).

    ⚠️ É o ÚNICO lugar deste arquivo que conhece as assinaturas de `coletar` e `compor`. Quando
    elas mudarem, edite só este helper — as asserções descrevem comportamento de produto e não
    devem mudar junto com a forma de chamar.
    """
    ausencias = coletar(db, user=user, hoje=hoje, ja_reportadas=marcos)
    payload = composer.compor(fatos=[], ausencias=ausencias, tendencias=[], valores={})
    falou = any(linha.kind == KIND_CARD for linha in payload.linhas)
    return falou, payload.ausencias_ditas


def test_ausencia_calada_continua_calada_no_dia_seguinte(db, usuario_owner, card_parado):
    """Fala no dia 12, cala no 13, e no 14 tem de CONTINUAR calada — a próxima é a 24.

    Hoje ela volta no dia 14. O mapa do payload é montado só com o que foi dito, então a
    ausência calada no dia 13 não entra nele; no dia 14 não há valor anterior e ela é tratada
    como novidade. O silêncio prometido dura exatamente um dia, e o dono vê a mesma pendência
    dia sim, dia não.
    """
    falou_12, marcos = _um_dia(db, usuario_owner, hoje=date(2026, 8, 6), marcos={})
    assert falou_12, "cruzou o limiar de 10 dias — tem de ser dito"
    assert marcos[CHAVE_CARD] == 12

    falou_13, marcos = _um_dia(db, usuario_owner, hoje=date(2026, 8, 7), marcos=marcos)
    assert not falou_13, "13 dias não é notícia nova"

    falou_14, _ = _um_dia(db, usuario_owner, hoje=date(2026, 8, 8), marcos=marcos)
    assert not falou_14, "14 dias também não é: a regra vale além de um dia"


# ── A função de escalada ────────────────────────────────────────────────────────────────


def test_o_ramo_positivo_e_o_comportamento_de_hoje():
    """É a identidade que torna seguro aplicar o conserto às cinco famílias de ausência.

    Se este teste falhar, o conserto deixou de ser transparente para card parado, contato
    sumido, ninguém respondeu, prazo e topo seco — e o raio da mudança passou a ser outro.
    """
    from app.modules.vima.absences import _proximo_marco

    for anterior in (1, 2, 3, 10, 12, 30):
        assert _proximo_marco(anterior) == anterior * 2


def test_falou_antes_de_vencer_volta_no_vencimento():
    """Marco negativo é "ainda não venceu". O próximo momento que é notícia é o vencimento.

    Com `anterior * 2` puro, um marco de -3 pede -6 — um número que `dias` nunca mais alcança,
    porque ele só cresce. A ausência deixaria de ser calada para sempre.
    """
    from app.modules.vima.absences import _proximo_marco

    assert _proximo_marco(-3) == 0
    assert _proximo_marco(-1) == 0


def test_falou_no_vencimento_volta_no_primeiro_dia_de_atraso():
    """Zero dobrado é zero: sem este ramo, a ausência falaria todo dia depois de vencer."""
    from app.modules.vima.absences import _proximo_marco

    assert _proximo_marco(0) == 1
