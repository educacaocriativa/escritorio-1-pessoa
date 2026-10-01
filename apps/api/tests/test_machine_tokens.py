"""Credencial de máquina (escopo `lead_ingest`): tabela global, só hash, 401 fail-closed."""
import pytest
from sqlalchemy.orm import Session

from app.modules.device_tokens import service as device_tokens_service
from app.modules.machine_tokens import service
from app.modules.machine_tokens.models import SCOPE_LEAD_INGEST

TENANT = "tenant-nexus-0001"


def _emite(db: Session, *, tenant_id: str = TENANT, name: str = "site nexuspublica"):
    return service.create_token(db, tenant_id=tenant_id, name=name, scope=SCOPE_LEAD_INGEST)


def test_emitir_devolve_o_cru_uma_vez_e_guarda_so_o_hash(db: Session):
    token, raw = _emite(db)
    assert len(raw) > 20
    assert token.token_hash != raw
    assert raw not in token.token_hash
    assert token.scope == SCOPE_LEAD_INGEST
    assert token.tenant_id == TENANT
    assert token.revoked_at is None


def test_emitir_recusa_escopo_desconhecido(db: Session):
    with pytest.raises(service.MachineTokenError) as e:
        service.create_token(db, tenant_id=TENANT, name="x", scope="receipt_upload")
    assert e.value.status_code == 422


def test_resolver_devolve_o_tenant_e_marca_uso(db: Session):
    _, raw = _emite(db)
    achado = service.resolve(db, raw=raw, scope=SCOPE_LEAD_INGEST)
    assert achado.tenant_id == TENANT
    assert achado.last_used_at is not None


@pytest.mark.parametrize("raw", ["", "nao-existe", "Bearer qualquer"])
def test_resolver_recusa_desconhecido_com_401(db: Session, raw: str):
    with pytest.raises(service.MachineTokenError) as e:
        service.resolve(db, raw=raw, scope=SCOPE_LEAD_INGEST)
    assert e.value.status_code == 401


def test_resolver_recusa_revogado_com_401(db: Session):
    token, raw = _emite(db)
    service.revoke(db, token_id=token.id)
    with pytest.raises(service.MachineTokenError) as e:
        service.resolve(db, raw=raw, scope=SCOPE_LEAD_INGEST)
    assert e.value.status_code == 401


def test_resolver_recusa_outro_escopo_com_401_e_nao_403(db: Session):
    _, raw = _emite(db)
    with pytest.raises(service.MachineTokenError) as e:
        service.resolve(db, raw=raw, scope="outro_escopo")
    assert e.value.status_code == 401


def test_token_de_dispositivo_nao_vale_como_credencial_de_maquina(db: Session):
    _, raw = device_tokens_service.create_token(
        db, tenant_id=TENANT, user_id="u-1", name="iPhone"
    )
    with pytest.raises(service.MachineTokenError) as e:
        service.resolve(db, raw=raw, scope=SCOPE_LEAD_INGEST)
    assert e.value.status_code == 401


def test_listar_traz_so_o_tenant_pedido_inclusive_revogados(db: Session):
    revogado, _ = _emite(db, name="site antigo")
    service.revoke(db, token_id=revogado.id)
    _emite(db, name="site novo")
    _emite(db, tenant_id="outro-tenant-0002", name="de outro tenant")
    nomes = {t.name for t in service.list_tokens(db, tenant_id=TENANT)}
    assert nomes == {"site antigo", "site novo"}


def test_revogar_inexistente_da_404(db: Session):
    with pytest.raises(service.MachineTokenError) as e:
        service.revoke(db, token_id="nao-existe")
    assert e.value.status_code == 404


def test_revogar_duas_vezes_preserva_a_primeira_data(db: Session):
    token, _ = _emite(db)
    primeira = service.revoke(db, token_id=token.id).revoked_at
    assert service.revoke(db, token_id=token.id).revoked_at == primeira
