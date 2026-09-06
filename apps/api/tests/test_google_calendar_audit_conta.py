"""A trilha do Google Calendar tem de dizer QUAL conta entrou e QUAL saiu (issue #307).

Antes disto, os três `audit.record()` de `google_calendar/service.py` gravavam só
`target=cred.id`. Como os DOIS caminhos de saída APAGAM a `GoogleCredential` na mesma transação
(`disconnect` → `db.delete(cred)`; `_descartar_credencial_revogada` → idem), o id sobrevivia
apontando para uma linha inexistente: o e-mail deixava de existir no banco e nenhum join o
trazia de volta. A `agenda_events.google_account_email` da 0086 também não salvava, porque a
invalidação de reconexão ZERA aquela coluna — o último rastro morria justo no evento auditado.

A correção é a coluna `audit_entries.detail` (migration 0087), o mesmo SNAPSHOT que
`platform_audit_entries.actor_email` já usava pelo mesmo motivo.

UM TESTE POR CALL SITE, de propósito. Os três chamam a mesma função e é fácil escrever uma
asserção só que passa a cobrir os três por acidente — aí quebrar dois deles não mata teste
nenhum e a cobertura é ilusória. Cada teste abaixo morre com a mutação do SEU call site,
verificado uma a uma.

Todas as chamadas HTTP ao Google são MOCKADAS.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import AuditEntry
from app.modules.google_calendar import service
from app.modules.google_calendar.models import GoogleCredential

REGISTER = {
    "legal_name": "Clínica Maria",
    "document": "98765432000198",
    "slug": "clinicamaria",
    "email": "maria@example.com",
    "name": "Maria",
    "password": "uma-senha-bem-forte",
}

CONTA = "dono.da.clinica@gmail.com"
OUTRA_CONTA = "socio@empresa.com.br"

_TOKEN_DATA = {
    "access_token": "ya29.fake-access",
    "refresh_token": "1//fake-refresh",
    "expires_in": 3600,
}


@pytest.fixture()
def tenant_id(client: TestClient, db: Session) -> str:
    from app.modules.auth.models import Tenant

    client.post("/auth/register", json=REGISTER)
    return db.scalars(select(Tenant)).first().id


def _conectar(db: Session, tenant_id: str, email: str) -> GoogleCredential:
    """Credencial VIVA (token no futuro), como depois de um callback bem-sucedido."""
    cred = GoogleCredential(
        tenant_id=tenant_id,
        google_account_email=email,
        access_token="access-valido",
        refresh_token="refresh-valido",
        token_expiry=datetime.now(UTC) + timedelta(hours=1),
    )
    db.add(cred)
    db.commit()
    return cred


def _entrada(db: Session, action: str) -> AuditEntry:
    entrada = db.scalar(select(AuditEntry).where(AuditEntry.action == action))
    assert entrada is not None, f"nenhuma entrada de audit para '{action}'"
    return entrada


# ── Call site 1: `upsert_credential` → google.credential.connect ─────────────
def test_connect_grava_a_conta_que_entrou(db: Session, tenant_id: str):
    """O `connect` é a ÚNICA ponta que sabe o e-mail novo.

    Sem ele não adianta ter os dois de saída: o `target` é o id da credencial, que o upsert
    REAPROVEITA entre reconexões — o mesmo id serve a todas as contas que o tenant já usou, e
    portanto não distingue nenhuma. Só o `detail` diz de qual conta para qual a troca foi.
    """
    service.upsert_credential(db, tenant_id=tenant_id, email=CONTA, token_data=_TOKEN_DATA)

    assert _entrada(db, "google.credential.connect").detail == CONTA


def test_connect_sem_userinfo_grava_vazio_e_nao_quebra(db: Session, tenant_id: str):
    """`handle_callback` segue com `email=""` quando o userinfo falha (robustez do módulo).

    O audit grava "" e isso é HONESTO: a conexão aconteceu sem que soubéssemos quem é. O que
    não pode é a ausência de e-mail derrubar o `connect` — os tokens já foram obtidos.
    """
    service.upsert_credential(db, tenant_id=tenant_id, email="", token_data=_TOKEN_DATA)

    assert _entrada(db, "google.credential.connect").detail == ""


# ── Call site 2: `disconnect` → google.credential.disconnect ─────────────────
def test_disconnect_grava_a_conta_que_saiu(db: Session, tenant_id: str, monkeypatch):
    """A conta tem de sobreviver ao `db.delete(cred)` da MESMA transação."""
    monkeypatch.setattr(httpx, "post", lambda *a, **k: None)
    _conectar(db, tenant_id, CONTA)

    assert service.disconnect(db, tenant_id=tenant_id, actor="user-1") is True

    assert db.scalar(select(GoogleCredential)) is None  # a linha REALMENTE sumiu
    assert _entrada(db, "google.credential.disconnect").detail == CONTA


def test_disconnect_grava_a_conta_mesmo_se_a_revogacao_falhar(
    db: Session, tenant_id: str, monkeypatch
):
    """Best-effort na revogação não pode custar o rastro: o delete acontece de qualquer jeito."""

    def explode(*a, **k):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(httpx, "post", explode)
    _conectar(db, tenant_id, CONTA)

    assert service.disconnect(db, tenant_id=tenant_id, actor="user-1") is True

    assert _entrada(db, "google.credential.disconnect").detail == CONTA


# ── Call site 3: `_descartar_credencial_revogada` → google.credential.revoked ─
@pytest.fixture()
def sessao_curta(db: Session, monkeypatch):
    """`service.tenant_session` → sessão SEPARADA na mesma engine (espelha produção)."""

    @contextmanager
    def _factory(_tenant_id: str):
        curta = Session(bind=db.get_bind(), autoflush=False, expire_on_commit=False)
        try:
            yield curta
            curta.commit()
        finally:
            curta.close()

    monkeypatch.setattr(service, "tenant_session", _factory)


class _Revogado400:
    status_code = 400
    text = '{"error": "invalid_grant", "error_description": "expired or revoked"}'

    def raise_for_status(self):
        raise httpx.HTTPStatusError("400 invalid_grant", request=None, response=None)


def test_revoked_grava_a_conta_que_o_google_matou(
    db: Session, tenant_id: str, monkeypatch, sessao_curta
):
    """O descarte automático roda em sessão CURTA e não tem o `cred` do chamador na mão.

    O e-mail é lido ANTES de abrir a outra sessão, junto de `tenant_id`/`cred_id` — mesma
    disciplina que a função já aplicava para os outros dois.
    """
    from app.modules.agenda.models import AgendaEvent

    cred = GoogleCredential(
        tenant_id=tenant_id,
        google_account_email=OUTRA_CONTA,
        access_token="velho",
        refresh_token="refresh-morto",
        token_expiry=datetime.now(UTC) - timedelta(hours=1),  # força a renovação
    )
    db.add(cred)
    ev = AgendaEvent(
        tenant_id=tenant_id,
        title="Reunião",
        kind="reuniao",
        starts_at=datetime.now(UTC) + timedelta(days=1),
        ends_at=datetime.now(UTC) + timedelta(days=1, hours=1),
    )
    db.add(ev)
    db.commit()

    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Revogado400())
    assert service.create_meet_event(db, tenant_id=tenant_id, event=ev) is None

    assert _entrada(db, "google.credential.revoked").detail == OUTRA_CONTA


# ── A pergunta da issue, ponta a ponta ───────────────────────────────────────
def test_a_trilha_sozinha_reconstroi_a_troca_de_conta(
    db: Session, tenant_id: str, monkeypatch
):
    """O caso que abriu a issue: "de QUAL conta para qual?".

    Depois da troca, NENHUMA linha do banco guarda a conta antiga — a `GoogleCredential` foi
    apagada e a invalidação de reconexão zerou `agenda_events.google_account_email`. A trilha
    tem de bastar sozinha.

    E note o `target`: os três registros carregam ids que já não endereçam nada (a credencial
    velha morreu). É o `detail` que responde.
    """
    monkeypatch.setattr(httpx, "post", lambda *a, **k: None)
    service.upsert_credential(db, tenant_id=tenant_id, email=CONTA, token_data=_TOKEN_DATA)
    service.disconnect(db, tenant_id=tenant_id, actor="user-1")
    service.upsert_credential(db, tenant_id=tenant_id, email=OUTRA_CONTA, token_data=_TOKEN_DATA)

    trilha = sorted(
        (e.action, e.detail)
        for e in db.scalars(
            select(AuditEntry).where(AuditEntry.action.startswith("google.credential."))
        ).all()
    )

    # `sorted`, e NÃO ordem cronológica, de propósito: `created_at` é `server_default=func.now()`
    # — o timestamp da TRANSAÇÃO. Aqui as três ações caem na mesma transação de teste, então os
    # carimbos EMPATAM e o desempate por `id` (UUID aleatório) daria uma ordem que muda entre
    # execuções. É a mesma armadilha documentada em `scripts/nucleo_activation.entradas_do_dna`.
    # Em produção cada ação é uma request própria e a cronologia existe; o que este teste precisa
    # provar é o CONTEÚDO — que cada entrada carrega a sua conta.
    assert trilha == sorted(
        [
            ("google.credential.connect", CONTA),
            ("google.credential.disconnect", CONTA),  # a conta que SAIU, nomeada
            ("google.credential.connect", OUTRA_CONTA),  # a conta que ENTROU, nomeada
        ]
    )


# ── A coluna em si ──────────────────────────────────────────────────────────
def test_detail_e_vazio_por_padrao_nunca_nulo(db: Session, tenant_id: str):
    """Os 121 `audit.record()` que não passam `detail` seguem gravando — com "" , não NULL.

    A coluna é `NOT NULL default ""` de propósito: "sem detalhe" é "não se aplica", não é
    "desconhecido". Um `None` aqui obrigaria todo leitor futuro a tratar NULL sem ganhar nada.
    """
    from app.core import audit

    audit.record(db, tenant_id=tenant_id, actor="user-1", action="teste.sem.detalhe")
    db.commit()

    entrada = _entrada(db, "teste.sem.detalhe")
    assert entrada.detail == ""
    assert entrada.detail is not None


def test_detail_cabe_um_email_inteiro_que_nao_caberia_composto_no_target(
    db: Session, tenant_id: str
):
    """A razão TÉCNICA de ser coluna, e não `target=f"{id}:{email}"`.

    `target` é `String(255)` e já carrega um UUID de 36 chars; o e-mail vai a 254 (RFC 5321).
    Composto dá 291 — o Postgres de produção RECUSA e derrubaria o `disconnect`, enquanto o
    SQLite da suíte ignoraria o limite e ficaria verde. Em coluna própria os 254 cabem.
    """
    from app.core import audit

    email_no_limite = "a" * 64 + "@" + "b" * 185 + ".com"  # 254 chars
    assert len(email_no_limite) == 254

    audit.record(
        db,
        tenant_id=tenant_id,
        actor="google:oauth",
        action="teste.email.longo",
        target="x" * 36,
        detail=email_no_limite,
    )
    db.commit()
    db.expire_all()  # força reler do banco, não devolver o objeto da identity map

    assert _entrada(db, "teste.email.longo").detail == email_no_limite
