"""O filtro decide quais REGRAS rodam, não quais resultados aparecem."""
from app.core.tenancy import CurrentUser
from app.modules.vima.permissions import modulos_permitidos, pode_ver


def _usuario(role: str, modulos: list[str]) -> CurrentUser:
    return CurrentUser(
        user_id="u1", tenant_id="t1", role=role,
        allowed_modules=modulos, is_platform_admin=False,
    )


def test_owner_ve_tudo():
    assert modulos_permitidos(_usuario("owner", [])) is None
    assert pode_ver(_usuario("owner", []), "financeiro") is True


def test_lista_vazia_em_sub_usuario_tambem_e_tudo():
    """`allowed_modules=[]` significa 'sem restrição' em `require_module`. Mesmo sentido aqui —
    divergir criaria dois significados para o mesmo dado."""
    assert modulos_permitidos(_usuario("sub_user", [])) is None


def test_sub_usuario_so_de_crm_nao_ve_financeiro():
    u = _usuario("sub_user", ["crm", "comercial"])
    assert modulos_permitidos(u) == {"crm", "comercial"}
    assert pode_ver(u, "financeiro") is False
    assert pode_ver(u, "crm") is True
