"""Regras do Super Admin: gestão de contas (tenant + owner) por todo o sistema.

As tabelas `tenants`/`users` são GLOBAIS (sem RLS) — o Master as consulta diretamente.
Para EXCLUIR uma conta, purgamos os dados de negócio (com RLS, por tenant) e depois removemos
as linhas globais.
"""
from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import audit
from app.core.security import hash_password
from app.core.tenancy import CurrentUser
from app.db.base import TenantMixin
from app.db.registry import Base  # importa todos os modelos -> registra as tabelas
from app.db.session import tenant_session
from app.modules.auth.models import Tenant, User
from app.modules.auth.service import AuthError
from app.modules.platform.schemas import (
    CreateAccountRequest,
    CreateStaffRequest,
    UpdateAccountRequest,
    UpdateUserRequest,
)


def _business_table_names() -> set[str]:
    """Tabelas de NEGÓCIO (subclasses de TenantMixin), descobertas dinamicamente.

    Assim, qualquer módulo futuro com dados por tenant é purgado automaticamente na exclusão
    de conta — sem precisar lembrar de editar uma lista hardcoded.
    """
    return {
        mapper.class_.__tablename__
        for mapper in Base.registry.mappers
        if issubclass(mapper.class_, TenantMixin)
    }


def _has_platform_admin(db: Session, tenant_id: str) -> bool:
    return (
        db.scalar(
            select(User.id).where(
                User.tenant_id == tenant_id, User.is_platform_admin.is_(True)
            )
        )
        is not None
    )


class PlatformError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _owner_of(db: Session, tenant_id: str) -> User | None:
    return db.scalar(
        select(User).where(User.tenant_id == tenant_id, User.role == "owner")
    )


def list_accounts(db: Session) -> list[tuple[Tenant, User | None]]:
    """Todas as contas reais (exclui o tenant interno da plataforma)."""
    tenants = list(db.scalars(select(Tenant).order_by(Tenant.created_at.desc())).all())
    out: list[tuple[Tenant, User | None]] = []
    for t in tenants:
        owner = _owner_of(db, t.id)
        # pula contas de plataforma (admins)
        if owner and owner.is_platform_admin:
            continue
        out.append((t, owner))
    return out


def create_account(db: Session, data: CreateAccountRequest) -> tuple[Tenant, User, str, str]:
    """Cria escritório + dono via CONVITE: gera senha temporária, marca troca no 1º acesso e a
    envia por e-mail/WhatsApp. Devolve (tenant, dono, senha_temporária, status_do_envio)."""
    email = str(data.email).lower()
    if db.scalar(select(Tenant).where(Tenant.slug == data.slug)):
        raise AuthError("Este subdomínio já está em uso", 409)
    if db.scalar(select(User).where(User.email == email)):
        raise AuthError("Este e-mail já está cadastrado", 409)

    temp = _temp_password()
    tenant = Tenant(slug=data.slug, legal_name=data.legal_name, document=data.document)
    db.add(tenant)
    db.flush()
    owner = User(
        tenant_id=tenant.id,
        email=email,
        name=data.name,
        password_hash=hash_password(temp),
        role="owner",
        allowed_modules=[],
        document=data.document,
        address=data.address,
        phone=data.phone,
        must_reset_password=True,
    )
    db.add(owner)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise AuthError("Subdomínio ou e-mail já cadastrado", 409) from e
    db.refresh(tenant)
    db.refresh(owner)
    status = _send_invite(
        name=data.name, email=email, phone=data.phone, temp=temp,
        delivery=data.delivery, company=tenant.legal_name,
    )
    return tenant, owner, temp, status


def get_user(db: Session, user_id: str) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise PlatformError("Usuário não encontrado", 404)
    return user


def update_account(db: Session, user_id: str, data: UpdateAccountRequest) -> User:
    user = get_user(db, user_id)
    if user.is_platform_admin:
        raise PlatformError("Não é possível editar o administrador da plataforma por aqui", 400)
    if data.name is not None:
        user.name = data.name
    if data.is_active is not None:
        user.is_active = data.is_active
    db.commit()
    db.refresh(user)
    return user


def delete_account(db: Session, tenant_id: str, actor: CurrentUser) -> None:
    """Exclui a conta de forma ATÔMICA: purga dados de negócio + remove tenant e usuários,
    tudo numa única transação. Bloqueia se houver qualquer administrador no tenant.

    Ao final, grava um log de PLATAFORMA (fora do tenant) da exclusão — sobrevive à purga e
    cumpre a exigência de rastro da LGPD (AC2). `actor` é o Master que executou a operação.
    """
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise PlatformError("Conta não encontrada", 404)
    if _has_platform_admin(db, tenant_id):
        raise PlatformError("Não é possível excluir uma conta de administrador", 400)

    # Snapshot ANTES da purga: depois do `DELETE FROM tenants` o slug some, e o log de
    # plataforma precisa ser autossuficiente (sem FK/join para uma linha que deixará de existir).
    # O ator (Master) vive em OUTRO tenant, então sua linha sobrevive; ainda assim capturamos o
    # e-mail aqui para deixar o log completo num único snapshot.
    target_tenant_slug = tenant.slug
    actor_row = db.get(User, actor.user_id)
    actor_email = actor_row.email if actor_row is not None else ""

    biz = _business_table_names()
    # Uma só transação (tenant_session commita ao sair) => sem estado órfão em falha parcial.
    # Os nomes de tabela vêm do nosso metadata (não de input), então o DELETE é seguro.
    # WHERE tenant_id explícito = defesa-em-profundidade nesta operação destrutiva (além da RLS).
    with tenant_session(tenant_id) as tdb:
        for table in reversed(Base.metadata.sorted_tables):  # ordem FK-segura p/ delete
            if table.name in biz:
                # table.name vem do nosso metadata (não de input) e está em `biz` — seguro.
                tdb.execute(
                    text(f"DELETE FROM {table.name} WHERE tenant_id = :tid"),  # noqa: S608
                    {"tid": tenant_id},
                )
        tdb.execute(text("DELETE FROM users WHERE tenant_id = :tid"), {"tid": tenant_id})
        tdb.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tenant_id})

    # A purga (bloco acima) já commitou com sucesso ao sair do `with` sem exceção. Só então
    # gravamos o log na sessão GLOBAL `db` — NUNCA na `tenant_session` do tenant que acabou de
    # sumir (seria uma escrita com RLS de um tenant inexistente, e é logicamente "fora do tenant").
    # [AUTO-DECISION / Story Task 4] Logamos a exclusão que DE FATO ocorreu (após a purga). A
    # atomicidade cross-sessão não é garantida entre os dois commits: uma falha rara entre eles
    # deixaria a conta apagada sem log. É escolha consciente — logar uma exclusão que falhou no
    # meio seria pior para auditoria/LGPD do que o risco raro de perder o log de uma que ocorreu.
    audit.record_platform(
        db,
        actor_user_id=actor.user_id,
        actor_email=actor_email,
        target_tenant_id=tenant_id,
        target_tenant_slug=target_tenant_slug,
        action="account_deleted",
    )
    db.commit()


# ── Hierarquia de usuários: Super Admin vê/edita/exclui todos ────────────────
def _customers_of(db: Session, tenant_id: str) -> list[dict]:
    """Clientes compradores de um escritório, vindos das matrículas (Enrollment), deduplicados.

    Hoje o comprador vive em Enrollment (não é um User de login). Agregamos por e-mail (ou nome,
    quando não há e-mail) e contamos quantas compras cada um fez.
    """
    from app.modules.products.models import Enrollment

    rows = db.scalars(
        select(Enrollment).where(Enrollment.tenant_id == tenant_id)
    ).all()
    by_key: dict[str, dict] = {}
    for e in rows:
        key = (e.email or e.name or "").strip().lower()
        if not key:
            continue
        if key in by_key:
            by_key[key]["purchases"] += 1
        else:
            by_key[key] = {"name": e.name, "email": e.email, "purchases": 1}
    return sorted(by_key.values(), key=lambda c: c["name"].lower())


def list_tenant_users(db: Session) -> list[dict]:
    """Hierarquia completa: cada escritório (Admin) com seus funcionários e clientes.

    Exclui as contas internas da plataforma (Master). Estrutura espelha o que o Super Admin vê:
    escritório → Admin (dono) → funcionários (sub_user) + clientes (compradores).
    """
    tenants = list(db.scalars(select(Tenant).order_by(Tenant.created_at.desc())).all())
    out: list[dict] = []
    for t in tenants:
        users = list(db.scalars(select(User).where(User.tenant_id == t.id)).all())
        admin = next((u for u in users if u.role == "owner"), None)
        if admin and admin.is_platform_admin:
            continue  # conta interna da plataforma, não aparece na lista
        staff = [u for u in users if u.role != "owner" and not u.is_platform_admin]
        customers = _customers_of(db, t.id)
        out.append({
            "tenant": t,
            "admin": admin,
            "staff": staff,
            "customers": customers,
            "staff_count": len(staff),
            "customer_count": len(customers),
        })
    return out


def list_customers(db: Session) -> list[dict]:
    """Todos os clientes compradores da plataforma (visão do Master), com o escritório de origem."""
    tenants = list(db.scalars(select(Tenant).order_by(Tenant.legal_name)).all())
    out: list[dict] = []
    for t in tenants:
        owner = _owner_of(db, t.id)
        if owner and owner.is_platform_admin:
            continue
        for c in _customers_of(db, t.id):
            out.append({**c, "tenant_id": t.id, "tenant_name": t.legal_name})
    return out


def _temp_password() -> str:
    """Senha temporária legível (~12 chars). O usuário a troca no 1º acesso."""
    import secrets

    return secrets.token_urlsafe(9)


def _send_invite(
    *, name: str, email: str, phone: str, temp: str, delivery: str, company: str
) -> str:
    """Entrega a senha temporária por e-mail ou WhatsApp. Devolve o status do envio."""
    from app.core import whatsapp
    from app.core.email import send_email

    msg = (
        f"Olá, {name}! Seu acesso à plataforma ({company}) foi criado.\n"
        f"Login (e-mail): {email}\n"
        f"Senha temporária: {temp}\n\n"
        "Por segurança, você deverá definir uma nova senha no primeiro acesso."
    )
    if delivery == "whatsapp":
        return whatsapp.send_text(to=phone, text=msg)
    return send_email(to=email, subject="Seu acesso à plataforma", body=msg)


def create_staff(db: Session, tenant_id: str, data: CreateStaffRequest) -> tuple[User, str, str]:
    """Cria um funcionário (sub_user) com cadastro completo, gera senha temporária e a envia
    por e-mail/WhatsApp. Devolve (usuário, senha_temporária, status_do_envio). E-mail é único."""
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise PlatformError("Conta não encontrada", 404)
    email = str(data.email).lower()
    if db.scalar(select(User).where(User.email == email)):
        raise AuthError("Este e-mail já está cadastrado", 409)

    temp = _temp_password()
    user = User(
        tenant_id=tenant_id,
        email=email,
        name=data.name,
        password_hash=hash_password(temp),
        role="sub_user",
        allowed_modules=data.allowed_modules,
        document=data.document,
        address=data.address,
        phone=data.phone,
        must_reset_password=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    status = _send_invite(
        name=data.name, email=email, phone=data.phone, temp=temp,
        delivery=data.delivery, company=tenant.legal_name,
    )
    return user, temp, status


def update_user(db: Session, user_id: str, data: UpdateUserRequest) -> User:
    user = get_user(db, user_id)
    if user.is_platform_admin:
        raise PlatformError("Não é possível editar o administrador da plataforma por aqui", 400)
    if data.name is not None:
        user.name = data.name
    if data.is_active is not None:
        user.is_active = data.is_active
    if data.allowed_modules is not None:
        user.allowed_modules = data.allowed_modules
    db.commit()
    db.refresh(user)
    return user


def delete_user(db: Session, user_id: str) -> None:
    """Exclui UM usuário. O dono (owner) só sai junto com a conta inteira (delete_account)."""
    user = get_user(db, user_id)
    if user.is_platform_admin:
        raise PlatformError("Não é possível excluir o administrador da plataforma", 400)
    if user.role == "owner":
        raise PlatformError(
            "Este é o dono da conta — exclua a conta inteira para removê-lo", 400
        )
    db.delete(user)
    db.commit()
