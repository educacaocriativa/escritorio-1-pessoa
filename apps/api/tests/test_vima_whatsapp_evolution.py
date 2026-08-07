"""Tenant Evolution recebe o briefing inteiro, em um passo.

A Evolution (Baileys) não conhece template nem janela de 24h: o texto sai direto, como mensagem
livre. Este é o caso simples — o de dois tempos é o da Meta (`test_vima_whatsapp_meta.py`).
"""
from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core import facts
from app.core.facts import FIN_PAGAMENTO_RECEBIDO
from app.core.whatsapp.capabilities import for_profile
from app.modules.auth.models import User
from app.modules.notifications.models import Notification
from app.modules.receivables.models import METHOD_PIX, STATUS_PAID, Charge
from app.modules.settings.models import TenantProfile
from app.modules.vima.scheduler import tick
from app.modules.wallet.models import KIND_SERVICE
from app.modules.whatsapp_templates.models import PURPOSE_VIMA_BRIEFING_TEXTO

REGISTER = {
    "legal_name": "Vima ME",
    "document": "11444777000161",
    "slug": "vimame",
    "email": "vima@example.com",
    "name": "Flávio Kato",
    "password": "uma-senha-bem-grande",
}

DEZ_E_CINCO_UTC = datetime(2026, 8, 6, 10, 5, tzinfo=UTC)  # 07:05 em America/Sao_Paulo


class _Profile:
    def __init__(self, provider: str | None) -> None:
        self.whatsapp_provider = provider


def test_evolution_nao_precisa_de_optin() -> None:
    assert for_profile(_Profile("evolution")).briefing_needs_optin is False


def test_meta_precisa_de_optin() -> None:
    """Parâmetro de template da Cloud API não aceita quebra de linha, e às 7h o dono está sempre
    fora da janela de 24h — então o briefing completo só sai depois que ELE responder."""
    assert for_profile(_Profile("meta")).briefing_needs_optin is True


@pytest.fixture()
def tenant_id(client: TestClient) -> str:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).json()["user"][
        "tenant_id"
    ]


@pytest.fixture()
def tenant_evolution(db: Session, tenant_id: str) -> TenantProfile:
    perfil = TenantProfile(
        tenant_id=tenant_id, display_name="Vima ME", timezone="America/Sao_Paulo",
        whatsapp_provider="evolution",
    )
    db.add(perfil)
    db.commit()
    return perfil


@pytest.fixture()
def usuario_com_optin(db: Session, tenant_id: str) -> User:
    user = db.query(User).filter(User.tenant_id == tenant_id).one()
    user.phone = "43984074017"
    user.briefing_hour = "07:00"
    user.briefing_whatsapp_enabled = True
    db.commit()
    return user


@pytest.fixture()
def aconteceu_algo(db: Session, tenant_id: str) -> Charge:
    cobranca = Charge(
        tenant_id=tenant_id, description="Consultoria", kind=KIND_SERVICE,
        method=METHOD_PIX, amount_cents=320_000, due_date=date(2026, 8, 3),
        status=STATUS_PAID, paid_at=datetime(2026, 8, 6, 12, 0, tzinfo=UTC),
    )
    db.add(cobranca)
    db.flush()
    facts.record(
        db, tenant_id=tenant_id, module="financeiro", kind=FIN_PAGAMENTO_RECEBIDO,
        title="Pagamento de João recebido", actor="system",
        subject_type="charge", subject_id=cobranca.id,
    )
    db.commit()
    return cobranca


def test_enfileira_o_texto_inteiro_em_tenant_evolution(
    db: Session, tenant_id, tenant_evolution, usuario_com_optin, aconteceu_algo
):
    tick(db, tenant_id=tenant_id, agora=DEZ_E_CINCO_UTC)

    n = db.query(Notification).one()
    assert n.channel == "whatsapp"
    assert n.purpose == PURPOSE_VIMA_BRIEFING_TEXTO
    assert n.recipient == usuario_com_optin.phone
    # É o briefing, não um aviso: o texto narrado inteiro, com quebras de linha e tudo.
    assert len(n.message) > 40
    # Texto livre — sem template. A Evolution recusa template por design.
    assert n.whatsapp_template_name is None
    # Notificação INTERNA ao dono: não é mensagem para um cliente do CRM.
    assert n.client_id is None


def test_nao_enfileira_duas_vezes_no_mesmo_dia(
    db: Session, tenant_id, tenant_evolution, usuario_com_optin, aconteceu_algo
):
    """O sweep roda a cada poucos minutos. Sem a guarda, o dono receberia o mesmo briefing a cada
    passada até a meia-noite."""
    tick(db, tenant_id=tenant_id, agora=DEZ_E_CINCO_UTC)
    tick(db, tenant_id=tenant_id, agora=datetime(2026, 8, 6, 10, 20, tzinfo=UTC))
    tick(db, tenant_id=tenant_id, agora=datetime(2026, 8, 6, 15, 0, tzinfo=UTC))

    assert db.query(Notification).count() == 1


def test_dia_seguinte_enfileira_de_novo(
    db: Session, tenant_id, tenant_evolution, usuario_com_optin, aconteceu_algo
):
    """A guarda é do DIA, não permanente — senão o briefing sairia uma vez na vida."""
    tick(db, tenant_id=tenant_id, agora=DEZ_E_CINCO_UTC)
    tick(db, tenant_id=tenant_id, agora=datetime(2026, 8, 7, 10, 5, tzinfo=UTC))

    assert db.query(Notification).count() == 2


def test_sem_telefone_nao_enfileira(
    db: Session, tenant_id, tenant_evolution, usuario_com_optin, aconteceu_algo
):
    """A preferência pode ter sido ligada e o telefone apagado depois. Enfileirar com destinatário
    vazio é o que `notifications.enqueue` rejeita — e a exceção derrubaria o sweep do tenant."""
    usuario_com_optin.phone = None
    db.commit()

    assert tick(db, tenant_id=tenant_id, agora=DEZ_E_CINCO_UTC) == 1
    assert db.query(Notification).count() == 0
