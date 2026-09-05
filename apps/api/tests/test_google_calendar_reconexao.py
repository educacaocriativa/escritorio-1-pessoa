"""Reconectar o Google não pode deixar evento apontando para o calendário de outra pessoa.

Issue #302. `agenda_events.google_event_id` era escrito em dois lugares e limpo em NENHUM. Com o
tenant desconectado nada quebrava — os três consumidores do id (`patch_meet_event`,
`delete_meet_event`, `pull_changes`) já retornam cedo sem credencial. O dano abria na
RECONEXÃO: se o dono voltasse com OUTRA conta Google, aqueles ids passavam a endereçar eventos
de um calendário que não é mais dele (remarcar/cancelar mexendo na agenda alheia; e o pull
importando de novo os mesmos compromissos, já que o `existing` nunca casava).

A correção carimba a PROCEDÊNCIA (`google_account_email`, migration 0086) nos dois pontos de
escrita e invalida, na reconexão, só o que veio de outra conta. Todas as chamadas HTTP ao Google
são MOCKADAS.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.agenda.models import AgendaEvent
from app.modules.google_calendar import service, sync
from app.modules.google_calendar.models import GoogleCredential

TENANT = "t" * 12
CONTA_ANTIGA = "antiga@gmail.com"
CONTA_NOVA = "nova@gmail.com"

_TOKEN_DATA = {
    "access_token": "ya29.novo-access",
    "refresh_token": "1//novo-refresh",
    "expires_in": 3600,
}


def _conectar(db: Session, email: str, *, sync_token: str | None = None) -> GoogleCredential:
    cred = GoogleCredential(
        tenant_id=TENANT,
        google_account_email=email,
        access_token="access-valido",
        refresh_token="refresh-valido",
        token_expiry=datetime.now(UTC) + timedelta(hours=1),
        sync_token=sync_token,
    )
    db.add(cred)
    db.commit()
    return cred


def _evento(
    db: Session,
    *,
    titulo: str,
    google_event_id: str | None,
    google_account_email: str | None,
    meeting_url: str | None,
) -> str:
    ev = AgendaEvent(
        tenant_id=TENANT,
        title=titulo,
        kind="reuniao",
        starts_at=datetime(2026, 9, 10, 13, 0, tzinfo=UTC),
        ends_at=datetime(2026, 9, 10, 14, 0, tzinfo=UTC),
        guests=[],
        google_event_id=google_event_id,
        google_account_email=google_account_email,
        meeting_url=meeting_url,
    )
    db.add(ev)
    db.commit()
    return ev.id


def _reler(db: Session, ev_id: str) -> AgendaEvent:
    """Relê do BANCO. O UPDATE em massa usa `synchronize_session=False`: sem expirar a sessão,
    o objeto em memória mentiria o estado anterior e o teste passaria por acidente."""
    db.expire_all()
    return db.get(AgendaEvent, ev_id)


# ── A limpeza na reconexão ───────────────────────────────────────────────────
def test_reconectar_com_a_mesma_conta_preserva_o_vinculo(db: Session):
    """O caso DOMINANTE (token expirou, o dono reconecta a mesma conta) não pode perder nada.

    É o teste que justifica o desenho inteiro: limpar no `disconnect` — quando ainda não se sabe
    qual conta vai voltar — destruiria o vínculo justamente aqui.
    """
    _conectar(db, CONTA_ANTIGA)
    ev_id = _evento(
        db, titulo="Reunião no Meet", google_event_id="gcal-1",
        google_account_email=CONTA_ANTIGA, meeting_url="https://meet.google.com/abc-defg-hij",
    )

    service.upsert_credential(db, tenant_id=TENANT, email=CONTA_ANTIGA, token_data=_TOKEN_DATA)

    ev = _reler(db, ev_id)
    assert ev.google_event_id == "gcal-1"
    assert ev.meeting_url == "https://meet.google.com/abc-defg-hij"
    assert ev.google_account_email == CONTA_ANTIGA


def test_reconectar_com_outra_conta_zera_o_vinculo(db: Session):
    """Conta diferente: o id endereça o calendário de OUTRA pessoa — some, junto com o link."""
    _conectar(db, CONTA_ANTIGA)
    ev_id = _evento(
        db, titulo="Reunião no Meet", google_event_id="gcal-1",
        google_account_email=CONTA_ANTIGA, meeting_url="https://meet.google.com/abc-defg-hij",
    )

    service.upsert_credential(db, tenant_id=TENANT, email=CONTA_NOVA, token_data=_TOKEN_DATA)

    ev = _reler(db, ev_id)
    assert ev.google_event_id is None
    assert ev.meeting_url is None
    assert ev.google_account_email is None
    # O evento em si continua na agenda: some o VÍNCULO com o Google, não o compromisso.
    assert ev.title == "Reunião no Meet"


def test_linha_legada_sem_procedencia_nao_e_tocada_na_troca_de_conta(db: Session):
    """`google_account_email IS NULL` = procedência DESCONHECIDA (gravada antes da 0086).

    Apagar às cegas reintroduziria a duplicação de eventos no próximo sync para os dados que já
    existem — que é a consequência nº 3 da issue. Elas se autocuram pelo sync (teste abaixo).
    """
    _conectar(db, CONTA_ANTIGA)
    ev_id = _evento(
        db, titulo="Evento legado", google_event_id="gcal-legado",
        google_account_email=None, meeting_url="https://meet.google.com/leg-ado-xyz",
    )

    service.upsert_credential(db, tenant_id=TENANT, email=CONTA_NOVA, token_data=_TOKEN_DATA)

    ev = _reler(db, ev_id)
    assert ev.google_event_id == "gcal-legado"
    assert ev.meeting_url == "https://meet.google.com/leg-ado-xyz"
    assert ev.google_account_email is None


def test_link_de_evento_sem_espelho_no_google_sobrevive_a_troca_de_conta(db: Session):
    """`meeting_url` só é apagado de quem TEM espelho no Google (`google_event_id IS NOT NULL`).

    Duas linhas, ambas sem id, pelas quais a cláusula responde:

    a) LINK MANUAL (Zoom): `create_event` só chama o Google quando `not data.meeting_url`, então
       quem digitou um link nunca teve id nem procedência. É o caso que a issue mais teme —
       apagar trabalho digitado à mão. Note que aqui a cláusula `google_account_email IS NOT
       NULL` também protege: só derrubando as DUAS cláusulas esta linha é destruída.

    b) ESPELHO PARCIAL: procedência conhecida, id ausente. Estado real e alcançável — `create_
       event` grava `event.google_event_id = data.get("id")`, então um 200 do Google trazendo
       `hangoutLink` mas sem `id` produz exatamente isto. Aqui a cláusula do id é a ÚNICA
       proteção, e é por esta linha que a remoção dela, sozinha, mata este teste.
    """
    _conectar(db, CONTA_ANTIGA)
    manual = _evento(
        db, titulo="Call no Zoom", google_event_id=None,
        google_account_email=None, meeting_url="https://zoom.us/j/12345",
    )
    parcial = _evento(
        db, titulo="Espelho sem id", google_event_id=None,
        google_account_email=CONTA_ANTIGA, meeting_url="https://meet.google.com/par-cial-xyz",
    )

    service.upsert_credential(db, tenant_id=TENANT, email=CONTA_NOVA, token_data=_TOKEN_DATA)

    assert _reler(db, manual).meeting_url == "https://zoom.us/j/12345"
    assert _reler(db, manual).google_event_id is None
    assert _reler(db, parcial).meeting_url == "https://meet.google.com/par-cial-xyz"
    assert _reler(db, parcial).google_account_email == CONTA_ANTIGA


def test_primeira_conexao_nao_apaga_nada(db: Session):
    """Conectar pela 1ª vez (sem credencial anterior) não pode varrer a agenda existente."""
    ev_id = _evento(
        db, titulo="Call no Zoom", google_event_id=None,
        google_account_email=None, meeting_url="https://zoom.us/j/12345",
    )

    service.upsert_credential(db, tenant_id=TENANT, email=CONTA_NOVA, token_data=_TOKEN_DATA)

    assert _reler(db, ev_id).meeting_url == "https://zoom.us/j/12345"
    assert db.scalar(select(GoogleCredential)).google_account_email == CONTA_NOVA


def test_conta_desconhecida_no_callback_nao_apaga_nada(db: Session):
    """`userinfo` falhou (`email=""`): sem saber QUEM conectou, não dá para afirmar que mudou.

    `handle_callback` segue em frente com e-mail vazio de propósito (uma falha de exibição não
    pode descartar tokens válidos). Na dúvida, não se destrói.
    """
    _conectar(db, CONTA_ANTIGA)
    ev_id = _evento(
        db, titulo="Reunião no Meet", google_event_id="gcal-1",
        google_account_email=CONTA_ANTIGA, meeting_url="https://meet.google.com/abc-defg-hij",
    )

    service.upsert_credential(db, tenant_id=TENANT, email="", token_data=_TOKEN_DATA)

    ev = _reler(db, ev_id)
    assert ev.google_event_id == "gcal-1"
    assert ev.meeting_url == "https://meet.google.com/abc-defg-hij"


# ── O carimbo da procedência, nos dois pontos de escrita do id ───────────────
def test_create_event_carimba_a_conta_conectada(db: Session, monkeypatch):
    """Ponto de escrita nº 1 (e1p → Google). Sem o carimbo, a linha nasce "legada" e imune."""
    from app.modules.agenda import service as agenda
    from app.modules.agenda.schemas import EventCreate

    _conectar(db, CONTA_ANTIGA)

    class _Resp:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"id": "gcal-novo", "hangoutLink": "https://meet.google.com/nov-oooo-xyz"}

    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp())

    event, _ = agenda.create_event(
        db,
        tenant_id=TENANT,
        actor="user-1",
        by_ai=False,
        data=EventCreate(
            title="Reunião nova",
            kind="reuniao",
            starts_at=datetime(2026, 9, 11, 13, 0, tzinfo=UTC),
            ends_at=datetime(2026, 9, 11, 14, 0, tzinfo=UTC),
        ),
    )
    assert event.google_event_id == "gcal-novo"
    assert event.google_account_email == CONTA_ANTIGA


def test_create_event_sem_conta_conhecida_carimba_none(db: Session, monkeypatch):
    """Credencial sem e-mail (`userinfo` falhou) grava NULL, não string vazia.

    "" na coluna passaria em `google_account_email IS NOT NULL` e a linha seria APAGADA na
    próxima reconexão, sem que ninguém jamais tivesse provado de qual conta ela veio.
    """
    from app.modules.agenda import service as agenda
    from app.modules.agenda.schemas import EventCreate

    _conectar(db, "")

    class _Resp:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"id": "gcal-anonimo"}

    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp())

    event, _ = agenda.create_event(
        db,
        tenant_id=TENANT,
        actor="user-1",
        by_ai=False,
        data=EventCreate(
            title="Reunião anônima",
            kind="reuniao",
            starts_at=datetime(2026, 9, 12, 13, 0, tzinfo=UTC),
            ends_at=datetime(2026, 9, 12, 14, 0, tzinfo=UTC),
        ),
    )
    assert event.google_event_id == "gcal-anonimo"
    assert event.google_account_email is None


class _FakeGet:
    def __init__(self, payload: dict):
        self.status_code = 200
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


@pytest.mark.parametrize("ja_existe", [False, True], ids=["insert", "update-autocura"])
def test_sync_carimba_a_conta_no_insert_e_no_update(db: Session, monkeypatch, ja_existe: bool):
    """Ponto de escrita nº 2 (Google → e1p), nos DOIS ramos de `_apply_item`.

    O ramo de UPDATE é o que AUTOCURA as linhas legadas: uma linha com `google_account_email`
    NULL (imune à limpeza, por desenho) ganha procedência no primeiro sync bem-sucedido e passa
    a ser invalidável como qualquer outra. Sem o carimbo nesse ramo, a linha legada ficaria
    legada para sempre.
    """
    _conectar(db, CONTA_ANTIGA)
    if ja_existe:
        ev_id = _evento(
            db, titulo="Título antigo", google_event_id="gcal-sync-1",
            google_account_email=None, meeting_url=None,
        )

    payload = {
        "items": [
            {
                "id": "gcal-sync-1",
                "summary": "Título do Google",
                "start": {"dateTime": "2026-09-12T13:00:00-03:00"},
                "end": {"dateTime": "2026-09-12T14:00:00-03:00"},
            }
        ],
        "nextSyncToken": "token-v1",
    }
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeGet(payload))

    assert sync.pull_changes(db, tenant_id=TENANT) == 1

    db.expire_all()
    ev = db.scalars(
        select(AgendaEvent).where(AgendaEvent.google_event_id == "gcal-sync-1")
    ).one()
    if ja_existe:
        assert ev.id == ev_id, "o sync deve ATUALIZAR a linha existente, não criar outra"
        assert ev.title == "Título do Google"
    assert ev.google_account_email == CONTA_ANTIGA


def test_linha_autocurada_pelo_sync_passa_a_ser_invalidada_na_troca_de_conta(
    db: Session, monkeypatch
):
    """O ciclo completo: legada → sync carimba → reconexão com outra conta agora a limpa.

    É a razão de o carimbo no ramo de UPDATE existir. Sem ele este teste falha na última
    asserção e a linha legada permanece apontando para um calendário alheio para sempre.
    """
    _conectar(db, CONTA_ANTIGA)
    ev_id = _evento(
        db, titulo="Legada", google_event_id="gcal-sync-1",
        google_account_email=None, meeting_url=None,
    )

    payload = {
        "items": [
            {
                "id": "gcal-sync-1",
                "summary": "Legada",
                "start": {"dateTime": "2026-09-12T13:00:00-03:00"},
                "end": {"dateTime": "2026-09-12T14:00:00-03:00"},
            }
        ],
        "nextSyncToken": "token-v1",
    }
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeGet(payload))
    sync.pull_changes(db, tenant_id=TENANT)

    service.upsert_credential(db, tenant_id=TENANT, email=CONTA_NOVA, token_data=_TOKEN_DATA)

    ev = _reler(db, ev_id)
    assert ev.google_event_id is None
    assert ev.google_account_email is None
