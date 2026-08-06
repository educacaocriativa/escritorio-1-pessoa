"""Tendência é quase toda de graça: o motor financeiro já produz os sinais."""
from datetime import UTC, date, datetime

import pytest
from sqlalchemy.orm import Session

from app.core.tenancy import CurrentUser
from app.modules.payables.models import STATUS_PAID as CONTA_PAGA
from app.modules.payables.models import Payable
from app.modules.receivables.models import METHOD_PIX, Charge
from app.modules.receivables.models import STATUS_PAID as COBRANCA_PAGA
from app.modules.vima.trends import coletar
from app.modules.wallet.models import KIND_SERVICE

TENANT = "t1"
HOJE = date(2026, 8, 6)


@pytest.fixture()
def usuario_owner() -> CurrentUser:
    return CurrentUser(
        user_id="u1", tenant_id=TENANT, role="owner",
        allowed_modules=[], is_platform_admin=False,
    )


@pytest.fixture()
def usuario_so_crm() -> CurrentUser:
    return CurrentUser(
        user_id="u2", tenant_id=TENANT, role="sub_user",
        allowed_modules=["crm"], is_platform_admin=False,
    )


@pytest.fixture()
def movimento_financeiro(db: Session) -> None:
    """Dinheiro entrando e saindo na janela de competência — o insumo do motor."""
    db.add(
        Charge(
            tenant_id=TENANT, description="Consultoria de agosto", kind=KIND_SERVICE,
            method=METHOD_PIX, amount_cents=320_000, due_date=date(2026, 8, 3),
            competence_date=date(2026, 8, 3), status=COBRANCA_PAGA,
            paid_at=datetime(2026, 8, 3, 12, 0, tzinfo=UTC),
        )
    )
    db.add(
        Payable(
            tenant_id=TENANT, description="Aluguel da sala", supplier="Imobiliária Alfa",
            amount_cents=250_000, due_date=date(2026, 8, 2),
            competence_date=date(2026, 8, 2), status=CONTA_PAGA,
            paid_at=datetime(2026, 8, 2, 9, 0, tzinfo=UTC),
        )
    )
    db.commit()


def test_le_os_sinais_do_motor_financeiro(db, usuario_owner, movimento_financeiro):
    tendencias = coletar(db, user=usuario_owner, hoje=HOJE)
    assert tendencias
    assert all(t.module == "financeiro" for t in tendencias)
    assert all(t.nivel in {"verde", "amarelo", "vermelho"} for t in tendencias)


def test_sub_usuario_de_crm_nao_recebe_nenhuma(db, usuario_so_crm, movimento_financeiro):
    assert coletar(db, user=usuario_so_crm, hoje=HOJE) == []
