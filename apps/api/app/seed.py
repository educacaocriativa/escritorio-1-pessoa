"""Semeia o Super Admin (Master) no primeiro start. Idempotente.

Cria um tenant interno "platform" + um usuário is_platform_admin com as credenciais do .env.
Rode após as migrations: `python -m app.seed`.
"""
from __future__ import annotations

from sqlalchemy import select

from app.config import settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.modules.auth.models import Tenant, User

PLATFORM_SLUG = "platform"


def seed_super_admin() -> None:
    db = SessionLocal()
    try:
        existing = db.scalar(select(User).where(User.is_platform_admin.is_(True)))
        if existing:
            print(f"[seed] Super admin já existe ({existing.email}).")
            return

        tenant = db.scalar(select(Tenant).where(Tenant.slug == PLATFORM_SLUG))
        if tenant is None:
            tenant = Tenant(slug=PLATFORM_SLUG, legal_name="Plataforma e1p", document="00000000000")
            db.add(tenant)
            db.flush()

        admin = User(
            tenant_id=tenant.id,
            email=settings.super_admin_email.lower(),
            name=settings.super_admin_name,
            password_hash=hash_password(settings.super_admin_password),
            role="owner",
            allowed_modules=[],
            is_active=True,
            is_platform_admin=True,
        )
        db.add(admin)
        db.commit()
        print(f"[seed] Super admin criado: {admin.email}")
    finally:
        db.close()


if __name__ == "__main__":
    seed_super_admin()
