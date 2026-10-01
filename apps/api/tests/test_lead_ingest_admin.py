"""`app/scripts/lead_ingest_admin.py`: emitir credencial e configurar produto/funis por tenant."""
import json
from contextlib import contextmanager

import pytest
from sqlalchemy.orm import Session

from app.modules.auth.models import Tenant
from app.modules.funnels.models import Funnel
from app.modules.machine_tokens import service as machine_tokens_service
from app.modules.machine_tokens.models import SCOPE_LEAD_INGEST
from app.modules.settings import service as settings_service
from app.scripts import lead_ingest_admin as admin


@pytest.fixture()
def tenant(db: Session) -> Tenant:
    t = Tenant(slug="nexus", legal_name="Nexus Pública", document="11222333000181")
    db.add(t)
    db.commit()
    return t


@pytest.fixture()
def mesma_sessao(db: Session, monkeypatch):
    @contextmanager
    def _mesma(*_args, **_kwargs):
        yield db

    monkeypatch.setattr(admin, "_sessao_global", _mesma)
    monkeypatch.setattr(admin, "tenant_session", _mesma)


def _funil(db: Session, tenant_id: str, nome: str) -> Funnel:
    funil = Funnel(tenant_id=tenant_id, name=nome, nodes=[{"id": "n1"}], edges=[])
    db.add(funil)
    db.commit()
    return funil


def test_emitir_token_resolve_o_tenant_pelo_slug(db: Session, tenant: Tenant):
    token, raw = admin.emitir_token(db, slug=" Nexus ", nome="site nexuspublica.com.br")
    assert token.tenant_id == tenant.id
    assert machine_tokens_service.resolve(db, raw=raw, scope=SCOPE_LEAD_INGEST).id == token.id


def test_slug_desconhecido_e_erro_de_operador(db: Session, tenant: Tenant):
    with pytest.raises(admin.AdminError, match="Tenant não encontrado"):
        admin.emitir_token(db, slug="nao-existe", nome="x")


def test_ler_funis():
    assert admin.ler_funis(["lead=f1", " compra_aprovada = f2 ", "renovacao="]) == {
        "lead": "f1", "compra_aprovada": "f2", "renovacao": "",
    }


@pytest.mark.parametrize("par", ["lead", "compra=f1"])
def test_ler_funis_recusa_formato_ou_evento_invalido(par: str):
    with pytest.raises(admin.AdminError):
        admin.ler_funis([par])


def test_configurar_grava_produto_e_funis_e_mescla(db: Session, tenant: Tenant):
    f1 = _funil(db, tenant.id, "Boas-vindas")
    f2 = _funil(db, tenant.id, "Recuperação")
    admin.configurar(db, tenant_id=tenant.id, produto="publia", funis={"lead": f1.id})
    resultado = admin.configurar(
        db, tenant_id=tenant.id, produto=None, funis={"carrinho_abandonado": f2.id}
    )
    assert resultado == {
        "produto": "publia", "funis": {"lead": f1.id, "carrinho_abandonado": f2.id},
    }
    assert settings_service.get_profile(db, tenant.id).lead_ingest_config == resultado


def test_configurar_com_funil_vazio_remove_o_mapeamento(db: Session, tenant: Tenant):
    f1 = _funil(db, tenant.id, "Boas-vindas")
    admin.configurar(db, tenant_id=tenant.id, produto="publia", funis={"lead": f1.id})
    resultado = admin.configurar(db, tenant_id=tenant.id, produto=None, funis={"lead": ""})
    assert resultado == {"produto": "publia", "funis": {}}


def test_configurar_recusa_funil_inexistente_sem_alterar_a_configuracao(
    db: Session, tenant: Tenant
):
    f1 = _funil(db, tenant.id, "Boas-vindas")
    f2 = _funil(db, tenant.id, "Recuperação")
    anterior = admin.configurar(db, tenant_id=tenant.id, produto="publia", funis={"lead": f1.id})
    with pytest.raises(admin.AdminError, match="Funil não encontrado"):
        admin.configurar(
            db, tenant_id=tenant.id, produto="outro",
            funis={"carrinho_abandonado": f2.id, "compra_aprovada": "nao-existe"},
        )
    db.expire_all()
    assert settings_service.get_profile(db, tenant.id).lead_ingest_config == anterior


def test_configurar_recusa_produto_invalido(db: Session, tenant: Tenant):
    with pytest.raises(admin.AdminError):
        admin.configurar(db, tenant_id=tenant.id, produto="Publ.IA", funis={})


def test_main_emitir_token_imprime_o_cru_uma_vez(db, tenant, mesma_sessao, capsys):
    assert admin.main(["emitir-token", "--tenant", "nexus", "--nome", "site"]) == 0
    raw = capsys.readouterr().out.strip().splitlines()[-1]
    assert machine_tokens_service.resolve(db, raw=raw, scope=SCOPE_LEAD_INGEST).tenant_id == (
        tenant.id
    )


def test_main_com_slug_errado_sai_com_2(db, tenant, mesma_sessao, capsys):
    assert admin.main(["configurar", "--tenant", "nao-existe", "--produto", "publia"]) == 2
    assert "Tenant não encontrado" in capsys.readouterr().err


def test_main_configurar_e_mostrar(db, tenant, mesma_sessao, capsys):
    f1 = _funil(db, tenant.id, "Boas-vindas")
    argv = ["configurar", "--tenant", "nexus", "--produto", "publia", "--funil", f"lead={f1.id}"]
    assert admin.main(argv) == 0
    capsys.readouterr()
    assert admin.main(["mostrar", "--tenant", "nexus"]) == 0
    assert json.loads(capsys.readouterr().out) == {"produto": "publia", "funis": {"lead": f1.id}}


def test_main_listar_e_revogar(db, tenant, mesma_sessao, capsys):
    token, raw = admin.emitir_token(db, slug="nexus", nome="site")
    assert admin.main(["listar-tokens", "--tenant", "nexus"]) == 0
    assert token.id in capsys.readouterr().out
    assert admin.main(["revogar-token", "--id", token.id]) == 0
    with pytest.raises(machine_tokens_service.MachineTokenError):
        machine_tokens_service.resolve(db, raw=raw, scope=SCOPE_LEAD_INGEST)


class _Espiao:
    """Delega à sessão real e registra quais modelos foram buscados com `get`."""

    def __init__(self, db: Session, rotulo: str, registro: list):
        self._db, self._rotulo, self._registro = db, rotulo, registro

    def get(self, modelo, *args, **kwargs):
        self._registro.append((self._rotulo, modelo))
        return self._db.get(modelo, *args, **kwargs)

    def __getattr__(self, nome):
        return getattr(self._db, nome)


@pytest.mark.parametrize("comando", ["configurar", "mostrar"])
def test_main_roda_na_sessao_do_tenant_do_slug(db, tenant, monkeypatch, capsys, comando):
    f1 = _funil(db, tenant.id, "Boas-vindas")
    registro: list = []
    abertas: list = []

    @contextmanager
    def _global():
        yield _Espiao(db, "global", registro)

    @contextmanager
    def _tenant(tenant_id):
        abertas.append(tenant_id)
        yield _Espiao(db, "tenant", registro)

    monkeypatch.setattr(admin, "_sessao_global", _global)
    monkeypatch.setattr(admin, "tenant_session", _tenant)
    argv = [comando, "--tenant", "nexus"]
    if comando == "configurar":
        argv += ["--produto", "publia", "--funil", f"lead={f1.id}"]

    assert admin.main(argv) == 0
    assert abertas == [tenant.id]
    if comando == "configurar":
        assert ("tenant", Funnel) in registro
        assert ("global", Funnel) not in registro
