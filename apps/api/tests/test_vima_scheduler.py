"""Gera no horário de cada usuário, no fuso do tenant — não em UTC cru.

O relógio é sempre INJETADO (`agora=`). Um job que lê `datetime.now()` sozinho só é testável
esperando o relógio da máquina chegar na hora certa, e é assim que o bug de fuso volta.
"""
from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core import facts
from app.core.facts import FIN_PAGAMENTO_RECEBIDO
from app.modules.auth.models import User
from app.modules.notifications.models import Notification
from app.modules.receivables.models import METHOD_PIX, STATUS_PAID, Charge
from app.modules.settings.models import TenantProfile
from app.modules.vima.models import Briefing
from app.modules.vima.scheduler import tick
from app.modules.wallet.models import KIND_SERVICE

REGISTER = {
    "legal_name": "Vima ME",
    "document": "11444777000161",
    "slug": "vimame",
    "email": "vima@example.com",
    "name": "Flávio Kato",
    "password": "uma-senha-bem-grande",
}

# 07:05 em America/Sao_Paulo (UTC−3). O dono de horário 07:00 já chegou; o de 09:00 não.
DEZ_E_CINCO_UTC = datetime(2026, 8, 6, 10, 5, tzinfo=UTC)


@pytest.fixture()
def tenant_id(client: TestClient) -> str:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).json()["user"][
        "tenant_id"
    ]


@pytest.fixture()
def tenant_br(db: Session, tenant_id: str) -> TenantProfile:
    perfil = TenantProfile(
        tenant_id=tenant_id, display_name="Vima ME", timezone="America/Sao_Paulo",
        whatsapp_provider="evolution",
    )
    db.add(perfil)
    db.commit()
    return perfil


@pytest.fixture()
def dono(db: Session, tenant_id: str) -> User:
    """O owner criado pelo /register — às 07:00, com telefone, WhatsApp ligado."""
    user = db.query(User).filter(User.tenant_id == tenant_id).one()
    user.phone = "43984074017"
    user.briefing_hour = "07:00"
    user.briefing_whatsapp_enabled = True
    db.commit()
    return user


@pytest.fixture()
def dorminhoco(db: Session, tenant_id: str) -> User:
    """Outro usuário do mesmo tenant, que pediu o briefing às 09:00."""
    user = User(
        tenant_id=tenant_id, email="tarde@example.com", name="Contador",
        password_hash="x", role="sub_user", allowed_modules=[],
        phone="43999998888", briefing_hour="09:00", briefing_whatsapp_enabled=True,
    )
    db.add(user)
    db.commit()
    return user


@pytest.fixture()
def aconteceu_algo(db: Session, tenant_id: str) -> Charge:
    """Sem isto o briefing sai `vazio=True` e as regras de entrega mudam de propósito."""
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


def test_gera_apenas_para_quem_ja_chegou_no_horario(
    db: Session, tenant_id, tenant_br, dono, dorminhoco, aconteceu_algo
):
    gerados = tick(db, tenant_id=tenant_id, agora=DEZ_E_CINCO_UTC)

    assert gerados == 1
    donos = [b.user_id for b in db.query(Briefing).all()]
    assert donos == [dono.id]


def test_o_das_nove_recebe_o_dele_quando_a_hora_chega(
    db: Session, tenant_id, tenant_br, dono, dorminhoco, aconteceu_algo
):
    tick(db, tenant_id=tenant_id, agora=DEZ_E_CINCO_UTC)
    # 09:30 em São Paulo = 12:30 UTC.
    assert tick(db, tenant_id=tenant_id, agora=datetime(2026, 8, 6, 12, 30, tzinfo=UTC)) == 1
    assert db.query(Briefing).count() == 2


def test_nao_gera_duas_vezes_no_mesmo_dia(
    db: Session, tenant_id, tenant_br, dono, aconteceu_algo
):
    tick(db, tenant_id=tenant_id, agora=DEZ_E_CINCO_UTC)
    assert tick(db, tenant_id=tenant_id, agora=datetime(2026, 8, 6, 11, 0, tzinfo=UTC)) == 0
    assert db.query(Briefing).count() == 1


def test_o_horario_e_do_TENANT_nao_de_UTC(
    db: Session, tenant_id, tenant_br, dono, aconteceu_algo
):
    """Às 07:05 **UTC** ainda são 04:05 em São Paulo: ninguém pediu briefing às 4 da manhã.

    Sem o fuso, todo tenant brasileiro receberia o briefing 3h antes do que escolheu — e o das
    07:00 acordaria com a notificação às 4h."""
    assert tick(db, tenant_id=tenant_id, agora=datetime(2026, 8, 6, 7, 5, tzinfo=UTC)) == 0


def test_usuario_inativo_nao_recebe(db: Session, tenant_id, tenant_br, dono, aconteceu_algo):
    dono.is_active = False
    db.commit()
    assert tick(db, tenant_id=tenant_id, agora=DEZ_E_CINCO_UTC) == 0


def test_briefing_vazio_nao_enfileira_whatsapp(db: Session, tenant_id, tenant_br, dono):
    """Um 'bom dia, nada aconteceu' diário é a forma mais rápida de ser silenciado — e um canal
    silenciado não entrega o dia em que importa.

    Note que o briefing É gerado: a TELA diz que está tranquilo. O que não sai é o WhatsApp."""
    assert tick(db, tenant_id=tenant_id, agora=DEZ_E_CINCO_UTC) == 1
    assert db.query(Briefing).one().vazio is True
    assert db.query(Notification).count() == 0


def test_quem_nao_ligou_o_whatsapp_recebe_so_a_tela(
    db: Session, tenant_id, tenant_br, dono, aconteceu_algo
):
    dono.briefing_whatsapp_enabled = False
    db.commit()
    assert tick(db, tenant_id=tenant_id, agora=DEZ_E_CINCO_UTC) == 1
    assert db.query(Notification).count() == 0


def test_briefing_ja_lido_na_tela_nao_vira_whatsapp(
    db: Session, tenant_id, tenant_br, dono, aconteceu_algo
):
    """Quem abriu o app antes da hora já recebeu a notícia. Mandar de novo é eco, não aviso."""
    from app.core.tenancy import CurrentUser
    from app.modules.vima import service

    atual = CurrentUser(
        user_id=dono.id, tenant_id=tenant_id, role=dono.role, allowed_modules=[]
    )
    briefing = service.gerar_ou_ler(db, user=atual, hoje=date(2026, 8, 6))
    service.marcar_lido(db, briefing_id=briefing.id, user=atual)

    assert tick(db, tenant_id=tenant_id, agora=DEZ_E_CINCO_UTC) == 0
    assert db.query(Notification).count() == 0
